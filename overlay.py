import sys, ctypes, json
import html
from PyQt6 import QtWidgets, QtCore, QtGui, QtSvg
from PyQt6.QtCore import pyqtSignal as Signal, pyqtSlot as Slot
from datetime import datetime
import queue
import re
import platform
import os
from pathlib import Path


def configure_console_encoding():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


configure_console_encoding()

# Windows extended style constant for no activation.
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000


def apply_no_activate(hwnd):
    """Prevent a top-level overlay window from becoming the active foreground window."""
    current_ex_style = ctypes.windll.user32.GetWindowLongW(int(hwnd), GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(int(hwnd), GWL_EXSTYLE, current_ex_style | WS_EX_NOACTIVATE)

# Queue for screenshots
screenshot_queue = queue.Queue()

RESPONSIVE_BREAKPOINT = 900
MIN_OVERLAY_WIDTH = 520
MIN_OVERLAY_HEIGHT = 360

UI = {
    "window": "rgba(14, 19, 24, 205)",
    "chrome": "rgba(24, 30, 36, 220)",
    "panel": "rgba(19, 24, 29, 202)",
    "panel_alt": "rgba(28, 34, 41, 190)",
    "border": "rgba(118, 134, 150, 78)",
    "border_strong": "rgba(160, 177, 194, 110)",
    "text": "#F4F7FA",
    "muted": "#AAB5C2",
    "muted_dim": "#748190",
    "accent": "#77B7FF",
    "success": "#69D279",
    "warning": "#F6A53A",
    "danger": "#FF5F66",
    "code": "#8FD7FF",
    "button": "rgba(37, 45, 54, 175)",
    "button_hover": "rgba(52, 63, 74, 210)",
    "button_active": "rgba(65, 78, 90, 230)",
    "font": "Segoe UI",
}

TONE_COLORS = {
    "neutral": UI["muted"],
    "accent": UI["accent"],
    "success": UI["success"],
    "warning": UI["warning"],
    "danger": UI["danger"],
}


def _rgba(hex_color, alpha=255):
    color = QtGui.QColor(hex_color)
    color.setAlpha(alpha)
    return color


ICON_DIR = Path(__file__).resolve().parent / "assets" / "icons"


def _icon(kind, color=None, size=22):
    """Create crisp SVG-backed line icons from standalone SVG files."""
    color = color or UI["muted"]
    icon_path = ICON_DIR / f"{kind}.svg"
    if not icon_path.is_file():
        icon_path = ICON_DIR / "fallback.svg"
    svg = icon_path.read_text(encoding="utf-8").replace("currentColor", color)
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
    render_size = max(size * 4, 72)
    pixmap = QtGui.QPixmap(render_size, render_size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)

    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QtCore.QRectF(0, 0, render_size, render_size))
    painter.end()

    return QtGui.QIcon(pixmap)


def _tool_button_style(tone="neutral", active=False, compact=False):
    tone_color = TONE_COLORS.get(tone, UI["muted"])
    active_border = tone_color if active else UI["border"]
    active_bg = f"rgba({QtGui.QColor(tone_color).red()}, {QtGui.QColor(tone_color).green()}, {QtGui.QColor(tone_color).blue()}, 42)" if active else UI["button"]
    padding = "0px" if compact else "0px 11px"
    return f"""
        QToolButton {{
            background-color: {active_bg};
            color: {UI["text"]};
            border: 1px solid {active_border};
            border-radius: 7px;
            padding: {padding};
            font-family: {UI["font"]};
            font-size: 13px;
            font-weight: 600;
        }}
        QToolButton:hover {{
            background-color: {UI["button_hover"]};
            border-color: {UI["border_strong"]};
        }}
        QToolButton:pressed {{
            background-color: {UI["button_active"]};
            border-color: {tone_color};
        }}
        QToolButton:checked {{
            background-color: rgba({QtGui.QColor(tone_color).red()}, {QtGui.QColor(tone_color).green()}, {QtGui.QColor(tone_color).blue()}, 48);
            border-color: {tone_color};
        }}
        QToolButton:disabled {{
            color: {UI["muted_dim"]};
            border-color: rgba(100, 112, 124, 44);
            background-color: rgba(31, 37, 44, 120);
        }}
    """


def _command_button_style(tone="neutral", active=False):
    tone_color = TONE_COLORS.get(tone, UI["muted"])
    active_bg = f"rgba({QtGui.QColor(tone_color).red()}, {QtGui.QColor(tone_color).green()}, {QtGui.QColor(tone_color).blue()}, 34)" if active else "transparent"
    return f"""
        QToolButton {{
            background-color: {active_bg};
            color: {UI["text"]};
            border: none;
            border-radius: 6px;
            padding: 0px 10px;
            font-family: {UI["font"]};
            font-size: 14px;
            font-weight: 500;
        }}
        QToolButton:hover {{
            background-color: rgba(255, 255, 255, 18);
        }}
        QToolButton:pressed {{
            background-color: rgba(255, 255, 255, 28);
        }}
    """


def _text_edit_style():
    return f"""
        QTextEdit {{
            background-color: transparent;
            color: {UI["text"]};
            border: none;
            border-radius: 0px;
            font-family: {UI["font"]};
            font-size: 14px;
            padding: 10px;
            line-height: 1.45;
            selection-background-color: rgba(119, 183, 255, 95);
        }}
        QScrollBar:vertical {{
            border: none;
            background: rgba(38, 45, 52, 105);
            width: 9px;
            margin: 8px 0 8px 0;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(150, 164, 180, 120);
            min-height: 24px;
            border-radius: 4px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
    """


def _slider_style():
    return """
        QSlider::groove:horizontal {
            height: 4px;
            background: rgba(135, 150, 166, 90);
            margin: 0px;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #F4F7FA;
            width: 12px;
            margin: -4px 0;
            border-radius: 6px;
        }
        QSlider::sub-page:horizontal {
            background: rgba(119, 183, 255, 150);
            border-radius: 2px;
        }
    """


# ----------------------------------------------------------------
# Utility function: sets the window to be excluded from screen capture.
def set_exclude_from_capture(winId):
    hwnd = int(winId)
    WDA_EXCLUDEFROMCAPTURE = 0x11  # Requires Windows 10 build 2004+
    result = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    if not result:
        print("Warning: Failed to set window display affinity.")


def apply_private_no_focus_window(widget):
    """Apply the main overlay's capture and activation rules to a top-level widget."""
    widget.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    no_focus_flag = QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
    if not widget.windowFlags() & no_focus_flag:
        widget.setWindowFlag(no_focus_flag, True)
    widget.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    set_exclude_from_capture(widget.winId())
    apply_no_activate(widget.winId())


def show_private_text_context_menu(text_edit, event):
    menu = text_edit.createStandardContextMenu(event.pos())
    if menu is None:
        event.accept()
        return

    apply_private_no_focus_window(menu)

    def refresh_menu_window_settings():
        if menu:
            apply_private_no_focus_window(menu)

    def cleanup_menu():
        if getattr(text_edit, "_private_context_menu", None) is menu:
            text_edit._private_context_menu = None
        menu.deleteLater()

    text_edit._private_context_menu = menu
    menu.aboutToShow.connect(refresh_menu_window_settings)
    menu.aboutToHide.connect(cleanup_menu)
    menu.popup(event.globalPos())
    QtCore.QTimer.singleShot(0, refresh_menu_window_settings)
    event.accept()


# ----------------------------------------------------------------
# ResizeHandle: used for resizing the overlay.
class ResizeHandle(QtWidgets.QWidget):
    def __init__(self, parent, position):
        super().__init__(parent)
        self.position = position  # e.g., "top-left", "right", etc.
        self.parent = parent

        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(20, 20)

    def paintEvent(self, event):
        if self.parent.show_resize_handles:
            painter = QtGui.QPainter(self)
            painter.setPen(QtGui.QPen(QtGui.QColor(180, 180, 180, 120), 1))
            painter.setBrush(QtGui.QBrush(QtGui.QColor(120, 120, 120, 80)))
            if "corner" in self.position:
                painter.drawRect(0, 0, 10, 10)
            else:
                painter.drawRect(0, 0, 8, 8)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.parent.start_resize(self.position, event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self.parent.resizing:
            self.parent.do_resize(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.parent.end_resize()

# ----------------------------------------------------------------
# PromptTextEdit: text editor that preserves Enter-to-submit behavior.
class PromptTextEdit(QtWidgets.QPlainTextEdit):
    submit_requested = Signal()
    close_requested = Signal()

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            if modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.submit_requested.emit()
            event.accept()
            return
        if key == QtCore.Qt.Key.Key_Escape:
            self.close_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        show_private_text_context_menu(self, event)


class OverlayTextEdit(QtWidgets.QTextEdit):
    def contextMenuEvent(self, event):
        show_private_text_context_menu(self, event)


# InputOverlay: a separate focusable overlay for text input.
class InputOverlay(QtWidgets.QWidget):
    # Signal emitted when text is submitted.
    text_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # This top-level window must be activatable for Windows to deliver keyboard input.
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.WindowStaysOnTopHint |
            QtCore.Qt.WindowType.Tool
        )
        self.setObjectName("InputOverlay")
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        parent_width = parent.width() if parent else 560
        parent_height = parent.height() if parent else 520
        self.resize(
            max(420, min(720, int(parent_width * 0.62))),
            max(206, min(252, int(parent_height * 0.38))),
        )

        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.panel = QtWidgets.QFrame(self)
        self.panel.setObjectName("InputPanel")
        self.panel.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        root_layout.addWidget(self.panel)

        # Main layout with margins.
        main_layout = QtWidgets.QVBoxLayout(self.panel)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        self.setStyleSheet(f"""
            QFrame#InputPanel {{
                background-color: {UI["window"]};
                border: 1px solid {UI["border"]};
                border-radius: 12px;
            }}
            QLabel {{
                color: {UI["text"]};
                font-family: {UI["font"]};
            }}
            QPlainTextEdit {{
                background-color: rgba(12, 17, 22, 214);
                color: {UI["text"]};
                border: 1px solid {UI["border"]};
                border-radius: 8px;
                padding: 10px 12px;
                font-family: {UI["font"]};
                font-size: 14px;
                selection-background-color: rgba(119, 183, 255, 95);
            }}
            QPlainTextEdit:focus {{
                border-color: {UI["accent"]};
                background-color: rgba(15, 21, 27, 232);
            }}
        """)

        # Top row with a close button.
        title_layout = QtWidgets.QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)

        title_icon = QtWidgets.QLabel()
        title_icon.setFixedSize(24, 24)
        title_icon.setPixmap(_icon("text", UI["accent"], 18).pixmap(QtCore.QSize(18, 18)))
        title_icon.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title_icon.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        title_layout.addWidget(title_icon)

        title = QtWidgets.QLabel("Text Input")
        title.setStyleSheet("font-size: 15px; font-weight: 800;")
        title.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        title_layout.addWidget(title)
        title_layout.addStretch(1)
        self.close_button = QtWidgets.QToolButton()
        self.close_button.setIcon(_icon("close", UI["text"], 18))
        self.close_button.setFixedSize(30, 30)
        self.close_button.setToolTip("Close")
        self.close_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.close_button.setStyleSheet(_tool_button_style("danger", compact=True))
        self.close_button.clicked.connect(self.close)
        title_layout.addWidget(self.close_button)
        main_layout.addLayout(title_layout)

        # Input field.
        self.input_field = PromptTextEdit()
        self.input_field.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.input_field.setPlaceholderText("Ask about the current screen or session...")
        self.input_field.setMinimumHeight(96)
        self.input_field.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.input_field.submit_requested.connect(self.handle_submit)
        self.input_field.close_requested.connect(self.close)
        self.input_field.textChanged.connect(self._sync_submit_state)
        main_layout.addWidget(self.input_field, 1)

        action_layout = QtWidgets.QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)
        action_layout.addStretch(1)

        # Submit button (kept in the input overlay).
        self.submit_button = QtWidgets.QToolButton()
        self.submit_button.setText("Submit")
        self.submit_button.setIcon(_icon("text", UI["accent"]))
        self.submit_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.submit_button.setFixedWidth(116)
        self.submit_button.setFixedHeight(38)
        self.submit_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.submit_button.setStyleSheet(_tool_button_style("accent"))
        self.submit_button.clicked.connect(self.handle_submit)
        action_layout.addWidget(self.submit_button)
        main_layout.addLayout(action_layout)
        self._sync_submit_state()

    def _sync_submit_state(self):
        self.submit_button.setEnabled(bool(self.input_field.toPlainText().strip()))

    def showEvent(self, event):
        super().showEvent(event)
        # Exclude this window from screen capture.
        set_exclude_from_capture(self.winId())
        # Bring focus to the input field.
        QtCore.QTimer.singleShot(0, self._focus_editor)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._focus_editor()

    def _focus_editor(self):
        self.raise_()
        self.activateWindow()
        self.input_field.setFocus(QtCore.Qt.FocusReason.ActiveWindowFocusReason)

    def handle_submit(self):
        text = self.input_field.toPlainText().strip()
        if text:
            self.text_submitted.emit(text)
            self.close()

# ----------------------------------------------------------------
# DraggableOverlay: the main overlay window.
class DraggableOverlay(QtWidgets.QWidget):
    text_submitted = Signal(str)
    
    # New signals for specialized analysis functions
    code_analysis_signal = Signal(str)  # For code problem analysis
    
    update_conversation_signal = Signal(str)  # New signal for thread-safe updates
    clear_history_signal = Signal()  # Signal to stop processing and clear history

    # New signal for general analysis with no thinking
    general_analysis_no_thinking_signal = Signal(str)
    
    # Signal for interview answers removed
    
    # New signal for updating transcriptions
    update_transcription_signal = Signal(str, str)
    
    # Signal for processing selected transcription removed

    def __init__(self):
        super().__init__()
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.WindowStaysOnTopHint |
            QtCore.Qt.WindowType.Tool |
            QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(0.9)
        self.setMinimumSize(MIN_OVERLAY_WIDTH, MIN_OVERLAY_HEIGHT)
        self.resize(1200, 600)

        self.is_processing = False
        self.use_transcriptions = True
        self.show_interviewer_suggestions = False

        self.last_interviewer_question = ""
        self.last_suggested_answer = ""
        self._active_auto_answer_question = ""
        self._active_auto_answer_user_index = None
        self._active_auto_answer_answer_index = None

        self.dragging = False
        self.resizing = False
        self.offset = QtCore.QPoint()
        self.resize_position = None
        self.show_resize_handles = True
        self.responsive_mode = None
        self.user_transcription_panel_visible = True
        self.compact_transcription_drawer_visible = False
        self.is_transcription_collapsed = False
        self._applying_responsive_layout = False
        self._status_text = "Listening..."
        self._status_color = UI["success"]

        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(18, 18, 18, 18)
        self.layout.setSpacing(0)

        class DummyButton:
            def __init__(self, checked=True):
                self._checked = checked

            def isChecked(self):
                return self._checked

            def sizeHint(self):
                class SizeHint:
                    def __init__(self):
                        self.height = 26
                        self.width = 100

                    def height(self):
                        return self.height
                return SizeHint()

        self.desktop_audio_button = DummyButton(checked=True)
        self.mic_button = DummyButton(checked=True)

        self._build_opacity_row()
        self.layout.addWidget(self.opacity_row)
        self.opacity_row.setVisible(False)

        self._build_title_bar()
        self.layout.addWidget(self.title_bar)

        self._build_content_area()
        self.layout.addWidget(self.content_area)
        self.setLayout(self.layout)

        self.create_resize_handles()

        self.conversation_history = []
        self.transcription_history = []
        self.input_overlay = None

        self.update_conversation_signal.connect(self._update_conversation_text)
        self.update_transcription_signal.connect(self._update_transcription_text)
        self._apply_responsive_layout(force=True)

    def _build_opacity_row(self):
        self.opacity_row = QtWidgets.QWidget(self)
        self.opacity_row.setAutoFillBackground(False)
        self.opacity_row.setFixedHeight(26)

        opacity_layout = QtWidgets.QHBoxLayout(self.opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.setSpacing(8)

        self.opacity_label = QtWidgets.QLabel("Opacity")
        self.opacity_label.setStyleSheet(f"color: {UI['text']}; font-family: {UI['font']}; font-size: 12px;")
        opacity_layout.addWidget(self.opacity_label)

        self.opacity_slider = self._create_opacity_slider(260)
        opacity_layout.addWidget(self.opacity_slider)
        opacity_layout.addStretch(1)

    def _build_title_bar(self):
        self.title_bar = QtWidgets.QFrame(self)
        self.title_bar.setObjectName("TitleBar")
        self.title_bar.setStyleSheet(f"""
            QFrame#TitleBar {{
                background-color: {UI["chrome"]};
                border: 1px solid rgba(118, 134, 150, 50);
                border-bottom: 1px solid rgba(118, 134, 150, 68);
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border-bottom-left-radius: 0px;
                border-bottom-right-radius: 0px;
            }}
            QLabel {{
                color: {UI["text"]};
                font-family: {UI["font"]};
            }}
        """)
        self.title_bar.setFixedHeight(52)
        title_layout = QtWidgets.QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(16, 0, 14, 0)
        title_layout.setSpacing(8)

        self.title_label = QtWidgets.QLabel("AI Live")
        self.title_label.setMinimumWidth(58)
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 800;")
        title_layout.addWidget(self.title_label)

        self.status_dot = QtWidgets.QLabel("●")
        self.status_dot.setFixedWidth(10)
        self.status_dot.setStyleSheet(f"color: {self._status_color}; font-size: 13px;")
        title_layout.addWidget(self.status_dot)

        self.status_label = QtWidgets.QLabel(self._status_text)
        self.status_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Preferred)
        self.status_label.setMinimumWidth(58)
        self.status_label.setStyleSheet(f"color: {self._status_color}; font-size: 13px; font-weight: 600;")
        title_layout.addWidget(self.status_label)
        title_layout.addStretch(1)

        self.header_opacity_container = QtWidgets.QWidget(self.title_bar)
        header_opacity_layout = QtWidgets.QHBoxLayout(self.header_opacity_container)
        header_opacity_layout.setContentsMargins(0, 0, 0, 0)
        header_opacity_layout.setSpacing(7)
        self.header_opacity_label = QtWidgets.QLabel("Opacity")
        self.header_opacity_label.setStyleSheet(f"color: {UI['text']}; font-family: {UI['font']}; font-size: 12px;")
        header_opacity_layout.addWidget(self.header_opacity_label)
        self.header_opacity_slider = self._create_opacity_slider(92)
        header_opacity_layout.addWidget(self.header_opacity_slider)
        title_layout.addWidget(self.header_opacity_container)

        self.screenshot_toggle_button = self._create_toolbar_button(
            "camera", "Screenshots included", "success", checkable=True, checked=True
        )
        self.screenshot_toggle_button.toggled.connect(self.toggle_screenshots)
        title_layout.addWidget(self.screenshot_toggle_button)

        self.show_transcription_panel_button = self._create_toolbar_button(
            "transcript_panel", "Hide live transcription", "accent", checkable=True, checked=True
        )
        self.show_transcription_panel_button.toggled.connect(self.toggle_transcription_panel)
        title_layout.addWidget(self.show_transcription_panel_button)

        self.transcription_toggle_button = self._create_toolbar_button(
            "transcript", "Transcripts included in analysis", "accent", checkable=True, checked=True
        )
        self.transcription_toggle_button.toggled.connect(self.toggle_transcriptions)
        title_layout.addWidget(self.transcription_toggle_button)

        self.interviewer_suggestion_button = self._create_toolbar_button(
            "auto", "Auto-answer disabled", "success", checkable=True, checked=False
        )
        self.interviewer_suggestion_button.toggled.connect(self.toggle_interviewer_suggestions)
        title_layout.addWidget(self.interviewer_suggestion_button)

        self.close_button = self._create_toolbar_button("close", "Close", "danger")
        self.close_button.clicked.connect(self.quit_application)
        title_layout.addWidget(self.close_button)

    def _build_content_area(self):
        self.content_area = QtWidgets.QFrame(self)
        self.content_area.setObjectName("ContentArea")
        self.content_area.setStyleSheet(f"""
            QFrame#ContentArea {{
                background-color: {UI["window"]};
                border-left: 1px solid rgba(118, 134, 150, 50);
                border-right: 1px solid rgba(118, 134, 150, 50);
                border-bottom: 1px solid rgba(118, 134, 150, 50);
                border-top: none;
                border-top-left-radius: 0px;
                border-top-right-radius: 0px;
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }}
        """)

        content_root = QtWidgets.QVBoxLayout(self.content_area)
        content_root.setContentsMargins(0, 0, 0, 0)
        content_root.setSpacing(0)
        self.content_root_layout = content_root

        self.split_container = QtWidgets.QWidget()
        self.content_split_layout = QtWidgets.QHBoxLayout(self.split_container)
        self.content_split_layout.setContentsMargins(0, 0, 0, 0)
        self.content_split_layout.setSpacing(0)
        content_root.addWidget(self.split_container, 1)

        self.conversation_panel = QtWidgets.QWidget()
        conversation_layout = QtWidgets.QVBoxLayout(self.conversation_panel)
        conversation_layout.setContentsMargins(0, 0, 0, 0)
        conversation_layout.setSpacing(0)

        self.conversation_text = OverlayTextEdit()
        self.conversation_text.setReadOnly(True)
        self.conversation_text.setStyleSheet(_text_edit_style())
        self.conversation_text.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.conversation_text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.conversation_text.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.WidgetWidth)
        conversation_layout.addWidget(self.conversation_text)
        self.content_split_layout.addWidget(self.conversation_panel, 2)

        self.split_divider = QtWidgets.QFrame()
        self.split_divider.setFixedWidth(1)
        self.split_divider.setStyleSheet("background-color: rgba(118, 134, 150, 62); border: none;")
        self.content_split_layout.addWidget(self.split_divider)

        self.transcription_panel = QtWidgets.QWidget()
        self.transcription_panel.setMinimumWidth(0)
        transcription_layout = QtWidgets.QVBoxLayout(self.transcription_panel)
        transcription_layout.setContentsMargins(0, 0, 0, 0)
        transcription_layout.setSpacing(8)
        self.transcription_layout = transcription_layout

        transcription_header = QtWidgets.QWidget()
        transcription_header_layout = QtWidgets.QHBoxLayout(transcription_header)
        transcription_header_layout.setContentsMargins(0, 0, 0, 0)
        transcription_header_layout.setSpacing(6)

        self.transcription_title = QtWidgets.QLabel("Live Transcription")
        self.transcription_title.setStyleSheet(
            f"color: {UI['text']}; font-family: {UI['font']}; font-weight: 800; font-size: 14px;"
        )
        transcription_header_layout.addWidget(self.transcription_title)
        transcription_header_layout.addStretch(1)

        self.clear_transcription_button = self._create_toolbar_button(
            "trash", "Clear transcriptions", "danger"
        )
        self.clear_transcription_button.setVisible(False)
        self.clear_transcription_button.clicked.connect(self.clear_transcriptions)
        transcription_header_layout.addWidget(self.clear_transcription_button)
        transcription_layout.addWidget(transcription_header)

        self.transcription_text = OverlayTextEdit()
        self.transcription_text.setReadOnly(True)
        self.transcription_text.setStyleSheet(_text_edit_style())
        self.transcription_text.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.transcription_text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.transcription_text.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.WidgetWidth)
        self.transcription_text.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse |
            QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        transcription_layout.addWidget(self.transcription_text)

        self.compact_drawer = QtWidgets.QWidget()
        self.compact_drawer_layout = QtWidgets.QVBoxLayout(self.compact_drawer)
        self.compact_drawer_layout.setContentsMargins(0, 0, 0, 0)
        self.compact_drawer_layout.setSpacing(0)
        self.compact_drawer.setVisible(False)
        content_root.addWidget(self.compact_drawer, 0)

        self.command_bar = QtWidgets.QFrame()
        self.command_bar.setObjectName("CommandBar")
        self.command_bar.setStyleSheet(f"""
            QFrame#CommandBar {{
                background-color: rgba(15, 20, 25, 78);
                border-top: 1px solid rgba(118, 134, 150, 68);
                border-radius: 0px;
            }}
        """)
        self.command_layout = QtWidgets.QHBoxLayout(self.command_bar)
        self.command_layout.setContentsMargins(18, 0, 18, 0)
        self.command_layout.setSpacing(12)
        self.command_bar.setFixedHeight(72)
        content_root.addWidget(self.command_bar)

        self.input_button = self._create_action_button("text", "Text Input", "neutral", self.open_input_overlay)
        self.screenshot_button = self._create_action_button("camera", "Screenshot", "warning", self.take_screenshot)
        self.clear_button = self._create_action_button("trash", "Clear History", "danger", self.clear_history)
        self.code_analyze_button = self._create_action_button("code", "Code Analysis", "accent", self.execute_code_analyze)
        self.general_analyze_button_regular = self._create_action_button("document", "General Analysis", "success", self.execute_general_analyze_no_thinking)

        self.command_buttons = [
            self.input_button,
            self.screenshot_button,
            self.clear_button,
            self.code_analyze_button,
            self.general_analyze_button_regular,
        ]
        self.command_divider = QtWidgets.QFrame()
        self.command_divider.setFixedWidth(1)
        self.command_divider.setStyleSheet("background-color: rgba(118, 134, 150, 70); border: none;")

        for index, button in enumerate(self.command_buttons):
            self.command_layout.addWidget(button)
            if index == 2:
                self.command_layout.addWidget(self.command_divider)

        self.conversation_stretch = 2
        self.transcription_stretch = 1
        self._attach_transcription_to_split()

    def _create_opacity_slider(self, width):
        slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        slider.setMinimum(20)
        slider.setMaximum(100)
        slider.setValue(90)
        slider.setFixedWidth(width)
        slider.setStyleSheet(_slider_style())
        slider.valueChanged.connect(self.change_opacity)
        return slider

    def _create_toolbar_button(self, icon_kind, tooltip, tone="neutral", checkable=False, checked=False):
        button = QtWidgets.QToolButton()
        button._icon_kind = icon_kind
        button._tone = tone
        button.setFixedSize(36, 32)
        button.setIconSize(QtCore.QSize(20, 20))
        button.setIcon(_icon(icon_kind, TONE_COLORS.get(tone, UI["muted"])))
        button.setToolTip(tooltip)
        button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        button.setCheckable(checkable)
        if checkable:
            button.setChecked(checked)
        button.setStyleSheet(_tool_button_style(tone, compact=True))
        return button

    def _create_action_button(self, icon_kind, label, tone, callback):
        button = QtWidgets.QToolButton()
        button._icon_kind = icon_kind
        button._tone = tone
        button._button_role = "command"
        button._wide_text = label
        button._short_text = {
            "Text Input": "Input",
            "Screenshot": "Shot",
            "Clear History": "Clear",
            "Code Analysis": "Code",
            "General Analysis": "General",
        }.get(label, label)
        button.setText(label)
        button.setToolTip(label)
        button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        button.setIconSize(QtCore.QSize(20, 20))
        button.setIcon(_icon(icon_kind, TONE_COLORS.get(tone, UI["muted"])))
        button.setFixedHeight(38)
        button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        button.setStyleSheet(_command_button_style(tone))
        button.clicked.connect(callback)
        return button

    def _flash_button(self, button, tone=None, duration=500):
        tone = tone or getattr(button, "_tone", "neutral")
        compact = button.toolButtonStyle() == QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        if getattr(button, "_button_role", "") == "command":
            button.setStyleSheet(_command_button_style(tone, active=True))
        else:
            button.setStyleSheet(_tool_button_style(tone, active=True, compact=compact))

        def reset():
            if button:
                self._apply_button_style(button)

        QtCore.QTimer.singleShot(duration, reset)

    def _apply_button_style(self, button):
        compact = button.toolButtonStyle() == QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        if getattr(button, "_button_role", "") == "command":
            button.setStyleSheet(_command_button_style(getattr(button, "_tone", "neutral")))
        else:
            button.setStyleSheet(_tool_button_style(getattr(button, "_tone", "neutral"), compact=compact))

    def _set_checked_silently(self, button, checked):
        blocker = QtCore.QSignalBlocker(button)
        button.setChecked(checked)
        del blocker

    def _attach_transcription_to_split(self):
        self.compact_drawer_layout.removeWidget(self.transcription_panel)
        self.content_split_layout.removeWidget(self.transcription_panel)
        self.transcription_panel.setParent(self.split_container)
        self.split_divider.setVisible(True)
        self.content_split_layout.addWidget(self.transcription_panel, self.transcription_stretch)
        self.content_split_layout.setStretch(0, self.conversation_stretch)
        self.content_split_layout.setStretch(1, 0)
        self.content_split_layout.setStretch(2, self.transcription_stretch)

    def _attach_transcription_to_drawer(self):
        self.content_split_layout.removeWidget(self.transcription_panel)
        self.compact_drawer_layout.removeWidget(self.transcription_panel)
        self.split_divider.setVisible(False)
        self.transcription_panel.setParent(self.compact_drawer)
        self.compact_drawer_layout.addWidget(self.transcription_panel)

    def _detach_transcription_panel(self):
        self.content_split_layout.removeWidget(self.transcription_panel)
        self.compact_drawer_layout.removeWidget(self.transcription_panel)
        self.split_divider.setVisible(False)
        self.transcription_panel.setVisible(False)
        self.transcription_panel.setParent(None)

    def _set_command_bar_mode(self, compact):
        self.command_divider.setVisible(not compact)
        self.command_bar.setFixedHeight(46 if compact else 72)
        for button in self.command_buttons:
            if compact:
                button.setText("")
                button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
                button.setFixedSize(43, 38)
                button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
            else:
                button.setText(button._short_text if self.width() < 1040 else button._wide_text)
                button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                button.setMinimumWidth(0)
                button.setMaximumWidth(16777215)
                button.setFixedHeight(38)
                button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
            self._apply_button_style(button)

    def _sync_status_label(self):
        compact = self.responsive_mode == "compact"
        max_width = 92 if compact else 320
        self.status_label.setMaximumWidth(max_width)
        metrics = QtGui.QFontMetrics(self.status_label.font())
        self.status_label.setText(metrics.elidedText(self._status_text, QtCore.Qt.TextElideMode.ElideRight, max_width))
        self.status_label.setToolTip(self._status_text)

    def _sync_transcription_button(self):
        compact = self.responsive_mode == "compact"
        self.show_transcription_panel_button.setVisible(not compact)
        if compact:
            checked = False
            tooltip = "Live transcription is hidden in compact mode"
        else:
            checked = self.user_transcription_panel_visible
            tooltip = "Hide live transcription" if checked else "Show live transcription"
        self._set_checked_silently(self.show_transcription_panel_button, checked)
        self.show_transcription_panel_button.setToolTip(tooltip)

    def _apply_responsive_layout(self, force=False):
        if (
            not hasattr(self, "opacity_row")
            or not hasattr(self, "content_split_layout")
            or not hasattr(self, "command_buttons")
        ):
            return
        if self._applying_responsive_layout:
            return
        self._applying_responsive_layout = True
        try:
            compact = self.width() < RESPONSIVE_BREAKPOINT
            mode = "compact" if compact else "wide"
            mode_changed = mode != self.responsive_mode
            if mode_changed or force:
                self.responsive_mode = mode

            self.layout.setContentsMargins(12 if compact else 18, 12 if compact else 18, 12 if compact else 18, 12 if compact else 18)
            self.layout.setSpacing(0)
            self.opacity_row.setVisible(False)
            self.opacity_slider.setFixedWidth(190 if compact else 260)
            self.header_opacity_label.setVisible(not compact)
            self.header_opacity_slider.setFixedWidth(48 if compact else 92)
            self._set_command_bar_mode(compact)

            if compact:
                self.compact_transcription_drawer_visible = False
                self.compact_drawer.setVisible(False)
                self._detach_transcription_panel()
                self.is_transcription_collapsed = True
            else:
                self.compact_transcription_drawer_visible = False
                self.compact_drawer.setVisible(False)
                if self.user_transcription_panel_visible:
                    self._attach_transcription_to_split()
                    self.transcription_panel.setVisible(True)
                    self.is_transcription_collapsed = False
                else:
                    self._detach_transcription_panel()
                    self.is_transcription_collapsed = True

            self._sync_transcription_button()
            self._sync_status_label()
        finally:
            self._applying_responsive_layout = False

    @Slot(bool)
    def set_processing(self, processing_state: bool):
        self.is_processing = processing_state

    def toggle_desktop_audio(self, checked):
        """Stub implementation for desktop audio toggle (button has been removed)"""
        # Desktop audio is always enabled now
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio toggle called (button removed)", flush=True)

    def toggle_microphone(self, checked):
        """Stub implementation for microphone toggle (button has been removed)"""
        # Microphone is always enabled now
        if checked:
            self.update_status("Listening...", "#4CAF50")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Microphone toggle called (button removed)", flush=True)
        else:
            self.update_status("Microphone Off", "#FF5050")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Microphone toggle called (button removed)", flush=True)

    def toggle_screenshots(self, checked):
        """Handle screenshot toggle button state changes"""
        if checked:
            self.screenshot_toggle_button.setToolTip("Screenshots included")
            self.screenshot_toggle_button.setIcon(_icon("camera", UI["success"]))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Screenshots enabled for analysis", flush=True)
        else:
            self.screenshot_toggle_button.setToolTip("Screenshots excluded")
            self.screenshot_toggle_button.setIcon(_icon("camera", UI["muted_dim"]))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Screenshots disabled for analysis", flush=True)
        self._apply_button_style(self.screenshot_toggle_button)

    def toggle_transcriptions(self, checked):
        """Handle transcription toggle button state changes"""
        self.use_transcriptions = checked
        if checked:
            self.transcription_toggle_button.setToolTip("Transcripts included in analysis")
            self.transcription_toggle_button.setIcon(_icon("transcript", UI["accent"]))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Transcriptions will be included in analysis", flush=True)
        else:
            self.transcription_toggle_button.setToolTip("Transcripts excluded from analysis")
            self.transcription_toggle_button.setIcon(_icon("transcript", UI["muted_dim"]))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Transcriptions will be excluded from analysis", flush=True)
        self._apply_button_style(self.transcription_toggle_button)
            
    def toggle_interviewer_suggestions(self, checked):
        """Handle interviewer auto-answer toggle button state changes"""
        self.show_interviewer_suggestions = checked
        if checked:
            self.interviewer_suggestion_button.setToolTip("Auto-answer enabled")
            self.interviewer_suggestion_button.setIcon(_icon("auto", UI["success"]))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Interviewer questions will be auto-answered", flush=True)
        else:
            self.interviewer_suggestion_button.setToolTip("Auto-answer disabled")
            self.interviewer_suggestion_button.setIcon(_icon("auto", UI["muted_dim"]))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Interviewer questions will not be auto-answered", flush=True)
        self._apply_button_style(self.interviewer_suggestion_button)

    @Slot(str, str)
    def update_status(self, status: str, color="#4CAF50"):
        self._status_text = status
        self._status_color = color
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 13px;")
        self.status_label.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 600;")
        self._sync_status_label()

    def _update_conversation_text(self, conversation_text):
        """Thread-safe method to update the conversation text"""
        # Save current scroll position
        scrollbar = self.conversation_text.verticalScrollBar()
        current_position = scrollbar.value()
        
        # Update the text
        self.conversation_text.setHtml(conversation_text)
        
        # Restore the saved scroll position
        scrollbar.setValue(current_position)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Maintained scroll position at {current_position}", flush=True)

    @Slot(dict)
    def update_response(self, response_json: dict):
        # Expecting response_json to include "user_query" and "response".
        user_query = response_json.get("user_query", "")
        ai_response = response_json.get("response", "")
        if not user_query and not ai_response:
            return
        # Append entries to conversation history.
        if user_query:
            self.conversation_history.append({"role": "user", "content": user_query})
        if ai_response:
            self.conversation_history.append({"role": "assistant", "content": ai_response})
        # Rebuild conversation text.
        conversation_text = ""
        
        def escape_html(text):
            """Helper function to escape HTML special characters and handle escape sequences"""
            # First, escape HTML special characters
            text = (text.replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;")
                      .replace('"', "&quot;")
                      .replace("'", "&#39;"))
            
            # Handle common escape sequences
            text = (text.replace("\\n", "<br>")
                      .replace("\\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
                      .replace("\\r", "")
                      .replace("\\\\", "&#92;")
                      .replace("\\'", "&#39;")
                      .replace('\\"', "&quot;"))
            
            return text
        
        def process_inline_markdown(text):
            """Process inline markdown elements like bold, italic, links, etc."""
            # First process markdown patterns, then escape HTML
            import re
            
            # Store original text for inline code processing
            original_text = text
            
            # Links: [text](url) - process links first
            pattern = r'\[(.*?)\]\((.*?)\)'
            text = re.sub(pattern, r'<a href="\2" style="color: #5B9BD5; text-decoration: none;">\1</a>', text)
            
            # Bold: **text** or __text__
            pattern = r'(\*\*|__)(.*?)\1'
            text = re.sub(pattern, r'<b>\2</b>', text)
            
            # Italic: *text* or _text_ (but not at the start of a list item)
            pattern = r'(?<!\*\s)(\*|_)(.*?)\1'
            text = re.sub(pattern, r'<i>\2</i>', text)
            
            # Now escape any remaining HTML special chars
            processed_text = escape_html(text)
            
            # But unescape the HTML tags we just added
            processed_text = processed_text.replace("&lt;a ", "<a ")
            processed_text = processed_text.replace("&lt;/a&gt;", "</a>")
            processed_text = processed_text.replace("&lt;b&gt;", "<b>")
            processed_text = processed_text.replace("&lt;/b&gt;", "</b>")
            processed_text = processed_text.replace("&lt;i&gt;", "<i>")
            processed_text = processed_text.replace("&lt;/i&gt;", "</i>")
            
            # Process inline code last, after escaping HTML
            # Find all inline code segments in the original text
            inline_code_matches = re.finditer(r'`([^`]+)`', original_text)
            
            # Replace each match with properly formatted code
            for match in inline_code_matches:
                code_content = match.group(1)
                escaped_code = escape_html(code_content)
                formatted_code = f'<code style="background-color: rgba(50, 50, 50, 0.7); padding: 2px 4px; border-radius: 3px; font-family: monospace;">{escaped_code}</code>'
                
                # Create a pattern that will match the exact code string in the processed text
                code_placeholder = escape_html(f'`{code_content}`')
                processed_text = processed_text.replace(code_placeholder, formatted_code, 1)
            
            return processed_text
        
        def convert_markdown_to_html(text):
            """Convert markdown text to HTML with language-specific syntax highlighting via Pygments"""
            import re
            from pygments import highlight
            from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
            from pygments.formatters import HtmlFormatter

            lines = text.split('\n')
            html_lines = []
            in_code_block = False
            in_list = False
            in_paragraph = False
            in_table = False
            code_language = ""
            code_block_lines = []
            style = "monokai"

            formatter = HtmlFormatter(noclasses=True, style=style, nowrap=True)

            i = 0
            while i < len(lines):
                line = lines[i]

                # Handle code blocks
                if line.startswith("```"):
                    if in_paragraph:
                        html_lines.append('</p>')
                        in_paragraph = False

                    if not in_code_block:
                        # Start of code block
                        in_code_block = True
                        code_language = line[3:].strip()
                        code_block_lines = []
                    else:
                        # End of code block - apply syntax highlighting
                        code = "\n".join(code_block_lines)
                        lexer = None
                        lexer_used = False
                        if code_language:
                            try:
                                lexer = get_lexer_by_name(code_language, stripall=True)
                                lexer_used = True
                            except Exception:
                                lexer = TextLexer(stripall=True)
                                lexer_used = False
                        else:
                            try:
                                lexer = guess_lexer(code)
                                lexer_used = True
                            except Exception:
                                lexer = TextLexer(stripall=True)
                                lexer_used = False
                        highlighted_html = highlight(code, lexer, formatter)
                        # Remove enclosing <div> Pygments generates, keep only <pre>
                        highlighted_html = re.sub(r'^<div[^>]*>', '', highlighted_html)
                        highlighted_html = re.sub(r'</div>\s*$', '', highlighted_html)
                        highlighted_html = highlighted_html.replace("\n", "<br>")
                        html_lines.append(
                            '<table width="100%" cellspacing="0" cellpadding="0" '
                            'style="margin-top: 6px; margin-bottom: 6px; border-collapse: collapse;">'
                            '<tr><td style="background-color: #111922; border: 1px solid #2F3B48; '
                            'padding: 6px 10px;">'
                            '<pre style="margin: 0; font-family: Consolas, Cascadia Mono, monospace; '
                            'font-size: 14px; line-height: 1.18; color: #E8EEF5;">'
                            f"{highlighted_html}"
                            "</pre></td></tr></table>"
                        )
                        in_code_block = False
                        code_language = ""
                        code_block_lines = []
                elif in_code_block:
                    # Accumulate lines inside code block
                    code_block_lines.append(line)
                else:
                    # Detect table rows - if line contains | character
                    if '|' in line and (line.strip().startswith('|') or line.strip().endswith('|')):
                        # Check if it's a table header separator
                        if re.match(r'^\s*\|?\s*[-:]+[-|\s:]*\|?\s*$', line):
                            # This is a table header separator, skip it
                            i += 1
                            continue
                            
                        if not in_table:
                            # Start a new table
                            html_lines.append('<table style="border-collapse: collapse; width: 100%; margin: 10px 0;">')
                            in_table = True
                            
                            # Check if we need to add table headers
                            if i > 0 and '|' in lines[i-1]:
                                # Go back and add the previous line as a header row
                                cells = [cell.strip() for cell in lines[i-1].strip('|').split('|')]
                                html_lines.append('<thead><tr>')
                                for cell in cells:
                                    html_lines.append(f'<th style="border: 1px solid rgba(100, 100, 100, 0.5); padding: 8px; text-align: left; background-color: rgba(60, 60, 60, 0.5);">{process_inline_markdown(cell)}</th>')
                                html_lines.append('</tr></thead><tbody>')
                        
                        # Process table row
                        cells = [cell.strip() for cell in line.strip('|').split('|')]
                        html_lines.append('<tr>')
                        for cell in cells:
                            html_lines.append(f'<td style="border: 1px solid rgba(100, 100, 100, 0.5); padding: 8px; text-align: left;">{process_inline_markdown(cell)}</td>')
                        html_lines.append('</tr>')
                        
                        # Check if the table ends after this row
                        if i+1 >= len(lines) or not ('|' in lines[i+1] and (lines[i+1].strip().startswith('|') or lines[i+1].strip().endswith('|'))):
                            html_lines.append('</tbody></table>')
                            in_table = False
                    else:
                        # Close the table if we're transitioning out
                        if in_table:
                            html_lines.append('</tbody></table>')
                            in_table = False
                            
                        # Headers (up to h6)
                        if line.startswith('# '):
                            if in_paragraph:
                                html_lines.append('</p>')
                                in_paragraph = False
                            html_lines.append(f'<h1 style="color: #E0E0E0; font-size: 1.8em; margin: 0.8em 0 0.4em 0;">{process_inline_markdown(line[2:])}</h1>')
                        elif line.startswith('## '):
                            if in_paragraph:
                                html_lines.append('</p>')
                                in_paragraph = False
                            html_lines.append(f'<h2 style="color: #E0E0E0; font-size: 1.45em; margin: 0.45em 0 0.25em 0;">{process_inline_markdown(line[3:])}</h2>')
                        elif line.startswith('### '):
                            if in_paragraph:
                                html_lines.append('</p>')
                                in_paragraph = False
                            html_lines.append(f'<h3 style="color: #E0E0E0; font-size: 1.4em; margin: 0.6em 0 0.3em 0;">{process_inline_markdown(line[4:])}</h3>')
                        elif line.startswith('#### '):
                            if in_paragraph:
                                html_lines.append('</p>')
                                in_paragraph = False
                            html_lines.append(f'<h4 style="color: #E0E0E0; font-size: 1.3em; margin: 0.5em 0 0.25em 0;">{process_inline_markdown(line[5:])}</h4>')
                        elif line.startswith('##### '):
                            if in_paragraph:
                                html_lines.append('</p>')
                                in_paragraph = False
                            html_lines.append(f'<h5 style="color: #E0E0E0; font-size: 1.2em; margin: 0.4em 0 0.2em 0;">{process_inline_markdown(line[6:])}</h5>')
                        elif line.startswith('###### '):
                            if in_paragraph:
                                html_lines.append('</p>')
                                in_paragraph = False
                            html_lines.append(f'<h6 style="color: #E0E0E0; font-size: 1.1em; margin: 0.3em 0 0.15em 0;">{process_inline_markdown(line[7:])}</h6>')
                        
                        # Unordered lists
                        elif line.strip().startswith('- ') or line.strip().startswith('* '):
                            if in_paragraph:
                                html_lines.append('</p>')
                                in_paragraph = False
                                
                            if not in_list:
                                html_lines.append('<ul style="margin-top: 0.25em; margin-bottom: 0.25em;">')
                                in_list = True
                            
                            content = line.strip()[2:]  # Remove the list marker
                            html_lines.append(f'<li>{process_inline_markdown(content)}</li>')
                            
                            # Check if the list continues
                            if i+1 >= len(lines) or not (lines[i+1].strip().startswith('- ') or lines[i+1].strip().startswith('* ')):
                                html_lines.append('</ul>')
                                in_list = False
                        
                        # Ordered lists
                        elif line.strip() and line.strip()[0].isdigit() and line.strip().find('. ') > 0:
                            if in_paragraph:
                                html_lines.append('</p>')
                                in_paragraph = False
                                
                            if not in_list:
                                html_lines.append('<ol style="margin-top: 0.5em; margin-bottom: 0.5em;">')
                                in_list = True
                            
                            # Extract the content after the number and period
                            content = line.strip()[line.strip().find('. ')+2:]
                            html_lines.append(f'<li>{process_inline_markdown(content)}</li>')
                            
                            # Check if the list continues
                            if i+1 >= len(lines) or not (lines[i+1].strip() and lines[i+1].strip()[0].isdigit() and lines[i+1].strip().find('. ') > 0):
                                html_lines.append('</ol>')
                                in_list = False
                        
                        # Horizontal rule
                        elif line.strip() == '---':
                            if in_paragraph:
                                html_lines.append('</p>')
                                in_paragraph = False
                            html_lines.append('<hr style="border: 1px solid rgba(100, 100, 100, 0.5); margin: 1em 0;">')
                        
                        # Blockquote
                        elif line.strip().startswith('> '):
                            if in_paragraph:
                                html_lines.append('</p>')
                                in_paragraph = False
                            content = line.strip()[2:]  # Remove the quote marker
                            html_lines.append(f'<blockquote style="border-left: 3px solid rgba(100, 100, 100, 0.5); padding-left: 10px; margin: 0.5em 0; color: #CCCCCC;">{process_inline_markdown(content)}</blockquote>')
                        
                        # Process normal paragraph with inline markdown
                        else:
                            # Handle empty lines and paragraph breaks
                            if not line.strip():
                                if in_paragraph:
                                    html_lines.append('</p>')
                                    in_paragraph = False
                            else:
                                # Start a new paragraph if needed
                                if not in_paragraph:
                                    html_lines.append('<p style="margin: 0 0; line-height: 1.2;">')
                                    in_paragraph = True
                                html_lines.append(f'{process_inline_markdown(line)}')
                
                i += 1
            
            # Close any open paragraph
            if in_paragraph:
                html_lines.append('</p>')
                
            # Close any open table
            if in_table:
                html_lines.append('</tbody></table>')
                
            return '\n'.join(html_lines)
        
        for entry in self.conversation_history:
            role_label = "You" if entry["role"] == "user" else "AI"
            role_color = "#4CAF50" if entry["role"] == "user" else "#2196F3"
            
            # Convert markdown to HTML for the content
            content = entry["content"]
            content = convert_markdown_to_html(content)
            
            # Add proper spacing and styling
            content = f"<div style='margin-bottom: 0px; line-height: 1.2;'>{content}</div>"
            
            conversation_text += (
                f"<div style='margin-bottom: 0px;'>"
                f"<span style='color: {role_color}; font-weight: bold; font-size: 14px;'>{role_label}:</span> "
                f"{content}"
                f"</div>"
            )
        # Use signal to update the UI thread-safely
        self.update_conversation_signal.emit(conversation_text)

    def _render_conversation_history_basic(self):
        conversation_text = ""
        for entry in self.conversation_history:
            role_label = "You" if entry["role"] == "user" else "AI"
            role_color = "#4CAF50" if entry["role"] == "user" else "#2196F3"
            content = html.escape(str(entry.get("content", ""))).replace("\n", "<br>")
            conversation_text += (
                f"<div style='margin-bottom: 0px;'>"
                f"<span style='color: {role_color}; font-weight: bold; font-size: 14px;'>{role_label}:</span> "
                f"<div style='margin-bottom: 0px; line-height: 1.2;'>{content}</div>"
                f"</div>"
            )
        self.update_conversation_signal.emit(conversation_text)

    @Slot(str)
    def clear_conversation_display(self, message: str = ""):
        """Clear conversation history without adding synthetic chat turns."""
        self.conversation_history = []
        self._active_auto_answer_question = ""
        self._active_auto_answer_user_index = None
        self._active_auto_answer_answer_index = None
        if message:
            self.conversation_text.setHtml(
                f"<div style='color: #FFA500; text-align: center; margin: 10px 0;'>{message}</div>"
            )
        else:
            self.conversation_text.clear()

    # ---------------- Resize Handles ----------------
    def create_resize_handles(self):
        self.handles = []
        positions = [
            "top-left", "top-right", "bottom-left", "bottom-right",
            "top", "right", "bottom", "left"
        ]
        for pos in positions:
            handle = ResizeHandle(self, pos)
            self.handles.append(handle)
        self.position_resize_handles()

    def position_resize_handles(self):
        if not hasattr(self, 'handles'):
            return
        for handle in self.handles:
            if handle.position == "top-left":
                handle.move(0, 0)
            elif handle.position == "top-right":
                handle.move(self.width() - handle.width(), 0)
            elif handle.position == "bottom-left":
                handle.move(0, self.height() - handle.height())
            elif handle.position == "bottom-right":
                handle.move(self.width() - handle.width(), self.height() - handle.height())
            elif handle.position == "top":
                handle.move(self.width() // 2 - handle.width() // 2, 0)
            elif handle.position == "right":
                handle.move(self.width() - handle.width(), self.height() // 2 - handle.height() // 2)
            elif handle.position == "bottom":
                handle.move(self.width() // 2 - handle.width() // 2, self.height() - handle.height())
            elif handle.position == "left":
                handle.move(0, self.height() // 2 - handle.height() // 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_resize_handles()
        self._apply_responsive_layout()

    def start_resize(self, position, global_pos):
        self.resizing = True
        self.resize_position = position
        self.start_resize_pos = global_pos
        self.start_resize_geometry = self.geometry()

    def do_resize(self, global_pos):
        if not self.resizing:
            return
        delta = global_pos - self.start_resize_pos
        start_geo = self.start_resize_geometry

        new_x = start_geo.x()
        new_y = start_geo.y()
        new_width = start_geo.width()
        new_height = start_geo.height()

        if "left" in self.resize_position:
            new_x = start_geo.x() + delta.x()
            new_width = start_geo.width() - delta.x()
        elif "right" in self.resize_position:
            new_width = start_geo.width() + delta.x()

        if "top" in self.resize_position:
            new_y = start_geo.y() + delta.y()
            new_height = start_geo.height() - delta.y()
        elif "bottom" in self.resize_position:
            new_height = start_geo.height() + delta.y()

        min_width = self.minimumWidth()
        min_height = self.minimumHeight()

        if new_width < min_width:
            if "left" in self.resize_position:
                new_x = start_geo.x() + start_geo.width() - min_width
            new_width = min_width

        if new_height < min_height:
            if "top" in self.resize_position:
                new_y = start_geo.y() + start_geo.height() - min_height
            new_height = min_height

        self.setGeometry(QtCore.QRect(new_x, new_y, new_width, new_height))

    def end_resize(self):
        self.resizing = False
        self.resize_position = None

    # ---------------- Mouse Dragging ----------------
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.dragging = True
            self.offset = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(self.mapToGlobal(event.position().toPoint() - self.offset))

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.dragging = False

    # ---------------- Focus Behavior and Screen Capture Exclusion ----------------
    def showEvent(self, event):
        super().showEvent(event)
        apply_private_no_focus_window(self)

    def quit_application(self):
        print("Closing AI Live application...")
        self.close()
        # Import the quit_application function from ai_live.py
        try:
            from ai_live import quit_application
            quit_application()
        except ImportError:
            # Fallback if the import fails
            QtWidgets.QApplication.quit()

    # ---------------- Open the Input Overlay ----------------
    def open_input_overlay(self):
        # Ensure only one input overlay is open.
        if self.input_overlay is not None and self.input_overlay.isVisible():
            self.input_overlay._focus_editor()
            return
        self.input_overlay = InputOverlay(self)
        # Center it over the main overlay.
        center = self.geometry().center()
        self.input_overlay.move(
            center.x() - self.input_overlay.width() // 2,
            center.y() - self.input_overlay.height() // 2
        )
        self.input_overlay.text_submitted.connect(self.handle_text_submitted)
        self.input_overlay.show()

    def handle_text_submitted(self, text):
        # Emit signal to process the text
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 Text submitted: {text}", flush=True)
        
        # If text is empty, use selected transcription text or shared session context.
        if not text.strip():
            text = self.get_transcriptions()
            if text:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔤 Using selected transcription as input", flush=True)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔤 Using shared session context as input", flush=True)
                
        self.text_submitted.emit(text)
        # No need to set processing state here as it's set in the process_text_input function

    def take_screenshot(self):
        """Take a screenshot and add it to the queue"""
        try:
            # Import here to avoid circular imports
            from ai_live import capture_screenshot
            screenshot_base64 = capture_screenshot()
            screenshot_queue.put(screenshot_base64)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📸 Screenshot added to queue", flush=True)
            self._flash_button(self.screenshot_button, "success")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error taking screenshot: {e}", flush=True)
    
    def execute_code_analyze(self):
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Executing code analysis with specialized prompt", flush=True)
            
            # Get transcriptions to use for the analysis
            transcriptions = self.get_transcriptions()
            
            # Send the transcriptions directly, no need to append the prompt
            # since the analyze_code_problem function already handles this
            if transcriptions:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔤 Including transcriptions in code analysis", flush=True)
                self.code_analysis_signal.emit(transcriptions)
            else:
                # Emit an empty string if no transcriptions
                self.code_analysis_signal.emit("")
            
            self._flash_button(self.code_analyze_button)
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error executing code analysis: {e}", flush=True)

    def clear_history(self):
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ Clearing conversation history", flush=True)
            
            # Clear local conversation history
            self.clear_conversation_display("Conversation history cleared")
            
            # Clear the chat models' history
            from chat import clear_chat_history
            clear_chat_history()
            
            self._flash_button(self.clear_button)
            
            # Update status
            self.update_status("History cleared", "#FFA500")
            # Reset status after 2 seconds
            QtCore.QTimer.singleShot(2000, lambda: self.update_status("Listening...", "#4CAF50"))
            
            # Emit clear_history_signal
            self.clear_history_signal.emit()
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error clearing history: {e}", flush=True)
            self.update_status("Error clearing history", "#FF0000")

    def execute_general_analyze_no_thinking(self):
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 Executing general analysis with thinking_budget=0", flush=True)
            
            # Get transcriptions to use for the analysis
            transcriptions = self.get_transcriptions()
            
            # Send the transcriptions directly, no need to append the prompt
            # since the analyze_general_problem_no_thinking function already handles this
            if transcriptions:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔤 Including transcriptions in general analysis (no thinking)", flush=True)
                self.general_analysis_no_thinking_signal.emit(transcriptions)
            else:
                # Emit an empty string if no transcriptions
                self.general_analysis_no_thinking_signal.emit("")
            
            self._flash_button(self.general_analyze_button_regular)
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error executing general analysis (no thinking): {e}", flush=True)

    # Interview answer method removed

    # Add a new method to clear transcriptions
    def clear_transcriptions(self):
        """Clear the transcription history and display"""
        from session_context import clear_transcript_context

        self.transcription_history = []
        clear_transcript_context()
        self.transcription_text.clear()
        self.transcription_text.append("<div style='color: #FFA500; margin: 10px 0;'>Transcription history cleared</div>")
        
        self._flash_button(self.clear_transcription_button)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ Transcription history cleared", flush=True)
    
    # Add a new method to update transcriptions
    @Slot(str, str)
    def update_transcription(self, text, source_type):
        """Update the transcription display with new text"""
        # Add to transcription history
        self.transcription_history.append({"text": text, "source": source_type})
        
        # Use signal to update the UI thread-safely
        self.update_transcription_signal.emit(text, source_type)
    
    # Add a new slot to handle transcription updates
    @Slot(str, str)
    def _update_transcription_text(self, text, source_type):
        """Thread-safe method to update the transcription text"""
        # Set color based on source
        source_color = "#4CAF50" if source_type == "mic" else "#2196F3"
        
        # Add appropriate prefix based on source type
        prefix = "Me: " if source_type == "mic" else "Interviewer: "
        
        # Format the transcription text with color and prefix
        formatted_text = (
            f"<div style='margin-bottom: 10px; color: {source_color};'>"
            f"{prefix}{text}"
            f"</div>"
        )
        
        # Add to the transcription text area
        self.transcription_text.append(formatted_text)
        
        # Scroll to the bottom
        self.transcription_text.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.transcription_text.ensureCursorVisible()

    # Process selected transcription method removed
    
    # HTML tag cleaning method removed

    # Add helper method to get transcriptions
    def get_transcriptions(self):
        """
        Get selected transcription text for the current analysis request.
        Unselected transcript context is supplied by session_context.
        """
        # If transcriptions are disabled, return empty string
        if not self.use_transcriptions:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔇 Transcriptions excluded from analysis by toggle", flush=True)
            return ""
            
        # Check if there's any selected text
        cursor = self.transcription_text.textCursor()
        selected_text = cursor.selectedText()
        
        if selected_text:
            # If text is selected, use that
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Using selected transcription text", flush=True)
            return selected_text
        
        return ""

    def change_opacity(self, value):
        """Change the opacity of the window based on slider value"""
        opacity = value / 100.0
        self.setWindowOpacity(opacity)
        for slider in (getattr(self, "opacity_slider", None), getattr(self, "header_opacity_slider", None)):
            if slider and slider.value() != value:
                blocker = QtCore.QSignalBlocker(slider)
                slider.setValue(value)
                del blocker
    
    def toggle_transcription_panel(self, checked=None):
        """Toggle the side transcription panel in wide mode."""
        compact = self.width() < RESPONSIVE_BREAKPOINT
        if compact:
            self.compact_transcription_drawer_visible = False
        else:
            if checked is None:
                self.user_transcription_panel_visible = not self.user_transcription_panel_visible
            else:
                self.user_transcription_panel_visible = checked
            self.compact_transcription_drawer_visible = False
        self._apply_responsive_layout(force=True)

# This method is now directly in update_interviewer_qa for better flow control
        
    def remove_suggestion_from_display(self):
        """Remove any interviewer suggestion from the conversation display"""
        # Since we're now using the standard conversation format,
        # we need a different approach to remove suggestions
        
        # The simplest approach is to rebuild the conversation from history,
        # excluding the suggestion we added
        
        try:
            # If we've added suggestions to the conversation history, remove them
            if hasattr(self, 'conversation_history'):
                # Look for entries that match our last suggestion
                original_length = len(self.conversation_history)
                
                # Remove entries that match our Q&A pair (if any)
                if self.last_interviewer_question and self.last_suggested_answer:
                    # Create filtered history
                    self.conversation_history = [
                        entry for entry in self.conversation_history 
                        if not (entry.get("role") == "user" and entry.get("content") == self.last_interviewer_question) and
                           not (entry.get("role") == "assistant" and entry.get("content") == self.last_suggested_answer)
                    ]
                    
                    # If we removed entries, rebuild the conversation display
                    if len(self.conversation_history) != original_length:
                        # Rebuild conversation text
                        conversation_text = ""
                        
                        from datetime import datetime
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ Removed suggestion from conversation history", flush=True)
                        
                        conversation_text = ""
                        for entry in self.conversation_history:
                            role_label = "You" if entry["role"] == "user" else "AI"
                            role_color = "#4CAF50" if entry["role"] == "user" else "#2196F3"
                            conversation_text += (
                                f"<div style='margin-bottom: 0px;'>"
                                f"<span style='color: {role_color}; font-weight: bold; font-size: 14px;'>{role_label}:</span> "
                                f"<div style='margin-bottom: 0px; line-height: 1.2;'>{entry['content']}</div>"
                                f"</div>"
                            )
                        self.update_conversation_signal.emit(conversation_text)
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error removing suggestion: {e}", flush=True)

    @Slot(str, str, bool)
    def update_interviewer_qa(self, question, answer, done):
        """Update the stored interviewer Q&A and update the display if needed"""
        # Make sure we have non-empty content
        if not question or not answer:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Skipping empty interviewer Q&A update", flush=True)
            return
            
        # Update the stored values
        self.last_interviewer_question = question
        self.last_suggested_answer = answer
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎙️ Received interviewer Q&A update", flush=True)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🤖 Auto-answer is {'enabled' if self.show_interviewer_suggestions else 'disabled'}", flush=True)
        
        # Check if auto-answer is enabled or force-enable for first question
        if self.show_interviewer_suggestions:
            # If auto-answer is on, display the suggestion
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 Auto-answering interviewer question", flush=True)
            user_index = self._active_auto_answer_user_index
            answer_index = self._active_auto_answer_answer_index
            has_active_entry = (
                self._active_auto_answer_question == question
                and user_index is not None
                and answer_index is not None
                and user_index < len(self.conversation_history)
                and answer_index < len(self.conversation_history)
            )

            if has_active_entry:
                self.conversation_history[user_index] = {"role": "user", "content": question}
                self.conversation_history[answer_index] = {"role": "assistant", "content": answer}
                self._render_conversation_history_basic()
            else:
                self._active_auto_answer_question = question
                self._active_auto_answer_user_index = len(self.conversation_history)
                self.conversation_history.append({"role": "user", "content": question})
                self._active_auto_answer_answer_index = len(self.conversation_history)
                self.conversation_history.append({"role": "assistant", "content": answer})
                self._render_conversation_history_basic()

            if done:
                self._active_auto_answer_question = ""
                self._active_auto_answer_user_index = None
                self._active_auto_answer_answer_index = None
        else:
            # Auto-answer is disabled, just store the Q&A but don't display
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚫 Not auto-answering (feature disabled)", flush=True)

# ----------------------------------------------------------------
# Main entry point.
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    overlay = DraggableOverlay()
    overlay.show()
    sys.exit(app.exec())
