"""Coordinates pinned workspace sessions and worker results through Qt signals."""
import threading
import copy
import uuid
from pathlib import Path
from PyQt6 import QtCore, QtWidgets
from .bridge import ProjectBridge
from .files import GuideError, ProjectFiles
from .runner import CodexRunner
from .codex_sessions import SessionReader, read_session_output
from .session import GuideSession, PromptSession
from .conversation import project_update_store as conversation
from .ui import ProjectGuidePanel
from .context import publish
from .alignment_tracker import EditorAlignmentTracker


class ProjectGuideController(QtCore.QObject):
    sessions_loaded = QtCore.pyqtSignal(str, object, object)
    finished = QtCore.pyqtSignal(str, object, object, object)
    progress = QtCore.pyqtSignal(str, str)
    context_changed = QtCore.pyqtSignal()

    def __init__(self, owner):
        super().__init__(owner)
        self.bridge = ProjectBridge()
        self.panel = ProjectGuidePanel(owner)
        self.panel.action.connect(self.handle)
        self.finished.connect(self.complete)
        self.sessions_loaded.connect(self.show_sessions)
        self.session_options = {}
        self.progress.connect(self.show_progress)
        self.session = None
        self.root = self.window = None
        self.runner = None
        self.generation = ''
        self.busy = False
        self.last_action = 'analyze'
        self.last_navigation = None
        self.page = 0
        self.summary_pending = False
        self.mode_pending = False
        self.alignment = EditorAlignmentTracker(self.panel, self.alignment_state)

    def alignment_state(self):
        state = self.bridge.state(self.window, self.root)
        return self.root, state['active'], state.get('workspace_name')

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
        if self.session and self.mode_pending:
            self.choose_mode()
        elif isinstance(self.session, PromptSession) and not self.session.result:
            try:
                self.run('analyze')
            except (GuideError, OSError) as exc:
                self.error(str(exc))
        elif self.session and self.session.result:
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
                self.session = None
                conversation.clear()
                self.publish_context()
                self.projects()
            elif action == 'select_project':
                self.cancel()
                self.window, self.root = value
                self.session = None
                conversation.clear()
                self.publish_context()
                self.page = 0
                self.files()
            elif action == 'files':
                self.cancel()
                self.session = None
                conversation.clear()
                self.publish_context()
                self.page = 0
                self.files()
            elif action == 'page':
                self.page = value
                self.files()
            elif action == 'preview':
                self.preview(value)
            elif action == 'select_problem':
                self.session = GuideSession(self.root, value, self.window)
                conversation.clear()
                self.mode_pending = True
                self.publish_context()
                self.choose_mode()
            elif action == 'select_mode':
                self.mode_pending = False
                if value == 'prompt':
                    self.session = PromptSession(self.root, self.session.problem, self.window)
                    conversation.activate(self.session.id)
                    self.publish_context()
                    self.run('analyze')
                else:
                    conversation.activate(self.session.id)
                    self.run('analyze')
            elif action == 'check_output' and isinstance(self.session, PromptSession):
                if self.session.codex_session_id:
                    self.run('check_output')
                else:
                    self.choose_session()
            elif action == 'sessions' and isinstance(self.session, PromptSession):
                self.choose_session()
            elif action == 'select_session' and isinstance(self.session, PromptSession):
                selected = self.session_options.get(value)
                if not selected:
                    raise GuideError('Refresh the session list and choose again.')
                self.session.codex_session_id = selected['id']
                self.session.codex_session_name = selected.get('name') or selected.get('preview', '')[:80] or selected['id']
                self.session.last_terminal_output = None
                self.run('check_output')
            elif action == 'check_program' and isinstance(self.session, PromptSession):
                terminals = self.bridge.terminals(self.window, self.root)
                self.program_terminals = {t['id']: t for t in terminals}
                self.panel.present('Choose the terminal containing the program result to review.',
                    [(t['name'] + ' - ' + t['command'][:70], 'select_program_terminal', t['id']) for t in terminals]
                    + [('Refresh', 'check_program', None), ('Back to prompt', 'start', None)])
            elif action == 'select_program_terminal' and isinstance(self.session, PromptSession):
                selected = self.program_terminals.get(value)
                if not selected:
                    raise GuideError('Refresh the terminal list and choose again.')
                self.session.terminal_id = selected['id']
                self.session.terminal_name = selected['name']
                self.run('check_program')
            elif action == 'copy_prompt' and isinstance(self.session, PromptSession):
                if self.session.current:
                    QtWidgets.QApplication.clipboard().setText(self.session.current['prompt'])
                    self.panel.banner.setText('Prompt copied. Paste and submit it in your Codex terminal.')
            elif action == 'approach' and isinstance(self.session, PromptSession):
                self.show_approach()
            elif action == 'choice':
                self.session.choices.append({'question': self.session.result['question'], 'answer': value})
                self.publish_context()
                self.run('clarify' if isinstance(self.session, PromptSession) else 'analyze')
            elif action in ('analyze', 'review', 'final', 'terminal', 'check_output', 'adapt'):
                self.run(action)
            elif action == 'retry':
                if self.session and self.mode_pending:
                    self.choose_mode()
                elif isinstance(self.session, PromptSession) and self.last_action == 'sessions':
                    self.choose_session()
                elif self.session:
                    self.run(self.last_action, navigation=self.last_navigation)
                else:
                    self.show()
            elif action in ('start', 'next', 'previous'):
                if self.session:
                    if (not isinstance(self.session, PromptSession) and action in ('start', 'next')
                            and conversation.snapshot(self.session.id)['revision'] > self.session.conversation_revision):
                        self.run('adapt', navigation=action)
                        return
                    self.summary_pending = False
                    self.session.move({'start': 0, 'next': 1, 'previous': -1}[action])
                    self.publish_context()
                    if isinstance(self.session, PromptSession):
                        self.alignment.stop()
                        self.panel.show_prompt(self.session)
                    else:
                        self.panel.show_step(self.session)
                        self.alignment.start()
            elif action == 'fit_editor':
                self.alignment.start()
            elif action in ('scroll_up', 'scroll_down'):
                self.panel.scroll_guidance(-1 if action == 'scroll_up' else 1)
            elif action == 'close_guide':
                self.panel.close()
            elif action == 'explain' and self.session and self.session.step:
                self.panel.present(self.session.step['explanation'], [('Back to step', 'start', None),
                    ('More detail', 'detail', None)])
            elif action == 'detail':
                self.run('explain')
            elif action in ('open', 'copy', 'copy_diff') and self.session and self.session.step:
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

    def choose_mode(self):
        self.panel.present('Choose how to work on ' + self.session.problem + '.',
                           [('Code Guide', 'select_mode', 'code'), ('Prompt Guide', 'select_mode', 'prompt'),
                            ('Change problem', 'files', None)])

    def choose_session(self):
        self.cancel()
        self.busy = True
        self.last_action = 'sessions'
        self.runner = runner = CodexRunner()
        generation = self.generation
        root = self.session.files.root
        self.panel.present('Loading saved Codex CLI sessions...', [('Cancel', 'cancel', None)])
        def worker():
            try:
                with SessionReader(runner.cancelled) as reader:
                    sessions = reader.list_sessions(root)
                self.sessions_loaded.emit(generation, sessions, None)
            except Exception as exc:
                self.sessions_loaded.emit(generation, None, str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def show_sessions(self, generation, sessions, error):
        if generation != self.generation:
            return
        self.busy = False
        if error:
            self.panel.present(error, [('Retry', 'sessions', None), ('Back to prompt', 'start', None)])
            return
        self.session_options = {s['id']: s for s in sessions}
        self.panel.present('Choose a Codex session for this guide. This choice is remembered. Most recent first.',
            [((s.get('name') or s.get('preview', '')[:100] or 'Codex') + ' - ' + s['id'][-8:],
              'select_session', s['id']) for s in sessions]
            + [('Refresh', 'sessions', None), ('Back to prompt', 'start', None)])

    def show_approach(self):
        self.panel.present('Full approach\n\n' + self.session.result['approach'], [('Show prompt', 'start', None),
                           ('Change problem', 'files', None)])

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
        elif action == 'copy_diff':
            QtWidgets.QApplication.clipboard().setText(step['diff'])
            self.panel.banner.setText('Diff copied.')
        else:
            self.bridge.open_location(self.window, self.root, step['path'], step['line'])
        self.panel.show_step(self.session)
        self.alignment.start()

    def run(self, action, navigation=None):
        if not self.session or self.busy:
            return
        self.last_action = action
        self.last_navigation = navigation
        self.generation = uuid.uuid4().hex
        generation, session = self.generation, self.session
        self.runner = runner = CodexRunner()
        request = session.begin(action)
        # Late audio updates belong to the following request.
        audio_context = conversation.snapshot(session.id)
        context = copy.deepcopy({'action': action, 'problem_file': session.problem,
                                 'choices': session.choices, 'previous_guidance': session.result,
                                 'current_step': session.step, 'mode': session.mode,
                                 'accepted_requirements': session.accepted_requirements,
                                 'conversation': audio_context,
                                 'consumed_conversation_revision': session.conversation_revision})
        selected_session_id = getattr(session, 'codex_session_id', None)
        selected_terminal_id = getattr(session, 'terminal_id', None)
        if isinstance(session, PromptSession):
            context.update(mode='prompt', current_prompt=session.history[-1]['prompt'] if session.history else '',
                           accepted_requirements=session.accepted_requirements,
                           conversation=audio_context, consumed_conversation_revision=session.conversation_revision)
            if action == 'clarify' and session.last_terminal_output is not None:
                context['terminal_output'] = copy.deepcopy(session.last_terminal_output)
        self.busy = True
        self.panel.banner.setText(str(self.root) + ' · ' + session.problem)
        self.panel.present('Preparing saved project files…', [('Cancel', 'cancel', None)])

        def worker():
            try:
                try:
                    _, diagnostics = self.editor_state(window=session.window, root=session.files.root)
                except (GuideError, OSError):
                    diagnostics = []
                context['editor_diagnostics'] = diagnostics
                if isinstance(session, PromptSession):
                    if action == 'check_output':
                        terminal = read_session_output(session.files.root, selected_session_id, context['current_prompt'], runner.cancelled)
                        session.check_terminal(terminal)
                        context['terminal_output'] = terminal
                    elif action == 'check_program':
                        terminal = self.bridge.terminal_output(session.window, session.files.root, selected_terminal_id)
                        session.check_terminal(terminal)
                        context['terminal_output'] = terminal
                        context['action'] = 'check_output'
                if action == 'terminal':
                    context['terminal_output'] = self.bridge.terminal_output(session.window, session.files.root)
                data = runner.run(session.files.root, context, lambda status: self.progress.emit(generation, status))
                envelope = {'request': request, 'terminal': context.get('terminal_output'),
                            'conversation_revision': audio_context['revision'], 'navigation': navigation}
                self.finished.emit(generation, envelope, data, None)
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
            navigation = None
            if isinstance(request_data, dict):
                if request_data['request'] != self.session.request:
                    return
                terminal = request_data['terminal']
                if terminal is not None and isinstance(self.session, PromptSession):
                    self.session.prepare_check(terminal)
                    self.session.last_terminal_output = copy.deepcopy(terminal)
                    if terminal.get('source') == 'codex_session':
                        self.session.codex_session_id = terminal['id']
                        self.session.codex_session_name = terminal['name']
                self.session.pending_conversation_revision = request_data['conversation_revision']
                navigation = request_data.get('navigation')
                request_data = request_data['request']
            first_prompt = isinstance(self.session, PromptSession) and not self.session.history
            next_step_id = None
            if navigation == 'next' and self.session.step:
                steps = self.session.result['steps']
                next_step_id = steps[min(self.session.index + 1, len(steps) - 1)]['id']
            if not self.session.accept(request_data, data):
                return
            self.summary_pending = (first_prompt if isinstance(self.session, PromptSession)
                                    else self.last_action == 'analyze' or
                                    (self.last_action == 'adapt' and navigation != 'next'
                                     and bool(data['conversation_change'].strip())))
            if (not isinstance(self.session, PromptSession) and self.last_action == 'adapt'
                    and not data['question'] and not data['blocked'] and navigation == 'next'):
                # Follow the requested destination even if Codex revised/reordered the steps.
                # If it was removed, keep the surviving current step (or first remaining step).
                self.session.index = next((i for i, step in enumerate(self.session.result['steps'])
                                           if step['id'] == next_step_id), self.session.index)
            self.publish_context()
            self.panel.banner.setText(str(self.root) + ' · ' + self.session.problem)
            self.render_result()
        except (GuideError, OSError) as exc:
            self.error(str(exc))

    def render_result(self):
        data = self.session.result
        if isinstance(self.session, PromptSession):
            self.alignment.stop()
            if data['blocked']:
                self.panel.present(data['blocked'], [('Back to prompt', 'start', None),
                    ('Change problem', 'files', None), ('Retry', 'retry', None)])
            elif data['status'] == 'clarification':
                self.panel.present(data['question'], [('Change problem', 'files', None)],
                                   [(choice, 'choice', choice) for choice in data['choices']])
            elif self.summary_pending and data['status'] == 'ready':
                self.show_approach()
            else:
                self.panel.show_prompt(self.session)
            return
        if data['blocked']:
            self.panel.present(data['blocked'], [('Change problem', 'files', None), ('Retry', 'retry', None)])
        elif data['question']:
            self.panel.present(data['summary'] + '\n\n' + data['question'],
                               [('Change problem', 'files', None)],
                               [(choice, 'choice', choice) for choice in data['choices']])
        elif self.summary_pending:
            self.panel.present('Full approach\n\n' + data['summary'],
                               [('Next', 'start', None), ('Change problem', 'files', None)])
        else:
            self.panel.show_step(self.session)
            self.alignment.start()

    def error(self, message):
        actions = [('Retry', 'retry', None), ('Change project', 'projects', None)]
        if self.root:
            actions.insert(1, ('Change problem', 'files', None))
        if self.session and self.session.result:
            if not isinstance(self.session, PromptSession):
                actions.insert(1, ('Check my changes', 'review', None))
            actions.insert(1, ('Back to guide', 'start', None))
        self.panel.present(message, actions)

    def cancel(self):
        self.alignment.stop()
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
        self.mode_pending = False
        conversation.clear()
        self.publish_context()
        self.root = self.window = None
        self.panel.hide()

    def publish_context(self):
        if publish(self.session):
            self.context_changed.emit()

    def close(self):
        self.clear()
        self.bridge.close()
