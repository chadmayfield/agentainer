"""Keep arbitrary pane passthrough opt-in."""
from pathlib import Path
import shlex
import unittest

ROOT = Path(__file__).resolve().parents[2]
SET_COMMANDS = {"set", "set-option", "setw", "set-window-option"}


def passthrough_values(text):
    """Every allow-passthrough value the config sets, in order."""
    values = []
    for line in text.splitlines():
        if "allow-passthrough" not in line or line.lstrip().startswith("#"):
            continue
        commands, current = [], []
        for word in shlex.split(line, comments=True):
            if word in (";", "\\;"):
                commands.append(current)
                current = []
            else:
                current.append(word)
        commands.append(current)
        found = False
        for command in commands:
            if "allow-passthrough" not in command:
                continue
            if command[0] not in SET_COMMANDS:
                raise ValueError("unrecognized command sets allow-passthrough: %r" % line)
            at = command.index("allow-passthrough")
            flags = "".join(w[1:] for w in command[1:at] if w.startswith("-"))
            rest = command[at + 1:]
            values.append("unset" if "u" in flags else (rest[0] if rest else "toggle"))
            found = True
        if not found:
            raise ValueError("allow-passthrough outside a set command: %r" % line)
    return values


class TerminalPolicyTests(unittest.TestCase):
    def test_image_does_not_enable_arbitrary_pane_passthrough(self):
        values = passthrough_values((ROOT / "rootfs/etc/tmux.conf").read_text())
        self.assertTrue(values, "tmux.conf does not set allow-passthrough")
        self.assertEqual(values[-1], "off", values)

    def test_parser_sees_every_spelling(self):
        for text, last in (
            ("set -g allow-passthrough off\n", "off"),
            ("set -g allow-passthrough off\nset -g allow-passthrough all\n", "all"),
            ("set -g allow-passthrough off\nset-option -g allow-passthrough on\n", "on"),
            ("set -g allow-passthrough off\nsetw -g allow-passthrough on\n", "on"),
            ("set -g allow-passthrough off\nset -g mouse on ; set -gq allow-passthrough on\n", "on"),
            ("set -g allow-passthrough off\nset -gu allow-passthrough\n", "unset"),
            ("set -g allow-passthrough off\nset -g allow-passthrough\n", "toggle"),
            ("set -g allow-passthrough off # not on\n", "off"),
        ):
            with self.subTest(text=text):
                self.assertEqual(passthrough_values(text)[-1], last)
        with self.assertRaises(ValueError):
            passthrough_values("if-shell true 'set -g allow-passthrough on'\n")
