"""Offline test helpers must not fetch an absent image."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PullPolicyTests(unittest.TestCase):
    def test_both_helpers_disable_pulls(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            log = base / "calls"
            engine = base / "engine"
            engine.write_text("#!" + sys.executable + "\nimport json,os,sys\n"
                              "with open(os.environ['CX_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n")
            engine.chmod(0o755)
            code = '. "$1"; run_in -- echo marker; run_bg sample'
            result = subprocess.run(["sh", "-ec", code, "sh", str(ROOT / "tests/lib.sh")],
                                    env=dict(os.environ, RUNTIME=str(engine), IMAGE="example.com/no-image:test", CX_LOG=str(log)),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(calls), 2)
            self.assertTrue(all("--pull=never" in call for call in calls), calls)
