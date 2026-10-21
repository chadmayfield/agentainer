"""Capture generic terminal scenarios from an existing image. No image build or host home mount."""
import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ('shell', 'eza', 'eza-tree', 'eza-broken', 'git-status', 'git-diff',
             'git-staged', 'git-conflict', 'bat', 'bat-yaml', 'fzf-idle', 'fzf',
             'fzf-selected', 'fzf-empty', 'vim', 'vim-yaml', 'vim-browser',
             'vim-search', 'vim-selection', 'vim-browser-narrow', 'tmux-single',
             'tmux', 'tmux-copy', 'tmux-activity', 'tmux-narrow')
NARROW_SCENARIOS = {'vim-browser-narrow', 'tmux-narrow'}


def validate(document):
    if document.get('schema') != 1:
        raise ValueError('unsupported capture schema')
    captures = document.get('captures', [])
    if [item.get('id') for item in captures] != list(SCENARIOS):
        raise ValueError('missing, duplicated or reordered capture scenarios')
    for item in captures:
        expected = (80, 24) if item['id'] in NARROW_SCENARIOS else (120, 32)
        if (item.get('cols'), item.get('rows')) != expected:
            raise ValueError('unexpected terminal dimensions')
        try:
            raw = base64.b64decode(item['output'], validate=True)
        except (KeyError, ValueError, binascii.Error) as error:
            raise ValueError('invalid terminal recording') from error
        if b'\x1b[' not in raw:
            raise ValueError('recording has no terminal formatting: ' + item['id'])
        if not item.get('expectedText'):
            raise ValueError('recording has no visible-content checks')
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', default=os.environ.get('RUNTIME', 'podman'))
    parser.add_argument('--image', default=os.environ.get('IMAGE', 'localhost/agentainer:dev'))
    parser.add_argument('--source-defaults', action='store_true',
                        help="overlay this checkout's home defaults onto the existing image, read-only")
    args = parser.parse_args(argv)
    destination = ROOT / 'artifacts/visual'
    name = 'cx-visual-' + uuid.uuid4().hex[:12]
    command = [args.runtime, 'run', '--rm', '--pull=never', '--name', name,
               '--network', 'none', '--hostname', 'agentainer',
               '--volume', str(Path(__file__).resolve().parent / 'fixtures') + ':/fixtures:ro']
    if args.source_defaults:
        command += ['--volume', str(ROOT / 'rootfs/etc/agentainer/home') + ':/etc/agentainer/home:ro',
                    '--volume', str(ROOT / 'rootfs/etc/agentainer/AGENTS.md') + ':/etc/agentainer/AGENTS.md:ro']
    command += ['--entrypoint', 'python3', args.image, '/fixtures/scenarios.py']
    temporary = None
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout or 'container capture failed')
        document = validate(json.loads(result.stdout))
        document['image'] = args.image
        document['defaults'] = 'checkout overlay' if args.source_defaults else 'image'
        destination.mkdir(parents=True, exist_ok=True)
        # An interrupted capture must not replace the last complete recording.
        with tempfile.NamedTemporaryFile(mode='w', prefix='cx-capture-', dir=destination,
                                         delete=False) as file:
            temporary = Path(file.name)
            json.dump(document, file, indent=2)
            file.write('\n')
        temporary.replace(destination / 'captures.json')
        print('Captured %d scenarios in %s' % (len(document['captures']), destination / 'captures.json'))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('visual capture: ' + str(error), file=sys.stderr)
        return 1
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        # Also removes the container created by this run if the client timed out or was interrupted.
        try:
            subprocess.run([args.runtime, 'rm', '-f', name], capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            pass


if __name__ == '__main__':
    raise SystemExit(main())
