import sys, ctypes, json
from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import pyqtSignal as Signal, pyqtSlot as Slot
from datetime import datetime
import queue
import re
import platform
import os

# Windows extended style constant for no activation.
WS_EX_NOACTIVATE = 0x08000000

# Queue for screenshots
screenshot_queue = queue.Queue()

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
# InputOverlay: a separate focusable overlay for text input.
class InputOverlay(QtWidgets.QWidget):
    # Signal emitted when text is submitted.
    text_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Do not set WS_EX_NOACTIVATE here so that this window can accept focus.
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.WindowStaysOnTopHint |
            QtCore.Qt.WindowType.Tool
        )
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
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
    text_submitted = Signal(str)
    pro_text_submitted = Signal(str)  # New signal for pro model text processing
    
    # New signals for specialized analysis functions
    code_analysis_signal = Signal(str)  # For code problem analysis
    general_analysis_signal = Signal(str)  # For general problem analysis  
    repeat_analysis_signal = Signal(str)  # For repeat analysis
    pro_code_analysis_signal = Signal(str)  # For pro code analysis
    pro_repeat_analysis_signal = Signal(str)  # For pro repeat analysis
    
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
        # Set up as non-activating.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.WindowStaysOnTopHint |
            QtCore.Qt.WindowType.Tool |
            QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(1200, 600)  # Wider to accommodate the transcription section

        # Initialize processing state.
        self.is_processing = False
        
        # New flag to control if transcriptions should be passed to analysis
        self.use_transcriptions = True

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
        
        # Desktop audio button removed
        
        # Microphone button removed
        
        # Add properties for desktop_audio_button and mic_button even though they don't exist in UI
        # This is for backward compatibility with existing code
        class DummyButton:
            def __init__(self, checked=True):
                self._checked = checked
                
            def isChecked(self):
                return self._checked
                
            def sizeHint(self):
                # Return a dummy size hint
                class SizeHint:
                    def __init__(self):
                        self.height = 26
                        self.width = 100
                    def height(self):
                        return self.height
                return SizeHint()
        
        # Create dummy buttons that will be used by code that depends on these objects
        self.desktop_audio_button = DummyButton(checked=True)
        self.mic_button = DummyButton(checked=True)
        
        # Add Screenshot Toggle button (Moved to Title Bar)
        self.screenshot_toggle_button = QtWidgets.QPushButton("🖼️ Screenshots On")
        self.screenshot_toggle_button.setCheckable(True)
        self.screenshot_toggle_button.setChecked(True) # Enabled by default
        # Set fixed height for the button
        self.screenshot_toggle_button.setFixedHeight(26)
        self.screenshot_toggle_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(100, 180, 100, 200); /* Greenish */
                color: white;
                border: none;
                border-radius: 5px;
                padding: 5px 10px; /* Match other title bar buttons */
                font-size: 12px; /* Match other title bar buttons */
            }
            QPushButton:checked {
                background-color: rgba(70, 150, 70, 200); /* Darker Green */
            }
            QPushButton:hover {
                background-color: rgba(120, 200, 120, 200);
            }
            QPushButton:pressed {
                background-color: rgba(90, 170, 90, 200);
            }
        """)
        self.screenshot_toggle_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.screenshot_toggle_button.toggled.connect(self.toggle_screenshots)
        title_layout.addWidget(self.screenshot_toggle_button)
        
        # Add Transcription Toggle button
        self.transcription_toggle_button = QtWidgets.QPushButton("🗣️ Include Transcripts")
        self.transcription_toggle_button.setCheckable(True)
        self.transcription_toggle_button.setChecked(True) # Enabled by default
        # Set fixed height for the button
        self.transcription_toggle_button.setFixedHeight(26)
        self.transcription_toggle_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(100, 150, 180, 200); /* Blueish */
                color: white;
                border: none;
                border-radius: 5px;
                padding: 5px 10px; /* Match other title bar buttons */
                font-size: 12px; /* Match other title bar buttons */
            }
            QPushButton:checked {
                background-color: rgba(70, 120, 150, 200); /* Darker Blue */
            }
            QPushButton:hover {
                background-color: rgba(120, 170, 200, 200);
            }
            QPushButton:pressed {
                background-color: rgba(90, 140, 170, 200);
            }
        """)
        self.transcription_toggle_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.transcription_toggle_button.toggled.connect(self.toggle_transcriptions)
        title_layout.addWidget(self.transcription_toggle_button)
        
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
        self.close_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.close_button.clicked.connect(self.quit_application)
        title_layout.addWidget(self.close_button)
        self.layout.addWidget(self.title_bar)

        # Main content area with split for conversation and transcription
        self.content_area = QtWidgets.QWidget(self)
        self.content_area.setStyleSheet("background-color: rgba(30, 30, 30, 180); border-radius: 5px;")
        
        # Create a horizontal layout for the split
        content_split_layout = QtWidgets.QHBoxLayout(self.content_area)
        content_split_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create the conversation panel (left side)
        self.conversation_panel = QtWidgets.QWidget()
        conversation_layout = QtWidgets.QVBoxLayout(self.conversation_panel)
        conversation_layout.setContentsMargins(0, 0, 10, 0)
        
        # Conversation area
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
        self.conversation_text.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.conversation_text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.conversation_text.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.WidgetWidth)
        conversation_layout.addWidget(self.conversation_text)
        
        # Input area - create a layout for action buttons
        input_layout = QtWidgets.QHBoxLayout()
        
        # Create a button for text input
        self.input_button = QtWidgets.QPushButton("💬 Text Input")
        self.input_button.setStyleSheet("""
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
        self.input_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.input_button.clicked.connect(self.open_input_overlay)
        input_layout.addWidget(self.input_button)
        
        # Add screenshot button
        self.screenshot_button = QtWidgets.QPushButton("📸 Screenshot")
        self.screenshot_button.setFixedHeight(30)  # Set a fixed height
        self.screenshot_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(180, 130, 70, 200);
                color: white; 
                border: none;
                border-radius: 5px;
                padding: 0 8px;  /* Adjust padding */
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(210, 160, 100, 200);
            }
            QPushButton:pressed {
                background-color: rgba(170, 120, 60, 200);
            }
        """)
        self.screenshot_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.screenshot_button.clicked.connect(self.take_screenshot)
        input_layout.addWidget(self.screenshot_button)
        
        # Add Clear History button
        self.clear_button = QtWidgets.QPushButton("🗑️ Clear History")
        self.clear_button.setFixedHeight(30)  # Set a fixed height
        self.clear_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(180, 80, 80, 200);  /* Red color */
                color: white; 
                border: none;
                border-radius: 5px;
                padding: 0 8px;  /* Adjust padding */
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(200, 100, 100, 200);
            }
            QPushButton:pressed {
                background-color: rgba(160, 60, 60, 200);
            }
        """)
        self.clear_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.clear_button.clicked.connect(self.clear_history)
        input_layout.addWidget(self.clear_button)
        
        conversation_layout.addLayout(input_layout)
        
        # Create a second row for analysis buttons
        analysis_layout = QtWidgets.QHBoxLayout()
        
        # Add Code Analysis button
        self.code_analyze_button = QtWidgets.QPushButton("🔍 Code Analysis")
        self.code_analyze_button.setFixedHeight(30)
        self.code_analyze_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(70, 130, 180, 200);
                color: white; 
                border: none;
                border-radius: 5px;
                padding: 0 8px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: rgba(90, 150, 200, 200);
            }
            QPushButton:pressed {
                background-color: rgba(50, 110, 160, 200);
            }
        """)
        self.code_analyze_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.code_analyze_button.clicked.connect(self.execute_code_analyze)
        analysis_layout.addWidget(self.code_analyze_button)
        
        # Add General Analysis button
        self.general_analyze_button_regular = QtWidgets.QPushButton("📝 General Analysis")
        self.general_analyze_button_regular.setFixedHeight(30)
        self.general_analyze_button_regular.setStyleSheet("""
            QPushButton {
                background-color: rgba(34, 150, 50, 200);
                color: white; 
                border: none;
                border-radius: 5px;
                padding: 0 8px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: rgba(54, 170, 70, 200);
            }
            QPushButton:pressed {
                background-color: rgba(14, 130, 30, 200);
            }
        """)
        self.general_analyze_button_regular.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.general_analyze_button_regular.clicked.connect(self.execute_general_analyze_no_thinking)
        analysis_layout.addWidget(self.general_analyze_button_regular)
        
        # Add Repeat Analysis button
        self.repeat_analyze_button = QtWidgets.QPushButton("🔄 Repeat Analysis")
        self.repeat_analyze_button.setFixedHeight(30)
        self.repeat_analyze_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 140, 0, 200);
                color: white; 
                border: none;
                border-radius: 5px;
                padding: 0 8px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: rgba(255, 160, 20, 200);
            }
            QPushButton:pressed {
                background-color: rgba(235, 120, 0, 200);
            }
        """)
        self.repeat_analyze_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.repeat_analyze_button.clicked.connect(self.execute_repeat_analyze)
        analysis_layout.addWidget(self.repeat_analyze_button)
        
        conversation_layout.addLayout(analysis_layout)
        
        # Create a third row for Pro model buttons
        pro_layout = QtWidgets.QHBoxLayout()
        
        # Add Pro Code Analysis button
        self.pro_code_analyze_button = QtWidgets.QPushButton("🚀 Pro Code Analysis")
        self.pro_code_analyze_button.setFixedHeight(30)
        self.pro_code_analyze_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(75, 0, 130, 200);
                color: white; 
                border: none;
                border-radius: 5px;
                padding: 0 8px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: rgba(95, 20, 150, 200);
            }
            QPushButton:pressed {
                background-color: rgba(55, 0, 110, 200);
            }
        """)
        self.pro_code_analyze_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.pro_code_analyze_button.clicked.connect(self.execute_pro_code_analyze)
        pro_layout.addWidget(self.pro_code_analyze_button)
        
        # Add General Analysis button
        self.general_analyze_button = QtWidgets.QPushButton("📝 Pro General Analysis")
        self.general_analyze_button.setFixedHeight(30)
        self.general_analyze_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(34, 150, 50, 200);
                color: white; 
                border: none;
                border-radius: 5px;
                padding: 0 8px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: rgba(54, 170, 70, 200);
            }
            QPushButton:pressed {
                background-color: rgba(14, 130, 30, 200);
            }
        """)
        self.general_analyze_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.general_analyze_button.clicked.connect(self.execute_general_analyze)
        pro_layout.addWidget(self.general_analyze_button)
        
        # Add Pro Repeat Analysis button
        self.pro_repeat_analyze_button = QtWidgets.QPushButton("⚡ Pro Repeat Analysis")
        self.pro_repeat_analyze_button.setFixedHeight(30)
        self.pro_repeat_analyze_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(139, 0, 139, 200);
                color: white; 
                border: none;
                border-radius: 5px;
                padding: 0 8px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: rgba(159, 20, 159, 200);
            }
            QPushButton:pressed {
                background-color: rgba(119, 0, 119, 200);
            }
        """)
        self.pro_repeat_analyze_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.pro_repeat_analyze_button.clicked.connect(self.execute_pro_repeat_analyze)
        pro_layout.addWidget(self.pro_repeat_analyze_button)
        
        conversation_layout.addLayout(pro_layout)
        
        # Fourth row for utility buttons removed
        
        # Add the conversation panel to the split layout
        content_split_layout.addWidget(self.conversation_panel, 2)  # 2/3 of width
        
        # Create the transcription panel (right side)
        self.transcription_panel = QtWidgets.QWidget()
        transcription_layout = QtWidgets.QVBoxLayout(self.transcription_panel)
        transcription_layout.setContentsMargins(10, 0, 0, 0)
        
        # Transcription title
        transcription_title = QtWidgets.QLabel("Live Transcription")
        transcription_title.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        transcription_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        transcription_layout.addWidget(transcription_title)
        
        # Transcription display
        self.transcription_text = QtWidgets.QTextEdit()
        self.transcription_text.setReadOnly(True)
        self.transcription_text.setStyleSheet("""
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
        self.transcription_text.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.transcription_text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.transcription_text.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.WidgetWidth)
        # Enable text selection capabilities
        self.transcription_text.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse | 
            QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        transcription_layout.addWidget(self.transcription_text)
        
        # Create a layout for transcription action buttons
        transcription_buttons_layout = QtWidgets.QHBoxLayout()
        
        # Clear transcription button
        self.clear_transcription_button = QtWidgets.QPushButton("🗑️ Clear Transcriptions")
        self.clear_transcription_button.setFixedHeight(30)
        self.clear_transcription_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(180, 80, 80, 200);
                color: white; 
                border: none;
                border-radius: 5px;
                padding: 0 8px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(200, 100, 100, 200);
            }
            QPushButton:pressed {
                background-color: rgba(160, 60, 60, 200);
            }
        """)
        self.clear_transcription_button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.clear_transcription_button.clicked.connect(self.clear_transcriptions)
        transcription_buttons_layout.addWidget(self.clear_transcription_button)
        
        transcription_layout.addLayout(transcription_buttons_layout)
        
        # Add the transcription panel to the split layout
        content_split_layout.addWidget(self.transcription_panel, 1)  # 1/3 of width
        
        # Add the content area to the main layout
        self.layout.addWidget(self.content_area)
        self.setLayout(self.layout)

        # Create resize handles.
        self.create_resize_handles()

        # Conversation history.
        self.conversation_history = []
        # Transcription history
        self.transcription_history = []
        
        # Keep track of input overlay instance.
        self.input_overlay = None
        
        # Connect the signals to slots
        self.update_conversation_signal.connect(self._update_conversation_text)
        self.update_transcription_signal.connect(self._update_transcription_text)

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
            self.screenshot_toggle_button.setText("🖼️ Screenshots On")
            self.screenshot_toggle_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(100, 180, 100, 200); /* Greenish */
                    color: white;
                    border: none;
                    border-radius: 5px;
                    padding: 5px 10px; /* Match other title bar buttons */
                    font-size: 12px; /* Match other title bar buttons */
                }
                QPushButton:checked {
                    background-color: rgba(70, 150, 70, 200); /* Darker Green */
                }
                QPushButton:hover {
                    background-color: rgba(120, 200, 120, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(90, 170, 90, 200);
                }
            """)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🖼️ Screenshots enabled for analysis", flush=True)
        else:
            self.screenshot_toggle_button.setText("🚫 Screenshots Off")
            self.screenshot_toggle_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(180, 100, 100, 200); /* Reddish */
                    color: white;
                    border: none;
                    border-radius: 5px;
                    padding: 5px 10px; /* Match other title bar buttons */
                    font-size: 12px; /* Match other title bar buttons */
                }
                QPushButton:checked {
                     background-color: rgba(150, 70, 70, 200); /* Darker Red */
                }
                QPushButton:hover {
                    background-color: rgba(200, 120, 120, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(170, 90, 90, 200);
                }
            """)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚫 Screenshots disabled for analysis", flush=True)

    def toggle_transcriptions(self, checked):
        """Handle transcription toggle button state changes"""
        self.use_transcriptions = checked
        if checked:
            self.transcription_toggle_button.setText("🗣️ Include Transcripts")
            self.transcription_toggle_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(100, 150, 180, 200); /* Blueish */
                    color: white;
                    border: none;
                    border-radius: 5px;
                    padding: 5px 10px; /* Match other title bar buttons */
                    font-size: 12px; /* Match other title bar buttons */
                }
                QPushButton:checked {
                    background-color: rgba(70, 120, 150, 200); /* Darker Blue */
                }
                QPushButton:hover {
                    background-color: rgba(120, 170, 200, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(90, 140, 170, 200);
                }
            """)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗣️ Transcriptions will be included in analysis", flush=True)
        else:
            self.transcription_toggle_button.setText("🔇 Exclude Transcripts")
            self.transcription_toggle_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(180, 120, 160, 200); /* Purplish */
                    color: white;
                    border: none;
                    border-radius: 5px;
                    padding: 5px 10px; /* Match other title bar buttons */
                    font-size: 12px; /* Match other title bar buttons */
                }
                QPushButton:checked {
                     background-color: rgba(150, 90, 130, 200); /* Darker Purple */
                }
                QPushButton:hover {
                    background-color: rgba(200, 140, 180, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(170, 110, 150, 200);
                }
            """)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔇 Transcriptions will be excluded from analysis", flush=True)

    @Slot(str, str)
    def update_status(self, status: str, color="#4CAF50"):
        self.status_label.setText(status)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 14px;")

    def _update_conversation_text(self, conversation_text):
        """Thread-safe method to update the conversation text"""
        # Update the text
        self.conversation_text.setHtml(conversation_text)
        
        # Always scroll to the bottom
        self.conversation_text.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.conversation_text.ensureCursorVisible()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Scrolling to bottom of conversation", flush=True)

    @Slot(dict)
    def update_response(self, response_json: dict):
        # Expecting response_json to include "user_query" and "response".
        user_query = response_json.get("user_query", "")
        ai_response = response_json.get("response", "")
        # Append entries to conversation history.
        self.conversation_history.append({"role": "user", "content": user_query})
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

            formatter = HtmlFormatter(noclasses=True, style=style)

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
                        html_lines.append(highlighted_html)
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
                            html_lines.append(f'<h2 style="color: #E0E0E0; font-size: 1.6em; margin: 0.7em 0 0.35em 0;">{process_inline_markdown(line[3:])}</h2>')
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
                                html_lines.append('<ul style="margin-top: 0.5em; margin-bottom: 0.5em;">')
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
                                    html_lines.append('<p style="margin: 0.5em 0; line-height: 1.5;">')
                                    in_paragraph = True
                                html_lines.append(f'{process_inline_markdown(line)}<br>')
                
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
            content = f"<div style='margin-bottom: 10px; line-height: 1.5;'>{content}</div>"
            
            conversation_text += (
                f"<div style='margin-bottom: 15px;'>"
                f"<span style='color: {role_color}; font-weight: bold; font-size: 14px;'>{role_label}:</span> "
                f"{content}"
                f"</div>"
            )
        # Use signal to update the UI thread-safely
        self.update_conversation_signal.emit(conversation_text)

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
        set_exclude_from_capture(self.winId())
        # Apply WS_EX_NOACTIVATE to the main overlay.
        hwnd = int(self.winId())
        current_ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, current_ex_style | WS_EX_NOACTIVATE)

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
        # Emit signal to process the text
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 Text submitted: {text}", flush=True)
        
        # If text is empty, use transcriptions instead
        if not text.strip():
            text = self.get_transcriptions()
            if text:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔤 Using transcriptions as input", flush=True)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ No text or transcriptions available", flush=True)
                return
                
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
            # Show a brief visual feedback
            self.screenshot_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(70, 180, 70, 200);
                    color: white;
                    border: none; 
                    border-radius: 5px;
                    padding: 0 8px;  /* Keep padding consistent */
                    font-size: 14px;
                }
            """)
            # Reset the button style after 500ms
            QtCore.QTimer.singleShot(500, lambda: self.screenshot_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(180, 130, 70, 200);
                    color: white;
                    border: none;
                    border-radius: 5px; 
                    padding: 0 8px;
                    font-size: 14px;  
                }
                QPushButton:hover {
                    background-color: rgba(210, 160, 100, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(170, 120, 60, 200);
                }            """))
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
            
            # Visual feedback
            self.code_analyze_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(50, 110, 160, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
            """)
            
            # Reset the button style after 500ms
            QtCore.QTimer.singleShot(500, lambda: self.code_analyze_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(70, 130, 180, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: rgba(90, 150, 200, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(50, 110, 160, 200);
                }
            """))
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error executing code analysis: {e}", flush=True)

    def execute_general_analyze(self):
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📝 Executing general analysis with specialized prompt", flush=True)
            
            # Get transcriptions to use for the analysis
            transcriptions = self.get_transcriptions()
            
            # Send the transcriptions directly, no need to append the prompt
            # since the analyze_general_problem function already handles this
            if transcriptions:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔤 Including transcriptions in general analysis", flush=True)
                self.general_analysis_signal.emit(transcriptions)
            else:
                # Emit an empty string if no transcriptions
                self.general_analysis_signal.emit("")
            
            # Visual feedback
            self.general_analyze_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(14, 130, 30, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
            """)
            
            # Reset the button style after 500ms
            QtCore.QTimer.singleShot(500, lambda: self.general_analyze_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(34, 150, 50, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: rgba(54, 170, 70, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(14, 130, 30, 200);
                }
            """))
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error executing general analysis: {e}", flush=True)

    def execute_repeat_analyze(self):
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 Executing repeat analysis with specialized prompt", flush=True)
            
            # Get transcriptions to use for the analysis
            transcriptions = self.get_transcriptions()
            
            # Send the transcriptions directly, no need to append the prompt
            # since the analyze_repeat_problem function already handles this
            if transcriptions:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔤 Including transcriptions in repeat analysis", flush=True)
                self.repeat_analysis_signal.emit(transcriptions)
            else:
                # Emit an empty string if no transcriptions
                self.repeat_analysis_signal.emit("")
            
            # Visual feedback
            self.repeat_analyze_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(235, 120, 0, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
            """)
            
            # Reset the button style after 500ms
            QtCore.QTimer.singleShot(500, lambda: self.repeat_analyze_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 140, 0, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 160, 20, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(235, 120, 0, 200);
                }
            """))
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error executing repeat analysis: {e}", flush=True)

    def execute_pro_code_analyze(self):
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Executing Pro code analysis with specialized prompt", flush=True)
            
            # Get transcriptions to use for the analysis
            transcriptions = self.get_transcriptions()
            
            # Send the transcriptions directly, no need to append the prompt
            # since the analyze_code_problem_pro function already handles this
            if transcriptions:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔤 Including transcriptions in Pro code analysis", flush=True)
                self.pro_code_analysis_signal.emit(transcriptions)
            else:
                # Emit an empty string if no transcriptions
                self.pro_code_analysis_signal.emit("")
            
            # Visual feedback
            self.pro_code_analyze_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(55, 0, 110, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
            """)
            
            # Reset the button style after 500ms
            QtCore.QTimer.singleShot(500, lambda: self.pro_code_analyze_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(75, 0, 130, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: rgba(95, 20, 150, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(55, 0, 110, 200);
                }
            """))
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error executing Pro code analysis: {e}", flush=True)

    def execute_pro_repeat_analyze(self):
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ Executing Pro repeat analysis with specialized prompt", flush=True)
            
            # Get transcriptions to use for the analysis
            transcriptions = self.get_transcriptions()
            
            # Send the transcriptions directly, no need to append the prompt
            # since the analyze_repeat_problem_pro function already handles this
            if transcriptions:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔤 Including transcriptions in Pro repeat analysis", flush=True)
                self.pro_repeat_analysis_signal.emit(transcriptions)
            else:
                # Emit an empty string if no transcriptions
                self.pro_repeat_analysis_signal.emit("")
            
            # Visual feedback
            self.pro_repeat_analyze_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(119, 0, 119, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
            """)
            
            # Reset the button style after 500ms
            QtCore.QTimer.singleShot(500, lambda: self.pro_repeat_analyze_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(139, 0, 139, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: rgba(159, 20, 159, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(119, 0, 119, 200);
                }
            """))
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error executing Pro repeat analysis: {e}", flush=True)

    def clear_history(self):
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️ Clearing conversation history", flush=True)
            
            # Clear local conversation history
            self.conversation_history = []
            self.conversation_text.clear()
            
            # Clear the chat models' history
            from chat import clear_chat_history
            clear_chat_history()
            
            # Show confirmation message
            self.conversation_text.append("<div style='color: #FFA500; text-align: center; margin: 10px 0;'>Conversation history cleared</div>")
            
            # Visual feedback for the button
            self.clear_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(160, 60, 60, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 14px;
                }
            """)
            
            # Reset the button style after 500ms
            QtCore.QTimer.singleShot(500, lambda: self.clear_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(180, 80, 80, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: rgba(200, 100, 100, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(160, 60, 60, 200);
                }
            """))
            
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
            
            # Visual feedback
            self.general_analyze_button_regular.setStyleSheet("""
                QPushButton {
                    background-color: rgba(14, 130, 30, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
            """)
            
            # Reset the button style after 500ms
            QtCore.QTimer.singleShot(500, lambda: self.general_analyze_button_regular.setStyleSheet("""
                QPushButton {
                    background-color: rgba(34, 150, 50, 200);
                    color: white; 
                    border: none;
                    border-radius: 5px;
                    padding: 0 8px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: rgba(54, 170, 70, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(14, 130, 30, 200);
                }
            """))
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error executing general analysis (no thinking): {e}", flush=True)

    # Interview answer method removed

    # Add a new method to clear transcriptions
    def clear_transcriptions(self):
        """Clear the transcription history and display"""
        self.transcription_history = []
        self.transcription_text.clear()
        self.transcription_text.append("<div style='color: #FFA500; text-align: center; margin: 10px 0;'>Transcription history cleared</div>")
        
        # Visual feedback for the button
        self.clear_transcription_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(160, 60, 60, 200);
                color: white; 
                border: none;
                border-radius: 5px;
                padding: 0 8px;
                font-size: 14px;
            }
        """)
        
        # Reset the button style after 500ms
        QtCore.QTimer.singleShot(500, lambda: self.clear_transcription_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(180, 80, 80, 200);
                color: white; 
                border: none;
                border-radius: 5px;
                padding: 0 8px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(200, 100, 100, 200);
            }
            QPushButton:pressed {
                background-color: rgba(160, 60, 60, 200);
            }
        """))
        
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
        
        # Format the transcription text with just the color, no label
        formatted_text = (
            f"<div style='margin-bottom: 10px; color: {source_color};'>"
            f"{text}"
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
        Get either the selected transcriptions or the last 4 transcriptions.
        Returns a string formatted as interviewer/user conversation.
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
        
        # Otherwise, use the last 4 transcriptions
        if len(self.transcription_history) > 0:
            # Get last 4 transcriptions (or fewer if not enough available)
            last_transcriptions = self.transcription_history[-4:] if len(self.transcription_history) >= 4 else self.transcription_history
            formatted_text = ""
            
            # Format them as interviewer/user conversation
            for entry in last_transcriptions:
                speaker = "Interviewer" if entry["source"] == "desktop" else "Me"
                formatted_text += f"{speaker}: {entry['text']}\n\n"
                
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Using last {len(last_transcriptions)} transcriptions", flush=True)
            return formatted_text + "Please answer the last question in this conversation."
        
        # If no transcriptions available
        return ""

# ----------------------------------------------------------------
# Main entry point.
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    overlay = DraggableOverlay()
    overlay.show()
    sys.exit(app.exec())
