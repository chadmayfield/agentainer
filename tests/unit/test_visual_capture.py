"""Failure paths for the optional visual-review capture driver."""
import ast
import base64
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'visual/capture.py'
SCENARIOS = PATH.parent / 'fixtures/scenarios.py'
SPEC = importlib.util.spec_from_file_location('visual_capture', PATH)
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def valid_document():
    return {'schema': 1, 'captures': [dict(id=name, cols=80 if name in capture.NARROW_SCENARIOS else 120,
            rows=24 if name in capture.NARROW_SCENARIOS else 32,
            expectedText=['sample'], output=base64.b64encode(b'\x1b[31msample\x1b[0m').decode())
            for name in capture.SCENARIOS]}


class VisualCaptureTests(unittest.TestCase):
    def test_missing_duplicate_and_unformatted_frames_fail(self):
        for mutation in ('missing', 'duplicate', 'unformatted', 'invalid-base64', 'no-marker'):
            document = valid_document()
            if mutation == 'missing':
                document['captures'].pop()
            elif mutation == 'duplicate':
                document['captures'][-1] = copy.deepcopy(document['captures'][0])
            elif mutation == 'unformatted':
                document['captures'][0]['output'] = base64.b64encode(b'plain text').decode()
            elif mutation == 'invalid-base64':
                document['captures'][0]['output'] = '!not base64!'
            else:
                document['captures'][0]['expectedText'] = []
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                capture.validate(document)

    def test_narrow_dimensions_are_allowed_only_for_narrow_scenarios(self):
        document = valid_document()
        self.assertEqual(capture.validate(document), document)
        for name, width, height in [('shell', 80, 24), ('vim-browser-narrow', 120, 32),
                                    ('tmux-narrow', 80, 32)]:
            changed = copy.deepcopy(document)
            item = next(frame for frame in changed['captures'] if frame['id'] == name)
            item.update(cols=width, rows=height)
            with self.subTest(name=name), self.assertRaises(ValueError):
                capture.validate(changed)

    def test_only_local_and_ghcr_references_are_recorded_in_full(self):
        digest = 'sha256:' + 'a' * 64
        cases = {
            'localhost/agentainer:dev': 'localhost/agentainer:dev',
            'ghcr.io/owner/agentainer:1.2.3': 'ghcr.io/owner/agentainer:1.2.3',
            'registry.example.com:5000/team/agentainer:dev': ':dev',
            'registry.example.com/team/agentainer@' + digest: '@' + digest,
            'registry.example.com/team/agentainer:dev@' + digest: '@' + digest,
            'registry.example.com:5000/team/agentainer': capture.NO_TAG,
            'agentainer:dev': ':dev',
            'docker.io/library/ubuntu': capture.NO_TAG,
            'x@not-a-digest.example.com': capture.NO_TAG,
            'x:bad/tag': capture.NO_TAG,
        }
        for reference, recorded in cases.items():
            with self.subTest(reference=reference):
                self.assertEqual(capture.recorded_image(reference), recorded)

    def test_capture_records_only_the_tag_of_another_registry(self):
        with tempfile.TemporaryDirectory(prefix='cx-visual-test-') as directory:
            root = Path(directory)
            with patch.object(capture, 'ROOT', root), patch.object(capture.subprocess, 'run') as run:
                run.side_effect = [subprocess.CompletedProcess([], 0, json.dumps(valid_document()), ''),
                                   subprocess.CompletedProcess([], 0, '', '')]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(capture.main(['--runtime', 'fake-engine', '--image',
                                                   'registry.example.com/team/agentainer:rc1']), 0)
                text = (root / 'artifacts/visual/captures.json').read_text()
                self.assertEqual(json.loads(text)['image'], ':rc1')
                self.assertNotIn('registry.example.com', text)
                # The engine still gets the full reference.
                self.assertIn('registry.example.com/team/agentainer:rc1', run.call_args_list[0].args[0])

    def test_complete_capture_is_published_with_overlay_label(self):
        with tempfile.TemporaryDirectory(prefix='cx-visual-test-') as directory:
            root = Path(directory)
            with patch.object(capture, 'ROOT', root), patch.object(capture.subprocess, 'run') as run:
                document = valid_document()
                run.side_effect = [subprocess.CompletedProcess([], 0, json.dumps(document), ''),
                                   subprocess.CompletedProcess([], 0, '', '')]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(capture.main(['--runtime', 'fake-engine', '--source-defaults']), 0)
                published = json.loads((root / 'artifacts/visual/captures.json').read_text())
                self.assertEqual(published['captures'], document['captures'])
                self.assertEqual(published['defaults'], 'checkout overlay')
                command = run.call_args_list[0].args[0]
                self.assertIn(str(root / 'rootfs/etc/agentainer/home') + ':/etc/agentainer/home:ro', command)
                self.assertFalse(list((root / 'artifacts/visual').glob('cx-capture-*')))

    def test_engine_failure_preserves_last_capture_and_returns_failure(self):
        with tempfile.TemporaryDirectory(prefix='cx-visual-test-') as directory:
            root = Path(directory)
            destination = root / 'artifacts/visual'
            destination.mkdir(parents=True)
            file = destination / 'captures.json'
            file.write_text('previous capture')
            with patch.object(capture, 'ROOT', root), patch.object(capture.subprocess, 'run') as run:
                run.return_value = subprocess.CompletedProcess([], 125, '', 'no such image')
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(capture.main(['--runtime', 'fake-engine']), 1)
                self.assertEqual(file.read_text(), 'previous capture')
                command = run.call_args_list[0].args[0]
                self.assertIn('--pull=never', command)
                self.assertEqual(command[command.index('--network') + 1], 'none')
                name = command[command.index('--name') + 1]
                self.assertTrue(name.startswith('cx-visual-'))
                self.assertEqual(run.call_args_list[-1].args[0], ['fake-engine', 'rm', '-f', name])

    def test_incomplete_container_output_cannot_publish_a_capture(self):
        with tempfile.TemporaryDirectory(prefix='cx-visual-test-') as directory:
            with patch.object(capture, 'ROOT', Path(directory)), patch.object(capture.subprocess, 'run') as run:
                document = valid_document()
                document['captures'].pop()
                run.return_value = subprocess.CompletedProcess([], 0, json.dumps(document), '')
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(capture.main(['--runtime', 'fake-engine']), 1)
                self.assertFalse((Path(directory) / 'artifacts/visual/captures.json').exists())

    def test_timeout_removes_only_the_container_created_by_this_run(self):
        with tempfile.TemporaryDirectory(prefix='cx-visual-test-') as directory:
            with patch.object(capture, 'ROOT', Path(directory)), patch.object(capture.subprocess, 'run') as run:
                run.side_effect = [subprocess.TimeoutExpired('fake-engine', 180),
                                   subprocess.CompletedProcess([], 0, '', '')]
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(capture.main(['--runtime', 'fake-engine']), 1)
                command = run.call_args_list[0].args[0]
                name = command[command.index('--name') + 1]
                self.assertEqual(run.call_args_list[-1].args[0], ['fake-engine', 'rm', '-f', name])

    def test_timeout_reports_a_container_it_could_not_remove(self):
        for removal in (subprocess.CompletedProcess([], 1, '', 'engine hung'),
                        subprocess.TimeoutExpired('fake-engine', 20)):
            with self.subTest(removal=type(removal).__name__), tempfile.TemporaryDirectory() as directory:
                with patch.object(capture, 'ROOT', Path(directory)), patch.object(capture.subprocess, 'run') as run:
                    run.side_effect = [subprocess.TimeoutExpired('fake-engine', 180), removal]
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        self.assertEqual(capture.main(['--runtime', 'fake-engine']), 1)
                    command = run.call_args_list[0].args[0]
                    name = command[command.index('--name') + 1]
                    self.assertIn('could not remove container ' + name, err.getvalue())

    def test_failed_removal_after_the_engine_returned_is_not_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(capture, 'ROOT', Path(directory)), patch.object(capture.subprocess, 'run') as run:
                run.side_effect = [subprocess.CompletedProcess([], 125, '', 'no such image'),
                                   subprocess.CompletedProcess([], 1, '', 'no such container')]
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(capture.main(['--runtime', 'fake-engine']), 1)
                self.assertNotIn('could not remove', err.getvalue())


class VisualScenarioSourceTests(unittest.TestCase):
    """Checks on the in-container scenario script, which runs only inside the image."""

    def setUp(self):
        self.source = SCENARIOS.read_text()

    def scenario_call(self, identifier):
        for node in ast.walk(ast.parse(self.source)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'add'
                    and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == identifier):
                return node
        self.fail('no add() call for ' + identifier)

    def test_tmux_scenarios_render_the_configured_status_right(self):
        for stale in ('Mon 19 Oct 12:00', 'logs#'):
            self.assertFalse(stale in self.source, 'scenarios.py still contains ' + stale)

    def test_activity_scenario_checks_activity_color(self):
        keywords = {keyword.arg: keyword.value for keyword in self.scenario_call('tmux-activity').keywords}
        self.assertIn('colors', keywords)
        self.assertEqual(ast.literal_eval(keywords['colors']), ['#a5d6ff'])

    def test_ls_colors_is_a_captured_scenario(self):
        self.assertEqual(capture.SCENARIOS[:2], ('shell', 'ls-colors'))
        self.scenario_call('ls-colors')


if __name__ == '__main__':
    unittest.main()
