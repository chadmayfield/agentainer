"""Fail when a seeded file uses a color outside the approved palette."""
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from palette import ALLOWED, colors_in  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SEEDED = "rootfs/etc/agentainer/home"

# Paths excluded from the Ayu wording check. The visual gallery still
# carries the old palette name.
AYU_PENDING = (
    "tests/visual",
    "artifacts/visual",
)


def git_ls_files(prefix):
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", prefix],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return [p.decode() for p in out.split(b"\0") if p]


class PaletteTests(unittest.TestCase):
    def test_colors_in_reads_hex_and_rgb_triples(self):
        self.assertEqual(
            colors_in("fg=#58A6FF di=01;38;2;1;4;9:su=48;2;73;2;2"),
            {"#58a6ff", "#010409", "#490202"},
        )

    def test_every_seeded_color_is_in_the_palette(self):
        files = git_ls_files(SEEDED)
        self.assertTrue(files)
        bad = {
            f: sorted(colors_in((ROOT / f).read_text(errors="replace")) - ALLOWED)
            for f in files
        }
        self.assertEqual({k: v for k, v in bad.items() if v}, {})

    def test_no_ayu_wording_outside_history(self):
        result = subprocess.run(
            ["git", "grep", "-niw", "ayu", "--", ".",
             ":!tests/unit/test_palette.py"]
            + [":!" + p for p in AYU_PENDING],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.returncode, 1)
