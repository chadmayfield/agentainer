"""Fault-inject seed copies without exposing an incomplete user config."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform.startswith("linux"), "seed publication uses Linux coreutils")
class SeedAtomicTests(unittest.TestCase):
    def test_partial_copy_is_not_published_and_can_be_retried(self):
        with tempfile.TemporaryDirectory(prefix="cx-seed-atomic-") as directory:
            base = Path(directory)
            source, destination = base / "source", base / "home/settings.json"
            source.write_text('{"complete": true}\n')
            source.chmod(0o640)
            script = base / "seed.sh"
            entry = (ROOT / "rootfs/usr/local/bin/agentainer-entrypoint").read_text()
            script.write_text(entry.split("# A one-shot command", 1)[0] + '\nseed_file "$1" "$2"\n')
            bindir = base / "bin"
            bindir.mkdir()
            copy = bindir / "cp"
            copy.write_text('#!/bin/sh\nprintf partial > "$2"\nexit 1\n')
            copy.chmod(0o755)
            env = dict(os.environ, PATH=str(bindir) + ":" + os.environ["PATH"])
            result = subprocess.run(["sh", str(script), str(source), str(destination)], env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(destination.exists(), "partial seed became the user-owned destination")
            self.assertEqual(list(destination.parent.iterdir()), [])
            copy.unlink()
            subprocess.run(["sh", str(script), str(source), str(destination)], env=env, check=True)
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertEqual(destination.stat().st_mode & 0o777, 0o640)
            destination.write_text("user configuration\n")
            subprocess.run(["sh", str(script), str(source), str(destination)], env=env, check=True)
            self.assertEqual(destination.read_text(), "user configuration\n")

    def test_user_file_created_during_copy_wins(self):
        with tempfile.TemporaryDirectory(prefix="cx-seed-race-") as directory:
            base = Path(directory)
            source, destination = base / "source", base / "destination"
            source.write_text("image default\n")
            script = base / "seed.sh"
            entry = (ROOT / "rootfs/usr/local/bin/agentainer-entrypoint").read_text()
            script.write_text(entry.split("# A one-shot command", 1)[0] + '\nseed_file "$1" "$2"\n')
            bindir = base / "bin"
            bindir.mkdir()
            copy = bindir / "cp"
            copy.write_text('#!/bin/sh\nprintf "user configuration\\n" > "$CX_DEST"\nexec /bin/cp "$@"\n')
            copy.chmod(0o755)
            env = dict(os.environ, PATH=str(bindir) + ":" + os.environ["PATH"], CX_DEST=str(destination))
            result = subprocess.run(["sh", str(script), str(source), str(destination)], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(destination.read_text(), "user configuration\n")
            self.assertEqual(sorted(p.name for p in base.iterdir()),
                             ["bin", "destination", "seed.sh", "source"])
