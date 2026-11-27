"""Image-owned Python commands must not execute a user's Python startup files."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PythonIsolationTests(unittest.TestCase):
    def test_command_shebangs_disable_user_site_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            env = dict(os.environ, PYTHONUSERBASE=str(base), HOME=str(base))
            site = Path(subprocess.run([sys.executable, "-c", "import site; print(site.getusersitepackages())"],
                                       env=env, capture_output=True, text=True, check=True).stdout.strip())
            site.mkdir(parents=True)
            marker = base / "ran"
            (site / "usercustomize.py").write_text("open(%r, 'w').write('ran')\n" % str(marker))
            for command, args in (("agentainer-mcp", ["list"]), ("agentainer-doctor", ["--help"])):
                with self.subTest(command=command):
                    source = ROOT / "rootfs/usr/local/bin" / command
                    interpreter, *flags = source.read_text().splitlines()[0].removeprefix("#!").split()
                    self.assertEqual((interpreter, flags), ("/usr/bin/python3", ["-I"]))
                    control = subprocess.run([sys.executable, str(source), *args],
                                             env=env, capture_output=True, text=True)
                    if not marker.exists():
                        self.skipTest("this Python does not load usercustomize: %s" % control.stderr)
                    marker.unlink()
                    result = subprocess.run([sys.executable, *flags, str(source), *args],
                                            env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(marker.exists(), result.stderr)

    def test_entrypoint_version_helper_uses_isolated_python(self):
        text = (ROOT / "rootfs/usr/local/lib/agentainer/entrypoint.d/30-agents-md.sh").read_text()
        self.assertIn("python3 -I /usr/local/lib/agentainer/release_version.py", text)
