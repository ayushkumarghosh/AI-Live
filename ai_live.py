import sys

# Stdio helper entry point must precede all GUI, audio and environment setup.
if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--project-guide-mcp':
    from project_guide.mcp import main as project_reader_main
    project_reader_main(sys.argv[2])
    raise SystemExit(0)

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
    shorten_analysis_answer,
)
from session_context import replace_latest_exchange_response
from azure_realtime import build_realtime_answer_instructions
from live_transcription import LiveAudioManager
from overlay import DraggableOverlay, initialize_windows_ole, uninitialize_windows_ole


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
audio_manager = None
project_guide = None

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

    print(f"{timestamp()} Starting {session_prefix} analysis", flush=True)

    def api_call_thread():
        try:
            with _with_rate_limit():
                response_json = analysis_fn(
                    user_input,
                    screenshots,
                    "jpeg",
                    include_transcripts=False,
                )

            if not _is_current_session(session_id):
                print(f"{timestamp()} Session {session_id} was canceled, discarding result", flush=True)
                return

            _run_on_ui("update_analysis_response", response_json, session_prefix)
            _run_on_ui("update_status", "Listening...", "#4CAF50")
        except Exception as exc:
            print(f"{timestamp()} Error in {session_prefix} analysis: {exc}", flush=True)
            if _is_current_session(session_id):
                _run_on_ui("update_status", "Error", "#FF0000")
                _run_on_ui(
                    "update_analysis_response",
                    {
                        "user_query": user_input,
                        "response": f"{error_label}: {exc}",
                        "_shortenable": False,
                    },
                    session_prefix,
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


def process_code_analysis(user_input):
    _start_manual_analysis(
        session_prefix="code",
        user_input=user_input,
        status="Analyzing code problem...",
        status_color="#00ADD8",
        analysis_fn=analyze_code_problem,
        error_label="Error in code analysis",
    )


def process_general_analysis_no_thinking(user_input):
    _start_manual_analysis(
        session_prefix="general",
        user_input=user_input,
        status="Processing...",
        status_color="#FFA500",
        analysis_fn=analyze_general_problem_no_thinking,
        error_label="Error in general analysis",
    )


def process_shorten_analysis(previous_answer: str, mode: str):
    """Shorten a successful Code or General analysis without changing its source context."""
    global overlay

    previous_answer = str(previous_answer or "")
    mode = str(mode or "").strip().lower()
    if mode not in {"code", "general"} or not previous_answer.strip():
        print(f"{timestamp()} Ignoring shorten request without an eligible manual answer", flush=True)
        return
    if overlay and overlay.is_processing:
        print(f"{timestamp()} Already processing another request, ignoring shorten", flush=True)
        return

    session_id = f"shorten_{datetime.now().strftime('%H%M%S')}_{hash(previous_answer)}"
    if overlay:
        _mark_processing(session_id, "Shortening answer...", "#FFA500")

    def api_call_thread():
        try:
            with _with_rate_limit():
                response_json = shorten_analysis_answer(previous_answer, mode)

            if not _is_current_session(session_id):
                print(f"{timestamp()} Session {session_id} was canceled, discarding shortened answer", flush=True)
                return

            replaced = replace_latest_exchange_response(
                mode,
                previous_answer,
                response_json.get("response", ""),
            )
            if not replaced:
                print(f"{timestamp()} No matching session answer found to replace after shortening", flush=True)
            _run_on_ui("update_shortened_analysis_response", response_json, mode)
            _run_on_ui("update_status", "Listening...", "#4CAF50")
        except Exception as exc:
            print(f"{timestamp()} Error shortening {mode} analysis: {exc}", flush=True)
            if _is_current_session(session_id):
                already_concise = isinstance(exc, ValueError) and any(
                    phrase in str(exc).lower()
                    for phrase in ("minimum length", "already too concise")
                )
                _run_on_ui(
                    "update_status",
                    "Answer already concise" if already_concise else "Could not shorten answer",
                    "#FFA500" if already_concise else "#FF0000",
                )
        finally:
            if _is_current_session(session_id):
                _run_on_ui("set_processing", False)

    threading.Thread(target=api_call_thread, daemon=True).start()


def initialize_live_audio():
    global overlay, audio_manager

    if not overlay:
        print(f"{timestamp()} Cannot start desktop audio without overlay", flush=True)
        return False

    def answer_update_callback(action, text):
        if not overlay:
            return
        _run_on_ui("apply_realtime_answer_update", action, text)
        if AUTO_ANSWER_LATENCY_LOG:
            print(
                f"{timestamp()} latency ui.realtime_answer_update queued action={action}",
                flush=True,
            )

    def session_reset_callback():
        _run_on_ui(
            "clear_realtime_answer_display",
            "Realtime session reconnected. Auto-answer context was reset.",
        )
        _run_on_ui("update_status", "Listening...", "#4CAF50")

    def status_callback(status, color):
        _run_on_ui("update_status", status, color)

    def instructions_provider():
        from resume_context import get_resume_context_section

        from project_guide.context import get_project_guide_context_section
        return build_realtime_answer_instructions(
            get_resume_context_section(), get_project_guide_context_section())

    audio_manager = LiveAudioManager(
        answer_update_callback=answer_update_callback,
        session_reset_callback=session_reset_callback,
        status_callback=status_callback,
        instructions_provider=instructions_provider,
    )
    result = audio_manager.start()
    if result:
        audio_manager.set_auto_answer_enabled(bool(overlay.show_interviewer_suggestions))
    print(f"{timestamp()} Live desktop audio {'started' if result else 'failed to start'}", flush=True)
    return result


def set_auto_answer_enabled(enabled):
    if audio_manager:
        audio_manager.set_auto_answer_enabled(enabled)


def refresh_realtime_instructions():
    if audio_manager:
        audio_manager.refresh_instructions()


def stop_processing_and_clear_history():
    global overlay, audio_manager

    print(f"{timestamp()} Clearing answer context and stopping processing", flush=True)

    if overlay:
        if hasattr(overlay, "current_session_id"):
            overlay.current_session_id = f"canceled_{datetime.now().strftime('%H%M%S')}"
        overlay.set_processing(False)
        overlay.update_status("Listening...", "#4CAF50")
        overlay.clear_conversation_display("Ready for new queries.")

    clear_chat_history()
    if project_guide:
        project_guide.clear()
    if audio_manager:
        audio_manager.reset_context()


def cleanup_audio():
    global audio_manager

    if audio_manager:
        print(f"{timestamp()} Stopping live desktop audio...", flush=True)
        audio_manager.cleanup()
        audio_manager = None


def cleanup_application():
    if project_guide:
        project_guide.close()
    cleanup_audio()
    uninitialize_windows_ole()


def quit_application():
    cleanup_audio()

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

    from project_guide.controller import ProjectGuideController
    global project_guide
    project_guide = ProjectGuideController(overlay)
    project_guide.context_changed.connect(refresh_realtime_instructions)
    overlay.project_guide_signal.connect(project_guide.show)

    overlay.text_submitted.connect(process_text_input)
    overlay.code_analysis_signal.connect(process_code_analysis)
    overlay.general_analysis_no_thinking_signal.connect(process_general_analysis_no_thinking)
    overlay.shorten_analysis_signal.connect(process_shorten_analysis)
    overlay.clear_history_signal.connect(stop_processing_and_clear_history)
    overlay.auto_answer_toggled_signal.connect(set_auto_answer_enabled)
    overlay.resume_context_changed_signal.connect(refresh_realtime_instructions)
    app.aboutToQuit.connect(cleanup_application)

    initialize_live_audio()
    app.exec()


if __name__ == "__main__":
    main()
