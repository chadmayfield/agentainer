"""Exercise the session assertion from the disconnect test without a container."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DisconnectAssertionTests(unittest.TestCase):
    def check_session(self, before, after, status=0):
        text = (ROOT / "tests/95-disconnect.sh").read_text()
        start = text.index("\nx tmux set-hook -u -t main client-attached\n")
        end = text.index('\nsame_panes "reattaching keeps every agent process"', start)
        assertion = text[start:end]
        # The stub receives the real tmux arguments; output and status come from these variables.
        shell = '. ./tests/lib.sh\nsid=$1\nafter=$2\nstatus=$3\nx() { printf "%s" "$after"; return "$status"; }\n'
        return subprocess.run(["sh", "-c", shell + assertion + "\nfinish\n", "sh", before, after, str(status)],
                              cwd=ROOT, capture_output=True, text=True)

    def test_failed_inspections_do_not_pass_as_matching_empty_sessions(self):
        r = self.check_session("", "", 125)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertFalse(any(line.startswith("ok ") for line in r.stdout.splitlines()), r.stdout)

    def test_a_real_unchanged_session_passes(self):
        r = self.check_session("$0", "$0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_changed_session_fails(self):
        r = self.check_session("$0", "$1")
        self.assertNotEqual(r.returncode, 0)
