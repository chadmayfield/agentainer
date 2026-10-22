"""Reject engine options where the launcher expects a container name."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NameArgumentsTests(unittest.TestCase):
    def test_down_refuses_a_container_without_the_agentainer_label(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            log = base / "removed"
            engine = base / "engine"
            engine.write_text('#!/bin/sh\nif [ "$1" = inspect ]; then echo 0; else echo removed >"$CX_LOG"; fi\n')
            engine.chmod(0o755)
            result = subprocess.run(["sh", str(ROOT / "bin/agentainer"), "down", "unrelated"],
                                    env=dict(os.environ, AGENTAINER_RUNTIME=str(engine), CX_LOG=str(log)),
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(log.exists())

    def test_trace_preserves_embedded_single_quotes(self):
        import shlex
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "it's a project"
            workspace.mkdir()
            result = self.launch(base, str(workspace))
            self.assertEqual(result.returncode, 0, result.stderr)
            trace = next(line for line in result.stderr.splitlines() if line.startswith("+ "))
            self.assertEqual(shlex.split(trace[2:])[1:], result.stdout.splitlines())

    def test_explicit_missing_env_file_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.launch(Path(directory), directory)
            self.assertIn("env file does not exist", result.stderr)

    def launch(self, base, *args, **extra):
        engine = base / "engine"
        engine.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        engine.chmod(0o755)
        environment = dict(os.environ, AGENTAINER_RUNTIME=str(engine), AGENTAINER_ENV_FILE="/nonexistent")
        environment.update(extra)
        return subprocess.run(["sh", str(ROOT / "bin/agentainer"), "up", *args],
                              env=environment,
                              cwd=base, capture_output=True, text=True)

    def test_names_are_valid_hostnames_before_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name in ("x" * 65, "bad/name", "_leading", ""):
                result = self.launch(base, "--name", name, directory)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_dot_home_sources_resolve_on_the_client(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            for value in (".", ".."):
                result = self.launch(base, str(base), AGENTAINER_HOME_VOLUME=value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(str((base / value).resolve()) + ":/home/agent", result.stdout.splitlines())

    def test_writable_env_files_warn(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            file = base / "env"
            file.write_text("FAKE=value\n")
            for mode in (0o620, 0o602):
                file.chmod(mode)
                result = self.launch(base, directory, AGENTAINER_ENV_FILE=str(file))
                self.assertIn("chmod 600", result.stderr)

    def test_mounting_host_home_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            result = self.launch(base, str(Path.home()))
            self.assertIn("host home", result.stderr)

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
