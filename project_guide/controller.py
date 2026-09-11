"""Coordinates pinned workspace sessions and worker results through Qt signals."""
import threading
import uuid
from pathlib import Path
from PyQt6 import QtCore, QtWidgets
from .bridge import ProjectBridge
from .files import GuideError, ProjectFiles
from .runner import CodexRunner
from .session import GuideSession
from .ui import ProjectGuidePanel
from .context import publish


class ProjectGuideController(QtCore.QObject):
    finished = QtCore.pyqtSignal(str, object, object, object)
    progress = QtCore.pyqtSignal(str, str)
    context_changed = QtCore.pyqtSignal()

    def __init__(self, owner):
        super().__init__(owner)
        self.bridge = ProjectBridge()
        self.panel = ProjectGuidePanel(owner)
        self.panel.action.connect(self.handle)
        self.finished.connect(self.complete)
        self.progress.connect(self.show_progress)
        self.session = None
        self.root = self.window = None
        self.runner = None
        self.generation = ''
        self.busy = False
        self.last_action = 'analyze'
        self.page = 0
        self.summary_pending = False

    def show(self):
        self.panel.show()
        self.panel.raise_()
        if self.busy:
            return
        if not self.bridge.server:
            try:
                self.bridge.start()
            except OSError as exc:
                self.error('Could not start the local VS Code connection: ' + str(exc))
                return
        if self.session and self.session.result:
            self.render_result()
        else:
            self.projects()

    def handle(self, action, value=None):
        if self.busy and action != 'cancel':
            return
        try:
            if action == 'cancel':
                self.cancel()
                self.error('Cancelled. Click Retry to continue.')
            elif action == 'projects':
                self.cancel()
                self.projects()
            elif action == 'select_project':
                self.cancel()
                self.window, self.root = value
                self.session = None
                self.publish_context()
                self.page = 0
                self.files()
            elif action == 'files':
                self.cancel()
                self.page = 0
                self.files()
            elif action == 'page':
                self.page = value
                self.files()
            elif action == 'preview':
                self.preview(value)
            elif action == 'select_problem':
                self.session = GuideSession(self.root, value, self.window)
                self.publish_context()
                self.run('analyze')
            elif action == 'choice':
                self.session.choices.append({'question': self.session.result['question'], 'answer': value})
                self.publish_context()
                self.run('analyze')
            elif action in ('analyze', 'review', 'final'):
                self.run(action)
            elif action == 'retry':
                if self.session:
                    self.run(self.last_action)
                else:
                    self.show()
            elif action in ('start', 'next', 'previous'):
                if self.session:
                    self.summary_pending = False
                    self.session.move({'start': 0, 'next': 1, 'previous': -1}[action])
                    self.publish_context()
                    self.panel.show_step(self.session)
            elif action == 'explain' and self.session and self.session.step:
                self.panel.present(self.session.step['explanation'], [('Back to step', 'start', None),
                    ('More detail', 'detail', None)])
            elif action == 'detail':
                self.run('explain')
            elif action in ('open', 'copy') and self.session and self.session.step:
                self.perform_step_action(action)
            else:
                return
        except (GuideError, OSError, ValueError) as exc:
            self.error(str(exc))

    def projects(self):
        options = []
        for window in self.bridge.windows():
            for root in window['roots']:
                label = ('Recommended · ' if not options else '') + root
                options.append((label, 'select_project', (window['window'], root)))
        self.panel.banner.setText('Local Windows projects · suggestions only')
        self.panel.present('Select a VS Code workspace folder.' if options else
            'No connected workspace. Install the AI-Live Project Guide VSIX, open a trusted local folder '
            'in VS Code, then click Refresh. Remote and untrusted workspaces are not supported.',
            [('Refresh', 'projects', None)], options, selection=True)

    def files(self):
        if not self.root:
            self.projects()
            return
        state = self.bridge.state(self.window, self.root)
        files = ProjectFiles(self.root)
        paths = list(files.paths())
        preferred = None
        if state['active']:
            try:
                active = Path(state['active']).resolve().relative_to(files.root).as_posix()
                if active in paths and Path(active).suffix.lower() in ('', '.md', '.txt', '.text', '.rst', '.markdown'):
                    preferred = active
            except (ValueError, OSError):
                pass
        paths.sort(key=lambda p: (p != preferred, Path(p).name.lower() not in ('readme.md', 'readme.txt'), p.lower()))
        start = self.page * 25
        options = [(('Recommended · ' if p == preferred else '') + p, 'preview', p) for p in paths[start:start + 25]]
        actions = [('Change project', 'projects', None)]
        if start:
            actions.append(('Previous page', 'page', self.page - 1))
        if start + 25 < len(paths):
            actions.append(('Next page', 'page', self.page + 1))
        self.panel.banner.setText(str(self.root))
        self.panel.present('Choose the saved text file containing the problem statement. Select a file to preview it.\n'
                           'Private configuration, dependencies, and build output are excluded.', actions, options, selection=True)

    def preview(self, relative):
        text = ProjectFiles(self.root).read(relative)
        self.panel.present(relative + '\n\n' + text,
                           [('Use this file', 'select_problem', relative), ('Choose another', 'files', None)])

    def editor_state(self, *, window=None, root=None):
        root = Path(root or self.root).resolve()
        window = window or self.window
        state = self.bridge.state(window, root)
        dirty, diagnostics = [], []
        for path in state['dirty']:
            try:
                dirty.append(Path(path).resolve().relative_to(root).as_posix())
            except (ValueError, OSError):
                pass
        for item in state['diagnostics']:
            if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                continue
            try:
                relative = Path(item['path']).resolve().relative_to(root).as_posix()
                diagnostics.append(dict(item, path=relative))
            except (ValueError, OSError):
                pass
        return dirty, diagnostics

    def perform_step_action(self, action):
        step = self.session.step
        if action == 'copy':
            QtWidgets.QApplication.clipboard().setText(step['code'])
            self.panel.banner.setText('Code copied. Paste it yourself in VS Code.')
        else:
            self.bridge.open_location(self.window, self.root, step['path'], step['line'])
        self.panel.show_step(self.session)

    def run(self, action):
        if not self.session or self.busy:
            return
        self.last_action = action
        self.generation = uuid.uuid4().hex
        generation, session = self.generation, self.session
        self.runner = runner = CodexRunner()
        self.busy = True
        self.panel.banner.setText(str(self.root) + ' · ' + session.problem)
        self.panel.present('Preparing saved project files…', [('Cancel', 'cancel', None)])

        def worker():
            try:
                request = session.begin()
                try:
                    _, diagnostics = self.editor_state(window=session.window, root=session.files.root)
                except (GuideError, OSError):
                    diagnostics = []
                context = {'action': action, 'problem_file': session.problem, 'choices': list(session.choices),
                           'previous_guidance': session.result, 'current_step': session.step,
                           'editor_diagnostics': diagnostics}
                data = runner.run(session.files.root, context, lambda status: self.progress.emit(generation, status))
                self.finished.emit(generation, request, data, None)
            except Exception as exc:
                self.finished.emit(generation, None, None, str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def show_progress(self, generation, text):
        if generation == self.generation and self.busy:
            self.panel.answer_text.setPlainText(text)

    def complete(self, generation, request_data, data, error):
        if generation != self.generation:
            return
        self.busy = False
        if error:
            self.error(error)
            return
        try:
            if not self.session.accept(request_data, data):
                return
            self.summary_pending = self.last_action == 'analyze'
            self.publish_context()
            self.panel.banner.setText(str(self.root) + ' · ' + self.session.problem)
            self.render_result()
        except (GuideError, OSError) as exc:
            self.error(str(exc))

    def render_result(self):
        data = self.session.result
        if data['blocked']:
            self.panel.present(data['blocked'], [('Change problem', 'files', None), ('Retry', 'retry', None)])
        elif data['question']:
            self.panel.present(data['summary'] + '\n\n' + data['question'],
                               [('Change problem', 'files', None)],
                               [(choice, 'choice', choice) for choice in data['choices']])
        elif self.summary_pending:
            self.panel.present(data['summary'], [('Start guidance', 'start', None), ('Change problem', 'files', None)])
        else:
            self.panel.show_step(self.session)

    def error(self, message):
        actions = [('Retry', 'retry', None), ('Change project', 'projects', None)]
        if self.root:
            actions.insert(1, ('Change problem', 'files', None))
        if self.session and self.session.result:
            actions.insert(1, ('Check my changes', 'review', None))
        self.panel.present(message, actions)

    def cancel(self):
        self.generation = uuid.uuid4().hex
        self.busy = False
        if self.session:
            self.session.cancel()
        if self.runner:
            runner = self.runner
            runner.cancelled.set()
            threading.Thread(target=runner.cancel, daemon=True).start()

    def clear(self):
        self.cancel()
        self.session = None
        self.publish_context()
        self.root = self.window = None
        self.panel.hide()

    def publish_context(self):
        if publish(self.session):
            self.context_changed.emit()

    def close(self):
        self.clear()
        self.bridge.close()
