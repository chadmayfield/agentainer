"""Reject engine options where the launcher expects a container name."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NameArgumentsTests(unittest.TestCase):
    def test_option_names_and_extra_names_never_reach_the_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            log = base / "calls"
            engine = base / "engine"
            engine.write_text('#!/bin/sh\necho called >>"$CX_LOG"\n')
            engine.chmod(0o755)
            for command in ("start", "attach", "shell", "down", "update", "doctor"):
                for arguments in (["--all"], ["one", "two"]):
                    with self.subTest(command=command, arguments=arguments):
                        log.unlink(missing_ok=True)
                        result = subprocess.run(
                            ["sh", str(ROOT / "bin/agentainer"), command, *arguments],
                            env=dict(os.environ, AGENTAINER_RUNTIME=str(engine), CX_LOG=str(log)),
                            capture_output=True, text=True)
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertFalse(log.exists(), "invalid input reached the engine")
