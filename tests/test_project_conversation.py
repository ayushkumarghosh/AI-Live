import unittest
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module


class ProjectConversationTests(unittest.TestCase):
    def make_store(self, **kwargs):
        try:
            module = import_module('project_guide.conversation')
        except ModuleNotFoundError:
            self.fail('project update store is not implemented')
        return module.ProjectUpdateStore(**kwargs)

    def test_retains_deduplicates_and_isolates_sessions(self):
        store = self.make_store()
        store.activate('a')
        self.assertEqual(store.active_session_id, 'a')
        self.assertTrue(store.record('a', '  Use SQLite.  '))
        self.assertFalse(store.record('a', 'Use SQLite.'))
        self.assertFalse(store.record('a', '  '))
        first = store.snapshot('a')
        self.assertEqual(first['updates'], [{'revision': 1, 'text': 'Use SQLite.'}])
        first['updates'][0]['text'] = 'mutated'
        self.assertEqual(store.snapshot('a')['updates'][0]['text'], 'Use SQLite.')
        store.activate('a')
        self.assertEqual(store.snapshot('a')['revision'], 1)
        store.activate('b')
        self.assertFalse(store.record('a', 'stale'))
        self.assertEqual(store.snapshot('a')['updates'], [])
        self.assertEqual(store.snapshot('b')['revision'], 0)
        store.clear()
        self.assertEqual(store.active_session_id, '')
        self.assertFalse(store.record('b', 'late'))

    def test_bounds_text_and_reports_dropped_revisions(self):
        store = self.make_store(max_updates=2, max_text_chars=8)
        store.activate('a')
        for text in ['first', 'second', '1234567890']:
            store.record('a', text)
        snapshot = store.snapshot('a')
        self.assertEqual(snapshot['revision'], 3)
        self.assertEqual(snapshot['dropped_updates'], 1)
        self.assertEqual(snapshot['updates'], [
            {'revision': 2, 'text': 'second'},
            {'revision': 3, 'text': '1234567…', 'truncated': True}])
        self.assertFalse(store.record('a', '1234567890'))

    def test_concurrent_records_have_unique_revisions(self):
        store = self.make_store(max_updates=200)
        store.activate('a')
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: store.record('a', str(i)), range(200)))
        snapshot = store.snapshot('a')
        self.assertEqual(snapshot['revision'], 200)
        self.assertEqual([u['revision'] for u in snapshot['updates']], list(range(1, 201)))
        self.assertEqual({u['text'] for u in snapshot['updates']}, {str(i) for i in range(200)})

    def test_correction_can_return_to_previously_recorded_requirement(self):
        store = self.make_store()
        store.activate('a')
        for text in ['Use SQLite.', 'Use Postgres.', 'Use SQLite.']:
            self.assertTrue(store.record('a', text))
        self.assertFalse(store.record('a', ' Use SQLite. '))
        self.assertEqual(store.snapshot('a')['updates'], [
            {'revision': 1, 'text': 'Use SQLite.'},
            {'revision': 2, 'text': 'Use Postgres.'},
            {'revision': 3, 'text': 'Use SQLite.'}])

    def test_concurrent_identical_updates_are_consecutive_duplicates(self):
        store = self.make_store()
        store.activate('a')
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: store.record('a', 'Use SQLite.'), range(200)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(store.snapshot('a')['revision'], 1)

    def test_truncation_does_not_merge_different_source_updates(self):
        store = self.make_store(max_text_chars=8)
        store.activate('a')
        self.assertTrue(store.record('a', '12345678'))
        self.assertFalse(store.snapshot('a')['updates'][-1].get('truncated', False))
        self.assertTrue(store.record('a', '1234567890'))
        self.assertTrue(store.record('a', '1234567891'))
        self.assertFalse(store.record('a', '1234567891'))
        snapshot = store.snapshot('a')
        self.assertEqual(snapshot['revision'], 3)
        self.assertTrue(snapshot['updates'][-1]['truncated'])
        snapshot['updates'][-1]['truncated'] = False
        self.assertTrue(store.snapshot('a')['updates'][-1]['truncated'])

    def test_invalid_limits_rejected(self):
        for kwargs in [{'max_updates': 0}, {'max_text_chars': 0}]:
            with self.assertRaises(ValueError):
                self.make_store(**kwargs)
