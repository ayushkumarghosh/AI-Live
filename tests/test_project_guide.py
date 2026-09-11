import json
import tempfile
import unittest
from pathlib import Path

from project_guide.files import ProjectFiles, GuideError
from project_guide.session import GuideSession, parse_guidance


def result():
    return dict(summary='Implement greeting', question='', choices=[], blocked='',
                steps=[dict(id='greeting', path='main.py', anchor='def hello():', line=1,
                            operation='replace', code='def hello(): return "Hi"', explanation='Return a greeting.')],
                verdict='not_reviewed', findings='', test_commands=['python -m unittest'])


class ProjectGuideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'main.py').write_text('def hello(): pass', encoding='utf-8')
        (self.root / 'README.md').write_text('Implement hello', encoding='utf-8')
        self.files = ProjectFiles(self.root)

    def test_paths_cannot_escape_or_use_windows_special_paths(self):
        for path in ['../secret', 'C:\\secret', '/secret', 'main.py:secret', 'CON', '.git/config']:
            with self.subTest(path=path), self.assertRaises(GuideError):
                self.files.resolve(path)

    def test_read_and_search(self):
        self.assertIn('hello', self.files.read('main.py'))
        self.assertIn('main.py', json.dumps(self.files.search('hello')))

    def test_codex_locations_are_preserved_without_file_checks(self):
        data = result()
        data['steps'][0].update(path='not-created.py', anchor='not saved', line=999)
        self.assertIs(parse_guidance(data), data)
        self.assertEqual(data['steps'][0]['line'], 999)

    def test_changed_files_do_not_reject_an_answer(self):
        session = GuideSession(self.root, 'README.md', 'window')
        request = session.begin()
        (self.root / 'main.py').unlink()
        self.assertTrue(session.accept(request, result()))

    def test_cancelled_requests_are_still_ignored(self):
        session = GuideSession(self.root, 'README.md', 'window')
        request = session.begin()
        session.cancel()
        self.assertFalse(session.accept(request, result()))

    def test_navigation_does_not_complete_steps(self):
        session = GuideSession(self.root, 'README.md', 'window')
        session.accept(session.begin(), result())
        session.move(1)
        self.assertEqual(session.result['verdict'], 'not_reviewed')
        self.assertEqual(session.index, 0)

    def test_answer_acceptance_does_not_read_files(self):
        from unittest.mock import patch
        session = GuideSession(self.root, 'README.md', 'window')
        with patch.object(session.files, 'read', side_effect=AssertionError('No validation reads')):
            self.assertTrue(session.accept(session.begin(), result()))

    def test_unrenderable_response_reports_format_error(self):
        with self.assertRaises(GuideError):
            parse_guidance({'summary': 'missing required display fields'})
