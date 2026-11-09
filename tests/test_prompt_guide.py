import tempfile
import unittest
from pathlib import Path

from project_guide import session as sessions
from project_guide.files import GuideError


def response(prompt='Implement the greeting', status='ready'):
    return dict(approach='Inspect, implement, verify.', explanation='Start small.',
                prompt=prompt, findings='', question='', choices=[], blocked='',
                status=status, accepted_requirements='Use Python', conversation_change='')


def terminal(output='Codex ready', revision=1):
    return dict(id='t1', execution_id='e1', revision=revision, output=output,
                running=True, truncated=False, exit_code=None, name='Codex', cwd='')


class PromptSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        Path(self.temp.name, 'README.md').write_text('Implement hello')

    def make_session(self):
        self.assertTrue(hasattr(sessions, 'PromptSession'), 'Prompt mode needs a separate session contract')
        return sessions.PromptSession(self.temp.name, 'README.md', 'window')

    def test_initial_response_and_history_do_not_precompute_future_prompts(self):
        session = self.make_session()
        session.accept(session.begin(), response())
        self.assertEqual(session.current['prompt'], 'Implement the greeting')
        self.assertEqual(len(session.history), 1)
        session.move(1)
        self.assertEqual(len(session.history), 1)
        self.assertEqual(session.result['status'], 'ready')

    def test_running_cli_can_advance_but_same_evidence_cannot(self):
        session = self.make_session()
        session.pin_terminal(terminal())
        session.accept(session.begin(), response())
        evidence = terminal('Implemented greeting', 2)
        session.prepare_check(evidence)
        session.accept(session.begin(), response('Run greeting tests'))
        self.assertEqual(len(session.history), 2)
        with self.assertRaises(GuideError):
            session.prepare_check(terminal('Implemented greeting', 3))
        session.move(-1)
        self.assertEqual(session.current['prompt'], 'Implement the greeting')
        self.assertEqual(session.result['prompt'], 'Run greeting tests')

    def test_uncertain_review_preserves_prompt_and_can_be_rechecked(self):
        session = self.make_session()
        session.pin_terminal(terminal())
        session.accept(session.begin(), response())
        evidence = terminal('Still working', 2)
        session.prepare_check(evidence)
        session.accept(session.begin(), response('', 'cannot_verify'))
        self.assertEqual(session.current['prompt'], 'Implement the greeting')
        self.assertEqual(len(session.history), 1)
        session.prepare_check(evidence)

    def test_cancel_does_not_consume_terminal_or_conversation_snapshot(self):
        session = self.make_session()
        session.pin_terminal(terminal())
        evidence = terminal('Done', 2)
        session.prepare_check(evidence)
        session.pending_conversation_revision = 3
        token = session.begin()
        session.cancel()
        self.assertFalse(session.accept(token, response()))
        self.assertEqual(session.conversation_revision, 0)
        session.prepare_check(evidence)

    def test_wrong_or_empty_terminal_never_advances(self):
        session = self.make_session()
        session.pin_terminal(terminal())
        for changes in ({'id': 'other'}, {'output': ''}):
            evidence = terminal('Done', 2)
            evidence.update(changes)
            with self.assertRaises(GuideError):
                session.prepare_check(evidence)

    def test_truncated_capture_is_reviewable_but_not_reusable_after_advancing(self):
        session = self.make_session()
        session.pin_terminal(terminal())
        session.accept(session.begin(), response())
        evidence = terminal('Complete latest response after older scrollback was discarded', 2)
        evidence['truncated'] = True
        session.prepare_check(evidence)
        session.accept(session.begin(), response('Inspect the greeting tests'))
        self.assertEqual(len(session.history), 2)
        evidence['revision'] += 1
        with self.assertRaises(GuideError):
            session.prepare_check(evidence)

    def test_inconclusive_truncated_capture_retains_prompt_and_can_be_rechecked(self):
        session = self.make_session()
        session.pin_terminal(terminal())
        session.accept(session.begin(), response())
        evidence = terminal('...partial response', 2)
        evidence['truncated'] = True
        session.prepare_check(evidence)
        session.accept(session.begin(), response('', 'cannot_verify'))
        self.assertEqual(session.current['prompt'], 'Implement the greeting')
        self.assertEqual(len(session.history), 1)
        session.prepare_check(evidence)

    def test_complete_has_no_new_prompt_and_requirements_persist(self):
        session = self.make_session()
        session.accept(session.begin(), response())
        session.pending_conversation_revision = 4
        session.accept(session.begin(), response('', 'complete'))
        self.assertEqual(len(session.history), 1)
        self.assertEqual(session.accepted_requirements, 'Use Python')
        self.assertEqual(session.conversation_revision, 4)

    def test_ready_requires_nonempty_prompt(self):
        session = self.make_session()
        with self.assertRaises(GuideError):
            session.accept(session.begin(), response(''))

    def test_repinning_same_terminal_preserves_unconsumed_evidence(self):
        session = self.make_session()
        session.pin_terminal(terminal())
        evidence = terminal('Question?', 2)
        session.prepare_check(evidence)
        session.pin_terminal(evidence)
        session.prepare_check(evidence)

    def test_changing_terminal_discards_cached_clarification_output(self):
        session = self.make_session()
        session.pin_terminal(terminal())
        session.last_terminal_output = terminal('Question?', 2)
        other = terminal('Other ready')
        other['id'] = 't2'
        session.pin_terminal(other)
        self.assertIsNone(session.last_terminal_output)
