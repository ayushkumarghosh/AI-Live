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

class DraggableOverlay(QtWidgets.QWidget):
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
        self.offset = QtCore.QPoint()
        
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
        self.conversation_text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.conversation_text.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
        content_layout.addWidget(self.conversation_text)
        
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
        
        # Initialize conversation history and processing state
        self.conversation_history = []
        self.is_processing = False
        
        # Setup a queue for thread-safe operations
        self._queue = []
        self._queue_mutex = QtCore.QMutex()
        self._queue_timer = QtCore.QTimer(self)
        self._queue_timer.timeout.connect(self._process_queue)
        self._queue_timer.start(100)  # Process queue every 100ms

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
        
        # Format the entire conversation
        conversation_text = ""
        for entry in self.conversation_history:
            if entry["role"] == "user":
                conversation_text += f"<span style='color: #4CAF50; font-weight: bold;'>You:</span> {entry['content']}<br>"
            else:
                conversation_text += f"<span style='color: #2196F3; font-weight: bold;'>AI:</span> {entry['content']}<br><br>"
        
        # Set the formatted conversation
        self.conversation_text.setHtml(conversation_text)
        
        # Scroll to bottom
        self.conversation_text.verticalScrollBar().setValue(
            self.conversation_text.verticalScrollBar().maximum()
        )
        
        # Update processing state
        self.is_processing = False

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
                    conversation_text += f"<span style='color: #4CAF50; font-weight: bold;'>You:</span> {entry['content']}<br>"
                else:
                    conversation_text += f"<span style='color: #2196F3; font-weight: bold;'>AI:</span> {entry['content']}<br><br>"
            
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

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    overlay = DraggableOverlay()
    overlay.show()
    sys.exit(app.exec_()) 