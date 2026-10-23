"""Observe complete tool-version stamps while another startup publishes one."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("flock"), "stamp test requires Linux tools")
class StampTests(unittest.TestCase):
    def test_version_reader_keeps_old_bytes_until_atomic_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            (home / ".agentainer").mkdir(parents=True)
            stamp = home / ".agentainer/image-version"
            stamp.write_text("old-complete\n")
            state = base / "state"
            state.mkdir()
            pins = base / "versions.env"
            pins.write_text("EXAMPLE_VERSION=1.0.0\n")
            bindir = base / "bin"
            bindir.mkdir()
            mover = bindir / "mv"
            mover.write_text('''#!/bin/sh
if [ "$3" = "$HOME/.agentainer/image-version" ]; then
  touch "$CX_BASE/paused"
  while [ ! -e "$CX_BASE/release" ]; do sleep 0.01; done
fi
exec /bin/mv "$@"
''')
            mover.chmod(0o755)
            source = (ROOT / "rootfs/usr/local/lib/agentainer/entrypoint.d/40-tools.sh").read_text()
            source = source.replace("/var/lib/agentainer", str(state)).replace(
                "/usr/local/lib/agentainer/tools-layout.sh", str(ROOT / "rootfs/usr/local/lib/agentainer/tools-layout.sh"))
            source = source.replace("/usr/local/share/agentainer/versions.env", str(pins))
            step = base / "step"
            step.write_text(source)
            process = subprocess.Popen(["sh", "-ec", 'warn() { echo "$*"; }; . "$1"', "sh", str(step)],
                                       env=dict(os.environ, HOME=str(home), CX_BASE=str(base),
                                                PATH=str(bindir) + ":" + os.environ["PATH"]),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 3
                while not (base / "paused").exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue((base / "paused").exists(), "stamp was written without an atomic publication")
                self.assertEqual(stamp.read_text(), "old-complete\n")
                (base / "release").touch()
                out, err = process.communicate(timeout=3)
                self.assertEqual(process.returncode, 0, out + err)
                self.assertRegex(stamp.read_text(), r"^[0-9a-f]{64}\n$")
            finally:
                (base / "release").touch()
                if process.poll() is None:
                    process.kill()
                process.communicate()
