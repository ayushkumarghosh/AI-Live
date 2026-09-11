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
