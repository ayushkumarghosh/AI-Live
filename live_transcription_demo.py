import sys
from datetime import datetime

from PyQt6 import QtCore, QtWidgets

from azure_realtime import build_realtime_answer_instructions
from live_transcription import LiveAudioManager
from overlay import DraggableOverlay
from resume_context import get_resume_context_section


def timestamp():
    return f"[{datetime.now().strftime('%H:%M:%S')}]"


def main():
    """Run the overlay with direct desktop-audio Realtime answers."""
    print(f"{timestamp()} Starting Realtime answer demo", flush=True)
    app = QtWidgets.QApplication(sys.argv)
    overlay = DraggableOverlay()
    overlay.show()

    def answer_update(action, text):
        QtCore.QMetaObject.invokeMethod(
            overlay,
            "apply_realtime_answer_update",
            QtCore.Qt.ConnectionType.QueuedConnection,
            QtCore.Q_ARG(str, action),
            QtCore.Q_ARG(str, text),
        )

    manager = LiveAudioManager(
        answer_update_callback=answer_update,
        instructions_provider=lambda: build_realtime_answer_instructions(
            get_resume_context_section()
        ),
    )
    overlay.auto_answer_toggled_signal.connect(manager.set_auto_answer_enabled)
    overlay.resume_context_changed_signal.connect(manager.refresh_instructions)
    overlay.clear_history_signal.connect(manager.reset_context)
    manager.start()

    def cleanup():
        print(f"{timestamp()} Cleaning up resources", flush=True)
        manager.cleanup()

    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
