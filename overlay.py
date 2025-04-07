import sys
from PyQt5 import QtWidgets, QtCore, QtGui
import ctypes
import json

class OverlayThread(QtCore.QThread):
    """Thread for running overlay UI to prevent freezing the main application"""
    def __init__(self):
        super().__init__()
        self.overlay = None
        
    def run(self):
        # Create overlay in this thread
        self.overlay = DraggableOverlay()
        
        # Show the overlay
        self.overlay.show()
        
        # Create a separate event loop for this thread
        self.exec_()

class ResizeHandle(QtWidgets.QWidget):
    """Resize handle for overlay window"""
    def __init__(self, parent, position):
        super().__init__(parent)
        self.position = position  # "top-left", "right", etc.
        self.parent = parent
        
        # Use arrow cursor for all handles
        self.setCursor(QtCore.Qt.ArrowCursor)
        
        # Make the handle transparent
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        
        # Set size
        self.setFixedSize(20, 20)
        
    def paintEvent(self, event):
        """Paint the handle with a subtle indicator"""
        if self.parent.show_resize_handles:
            painter = QtGui.QPainter(self)
            painter.setPen(QtGui.QPen(QtGui.QColor(180, 180, 180, 120), 1))
            painter.setBrush(QtGui.QBrush(QtGui.QColor(120, 120, 120, 80)))
            
            # Draw a small rectangle or circle to indicate handle
            if "corner" in self.position:
                painter.drawRect(0, 0, 10, 10)
            else:
                painter.drawRect(0, 0, 8, 8)
    
    def mousePressEvent(self, event):
        """Handle mouse press to start resizing"""
        if event.button() == QtCore.Qt.LeftButton:
            self.parent.start_resize(self.position, event.globalPos())
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for resize operation"""
        if self.parent.resizing:
            self.parent.do_resize(event.globalPos())
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release to end resizing"""
        if event.button() == QtCore.Qt.LeftButton:
            self.parent.end_resize()

class DraggableOverlay(QtWidgets.QWidget):
    # Add a signal for text submission
    text_submitted = QtCore.pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        # Create a frameless, always-on-top overlay window
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint |
                          QtCore.Qt.WindowStaysOnTopHint |
                          QtCore.Qt.Tool)
        # Make the background translucent
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        
        # Set initial size (larger size)
        self.resize(800, 600)
        
        # Variables for dragging
        self.dragging = False
        self.resizing = False
        self.offset = QtCore.QPoint()
        self.resize_position = None
        self.show_resize_handles = True  # Set to True to see the handles initially
        
        # Create a layout for the content
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(20, 20, 20, 20)
        
        # Create a title bar
        self.title_bar = QtWidgets.QWidget(self)
        self.title_bar.setStyleSheet("background-color: rgba(50, 50, 50, 200); border-radius: 5px;")
        title_layout = QtWidgets.QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(10, 5, 10, 5)
        
        # Title label
        self.title_label = QtWidgets.QLabel("AI Live")
        self.title_label.setStyleSheet("color: white; font-weight: bold; font-size: 16px;")
        title_layout.addWidget(self.title_label)
        
        # Status indicator
        self.status_label = QtWidgets.QLabel("Listening...")
        self.status_label.setStyleSheet("color: #4CAF50; font-size: 14px;")
        title_layout.addWidget(self.status_label)
        
        # Spacer to push buttons to the right
        title_layout.addStretch(1)
        
        # Close button
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
        
        # Add title bar to main layout
        self.layout.addWidget(self.title_bar)
        
        # Create content area
        self.content_area = QtWidgets.QWidget(self)
        self.content_area.setStyleSheet("background-color: rgba(30, 30, 30, 180); border-radius: 5px;")
        content_layout = QtWidgets.QVBoxLayout(self.content_area)
        
        # Conversation text area with scrollbar
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
        # Prevent cursor from changing on hover
        self.conversation_text.viewport().setCursor(QtCore.Qt.ArrowCursor)
        self.conversation_text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.conversation_text.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
        content_layout.addWidget(self.conversation_text)
        
        # Add text input area and submit button
        input_layout = QtWidgets.QHBoxLayout()
        
        # Text input field
        self.text_input = QtWidgets.QLineEdit()
        self.text_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(60, 60, 60, 150);
                color: white;
                border: 1px solid rgba(100, 100, 100, 150);
                border-radius: 5px;
                padding: 8px;
                font-size: 14px;
            }
        """)
        self.text_input.setPlaceholderText("Type your question and press Enter...")
        self.text_input.returnPressed.connect(self.submit_text)
        input_layout.addWidget(self.text_input)
        
        # Submit button
        self.submit_button = QtWidgets.QPushButton("Submit")
        self.submit_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(70, 130, 180, 200);
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(100, 160, 210, 200);
            }
            QPushButton:pressed {
                background-color: rgba(60, 120, 170, 200);
            }
        """)
        self.submit_button.setCursor(QtCore.Qt.ArrowCursor)
        self.submit_button.clicked.connect(self.submit_text)
        input_layout.addWidget(self.submit_button)
        
        # Add input layout to content layout
        content_layout.addLayout(input_layout)
        
        # Add content area to main layout
        self.layout.addWidget(self.content_area)
        
        # Set the main layout
        self.setLayout(self.layout)
        
        # Apply styles
        self.setStyleSheet("""
            QWidget {
                border-radius: 5px;
            }
        """)
        
        # Create resize handles
        self.create_resize_handles()
        
        # Initialize conversation history and processing state
        self.conversation_history = []
        self.is_processing = False
        
        # Setup a queue for thread-safe operations
        self._queue = []
        self._queue_mutex = QtCore.QMutex()
        self._queue_timer = QtCore.QTimer(self)
        self._queue_timer.timeout.connect(self._process_queue)
        self._queue_timer.start(100)  # Process queue every 100ms
        
        # Set minimum size
        self.setMinimumSize(300, 200)
    
    def create_resize_handles(self):
        """Create resize handles at the corners and edges"""
        self.handles = []
        
        # Create corner handles
        positions = [
            "top-left", "top-right", "bottom-left", "bottom-right",
            "top", "right", "bottom", "left"
        ]
        
        for pos in positions:
            handle = ResizeHandle(self, pos)
            self.handles.append(handle)
        
        # Position the handles during resize events
        self.position_resize_handles()
    
    def position_resize_handles(self):
        """Position the resize handles based on the current window geometry"""
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
        """Handle resize event to reposition resize handles"""
        super().resizeEvent(event)
        self.position_resize_handles()
    
    def start_resize(self, position, global_pos):
        """Start resize operation"""
        self.resizing = True
        self.resize_position = position
        self.start_resize_pos = global_pos
        self.start_resize_geometry = self.geometry()
    
    def do_resize(self, global_pos):
        """Perform resize based on mouse movement and resize position"""
        if not self.resizing:
            return
            
        delta = global_pos - self.start_resize_pos
        new_geo = QtCore.QRect(self.start_resize_geometry)
        
        # Apply resize based on position
        if "left" in self.resize_position:
            new_geo.setLeft(self.start_resize_geometry.left() + delta.x())
        if "right" in self.resize_position:
            new_geo.setRight(self.start_resize_geometry.right() + delta.x())
        if "top" in self.resize_position:
            new_geo.setTop(self.start_resize_geometry.top() + delta.y())
        if "bottom" in self.resize_position:
            new_geo.setBottom(self.start_resize_geometry.bottom() + delta.y())
        
        # Apply new geometry if it meets minimum size
        if new_geo.width() >= self.minimumWidth() and new_geo.height() >= self.minimumHeight():
            self.setGeometry(new_geo)
    
    def end_resize(self):
        """End resize operation"""
        self.resizing = False
        self.resize_position = None

    def _enqueue(self, func, *args, **kwargs):
        """Enqueue a function to be executed in the UI thread"""
        with QtCore.QMutexLocker(self._queue_mutex):
            self._queue.append((func, args, kwargs))
    
    def _process_queue(self):
        """Process queued functions in the UI thread"""
        with QtCore.QMutexLocker(self._queue_mutex):
            queue = self._queue
            self._queue = []
        
        for func, args, kwargs in queue:
            func(*args, **kwargs)

    def update_status(self, status, color="#4CAF50"):
        """Update the status label with new text and color"""
        # Add to queue for thread-safe execution
        self._enqueue(self._update_status_impl, status, color)
    
    def _update_status_impl(self, status, color):
        """Actual implementation of status update in UI thread"""
        self.status_label.setText(status)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 14px;")

    def update_response(self, response_data):
        """Update the conversation with new response"""
        # Add to queue for thread-safe execution
        self._enqueue(self._update_response_impl, response_data)
    
    def _update_response_impl(self, response_data):
        """Actual implementation of response update in UI thread"""
        # Extract data from the response
        if isinstance(response_data, dict):
            # Extract directly from the dictionary response
            user_query = response_data.get("user_query", "Could not extract query")
            ai_response = response_data.get("response", "No response generated")
        else:
            # Handle the case where response_data is a string (for backward compatibility)
            try:
                # Try to parse as JSON
                json_data = json.loads(response_data)
                user_query = json_data.get("user_query", "Could not extract query")
                ai_response = json_data.get("response", "No response generated")
            except (json.JSONDecodeError, TypeError):
                # If it's not valid JSON, use original string handling
                parts = response_data.split("\n\n", 1)
                if len(parts) > 1 and parts[0].startswith("User's query:"):
                    user_query = parts[0].replace("User's query:", "").strip()
                    ai_response = parts[1]
                else:
                    user_query = "Could not extract query"
                    ai_response = response_data
        
        # Add to conversation history
        self.conversation_history.append({"role": "user", "content": user_query})
        self.conversation_history.append({"role": "assistant", "content": ai_response})
        
        # Format the entire conversation with proper code handling
        conversation_text = ""
        for entry in self.conversation_history:
            if entry["role"] == "user":
                conversation_text += f"<span style='color: #4CAF50; font-weight: bold;'>You:</span> {entry['content']}<br><br>"
            else:
                # Process AI response to format code blocks properly
                formatted_content = self._format_code_blocks(entry['content'])
                conversation_text += f"<span style='color: #2196F3; font-weight: bold;'>AI:</span> {formatted_content}<br><br>"
        
        # Set the formatted conversation
        self.conversation_text.setHtml(conversation_text)
        
        # Scroll to bottom
        self.conversation_text.verticalScrollBar().setValue(
            self.conversation_text.verticalScrollBar().maximum()
        )
        
        # Update processing state
        self.is_processing = False
    
    def _format_code_blocks(self, text):
        """Format code blocks with proper styling"""
        import re
        
        # Define CSS for code blocks once
        css = """
        <style>
            pre.code-block {
                background-color: #2b2b2b;
                color: #e6e6e6;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                padding: 12px;
                border-radius: 5px;
                margin: 10px 0;
                white-space: pre-wrap;
                overflow-x: auto;
                font-size: 13px;
                line-height: 1.4;
            }
            .language-header {
                color: #808080;
                font-size: 12px;
                font-family: sans-serif;
                margin-bottom: 5px;
                font-weight: bold;
            }
        </style>
        """
        
        # Check if the text actually contains code blocks
        if "```" not in text:
            # No code blocks, just return the text with newlines as <br> tags
            return text.replace('\n', '<br>')
        
        # Pattern to match code blocks with optional language specification
        pattern = r'```(\w+)?\n([\s\S]*?)```'
        
        # Start with CSS
        formatted_text = css
        
        # Process text and replace code blocks
        last_end = 0
        for match in re.finditer(pattern, text):
            # Add the text before this code block
            formatted_text += text[last_end:match.start()].replace('\n', '<br>')
            
            # Extract language and code
            lang = match.group(1) or ''
            code = match.group(2)
            
            # HTML escape the code content
            code_html = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            # Format with proper HTML tags
            if lang:
                formatted_text += f'<div class="language-header">{lang}</div>'
            
            formatted_text += f'<pre class="code-block">{code_html}</pre>'
            
            # Update the last position
            last_end = match.end()
        
        # Add remaining text
        formatted_text += text[last_end:].replace('\n', '<br>')
        
        return formatted_text

    def show_processing(self):
        """Show processing indicator in the conversation area"""
        # Add to queue for thread-safe execution
        self._enqueue(self._show_processing_impl)
    
    def _show_processing_impl(self):
        """Actual implementation of showing processing indicator in UI thread"""
        if not self.is_processing:
            self.is_processing = True
            
            # Format the conversation with a processing indicator
            conversation_text = ""
            for entry in self.conversation_history:
                if entry["role"] == "user":
                    conversation_text += f"<span style='color: #4CAF50; font-weight: bold;'>You:</span> {entry['content']}<br><br>"
                else:
                    # Process AI response to format code blocks properly
                    formatted_content = self._format_code_blocks(entry['content'])
                    conversation_text += f"<span style='color: #2196F3; font-weight: bold;'>AI:</span> {formatted_content}<br><br>"
            
            conversation_text += "<span style='color: #FFA500; font-style: italic;'>Processing...</span>"
            
            # Set the formatted conversation
            self.conversation_text.setHtml(conversation_text)
            
            # Scroll to bottom
            self.conversation_text.verticalScrollBar().setValue(
                self.conversation_text.verticalScrollBar().maximum()
            )

    def clear_response(self):
        """Clear the conversation history"""
        # Add to queue for thread-safe execution
        self._enqueue(self._clear_response_impl)
    
    def _clear_response_impl(self):
        """Actual implementation of clearing conversation in UI thread"""
        self.conversation_history = []
        self.conversation_text.clear()

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

    def showEvent(self, event):
        super().showEvent(event)
        # Once the window is visible, set it to be excluded from capture
        self.set_exclude_from_capture()

    def set_exclude_from_capture(self):
        # This is Windows-specific: use SetWindowDisplayAffinity
        hwnd = int(self.winId())
        # WDA_EXCLUDEFROMCAPTURE is available on Windows 10 (build 2004 and later)
        WDA_EXCLUDEFROMCAPTURE = 0x11
        result = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        if not result:
            print("Warning: Failed to set window display affinity. Screen sharing may capture the overlay.")
    
    def quit_application(self):
        """Stop the entire application when close button is clicked"""
        print("Closing AI Live application...")
        # Close the overlay window
        self.close()
        # Quit the application
        QtWidgets.QApplication.quit()

    def submit_text(self):
        """Handle text submission from the input field"""
        text = self.text_input.text().strip()
        if text:
            # Show processing status
            self.update_status("Processing...", "#FFA500")
            self._enqueue(self._show_processing_impl)
            
            # Emit the text submitted signal
            self.text_submitted.emit(text)
            
            # Clear the input field
            self.text_input.clear()

    def set_processing(self, processing_state):
        """Set the processing state flag"""
        # Add to queue for thread-safe execution
        self._enqueue(self._set_processing_impl, processing_state)
    
    def _set_processing_impl(self, processing_state):
        """Actual implementation of setting processing state in UI thread"""
        self.is_processing = processing_state

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    overlay = DraggableOverlay()
    overlay.show()
    sys.exit(app.exec_()) 