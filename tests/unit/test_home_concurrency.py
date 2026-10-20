"""Exercise writers in separate processes on one home directory."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]


class HomeConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cx-home-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        (self.home / ".agentainer").mkdir(parents=True)
        self.processes = []
        self.addCleanup(self.stop_processes)

    def stop_processes(self):
        for p in self.processes:
            if p.poll() is None:
                p.kill()
            p.communicate()

    def start(self, argv, **env):
        p = subprocess.Popen(argv, env=dict(os.environ, HOME=str(self.home), CX_TMP=str(self.base), **env),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.processes.append(p)
        return p

    def wait_file(self, name):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if (self.base / name).exists():
                return
            time.sleep(0.01)
        self.fail("process did not reach %s" % name)

    def complete(self, p):
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, out + err)
        return out, err

    @unittest.skipUnless(shutil.which("flock"), "entrypoint requires Linux flock")
    def test_concurrent_seed_and_release_tracking_keep_newest_default(self):
        steps = ROOT / "rootfs/usr/local/lib/agentainer/entrypoint.d"
        entrypoint = (ROOT / "rootfs/usr/local/bin/agentainer-entrypoint").read_text()
        bindir = self.base / "bin"
        bindir.mkdir()
        cp = bindir / "cp"
        cp.write_text("""#!/bin/sh
case "$1" in
*/older/AGENTS.md)
    touch "$CX_TMP/copy-paused"
    while [ ! -e "$CX_TMP/release-copy" ]; do sleep 0.01; done
    ;;
esac
exec /bin/cp "$@"
""")
        cp.chmod(0o755)
        entries = {}
        for image in ("older", "newer"):
            root = self.base / image
            (root / "home").mkdir(parents=True)
            (root / "seed").mkdir()
            (root / "AGENTS.md").write_text(image + " default\n")
            staged = root / "steps"
            staged.mkdir()
            for name in ("10-dirs.sh", "20-seed.sh", "30-agents-md.sh"):
                text = (steps / name).read_text().replace("/etc/agentainer", str(root))
                text = text.replace("/etc/skel", str(root / "skel"))
                (staged / name).write_text(text)
            target = root / "entrypoint"
            target.write_text(entrypoint.replace("STEPS=/usr/local/lib/agentainer/entrypoint.d",
                                                 'STEPS="%s"' % staged))
            entries[image] = target
        env = {"PATH": str(bindir) + ":" + os.environ["PATH"]}
        older = self.start(["sh", str(entries["older"]), "echo", "STARTED"],
                           AGENTAINER_IMAGE_VERSION="2026.01.01", **env)
        self.wait_file("copy-paused")
        newer = self.start(["sh", str(entries["newer"]), "echo", "STARTED"],
                           AGENTAINER_IMAGE_VERSION="2026.02.01", **env)
        try:
            newer.communicate(timeout=0.5)
            blocked = False
        except subprocess.TimeoutExpired:
            blocked = True
        finally:
            (self.base / "release-copy").touch()
        self.complete(older)
        self.complete(newer)
        self.assertTrue(blocked, "newer startup passed a seed copy still in progress")
        self.assertEqual((self.home / ".agentainer/AGENTS.md").read_text(), "newer default\n")
        ledger = (self.home / ".agentainer/agents-default.sha256").read_text()
        self.assertIn("2026.01.01", ledger)
        self.assertIn("2026.02.01", ledger)

    def test_direct_and_startup_sync_preserve_managed_ownership(self):
        bindir = self.base / "bin"
        bindir.mkdir()
        (self.home / ".agentainer/mcp.json").write_text(
            '{"mcpServers":{"shared":{"command":"example"}}}')
        claude = bindir / "claude"
        claude.write_text("#!/bin/sh\nexit 0\n")
        claude.chmod(0o755)
        codex = bindir / "codex"
        codex.write_text("#!/bin/sh\nexit 0\n")
        codex.chmod(0o755)
        worker = self.base / "worker.py"
        worker.write_text("""import importlib.machinery,importlib.util,os,pathlib,time
loader = importlib.machinery.SourceFileLoader('mcp', os.environ['CX_SOURCE'])
spec = importlib.util.spec_from_loader('mcp', loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
args = ['sync']
if os.environ['CX_WORKER'] == 'A':
    write = m.write_atomic
    def paused(path, text):
        write(path, text)
        if path == str(pathlib.Path(os.environ['HOME']) / '.claude.json'):
            t = pathlib.Path(os.environ['CX_TMP'])
            (t / 'added').touch()
            while not (t / 'releaseA').exists():
                time.sleep(0.01)
    m.write_atomic = paused
if os.environ['CX_WORKER'] == 'B':
    args += ['--if-changed']
    original = m.sync_codex
    def gated(*args):
        t = pathlib.Path(os.environ['CX_TMP'])
        (t / 'Bpaused').touch()
        while not (t / 'releaseB').exists():
            time.sleep(0.01)
        return original(*args)
    m.sync_codex = gated
raise SystemExit(m.main(args))
""")
        env = {"PATH": str(bindir), "CX_SOURCE": str(ROOT / "rootfs/usr/local/bin/agentainer-mcp")}
        a = self.start([sys.executable, "-B", str(worker)], CX_WORKER="A", **env)
        self.wait_file("added")
        b = self.start([sys.executable, "-B", str(worker)], CX_WORKER="B", **env)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not (self.base / "Bpaused").exists():
            time.sleep(0.01)
        (self.base / "releaseA").touch()
        self.complete(a)
        (self.base / "releaseB").touch()
        self.complete(b)
        manifest = json.loads((self.home / ".agentainer/mcp-managed.json").read_text())
        self.assertEqual(manifest["claude"], ["shared"])
        self.assertIn("shared", json.loads((self.home / ".claude.json").read_text())["mcpServers"])

    @unittest.skipUnless(shutil.which("flock"), "entrypoint requires Linux flock")
    def test_concurrent_config_seeding_waits_for_the_first_copy(self):
        root = self.base / "image"
        (root / "home").mkdir(parents=True)
        (root / "home/.profile").write_text("image profile\n")
        steps = root / "steps"
        steps.mkdir()
        for name in ("10-dirs.sh", "20-seed.sh"):
            text = (ROOT / "rootfs/usr/local/lib/agentainer/entrypoint.d" / name).read_text()
            (steps / name).write_text(text.replace("/etc/agentainer", str(root))
                                          .replace("/etc/skel", str(root / "skel")))
        entrypoint = root / "entrypoint"
        text = (ROOT / "rootfs/usr/local/bin/agentainer-entrypoint").read_text()
        entrypoint.write_text(text.replace("STEPS=/usr/local/lib/agentainer/entrypoint.d",
                                          'STEPS="%s"' % steps))
        bindir = self.base / "bin"
        bindir.mkdir()
        cp = bindir / "cp"
        cp.write_text('''#!/bin/sh
if [ "$CX_WORKER" = A ]; then
    touch "$CX_TMP/copy-paused"
    while [ ! -e "$CX_TMP/release-copy" ]; do sleep 0.01; done
else
    touch "$CX_TMP/B-copied"
fi
exec /bin/cp "$@"
''')
        cp.chmod(0o755)
        env = {"PATH": str(bindir) + ":" + os.environ["PATH"]}
        a = self.start(["sh", str(entrypoint), "echo", "STARTED"], CX_WORKER="A", **env)
        self.wait_file("copy-paused")
        b = self.start(["sh", str(entrypoint), "echo", "STARTED"], CX_WORKER="B", **env)
        time.sleep(0.3)
        waited = b.poll() is None and not (self.base / "B-copied").exists()
        (self.base / "release-copy").touch()
        self.complete(a)
        self.complete(b)
        self.assertTrue(waited, "the second seed copied a destination still being created")
        self.assertEqual((self.home / ".profile").read_text(), "image profile\n")

    def test_killed_sync_recovers_ownership_on_restart(self):
        bindir = self.base / "bin"
        bindir.mkdir()
        cli = bindir / "claude"
        cli.write_text("#!/bin/sh\nexit 0\n")
        cli.chmod(0o755)
        desired = self.home / ".agentainer/mcp.json"
        desired.write_text('{"mcpServers":{"orphan":{"command":"example"}}}')
        worker = self.base / "interrupted.py"
        worker.write_text('''import importlib.machinery,importlib.util,os,pathlib,time
loader = importlib.machinery.SourceFileLoader('mcp', os.environ['CX_SOURCE'])
spec = importlib.util.spec_from_loader('mcp', loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
write = m.write_atomic
def paused(path, text):
    write(path, text)
    if path == str(pathlib.Path(os.environ['HOME']) / '.claude.json'):
        (pathlib.Path(os.environ['CX_TMP']) / 'config-renamed').touch()
        while True:
            time.sleep(0.1)
m.write_atomic = paused
raise SystemExit(m.main(['sync']))
''')
        env = {"PATH": str(bindir), "CX_SOURCE": str(ROOT / "rootfs/usr/local/bin/agentainer-mcp")}
        killed = self.start([sys.executable, "-B", str(worker)], **env)
        self.wait_file("config-renamed")
        killed.kill()
        killed.communicate(timeout=5)
        self.assertEqual(killed.returncode, -9)
        self.assertIn("orphan", json.loads((self.home / ".claude.json").read_text())["mcpServers"])
        self.assertTrue((self.home / ".agentainer/mcp-pending-claude.json").is_file())
        desired.write_text('{"mcpServers":{}}')
        restarted = self.start([sys.executable, "-B", env["CX_SOURCE"], "sync", "--if-changed"], **env)
        self.complete(restarted)
        self.assertEqual(json.loads((self.home / ".claude.json").read_text())["mcpServers"], {})
        manifest = json.loads((self.home / ".agentainer/mcp-managed.json").read_text())
        self.assertEqual(manifest["claude"], [])
        self.assertFalse((self.home / ".agentainer/mcp-pending-claude.json").exists())
