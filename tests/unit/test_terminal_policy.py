"""Keep arbitrary pane passthrough opt-in."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TerminalPolicyTests(unittest.TestCase):
    def test_image_does_not_enable_arbitrary_pane_passthrough(self):
        text = (ROOT / "rootfs/etc/tmux.conf").read_text()
        self.assertIn("set -g allow-passthrough off", text)
        self.assertNotIn("set -g allow-passthrough on", text)
