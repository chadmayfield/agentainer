"""Failures and interrupted writes must not lose MCP ownership or expose credentials."""
import contextlib
import io
import json
import os
from unittest import mock

import test_mcp_sync as base

mcp = base.mcp


class RecoveryTests(base.SyncBase):
    def test_failed_removal_is_retried_on_the_next_start(self):
        self.write_mcp({"revoked": {"command": "example"}})
        self.assertEqual(self.sync(), 0)
        self.write_mcp({})
        original = mcp.write_atomic

        def fail_config(path, text):
            if path == os.path.join(self.home, ".claude.json"):
                raise OSError("injected config write failure")
            return original(path, text)

        # A CLI failure covers the old implementation; a file failure covers direct writes.
        cli = os.path.join(self.bin, "claude")
        with open(cli, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        with mock.patch.object(mcp, "write_atomic", side_effect=fail_config):
            with contextlib.redirect_stderr(io.StringIO()):
                rc = mcp.main(["sync", "--if-changed"], env=self.env)
        self.assertNotEqual(rc, 0, "a failed removal was stamped as successful")
        self.assertIn("revoked", json.loads(self.read(".claude.json"))["mcpServers"])
        self.assertEqual(mcp.main(["sync", "--if-changed"], env=self.env), 0)
        self.assertNotIn("revoked", json.loads(self.read(".claude.json"))["mcpServers"])
        self.assertEqual(json.loads(self.read(".agentainer", "mcp-managed.json"))["claude"], [])

    def test_literal_credentials_never_enter_child_arguments(self):
        secret = "cx-synthetic-credential"
        self.write_mcp({"web": {"url": "https://mcp.example.com", "headers": {"X-Key": secret}},
                        "local": {"command": "example", "args": [secret], "env": {"TOKEN": secret}}})
        self.assertEqual(self.sync(), 0)
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
        self.assertEqual(sorted(manifest["claude"]), ["local", "web"])
        self.assertEqual(sorted(manifest["agy"]), ["local", "web"])
        self.assertNotIn(secret, self.calls(), "configuration was passed through argv")
        for parts in ((".claude.json",), (".gemini", "config", "mcp_config.json")):
            config = json.loads(self.read(*parts))["mcpServers"]
            self.assertEqual(config["web"]["headers"]["X-Key"], secret)
            self.assertEqual(config["local"]["env"]["TOKEN"], secret)
            self.assertEqual(config["local"]["args"], [secret])

    def test_restart_recovers_ownership_after_each_config_write(self):
        for agent, parts in (("claude", (".claude.json",)),
                             ("agy", (".gemini", "config", "mcp_config.json")),
                             ("opencode", (".config", "opencode", "opencode.json"))):
            with self.subTest(agent=agent):
                name = "orphan_" + agent
                self.write_mcp({name: {"command": "example"}})
                original = mcp.write_atomic
                target = os.path.join(self.home, *parts)

                def interrupted(path, text):
                    original(path, text)
                    if path == target:
                        raise KeyboardInterrupt("injected termination after config rename")

                with mock.patch.object(mcp, "write_atomic", side_effect=interrupted):
                    with self.assertRaises(KeyboardInterrupt):
                        self.sync()
                # Recovery must run before the startup hash shortcut and before removals.
                self.write_mcp({})
                self.assertEqual(mcp.main(["sync", "--if-changed"], env=self.env), 0)
                data = json.loads(self.read(*parts))
                servers = data["mcp"]["servers"] if agent == "opencode" else data["mcpServers"]
                self.assertNotIn(name, servers)
                manifest = json.loads(self.read(".agentainer", "mcp-managed.json"))
                self.assertEqual(manifest[agent], [])

    def test_interruption_before_config_write_does_not_claim_a_user_server(self):
        self.write_mcp({"same": {"command": "ours"}})
        original = mcp.write_atomic

        def before_write(path, text):
            if path == os.path.join(self.home, ".claude.json"):
                raise KeyboardInterrupt("before config write")
            original(path, text)

        with mock.patch.object(mcp, "write_atomic", side_effect=before_write):
            with self.assertRaises(KeyboardInterrupt):
                self.sync()
        # The intent alone is not proof of ownership.
        with open(os.path.join(self.home, ".claude.json"), "w") as f:
            json.dump({"mcpServers": {"same": {"command": "theirs"}}}, f)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.sync(), 1)
        self.assertEqual(json.loads(self.read(".claude.json"))["mcpServers"]["same"]["command"], "theirs")
        manifest = json.loads(self.read(".agentainer", "mcp-managed.json") or "{}")
        self.assertNotIn("same", manifest.get("claude", []))

    def test_restart_retries_a_write_interrupted_before_the_config_rename(self):
        self.write_mcp({"retry": {"command": "example"}})
        original = mcp.write_atomic

        def before_write(path, text):
            if path == os.path.join(self.home, ".claude.json"):
                raise KeyboardInterrupt("before config write")
            original(path, text)

        with mock.patch.object(mcp, "write_atomic", side_effect=before_write):
            with self.assertRaises(KeyboardInterrupt):
                self.sync()
        self.assertEqual(mcp.main(["sync", "--if-changed"], env=self.env), 0)
        self.assertIn("retry", json.loads(self.read(".claude.json"))["mcpServers"])
        self.assertEqual(json.loads(self.read(".agentainer", "mcp-managed.json"))["claude"], ["retry"])

    def test_new_configs_are_private_and_journals_do_not_copy_credentials(self):
        secret = "cx-synthetic-private-value"
        self.write_mcp({"private": {"command": "example", "env": {"TOKEN": secret}}})
        original = mcp.write_atomic
        journals = []

        def observe(path, text, **kwargs):
            if "mcp-pending-" in path:
                journals.append(text)
            original(path, text, **kwargs)

        with mock.patch.object(mcp, "write_atomic", side_effect=observe):
            self.assertEqual(self.sync(), 0)
        self.assertEqual(len(journals), 4)
        self.assertTrue(all(secret not in text for text in journals))
        for parts in ((".claude.json",), (".gemini", "config", "mcp_config.json"),
                      (".codex", "config.toml"), (".config", "opencode", "opencode.json")):
            self.assertEqual(os.stat(os.path.join(self.home, *parts)).st_mode & 0o777, 0o600)

    def test_every_agent_recovers_at_journal_config_and_manifest_boundaries(self):
        original = mcp.write_atomic
        for agent in ("claude", "agy", "codex", "opencode"):
            for boundary in ("journal", "config", "manifest"):
                with self.subTest(agent=agent, boundary=boundary):
                    name = agent + "_" + boundary
                    self.write_mcp({name: {"command": "example"}})
                    pending = os.path.join(self.home, ".agentainer", "mcp-pending-" + agent + ".json")
                    config = mcp.agent_config_path(agent, self.env)
                    manifest = os.path.join(self.home, ".agentainer", "mcp-managed.json")
                    target = {"journal": pending, "config": config, "manifest": manifest}[boundary]

                    def interrupted(path, text):
                        original(path, text)
                        if path == target and os.path.exists(pending):
                            raise KeyboardInterrupt("injected termination at " + boundary)

                    with mock.patch.object(mcp, "write_atomic", side_effect=interrupted):
                        with self.assertRaises(KeyboardInterrupt):
                            self.sync()
                    self.assertEqual(mcp.main(["sync", "--if-changed"], env=self.env), 0)
                    owned = json.loads(self.read(".agentainer", "mcp-managed.json"))
                    self.assertEqual(owned[agent], [name])
                    self.write_mcp({})
                    self.assertEqual(self.sync(), 0)
                    self.assertTrue(all(not names for names in json.loads(self.read(".agentainer", "mcp-managed.json")).values()))

    def test_corrupt_or_misdirected_journal_preserves_existing_config(self):
        self.write_mcp({"kept": {"command": "original"}})
        self.assertEqual(self.sync(), 0)
        before = self.read(".claude.json")
        pending = os.path.join(self.home, ".agentainer", "mcp-pending-claude.json")
        for text in ("{broken", json.dumps({"path": "/different/config"})):
            with self.subTest(text=text):
                with open(pending, "w") as f:
                    f.write(text)
                self.write_mcp({})
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(self.sync(), 1)
                self.assertEqual(self.read(".claude.json"), before)
                self.assertTrue(os.path.exists(pending))

    def test_interruption_after_journal_cleanup_keeps_committed_ownership(self):
        self.write_mcp({"committed": {"command": "example"}})
        original = mcp.os.unlink
        target = os.path.join(self.home, ".agentainer", "mcp-pending-claude.json")

        def interrupted(path):
            original(path)
            if path == target:
                raise KeyboardInterrupt("after journal cleanup")

        with mock.patch.object(mcp.os, "unlink", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.sync()
        self.write_mcp({})
        self.assertEqual(mcp.main(["sync", "--if-changed"], env=self.env), 0)
        self.assertEqual(json.loads(self.read(".claude.json"))["mcpServers"], {})
