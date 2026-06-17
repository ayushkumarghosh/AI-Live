import base64
import io
import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Callable, List

from PIL import ImageGrab
from PyQt6 import QtCore, QtWidgets

from chat import (
    analyze_code_problem,
    analyze_general_problem_no_thinking,
    analyze_with_text_input,
    clear_chat_history,
    start_auto_answer_warmup,
)
from live_transcription import LiveTranscriptionManager
from overlay import DraggableOverlay, initialize_windows_ole, uninitialize_windows_ole
from session_context import record_transcript


def configure_console_encoding():
    """Keep Windows console logging from crashing on non-ASCII UI/status text."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


configure_console_encoding()


overlay = None
transcription_manager = None

RATE_LIMIT = 2.0
last_request_time = 0.0
api_semaphore = threading.Semaphore(1)
AUTO_ANSWER_LATENCY_LOG = os.getenv("AUTO_ANSWER_LATENCY_LOG", "false").strip().lower() in {"1", "true", "yes", "on"}


def timestamp():
    return f"[{datetime.now().strftime('%H:%M:%S')}]"


def capture_screenshot(max_width=1280, quality=85):
    """Capture a compressed screenshot and return it as base64 JPEG."""
    screenshot = ImageGrab.grab()
    orig_width, orig_height = screenshot.size

    if orig_width > max_width:
        ratio = max_width / float(orig_width)
        screenshot = screenshot.resize((max_width, int(orig_height * ratio)), resample=1)

    img_bytes = io.BytesIO()
    screenshot.save(img_bytes, format="JPEG", quality=quality, optimize=True)
    img_bytes.seek(0)
    return base64.b64encode(img_bytes.getvalue()).decode("utf-8")


def _run_on_ui(method_name: str, *args):
    if not overlay:
        return

    qt_args = []
    for value in args:
        if isinstance(value, dict):
            qt_args.append(QtCore.Q_ARG(dict, value))
        elif isinstance(value, bool):
            qt_args.append(QtCore.Q_ARG(bool, value))
        else:
            qt_args.append(QtCore.Q_ARG(str, str(value)))

    QtCore.QMetaObject.invokeMethod(
        overlay,
        method_name,
        QtCore.Qt.ConnectionType.QueuedConnection,
        *qt_args,
    )


def _mark_processing(session_id: str, status: str, color: str):
    if not overlay:
        return

    overlay.current_session_id = session_id
    overlay.set_processing(True)
    overlay.update_status(status, color)


def _is_current_session(session_id: str) -> bool:
    return bool(overlay and getattr(overlay, "current_session_id", None) == session_id)


def _collect_screenshots() -> List[str]:
    screenshots = []
    if not overlay or not overlay.screenshot_toggle_button.isChecked():
        print(f"{timestamp()} Screenshots disabled for this request", flush=True)
        return screenshots

    from overlay import screenshot_queue

    while not screenshot_queue.empty():
        try:
            screenshot = screenshot_queue.get_nowait()
            screenshots.append(screenshot)
            screenshot_queue.task_done()
            print(f"{timestamp()} Using queued screenshot", flush=True)
        except Exception:
            break

    if not screenshots:
        screenshots.append(capture_screenshot())
        print(f"{timestamp()} Captured new screenshot", flush=True)

    return screenshots


@contextmanager
def _with_rate_limit():
    global last_request_time

    with api_semaphore:
        current_time = time.time()
        wait_time = RATE_LIMIT - (current_time - last_request_time)
        if wait_time > 0:
            print(f"{timestamp()} Rate limiting: waiting {wait_time:.2f}s", flush=True)
            time.sleep(wait_time)

        last_request_time = time.time()
        yield


def _start_manual_analysis(
    *,
    session_prefix: str,
    user_input: str,
    status: str,
    status_color: str,
    analysis_fn: Callable[..., dict],
    error_label: str,
):
    global overlay

    if overlay and overlay.is_processing:
        print(f"{timestamp()} Already processing another request, ignoring {session_prefix}", flush=True)
        return

    session_id = f"{session_prefix}_{datetime.now().strftime('%H%M%S')}_{hash(user_input)}"
    if overlay:
        _mark_processing(session_id, status, status_color)

    try:
        screenshots = _collect_screenshots()
    except Exception as exc:
        print(f"{timestamp()} Error capturing screenshot: {exc}", flush=True)
        screenshots = []

    include_transcripts = bool(getattr(overlay, "use_transcriptions", True))
    print(f"{timestamp()} Starting {session_prefix} analysis", flush=True)

    def api_call_thread():
        try:
            with _with_rate_limit():
                response_json = analysis_fn(
                    user_input,
                    screenshots,
                    "jpeg",
                    include_transcripts=include_transcripts,
                )

            if not _is_current_session(session_id):
                print(f"{timestamp()} Session {session_id} was canceled, discarding result", flush=True)
                return

            _run_on_ui("update_response", response_json)
            _run_on_ui("update_status", "Listening...", "#4CAF50")
        except Exception as exc:
            print(f"{timestamp()} Error in {session_prefix} analysis: {exc}", flush=True)
            if _is_current_session(session_id):
                _run_on_ui("update_status", "Error", "#FF0000")
                _run_on_ui(
                    "update_response",
                    {"user_query": user_input, "response": f"{error_label}: {exc}"},
                )
        finally:
            if _is_current_session(session_id):
                _run_on_ui("set_processing", False)

    threading.Thread(target=api_call_thread, daemon=True).start()


def process_text_input(text_input):
    _start_manual_analysis(
        session_prefix="text",
        user_input=text_input,
        status="Processing...",
        status_color="#FFA500",
        analysis_fn=analyze_with_text_input,
        error_label="Error analyzing text input",
    )


def process_code_analysis(transcription):
    _start_manual_analysis(
        session_prefix="code",
        user_input=transcription,
        status="Analyzing code problem...",
        status_color="#00ADD8",
        analysis_fn=analyze_code_problem,
        error_label="Error in code analysis",
    )


def process_general_analysis_no_thinking(transcription):
    _start_manual_analysis(
        session_prefix="general",
        user_input=transcription,
        status="Processing...",
        status_color="#FFA500",
        analysis_fn=analyze_general_problem_no_thinking,
        error_label="Error in general analysis",
    )


def initialize_live_transcription():
    global overlay, transcription_manager

    if not overlay:
        print(f"{timestamp()} Cannot start transcription without overlay", flush=True)
        return False

    def transcription_callback(text, source_type):
        record_transcript(text, source_type)
        if overlay:
            _run_on_ui("update_transcription", text, source_type)

    def auto_answer_callback(question, answer, done, clear_previous=False):
        if not overlay:
            return
        _run_on_ui("update_interviewer_qa", question, answer, done, clear_previous)
        if AUTO_ANSWER_LATENCY_LOG:
            print(
                f"{timestamp()} latency ui.auto_answer_update queued done={done} clear={clear_previous}",
                flush=True,
            )

    transcription_manager = LiveTranscriptionManager(
        transcription_callback,
        auto_answer_callback=auto_answer_callback,
    )
    result = transcription_manager.start_transcription()
    if result:
        start_auto_answer_warmup()
    print(f"{timestamp()} Live transcription {'started' if result else 'failed to start'}", flush=True)
    return result


def stop_processing_and_clear_history():
    global overlay

    print(f"{timestamp()} Clearing answer context and stopping processing", flush=True)

    if overlay:
        if hasattr(overlay, "current_session_id"):
            overlay.current_session_id = f"canceled_{datetime.now().strftime('%H%M%S')}"
        overlay.set_processing(False)
        overlay.update_status("Listening...", "#4CAF50")
        overlay.clear_conversation_display("Ready for new queries.")

    clear_chat_history()


def cleanup_transcription():
    global transcription_manager

    if transcription_manager:
        print(f"{timestamp()} Stopping live transcription...", flush=True)
        transcription_manager.cleanup()
        transcription_manager = None


def cleanup_application():
    cleanup_transcription()
    uninitialize_windows_ole()


def quit_application():
    cleanup_transcription()

    app = QtWidgets.QApplication.instance()
    if app and not QtWidgets.QApplication.closingDown():
        app.quit()


def main():
    initialize_windows_ole()
    QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseDesktopOpenGL)

    app = QtWidgets.QApplication(sys.argv)

    try:
        from resume_context import load_cached_resume_context

        cached_resume = load_cached_resume_context()
        if cached_resume:
            print(f"{timestamp()} Loaded cached resume context: {cached_resume.filename}", flush=True)
    except Exception as exc:
        print(f"{timestamp()} Failed to load cached resume context: {exc}", flush=True)

    global overlay
    overlay = DraggableOverlay()
    overlay.show()

    overlay.text_submitted.connect(process_text_input)
    overlay.code_analysis_signal.connect(process_code_analysis)
    overlay.general_analysis_no_thinking_signal.connect(process_general_analysis_no_thinking)
    overlay.clear_history_signal.connect(stop_processing_and_clear_history)
    app.aboutToQuit.connect(cleanup_application)

    initialize_live_transcription()
    app.exec()


if __name__ == "__main__":
    main()
