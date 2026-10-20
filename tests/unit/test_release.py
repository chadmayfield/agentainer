"""Run the release shell with registry, signing and git commands replaced by stubs."""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "ghcr.io/chadmayfield/agentainer"


class ReleaseTests(unittest.TestCase):
    def run_release(self, candidate, versions, **extra):
        with tempfile.TemporaryDirectory(prefix="cx-release-") as d:
            t = Path(d)
            (t / "digests").mkdir()
            for arch in ("amd64", "arm64"):
                (t / "digests" / arch).write_text("sha256:" + "a" * 64 + "\n")
            artifact_case = extra.pop("CX_ARTIFACT_CASE", "")
            if artifact_case == "missing":
                (t / "digests/arm64").unlink()
            elif artifact_case == "malformed":
                (t / "digests/arm64").write_text("not-a-digest")
            elif artifact_case == "extra":
                (t / "digests/unexpected").write_text("extra")
            manifest = json.dumps({"schemaVersion": 2, "annotations": {
                "org.opencontainers.image.description":
                    "Claude Code, Codex, Antigravity CLI and OpenCode in one container"}})
            digest = "sha256:" + hashlib.sha256(manifest.encode()).hexdigest()
            bindir = t / "bin"
            bindir.mkdir()
            stub = "#!" + sys.executable + "\n" + """import json,os,sys
cmd = os.path.basename(sys.argv[0])
a = sys.argv[1:]
with open(os.environ['CX_LOG'], 'a') as f:
    f.write(json.dumps([cmd] + a) + '\\n')
if cmd == 'python3':
    if a[0].endswith('/tests/host/test-published-image.py'):
        sys.exit(int(os.environ.get('CX_VERIFY_RC', '0')))
    os.execv(os.environ['CX_REAL_PYTHON'], ['python3'] + a)
if cmd == 'cosign':
    sys.exit(int(os.environ.get('CX_SIGN_RC', '0')))
if cmd == 'git':
    if a[0] == 'fetch':
        sys.exit(int(os.environ.get('CX_FETCH_RC', '0')))
    if a[0] == 'log':
        print(os.environ['CX_HISTORY'])
    sys.exit(0)
stage = ('dry-run' if '--dry-run' in a else
         'retag' if 'create' in a and any(':latest' in x for x in a) else
         'create-sha' if 'create' in a else 'inspect')
if stage == os.environ.get('CX_DOCKER_FAIL'):
    sys.exit(9)
if '--raw' in a:
    doc = json.loads(os.environ['CX_MANIFEST'])
    if os.environ.get('CX_BAD_ANNOTATION'):
        doc['annotations'] = {}
    print(json.dumps(doc))
elif 'inspect' in a:
    print(json.dumps({'digest': 'sha256:' + 'c' * 64 if os.environ.get('CX_BAD_POST') and any(x.endswith(':latest') or x.endswith(':' + os.environ['V']) for x in a) else os.environ['CX_DIGEST']}))
elif '--dry-run' in a:
    print('{}' if os.environ.get('CX_BAD_DRY') else os.environ['CX_MANIFEST'])
"""
            for cmd in ("docker", "cosign", "git", "python3"):
                path = bindir / cmd
                path.write_text(stub)
                path.chmod(0o755)
            script = ROOT / "scripts/release-image.sh"
            env = dict(os.environ, V=candidate, SHA="b" * 40, OWNER="example", REPOSITORY="example/agentainer", CX_LOG=str(t / "log"),
                       CX_REAL_PYTHON=sys.executable, PATH=str(bindir) + ":" + os.environ["PATH"], CX_MANIFEST=manifest, CX_DIGEST=digest,
                       CX_HISTORY="\n".join("Merge pull request #1 from example/release/" + v for v in versions),
                       **extra)
            result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
                                    cwd=t, env=env, capture_output=True, text=True)
            calls = [json.loads(s) for s in (t / "log").read_text().splitlines()] if (t / "log").exists() else []
            self.last_calls = calls
            tags = [c[i + 1] for c in calls if c[:4] == ["docker", "buildx", "imagetools", "create"]
                    for i, arg in enumerate(c) if arg == "-t"]
            return result, tags

    def test_older_release_keeps_its_version_tag_without_moving_latest(self):
        r, tags = self.run_release("2026.10.19", ["2026.10.20", "2026.10.19"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(IMAGE + ":2026.10.19", tags)
        self.assertNotIn(IMAGE + ":latest", tags)

    def test_same_day_suffixes_are_compared_as_numbers(self):
        r, tags = self.run_release("2026.10.19.2", ["2026.10.19.10", "2026.10.19.2"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(IMAGE + ":latest", tags)

    def test_newest_release_and_its_retry_can_move_latest(self):
        r, tags = self.run_release("2026.10.19.10", ["2026.10.19.10", "2026.10.19.2", "2026.10.19"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(IMAGE + ":latest", tags)

    def test_first_release_can_move_latest(self):
        r, tags = self.run_release("2026.10.19", ["2026.10.19"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(IMAGE + ":latest", tags)

    def test_failed_history_refresh_cannot_move_latest(self):
        r, tags = self.run_release("2026.10.19", ["2026.10.19"], CX_FETCH_RC="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(IMAGE + ":latest", tags)

    def test_missing_release_history_cannot_move_latest(self):
        r, tags = self.run_release("2026.10.19", [])
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(IMAGE + ":latest", tags)

    def test_signing_failure_cannot_move_public_tags(self):
        r, tags = self.run_release("2026.10.19", ["2026.10.19"], CX_SIGN_RC="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(IMAGE + ":latest", tags)
        self.assertNotIn(IMAGE + ":2026.10.19", tags)

    def test_dry_run_digest_mismatch_cannot_move_public_tags(self):
        r, tags = self.run_release("2026.10.19", ["2026.10.19"], CX_BAD_DRY="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(IMAGE + ":latest", tags)
        self.assertNotIn(IMAGE + ":2026.10.19", tags)

    def test_invalid_historical_release_names_do_not_block_a_valid_release(self):
        for old in ("2026.02.30", "1.0.0", "2026.13.01", "2026.10.19.0"):
            with self.subTest(old=old):
                r, tags = self.run_release("2026.10.19", ["2026.10.19", old])
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(IMAGE + ":2026.10.19", tags)
                self.assertIn(IMAGE + ":latest", tags)

    def test_invalid_candidate_still_cannot_publish_public_tags(self):
        for candidate in ("2026.02.30", "1.0.0"):
            with self.subTest(candidate=candidate):
                r, tags = self.run_release(candidate, [candidate])
                self.assertNotEqual(r.returncode, 0)
                self.assertNotIn(IMAGE + ":" + candidate, tags)
                self.assertNotIn(IMAGE + ":latest", tags)

    def test_bad_digest_artifacts_stop_before_registry_or_signing_calls(self):
        for case in ("missing", "malformed", "extra"):
            with self.subTest(case=case):
                r, tags = self.run_release("2026.10.19", ["2026.10.19"], CX_ARTIFACT_CASE=case)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(tags, [])
                self.assertEqual(self.last_calls, [])

    def test_wrong_annotations_cannot_move_public_tags(self):
        r, tags = self.run_release("2026.10.19", ["2026.10.19"], CX_BAD_ANNOTATION="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(tags, [IMAGE + ":sha-" + "b" * 7])
        self.assertFalse(any(c[0] == "cosign" for c in self.last_calls))

    def test_registry_command_failures_stop_the_release(self):
        for stage in ("create-sha", "inspect", "dry-run", "retag"):
            with self.subTest(stage=stage):
                r, _ = self.run_release("2026.10.19", ["2026.10.19"], CX_DOCKER_FAIL=stage)
                self.assertNotEqual(r.returncode, 0)
                if stage != "retag":
                    self.assertFalse(any(IMAGE + ":latest" in c for c in self.last_calls))

    def test_a_wrong_digest_after_retagging_fails(self):
        r, tags = self.run_release("2026.10.19", ["2026.10.19"], CX_BAD_POST="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(IMAGE + ":latest", tags)
        self.assertIn("points at sha256:" + "c" * 64, r.stderr)

    def test_success_signs_recursively_and_checks_dry_run_before_public_tags(self):
        r, _ = self.run_release("2026.10.19", ["2026.10.19"])
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.last_calls
        signing = next(i for i, c in enumerate(calls) if c[0] == "cosign")
        dry_run = next(i for i, c in enumerate(calls) if "--dry-run" in c)
        retag = next(i for i, c in enumerate(calls) if IMAGE + ":latest" in c and "create" in c)
        self.assertIn("--recursive", calls[signing])
        self.assertIn("@sha256:", calls[signing][-1])
        self.assertLess(signing, dry_run)
        self.assertLess(dry_run, retag)

    def test_failed_live_verification_cannot_move_public_tags(self):
        r, tags = self.run_release("2026.10.19", ["2026.10.19"], CX_VERIFY_RC="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(tags, [IMAGE + ":sha-" + "b" * 7])
        self.assertTrue(any(c[0] == "python3" and c[1].endswith("/test-published-image.py")
                            for c in self.last_calls))

    def test_live_verification_uses_signed_digest_before_public_tags(self):
        r, _ = self.run_release("2026.10.19", ["2026.10.19"])
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.last_calls
        signing = next(i for i, c in enumerate(calls) if c[0] == "cosign")
        verification = next(i for i, c in enumerate(calls)
                            if c[0] == "python3" and c[1].endswith("/test-published-image.py"))
        retag = next(i for i, c in enumerate(calls) if IMAGE + ":latest" in c and "create" in c)
        self.assertEqual(calls[verification][2], IMAGE)
        self.assertEqual(IMAGE + "@" + calls[verification][3], calls[signing][-1])
        self.assertEqual(calls[verification][4:], [
            "https://github.com/example/agentainer/.github/workflows/build.yml@refs/heads/main",
            "https://token.actions.githubusercontent.com"])
        self.assertLess(signing, verification)
        self.assertLess(verification, retag)

    def test_release_version_waits_for_aggregate_ci(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        version = workflow.split("\n  version:\n", 1)[1].split("\n  publish:\n", 1)[0]
        needs = re.search(r"^    needs: (.+)$", version, re.M).group(1)
        self.assertIn("ci", re.findall(r"[a-z][a-z-]*", needs))
