"""Exercise the seeded defaults with the image's actual tools, without network access."""
import hashlib
import json
import os
import pty
import re
import select
import shlex
import signal
import struct
import termios
import time
import fcntl
from pathlib import Path
import subprocess
import tempfile
import unittest

HOME = Path.home()


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


class DefaultsTests(unittest.TestCase):
    def command(self, args, **kwargs):
        result = run(args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_home_contains_image_defaults_before_user_edits(self):
        source = Path('/etc/agentainer/home')
        for path in source.rglob('*'):
            if path.is_file():
                target = HOME / path.relative_to(source)
                self.assertTrue(target.is_file(), str(target))
                self.assertEqual(target.read_bytes(), path.read_bytes(),
                                 'Initial home differs from image defaults: ' + str(target))

    def test_git_has_generic_identity_and_working_ignore_patterns(self):
        config = self.command(['git', 'config', 'list', '--file', str(HOME / '.gitconfig')])
        keys = dict(line.split('=', 1) for line in config.splitlines())
        for name in ('user.name', 'user.email', 'user.signingkey', 'include.path'):
            self.assertNotIn(name, keys)
        self.assertFalse(any(key.startswith('credential.') for key in keys))
        self.assertEqual(keys['user.useconfigonly'], 'true')
        self.assertEqual(keys['core.editor'], 'vim')
        self.assertEqual(keys['push.default'], 'simple')
        self.assertEqual(keys['alias.st'], 'status')
        for key, value in keys.items():
            if key.startswith('alias.'):
                self.assertTrue(shlex.split(value), key)
        with tempfile.TemporaryDirectory(prefix='cx-git-defaults-') as directory:
            self.command(['git', 'init', directory])
            paths = ['.DS_Store', 'Thumbs.db', '.sample.swp', 'sample.txt~']
            ignored = self.command(['git', '-C', directory, 'check-ignore', *paths])
            self.assertEqual(set(ignored.splitlines()), set(paths))
            self.assertEqual(run(['git', '-C', directory, 'check-ignore', 'source.py']).returncode, 1)

    def test_git_diff_and_status_use_ayu_colors(self):
        with tempfile.TemporaryDirectory(prefix='cx-git-colors-') as directory:
            base = Path(directory)
            before, after = base / 'before', base / 'after'
            before.write_text('removed line\n')
            after.write_text('added line\n')
            diff = run(['git', 'diff', '--no-index', '--color=always', str(before), str(after)])
            self.assertEqual(diff.returncode, 1, diff.stdout + diff.stderr)
            self.assertIn('38;2;170;217;76m+', diff.stdout)
            self.assertIn('38;2;170;217;76madded line', diff.stdout)
            self.assertIn('38;2;240;113;120m-removed line', diff.stdout)
            self.assertIn('38;2;230;180;80m@@', diff.stdout)
            self.command(['git', 'init', directory])
            status = self.command(['git', '-C', directory, '-c', 'color.ui=always', 'status', '--short'])
            self.assertIn('38;2;230;180;80m??', status)
            plain = self.command(['git', '-C', directory, 'status', '--short'])
            self.assertNotIn('\x1b[', plain)

    def test_ls_colors_reach_interactive_file_listings(self):
        with tempfile.TemporaryDirectory(prefix='cx-ls-colors-') as directory:
            base = Path(directory)
            folder, executable, link = base / 'folder', base / 'script', base / 'link'
            folder.mkdir()
            executable.write_text('#!/bin/sh\nexit 0\n')
            executable.chmod(0o755)
            link.symlink_to(executable)
            output = self.command(['bash', '-ic',
                'test -n "$LS_COLORS" && ls --color=always --directory "$@"',
                'cx-ls-colors', str(folder), str(executable), str(link)])
            self.assertIn('38;2;191;189;182m', output)
            self.assertIn('38;2;170;217;76m', output)
            self.assertIn('38;2;230;180;80m', output)

    def test_eza_theme_colors_metadata_and_respects_file_color_overrides(self):
        with tempfile.TemporaryDirectory(prefix='cx-eza-colors-') as directory:
            base = Path(directory)
            (base / 'sample.txt').write_text('example\n')
            (base / 'folder').mkdir()
            env = dict(os.environ)
            for key in ('LS_COLORS', 'EZA_COLORS', 'EZA_CONFIG_DIR', 'NO_COLOR'):
                env.pop(key, None)
            args = ['eza', '--color=always', '--long', '--group', '--header', directory]
            result = run(args, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stderr, '')
            self.assertIn('38;2;230;180;80', result.stdout)
            self.assertIn('38;2;116;116;116', result.stdout)
            self.assertIn('38;2;191;189;182', result.stdout)
            env['LS_COLORS'] = 'di=38;2;1;2;3'
            overridden = self.command(args, env=env)
            self.assertIn('38;2;1;2;3', overridden)
            self.assertIn('38;2;230;180;80', overridden)

    def test_agent_settings_have_expected_display_and_permission_values(self):
        claude = json.loads((HOME / '.claude/settings.json').read_text())
        self.assertEqual(claude['permissions']['defaultMode'], 'manual')
        self.assertNotIn('allow', claude['permissions'])
        self.assertEqual(claude['outputStyle'], 'Explanatory')
        self.assertIs(claude['showTurnDuration'], True)
        self.assertEqual(claude['preferredNotifChannel'], 'terminal_bell')
        agy = json.loads((HOME / '.gemini/antigravity-cli/settings.json').read_text())
        self.assertEqual(agy['toolPermission'], 'request-review')
        self.assertEqual(agy['colorScheme'], 'terminal')
        self.assertIs(agy['notifications'], True)
        cli = json.loads((HOME / '.config/opencode/cli.json').read_text())
        self.assertEqual(cli['theme'], {'name': 'ayu', 'mode': 'dark'})
        self.assertEqual(cli['session']['permissions'], 'prompt')
        self.assertEqual(cli['attention'], {'notifications': True, 'sound': False})
        self.assertEqual(cli['diffs'], {'view': 'auto', 'wrap': 'word', 'tree': True})
        self.assertEqual(cli['mini'], {'footer': 'show', 'turn_summary': 'show'})
        codex = (HOME / '.codex/config.toml').read_text()
        self.assertIn('approval_policy = "on-request"', codex)
        self.assertIn('sandbox_mode = "danger-full-access"', codex)
        for path in (HOME / '.claude/settings.json', HOME / '.gemini/antigravity-cli/settings.json',
                     HOME / '.config/opencode/opencode.json', HOME / '.config/opencode/cli.json'):
            data = json.loads(path.read_text())
            self.assertNotIn('model', data)
            self.assertNotIn('apiKey', data)
            self.assertNotIn('env', data)
            self.assertNotIn('hooks', data)
            self.assertNotIn('provider', data)

    def claude_settings_report(self):
        result = run(['claude', 'doctor'], timeout=30)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn('Claude Code doctor', output)
        return output

    def test_claude_native_diagnostic_accepts_defaults_and_detects_invalid_settings(self):
        self.assertNotIn('Invalid settings', self.claude_settings_report())
        path = HOME / '.claude/settings.json'
        original = path.read_bytes()
        try:
            data = json.loads(original)
            data['showTurnDuration'] = 'not a boolean'
            path.write_text(json.dumps(data))
            output = self.claude_settings_report()
            self.assertIn('Invalid settings', output)
            self.assertIn('showTurnDuration', output)
        finally:
            path.write_bytes(original)

    def opencode_terminal(self, seconds=6):
        pid, master = pty.fork()
        if pid == 0:
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 120, 0, 0))
                os.execvpe('opencode', ['opencode'], dict(os.environ,
                    TERM='xterm-256color', COLORTERM='truecolor'))
            except BaseException:
                os._exit(127)
        output = bytearray()
        started = time.monotonic()
        try:
            while time.monotonic() - started < seconds:
                if not select.select([master], [], [], 0.1)[0]:
                    continue
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
                for query, response in ((b'\x1b[6n', b'\x1b[1;1R'),
                                        (b'\x1b[c', b'\x1b[?1;2c'),
                                        (b'\x1b]11;?\x07', b'\x1b]11;rgb:0000/0000/0000\x07')):
                    if query in chunk:
                        os.write(master, response)
            return output.decode(errors='replace')
        finally:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
            os.close(master)

    def assert_opencode_loaded_ayu(self, output):
        plain = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', output)
        self.assertIn('Ask anything', plain, 'OpenCode did not render its input prompt')
        self.assertIn('\x1b]12;#bfbdb6\x07', output,
                      'OpenCode did not apply the configured Ayu cursor color')

    def test_opencode_native_client_loads_cli_config_and_detects_fallback(self):
        self.assert_opencode_loaded_ayu(self.opencode_terminal())
        path = HOME / '.config/opencode/cli.json'
        original = path.read_bytes()
        try:
            data = json.loads(original)
            data['attention'] = 'not an object'
            path.write_text(json.dumps(data))
            output = self.opencode_terminal()
            plain = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', output)
            self.assertIn('Ask anything', plain, 'OpenCode did not render its input prompt')
            with self.assertRaises(AssertionError):
                self.assert_opencode_loaded_ayu(output)
        finally:
            path.write_bytes(original)

    def test_shell_completion_and_cli_theme_options_are_usable(self):
        output = self.command(['bash', '-ic',
            'test "$EDITOR" = vim && test "$VISUAL" = vim && '
            'shopt -q histappend && complete -p git && '
            'declare -F fzf-file-widget && '
            'test -r "$FZF_DEFAULT_OPTS_FILE" && echo SHELL_VERIFIED'])
        self.assertIn('SHELL_VERIFIED', output)
        result = self.command(['bash', '-ic', 'printf "probe\\n" | fzf --filter=probe'])
        self.assertEqual(result.strip(), 'probe')
        self.command(['bat', '--paging=never', str(HOME / '.gitconfig')])

    def test_vim_honors_project_editorconfig_and_has_no_gutter_underline(self):
        with tempfile.TemporaryDirectory(prefix='cx-vim-defaults-') as directory:
            base = Path(directory)
            (base / '.editorconfig').write_text('root = true\n[*]\nindent_style = space\nindent_size = 6\nend_of_line = crlf\n')
            sample = base / 'sample.yaml'
            sample.write_text('key: value\n')
            script = base / 'check.vim'
            script.write_text('\n'.join([
                'let g:netrw_dirhistmax = 0',
                'edit ' + str(sample),
                "call assert_equal(6, &shiftwidth)",
                "call assert_equal('dos', &fileformat)",
                "call assert_equal(1, &undofile)",
                "call assert_true(isdirectory(expand('~/.vim/undo')))",
                "call assert_true(isdirectory(expand('~/.vim/swap')))",
                "call assert_true(isdirectory(expand('~/.vim/backup')))",
                "call assert_equal('#000000', synIDattr(hlID('Normal'), 'bg#'))",
                "call assert_notequal('1', synIDattr(hlID('CursorLineNr'), 'underline', 'cterm'))",
                "call assert_notequal('1', synIDattr(hlID('CursorLine'), 'underline', 'term'))",
                "call assert_equal(':25Lexplore!<CR>', maparg('\\e', 'n'))",
                '25Lexplore! ' + str(base),
                "call assert_equal('netrw', &filetype)",
                "call assert_equal(2, winnr('$'))",
                "call assert_true(win_screenpos(win_getid())[1] > win_screenpos(win_getid(1))[1])",
                "if !empty(v:errors) | echo join(v:errors, '\\n') | cquit 1 | endif",
                'qa!', '']))
            result = run(['vim', '-u', str(HOME / '.vimrc'), '-n', '-i', 'NONE', '-es', '-V1', '-S', str(script)])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('W22:', result.stderr)

    def test_tmux_theme_and_shortcuts_load(self):
        socket = 'cx-defaults-%s' % os.getpid()
        base = ['tmux', '-L', socket]
        try:
            self.command(base + ['-f', str(HOME / '.tmux.conf'), 'new-session', '-d', '-s', 'cx-defaults'])
            style = self.command(base + ['show-options', '-g', 'status-style'])
            self.assertIn('bg=#202020', style)
            self.assertIn('fg=#e6b450', style)
            self.assertIn('1', self.command(base + ['show-options', '-g', 'base-index']))
            for key in ('|', '-', 'r', 'c', 'H', 'J', 'K', 'L'):
                self.command(base + ['list-keys', '-T', 'prefix', key])
            self.command(base + ['list-keys', '-T', 'copy-mode-vi', 'y'])
        finally:
            run(base + ['kill-server'])

    def test_user_edits_survive_a_second_start(self):
        paths = [HOME / name for name in ('.bashrc', '.gitconfig', '.vimrc', '.tmux.conf',
                    '.config/eza/theme.yml', '.config/fzf/config', '.config/bat/config')]
        for path in paths:
            with path.open('a') as file:
                file.write('\n# User customization marker\n' if path.name != '.vimrc'
                           else '\n" User customization marker\n')
        for name, key, value in (
            ('.claude/settings.json', 'outputStyle', 'default'),
            ('.gemini/antigravity-cli/settings.json', 'notifications', False),
            ('.config/opencode/opencode.json', 'update', 'notify'),
            ('.config/opencode/cli.json', 'attention', {'notifications': False, 'sound': True}),
        ):
            path = HOME / name
            data = json.loads(path.read_text())
            data[key] = value
            path.write_text(json.dumps(data))
            paths.append(path)
        codex = HOME / '.codex/config.toml'
        with codex.open('a') as file:
            file.write('\n# User customization marker\n')
        paths.append(codex)
        before = {path: hashlib.sha256(path.read_bytes()).digest() for path in paths}
        self.command(['agentainer-entrypoint', 'true'])
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).digest() for path in paths})


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DefaultsTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print('DEFAULTS_VERIFIED')
