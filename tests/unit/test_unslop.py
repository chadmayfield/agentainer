"""Check immutable skill downloads and fail-closed installation without network access."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('unslop_bump', ROOT / 'scripts/bump_versions.py')
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)


class UnslopResolverTests(unittest.TestCase):
    def test_resolves_skill_and_license_from_one_immutable_commit(self):
        commit = 'a' * 40
        prefix = 'https://raw.githubusercontent.com/cursor/plugins/' + commit + '/pstack/'
        responses = {prefix + 'skills/unslop/SKILL.md': b'skill bytes\n', prefix + 'LICENSE': b'license bytes\n'}
        with patch.object(bump, 'fetch_json', return_value=[{'sha': commit}]) as metadata, \
                patch.object(bump, 'fetch_bytes', side_effect=responses.__getitem__) as fetch:
            pins = bump.r_unslop()
        metadata.assert_called_once_with('https://api.github.com/repos/cursor/plugins/commits?path=pstack&per_page=1')
        self.assertEqual(pins, {'UNSLOP_COMMIT': commit,
                         'UNSLOP_SHA256': hashlib.sha256(responses[prefix + 'skills/unslop/SKILL.md']).hexdigest(),
                         'UNSLOP_LICENSE_SHA256': hashlib.sha256(responses[prefix + 'LICENSE']).hexdigest()})
        self.assertEqual({call.args[0] for call in fetch.call_args_list}, set(responses))
        self.assertIn(bump.r_unslop, bump.RESOLVERS)
        for key, value in pins.items():
            self.assertIsNone(bump.invalid(key, value))

    def test_refuses_unsafe_or_abbreviated_commits_before_download(self):
        for commit in ('main', 'a' * 12, 'A' * 40, '../main', 'a' * 40 + ';id'):
            with self.subTest(commit=commit), \
                    patch.object(bump, 'fetch_json', return_value=[{'sha': commit}]), \
                    patch.object(bump, 'fetch_bytes') as fetch:
                with self.assertRaises(bump.LookupFailed):
                    bump.r_unslop()
                fetch.assert_not_called()
                self.assertIsNotNone(bump.invalid('UNSLOP_COMMIT', commit))


@unittest.skipUnless(shutil.which('sha256sum'), 'installer requires sha256sum')
class UnslopInstallerTests(unittest.TestCase):
    def install(self, corrupt=None):
        with tempfile.TemporaryDirectory(prefix='cx-unslop-install-') as directory:
            base = Path(directory)
            output = base / 'installed'
            bindir = base / 'bin'
            bindir.mkdir()
            contents = {'SKILL.md': b'---\nname: unslop\ndescription: Clean writing.\n---\nRules.\n',
                        'LICENSE': b'MIT License\nCopyright fixture\n'}
            for name, data in contents.items():
                (base / name).write_bytes(data)
            curl = bindir / 'curl'
            curl.write_text('#!/bin/sh\nout=\nwhile [ "$#" -gt 0 ]; do\n'
                            'case "$1" in -o) out=$2; shift ;; esac\nurl=$1\nshift\ndone\n'
                            'printf "%s\\n" "$url" >>"$CX_BASE/urls"\n'
                            'cp "$CX_BASE/${url##*/}" "$out"\n')
            curl.chmod(0o755)
            script = base / 'install.sh'
            script.write_text((ROOT / 'build/install-unslop.sh').read_text()
                              .replace('/usr/local/lib/agentainer-build/fetch.sh', str(ROOT / 'build/fetch.sh'))
                              .replace('/usr/local/share/agentainer/skills/unslop', str(output)))
            env = dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH'], CX_BASE=str(base),
                       UNSLOP_COMMIT='a' * 40, TMPDIR=str(base))
            for name, key in (('SKILL.md', 'UNSLOP_SHA256'), ('LICENSE', 'UNSLOP_LICENSE_SHA256')):
                env[key] = '0' * 64 if corrupt == name else hashlib.sha256(contents[name]).hexdigest()
            result = subprocess.run(['sh', str(script)], env=env, capture_output=True, text=True, timeout=10)
            if corrupt:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('checksum mismatch', result.stderr)
                self.assertFalse(output.exists(), 'installed files before verifying both downloads')
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                for name, data in contents.items():
                    self.assertEqual((output / name).read_bytes(), data)
                    self.assertEqual((output / name).stat().st_mode & 0o777, 0o644)
                prefix = 'https://raw.githubusercontent.com/cursor/plugins/' + 'a' * 40 + '/pstack/'
                self.assertEqual((base / 'urls').read_text().splitlines(),
                                 [prefix + 'skills/unslop/SKILL.md', prefix + 'LICENSE'])

    def test_preserves_upstream_skill_and_license_bytes(self):
        self.install()

    def test_rejects_corrupt_skill_or_license_before_installing(self):
        for name in ('SKILL.md', 'LICENSE'):
            with self.subTest(name=name):
                self.install(corrupt=name)
