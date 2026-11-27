"""Exercise the bundled abtop release offline without agent credentials."""
import json
import os
from pathlib import Path
import subprocess
import tempfile


def require(condition, message="abtop check failed"):
    # A bare assert disappears under python -O or PYTHONOPTIMIZE.
    if not condition:
        raise SystemExit(message)

pins = dict(line.split('=', 1) for line in
            Path('/usr/local/share/agentainer/versions.env').read_text().splitlines()
            if line and not line.startswith('#'))
with tempfile.TemporaryDirectory(prefix='cx-abtop-') as directory:
    home = Path(directory)
    env = dict(os.environ, HOME=directory, XDG_CONFIG_HOME=str(home / '.config'),
               XDG_CACHE_HOME=str(home / '.cache'), XDG_DATA_HOME=str(home / '.local/share'))

    def run(*args):
        return subprocess.run(['abtop', *args], env=env, check=True,
                              capture_output=True, text=True, timeout=30).stdout

    require(run('--version').strip() == 'abtop ' + pins['ABTOP_VERSION'])
    for args in (('--json',), ('--demo', '--json')):
        snapshot = json.loads(run(*args))
        require(isinstance(snapshot['sessions'], list))
        require(isinstance(snapshot['rate_limits'], list))
        require(isinstance(snapshot['orphan_ports'], list))
        require(isinstance(snapshot['host'], dict))
        if '--demo' in args:
            require(snapshot['sessions'], 'demo snapshot has no sessions')
    require(not (home / '.claude/settings.json').exists(), 'snapshot installed Claude settings')
print('ABTOP_VERIFIED')
