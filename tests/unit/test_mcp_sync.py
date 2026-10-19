import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import stat
import tempfile
import unittest

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "..", "..", "rootfs", "usr", "local", "bin", "agentainer-mcp")
loader = importlib.machinery.SourceFileLoader("agentainer_mcp", SRC)
spec = importlib.util.spec_from_loader("agentainer_mcp", loader)
mcp = importlib.util.module_from_spec(spec)
loader.exec_module(mcp)

# Stub CLI: logs its argv and succeeds.
STUB = """#!/bin/sh
echo "$(basename "$0") $*" >> "$LOG"
exit 0
"""


class SyncBase(unittest.TestCase):
    """A temporary home and stub agent CLIs that log their arguments."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = os.path.join(self.tmp, "home")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(os.path.join(self.home, ".agentainer"))
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "log")
        open(self.log, "w").close()
        for name in ("claude", "codex", "opencode", "agy"):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(STUB)
            os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        self.env = {"HOME": self.home, "PATH": self.bin + ":/usr/bin:/bin",
                    "LOG": self.log, "SECRET_TOKEN": "s3cr3t-value"}

    def write_mcp(self, servers):
        with open(os.path.join(self.home, ".agentainer", "mcp.json"), "w") as f:
            json.dump({"mcpServers": servers}, f)

    def calls(self):
        with open(self.log) as f:
            return f.read()

    def sync(self):
        return mcp.main(["sync"], env=self.env)

    def sync_err(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = self.sync()
        return rc, err.getvalue()

    def assert_added_elsewhere(self, name, agents):
        """Positive check that sync ran: NAME reached each of AGENTS."""
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json") or "{}")
        for agent in agents:
            self.assertIn(name, manifest.get(agent, []), agent)
        if "agy" in agents:
            self.assertIn("agy mcp add %s " % name, self.calls())
        if "codex" in agents:
            self.assertIn("[mcp_servers.%s]" % name, self.read(".codex", "config.toml"))
        if "opencode" in agents:
            self.assertIn(name, self.opencode_servers())

    def read(self, *parts):
        path = os.path.join(self.home, *parts)
        if not os.path.exists(path):
            return ""
        with open(path) as f:
            return f.read()

    def opencode_servers(self):
        text = self.read(".config", "opencode", "opencode.json")
        return (json.loads(text).get("mcp") or {}).get("servers", {}) if text else {}


class SyncTests(SyncBase):
    def test_adds_servers_to_each_agent(self):
        self.write_mcp({"fs": {"command": "npx", "args": ["-y", "@example/fs"]}})
        self.assertEqual(self.sync(), 0)
        log = self.calls()
        self.assertIn("claude mcp add-json fs", log)
        self.assertIn("agy mcp add fs -- npx -y @example/fs", log)
        self.assertIn('[mcp_servers.fs]\ncommand = "npx"\nargs = ["-y", "@example/fs"]', self.read(".codex", "config.toml"))
        self.assertEqual(self.opencode_servers()["fs"], {"type": "local", "command": ["npx", "-y", "@example/fs"]})
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        self.assertEqual(manifest, {"agy": ["fs"], "claude": ["fs"], "codex": ["fs"], "opencode": ["fs"]})

    def test_agent_error_output_is_not_logged(self):
        # An agent CLI may echo its arguments on failure; literal values in mcp.json would
        # then reach container or pod logs through the warning.
        p = os.path.join(self.bin, "claude")
        with open(p, "w") as f:
            f.write('#!/bin/sh\necho "$(basename "$0") $*" >> "$LOG"\n'
                    'echo "bad config: $*" >&2\nexit 3\n')
        os.chmod(p, 0o755)
        self.write_mcp({"web": {"url": "https://mcp.example.com", "headers": {"X-Key": "literal-secret-123"}}})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.sync()
        self.assertIn("claude mcp add-json web failed (exit 3)", err.getvalue())
        self.assertNotIn("literal-secret-123", err.getvalue())

    def agy_config(self, text):
        os.makedirs(os.path.join(self.home, ".gemini", "config"), exist_ok=True)
        with open(os.path.join(self.home, ".gemini", "config", "mcp_config.json"), "w") as f:
            f.write(text)

    def test_agy_empty_config_has_no_servers(self):
        # agy's sign-in leaves an empty mcp_config.json.
        for text in ("", "  \n"):
            open(self.log, "w").close()
            self.agy_config(text)
            self.write_mcp({"fs": {"command": "npx"}})
            self.sync()
            self.assertIn("agy mcp add fs -- npx", self.calls())
            os.unlink(os.path.join(self.home, ".agentainer", "mcp-managed.json"))

    def test_agy_broken_config_is_left_alone(self):
        self.agy_config("{not json")
        self.write_mcp({"fs": {"command": "npx"}})
        _, err = self.sync_err()
        self.assertNotIn("agy mcp add", self.calls())
        self.assertIn("agy already has a server named fs", err)
        self.assertIn("claude mcp add-json fs", self.calls())
        self.assert_added_elsewhere("fs", ("claude", "codex", "opencode"))

    def test_removes_only_managed(self):
        self.write_mcp({"a": {"command": "x"}, "b": {"command": "y"}})
        self.sync()
        self.write_mcp({"a": {"command": "x"}})
        open(self.log, "w").close()
        self.sync()
        log = self.calls()
        self.assertIn("claude mcp remove b --scope user", log)
        self.assertIn("agy mcp remove b", log)
        self.assertEqual(log.count("claude mcp add-json a "), 1)
        self.assertIn("[mcp_servers.a]", self.read(".codex", "config.toml"))
        self.assertNotIn("[mcp_servers.b]", self.read(".codex", "config.toml"))
        self.assertEqual(sorted(self.opencode_servers()), ["a"])

    def test_keeps_unmanaged_servers(self):
        with open(os.path.join(self.home, ".claude.json"), "w") as f:
            json.dump({"mcpServers": {"mine": {"type": "stdio", "command": "theirs"}}}, f)
        os.makedirs(os.path.join(self.home, ".codex"))
        with open(os.path.join(self.home, ".codex", "config.toml"), "w") as f:
            f.write('model = "x"\n\n[mcp_servers.mine]\ncommand = "theirs"\n')
        os.makedirs(os.path.join(self.home, ".config", "opencode"))
        with open(os.path.join(self.home, ".config", "opencode", "opencode.json"), "w") as f:
            json.dump({"update": "disable", "mcp": {"servers": {"mine": {"type": "local", "command": ["theirs"]}}}}, f)
        os.makedirs(os.path.join(self.home, ".gemini", "config"))
        with open(os.path.join(self.home, ".gemini", "config", "mcp_config.json"), "w") as f:
            json.dump({"mcpServers": {"mine": {"command": "theirs"}}}, f)
        self.write_mcp({"mine": {"command": "z"}, "other": {"command": "o"}})
        _, err = self.sync_err()
        log = self.calls()
        self.assertNotIn("claude mcp add-json mine", log)
        self.assertNotIn("claude mcp remove mine", log)
        self.assertNotIn("agy mcp add mine", log)
        for agent in ("claude", "codex", "opencode", "agy"):
            self.assertIn("%s already has a server named mine" % agent, err)
        # A server without a conflict still reaches every agent.
        self.assertIn("claude mcp add-json other", log)
        self.assert_added_elsewhere("other", ("claude", "codex", "opencode", "agy"))
        toml = self.read(".codex", "config.toml")
        self.assertIn('command = "theirs"', toml)
        self.assertNotIn('command = "z"', toml)
        self.assertIn('model = "x"', toml)
        self.assertEqual(self.opencode_servers()["mine"]["command"], ["theirs"])
        self.assertIn('"update": "disable"', self.read(".config", "opencode", "opencode.json"))

    def test_malformed_json_changes_nothing(self):
        with open(os.path.join(self.home, ".agentainer", "mcp.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(self.sync(), 1)
        self.assertEqual(self.calls(), "")
        self.assertFalse(os.path.exists(os.path.join(self.home, ".agentainer", "mcp-managed.json")))

    def test_list_works_with_malformed_mcp_json(self):
        with open(os.path.join(self.home, ".agentainer", "mcp.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(mcp.main(["list"], env=self.env), 0)

    def test_rejects_server_without_command_or_url(self):
        self.write_mcp({"bad": {"args": ["x"]}})
        self.assertEqual(self.sync(), 1)
        self.assertEqual(self.calls(), "")

    def test_never_writes_secret_values(self):
        self.write_mcp({"gh": {"command": "srv", "env": {"SECRET_TOKEN": "${SECRET_TOKEN}"}},
                        "web": {"url": "https://mcp.example.com/mcp",
                                "headers": {"Authorization": "Bearer ${SECRET_TOKEN}"}}})
        self.sync()
        # The servers were written, so the absence checks below look at real output.
        self.assertIn("claude mcp add-json gh", self.calls())
        self.assertIn("claude mcp add-json web", self.calls())
        self.assertIn("[mcp_servers.gh]", self.read(".codex", "config.toml"))
        self.assertEqual(sorted(self.opencode_servers()), ["gh", "web"])
        self.assertNotIn("s3cr3t-value", self.calls())
        self.assertNotIn("s3cr3t-value", self.read(".codex", "config.toml"))
        self.assertNotIn("s3cr3t-value", self.read(".config", "opencode", "opencode.json"))

    def test_opencode_uses_its_env_syntax(self):
        self.write_mcp({"gh": {"command": "srv", "env": {"TOKEN": "${SECRET_TOKEN}"}}})
        self.sync()
        self.assertEqual(self.opencode_servers()["gh"]["environment"], {"TOKEN": "{env:SECRET_TOKEN}"})

    def test_opencode_remote_headers(self):
        self.write_mcp({"web": {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "Bearer ${SECRET_TOKEN}"}}})
        self.sync()
        self.assertEqual(self.opencode_servers()["web"],
                         {"type": "remote", "url": "https://mcp.example.com/mcp",
                          "headers": {"Authorization": "Bearer {env:SECRET_TOKEN}"}})

    def test_codex_env_reference_becomes_env_vars(self):
        self.write_mcp({"gh": {"command": "srv", "env": {"GH_TOKEN": "${GH_TOKEN}", "MODE": "ro"}}})
        self.sync()
        toml = self.read(".codex", "config.toml")
        self.assertIn('env_vars = ["GH_TOKEN"]', toml)
        self.assertIn('env = { "MODE" = "ro" }', toml)

    def test_codex_http_headers(self):
        self.write_mcp({"web": {"url": "https://mcp.example.com/mcp",
                                "headers": {"Authorization": "Bearer ${SECRET_TOKEN}",
                                            "X-Team": "${TEAM}", "X-Static": "1"}}})
        self.sync()
        toml = self.read(".codex", "config.toml")
        self.assertIn('bearer_token_env_var = "SECRET_TOKEN"', toml)
        self.assertIn('env_http_headers = { "X-Team" = "TEAM" }', toml)
        self.assertIn('http_headers = { "X-Static" = "1" }', toml)

    def test_agy_static_env_and_headers_passed_references_dropped(self):
        self.write_mcp({"gh": {"command": "srv", "env": {"MODE": "ro", "T": "${SECRET_TOKEN}"}},
                        "web": {"url": "https://mcp.example.com/mcp", "headers": {"X-Static": "1"}}})
        self.sync()
        log = self.calls()
        self.assertIn("agy mcp add --env MODE=ro gh -- srv", log)
        self.assertIn("agy mcp add --header X-Static: 1 web https://mcp.example.com/mcp", log)


class RobustnessTests(SyncBase):
    def codex_path(self):
        os.makedirs(os.path.join(self.home, ".codex"), exist_ok=True)
        return os.path.join(self.home, ".codex", "config.toml")

    def test_user_tables_after_ours_survive_a_resync(self):
        self.write_mcp({"e": {"command": "x"}})
        self.sync()
        with open(self.codex_path(), "a") as f:
            f.write('\n[profiles.mine] # mine\nmodel = "keepme"\n\n[[skills.config]]\nname = "s"\n')
        self.write_mcp({"e": {"command": "y"}})
        self.sync()
        toml = self.read(".codex", "config.toml")
        self.assertIn('model = "keepme"', toml)
        self.assertIn("[[skills.config]]", toml)
        self.assertIn('command = "y"', toml)
        self.assertNotIn('command = "x"', toml)

    def test_user_server_in_other_toml_spellings_is_left_alone(self):
        for text in ('mcp_servers.foo.command = "theirs"\n',
                     '[mcp_servers]\nfoo = { command = "theirs" }\n',
                     '[mcp_servers."foo"]\ncommand = "theirs"\n'):
            with open(self.codex_path(), "w") as f:
                f.write(text)
            self.write_mcp({"foo": {"command": "ours"}, "bar": {"command": "ok"}})
            _, err = self.sync_err()
            toml = self.read(".codex", "config.toml")
            self.assertNotIn('"ours"', toml, text)
            self.assertIn('"theirs"', toml, text)
            self.assertIn("codex already has a server named foo", err, text)
            self.assertIn('[mcp_servers.bar]\ncommand = "ok"', toml, text)

    def test_non_bmp_characters_are_written_literally(self):
        self.write_mcp({"u": {"command": "srv", "args": ["\U0001F600", "a\x7fb"]}})
        self.sync()
        toml = self.read(".codex", "config.toml")
        self.assertIn("\U0001F600", toml)
        self.assertNotIn("\\ud83d", toml.lower())
        self.assertNotIn("\x7f", toml)

    def test_bad_value_types_are_rejected_before_any_change(self):
        for servers in ({"p": {"command": "srv", "env": {"PORT": 8080}}},
                        {"p": {"command": "srv", "args": "not-a-list"}},
                        {"p": {"url": "https://x.example.com", "headers": {"H": ["a"]}}}):
            open(self.log, "w").close()
            self.write_mcp(servers)
            self.assertEqual(self.sync(), 1)
            self.assertEqual(self.calls(), "")

    def test_one_agent_failing_does_not_lose_the_others(self):
        os.makedirs(os.path.join(self.home, ".config", "opencode"))
        with open(os.path.join(self.home, ".config", "opencode", "opencode.json"), "w") as f:
            f.write('{"mcp": []}')
        self.write_mcp({"k": {"command": "x"}})
        rc = self.sync()
        self.assertNotEqual(rc, 0)
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        self.assertEqual(manifest["claude"], ["k"])
        self.assertEqual(manifest["agy"], ["k"])
        # Removing k later removes it where it was added.
        self.write_mcp({})
        open(self.log, "w").close()
        self.sync()
        self.assertIn("claude mcp remove k", self.calls())
        self.assertIn("agy mcp remove k", self.calls())

    def test_failed_cli_add_returns_nonzero(self):
        p = os.path.join(self.bin, "claude")
        with open(p, "w") as f:
            f.write('#!/bin/sh\necho "claude $*" >> "$LOG"\ncase "$2" in add-json) exit 1 ;; esac\nexit 0\n')
        self.write_mcp({"k": {"command": "x"}})
        self.assertNotEqual(self.sync(), 0)
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        self.assertNotIn("k", manifest.get("claude", []))

    def test_partial_reference_warns(self):
        import io
        import contextlib
        err = io.StringIO()
        self.write_mcp({"w": {"url": "https://x.example.com", "headers": {"X": "Token ${T}"}}})
        with contextlib.redirect_stderr(err):
            self.sync()
        self.assertIn("only exact ${NAME}", err.getvalue())

    def test_codex_bearer_reference_on_other_header_is_left_out(self):
        # Codex env_http_headers sends the variable's value as the whole header, so
        # "Bearer ${T}" on a header other than Authorization has no Codex spelling.
        self.write_mcp({"w": {"url": "https://x.example.com", "headers": {"X-Auth": "Bearer ${T}"}}})
        rc, err = self.sync_err()
        toml = self.read(".codex", "config.toml")
        self.assertNotIn("X-Auth", toml)
        self.assertNotIn("${T}", toml)
        self.assertIn("codex: header X-Auth on w", err)
        self.assertEqual(rc, 0)

    def test_sse_server_goes_to_claude_as_sse(self):
        self.write_mcp({"s": {"type": "sse", "url": "https://x.example.com/sse"}})
        rc, err = self.sync_err()
        self.assertIn('"type": "sse"', self.calls())
        self.assertNotIn("[mcp_servers.s]", self.read(".codex", "config.toml"))
        self.assertNotIn("agy mcp add", self.calls())
        self.assertIn("codex: s uses SSE", err)
        self.assertIn("agy: s uses SSE", err)
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        self.assertEqual(manifest["claude"], ["s"])
        self.assertEqual(manifest["codex"], [])
        self.assertEqual(manifest["agy"], [])
        self.assertEqual(rc, 0)

    def test_http_type_is_accepted(self):
        self.write_mcp({"h": {"type": "http", "url": "https://x.example.com/mcp"},
                        "c": {"type": "stdio", "command": "srv"}})
        rc, err = self.sync_err()
        self.assertEqual(rc, 0)
        self.assertNotIn("warning", err)
        self.assertIn('"type": "http"', self.calls())

    def test_bad_type_is_rejected(self):
        for s in ({"type": "sse", "command": "srv"}, {"type": "ws", "url": "wss://x.example.com"}):
            open(self.log, "w").close()
            self.write_mcp({"b": s})
            self.assertEqual(self.sync_err()[0], 1)
            self.assertEqual(self.calls(), "")

    def test_unknown_keys_warn(self):
        self.write_mcp({"c": {"command": "srv", "cwd": "/tmp", "timeout": 5, "disabled": True}})
        rc, err = self.sync_err()
        self.assertIn("c: cwd, disabled, timeout", err)
        self.assertIn("claude mcp add-json c", self.calls())

    def claude_json(self, data):
        with open(os.path.join(self.home, ".claude.json"), "w") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def test_claude_conflict_reads_user_scope_only(self):
        # A project-scope server of the same name (in /workspace) is not a conflict.
        self.claude_json({"mcpServers": {"mine": {"type": "stdio", "command": "x"}},
                          "projects": {"/workspace": {"mcpServers": {"proj": {"command": "y"}}}}})
        self.write_mcp({"mine": {"command": "z"}, "proj": {"command": "z"}})
        self.sync()
        log = self.calls()
        self.assertNotIn("claude mcp get", log)
        self.assertNotIn("claude mcp add-json mine", log)
        self.assertIn("claude mcp add-json proj", log)

    def test_claude_conflict_honours_claude_config_dir(self):
        d = os.path.join(self.tmp, "cc")
        os.makedirs(d)
        with open(os.path.join(d, ".claude.json"), "w") as f:
            json.dump({"mcpServers": {"mine": {"command": "x"}}}, f)
        self.env["CLAUDE_CONFIG_DIR"] = d
        self.write_mcp({"mine": {"command": "z"}, "other": {"command": "o"}})
        _, err = self.sync_err()
        self.assertNotIn("claude mcp add-json mine", self.calls())
        self.assertIn("claude already has a server named mine", err)
        self.assertIn("claude mcp add-json other", self.calls())
        self.assert_added_elsewhere("mine", ("agy", "codex", "opencode"))

    def test_unreadable_claude_json_counts_as_taken(self):
        self.claude_json("{broken")
        self.write_mcp({"k": {"command": "z"}})
        _, err = self.sync_err()
        self.assertNotIn("claude mcp add-json k", self.calls())
        self.assertIn("claude already has a server named k", err)
        self.assert_added_elsewhere("k", ("agy", "codex", "opencode"))



class WriteAtomicTests(unittest.TestCase):
    def tmpdir(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        return d

    def test_another_writers_temp_file_does_not_block(self):
        # Two containers can share one home volume, so a fixed temp name can collide.
        d = self.tmpdir()
        path = os.path.join(d, "mcp-managed.json")
        os.mkdir(path + ".agentainer-tmp")
        mcp.write_atomic(path, "{}")
        with open(path) as f:
            self.assertEqual(f.read(), "{}")
        self.assertEqual(sorted(os.listdir(d)), ["mcp-managed.json", "mcp-managed.json.agentainer-tmp"])

    def test_keeps_the_mode_of_a_replaced_file(self):
        d = self.tmpdir()
        path = os.path.join(d, "config.toml")
        with open(path, "w") as f:
            f.write("old")
        os.chmod(path, 0o640)
        mcp.write_atomic(path, "new")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)

    def test_symlinked_file_stays_a_symlink(self):
        # A user who keeps config.toml in a dotfiles repo links it into place.
        d = self.tmpdir()
        os.mkdir(os.path.join(d, "dotfiles"))
        target = os.path.join(d, "dotfiles", "config.toml")
        with open(target, "w") as f:
            f.write("old")
        link = os.path.join(d, "config.toml")
        os.symlink(os.path.join("dotfiles", "config.toml"), link)
        mcp.write_atomic(link, "new")
        self.assertTrue(os.path.islink(link))
        with open(target) as f:
            self.assertEqual(f.read(), "new")
        self.assertEqual(sorted(os.listdir(os.path.join(d, "dotfiles"))), ["config.toml"])

    def test_syncs_data_before_rename(self):
        calls = []
        real_fsync, real_replace = os.fsync, os.replace
        os.fsync = lambda fd: (calls.append("fsync"), real_fsync(fd))[1]
        os.replace = lambda a, b: (calls.append("replace"), real_replace(a, b))[1]
        try:
            mcp.write_atomic(os.path.join(self.tmpdir(), "f"), "x")
        finally:
            os.fsync, os.replace = real_fsync, real_replace
        self.assertEqual(calls[:2], ["fsync", "replace"])

if __name__ == "__main__":
    unittest.main()
