"""Exercise entrypoint path conflicts in a temporary container home."""
import fcntl
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
# The steps read these path overrides; a runner that sets one (GitHub's Ubuntu images set
# XDG_CONFIG_HOME) would send them outside the temporary home. Tests that need one set it.
ENV = {k: v for k, v in os.environ.items() if k not in ("CODEX_HOME", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR")}
STEPS = ROOT / "rootfs/usr/local/lib/agentainer/entrypoint.d"
# The entrypoint's home_path helper, which the steps call.
HOME_PATH = re.search(r"^home_path\(\) \{\n.*?^\}\n",
                      (ROOT / "rootfs/usr/local/bin/agentainer-entrypoint").read_text(), re.S | re.M).group(0)


class HomePathTests(unittest.TestCase):
    def home_path(self, relative, **env):
        result = subprocess.run(["sh", "-ec", HOME_PATH + 'home_path "$1"', "sh", relative],
                                env=dict(ENV, HOME="/h", **env), capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def test_claude_config_dir_moves_only_the_claude_directory(self):
        self.assertEqual(self.home_path(".claude/settings.json"), "/h/.claude/settings.json")
        self.assertEqual(self.home_path(".claude/settings.json", CLAUDE_CONFIG_DIR="/c"), "/c/settings.json")
        self.assertEqual(self.home_path(".claude", CLAUDE_CONFIG_DIR="/c"), "/c")
        # An empty variable means the default, as in agentainer-mcp and agentainer-doctor.
        self.assertEqual(self.home_path(".claude/CLAUDE.md", CLAUDE_CONFIG_DIR=""), "/h/.claude/CLAUDE.md")
        self.assertEqual(self.home_path(".claude.json", CLAUDE_CONFIG_DIR="/c"), "/h/.claude.json")
        self.assertEqual(self.home_path(".claudex/x", CLAUDE_CONFIG_DIR="/c"), "/h/.claudex/x")


@unittest.skipUnless(shutil.which("flock"), "startup path tests require Linux flock")
class StartupPathsTests(unittest.TestCase):
    def test_blocked_agents_ledger_warns_without_stopping_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentainer/agents-default.sha256").mkdir(parents=True)
            image = home / "image"
            image.mkdir()
            (image / "AGENTS.md").write_text("default\n")
            source = (ROOT / "rootfs/usr/local/lib/agentainer/entrypoint.d/30-agents-md.sh").read_text()
            step = home / "step.sh"
            step.write_text(source.replace("/etc/agentainer", str(image)))
            shell = HOME_PATH + 'warn() { echo "$*"; }; log() { echo "$*"; }; seed_file() { :; }; . "$1"'
            result = subprocess.run(["sh", "-ec", shell, "sh", str(step)],
                                    env=dict(ENV, HOME=str(home)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("cannot record", result.stdout)

    def test_dangling_service_link_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentainer").mkdir()
            config = home / ".config/opencode/service.json"
            config.parent.mkdir(parents=True)
            config.symlink_to("missing-target")
            bindir = home / "bin"
            bindir.mkdir()
            command = bindir / "opencode"
            command.write_text('#!/bin/sh\nrm -f "$HOME/.config/opencode/service.json"\nprintf replaced >"$HOME/.config/opencode/service.json"\n')
            command.chmod(0o755)
            result = subprocess.run(["sh", "-ec", HOME_PATH + 'warn() { echo "$*"; }; . "$1"', "sh",
                                     str(STEPS / "70-opencode.sh")],
                                    env=dict(ENV, HOME=str(home), PATH=str(bindir) + ":" + os.environ["PATH"]),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(config.is_symlink())

    def test_unwritable_seed_lock_warns_and_skips_seeding(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentainer/.seed.lock").mkdir(parents=True)
            result = subprocess.run(["sh", "-ec", HOME_PATH + 'warn() { echo "$*"; }; . "$1"', "sh",
                                     str(STEPS / "20-seed.sh")],
                                    env=dict(ENV, HOME=str(home)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("seed lock", result.stdout)

    def test_busy_seed_lock_warns_and_skips_seeding(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentainer").mkdir()
            step = home / "step.sh"
            step.write_text((STEPS / "20-seed.sh").read_text().replace("flock -w 30 9", "flock -w 1 9"))
            with open(home / ".agentainer/.seed.lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = subprocess.run(["sh", "-ec", HOME_PATH + 'warn() { echo "$*"; }; . "$1"; echo STEP-RETURNED',
                                         "sh", str(step)],
                                        env=dict(ENV, HOME=str(home)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("held the seed lock", result.stdout)
            self.assertIn("STEP-RETURNED", result.stdout)

    def test_seeding_follows_codex_home_and_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            (home / ".agentainer").mkdir(parents=True)
            source = base / "image"
            for relative in (".codex/config.toml", ".config/opencode/opencode.json", ".config/bat/config"):
                (source / relative).parent.mkdir(parents=True, exist_ok=True)
                (source / relative).write_text(relative + "\n")
            step = base / "step.sh"
            step.write_text((STEPS / "20-seed.sh").read_text().replace("src=/etc/agentainer/home", "src=" + str(source)))
            shell = HOME_PATH + 'warn() { echo "$*"; }; seed_file() { mkdir -p "$(dirname "$2")" && cp "$1" "$2"; }; . "$1"'
            result = subprocess.run(["sh", "-ec", shell, "sh", str(step)],
                                    env=dict(ENV, HOME=str(home), CODEX_HOME=str(base / "codex"),
                                             XDG_CONFIG_HOME=str(base / "xdg")),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((base / "codex/config.toml").is_file())
            self.assertTrue((base / "xdg/opencode/opencode.json").is_file())
            self.assertFalse((home / ".codex").exists())
            self.assertFalse((home / ".config/opencode").exists())
            # Only OpenCode's directory moves; other tools keep their ~/.config paths.
            self.assertTrue((home / ".config/bat/config").is_file())

    def test_seeding_follows_claude_config_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            (home / ".agentainer").mkdir(parents=True)
            source = base / "image"
            for relative in (".claude/CLAUDE.md", ".claude/settings.json", ".claude/themes/github-dark.json"):
                (source / relative).parent.mkdir(parents=True, exist_ok=True)
                (source / relative).write_text(relative + "\n")
            step = base / "step.sh"
            step.write_text((STEPS / "20-seed.sh").read_text().replace("src=/etc/agentainer/home", "src=" + str(source)))
            shell = HOME_PATH + 'warn() { echo "$*"; }; seed_file() { mkdir -p "$(dirname "$2")" && cp "$1" "$2"; }; . "$1"'
            result = subprocess.run(["sh", "-ec", shell, "sh", str(step)],
                                    env=dict(ENV, HOME=str(home), CLAUDE_CONFIG_DIR=str(base / "claude")),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # CLAUDE.md holds the import of ~/.agentainer/AGENTS.md, so it must land where
            # Claude Code reads its user memory.
            for relative in ("CLAUDE.md", "settings.json", "themes/github-dark.json"):
                self.assertTrue((base / "claude" / relative).is_file(), relative)
            self.assertFalse((home / ".claude").exists())

    def test_instruction_links_follow_codex_home_and_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            (home / ".agentainer").mkdir(parents=True)
            image = base / "image"
            image.mkdir()
            (image / "AGENTS.md").write_text("default\n")
            step = base / "step.sh"
            step.write_text((STEPS / "30-agents-md.sh").read_text().replace("/etc/agentainer", str(image)))
            shell = (HOME_PATH + 'seed_file() { [ -e "$2" ] || cp "$1" "$2"; }\n'
                     'warn() { echo "$*"; }; log() { echo "$*"; }; . "$1"')
            result = subprocess.run(["sh", "-ec", shell, "sh", str(step)],
                                    env=dict(ENV, HOME=str(home), CODEX_HOME=str(base / "codex"),
                                             XDG_CONFIG_HOME=str(base / "xdg")),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            canon = str(home / ".agentainer/AGENTS.md")
            for link in (base / "codex/AGENTS.md", base / "xdg/opencode/AGENTS.md", home / ".gemini/AGENTS.md"):
                self.assertEqual(os.readlink(link), canon, link)
            self.assertFalse((home / ".codex").exists())

    def test_opencode_step_checks_service_json_under_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            (home / ".agentainer").mkdir(parents=True)
            service = base / "xdg/opencode/service.json"
            service.parent.mkdir(parents=True)
            service.write_text('{"disabled": false}\n')
            bindir = base / "bin"
            bindir.mkdir()
            command = bindir / "opencode"
            command.write_text('#!/bin/sh\necho called >"$HOME/opencode-ran"\n')
            command.chmod(0o755)
            result = subprocess.run(["sh", "-ec", HOME_PATH + 'warn() { echo "$*"; }; . "$1"', "sh",
                                     str(STEPS / "70-opencode.sh")],
                                    env=dict(ENV, HOME=str(home), XDG_CONFIG_HOME=str(base / "xdg"),
                                             PATH=str(bindir) + ":" + os.environ["PATH"]),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((home / "opencode-ran").exists())
            self.assertTrue((home / ".agentainer/.opencode-service-disabled").exists())

    def test_opencode_step_keeps_the_shared_descriptors_blocking(self):
        # The stub does what OpenCode does to what it inherits. The step must give it
        # none of the descriptors the container command later uses.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            (home / ".agentainer").mkdir(parents=True)
            bindir = base / "bin"
            bindir.mkdir()
            command = bindir / "opencode"
            command.write_text("#!/usr/bin/env python3\nimport os\nfor fd in (0, 1, 2):\n"
                               "    os.set_blocking(fd, False)\n")
            command.chmod(0o755)
            pipes = [os.pipe() for _ in range(3)]
            try:
                process = subprocess.run(
                    ["sh", "-ec", HOME_PATH + 'warn() { echo "$*" >&2; }; . "$1"', "sh",
                     str(STEPS / "70-opencode.sh")],
                    stdin=pipes[0][0], stdout=pipes[1][1], stderr=pipes[2][1],
                    env=dict(ENV, HOME=str(home), PATH=str(bindir) + ":" + os.environ["PATH"]))
                self.assertEqual(process.returncode, 0)
                self.assertTrue((home / ".agentainer/.opencode-service-disabled").exists())
                self.assertEqual([os.get_blocking(pipes[0][0]), os.get_blocking(pipes[1][1]),
                                  os.get_blocking(pipes[2][1])], [True, True, True])
            finally:
                for read, write in pipes:
                    os.close(read)
                    os.close(write)
