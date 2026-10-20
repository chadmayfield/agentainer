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
    return textwrap.dedent(text.split("        run: |\n", 1)[1])


class WorkflowVersionTests(unittest.TestCase):
    def select(self, subject, existing=False):
        with tempfile.TemporaryDirectory(prefix="cx-workflow-version-") as d:
            root = Path(d)
            git = root / "git"
            git.write_text("#!" + sys.executable + "\n" + '''import os,sys
if sys.argv[1] == 'log':
    print(os.environ['CX_SUBJECT'])
else:
    sys.exit(int(os.environ['CX_TAG_STATUS']))
''')
            git.chmod(0o755)
            output = root / "output"
            script = run_block("      - id: ver\n", "\n  publish:")
            result = subprocess.run(["bash", "-eo", "pipefail", "-c", script], cwd=ROOT,
                                    env=dict(os.environ, PATH=str(root) + ":" + os.environ["PATH"],
                                             CX_SUBJECT=subject, CX_TAG_STATUS="0" if existing else "1",
                                             OWNER="example", SHA="a" * 40, GITHUB_OUTPUT=str(output)),
                                    capture_output=True, text=True)
            return result, output.read_text() if output.exists() else ""

    def test_requested_prerelease_and_stable_outputs(self):
        for value, prerelease in [("0.1.0-dev.20261019.1", "true"), ("0.1.0", "false")]:
            with self.subTest(value=value):
                result, output = self.select("Merge pull request #1 from example/release/" + value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, "version=%s\nprerelease=%s\n" % (value, prerelease))

    def test_wrong_owner_hotfix_malformed_date_and_existing_tag_fail_closed(self):
        subjects = ["Merge pull request #1 from other/release/0.1.0",
                    "Merge pull request #1 from example/hotfix/0.1.0",
                    "Merge pull request #1 from example/release/0.1.0-dev.20260230.1",
                    "Merge pull request #1 from example/release/0.1.0\nINJECTED=true"]
        for subject in subjects:
            with self.subTest(subject=subject):
                result, output = self.select(subject)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, "")
        result, output = self.select("Merge pull request #1 from example/release/0.1.0", existing=True)
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
