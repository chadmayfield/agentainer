"""Run the release shell with registry, signing and git commands replaced by stubs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
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
            manifest = json.dumps({"schemaVersion": 2, "annotations": {
                "org.opencontainers.image.description":
                    "Claude Code, Codex, Antigravity CLI and OpenCode in one container"}})
            digest = "sha256:" + hashlib.sha256(manifest.encode()).hexdigest()
            bindir = t / "bin"
            bindir.mkdir()
            stub = """#!/usr/bin/env python3
import json,os,sys
cmd = os.path.basename(sys.argv[0])
a = sys.argv[1:]
with open(os.environ['CX_LOG'], 'a') as f:
    f.write(json.dumps([cmd] + a) + '\\n')
if cmd == 'cosign':
    sys.exit(int(os.environ.get('CX_SIGN_RC', '0')))
if cmd == 'git':
    if a[0] == 'fetch':
        sys.exit(int(os.environ.get('CX_FETCH_RC', '0')))
    if a[0] == 'log':
        print(os.environ['CX_HISTORY'])
    sys.exit(0)
if '--raw' in a:
    print(os.environ['CX_MANIFEST'])
elif 'inspect' in a:
    print(json.dumps({'digest': os.environ['CX_DIGEST']}))
elif '--dry-run' in a:
    print('{}' if os.environ.get('CX_BAD_DRY') else os.environ['CX_MANIFEST'])
"""
            for cmd in ("docker", "cosign", "git"):
                path = bindir / cmd
                path.write_text(stub)
                path.chmod(0o755)
            script = ROOT / "scripts/release-image.sh"
            env = dict(os.environ, V=candidate, SHA="b" * 40, OWNER="example", CX_LOG=str(t / "log"),
                       PATH=str(bindir) + ":" + os.environ["PATH"], CX_MANIFEST=manifest, CX_DIGEST=digest,
                       CX_HISTORY="\n".join("Merge pull request #1 from example/release/" + v for v in versions),
                       **extra)
            result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
                                    cwd=t, env=env, capture_output=True, text=True)
            calls = [json.loads(s) for s in (t / "log").read_text().splitlines()]
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
