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
            site = base / ("lib/python%d.%d/site-packages" % sys.version_info[:2])
            site.mkdir(parents=True)
            marker = base / "ran"
            (site / "usercustomize.py").write_text("open(%r, 'w').write('ran')\n" % str(marker))
            for command in ("agentainer-mcp", "agentainer-doctor"):
                source = ROOT / "rootfs/usr/local/bin" / command
                shebang = source.read_text().splitlines()[0]
                self.assertEqual(shebang, "#!/usr/bin/python3 -I")
                result = subprocess.run([sys.executable, "-I", str(source), "--help"],
                                        env=dict(os.environ, PYTHONUSERBASE=str(base)),
                                        capture_output=True, text=True)
                self.assertFalse(marker.exists(), result.stderr)

    def test_entrypoint_version_helper_uses_isolated_python(self):
        text = (ROOT / "rootfs/usr/local/lib/agentainer/entrypoint.d/30-agents-md.sh").read_text()
        self.assertIn("python3 -I /usr/local/lib/agentainer/release_version.py", text)
