"""Check dash path resolution without starting an engine."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("dash"), "path regression requires dash")
class DashPathTests(unittest.TestCase):
    def test_cd_minus_does_not_duplicate_the_mount_path(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            previous = base / "previous"
            previous.mkdir()
            engine = base / "engine"
            engine.write_text("#!" + sys.executable + "\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
            engine.chmod(0o755)
            result = subprocess.run(["dash", str(ROOT / "bin/agentainer"), "up", "--", "-"],
                                    env=dict(os.environ, AGENTAINER_RUNTIME=str(engine),
                                             AGENTAINER_ENV_FILE="/nonexistent", OLDPWD=str(previous)),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(previous.resolve()) + ":/workspace", json.loads(result.stdout))
