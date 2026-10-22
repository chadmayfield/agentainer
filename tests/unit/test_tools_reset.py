"""Emulate two container PID namespaces resetting a shared tools directory."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("flock"), "reset requires Linux flock")
class ResetTests(unittest.TestCase):
    def test_concurrent_resets_with_identical_pids_and_timestamps_keep_separate_backups(self):
        with tempfile.TemporaryDirectory(prefix="cx-reset-") as d:
            t = Path(d)
            home = t / "home"
            tools = home / ".agentainer/tools"
            (tools / "bin").mkdir(parents=True)
            (tools / "bin/original").write_text("first tool contents\n")
            bindir = t / "bin"
            bindir.mkdir()
            date = bindir / "date"
            date.write_text("#!/bin/sh\necho 20261019T120000Z\n")
            date.chmod(0o755)
            mv = bindir / "mv"
            mv.write_text('''#!/bin/sh
touch "$CX_TMP/moving$CX_WORKER"
while [ ! -e "$CX_TMP/release$CX_WORKER" ]; do sleep 0.01; done
exec /bin/mv "$@"
''')
            mv.chmod(0o755)
            script = t / "reset"
            source = (ROOT / "rootfs/usr/local/bin/agentainer-tools").read_text()
            # Separate containers may both run this command as PID 1.
            source = source.replace("$$", "1").replace("/usr/local/lib/agentainer/tools-layout.sh",
                                                       str(ROOT / "rootfs/usr/local/lib/agentainer/tools-layout.sh"))
            script.write_text(source)
            processes = []

            def start(worker):
                env = dict(os.environ, HOME=str(home), CX_TMP=d, CX_WORKER=worker,
                           PATH=str(bindir) + ":" + os.environ["PATH"])
                p = subprocess.Popen(["sh", str(script), "reset"], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                processes.append(p)
                return p

            def wait_file(name):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if (t / name).exists():
                        return
                    time.sleep(0.01)
                self.fail("reset did not reach " + name)

            try:
                a = start("A")
                wait_file("movingA")
                b = start("B")
                time.sleep(0.2)
                serialized = not (t / "movingB").exists()
                (t / "releaseA").touch()
                out, err = a.communicate(timeout=5)
                self.assertEqual(a.returncode, 0, out + err)
                wait_file("movingB")
                (tools / "bin/second").write_text("second tool contents\n")
                (t / "releaseB").touch()
                out, err = b.communicate(timeout=5)
                self.assertEqual(b.returncode, 0, out + err)
                backups = list((home / ".agentainer").glob("tools.*.bak"))
                self.assertEqual(len(backups), 2, "resets collided on the same backup path")
                self.assertTrue(serialized, "the second reset moved files before the first finished")
                self.assertEqual(sorted(x.name for backup in backups for x in (backup / "bin").iterdir()),
                                 ["original", "second"])
                self.assertEqual(sorted(path.read_text() for backup in backups for path in (backup / "bin").iterdir()),
                                 ["first tool contents\n", "second tool contents\n"])
                self.assertFalse(any((backup / "tools").exists() for backup in backups))
                self.assertTrue((tools / "bin").is_dir())
            finally:
                for p in processes:
                    if p.poll() is None:
                        p.kill()
                    p.communicate()
