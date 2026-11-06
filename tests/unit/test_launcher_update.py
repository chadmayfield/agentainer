"""Exercise update rollback with a stateful container-engine fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LauncherUpdateTests(unittest.TestCase):
    def update(self, failure="", running=True, locale_label="", extra_env=None):
        with tempfile.TemporaryDirectory(prefix="cx-update-") as directory:
            base = Path(directory)
            (base / "workspace").mkdir()
            state = base / "state.json"
            state.write_text(json.dumps({"cx-example": {"generation": "old", "running": running}}))
            engine = base / "engine"
            engine.write_text("#!" + sys.executable + "\n" + '''import json,os,sys
from pathlib import Path
base=Path(os.environ['CX_BASE']); path=base/'state.json'; state=json.loads(path.read_text())
a=sys.argv[1:]; cmd=a[0]; failure=os.environ['CX_FAILURE']
with (base/'calls').open('a') as f:f.write(json.dumps(a)+'\\n')
def save(): path.write_text(json.dumps(state))
if cmd=='inspect':
    name=a[-1]
    if name not in state: sys.exit(1)
    fmt=a[a.index('--format')+1]
    if '.State.Running' in fmt: print(str(state[name]['running']).lower())
    elif '.Id' in fmt: print(state[name]['generation'])
    elif '.update"' in fmt:
        print((base/'token').read_text() if state[name]['generation']=='new' and (base/'token').exists() else '')
    else:
        values={'image':'example.com/agentainer:test','dir':str(base/'workspace'),
                'sudo':'0','home':'cx-home','env-file':'',
                'locale':os.environ.get('CX_LOCALE','')}
        print(next((v for k,v in values.items() if '.'+k+'"' in fmt),''))
elif cmd=='pull': sys.exit(1 if failure=='pull' else 0)
elif cmd=='rename':
    if a[2] in state: sys.exit(1)
    state[a[2]]=state.pop(a[1]); save()
elif cmd=='stop': state[a[1]]['running']=False; save()
elif cmd=='start': state[a[1]]['running']=True; save()
elif cmd=='rm': state.pop(a[-1],None); save()
elif cmd=='run':
    name=a[a.index('--name')+1]
    if failure=='collision':
        state[name]={'generation':'rival','running':True}; save(); sys.exit(125)
    for value in a:
        if value.startswith('io.github.chadmayfield.agentainer.update='):
            (base/'token').write_text(value.split('=',1)[1])
    state[name]={'generation':'new','running':failure not in ('create','startup')}; save()
    sys.exit(125 if failure=='create' else 0)
elif cmd=='exec': sys.exit(0)
''')
            engine.chmod(0o755)
            result = subprocess.run(["sh", str(ROOT / "bin/agentainer"), "update", "cx-example"],
                                    env=dict(os.environ, AGENTAINER_RUNTIME=str(engine),
                                             CX_BASE=str(base), CX_FAILURE=failure,
                                             CX_LOCALE=locale_label, **(extra_env or {})),
                                    capture_output=True, text=True)
            calls = [json.loads(line) for line in (base / "calls").read_text().splitlines()]
            return result, json.loads(state.read_text()), calls

    def test_creation_failure_restores_old_container_and_running_state(self):
        for running in (True, False):
            with self.subTest(running=running):
                result, state, _ = self.update("create", running)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(state, {"cx-example": {"generation": "old", "running": running}})

    def test_entrypoint_failure_restores_old_container(self):
        result, state, _ = self.update("startup")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state, {"cx-example": {"generation": "old", "running": True}})

    def test_success_removes_backup_only_after_readiness(self):
        result, state, calls = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state, {"cx-example": {"generation": "new", "running": True}})
        probe = next(i for i,c in enumerate(calls) if c[0] == "exec")
        removal = next(i for i,c in enumerate(calls) if c[0] == "rm")
        self.assertLess(probe, removal)

    def test_pull_failure_leaves_old_container_untouched(self):
        result, state, calls = self.update("pull")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state, {"cx-example": {"generation": "old", "running": True}})
        self.assertFalse(any(c[0] in ("rename", "stop", "rm", "run") for c in calls))

    def test_name_collision_never_deletes_an_unrelated_container(self):
        result, state, calls = self.update("collision")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state.get("cx-example"), {"generation": "rival", "running": True})
        self.assertEqual(state.get("cx-agentainer-backup-cx-example"),
                         {"generation": "old", "running": False})
        self.assertFalse(any(c[0] == "rm" and c[-1] == "cx-example" for c in calls))

    def run_call(self, calls):
        return next(c for c in calls if c[0] == "run")

    def test_replayed_label_is_validated(self):
        result, _, calls = self.update(locale_label="LANG=en_US.UTF-8 TZ=:/etc/passwd")
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.run_call(calls)
        self.assertIn("LANG=en_US.UTF-8", run)
        self.assertFalse(any(a.startswith("TZ=") for a in run), run)

    def test_update_replays_recorded_locale_not_the_current_shell(self):
        result, _, calls = self.update(locale_label="LANG=de_DE.UTF-8 TZ=Europe/Berlin",
                                       extra_env={"LANG": "en_US.UTF-8", "TZ": "UTC"})
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.run_call(calls)
        self.assertIn("LANG=de_DE.UTF-8", run)
        self.assertIn("TZ=Europe/Berlin", run)
        self.assertNotIn("TZ=UTC", run)
        self.assertIn("io.github.chadmayfield.agentainer.locale=LANG=de_DE.UTF-8 TZ=Europe/Berlin", run)

    def test_update_of_a_container_without_locale_label_passes_none(self):
        result, _, calls = self.update(extra_env={"LANG": "en_US.UTF-8", "TZ": "UTC"})
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.run_call(calls)
        self.assertFalse(any(a.startswith(("LANG=", "TZ=")) for a in run), run)
