"""Exercise the session assertion from the disconnect test without a container."""
from pathlib import Path
import subprocess
import json
import re
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

    def pane_snapshot(self, window_name, pid="157", dead="0"):
        text = (ROOT / "tests/95-disconnect.sh").read_text()
        function = re.search(r"^panes\(\) \{.*$", text, re.M).group(0)
        fields = {"window_name": window_name, "window_id": "@0", "pane_id": "%0",
                  "pane_pid": pid, "pane_dead": dead}
        renderer = """import json,sys
text = sys.argv[-1]
for key, value in json.loads(sys.argv[1]).items():
    text = text.replace('#{' + key + '}', value)
print(text)
"""
        # POSIX shell positional parameters keep the tmux format unchanged for the renderer.
        shell = 'renderer=$1; fields=$2; x() { python3 -c "$renderer" "$fields" "$@"; }\n'
        result = subprocess.run(["sh", "-c", shell + function + "\npanes\n", "sh", renderer, json.dumps(fields)],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_automatic_window_rename_does_not_change_pane_identity(self):
        self.assertEqual(self.pane_snapshot("tmux"), self.pane_snapshot("bash"))

    def test_pane_snapshot_detects_process_replacement_and_death(self):
        before = self.pane_snapshot("bash")
        self.assertNotEqual(before, self.pane_snapshot("bash", pid="158"))
        self.assertNotEqual(before, self.pane_snapshot("bash", dead="1"))
