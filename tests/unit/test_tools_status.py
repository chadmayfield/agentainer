"""Report the selected tools root instead of the requested environment value."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ToolsStatusTests(unittest.TestCase):
    def test_effective_mode_follows_active_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state = base / "state"
            state.mkdir()
            persistent = base / ".agentainer/tools"
            persistent.mkdir(parents=True)
            (persistent / "python/bin").mkdir(parents=True)
            (persistent / "python/bin/python-user-tool").touch()
            active = state / "active"
            active.symlink_to(persistent)
            script = base / "tools"
            script.write_text((ROOT / "rootfs/usr/local/bin/agentainer-tools").read_text()
                              .replace("/usr/local/lib/agentainer/tools-layout.sh",
                                       str(ROOT / "rootfs/usr/local/lib/agentainer/tools-layout.sh"))
                              .replace("/var/lib/agentainer", str(state)))
            result = subprocess.run(["sh", str(script), "status"],
                                    env=dict(os.environ, HOME=str(base), AGENTAINER_TOOLS="bogus"),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("mode: persist\nroot: " + str(persistent), result.stdout)
            self.assertIn("python-user-tool", result.stdout)
