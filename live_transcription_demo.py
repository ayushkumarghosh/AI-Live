import sys
from PyQt6 import QtWidgets
import threading
from datetime import datetime
from live_transcription import LiveTranscriptionManager
from overlay import DraggableOverlay

def main():
    """Main entry point for the live transcription demo"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Live Transcription Demo", flush=True)
    
    # Create Qt application
    app = QtWidgets.QApplication(sys.argv)
    
    # Create and show the overlay
    overlay = DraggableOverlay()
    overlay.show()
    
    # Create the transcription callback function
    def transcription_callback(text, source_type):
        """Callback function for transcription updates"""
        if overlay:
            # Update the overlay with the transcription
            overlay.update_transcription(text, source_type)
    
    # Create the transcription manager
    transcription_manager = LiveTranscriptionManager(transcription_callback)
    
    # Start the transcription in a separate thread
    def start_transcription():
        transcription_manager.start_transcription()
    
    threading.Thread(target=start_transcription, daemon=True).start()
    
    # Define cleanup
    def cleanup():
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Cleaning up resources", flush=True)
        transcription_manager.cleanup()
    
    # Register cleanup on exit
    app.aboutToQuit.connect(cleanup)
    
    # Run the Qt event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 