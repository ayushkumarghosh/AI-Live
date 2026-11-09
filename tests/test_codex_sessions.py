import copy
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from project_guide.codex_sessions import SessionReader, session_evidence
from project_guide.files import GuideError
from project_guide.session import PromptSession
from tests.test_prompt_guide import response


def turn(id='turn1', prompt='Investigate greeting', answer='The greeting is missing.', status='completed'):
    return {'id': id, 'status': status, 'items': [
        {'type': 'userMessage', 'content': [{'type': 'text', 'text': prompt}]},
        {'type': 'agentMessage', 'text': answer}]}


class CodexSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'README.md').write_text('Greeting')
        self.thread = {'id': 'cli1', 'cwd': str(self.root), 'source': 'cli',
                       'updatedAt': 2, 'turns': [turn()]}

    def test_latest_skips_own_exec_ephemeral_and_other_project_and_paginates(self):
        reader = SessionReader()
        own = dict(self.thread, id='own', source='exec', updatedAt=20)
        ephemeral = dict(self.thread, id='temp', ephemeral=True)
        other = dict(self.thread, cwd=str(self.root.parent))
        reader.call = Mock(side_effect=[{'data': [own, ephemeral, other], 'nextCursor': 'page2'},
                                      {'data': [self.thread], 'nextCursor': None}, {'thread': self.thread}])
        self.assertEqual(reader.latest(self.root)['id'], 'cli1')
        calls = reader.call.call_args_list
        self.assertEqual(calls[0].args[1]['sourceKinds'], ['cli'])
        self.assertEqual(calls[0].args[1]['sortKey'], 'updated_at')
        self.assertEqual(calls[1].args[1]['cursor'], 'page2')
        self.assertEqual(calls[2].args, ('thread/read', {'threadId': 'cli1', 'includeTurns': True}))

    def test_newest_eligible_session_is_used_even_if_older_has_more_history(self):
        reader = SessionReader()
        newer = dict(self.thread, id='new', turns=[])
        reader.call = Mock(side_effect=[{'data': [newer, self.thread]}, {'thread': newer}])
        selected = reader.latest(self.root)
        self.assertEqual(selected['id'], 'new')
        with self.assertRaisesRegex(GuideError, 'no saved response'):
            session_evidence(selected, 'Investigate greeting')

    def test_no_session_never_falls_back_to_own_request(self):
        reader = SessionReader()
        reader.call = Mock(return_value={'data': [dict(self.thread, source='exec')]})
        with self.assertRaisesRegex(GuideError, 'No saved Codex CLI session'):
            reader.latest(self.root)

    def test_extracts_messages_and_followups_without_reasoning_or_spinner_stream(self):
        self.thread['turns'][0]['items'].append({'type': 'reasoning', 'text': 'internal'})
        self.thread['turns'].append(turn('turn2', 'Also support empty names', 'Empty names need handling.'))
        evidence = session_evidence(self.thread, 'Investigate\n greeting')
        self.assertEqual(evidence['execution_id'], 'turn2')
        self.assertIn('User: Also support empty names', evidence['output'])
        self.assertIn('Codex: Empty names need handling.', evidence['output'])
        self.assertNotIn('internal', evidence['output'])
        self.assertFalse(evidence['truncated'])

    def test_running_failed_interrupted_or_wrong_prompt_never_uses_old_answer(self):
        for status in ['inProgress', 'failed', 'interrupted']:
            with self.subTest(status=status):
                thread = copy.deepcopy(self.thread)
                thread['turns'].append(turn('new', status=status))
                with self.assertRaises(GuideError):
                    session_evidence(thread, 'Investigate greeting')
        self.assertIn('The greeting is missing.', session_evidence(self.thread, 'An edited prompt')['output'])

    def test_same_turn_cannot_advance_twice_even_after_session_switch(self):
        session = PromptSession(self.root, 'README.md', 'window')
        evidence = session_evidence(self.thread, 'Investigate greeting')
        session.prepare_check(evidence)
        session.accept(session.begin(), response('Next prompt'))
        another = dict(evidence, id='cli2')
        session.prepare_check(another)
        session.accept(session.begin(), response('Third prompt'))
        with self.assertRaises(GuideError):
            session.prepare_check(dict(evidence, revision=99, output='Later serialization'))

    def test_cancelled_read_does_not_send_request(self):
        cancelled = threading.Event()
        cancelled.set()
        reader = SessionReader(cancelled)
        reader.process = Mock()
        with self.assertRaisesRegex(GuideError, 'Cancelled'):
            reader.call('thread/list', {})
        reader.process.stdin.write.assert_not_called()

    def test_oversized_answer_can_recover_with_complete_concise_followup(self):
        self.thread['turns'] = [turn(answer='x' * 100001)]
        with self.assertRaisesRegex(GuideError, 'concise response'):
            session_evidence(self.thread, 'Investigate greeting')
        self.thread['turns'].append(turn('summary', 'Summarize the evidence', 'The greeting is missing.'))
        evidence = session_evidence(self.thread, 'Investigate greeting')
        self.assertFalse(evidence['truncated'])
        self.assertEqual(evidence['output'], 'User: Summarize the evidence\n\nCodex: The greeting is missing.')

    def test_windows_cleanup_stops_owned_process_tree(self):
        reader = SessionReader()
        reader.process = Mock(pid=12345)
        reader.process.poll.return_value = None
        reader.reader = Mock()
        with patch('project_guide.codex_sessions.os.name', 'nt'), \
                patch('project_guide.codex_sessions.subprocess.run') as stop:
            reader.__exit__(None, None, None)
        self.assertEqual(stop.call_args.args[0], ['taskkill.exe', '/PID', '12345', '/T', '/F'])
        reader.process.stdin.close.assert_called_once()
        reader.process.stdout.close.assert_called_once()

    def test_explicit_read_keeps_selected_session_and_checks_project(self):
        reader = SessionReader()
        reader.call = Mock(return_value={'thread': self.thread})
        self.assertEqual(reader.read(self.root, 'cli1')['id'], 'cli1')
        reader.call.assert_called_once_with('thread/read', {'threadId': 'cli1', 'includeTurns': True})
        with self.assertRaises(GuideError):
            reader.read(self.root, 'different')

    def test_list_filters_own_sessions_and_other_projects(self):
        reader = SessionReader()
        reader.call = Mock(return_value={'data': [self.thread, dict(self.thread, source='exec'),
                                                  dict(self.thread, ephemeral=True),
                                                  dict(self.thread, source='appServer'),
                                                  dict(self.thread, cwd=str(self.root.parent))]})
        self.assertEqual(reader.list_sessions(self.root), [self.thread])
        self.assertEqual(reader.call.call_args.args[1]['sourceKinds'], ['cli'])
