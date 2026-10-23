"""A broken tool must fail a fixture even with Python optimization enabled."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


class FixtureChecksTests(unittest.TestCase):
    def test_optimized_infrastructure_fixture_rejects_failing_tools(self):
        path = ROOT / "tests/fixtures/check-infrastructure.py"
        source = path.read_text()
        original = Path.read_text

        def read(path, *args, **kwargs):
            if str(path) == "/etc/agentainer/versions.json":
                return json.dumps({"pins": {"KUBECTL_VERSION": "1.0.0", "HELM_VERSION": "1.0.0"}})
            return original(path, *args, **kwargs)

        def broken(arguments, **kwargs):
            return subprocess.CompletedProcess(arguments, 7,
                json.dumps({"clientVersion": {"gitVersion": "vWRONG"}}), "fake tool failure")

        output = io.StringIO()
        with mock.patch.object(Path, "read_text", read), mock.patch.object(subprocess, "run", broken), \
                contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit):
                exec(compile(source, str(path), "exec", optimize=2), {"__name__": "__main__"})
        self.assertNotIn("INFRASTRUCTURE_VERIFIED", output.getvalue())
