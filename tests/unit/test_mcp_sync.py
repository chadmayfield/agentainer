import importlib.machinery
import importlib.util
import json
import os
import stat
import tempfile
import unittest

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "..", "..", "rootfs", "usr", "local", "bin", "agentbox-mcp")
loader = importlib.machinery.SourceFileLoader("agentbox_mcp", SRC)
spec = importlib.util.spec_from_loader("agentbox_mcp", loader)
mcp = importlib.util.module_from_spec(spec)
loader.exec_module(mcp)

# Stub CLI: logs its argv; "claude mcp get NAME" succeeds when "claude NAME" is in $EXISTING.
STUB = """#!/bin/sh
echo "$(basename "$0") $*" >> "$LOG"
if [ "$1 $2" = "mcp get" ]; then grep -qx "$(basename "$0") $3" "$EXISTING"; exit $?; fi
exit 0
"""


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(os.path.join(self.home, ".agentbox"))
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "log")
        self.existing = os.path.join(self.tmp, "existing")
        open(self.log, "w").close()
        open(self.existing, "w").close()
        for name in ("claude", "codex", "opencode", "agy"):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(STUB)
            os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        self.env = {"HOME": self.home, "PATH": self.bin + ":/usr/bin:/bin",
                    "LOG": self.log, "EXISTING": self.existing, "SECRET_TOKEN": "s3cr3t-value"}

    def write_mcp(self, servers):
        with open(os.path.join(self.home, ".agentbox", "mcp.json"), "w") as f:
            json.dump({"mcpServers": servers}, f)

    def calls(self):
        with open(self.log) as f:
            return f.read()

    def sync(self):
        return mcp.main(["sync"], env=self.env)

    def read(self, *parts):
        path = os.path.join(self.home, *parts)
        if not os.path.exists(path):
            return ""
        with open(path) as f:
            return f.read()

    def opencode_servers(self):
        text = self.read(".config", "opencode", "opencode.json")
        return (json.loads(text).get("mcp") or {}).get("servers", {}) if text else {}

    def test_adds_servers_to_each_agent(self):
        self.write_mcp({"fs": {"command": "npx", "args": ["-y", "@example/fs"]}})
        self.assertEqual(self.sync(), 0)
        log = self.calls()
        self.assertIn("claude mcp add-json fs", log)
        self.assertIn("agy mcp add fs -- npx -y @example/fs", log)
        self.assertIn('[mcp_servers.fs]\ncommand = "npx"\nargs = ["-y", "@example/fs"]', self.read(".codex", "config.toml"))
        self.assertEqual(self.opencode_servers()["fs"], {"type": "local", "command": ["npx", "-y", "@example/fs"]})
        manifest = json.loads(self.read(".agentbox", "mcp-managed.json"))
        self.assertEqual(manifest, {"agy": ["fs"], "claude": ["fs"], "codex": ["fs"], "opencode": ["fs"]})

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
        with open(self.existing, "w") as f:
            f.write("claude mine\n")
        os.makedirs(os.path.join(self.home, ".codex"))
        with open(os.path.join(self.home, ".codex", "config.toml"), "w") as f:
            f.write('model = "x"\n\n[mcp_servers.mine]\ncommand = "theirs"\n')
        os.makedirs(os.path.join(self.home, ".config", "opencode"))
        with open(os.path.join(self.home, ".config", "opencode", "opencode.json"), "w") as f:
            json.dump({"update": "disable", "mcp": {"servers": {"mine": {"type": "local", "command": ["theirs"]}}}}, f)
        os.makedirs(os.path.join(self.home, ".gemini", "config"))
        with open(os.path.join(self.home, ".gemini", "config", "mcp_config.json"), "w") as f:
            json.dump({"mcpServers": {"mine": {"command": "theirs"}}}, f)
        self.write_mcp({"mine": {"command": "z"}})
        self.sync()
        log = self.calls()
        self.assertNotIn("claude mcp add-json mine", log)
        self.assertNotIn("claude mcp remove mine", log)
        self.assertNotIn("agy mcp add", log)
        toml = self.read(".codex", "config.toml")
        self.assertIn('command = "theirs"', toml)
        self.assertNotIn('command = "z"', toml)
        self.assertIn('model = "x"', toml)
        self.assertEqual(self.opencode_servers()["mine"]["command"], ["theirs"])
        self.assertIn('"update": "disable"', self.read(".config", "opencode", "opencode.json"))

    def test_malformed_json_changes_nothing(self):
        with open(os.path.join(self.home, ".agentbox", "mcp.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(self.sync(), 1)
        self.assertEqual(self.calls(), "")
        self.assertFalse(os.path.exists(os.path.join(self.home, ".agentbox", "mcp-managed.json")))

    def test_list_works_with_malformed_mcp_json(self):
        with open(os.path.join(self.home, ".agentbox", "mcp.json"), "w") as f:
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


class RobustnessTests(SyncTests):
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
            self.write_mcp({"foo": {"command": "ours"}})
            self.sync()
            toml = self.read(".codex", "config.toml")
            self.assertNotIn('"ours"', toml, text)
            self.assertIn('"theirs"', toml, text)

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
        manifest = json.loads(self.read(".agentbox", "mcp-managed.json"))
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
            f.write('#!/bin/sh\necho "claude $*" >> "$LOG"\ncase "$2" in add-json | get) exit 1 ;; esac\nexit 0\n')
        self.write_mcp({"k": {"command": "x"}})
        self.assertNotEqual(self.sync(), 0)
        manifest = json.loads(self.read(".agentbox", "mcp-managed.json"))
        self.assertNotIn("k", manifest.get("claude", []))

    def test_partial_reference_warns(self):
        import io
        import contextlib
        err = io.StringIO()
        self.write_mcp({"w": {"url": "https://x.example.com", "headers": {"X": "Token ${T}"}}})
        with contextlib.redirect_stderr(err):
            self.sync()
        self.assertIn("only exact ${NAME}", err.getvalue())


if __name__ == "__main__":
    unittest.main()
