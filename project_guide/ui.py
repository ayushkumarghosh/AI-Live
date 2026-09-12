"""Guide presentation: selectable actions only, no editable prompt surface."""
from PyQt6 import QtCore, QtGui, QtWidgets
from overlay import CodeAnswerOverlay, render_basic_answer_html
from .diff import render_guide_diff


class ProjectGuidePanel(CodeAnswerOverlay):
    action = QtCore.pyqtSignal(str, object)

    def __init__(self, owner=None):
        super().__init__(owner)
        self._adjusting_line_spacing = False
        self._editor_fit = None
        self._normal_geometry = None
        self._guidance_html = None
        self._normal_guidance_html = None
        self._using_grid = False
        self._snapping_scroll = False
        self._normal_text_style = self.answer_text.styleSheet()
        self._fitted_input = None
        self.answer_text.textChanged.connect(self._apply_line_spacing)
        self.answer_text.verticalScrollBar().valueChanged.connect(self._snap_scroll)
        self.title_label.setText('Project Guide · read only')
        self.close_button.setToolTip('Close Project Guide')
        self.resize(780, 620)
        self.banner = QtWidgets.QLabel()
        self.banner.setWordWrap(True)
        self.banner.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
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

    def accepts_fitted_input(self, point):
        if self._editor_fit is None:
            return True
        return any(button.isVisible() and button.isEnabled() and
                   QtCore.QRect(button.mapTo(self, QtCore.QPoint()), button.size()).contains(point)
                   for button in self.findChildren(QtWidgets.QAbstractButton))

    def fitted_native_hit_test(self, point, rect):
        # Native hook coordinates are physical pixels, Qt geometry is logical.
        return self.accepts_fitted_input(QtCore.QPoint(
            round((point.x - rect.left) * self.width() / max(1, rect.right - rect.left)),
            round((point.y - rect.top) * self.height() / max(1, rect.bottom - rect.top))))

    def _set_fitted_input(self, enabled):
        app = QtWidgets.QApplication.instance()
        if app.platformName() != 'windows':
            return
        from overlay_cursor import OverlayCursorMode, install_cursor_mirroring
        self.setProperty('fitted_input_routing', enabled)
        shared = install_cursor_mirroring(app)
        if enabled:
            shared.refresh()  # Relinquish this HWND before the dedicated router owns it.
            if self._fitted_input is None:
                self._fitted_input = OverlayCursorMode(app, windows_provider=lambda: [self])
                self._fitted_input.setParent(self)
            self._fitted_input.set_enabled(True)
            if not self._fitted_input.enabled:
                self.setProperty('fitted_input_routing', False)
        elif self._fitted_input:
            self._fitted_input.set_enabled(False)
            shared.refresh()

    def hideEvent(self, event):
        self._set_fitted_input(False)
        super().hideEvent(event)

    def _fit_controls(self, fitted, width=780):
        columns = 3 if fitted and width < 640 else 4
        controls = []
        while self.buttons.count():
            controls.append(self.buttons.takeAt(0).widget())
        self.buttons.setSpacing(4 if fitted else 6)
        for i, button in enumerate(controls):
            style = button.property('normal_style')
            button.setStyleSheet(style.replace('padding:8px;', 'padding:4px;font-family:Segoe UI;font-size:11px;') if fitted else style)
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored if fitted else
                                 QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Fixed)
            self.buttons.addWidget(button, i // columns, i % columns)
        self.banner.setWordWrap(not fitted)
        self.banner.setStyleSheet('color:#edbd70;padding:4px;font-family:Segoe UI;font-size:11px;' if fitted
                                 else 'color:#edbd70;padding:8px;')
        self.banner.setMinimumHeight(24 if fitted else 0)
        self.banner.setMaximumHeight(24 if fitted else 16777215)
        self.banner.setToolTip(self.banner.text() if fitted else '')

    def _apply_line_spacing(self):
        """Match the workspace editor's 24px rows without clipping headings."""
        if self._adjusting_line_spacing:
            return
        self._adjusting_line_spacing = True
        try:
            cursor = QtGui.QTextCursor(self.answer_text.document())
            cursor.select(QtGui.QTextCursor.SelectionType.Document)
            block = QtGui.QTextBlockFormat()
            pitch = self._editor_fit[2] if self._editor_fit else 24
            kind = (QtGui.QTextBlockFormat.LineHeightTypes.FixedHeight if self._editor_fit else
                    QtGui.QTextBlockFormat.LineHeightTypes.MinimumHeight)
            block.setLineHeight(pitch, kind.value)
            if self._editor_fit:
                block.setTopMargin(0)
                block.setBottomMargin(0)
                font = QtGui.QFont('Consolas')
                font.setPixelSize(12)
                fmt = QtGui.QTextCharFormat()
                fmt.setFont(font)
                cursor.mergeCharFormat(fmt)
            cursor.mergeBlockFormat(block)
            if self._editor_fit:
                frame = self.answer_text.document().rootFrame()
                fmt = frame.frameFormat()
                fmt.setMargin(0)
                fmt.setPadding(0)
                fmt.setBorder(0)
                frame.setFrameFormat(fmt)
        finally:
            self._adjusting_line_spacing = False

    def _snap_scroll(self, value):
        if not self._editor_fit or self._snapping_scroll:
            return
        self._snapping_scroll = True
        try:
            pitch = self._editor_fit[2]
            bar = self.answer_text.verticalScrollBar()
            maximum = (bar.maximum() // pitch) * pitch
            bar.setValue(min(maximum, round(value / pitch) * pitch))
            bar.setSingleStep(pitch)
        finally:
            self._snapping_scroll = False

    def fit_editor(self, rect, row_center, pitch=24):
        """Place the text's ink midway between measured editor text rows."""
        if rect.width() < 420 or rect.height() < 280:
            return
        if self._normal_geometry is None:
            self._normal_geometry = self.geometry()
        self._editor_fit = (QtCore.QRect(rect), row_center, pitch)
        if self._guidance_html and not self._using_grid:
            self._using_grid = True
            self.answer_text.setHtml(self._guidance_html)
        self.panel.setStyleSheet('QFrame#CodeAnswerPanel { background:transparent; border:0; border-radius:0; }')
        self.title_bar.hide()
        self.panel.layout().removeWidget(self.banner)
        self.panel.layout().insertWidget(self.panel.layout().indexOf(self.actions), self.banner)
        self.banner.setVisible(bool(self.banner.text()))
        for handle in self.handles:
            handle.hide()
        self.answer_text.setStyleSheet(self._normal_text_style + '\nQTextEdit { padding:0px; }')
        self._fit_controls(True, rect.width())
        # Refresh native minimum-size constraints before asking Windows to resize.
        self.panel.layout().activate()
        self.layout().activate()
        self.setGeometry(rect)
        self.panel.layout().activate()
        self._apply_line_spacing()
        doc = self.answer_text.document()
        # QTextDocument's top margin affects its first baseline, independently of
        # the widget frame. Measure that baseline instead of guessing a padding.
        doc.documentLayout().documentSize()
        first = doc.begin().layout()
        if first.lineCount():
            line = first.lineAt(0)
            font = QtGui.QFont('Consolas')
            font.setPixelSize(12)
            ink_center = QtGui.QFontMetricsF(font).tightBoundingRect('0123456789').center().y()
            desired = row_center + pitch / 2 - ink_center
            baseline = (self.answer_text.viewport().mapToGlobal(QtCore.QPoint()).y()
                        + first.position().y() + line.y() + line.ascent())
            margin = (desired - baseline) % pitch
            fmt = doc.rootFrame().frameFormat()
            fmt.setTopMargin(margin)
            # Leave enough trailing space for a full-row final scroll position.
            fmt.setBottomMargin(pitch)
            self._adjusting_line_spacing = True
            try:
                doc.rootFrame().setFrameFormat(fmt)
            finally:
                self._adjusting_line_spacing = False
        self._snap_scroll(self.answer_text.verticalScrollBar().value())
        self._set_fitted_input(True)

    def release_editor(self):
        if self._editor_fit is None:
            return
        self._editor_fit = None
        self._set_fitted_input(False)
        self._using_grid = False
        self.panel.setStyleSheet('')
        self.title_bar.show()
        self.panel.layout().removeWidget(self.banner)
        self.panel.layout().insertWidget(1, self.banner)
        self.banner.show()
        self._fit_controls(False)
        for handle in self.handles:
            handle.setVisible(self.show_resize_handles)
        self.answer_text.setStyleSheet(self._normal_text_style)
        self.answer_text.document().setDocumentMargin(4)
        if self._normal_geometry is not None:
            self.panel.layout().activate()
            self.layout().activate()
            restored = QtCore.QRect(self._normal_geometry)
            restored.setSize(restored.size().expandedTo(self.minimumSizeHint()).expandedTo(self.minimumSize()))
            self.setGeometry(restored)
        self._normal_geometry = None
        if self._normal_guidance_html:
            self.answer_text.setHtml(self._normal_guidance_html)

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
        button.setProperty('normal_style', button.styleSheet())
        button.clicked.connect(lambda _checked=False: self.action.emit(action, value))
        return button

    def present(self, text, actions, options=(), *, selection=False, guidance=False):
        if not guidance:
            self.release_editor()
            self._guidance_html = None
            self._normal_guidance_html = None
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
        grid_content = content
        if step:
            content += render_guide_diff(step['diff'], step['path'])
            content += render_basic_answer_html('\n' + step['explanation'] + '\n\n')
            grid_content += render_guide_diff(step['diff'], step['path'], grid=True)
            grid_content += render_basic_answer_html('\n' + step['explanation'] + '\n\n')
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
                        ('Copy diff', 'copy_diff', None),
                        ('Open location', 'open', None)]
        actions += [('Check my changes', 'review', None), ('Final review', 'final', None),
                    ('Change problem', 'files', None), ('Change project', 'projects', None)]
        actions += [('Fit editor', 'fit_editor', None), ('Close guide', 'close_guide', None)]
        self.present(text, actions, guidance=True)
        self._guidance_html = grid_content + render_basic_answer_html(text)
        self._normal_guidance_html = content + render_basic_answer_html(text)
        self._using_grid = bool(self._editor_fit)
        self.answer_text.setHtml(self._guidance_html if self._using_grid else content + render_basic_answer_html(text))
        if self._editor_fit:
            self.fit_editor(*self._editor_fit)

    def closeEvent(self, event):
        self.action.emit('cancel', None)
        super().closeEvent(event)
