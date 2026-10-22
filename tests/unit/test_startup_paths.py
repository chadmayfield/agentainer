"""Exercise entrypoint path conflicts in a temporary container home."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("flock"), "startup path tests require Linux flock")
class StartupPathsTests(unittest.TestCase):
    def test_blocked_agents_ledger_warns_without_stopping_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentainer/agents-default.sha256").mkdir(parents=True)
            image = home / "image"
            image.mkdir()
            (image / "AGENTS.md").write_text("default\n")
            source = (ROOT / "rootfs/usr/local/lib/agentainer/entrypoint.d/30-agents-md.sh").read_text()
            step = home / "step.sh"
            step.write_text(source.replace("/etc/agentainer", str(image)))
            shell = 'warn() { echo "$*"; }; log() { echo "$*"; }; seed_file() { :; }; . "$1"'
            result = subprocess.run(["sh", "-ec", shell, "sh", str(step)],
                                    env=dict(os.environ, HOME=str(home)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("cannot record", result.stdout)

    def test_dangling_service_link_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentainer").mkdir()
            config = home / ".config/opencode/service.json"
            config.parent.mkdir(parents=True)
            config.symlink_to("missing-target")
            bindir = home / "bin"
            bindir.mkdir()
            command = bindir / "opencode"
            command.write_text('#!/bin/sh\nrm -f "$HOME/.config/opencode/service.json"\nprintf replaced >"$HOME/.config/opencode/service.json"\n')
            command.chmod(0o755)
            result = subprocess.run(["sh", "-ec", 'warn() { echo "$*"; }; . "$1"', "sh",
                                     str(ROOT / "rootfs/usr/local/lib/agentainer/entrypoint.d/70-opencode.sh")],
                                    env=dict(os.environ, HOME=str(home), PATH=str(bindir) + ":" + os.environ["PATH"]),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(config.is_symlink())

    def test_unwritable_seed_lock_warns_and_skips_seeding(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentainer/.seed.lock").mkdir(parents=True)
            result = subprocess.run(["sh", "-ec", 'warn() { echo "$*"; }; . "$1"', "sh",
                                     str(ROOT / "rootfs/usr/local/lib/agentainer/entrypoint.d/20-seed.sh")],
                                    env=dict(os.environ, HOME=str(home)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("seed lock", result.stdout)
