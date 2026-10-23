"""Check health failures and startup readiness in disposable filesystem fixtures."""
import json
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "rootfs/usr/local/bin/agentainer-healthcheck"
ENTRYPOINT = ROOT / "rootfs/usr/local/bin/agentainer-entrypoint"


class HealthcheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cx-health-unit-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = self.base / "state"
        self.state.mkdir()
        self.ready = self.state / "ready"
        self.ready.touch()
        self.home = self.base / "home"
        self.home.mkdir()
        self.tools = self.base / "tools"
        self.tools.mkdir()
        self.active = self.state / "active"
        self.active.symlink_to(self.tools, target_is_directory=True)

    def probe(self, **overrides):
        self.assertTrue(COMMAND.is_file(), "health-check command is missing")
        script = self.base / "probe.sh"
        script.write_text(COMMAND.read_text().replace("/var/lib/agentainer", str(self.state)))
        env = dict(os.environ, HOME=str(self.home))
        env.update(overrides)
        result = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True,
                                timeout=3)
        self.assertNotIn("cx-private-value", result.stdout + result.stderr)
        return result

    def test_healthy_probe_is_silent_and_does_not_change_home(self):
        (self.home / "settings").write_text("cx-private-value")
        result = self.probe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")
        self.assertEqual([p.name for p in self.home.iterdir()], ["settings"])
        self.assertEqual((self.home / "settings").read_text(), "cx-private-value")

    def test_missing_ready_marker_fails(self):
        self.ready.unlink()
        self.assertEqual(self.probe().returncode, 1)

    def test_directory_or_symlink_cannot_supply_ready_marker(self):
        self.ready.unlink()
        self.ready.mkdir()
        self.assertEqual(self.probe().returncode, 1)
        self.ready.rmdir()
        self.ready.symlink_to(self.home / "cx-private-value")
        (self.home / "cx-private-value").touch()
        self.assertEqual(self.probe().returncode, 1)

    def test_missing_or_empty_home_fails_without_printing_its_value(self):
        for home in ("", str(self.home / "cx-private-value")):
            with self.subTest(home=home):
                self.assertEqual(self.probe(HOME=home).returncode, 1)

    @unittest.skipIf(os.geteuid() == 0, "permission checks must run without root capabilities")
    def test_home_requires_read_write_and_search_permissions(self):
        for mode in (0o300, 0o500, 0o600):
            with self.subTest(mode=mode):
                self.home.chmod(mode)
                try:
                    self.assertEqual(self.probe().returncode, 1)
                finally:
                    self.home.chmod(0o700)

    def test_missing_broken_or_non_symlink_active_directory_fails(self):
        self.active.unlink()
        self.assertEqual(self.probe().returncode, 1)
        self.active.symlink_to(self.base / "cx-private-value")
        self.assertEqual(self.probe().returncode, 1)
        self.active.unlink()
        self.active.mkdir()
        self.assertEqual(self.probe().returncode, 1)

    @unittest.skipIf(os.geteuid() == 0, "permission checks must run without root capabilities")
    def test_tools_target_requires_read_and_search_permissions(self):
        for mode in (0o300, 0o600):
            with self.subTest(mode=mode):
                self.tools.chmod(mode)
                try:
                    self.assertEqual(self.probe().returncode, 1)
                finally:
                    self.tools.chmod(0o700)

    def test_containerfile_executes_probe_with_startup_grace(self):
        text = (ROOT / "Containerfile").read_text()
        instructions = re.findall(r"^HEALTHCHECK (.*(?:\n\s+.*)*)", text, re.MULTILINE)
        self.assertEqual(len(instructions), 1, "image needs exactly one health check")
        options, command = re.split(r"\s+CMD\s+", instructions[0].replace("\\\n", " "), maxsplit=1)
        self.assertEqual(json.loads(command), ["/usr/local/bin/agentainer-healthcheck"])
        for option in ("--interval=30s", "--timeout=5s", "--start-period=180s", "--retries=3"):
            self.assertIn(option, options.split())


class StartupReadinessTests(unittest.TestCase):
    def test_restart_clears_previous_marker_until_steps_complete(self):
        with tempfile.TemporaryDirectory(prefix="cx-health-restart-") as directory:
            base = Path(directory)
            state, steps = base / "state", base / "steps"
            state.mkdir()
            steps.mkdir()
            ready = state / "ready"
            ready.touch()
            started, release = base / "started", base / "release"
            (steps / "00-wait.sh").write_text(
                ': >"$CX_STARTED"\nwhile [ ! -f "$CX_RELEASE" ]; do sleep 0.02; done\n')
            script = base / "entrypoint.sh"
            script.write_text(ENTRYPOINT.read_text()
                              .replace("/usr/local/lib/agentainer/entrypoint.d", str(steps))
                              .replace("/var/lib/agentainer", str(state)))
            env = dict(os.environ, CX_STARTED=str(started), CX_RELEASE=str(release))
            process = subprocess.Popen(["sh", str(script), "true"], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 3
                while not started.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(started.exists(), "startup step did not run")
                self.assertFalse(ready.exists(), "previous startup marker survived restart")
                release.touch()
                stdout, stderr = process.communicate(timeout=3)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                self.assertTrue(ready.is_file())
                (steps / "00-wait.sh").write_text("return 1\n")
                failed = subprocess.run(["sh", str(script), "true"], env=env,
                                        capture_output=True, text=True, timeout=3)
                self.assertEqual(failed.returncode, 1)
                self.assertFalse(ready.exists(), "failed restart left a healthy marker")
            finally:
                release.touch()
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=3)


class HealthHarnessTests(unittest.TestCase):
    def test_startup_grace_covers_an_engine_with_a_delayed_first_probe(self):
        spec = importlib.util.spec_from_file_location("cx_health_delayed", ROOT / "tests/host/test-healthcheck.py")
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        metadata = {"Test": ["CMD", "/usr/local/bin/agentainer-healthcheck"],
                    "Interval": 30_000_000_000, "Timeout": 5_000_000_000,
                    "StartPeriod": 180_000_000_000, "Retries": 3}
        elapsed = [0.0]
        grace = [0]

        class GraceObserved(Exception):
            pass

        def engine(arguments, **kwargs):
            operation = arguments[1]
            output = ""
            if operation == "image":
                output = json.dumps([{"Config": {"Healthcheck": metadata}}])
            elif operation == "run":
                grace[0] = int(next(a for a in arguments if a.startswith("--health-start-period=")).split("=")[1][:-1])
            elif operation == "inspect":
                # Docker's default startup interval can delay its first result by 5s.
                logs = [{"ExitCode": 1}] if elapsed[0] >= 5 else None
                state = {"Status": "starting", "Log": logs,
                         "FailingStreak": int(elapsed[0] >= grace[0])}
                output = json.dumps([{"State": {"Health": state}}])
            elif operation == "exec":
                raise GraceObserved()
            return subprocess.CompletedProcess(arguments, 0, output, "")

        def sleep(seconds):
            elapsed[0] += seconds

        with mock.patch.object(harness.subprocess, "run", side_effect=engine), \
                mock.patch.object(harness.time, "monotonic", side_effect=lambda: elapsed[0]), \
                mock.patch.object(harness.time, "sleep", side_effect=sleep), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(GraceObserved, msg="first probe arrived after test grace expired"):
                harness.main()

    def test_failed_start_removes_a_container_the_engine_already_created(self):
        spec = importlib.util.spec_from_file_location("cx_health_harness", ROOT / "tests/host/test-healthcheck.py")
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        metadata = {"Test": ["CMD", "/usr/local/bin/agentainer-healthcheck"],
                    "Interval": 30_000_000_000, "Timeout": 5_000_000_000,
                    "StartPeriod": 180_000_000_000, "Retries": 3}
        calls = []

        def engine(arguments, **kwargs):
            calls.append(arguments[1:])
            operation = arguments[1]
            if operation == "image":
                return subprocess.CompletedProcess(arguments, 0, json.dumps([{"Config": {"Healthcheck": metadata}}]), "")
            if operation == "run":
                return subprocess.CompletedProcess(arguments, 125, "", "start failed after creation")
            if operation in ("container", "rm"):
                return subprocess.CompletedProcess(arguments, 0, "", "")
            self.fail("unexpected engine operation")

        with mock.patch.object(harness.subprocess, "run", side_effect=engine), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(harness.main(), 1)
        names = [call[call.index("--name") + 1] for call in calls if call[0] == "run"]
        self.assertEqual(len(names), 1)
        self.assertIn(["rm", "-f", names[0]], calls, "failed-start container was left behind")
