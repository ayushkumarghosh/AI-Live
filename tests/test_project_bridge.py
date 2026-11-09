import json
import tempfile
import unittest
import urllib.request
import urllib.error
import threading
import time
from pathlib import Path
from project_guide.bridge import ProjectBridge
from project_guide.files import GuideError


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'main.py').write_text('hello')
        self.bridge = ProjectBridge(self.root / 'state')
        self.bridge.start()
        self.addCleanup(self.bridge.close)

    def post(self, path, body, token=None):
        req = urllib.request.Request(self.bridge.url + path, json.dumps(body).encode(),
              headers={'Authorization': 'Bearer ' + (token or self.bridge.token), 'Content-Type': 'application/json'})
        return json.load(urllib.request.urlopen(req, timeout=3))

    def register(self):
        return self.post('/poll', dict(window='one', roots=[str(self.root)], active=str(self.root / 'main.py'),
                         focused=True, dirty=[], diagnostics=[], trusted=True, remote=False))

    def test_capture_endpoint_requires_auth_and_returns_recent_terminal_reports(self):
        terminal = dict(name='Codex', cwd=str(self.root), command='codex', output='Latest response',
                        running=True, exit_code=None, truncated=True,
                        id='t1', execution_id='e1', revision=3)
        self.post('/poll', dict(window='one', roots=[str(self.root)], trusted=True,
                               remote=False, terminal=terminal, terminals=[terminal]))
        def read(headers):
            request = urllib.request.Request(self.bridge.url + '/captures', headers=headers)
            return json.load(urllib.request.urlopen(request, timeout=3))
        for headers in ({}, {'Authorization': 'Bearer wrong'},
                        {'Authorization': 'Bearer ' + self.bridge.token, 'Origin': 'https://example.com'}):
            with self.assertRaises(urllib.error.HTTPError) as error:
                read(headers)
            self.assertEqual(error.exception.code, 401)
        result = read({'Authorization': 'Bearer ' + self.bridge.token})
        self.assertEqual(result['windows'][0]['terminals'], [terminal])
        self.assertEqual(result['windows'][0]['terminal'], terminal)
        self.assertNotIn(self.bridge.token, json.dumps(result))
        with self.bridge.lock:
            self.bridge.clients['one']['seen'] -= 7
        self.assertEqual(read({'Authorization': 'Bearer ' + self.bridge.token}), {'windows': []})

    def test_auth_and_no_arbitrary_commands(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post('/poll', {}, 'wrong')
        self.assertEqual(error.exception.code, 401)
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/execute', {'command': 'danger'})

    def test_only_explicit_open_is_queued_and_project_is_pinned(self):
        self.register()
        self.assertEqual(self.bridge.windows()[0]['window'], 'one')
        self.bridge.open_location('one', self.root, 'main.py', 1)
        commands = self.register()['commands']
        self.assertEqual(commands[0]['type'], 'open')
        self.assertEqual(commands[0]['path'], str(self.root / 'main.py'))
        self.assertEqual(self.register()['commands'], [])
        with self.assertRaises(GuideError):
            self.bridge.open_location('one', self.root, '../outside', 1)

    def test_multiple_windows_recommend_recent_focus_without_repinning(self):
        self.register()
        self.post('/poll', dict(window='two', roots=[str(self.root)], active=None,
                  focused=True, dirty=[], diagnostics=[], trusted=True, remote=False))
        self.assertEqual(self.bridge.windows()[0]['window'], 'two')
        self.assertEqual(self.bridge.state('one', self.root)['window'], 'one')
        self.post('/poll', dict(window='one', roots=[], active=None,
                  focused=False, dirty=[], diagnostics=[], trusted=True, remote=False))
        with self.assertRaises(GuideError):
            self.bridge.state('one', self.root)

    def test_remote_and_untrusted_reports_are_not_selectable(self):
        self.register()
        self.post('/poll', dict(window='one', remote=True, trusted=True))
        self.assertEqual(self.bridge.windows(), [])
        self.post('/poll', dict(window='one', remote=False, trusted=False))
        self.assertEqual(self.bridge.windows(), [])

    def test_named_workspace_metadata_is_available_for_editor_alignment(self):
        self.post('/poll', dict(window='one', roots=[str(self.root)], active=str(self.root / 'main.py'),
                  workspaceName='My multi-root workspace', trusted=True, remote=False))
        self.assertEqual(self.bridge.state('one', self.root)['workspace_name'], 'My multi-root workspace')

    def test_terminal_report_is_bounded_and_scoped_to_selected_project(self):
        from unittest.mock import patch
        terminal = dict(name='pwsh', cwd=str(self.root), command='pytest', output='1 failed',
                        running=False, exit_code=1, truncated=False)
        body = dict(window='one', roots=[str(self.root)], trusted=True, remote=False, terminal=terminal)
        self.post('/poll', body)
        with patch.object(self.bridge, 'fresh_state', return_value=self.bridge.state('one', self.root)):
            self.assertEqual(self.bridge.terminal_output('one', self.root)['output'], '1 failed')
        terminal['cwd'] = str(self.root.parent)
        self.post('/poll', body)
        with patch.object(self.bridge, 'fresh_state', return_value=self.bridge.state('one', self.root)):
            with self.assertRaisesRegex(GuideError, 'inside this project'):
                self.bridge.terminal_output('one', self.root)
        terminal['output'] = 'x' * 32001
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/poll', body)

    def test_missing_terminal_capture_explains_how_to_enable_it(self):
        from unittest.mock import patch
        self.register()
        with patch.object(self.bridge, 'fresh_state', return_value=self.bridge.state('one', self.root)):
            with self.assertRaisesRegex(GuideError, 'shell integration'):
                self.bridge.terminal_output('one', self.root)

    def test_close_removes_only_own_discovery_file(self):
        self.assertTrue(self.bridge.discovery.exists())
        self.bridge.close()
        self.assertFalse(self.bridge.discovery.exists())

    def test_fresh_state_waits_for_editor_acknowledgement(self):
        self.register()
        answers = []
        worker = threading.Thread(target=lambda: answers.append(self.bridge.fresh_state('one', self.root)))
        worker.start()
        with self.bridge.condition:
            self.assertTrue(self.bridge.condition.wait_for(lambda: 'one' in self.bridge.refresh_requests, timeout=1))
        response = self.register()
        self.assertIn('refresh', response)
        self.assertFalse(answers)
        self.post('/poll', dict(window='one', roots=[str(self.root)], active=None, focused=True,
                  dirty=[str(self.root / 'main.py')], diagnostics=[], trusted=True, remote=False,
                  ack=response['refresh']))
        worker.join(3)
        self.assertEqual(answers[0]['dirty'], [str(self.root / 'main.py')])


    def capture(self, **changes):
        return dict(dict(id='pin', execution_id='run-1', revision=2, name='pwsh',
                         cwd=str(self.root), command='pytest', output='failed',
                         running=False, exit_code=1, truncated=False), **changes)

    def report(self, terminals, terminal=None, **changes):
        return self.bridge.poll(dict(dict(window='one', roots=[str(self.root)],
            trusted=True, remote=False, terminals=terminals, terminal=terminal), **changes))

    def test_terminal_list_preserves_identity_and_filters_scope(self):
        self.report([self.capture(), self.capture(id='outside', cwd=str(self.root.parent)),
                     self.capture(id='unknown', cwd='')])
        records = self.bridge.terminals('one', self.root)
        self.assertEqual([r['id'] for r in records], ['pin'])
        self.assertEqual(records[0]['execution_id'], 'run-1')
        self.assertEqual(records[0]['revision'], 2)
        records[0]['output'] = 'mutated'
        self.assertEqual(self.bridge.terminals('one', self.root)[0]['output'], 'failed')

    def test_pinned_terminal_uses_fresh_report_and_never_active_fallback(self):
        self.report([self.capture()], self.capture(id='active'))
        def fresh_call(records):
            answers = []
            def call():
                try:
                    answers.append(self.bridge.terminal_output('one', self.root, 'pin'))
                except Exception as error:
                    answers.append(error)
            worker = threading.Thread(target=call)
            with self.bridge.condition:
                self.bridge.refresh_requests.clear()
            worker.start()
            with self.bridge.condition:
                self.assertTrue(self.bridge.condition.wait_for(
                    lambda: 'one' in self.bridge.refresh_requests, timeout=1))
                ack = self.bridge.refresh_requests['one']
            self.report(records, self.capture(id='active'), ack=ack)
            worker.join(2)
            self.assertFalse(worker.is_alive())
            return answers[0]
        result = fresh_call([self.capture(execution_id='run-2', revision=0, output='new')])
        self.assertIsInstance(result, dict)
        self.assertEqual(result['output'], 'new')
        self.assertEqual(result['execution_id'], 'run-2')
        self.assertEqual(result['revision'], 0)
        self.assertIsInstance(fresh_call([]), GuideError)
        self.assertIsInstance(fresh_call([self.capture(cwd=str(self.root.parent))]), GuideError)

    def test_invalid_terminal_reports_are_rejected_atomically(self):
        self.report([self.capture()])
        invalid = [None, {}, [self.capture()] * 21, [self.capture(), self.capture()]]
        for field, value in [('id', ''), ('id', 2), ('execution_id', ''),
                             ('execution_id', 'x' * 101), ('revision', -1),
                             ('revision', True), ('revision', 1.5), ('output', 'x' * 32001)]:
            invalid.append([self.capture(**{field: value})])
        missing = self.capture()
        del missing['id']
        invalid.append([missing])
        for records in invalid:
            with self.subTest(records=str(records)[:100]):
                with self.assertRaises(ValueError):
                    self.report(records)
                self.assertEqual(self.bridge.state('one', self.root)['terminals'][0]['id'], 'pin')
        with self.assertRaises(ValueError):
            self.report([], self.capture(revision=True))
