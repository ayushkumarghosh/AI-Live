"""Guide presentation: selectable actions only, no editable prompt surface."""
from PyQt6 import QtCore, QtWidgets
from overlay import CodeAnswerOverlay, render_basic_answer_html
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_for_filename, TextLexer
from pygments.util import ClassNotFound


def render_guide_code(code, path):
    """Match the main overlay's Monokai code cards without parsing code as Markdown."""
    try:
        lexer = get_lexer_for_filename(path, stripnl=False, ensurenl=False)
    except ClassNotFound:
        lexer = TextLexer(stripnl=False, ensurenl=False)
    content = highlight(code, lexer, HtmlFormatter(noclasses=True, style='monokai', nowrap=True))
    return (
        '<table width="100%" cellspacing="0" cellpadding="0"><tr><td '
        'style="background-color:#111922;border:1px solid #2F3B48;padding:6px 10px;">'
        '<pre style="margin:0;font-family:Consolas, Cascadia Mono, monospace;'
        'font-size:14px;color:#E8EEF5;">' + content + '</pre></td></tr></table>')


class ProjectGuidePanel(CodeAnswerOverlay):
    action = QtCore.pyqtSignal(str, object)

    def __init__(self, owner=None):
        super().__init__(owner)
        self.title_label.setText('Project Guide · read only')
        self.close_button.setToolTip('Close Project Guide')
        self.resize(780, 620)
        self.banner = QtWidgets.QLabel()
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet('color: #edbd70; padding: 8px;')
        self.panel.layout().insertWidget(1, self.banner)
        self.actions = QtWidgets.QWidget()
        self.buttons = QtWidgets.QGridLayout(self.actions)
        self.panel.layout().addWidget(self.actions)
        self.options = QtWidgets.QScrollArea()
        self.options.setWidgetResizable(True)
        self.options.setMaximumHeight(200)
        self.option_body = QtWidgets.QWidget()
        self.option_layout = QtWidgets.QVBoxLayout(self.option_body)
        self.options.setWidget(self.option_body)
        self.panel.layout().insertWidget(2, self.options)
        self.options.hide()

    @staticmethod
    def clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def button(self, text, action, value=None):
        button = QtWidgets.QPushButton(text)
        button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        button.setStyleSheet('QPushButton {background:#253341;color:#e7edf3;padding:8px;border:1px solid #53606d;border-radius:4px;} QPushButton:hover {background:#354b60;}')
        button.clicked.connect(lambda _checked=False: self.action.emit(action, value))
        return button

    def present(self, text, actions, options=(), *, selection=False):
        self.answer_text.setPlainText(text)
        self.answer_text.setMaximumHeight(80 if selection and options else 16777215)
        self.options.setMaximumHeight(16777215 if selection else 200)
        self.panel.layout().setStretchFactor(self.answer_text, 0 if selection and options else 1)
        self.panel.layout().setStretchFactor(self.options, 1 if selection and options else 0)
        self.clear_layout(self.buttons)
        self.clear_layout(self.option_layout)
        for i, (label, action, value) in enumerate(actions):
            self.buttons.addWidget(self.button(label, action, value), i // 4, i % 4)
        for label, action, value in options:
            self.option_layout.addWidget(self.button(label, action, value))
        self.options.setVisible(bool(options))
        self.options.verticalScrollBar().setValue(0)

    def show_step(self, session):
        data, step = session.result, session.step
        text = data['summary'] + '\n\n'
        if step:
            text += (f'Step {session.index + 1} of {len(data["steps"])} — {step["operation"].upper()}\n'
                     f'{step["path"]} · line {step["line"]}\n'
                     f'Location: {step["anchor"] or "New file — create it manually"}\n\n'
                     )
        content = render_basic_answer_html(text)
        if step:
            content += render_guide_code(step['code'], step['path'])
            content += render_basic_answer_html('\n' + step['explanation'] + '\n\n')
        text = ''
        if data['verdict'] != 'not_reviewed':
            text += data['verdict'].replace('_', ' ').capitalize() + '\n' + data['findings'] + '\n\n'
        text += 'Code review only. Tests have not been run.\n'
        if data['test_commands']:
            text += 'Suggested commands to run yourself:\n' + '\n'.join(data['test_commands'])
        actions = []
        if step:
            if session.index > 0:
                actions.append(('Previous', 'previous', None))
            if session.index < len(data['steps']) - 1:
                actions.append(('Next', 'next', None))
            actions += [('Explain', 'explain', None), ('Copy code', 'copy', None),
                        ('Open location', 'open', None)]
        actions += [('Check my changes', 'review', None), ('Final review', 'final', None),
                    ('Change problem', 'files', None), ('Change project', 'projects', None)]
        self.present(text, actions)
        self.answer_text.setHtml(content + render_basic_answer_html(text))

    def closeEvent(self, event):
        self.action.emit('cancel', None)
        super().closeEvent(event)
