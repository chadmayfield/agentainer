"""Exercise offline diagnostics with private configuration and failing tools."""
import contextlib
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "rootfs/usr/local/bin/agentainer-doctor"
HAS_TOMLLIB = importlib.util.find_spec("tomllib") is not None
SECRET = "cx-private-value-never-print-this"


def load_doctor():
    loader = importlib.machinery.SourceFileLoader("cx_doctor", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class DoctorCommandTests(unittest.TestCase):
    def test_help_succeeds_without_checking_the_host(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("agentainer-doctor [--json]", result.stdout)


@unittest.skipUnless(HAS_TOMLLIB, "doctor config checks require Python 3.11+; image has Python 3.14")
class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cx-doctor-unit-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir(mode=0o700)
        self.state = self.base / "state"
        self.state.mkdir()
        self.manifest = self.base / "versions.json"
        self.manifest.write_text(json.dumps({"pins": {}, "apt": {}}))
        self.env = {"HOME": str(self.home), "PATH": os.environ["PATH"], "AGENTAINER_TOOLS": "ephemeral",
                    "OPENAI_API_KEY": SECRET}
        for relative in (".claude/settings.json", ".gemini/antigravity-cli/settings.json",
                         ".config/opencode/opencode.json", ".config/opencode/cli.json"):
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"private": SECRET}))
        codex = self.home / ".codex/config.toml"
        codex.parent.mkdir()
        codex.write_text('approval_policy = "on-request"\n')
        self.box = self.home / ".agentainer"
        self.box.mkdir()
        self.tools = self.state / "tools"
        self.tools.mkdir()
        (self.state / "active").symlink_to(self.tools, target_is_directory=True)
        self.doctor = load_doctor()

    def collect(self, probe=None):
        return self.doctor.collect(self.home, self.state, self.manifest, self.env,
                                   probe=probe or (lambda *args, **kwargs: ("ok", "version probe passed")))

    def assert_safe(self, checks):
        self.assertNotIn(SECRET, json.dumps(checks))

    def test_healthy_home_passes_without_changing_files(self):
        def snapshot():
            return {str(p.relative_to(self.home)): (p.read_bytes(), p.stat().st_mode)
                    for p in self.home.rglob("*") if p.is_file()}
        before = snapshot()
        checks = self.collect()
        self.assertTrue(checks)
        self.assertTrue(all(check["status"] == "ok" for check in checks), checks)
        self.assertEqual(snapshot(), before)
        self.assert_safe(checks)

    def test_invalid_json_and_toml_fail_without_echoing_values(self):
        for relative, text in ((".claude/settings.json", '{"' + SECRET + '":'),
                               (".codex/config.toml", 'private = "' + SECRET + '"\nprivate = 2')):
            with self.subTest(relative=relative):
                path = self.home / relative
                before = path.read_text()
                path.write_text(text)
                checks = self.collect()
                self.assertTrue(any(c["status"] == "fail" and c["name"].startswith("config.") for c in checks))
                self.assert_safe(checks)
                self.assertEqual(path.read_text(), text)
                path.write_text(before)

    def test_missing_config_warns_and_directory_in_its_place_fails(self):
        path = self.home / ".claude/settings.json"
        path.unlink()
        checks = self.collect()
        self.assertTrue(any(c["name"] == "config.claude" and c["status"] == "warn" for c in checks))
        path.mkdir()
        checks = self.collect()
        self.assertTrue(any(c["name"] == "config.claude" and c["status"] == "fail" for c in checks))

    def test_home_permission_failure_is_reported(self):
        with mock.patch.object(self.doctor.os, "access", return_value=False):
            checks = self.collect()
        self.assertTrue(any(c["name"] == "home" and c["status"] == "fail" for c in checks))

    def test_invalid_image_inventory_is_reported(self):
        self.manifest.write_text(json.dumps({"pins": SECRET, "apt": {}}))
        checks = self.collect()
        self.assertTrue(any(c["name"] == "image.manifest" and c["status"] == "fail" for c in checks))
        self.assert_safe(checks)

    def test_configuration_directory_overrides_are_checked(self):
        for variable, name, filename in (("CLAUDE_CONFIG_DIR", "config.claude", "settings.json"),
                                          ("CODEX_HOME", "config.codex", "config.toml"),
                                          ("XDG_CONFIG_HOME", "config.opencode", "opencode/opencode.json")):
            with self.subTest(variable=variable):
                root = self.base / variable
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(SECRET)
                self.env[variable] = str(root)
                checks = self.collect()
                self.assertTrue(any(c["name"] == name and c["status"] == "fail" for c in checks))
                self.assert_safe(checks)
                del self.env[variable]

    def test_jsonc_is_reported_as_not_checked(self):
        (self.home / ".config/opencode/opencode.jsonc").write_text('{ // ' + SECRET + '\n}')
        checks = self.collect()
        self.assertTrue(any(c["name"] == "config.opencode" and c["status"] == "warn" for c in checks))
        self.assert_safe(checks)

    def test_persistence_mode_and_target_must_agree(self):
        self.env["AGENTAINER_TOOLS"] = "persist"
        checks = self.collect()
        self.assertTrue(any(c["name"] == "tools.persistence" and c["status"] == "fail" for c in checks))
        root = self.box / "tools"
        root.mkdir()
        (self.state / "active").unlink()
        (self.state / "active").symlink_to(root, target_is_directory=True)
        self.assertFalse(any(c["status"] == "fail" for c in self.collect()))
        self.env["AGENTAINER_TOOLS"] = SECRET
        checks = self.collect()
        self.assertTrue(any(c["name"] == "tools.persistence" and c["status"] == "fail" for c in checks))
        self.assert_safe(checks)

    def mcp_input(self):
        path = self.box / "mcp.json"
        path.write_text(json.dumps({"mcpServers": {"example": {"command": "echo", "args": [SECRET]}}}))
        (self.box / ".mcp-sync.lock").touch()
        return path

    def test_mcp_invalid_input_fails_and_stale_sync_warns(self):
        path = self.mcp_input()
        path.write_text(json.dumps({"mcpServers": {SECRET: {"command": "echo", "url": SECRET}}}))
        checks = self.collect()
        self.assertTrue(any(c["name"] == "mcp" and c["status"] == "fail" for c in checks))
        self.assert_safe(checks)
        self.mcp_input()
        checks = self.collect()
        self.assertTrue(any(c["name"] == "mcp" and c["status"] == "warn" for c in checks))

    def test_mcp_success_stamp_and_ownership_metadata_are_checked(self):
        path = self.mcp_input()
        (self.box / ".mcp-synced.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "\n")
        manifest = self.box / "mcp-managed.json"
        manifest.write_text(json.dumps({"claude": ["example"]}))
        checks = self.collect()
        self.assertTrue(any(c["name"] == "mcp" and c["status"] == "ok" for c in checks))
        manifest.write_text(json.dumps({"claude": SECRET}))
        checks = self.collect()
        self.assertTrue(any(c["name"] == "mcp" and c["status"] == "fail" for c in checks))
        self.assert_safe(checks)

    def test_active_or_interrupted_mcp_sync_is_not_reported_as_healthy(self):
        self.mcp_input()
        lock = self.box / ".mcp-sync.lock"
        with lock.open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            checks = self.collect()
            self.assertTrue(any(c["name"] == "mcp" and c["status"] == "warn" for c in checks))
        pending = self.box / "mcp-pending-claude.json"
        pending.write_text(json.dumps({"path": SECRET}))
        checks = self.collect()
        self.assertTrue(any(c["name"] == "mcp" and c["status"] == "warn" for c in checks))
        self.assertEqual(json.loads(pending.read_text()), {"path": SECRET})
        self.assert_safe(checks)

    def test_probe_environment_excludes_credentials_and_personal_config(self):
        environments = []
        def probe(name, arguments, env, cwd):
            environments.append(dict(env))
            self.assertNotEqual(env["HOME"], str(self.home))
            self.assertEqual(env["HOME"], str(cwd))
            return "ok", "version probe passed"
        self.collect(probe)
        self.assertTrue(environments)
        self.assertTrue(all(SECRET not in json.dumps(env) for env in environments))
        self.assertTrue(all(env["GOTOOLCHAIN"] == "local" for env in environments))

    def test_probe_failure_is_not_hidden(self):
        checks = self.collect(lambda *args, **kwargs: ("fail", "version probe failed"))
        self.assertTrue(any(c["name"].startswith("tool.") and c["status"] == "fail" for c in checks))

    def test_tool_output_is_discarded_and_timeout_is_bounded(self):
        tool = self.base / "cx-tool"
        tool.write_text("#!" + sys.executable + "\nimport sys\nprint(" + repr(SECRET) + ")\nprint(" + repr(SECRET) + ",file=sys.stderr)\nsys.exit(1)\n")
        tool.chmod(0o755)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status, message = self.doctor.probe_tool(str(tool), ["--version"], self.env, self.base, timeout=1)
        self.assertEqual(status, "fail")
        self.assertNotIn(SECRET, output.getvalue() + message)
        tool.write_text("#!" + sys.executable + "\nimport time\ntime.sleep(10)\n")
        status, message = self.doctor.probe_tool(str(tool), ["--version"], self.env, self.base, timeout=0.05)
        self.assertEqual(status, "fail")
        self.assertIn("timed out", message)
        status, _ = self.doctor.probe_tool(str(self.base / "cx-missing"), ["--version"], self.env, self.base)
        self.assertEqual(status, "fail")

    def test_cli_output_and_exit_codes_are_credential_safe(self):
        for checks, expected in (([{"name": "home", "status": "ok", "message": "ready"}], 0),
                                 ([{"name": "home", "status": "warn", "message": "check permissions"}], 0),
                                 ([{"name": "home", "status": "fail", "message": "not writable"}], 1)):
            for args in ([], ["--json"]):
                with self.subTest(checks=checks, args=args), mock.patch.object(self.doctor, "collect", return_value=checks):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        rc = self.doctor.main(args)
                    self.assertEqual(rc, expected)
                    self.assertNotIn(SECRET, output.getvalue())
                    if args:
                        self.assertEqual(json.loads(output.getvalue())["checks"], checks)
        for args in ([SECRET], ["--json", SECRET]):
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                self.assertEqual(self.doctor.main(args), 2)
            self.assertNotIn(SECRET, output.getvalue())

    def test_unexpected_error_does_not_print_exception_values(self):
        output = io.StringIO()
        with mock.patch.object(self.doctor, "collect", side_effect=OSError(SECRET)), contextlib.redirect_stdout(output):
            self.assertEqual(self.doctor.main(["--json"]), 1)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "fail")
