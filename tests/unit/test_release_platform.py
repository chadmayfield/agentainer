"""Reject published platform images that cannot start or identify the release."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReleasePlatformTests(unittest.TestCase):
    def check(self, arch="amd64", **overrides):
        with tempfile.TemporaryDirectory(prefix="cx-release-platform-") as directory:
            base = Path(directory)
            engine = base / "engine"
            engine.write_text("#!" + sys.executable + "\n" + '''import os,sys,json
a=sys.argv[1:]
with open(os.environ['CX_LOG'],'a') as f:f.write(json.dumps(a)+'\\n')
if a[:2]==['image','inspect']: print(os.environ['CX_METADATA'])
if a[0]=='run': sys.exit(int(os.environ.get('CX_RUN_RC','0')))
''')
            engine.chmod(0o755)
            uname = base / "uname"
            uname.write_text('#!/bin/sh\nprintf "%s\\n" "$CX_MACHINE"\n')
            uname.chmod(0o755)
            env = dict(os.environ, PATH=str(base) + ":" + os.environ["PATH"], RUNTIME=str(engine),
                       CX_LOG=str(base / "calls"), CX_MACHINE="x86_64" if arch == "amd64" else "aarch64",
                       CX_METADATA=arch + "|" + "a" * 40 + "|0.1.0")
            env.update(overrides)
            ref = "registry.example.com/agentainer@sha256:" + "b" * 64
            result = subprocess.run(["sh", str(ROOT / "scripts/check-release-platform.sh"),
                                     ref, arch, "a" * 40, "0.1.0"], env=env,
                                    capture_output=True, text=True)
            calls = [json.loads(line) for line in (base / "calls").read_text().splitlines()] if (base / "calls").exists() else []
            return result, calls, ref

    def test_both_architectures_pull_and_run_the_exact_pushed_digest(self):
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch):
                result, calls, ref = self.check(arch)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls[0], ["pull", "--platform", "linux/" + arch, ref])
                run = next(c for c in calls if c[0] == "run")
                self.assertIn(ref, run)
                self.assertEqual(run[run.index("--network") + 1], "none")
                for tool in ("claude", "codex", "agy", "opencode"):
                    self.assertIn(tool + " --version", run[-1])

    def test_failed_startup_fails_the_platform_gate(self):
        result, _, _ = self.check(CX_RUN_RC="42")
        self.assertNotEqual(result.returncode, 0)

    def test_wrong_architecture_revision_or_version_never_runs(self):
        for metadata in ("arm64|" + "a" * 40 + "|0.1.0",
                         "amd64|" + "c" * 40 + "|0.1.0",
                         "amd64|" + "a" * 40 + "|dev"):
            with self.subTest(metadata=metadata):
                result, calls, _ = self.check(CX_METADATA=metadata)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c[0] == "run" for c in calls))

    def test_wrong_native_runner_is_rejected_before_pull(self):
        result, calls, _ = self.check(CX_MACHINE="aarch64")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_workflow_checks_pushed_platform_before_recording_its_digest(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text().split("\n  publish:\n", 1)[1].split("\n  release:\n", 1)[0]
        check = workflow.index("run: sh scripts/check-release-platform.sh")
        record = workflow.index("- name: Record the digest")
        self.assertLess(check, record)
        self.assertIn("${{ steps.build.outputs.digest }}", workflow[:record])
        self.assertNotIn("continue-on-error", workflow[check:record])
