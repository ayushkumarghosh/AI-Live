import sys, ctypes, json
from PyQt5 import QtWidgets, QtCore, QtGui

# Windows extended style constant for no activation.
WS_EX_NOACTIVATE = 0x08000000

# ----------------------------------------------------------------
# Utility function: sets the window to be excluded from screen capture.
def set_exclude_from_capture(winId):
    hwnd = int(winId)
    WDA_EXCLUDEFROMCAPTURE = 0x11  # Requires Windows 10 build 2004+
    result = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    if not result:
        print("Warning: Failed to set window display affinity.")

# ----------------------------------------------------------------
# ResizeHandle: used for resizing the overlay.
class ResizeHandle(QtWidgets.QWidget):
    def __init__(self, parent, position):
        super().__init__(parent)
        self.position = position  # e.g., "top-left", "right", etc.
        self.parent = parent

        self.setCursor(QtCore.Qt.ArrowCursor)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
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
        if event.button() == QtCore.Qt.LeftButton:
            self.parent.start_resize(self.position, event.globalPos())

    def mouseMoveEvent(self, event):
        if self.parent.resizing:
            self.parent.do_resize(event.globalPos())

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.parent.end_resize()

# ----------------------------------------------------------------
# InputOverlay: a separate focusable overlay for text input.
class InputOverlay(QtWidgets.QWidget):
    # Signal emitted when text is submitted.
    text_submitted = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Do not set WS_EX_NOACTIVATE here so that this window can accept focus.
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.resize(400, 100)

        # Main layout with margins.
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Top row with a close button.
        title_layout = QtWidgets.QHBoxLayout()
        title_layout.addStretch(1)
        self.close_button = QtWidgets.QPushButton("✕")
        self.close_button.setFixedSize(20, 20)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(80, 80, 80, 200);
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: rgba(200, 60, 60, 200);
            }
            QPushButton:pressed {
                background-color: rgba(180, 40, 40, 200);
            }
        """)
        self.close_button.clicked.connect(self.close)
        title_layout.addWidget(self.close_button)
        main_layout.addLayout(title_layout)

        # Input field.
        self.input_field = QtWidgets.QLineEdit()
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: rgba(60, 60, 60, 150);
                color: white;
                border: 1px solid rgba(100, 100, 100, 150);
                border-radius: 5px;
                padding: 8px;
                font-size: 14px;
            }
        """)
        self.input_field.setPlaceholderText("Type your question and press Enter...")
        # When return is pressed, call handle_submit.
        self.input_field.returnPressed.connect(self.handle_submit)
        main_layout.addWidget(self.input_field)

        # Submit button (kept in the input overlay).
        self.submit_button = QtWidgets.QPushButton("Submit")
        self.submit_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(70, 130, 180, 200);
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(100, 160, 210, 200);
            }
            QPushButton:pressed {
                background-color: rgba(60, 120, 170, 200);
            }
        """)
        self.submit_button.clicked.connect(self.handle_submit)
        main_layout.addWidget(self.submit_button)

    def showEvent(self, event):
        super().showEvent(event)
        # Exclude this window from screen capture.
        set_exclude_from_capture(self.winId())
        # Bring focus to the input field.
        QtCore.QTimer.singleShot(0, self.input_field.setFocus)

    def handle_submit(self):
        text = self.input_field.text().strip()
        if text:
            self.text_submitted.emit(text)
        self.close()

# ----------------------------------------------------------------
# DraggableOverlay: the main overlay window.
class DraggableOverlay(QtWidgets.QWidget):
    text_submitted = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        # Set up as non-activating.
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool |
            QtCore.Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.resize(800, 600)

        # Initialize processing state.
        self.is_processing = False

        # Flags for dragging and resizing.
        self.dragging = False
        self.resizing = False
        self.offset = QtCore.QPoint()
        self.resize_position = None
        self.show_resize_handles = True

        # Main layout.
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(20, 20, 20, 20)

        # Title bar.
        self.title_bar = QtWidgets.QWidget(self)
        self.title_bar.setStyleSheet("background-color: rgba(50, 50, 50, 200); border-radius: 5px;")
        title_layout = QtWidgets.QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(10, 5, 10, 5)

        self.title_label = QtWidgets.QLabel("AI Live")
        self.title_label.setStyleSheet("color: white; font-weight: bold; font-size: 16px;")
        title_layout.addWidget(self.title_label)

        self.status_label = QtWidgets.QLabel("Listening...")
        self.status_label.setStyleSheet("color: #4CAF50; font-size: 14px;")
        title_layout.addWidget(self.status_label)
        title_layout.addStretch(1)

        self.close_button = QtWidgets.QPushButton("✕")
        self.close_button.setFixedSize(24, 24)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(80, 80, 80, 200);
                color: white;
                border: none;
                border-radius: 12px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(200, 60, 60, 200);
            }
            QPushButton:pressed {
                background-color: rgba(180, 40, 40, 200);
            }
        """)
        self.close_button.setCursor(QtCore.Qt.ArrowCursor)
        self.close_button.clicked.connect(self.quit_application)
        title_layout.addWidget(self.close_button)
        self.layout.addWidget(self.title_bar)

        # Content area.
        self.content_area = QtWidgets.QWidget(self)
        self.content_area.setStyleSheet("background-color: rgba(30, 30, 30, 180); border-radius: 5px;")
        content_layout = QtWidgets.QVBoxLayout(self.content_area)

        self.conversation_text = QtWidgets.QTextEdit()
        self.conversation_text.setReadOnly(True)
        self.conversation_text.setStyleSheet("""
            QTextEdit {
                background-color: rgba(40, 40, 40, 150);
                color: #E0E0E0;
                border: none;
                font-size: 14px;
                padding: 10px;
                line-height: 1.5;
            }
            QScrollBar:vertical {
                border: none;
                background: rgba(50, 50, 50, 100);
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(100, 100, 100, 150);
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        self.conversation_text.viewport().setCursor(QtCore.Qt.ArrowCursor)
        self.conversation_text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.conversation_text.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
        content_layout.addWidget(self.conversation_text)

        # Input area: only the "Enter Text" button.
        input_layout = QtWidgets.QHBoxLayout()
        self.enter_text_button = QtWidgets.QPushButton("Enter Text")
        self.enter_text_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(60, 60, 60, 150);
                color: white;
                border: 1px solid rgba(100, 100, 100, 150);
                border-radius: 5px;
                padding: 8px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(80, 80, 80, 150);
            }
            QPushButton:pressed {
                background-color: rgba(60, 60, 60, 200);
            }
        """)
        self.enter_text_button.setCursor(QtCore.Qt.ArrowCursor)
        self.enter_text_button.clicked.connect(self.open_input_overlay)
        input_layout.addWidget(self.enter_text_button)
        content_layout.addLayout(input_layout)

        self.layout.addWidget(self.content_area)
        self.setLayout(self.layout)

        # Create resize handles.
        self.create_resize_handles()

        # Conversation history.
        self.conversation_history = []
        # Keep track of input overlay instance.
        self.input_overlay = None

    # Methods for processing state and status updating.
    def set_processing(self, processing_state: bool):
        self.is_processing = processing_state

    def update_status(self, status: str, color="#4CAF50"):
        self.status_label.setText(status)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 14px;")

    def update_response(self, response_json: dict):
        # Expecting response_json to include "user_query" and "response".
        user_query = response_json.get("user_query", "")
        ai_response = response_json.get("response", "")
        # Append entries to conversation history.
        self.conversation_history.append({"role": "user", "content": user_query})
        self.conversation_history.append({"role": "assistant", "content": ai_response})
        # Rebuild conversation text.
        conversation_text = ""
        for entry in self.conversation_history:
            role_label = "You" if entry["role"] == "user" else "AI"
            role_color = "#4CAF50" if entry["role"] == "user" else "#2196F3"
            conversation_text += (
                f"<span style='color: {role_color}; font-weight: bold;'>{role_label}:</span> "
                f"{entry['content']}<br><br>"
            )
        self.conversation_text.setHtml(conversation_text)

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

    def start_resize(self, position, global_pos):
        self.resizing = True
        self.resize_position = position
        self.start_resize_pos = global_pos
        self.start_resize_geometry = self.geometry()

    def do_resize(self, global_pos):
        if not self.resizing:
            return
        delta = global_pos - self.start_resize_pos
        new_geo = QtCore.QRect(self.start_resize_geometry)
        if "left" in self.resize_position:
            new_geo.setLeft(self.start_resize_geometry.left() + delta.x())
        if "right" in self.resize_position:
            new_geo.setRight(self.start_resize_geometry.right() + delta.x())
        if "top" in self.resize_position:
            new_geo.setTop(self.start_resize_geometry.top() + delta.y())
        if "bottom" in self.resize_position:
            new_geo.setBottom(self.start_resize_geometry.bottom() + delta.y())
        if new_geo.width() >= self.minimumWidth() and new_geo.height() >= self.minimumHeight():
            self.setGeometry(new_geo)

    def end_resize(self):
        self.resizing = False
        self.resize_position = None

    # ---------------- Mouse Dragging ----------------
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.dragging = True
            self.offset = event.pos()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(self.mapToGlobal(event.pos() - self.offset))

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.dragging = False

    # ---------------- Focus Behavior and Screen Capture Exclusion ----------------
    def showEvent(self, event):
        super().showEvent(event)
        set_exclude_from_capture(self.winId())
        # Apply WS_EX_NOACTIVATE to the main overlay.
        hwnd = int(self.winId())
        current_ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, current_ex_style | WS_EX_NOACTIVATE)

    def quit_application(self):
        print("Closing AI Live application...")
        self.close()
        QtWidgets.QApplication.quit()

    # ---------------- Open the Input Overlay ----------------
    def open_input_overlay(self):
        # Ensure only one input overlay is open.
        if self.input_overlay is not None and self.input_overlay.isVisible():
            self.input_overlay.raise_()
            self.input_overlay.activateWindow()
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
        # Emit signal if needed.
        self.text_submitted.emit(text)

# ----------------------------------------------------------------
# Main entry point.
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    overlay = DraggableOverlay()
    overlay.show()
    sys.exit(app.exec_())
