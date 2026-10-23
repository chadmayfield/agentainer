"""Run only inside a disposable Agentainer container, with no host home mounted."""
import base64
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time

COLS, ROWS = 120, 32
WORKSPACE = Path('/workspace')
FIXTURES = Path('/fixtures')
EPOCH = 1792411200


def checked(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30, **kwargs)
    if result.returncode:
        raise RuntimeError('%s: %s' % (args[0], result.stderr or result.stdout))
    return result.stdout


def terminal(args, markers, interactive=False, send=None, send_when=b'@agentainer', timeout=12,
             cols=COLS, rows=ROWS, after_ready=None, ready=None):
    """Capture a live PTY frame, before interactive programs restore their screen."""
    pid, master = pty.fork()
    if pid == 0:
        try:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
            os.execvpe(args[0], args, os.environ)
        except BaseException:
            os._exit(127)
    output = bytearray()
    status = None
    sent = send is None
    acted = after_ready is None
    responses = {
        b'\x1b[6n': b'\x1b[1;1R',
        b'\x1b[c': b'\x1b[?1;2c',
        b'\x1b[>c': b'\x1b[>0;4000;0c',
        b'\x1b[>0c': b'\x1b[>0;4000;0c',
        b'\x1b]11;?\x07': b'\x1b]11;rgb:0000/0000/0000\x07',
        b'\x1b]11;?\x1b\\': b'\x1b]11;rgb:0000/0000/0000\x1b\\',
    }
    answered = {query: 0 for query in responses}
    def content_present(expected=markers):
        plain = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', bytes(output))
        return all(text.encode() in plain for text in expected)

    started = changed = time.monotonic()
    try:
        while time.monotonic() - started < timeout:
            readable, _, _ = select.select([master], [], [], 0.05)
            if readable:
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    chunk = b''
                if chunk:
                    output.extend(chunk)
                    changed = time.monotonic()
                    for query, response in responses.items():
                        count = output.count(query)
                        if count > answered[query]:
                            os.write(master, response * (count - answered[query]))
                            answered[query] = count
                    if not sent and send_when in output:
                        os.write(master, send)
                        sent = True
            if not acted and content_present(ready or markers) and time.monotonic() - changed > 0.4:
                after_ready()
                acted = True
                changed = time.monotonic()
            child, child_status = os.waitpid(pid, os.WNOHANG)
            if child:
                status = child_status
                if interactive:
                    raise RuntimeError('interactive program exited before capture: ' + str(args))
                if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
                    raise RuntimeError('terminal command failed: ' + output[-2000:].decode(errors='replace'))
                break
            if interactive and sent and acted and content_present():
                if time.monotonic() - changed > 0.4 and time.monotonic() - started > 0.7:
                    break
        else:
            raise RuntimeError('terminal capture timed out: ' + str(args) + '\n' + output[-2000:].decode(errors='replace'))
        if not content_present():
            raise RuntimeError('terminal content missing: ' + str(markers))
        return base64.b64encode(output).decode('ascii')
    finally:
        os.close(master)
        if status is None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)


def main():
    home = Path(tempfile.mkdtemp(prefix='cx-visual-home-'))
    os.environ.update(HOME=str(home), TERM='xterm-256color', COLORTERM='truecolor',
                      LANG='C.UTF-8', LC_ALL='C.UTF-8', TZ='UTC',
                      COLUMNS=str(COLS), LINES=str(ROWS),
                      GIT_AUTHOR_NAME='Example Developer', GIT_AUTHOR_EMAIL='developer@example.com',
                      GIT_COMMITTER_NAME='Example Developer', GIT_COMMITTER_EMAIL='developer@example.com',
                      GIT_AUTHOR_DATE='2026-10-19T12:00:00+00:00',
                      GIT_COMMITTER_DATE='2026-10-19T12:00:00+00:00')
    checked(['agentainer-entrypoint', 'true'])
    if not (home / '.config/agentainer/shell-theme.bash').is_file():
        raise RuntimeError('image has no Agentainer color defaults; use --source-defaults for checkout defaults')
    os.chdir(WORKSPACE)
    for name in ('sample.py', 'settings.yaml', 'README.md'):
        shutil.copyfile(FIXTURES / name, WORKSPACE / name)
    (WORKSPACE / 'scripts').mkdir()
    shutil.copyfile(FIXTURES / 'sample.py', WORKSPACE / 'scripts/example.py')
    (WORKSPACE / 'run-example').write_text('#!/bin/sh\nprintf "Example only\\n"\n')
    (WORKSPACE / 'run-example').chmod(0o755)
    (WORKSPACE / 'current.py').symlink_to('sample.py')
    # Git history belongs only to the disposable fixture, with generic identity and dates.
    checked(['git', 'init', '.'])
    checked(['git', 'add', 'sample.py', 'settings.yaml', 'README.md'])
    checked(['git', 'commit', '-m', 'Add example files'])
    sample = WORKSPACE / 'sample.py'
    sample.write_text(sample.read_text().replace('DEBUG = False', 'DEBUG = True').replace('RETRIES = 3', 'RETRIES = 5'))
    settings = WORKSPACE / 'settings.yaml'
    settings.write_text(settings.read_text().replace('retries: 3', 'retries: 5'))
    checked(['git', 'add', 'settings.yaml'])
    (WORKSPACE / 'README.md').unlink()
    (WORKSPACE / 'notes.txt').write_text('Review the Agentainer colors.\n')
    for path in WORKSPACE.iterdir():
        if path.name != '.git':
            os.utime(path, (EPOCH, EPOCH), follow_symlinks=False)

    captures = []

    def add(identifier, title, description, args, expected, cols=COLS, rows=ROWS,
            backgrounds=(), absent=(), **kwargs):
        captures.append(dict(id=identifier, title=title, description=description,
                             output=terminal(args, expected, cols=cols, rows=rows, **kwargs),
                             expectedText=expected, expectedBackgrounds=list(backgrounds),
                             absentText=list(absent), cols=cols, rows=rows))
        print('Captured ' + identifier, file=sys.stderr)

    add('shell', 'Shell and ls', 'Amber user, blue hostname, muted green directories, amber links, green executables.',
        ['bash', '--noprofile', '--rcfile', str(home / '.bashrc'), '-i'],
        ['@agentainer', 'sample.py', 'run-example'], interactive=True, send=b'ls --color=always\n')
    add('eza', 'eza', 'File types, permissions, owners, sizes, dates and Git indicators.',
        ['bash', '-ic', 'eza --color=always --long --group --header --git --icons=never'],
        ['Permissions', 'sample.py', 'settings.yaml'])
    add('eza-tree', 'eza tree', 'Nested files, directories, executables and symbolic links.',
        ['bash', '-ic', 'eza --color=always --tree --level=2 --icons=never'],
        ['scripts', 'example.py', 'current.py'])
    errors = Path(tempfile.mkdtemp(prefix='cx-visual-links-'))
    (errors / 'target.txt').write_text('Existing target\n')
    (errors / 'working-link').symlink_to('target.txt')
    (errors / 'missing-link').symlink_to('missing-target')
    for path in errors.iterdir():
        os.utime(path, (EPOCH, EPOCH), follow_symlinks=False)
    add('eza-broken', 'eza broken symbolic link', 'A working link beside an orphaned link and its missing target.',
        ['bash', '-ic', 'eza --color=always --long --header "$1"', 'cx-links', str(errors)],
        ['working-link', 'missing-link', 'missing-target', '19 Oct 12:00'])
    add('git-status', 'Git status', 'Staged changes, working-tree changes, deletions and untracked files.',
        ['bash', '-ic', 'git -c color.ui=always status --short --branch'],
        ['sample.py', 'settings.yaml', 'notes.txt'])
    add('git-diff', 'Git diff', 'Amber hunk headings, gray context, green additions and red removals.',
        ['bash', '-ic', 'git --no-pager diff --color=always -- sample.py'],
        ['DEBUG', 'RETRIES'])
    add('git-staged', 'Git staged diff', 'The diff of staged changes, separate from working-tree edits.',
        ['bash', '-ic', 'git --no-pager diff --cached --color=always'],
        ['settings.yaml', 'retries'])
    conflict = Path(tempfile.mkdtemp(prefix='cx-visual-conflict-'))
    git = ['git', '-C', str(conflict)]
    checked(git + ['init', '.'])
    conflict_file = conflict / 'conflict.txt'
    conflict_file.write_text('base value\n')
    checked(git + ['add', 'conflict.txt'])
    checked(git + ['commit', '-m', 'Add conflict fixture'])
    checked(git + ['checkout', '-b', 'incoming'])
    conflict_file.write_text('incoming value\n')
    checked(git + ['commit', '-am', 'Change incoming value'])
    checked(git + ['checkout', 'main'])
    conflict_file.write_text('ours value\n')
    checked(git + ['commit', '-am', 'Change current value'])
    merge = subprocess.run(git + ['merge', '--no-edit', 'incoming'], capture_output=True, text=True, timeout=30)
    if merge.returncode != 1 or '<<<<<<< HEAD' not in conflict_file.read_text():
        raise RuntimeError('fixture did not produce the expected merge conflict')
    add('git-conflict', 'Git merge conflict', 'A real unresolved merge with current and incoming conflict markers.',
        git + ['--no-pager', 'diff', '--color=always'],
        ['<<<<<<< HEAD', '>>>>>>> incoming', 'ours value', 'incoming value'])
    add('bat', 'bat', 'The built-in ANSI theme, shown with the reference terminal palette.',
        ['bash', '-ic', 'bat --color=always --paging=never sample.py'],
        ['sample.py', 'describe'])
    add('bat-yaml', 'bat YAML', 'Comments, mappings, strings, booleans and numbers in the ANSI theme.',
        ['bash', '-ic', 'bat --color=always --paging=never settings.yaml'],
        ['settings.yaml', 'application'])
    add('fzf-idle', 'fzf before filtering', 'All candidates with an empty search prompt and the current row selected.',
        ['bash', '-ic', "printf '%s\\n' sample.py settings.yaml scripts/example.py notes.txt | fzf --header='Example files'"],
        ['sample.py', 'settings.yaml', 'Example files'], interactive=True)
    add('fzf', 'fzf', 'Black background, charcoal selection, amber prompt and matching highlights.',
        ['bash', '-ic', "printf '%s\\n' sample.py settings.yaml scripts/example.py notes.txt | fzf --query=py --header='Example files'"],
        ['sample.py', 'example.py', 'Example files'], interactive=True)
    add('fzf-selected', 'fzf multiple selections', 'Both matching files selected, showing selected and current rows.',
        ['bash', '-ic', "printf '%s\\n' sample.py settings.yaml scripts/example.py notes.txt | fzf --multi --sync --bind=start:select-all --query=py --header='Example files'"],
        ['sample.py', 'example.py', '┃'], interactive=True)
    add('fzf-empty', 'fzf without matches', 'An unmatched query with a zero-result count and no candidate rows.',
        ['bash', '-ic', "printf '%s\\n' sample.py settings.yaml scripts/example.py notes.txt | fzf --query=unmatched --header='Example files'"],
        ['unmatched', '0/4', 'Example files'], interactive=True, absent=['sample.py', 'settings.yaml', 'example.py'])
    add('vim', 'Vim', 'Syntax colors, line numbers, gutter, current line and slate-blue status line.',
        ['vim', '-n', '-i', 'NONE', 'sample.py'], ['sample.py', 'describe'], interactive=True)

    add('vim-yaml', 'Vim YAML', 'YAML syntax with two-space indentation and the current-line gutter.',
        ['vim', '-n', '-i', 'NONE', 'settings.yaml'], ['settings.yaml', 'application'], interactive=True)
    add('vim-browser', 'Vim file browser', 'The right-hand file browser alongside the Python buffer.',
        ['vim', '-n', '-i', 'NONE', 'sample.py', '-c', '25Lexplore! /workspace'],
        ['sample.py', 'settings.yaml'], interactive=True)

    review = WORKSPACE / 'review.py'
    review.write_text('from pathlib import Path\n\n# Trailing whitespace' + '   ' +
                      '\nselection = "Selected text"\n\n' + sample.read_text())
    add('vim-search', 'Vim search and whitespace', 'Highlighted path matches, trailing-space dots and the current-line gutter.',
        ['vim', '-n', '-i', 'NONE', 'review.py', '-c', "let @/ = 'path'", '-c', 'set hlsearch'],
        ['review.py', 'Trailing whitespace...', 'Path'], interactive=True, backgrounds=['#e6b450', '#141414'])
    add('vim-selection', 'Vim visual selection', 'Character selection alongside the cursor line and visible trailing whitespace.',
        ['vim', '-n', '-i', 'NONE', 'review.py', '-c', 'normal! 4G0v$'],
        ['review.py', 'Selected text', 'VISUAL', 'def describe(path: Path) -> str:'], interactive=True, backgrounds=['#333333'])
    add('vim-browser-narrow', 'Vim browser at 80 columns', 'The right-hand browser and editing buffer at 80 columns by 24 rows.',
        ['vim', '-n', '-i', 'NONE', 'sample.py', '-c', '25Lexplore! /workspace'],
        ['sample.py', 'settings.yaml'], interactive=True, cols=80, rows=24)

    tmux = ['tmux' , '-L', 'cx-visual']
    try:
        checked(tmux + ['-f', str(home / '.tmux.conf'), 'new-session', '-d', '-s', 'main', '-n', 'workspace'])
        checked(tmux + ['set-option', '-g', 'status-right', 'Mon 19 Oct 12:00'])
        add('tmux-single', 'tmux single pane', 'One window and one pane with the charcoal and amber status bar.',
            tmux + ['attach-session', '-t', 'main'], ['workspace', '@agentainer', 'Mon 19 Oct'], interactive=True)
        checked(tmux + ['new-window', '-d', '-n', 'logs'])
        checked(tmux + ['split-window', '-h'])
        add('tmux', 'tmux', 'Split panes and multiple windows with the charcoal and amber status bar. Clock fixed for review.',
            tmux + ['attach-session', '-t', 'main'], ['workspace', 'logs', 'Mon 19 Oct'], interactive=True)
        pane = 'main:1.1'
        checked(tmux + ['select-pane', '-t', pane])
        checked(tmux + ['send-keys', '-t', pane,
                        "printf '%s\\n' 'Copy mode example' 'Select this line' 'Another readable line'", 'Enter'])

        def select_copy_text():
            checked(tmux + ['copy-mode', '-t', pane])
            for action in ('cursor-up', 'start-of-line', 'begin-selection', 'end-of-line'):
                checked(tmux + ['send-keys', '-X', '-t', pane, action])
            if checked(tmux + ['display-message', '-p', '-t', pane, '#{selection_present}']).strip() != '1':
                raise RuntimeError('tmux copy-mode selection did not start')

        add('tmux-copy', 'tmux copy-mode selection', 'Selected terminal text in the configured copy-mode colors.',
            tmux + ['attach-session', '-t', 'main'], ['Copy mode example', 'Another readable line'],
            interactive=True, ready=['Copy mode example', 'Another readable line'],
            after_ready=select_copy_text, backgrounds=['#ffb454'])
        checked(tmux + ['send-keys', '-X', '-t', pane, 'cancel'])
        checked(tmux + ['select-window', '-t', 'main:2'])
        checked(tmux + ['select-window', '-t', 'main:1'])

        def mark_activity():
            checked(tmux + ['send-keys', '-t', 'main:2', "printf 'Background activity\\n'", 'Enter'])
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if checked(tmux + ['display-message', '-p', '-t', 'main:2', '#{window_activity_flag}']).strip() == '1':
                    return
                time.sleep(0.05)
            raise RuntimeError('background window did not record activity')

        add('tmux-activity', 'tmux window activity', 'The background logs window has a verified activity flag and highlighted status entry.',
            tmux + ['attach-session', '-t', 'main'], ['workspace', 'logs#', 'Mon 19 Oct'],
            interactive=True, ready=['workspace', 'logs'], after_ready=mark_activity)
        add('tmux-narrow', 'tmux split panes at 80 columns', 'Split panes, window names and the clock at 80 columns by 24 rows.',
            tmux + ['attach-session', '-t', 'main'], ['workspace', 'logs', 'Mon 19 Oct'],
            interactive=True, cols=80, rows=24)
    finally:
        subprocess.run(tmux + ['kill-server'], capture_output=True, timeout=10)
    versions = {tool: checked([tool, '--version']).splitlines()[0]
                for tool in ('eza', 'git', 'bat', 'fzf')}
    print(json.dumps(dict(schema=1, captures=captures, tools=versions)))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('visual scenarios: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
