"""Execute the workflow's version and GitHub release shell with read-only stubs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]


def run_block(start, end=None):
    text = (ROOT / ".github/workflows/build.yml").read_text().split(start, 1)[1]
    if end:
        text = text.split(end, 1)[0]
    lines = text.split("        run: |\n", 1)[1].splitlines(keepends=True)
    body = []
    for line in lines:
        if line.strip() and not line.startswith("          "):
            break
        body.append(line)
    return textwrap.dedent("".join(body))


class WorkflowVersionTests(unittest.TestCase):
    def select(self, value, rejected=False):
        with tempfile.TemporaryDirectory(prefix="cx-workflow-version-") as d:
            root = Path(d)
            git = root / "git"
            git.write_text("#!/bin/sh\nexit 0\n")
            git.chmod(0o755)
            python = root / "python3"
            python.write_text("#!" + sys.executable + "\n" + '''import os,sys
if sys.argv[1].endswith('/check_release_tag.py'):
    if os.environ['CX_REJECTED'] == 'true': sys.exit(1)
    print(os.environ['CX_VERSION'])
else:
    os.execv(os.environ['CX_REAL_PYTHON'], [os.environ['CX_REAL_PYTHON']] + sys.argv[1:])
''')
            python.chmod(0o755)
            output = root / "output"
            script = run_block("      - id: ver\n", "\n  publish:")
            result = subprocess.run(["bash", "-eo", "pipefail", "-c", script], cwd=ROOT,
                                    env=dict(os.environ, PATH=str(root) + ":" + os.environ["PATH"],
                                             CX_VERSION=value, CX_REJECTED=str(rejected).lower(),
                                             CX_REAL_PYTHON=sys.executable, OWNER="example", SHA="a" * 40,
                                             GITHUB_OUTPUT=str(output)), capture_output=True, text=True)
            return result, output.read_text() if output.exists() else ""

    def test_verified_prerelease_and_stable_outputs(self):
        for value, prerelease in [("0.1.0-dev.20261019.1", "true"), ("0.1.0", "false")]:
            with self.subTest(value=value):
                result, output = self.select(value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, "version=%s\nprerelease=%s\n" % (value, prerelease))

    def test_failed_tag_guard_writes_no_version_outputs(self):
        result, output = self.select("0.1.0", rejected=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, "")

    def create(self, prerelease, latest):
        with tempfile.TemporaryDirectory(prefix="cx-workflow-release-") as d:
            root = Path(d)
            python = root / "python3"
            python.write_text("#!/bin/sh\nprintf 'summary\\n'\n")
            python.chmod(0o755)
            gh = root / "gh"
            gh.write_text("#!" + sys.executable + "\nimport json,os,sys\n"
                          "with open(os.environ['CX_LOG'], 'w') as f: json.dump(sys.argv[1:], f)\n")
            gh.chmod(0o755)
            log = root / "calls"
            result = subprocess.run(["bash", "-eo", "pipefail", "-c", run_block("      - name: Git tag and GitHub release\n")],
                                    cwd=ROOT, capture_output=True, text=True,
                                    env=dict(os.environ, PATH=str(root) + ":" + os.environ["PATH"],
                                             PRERELEASE=prerelease, MAKE_LATEST=latest,
                                             V="0.1.0-dev.20261019.1" if prerelease == "true" else "0.1.0",
                                             SHA="a" * 40, CX_LOG=str(log)))
            return result, json.loads(log.read_text()) if log.exists() else []

    def test_github_prerelease_is_explicitly_not_latest(self):
        result, args = self.create("true", "false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--prerelease", args)
        self.assertIn("--latest=false", args)
        self.assertEqual(args[2], "v0.1.0-dev.20261019.1")

    def test_stable_release_uses_same_latest_decision_as_registry(self):
        for latest in ("true", "false"):
            result, args = self.create("false", latest)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("--prerelease", args)
            self.assertIn("--latest=" + latest, args)

    def test_missing_or_conflicting_release_decision_cannot_call_github(self):
        for prerelease, latest in [("true", "true"), ("", "false"), ("false", "")]:
            result, args = self.create(prerelease, latest)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(args, [])

    def test_publishing_requires_a_tag_push_and_signed_tag_guard(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        self.assertIn('tags: ["v*"]', workflow)
        version_job = workflow.split("\n  version:\n", 1)[1].split("\n  publish:\n", 1)[0]
        self.assertIn("refs/tags/v", version_job)
        self.assertIn("scripts/check_release_tag.py", version_job)
        self.assertIn("ref: main", version_job, "candidate tags must not supply their own authorization code")

    def test_attestation_sits_between_signing_and_promotion(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        start = workflow.index("run: bash scripts/release-image.sh prepare")
        attest = workflow.index("uses: actions/attest@", start)
        promote = workflow.index("run: bash scripts/release-image.sh promote", attest)
        self.assertLess(start, attest)
        self.assertLess(attest, promote)
        block = workflow[attest:promote]
        self.assertIn("subject-digest: ${{ steps.prepare-index.outputs.digest }}", block)
        self.assertNotIn("if: always()", block)
        self.assertNotIn("continue-on-error", block)
        self.assertIn("--verify-tag", workflow)
        self.assertNotIn('--target "$SHA"', workflow)

    def test_publication_waits_for_environment_approval_after_signature_verification(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        approval = workflow.split("\n  authorize-release:\n", 1)[1].split("\n  publish:\n", 1)[0]
        self.assertIn("needs: version", approval)
        self.assertIn("environment: release", approval)
        self.assertIn("permissions: {}", approval)
        publish = workflow.split("\n  publish:\n", 1)[1].split("\n  release:\n", 1)[0]
        self.assertIn("needs: [version, authorize-release]", publish)
        self.assertNotIn("if: always()", publish)
        self.assertNotIn("continue-on-error", approval)
