import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PyQt6 import QtCore, QtWidgets
from project_guide.controller import ProjectGuideController
from project_guide.session import PromptSession
from project_guide.context import get_project_guide_context_section
from tests.test_prompt_guide import response, terminal


class PromptUITests(unittest.TestCase):
    def test_retry_retains_next_destination_after_failed_update(self):
        from project_guide.session import GuideSession
        from project_guide.conversation import project_update_store as updates
        from tests.test_project_guide import result
        session = GuideSession(self.temp.name, 'README.md', 'one')
        data = result()
        data['steps'].append(dict(data['steps'][0], id='second'))
        session.accept(session.begin(), data)
        self.controller.session = session
        updates.activate(session.id)
        self.addCleanup(updates.clear)
        updates.record(session.id, 'Keep the greeting')
        loop = QtCore.QEventLoop()
        self.controller.finished.connect(lambda *_: loop.quit())
        with patch('project_guide.controller.CodexRunner') as factory, \
                patch.object(self.controller, 'editor_state', return_value=([], [])), \
                patch.object(self.controller.alignment, 'start'):
            factory.return_value.run.side_effect = [RuntimeError('Temporary failure'), data]
            self.controller.handle('next')
            QtCore.QTimer.singleShot(2000, loop.quit)
            loop.exec()
            self.assertIn('Temporary failure', self.controller.panel.answer_text.toPlainText())
            self.controller.handle('retry')
            QtCore.QTimer.singleShot(2000, loop.quit)
            loop.exec()
        self.assertEqual(session.step['id'], 'second')
        self.assertIn('Step 2 of 2', self.controller.panel.answer_text.toPlainText())

    def test_next_advances_after_changed_requirements(self):
        from project_guide.session import GuideSession
        from tests.test_project_guide import result
        session = GuideSession(self.temp.name, 'README.md', 'one')
        original = result()
        original['steps'].append(dict(original['steps'][0], id='second'))
        session.accept(session.begin(), original)
        self.controller.session = session
        self.controller.last_action = 'adapt'
        changed = result()
        changed['steps'].append(dict(changed['steps'][0], id='second', explanation='Use formal greeting'))
        changed.update(conversation_change='Use a formal greeting.', accepted_requirements='Formal greeting')
        envelope = {'request': session.begin('adapt'), 'terminal': None,
                    'conversation_revision': 1, 'navigation': 'next'}
        with patch.object(self.controller.alignment, 'start'):
            self.controller.complete(self.controller.generation, envelope, changed, None)
        self.assertEqual(session.step['id'], 'second')
        self.assertFalse(self.controller.summary_pending)
        self.assertIn('Step 2 of 2', self.controller.panel.answer_text.toPlainText())

    def test_code_audio_updates_flow_to_next_step_without_unneeded_rewrites(self):
        from project_guide.session import GuideSession
        from project_guide.conversation import project_update_store as updates
        from tests.test_project_guide import result
        import copy
        session = GuideSession(self.temp.name, 'README.md', 'one')
        self.controller.session = session
        updates.activate(session.id)
        self.addCleanup(updates.clear)
        original = result()
        original['steps'].append(dict(original['steps'][0], id='second'))
        session.accept(session.begin(), original)
        self.controller.publish_context()
        section = get_project_guide_context_section()
        self.assertIn('"mode": "code"', section)
        self.assertIn(session.id, section)
        self.assertIn('Return a greeting.', section)
        updates.record(session.id, 'Keep the existing greeting requirement')
        loop = QtCore.QEventLoop()
        self.controller.finished.connect(lambda *_: loop.quit())

        def review(root, context, progress):
            self.assertEqual(context['action'], 'adapt')
            self.assertEqual(context['mode'], 'code')
            self.assertEqual(context['conversation']['revision'], 1)
            self.assertEqual(context['consumed_conversation_revision'], 0)
            self.assertEqual(context['accepted_requirements'], 'Return a greeting.')
            updates.record(session.id, 'Now use a formal greeting')
            candidate = copy.deepcopy(original)
            candidate['steps'][0]['code'] = 'unnecessary rewrite'
            return candidate

        with patch('project_guide.controller.CodexRunner') as factory, \
                patch.object(self.controller, 'editor_state', return_value=([], [])), \
                patch.object(self.controller.alignment, 'start'):
            factory.return_value.run.side_effect = review
            self.controller.handle('next')
            QtCore.QTimer.singleShot(2000, loop.quit)
            loop.exec()
        self.assertEqual(session.result, original)
        self.assertEqual(session.index, 1)
        self.assertEqual(session.conversation_revision, 1)
        self.assertEqual(updates.snapshot(session.id)['revision'], 2)
        changed = result()
        changed.update(conversation_change='Use a formal greeting.',
                       accepted_requirements='Return a formal greeting.')
        self.controller.last_action = 'adapt'
        envelope = {'request': session.begin('adapt'), 'terminal': None,
                    'conversation_revision': 2, 'navigation': 'next'}
        with patch.object(self.controller.alignment, 'start'):
            self.controller.complete(self.controller.generation, envelope, changed, None)
        self.assertEqual(session.result, changed)
        self.assertFalse(self.controller.summary_pending)
        self.assertIn('Step 1 of 1', self.controller.panel.answer_text.toPlainText())
        self.assertIn('Return a formal greeting.', get_project_guide_context_section())

    def test_code_navigation_without_audio_keeps_steps(self):
        from project_guide.session import GuideSession
        from project_guide.conversation import project_update_store as updates
        from tests.test_project_guide import result
        session = GuideSession(self.temp.name, 'README.md', 'one')
        self.controller.session = session
        updates.activate(session.id)
        self.addCleanup(updates.clear)
        data = result()
        data['steps'].append(dict(data['steps'][0], id='second'))
        session.accept(session.begin(), data)
        with patch.object(self.controller, 'run', side_effect=AssertionError('No new requirements')), \
                patch.object(self.controller.alignment, 'start'):
            self.controller.handle('next')
        self.assertEqual(session.index, 1)
        self.assertEqual(session.result, data)

    def test_code_guide_shows_full_approach_before_steps(self):
        from project_guide.session import GuideSession
        from tests.test_project_guide import result
        session = GuideSession(self.temp.name, 'README.md', 'one')
        self.controller.session = session
        self.controller.last_action = 'analyze'
        question = result()
        question.update(question='Which greeting?', choices=['Formal', 'Casual'], steps=[])
        self.controller.complete(self.controller.generation, session.begin(), question, None)
        self.assertIn('Which greeting?', self.controller.panel.answer_text.toPlainText())
        data = result()
        data['summary'] = 'Construct a formal greeting, return it, and check empty input.'
        data['steps'].append(dict(data['steps'][0], id='second', explanation='Second step explanation'))
        self.controller.complete(self.controller.generation, session.begin(), data, None)
        text = self.controller.panel.answer_text.toPlainText()
        self.assertTrue(text.startswith('Full approach\n\n'))
        self.assertIn(data['summary'], text)
        self.assertNotIn(data['steps'][0]['diff'], text)
        self.assertIn('Next', self.labels())
        with patch.object(self.controller.alignment, 'start'):
            next_button = next(b for b in self.controller.panel.findChildren(QtWidgets.QPushButton)
                               if b.text() == 'Next' and not b.isHidden())
            next_button.click()
            step_text = self.controller.panel.answer_text.toPlainText()
            self.assertIn('Step 1 of 2', step_text)
            self.assertIn(data['steps'][0]['explanation'], step_text)
            self.assertNotIn(data['summary'], step_text)
            self.assertNotIn(data['summary'], self.controller.panel._guidance_html)
            self.controller.handle('next')
            step_text = self.controller.panel.answer_text.toPlainText()
            self.assertIn('Step 2 of 2', step_text)
            self.assertNotIn(data['summary'], step_text)
        self.assertFalse(self.controller.summary_pending)
        self.assertNotIn('Start guidance', self.labels())

    def test_first_prompt_after_clarification_shows_approach_first(self):
        session = PromptSession(self.temp.name, 'README.md', 'one')
        question = response('', 'clarification')
        question.update(question='Which greeting?', choices=['Formal', 'Casual'])
        session.accept(session.begin(), question)
        self.controller.session = session
        self.controller.last_action = 'clarify'
        data = response('Investigate the greeting behavior')
        data['approach'] = 'Full approach: establish requirements, trace behavior, agree the design, implement, and verify.'
        self.controller.complete(self.controller.generation, session.begin(), data, None)
        self.assertIn(data['approach'], self.controller.panel.answer_text.toPlainText())
        self.assertNotIn(data['prompt'], self.controller.panel.answer_text.toPlainText())
        self.assertIn('Show prompt', self.labels())
        self.controller.handle('start')
        self.assertIn(data['prompt'], self.controller.panel.answer_text.toPlainText())

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        Path(self.temp.name, 'README.md').write_text('Implement hello')
        self.controller = ProjectGuideController(None)
        self.addCleanup(self.controller.close)
        self.controller.root, self.controller.window = self.temp.name, 'one'

    def labels(self):
        return [b.text() for b in self.controller.panel.findChildren(QtWidgets.QPushButton) if not b.isHidden()]

    def prompt_session(self):
        session = PromptSession(self.temp.name, 'README.md', 'one')
        session.pin_terminal(terminal())
        session.codex_session_id = 'cli1'
        session.accept(session.begin(), response())
        self.controller.session = session
        return session

    def test_problem_selection_offers_mode_before_generation(self):
        with patch.object(self.controller, 'run') as run:
            self.controller.handle('select_problem', 'README.md')
        self.assertIn('Prompt Guide', self.labels())
        self.assertIn('Code Guide', self.labels())
        run.assert_not_called()

    def test_prompt_mode_starts_without_terminal_selection(self):
        self.controller.handle('select_problem', 'README.md')
        with patch.object(self.controller, 'run') as run, \
                patch.object(self.controller.bridge, 'terminals', side_effect=AssertionError('No terminal selection')):
            self.controller.handle('select_mode', 'prompt')
        run.assert_called_once_with('analyze')
        self.assertIsInstance(self.controller.session, PromptSession)

    def test_first_check_selects_session_and_later_checks_reuse_it(self):
        session = self.prompt_session()
        session.codex_session_id = None
        with patch.object(self.controller, 'choose_session') as choose, patch.object(self.controller, 'run') as run:
            self.controller.handle('check_output')
            choose.assert_called_once()
            run.assert_not_called()
            self.controller.session_options = {'chosen': {'id': 'chosen', 'name': 'My session'}}
            self.controller.handle('select_session', 'chosen')
            self.controller.handle('check_output')
            self.assertEqual(session.codex_session_id, 'chosen')
            self.assertEqual(run.call_count, 2)
            choose.assert_called_once()

    def test_cancelled_session_listing_cannot_replace_panel(self):
        self.prompt_session()
        generation = self.controller.generation
        self.controller.cancel()
        with patch.object(self.controller.panel, 'present') as present:
            self.controller.show_sessions(generation, [{'id': 'stale'}], None)
        present.assert_not_called()

    def test_retry_after_cancelled_picker_reopens_picker_without_generation(self):
        self.prompt_session()
        self.controller.last_action = 'sessions'
        self.controller.cancel()
        with patch.object(self.controller, 'choose_session') as choose, patch.object(self.controller, 'run') as run:
            self.controller.handle('retry')
        choose.assert_called_once()
        run.assert_not_called()

    def test_program_terminal_review_preserves_codex_session_choice(self):
        session = self.prompt_session()
        evidence = terminal('AssertionError: expected Hello Ada, got None', 4)
        self.controller.program_terminals = {evidence['id']: evidence}
        loop = QtCore.QEventLoop()
        self.controller.finished.connect(lambda *_: loop.quit())
        captured = {}
        def review(root, context, progress):
            captured.update(context)
            return response('Fix the greeting return value')
        with patch('project_guide.controller.CodexRunner') as factory, \
                patch.object(self.controller, 'editor_state', return_value=([], [])), \
                patch.object(self.controller.bridge, 'terminal_output', return_value=evidence) as read, \
                patch('project_guide.controller.read_session_output') as read_session:
            factory.return_value.run.side_effect = review
            self.controller.handle('select_program_terminal', evidence['id'])
            QtCore.QTimer.singleShot(2000, loop.quit)
            loop.exec()
        read.assert_called_once_with('one', session.files.root, evidence['id'])
        read_session.assert_not_called()
        self.assertEqual(captured['action'], 'check_output')
        self.assertEqual(captured['terminal_output']['output'], evidence['output'])
        self.assertEqual(session.codex_session_id, 'cli1')
        self.assertIn('Check terminal output', self.labels())

    def test_prompt_display_copy_and_history_never_fit_editor(self):
        session = self.prompt_session()
        session.accept(session.begin(), response('Run tests'))
        with patch.object(self.controller.alignment, 'start', side_effect=AssertionError('Must not fit prompts')):
            self.controller.handle('start')
            self.assertIn('Run tests', self.controller.panel.answer_text.toPlainText())
            self.assertIn('Copy prompt', self.labels())
            self.controller.handle('previous')
            self.controller.handle('copy_prompt')
            self.assertEqual(self.app.clipboard().text(), 'Implement the greeting')
            self.assertEqual(len(session.history), 2)
            self.assertNotIn('Check output', self.labels())
            self.controller.handle('next')
            self.assertIn('Check output', self.labels())

    def test_context_exposes_latest_prompt_not_historical_navigation(self):
        session = self.prompt_session()
        session.accept(session.begin(), response('Run tests'))
        session.move(-1)
        self.controller.publish_context()
        section = get_project_guide_context_section()
        self.assertIn('Run tests', section)
        self.assertIn('Use Python', section)

    def test_check_sends_pinned_output_and_retains_prompt_on_uncertain_result(self):
        session = self.prompt_session()
        loop = QtCore.QEventLoop()
        self.controller.finished.connect(lambda *_: loop.quit())
        captured = {}

        def review(root, context, progress):
            captured.update(context)
            return response('', 'cannot_verify')

        with patch('project_guide.controller.CodexRunner') as factory, \
                patch.object(self.controller, 'editor_state', return_value=([], [])), \
                patch('project_guide.controller.read_session_output', return_value=terminal('Working', 2)) as read:
            factory.return_value.run.side_effect = review
            self.controller.handle('check_output')
            QtCore.QTimer.singleShot(2000, loop.quit)
            loop.exec()
        self.assertEqual(captured.get('mode'), 'prompt')
        self.assertEqual(captured['current_prompt'], 'Implement the greeting')
        self.assertEqual(captured['terminal_output']['output'], 'Working')
        self.assertEqual(read.call_args.args[:3], (session.files.root, 'cli1', 'Implement the greeting'))
        self.assertEqual(len(session.history), 1)
        self.assertIn('Implement the greeting', self.controller.panel.answer_text.toPlainText())

    def test_truncated_tail_reaches_reviewer_and_can_advance(self):
        session = self.prompt_session()
        evidence = terminal('Latest complete response', 2)
        evidence['truncated'] = True
        loop = QtCore.QEventLoop()
        self.controller.finished.connect(lambda *_: loop.quit())
        captured = {}

        def review(root, context, progress):
            captured.update(context)
            result = response('Inspect greeting tests')
            result['findings'] = 'Older capture is missing; latest response supports investigation.'
            return result

        with patch('project_guide.controller.CodexRunner') as factory, \
                patch.object(self.controller, 'editor_state', return_value=([], [])), \
                patch('project_guide.controller.read_session_output', return_value=evidence):
            factory.return_value.run.side_effect = review
            self.controller.handle('check_output')
            QtCore.QTimer.singleShot(2000, loop.quit)
            loop.exec()
        self.assertEqual(captured['terminal_output'], evidence)
        self.assertEqual(len(session.history), 2)
        self.assertIn('Inspect greeting tests', self.controller.panel.answer_text.toPlainText())
        self.assertIn('Older capture is missing', self.controller.panel.answer_text.toPlainText())

    def test_session_review_updates_automatic_session_label(self):
        session = self.prompt_session()
        evidence = terminal('Completed saved answer', 2)
        evidence.update(source='codex_session', id='latest-cli', name='Latest project session')
        envelope = {'request': session.begin(), 'terminal': evidence, 'conversation_revision': 0}
        self.controller.complete(self.controller.generation, envelope, response('Next investigation'), None)
        self.assertEqual(session.codex_session_id, 'latest-cli')
        self.assertIn('Latest project session', self.controller.panel.answer_text.toPlainText())
        self.assertNotIn('Select terminal', self.labels())

    def test_cancelled_worker_cannot_replace_new_request_token(self):
        session = self.prompt_session()
        workers = []

        class DeferredThread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                if getattr(self.target, '__name__', '') == 'worker':
                    workers.append(self.target)

        with patch('project_guide.controller.threading.Thread', DeferredThread), \
                patch('project_guide.controller.CodexRunner') as factory, \
                patch.object(self.controller, 'editor_state', return_value=([], [])):
            factory.return_value.run.return_value = response('New prompt')
            self.controller.run('analyze')
            self.controller.cancel()
            self.controller.run('analyze')
            request = session.request
            workers[0]()
            self.assertEqual(session.request, request)
            workers[1]()
            self.assertEqual(session.result['prompt'], 'New prompt')

    def test_audio_arriving_during_generation_remains_pending(self):
        from project_guide.conversation import project_update_store as updates
        session = self.prompt_session()
        updates.activate(session.id)
        updates.record(session.id, 'Use Python')
        loop = QtCore.QEventLoop()
        self.controller.finished.connect(lambda *_: loop.quit())

        def review(root, context, progress):
            updates.record(session.id, 'Also support empty names')
            self.assertEqual(context['conversation']['revision'], 1)
            return response('Implement greeting with tests')

        with patch('project_guide.controller.CodexRunner') as factory, \
                patch.object(self.controller, 'editor_state', return_value=([], [])):
            factory.return_value.run.side_effect = review
            self.controller.run('analyze')
            QtCore.QTimer.singleShot(2000, loop.quit)
            loop.exec()
        self.assertEqual(session.conversation_revision, 1)
        self.assertEqual(updates.snapshot(session.id)['revision'], 2)

    def test_initial_cannot_verify_shows_findings_and_retry(self):
        session = PromptSession(self.temp.name, 'README.md', 'one')
        data = response('', 'cannot_verify')
        data['findings'] = 'Need a readable problem statement.'
        session.accept(session.begin(), data)
        self.controller.session = session
        self.controller.summary_pending = True
        self.controller.render_result()
        self.assertIn('Need a readable problem statement.', self.controller.panel.answer_text.toPlainText())
        self.assertIn('Retry', self.labels())
        self.assertNotIn('Check output', self.labels())

    def test_clarification_retains_evidence_until_resolved(self):
        session = self.prompt_session()
        question = response('', 'clarification')
        question.update(question='Which greeting?', choices=['Formal', 'Casual'])
        envelope = {'request': session.begin(), 'terminal': terminal('Which greeting?', 2), 'conversation_revision': 0}
        self.controller.complete(self.controller.generation, envelope, question, None)
        self.assertIn('Formal', self.labels())
        resolved = {'request': session.begin(), 'terminal': terminal('Which greeting?', 2), 'conversation_revision': 0}
        self.controller.complete(self.controller.generation, resolved, response('Use a formal greeting'), None)
        self.assertEqual(session.result['prompt'], 'Use a formal greeting')
        from project_guide.files import GuideError
        with self.assertRaises(GuideError):
            session.prepare_check(terminal('Which greeting?', 3))
