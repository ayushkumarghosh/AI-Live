import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PyQt6 import QtCore, QtGui, QtWidgets
from project_guide.ui import ProjectGuidePanel
from project_guide.session import GuideSession
from project_guide.controller import ProjectGuideController
from tests.test_project_guide import result


class GuideUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.panel = ProjectGuidePanel()
        self.addCleanup(self.panel.deleteLater)

    def test_no_editable_input_widgets(self):
        self.assertEqual(self.panel.findChildren(QtWidgets.QLineEdit), [])
        self.assertTrue(all(edit.isReadOnly() for edit in self.panel.findChildren(QtWidgets.QTextEdit)))

    def test_fitted_text_has_tinted_background_and_normal_view_restores_it(self):
        self.panel.present('Guidance text', [], guidance=True)
        self.panel.show()
        self.panel.fit_editor(QtCore.QRect(100, 100, 700, 500), 112)
        fragment = self.panel.answer_text.document().begin().begin().fragment()
        color = fragment.charFormat().background().color()
        self.assertEqual(color, QtGui.QColor(24, 52, 72, 190))
        self.panel.release_editor()
        fragment = self.panel.answer_text.document().begin().begin().fragment()
        self.assertEqual(fragment.charFormat().background().style(), QtCore.Qt.BrushStyle.NoBrush)

    def test_scroll_buttons_move_fitted_guide_without_refitting(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('task')
            controller = ProjectGuideController(None)
            self.addCleanup(controller.close)
            session = GuideSession(directory, 'README.md', 'one')
            session.result = result()
            session.result['steps'][0]['explanation'] = '\n'.join(f'Guidance row {i}' for i in range(90))
            controller.session = session
            panel = controller.panel
            panel.show_step(session)
            panel.show()
            panel.fit_editor(QtCore.QRect(100, 100, 700, 500), 112)
            self.app.processEvents()
            buttons = {panel.buttons.itemAt(i).widget().text(): panel.buttons.itemAt(i).widget()
                       for i in range(panel.buttons.count())}
            bar = panel.answer_text.verticalScrollBar()
            with patch.object(controller.alignment, 'start', side_effect=AssertionError('No refit')):
                buttons['Scroll down'].click()
                self.assertEqual(bar.value(), 72)
                buttons['Scroll up'].click()
                self.assertEqual(bar.value(), 0)
                buttons['Scroll up'].click()
                self.assertEqual(bar.value(), 0)
                for _ in range(100):
                    buttons['Scroll down'].click()
                self.assertEqual(bar.value(), bar.maximum() // 24 * 24)

    def test_fitted_guidance_stays_on_interleaved_grid_through_wrapping_and_scroll(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('task')
            session = GuideSession(directory, 'README.md', 'one')
            session.result = result()
            session.result['steps'][0]['explanation'] = 'Long summary with wrapping. ' * 40
            self.panel.show_step(session)
            self.panel.show()
            self.panel.fit_editor(QtCore.QRect(650, 88, 770, 700), 424, 24)
            self.app.processEvents()
            self.assertEqual(self.panel.geometry(), QtCore.QRect(650, 88, 770, 700))
            edit = self.panel.answer_text
            self.assertEqual(edit.viewport().mapToGlobal(QtCore.QPoint()).x(), 650)
            doc = edit.document()
            block = doc.begin()
            baseline_phases = []
            while block.isValid():
                layout = block.layout()
                for i in range(layout.lineCount()):
                    line = layout.lineAt(i)
                    baseline = (edit.viewport().mapToGlobal(QtCore.QPoint()).y()
                                + layout.position().y() + line.y() + line.ascent())
                    baseline_phases.append(round(baseline % 24, 2))
                block = block.next()
            self.assertGreater(len(baseline_phases), 20)
            self.assertLess(max(baseline_phases) - min(baseline_phases), 1)
            edit.verticalScrollBar().setValue(37)
            self.assertEqual(edit.verticalScrollBar().value() % 24, 0)

    def test_leaving_guidance_restores_normal_panel(self):
        self.panel.show()
        self.app.processEvents()
        original = self.panel.geometry()
        self.panel.fit_editor(QtCore.QRect(650, 88, 770, 700), 424, 24)
        self.panel.present('Choose a workspace', [], [('A', 'projects', None)], selection=True)
        self.app.processEvents()
        self.assertEqual(self.panel.geometry(), original)
        self.assertFalse(self.panel.title_bar.isHidden())

    def test_small_editor_fit_does_not_inherit_footer_minimum_size(self):
        self.panel.banner.setText('C:/Users/ayush/Downloads/' + 'long-project-folder/' * 8)
        self.panel.present('Guidance\n' * 40,
                           [('Check my changes', 'review', None)] * 12, guidance=True)
        self.panel.show()
        self.app.processEvents()
        target = QtCore.QRect(260, 344, 455, 302)
        self.panel.fit_editor(target, 350, 24)
        self.app.processEvents()
        self.assertEqual(self.panel.geometry(), target)
        self.assertLessEqual(self.panel.minimumSizeHint().width(), target.width())
        self.assertLessEqual(self.panel.minimumSizeHint().height(), target.height())
        self.assertGreaterEqual(self.panel.answer_text.viewport().height(), 144)
        self.assertGreaterEqual(self.panel.banner.contentsRect().height(), self.panel.banner.fontMetrics().height())

    def test_fitted_scroll_reaches_the_last_line(self):
        self.panel.present('\n'.join(f'Guidance line {i}' for i in range(70)), [], guidance=True)
        self.panel.show()
        self.panel.fit_editor(QtCore.QRect(100, 100, 700, 401), 112, 24)
        self.app.processEvents()
        edit = self.panel.answer_text
        bar = edit.verticalScrollBar()
        bar.setValue(bar.maximum())
        cursor = QtGui.QTextCursor(edit.document())
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        self.assertLessEqual(edit.cursorRect(cursor).bottom(), edit.viewport().height())
        self.assertEqual(bar.value() % 24, 0)

    def test_fitted_baseline_is_halfway_between_editor_ink_centers(self):
        self.panel.present('Sample guidance', [], guidance=True)
        self.panel.show()
        self.panel.fit_editor(QtCore.QRect(100, 88, 700, 400), 94.5, 24)
        self.app.processEvents()
        font = QtGui.QFont('Consolas')
        font.setPixelSize(12)
        ink = QtGui.QFontMetricsF(font).tightBoundingRect('0123456789').center().y()
        layout = self.panel.answer_text.document().begin().layout()
        line = layout.lineAt(0)
        center = (self.panel.answer_text.viewport().mapToGlobal(QtCore.QPoint()).y()
                  + layout.position().y() + line.y() + line.ascent() + ink)
        self.assertAlmostEqual((center - 94.5) % 24, 12, delta=0.75)

    def test_alignment_recovers_from_a_disconnected_workspace(self):
        from project_guide.alignment_tracker import EditorAlignmentTracker
        from project_guide.files import GuideError

        def disconnected():
            raise GuideError('Disconnected')

        self.panel.show()
        self.panel._guidance_html = 'Guidance'
        self.panel.fit_editor(QtCore.QRect(100, 88, 700, 400), 94.5, 24)
        tracker = EditorAlignmentTracker(self.panel, disconnected)
        tracker.timer.start()
        tracker.request()
        self.assertFalse(tracker.timer.isActive())
        self.assertIsNone(self.panel._editor_fit)

    def test_fitted_button_click_is_delivered_once_and_drag_out_cancels(self):
        self.panel.present('Guidance', [('Next', 'next', None)], guidance=True)
        self.panel.show()
        self.panel.fit_editor(QtCore.QRect(100, 100, 700, 500), 112)
        self.app.processEvents()
        button = self.panel.buttons.itemAt(0).widget()
        point = button.mapTo(self.panel, button.rect().center())
        actions = []
        self.panel.action.connect(lambda action, _: actions.append(action))
        self.panel.fitted_button.emit('down', point)
        self.panel.fitted_button.emit('up', point)
        self.app.processEvents()
        self.assertEqual(actions, ['next'])
        self.panel.fitted_button.emit('down', point)
        self.panel.fitted_button.emit('up', QtCore.QPoint(5, 5))
        self.app.processEvents()
        self.assertEqual(actions, ['next'])
        self.assertFalse(button.isDown())

    def test_guidance_actions_include_terminal_without_copy_or_open(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('task')
            session = GuideSession(directory, 'README.md', 'one')
            session.result = result()
            self.panel.show_step(session)
            labels = [self.panel.buttons.itemAt(i).widget().text() for i in range(self.panel.buttons.count())]
            self.assertIn('Check terminal output', labels)
            self.assertFalse({'Copy code', 'Copy diff', 'Open location'} & set(labels))

    def test_fitted_input_only_accepts_buttons(self):
        self.panel.present('Guidance', [('Next', 'next', None)], guidance=True)
        self.panel.show()
        self.panel.fit_editor(QtCore.QRect(100, 100, 700, 500), 112)
        self.app.processEvents()
        button = self.panel.buttons.itemAt(0).widget()
        self.assertTrue(self.panel.accepts_fitted_input(button.mapTo(self.panel, button.rect().center())))
        self.assertFalse(self.panel.accepts_fitted_input(self.panel.answer_text.mapTo(self.panel, QtCore.QPoint(20, 20))))
        self.panel.release_editor()
        self.assertTrue(self.panel.accepts_fitted_input(QtCore.QPoint(20, 20)))

    def test_stationary_editor_does_not_repeat_screen_capture(self):
        from project_guide.alignment_tracker import EditorAlignmentTracker
        from unittest.mock import Mock
        self.panel.present('Guidance', [], guidance=True)
        self.panel._guidance_html = 'Guidance'
        self.panel.show()
        tracker = EditorAlignmentTracker(self.panel, lambda: ('root', 'a.py', None))
        tracker.timer.start()
        screen = Mock()
        screen.availableGeometry.return_value = QtCore.QRect(0, 0, 1400, 1000)
        screen.devicePixelRatio.return_value = 1
        bounds = dict(hwnd=1, foreground=True, viewport=(100, 100, 800, 600), row=None,
                      editor_key=('root', 'a.py', None))
        with patch('project_guide.alignment_tracker.logical_viewport',
                   return_value=(screen, QtCore.QRect(100, 100, 700, 500))), \
             patch('project_guide.alignment_tracker.measure_gutter', return_value=112) as capture:
            tracker.receive(0, bounds)
            tracker.receive(0, bounds)
            tracker.receive(0, dict(bounds, foreground=False))
            tracker.receive(0, bounds)
            self.assertEqual(capture.call_count, 1)
            tracker.receive(0, dict(bounds, editor_key=('root', 'b.py', None)))
            self.assertEqual(capture.call_count, 2)
        tracker.stop()

    def test_missing_alignment_dependency_is_visible(self):
        from project_guide.alignment_tracker import EditorAlignmentTracker
        self.panel.show()
        self.panel._guidance_html = 'Guidance'
        tracker = EditorAlignmentTracker(self.panel, lambda: ('root', 'file', None))
        loop = QtCore.QEventLoop()
        tracker.measured.connect(lambda *_: loop.quit())
        with patch('project_guide.alignment_tracker.WindowsEditorLocator',
                   side_effect=ModuleNotFoundError("No module named 'comtypes'")):
            tracker.start()
            QtCore.QTimer.singleShot(2000, loop.quit)
            loop.exec()
        self.assertIn('comtypes', self.panel.banner.text())
        self.assertFalse(tracker.timer.isActive())

    def test_code_is_highlighted_and_literal_markup_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('task')
            session = GuideSession(directory, 'README.md', 'one')
            session.result = result()
            code = 'def hello(): return "<tag> & ```"'
            session.step['code'] = code
            session.step['diff'] = ('--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n'
                                    '-def hello(): pass\n+' + code + '\n')
            self.panel.show_step(session)
            self.assertIn(code, self.panel.answer_text.toPlainText())
            self.assertIn('def hello(): pass', self.panel.answer_text.toPlainText())
            rendered = self.panel.answer_text.toHtml().lower()
            self.assertIn('#8bd49c', rendered)
            self.assertIn('#f08080', rendered)
            self.assertNotIn('#183b2b', rendered)
            self.assertNotIn('#48262b', rendered)
            self.assertIn('consolas', rendered)
            self.assertIn('#66d9ef', rendered)
            self.assertEqual(session.step['code'], code)

    def test_picker_uses_available_height_and_restores_preview(self):
        options = [(f'file{i}.md', 'preview', str(i)) for i in range(25)]
        self.panel.present('Select a problem file', [], options, selection=True)
        self.panel.show()
        self.app.processEvents()
        initial = self.panel.options.height()
        self.assertGreater(initial, 300)
        self.panel.resize(780, 800)
        self.app.processEvents()
        self.assertGreater(self.panel.options.height(), initial)
        self.panel.present('Full problem preview\n' * 100, [])
        self.app.processEvents()
        self.assertTrue(self.panel.options.isHidden())
        self.assertGreater(self.panel.answer_text.height(), 300)

    def test_audio_context_tracks_selection_navigation_and_clear(self):
        from project_guide.context import get_project_guide_context_section
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('Build a greeting app')
            controller = ProjectGuideController(None)
            self.addCleanup(controller.close)
            controller.root, controller.window = directory, 'one'
            changes = []
            controller.context_changed.connect(lambda: changes.append(True))
            with patch.object(controller, 'run'):
                controller.handle('select_problem', 'README.md')
            self.assertIn('Build a greeting app', get_project_guide_context_section())
            data = result()
            data['steps'].append(dict(data['steps'][0], id='second', code='second_step_code'))
            controller.session.result = data
            controller.handle('next')
            self.assertIn('second_step_code', get_project_guide_context_section())
            controller.clear()
            self.assertEqual(get_project_guide_context_section(), '')
            self.assertEqual(len(changes), 3)

    def test_steps_are_buttons_and_navigation_is_not_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('task')
            Path(directory, 'main.py').write_text('def hello(): pass')
            session = GuideSession(directory, 'README.md', 'one')
            request = session.begin()
            session.accept(request, result())
            self.panel.show_step(session)
            labels = [b.text() for b in self.panel.findChildren(QtWidgets.QPushButton) if not b.isHidden()]
            self.assertIn('Check my changes', labels)
            self.assertIn('Check terminal output', labels)
            self.assertNotIn('Copy diff', labels)
            self.assertNotIn('Apply', labels)
            self.assertIn('main.py', self.panel.answer_text.toPlainText())
            self.assertEqual(session.result['verdict'], 'not_reviewed')

    def test_reopening_preserves_pending_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('task')
            Path(directory, 'main.py').write_text('def hello(): pass')
            controller = ProjectGuideController(None)
            self.addCleanup(controller.close)
            controller.session = GuideSession(directory, 'README.md', 'one')
            controller.session.result = dict(result(), question='Which greeting?', choices=['Formal', 'Casual'])
            with patch.object(controller.bridge, 'start'):
                controller.show()
                controller.panel.close()
                controller.show()
            labels = [b.text() for b in controller.panel.findChildren(QtWidgets.QPushButton) if not b.isHidden()]
            self.assertIn('Formal', labels)
            self.assertIn('Casual', labels)

    def test_cancelled_completion_does_not_update_the_panel(self):
        controller = ProjectGuideController(None)
        self.addCleanup(controller.close)
        controller.generation = 'old'
        controller.panel.present('Current view', [])
        controller.cancel()
        controller.complete('old', None, result(), None)
        self.assertEqual(controller.panel.answer_text.toPlainText(), 'Current view')

    def test_terminal_button_requests_review_with_captured_output(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('task')
            controller = ProjectGuideController(None)
            self.addCleanup(controller.close)
            controller.root, controller.window = directory, 'one'
            controller.session = GuideSession(directory, 'README.md', 'one')
            controller.session.result = result()
            evidence = dict(command='pytest', output='1 failed', running=False, exit_code=1)
            loop = QtCore.QEventLoop()
            controller.finished.connect(lambda *_: loop.quit())
            with patch('project_guide.controller.CodexRunner') as factory, \
                 patch.object(controller, 'editor_state', return_value=([], [])), \
                 patch.object(controller.bridge, 'terminal_output', return_value=evidence) as terminal:
                factory.return_value.run.return_value = result()
                controller.handle('terminal')
                QtCore.QTimer.singleShot(2000, loop.quit)
                loop.exec()
                terminal.assert_called_once_with('one', controller.session.files.root)
                context = factory.return_value.run.call_args.args[1]
                self.assertEqual(context['action'], 'terminal')
                self.assertEqual(context['terminal_output'], evidence)

    def test_copy_does_not_require_editor_or_file_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('task')
            controller = ProjectGuideController(None)
            self.addCleanup(controller.close)
            controller.session = GuideSession(directory, 'README.md', 'one')
            controller.session.result = result()
            with patch.object(controller, 'editor_state', side_effect=AssertionError('No editor validation')):
                controller.handle('copy')
            self.assertEqual(self.app.clipboard().text(), result()['steps'][0]['code'])

    def test_copy_diff_preserves_patch_and_does_not_open_editor(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('task')
            controller = ProjectGuideController(None)
            self.addCleanup(controller.close)
            controller.session = GuideSession(directory, 'README.md', 'one')
            controller.session.result = result()
            self.app.clipboard().clear()
            with patch.object(controller.bridge, 'open_location', side_effect=AssertionError('No editor action')):
                controller.handle('copy_diff')
            self.assertEqual(self.app.clipboard().text(), result()['steps'][0]['diff'])

    def test_open_uses_codex_line_without_reading_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'README.md').write_text('task')
            controller = ProjectGuideController(None)
            self.addCleanup(controller.close)
            controller.root, controller.window = directory, 'one'
            controller.session = GuideSession(directory, 'README.md', 'one')
            controller.session.result = result()
            controller.session.step.update(anchor='not saved', line=999)
            with patch.object(controller.bridge, 'open_location') as opening:
                controller.handle('open')
            opening.assert_called_once_with('one', directory, 'main.py', 999)
