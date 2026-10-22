"""Exercise launcher readiness against current and legacy image contracts."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReadinessProtocolTests(unittest.TestCase):
    def test_current_images_require_completion_while_legacy_images_use_the_link(self):
        launcher = (ROOT / "bin/agentainer").read_text()
        code = re.search(r'if "\$R" exec "\$name" sh -ec \'(.*?)\' 2>/dev/null', launcher, re.S).group(1)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state = base / "state"
            state.mkdir()
            share = base / "share"
            share.mkdir()
            (state / "active").symlink_to(base)
            capability = share / "startup-readiness-v1"
            capability.touch()
            code = code.replace("/var/lib/agentainer", str(state)).replace("/usr/local/share/agentainer", str(share))
            self.assertNotEqual(subprocess.run(["sh", "-ec", code], capture_output=True).returncode, 0)
            (state / "ready").touch()
            self.assertEqual(subprocess.run(["sh", "-ec", code], capture_output=True).returncode, 0)
            (state / "ready").unlink()
            capability.unlink()
            self.assertEqual(subprocess.run(["sh", "-ec", code], capture_output=True).returncode, 0)
