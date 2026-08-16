import asyncio
import base64
import json
import os
import sys
import threading
import time
from datetime import datetime
from urllib.parse import quote, urlparse

import websockets

from env_loader import load_env_file


load_env_file()

REALTIME_DEPLOYMENT = os.getenv("AZURE_OPENAI_REALTIME_DEPLOYMENT", "").strip()
ANSWER_TOOL_NAME = "update_visible_answer"
ANSWER_UPDATE_TOOL = {
    "type": "function",
    "name": ANSWER_TOOL_NAME,
    "description": (
        "Apply one completed interview-answer update to the candidate's visible answer. "
        "Use append for the same topic, reset for a genuinely new primary topic, and "
        "no_update when the interviewer turn needs no visible answer."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["append", "reset", "no_update"],
            },
            "text": {"type": "string"},
        },
        "required": ["action", "text"],
        "additionalProperties": False,
    },
}


def configure_console_encoding():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def parse_int_env(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
        if parsed <= 0:
            raise ValueError("must be positive")
        return parsed
    except ValueError:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Invalid {name}={value!r}; using {default}",
            flush=True,
        )
        return default


def parse_float_env(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
        if parsed <= 0:
            raise ValueError("must be positive")
        return parsed
    except ValueError:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Invalid {name}={value!r}; using {default}",
            flush=True,
        )
        return default


configure_console_encoding()

SAMPLE_RATE = parse_int_env("SAMPLE_RATE", 24000)
if SAMPLE_RATE != 24000:
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Azure Realtime expects 24000 Hz PCM input; "
        f"using 24000 instead of {SAMPLE_RATE}",
        flush=True,
    )
    SAMPLE_RATE = 24000

CHANNELS = parse_int_env("CHANNELS", 1)
CHUNK_SIZE = parse_int_env("CHUNK_SIZE", 1024)
VAD_SILENCE_MS = parse_int_env("AZURE_OPENAI_VAD_SILENCE_MS", 350)
VAD_PREFIX_PADDING_MS = parse_int_env("AZURE_OPENAI_VAD_PREFIX_PADDING_MS", 300)
VAD_THRESHOLD = parse_float_env("AZURE_OPENAI_VAD_THRESHOLD", 0.5)
LATENCY_LOG_ENABLED = os.getenv("AUTO_ANSWER_LATENCY_LOG", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def timestamp():
    return f"[{datetime.now().strftime('%H:%M:%S')}]"


def latency_log(event, start_at=None, **fields):
    if not LATENCY_LOG_ENABLED:
        return
    elapsed = ""
    if start_at is not None:
        elapsed = f" +{(time.perf_counter() - start_at) * 1000:.0f}ms"
    details = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    if details:
        details = f" {details}"
    print(f"{timestamp()} latency realtime_answer.{event}{elapsed}{details}", flush=True)


def _required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to .env or your environment.")
    return value


def _realtime_url(deployment, endpoint=None):
    endpoint = (endpoint or _required_env("AZURE_OPENAI_REALTIME_ENDPOINT")).rstrip("/")
    parsed = urlparse(endpoint)
    host = parsed.netloc or parsed.path
    if not host:
        raise RuntimeError("AZURE_OPENAI_REALTIME_ENDPOINT is not a valid Azure endpoint.")
    return f"wss://{host}/openai/v1/realtime?model={quote(deployment)}"


def _format_websocket_error(exc):
    response = getattr(exc, "response", None)
    if not response:
        return str(exc)

    body = getattr(response, "body", "") or ""
    if isinstance(body, bytearray):
        body = bytes(body)
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    else:
        body = str(body)

    status = getattr(response, "status_code", None) or getattr(response, "status", None)
    body = body.strip()
    return f"{exc}; status={status}; body={body}" if body else f"{exc}; status={status}"


async def _connect_websocket(url, api_key):
    headers = [("api-key", api_key)]
    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, max_size=None)


def build_realtime_answer_instructions(resume_section=""):
    instructions = """
You are a realtime interview answer assistant for a software engineering candidate.
You hear only the interviewer's desktop audio. Understand the audio directly and decide
whether the candidate's currently visible answer should be extended, replaced, or left alone.

You must finish every response by calling update_visible_answer exactly once. Do not emit
free-form assistant text outside that function call.

Action rules:
- Use reset for the first answer and when the interviewer starts a genuinely new primary
  question or topic. The text must contain a complete answer to that new question.
- Use append when the interviewer asks a follow-up, adds a constraint, requests more detail,
  clarifies the same question, or corrects something within the same topic. The text must
  contain only the new continuation. Never repeat or regenerate the existing visible answer.
- For a same-topic correction, append a natural correction such as "More precisely, ...".
- Use no_update with an empty text value for acknowledgements, filler, incomplete speech,
  or turns that do not require the candidate to say anything new.

The successful update_visible_answer calls earlier in this conversation represent the answer
already visible to the candidate. Continue from those calls instead of replying to or restating
them. Keep answers concise, accurate, practical, and ready to say aloud. Write like an Indian
software engineer speaking naturally in an interview: direct, conversational Indian English,
first person where useful, and technically specific without sounding scripted or like an AI.
Do not force slang, Hinglish, filler words, or accent-like spelling.

Use resume details only for questions about the candidate's experience, projects, background,
skills, strengths, or achievements, or when a personalised example is clearly useful. Never
invent resume details.
""".strip()
    resume_section = str(resume_section or "").strip()
    if resume_section:
        instructions += f"\n\n{resume_section}"
    return instructions


def validate_answer_update(arguments):
    if isinstance(arguments, str):
        try:
            payload = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc.msg}") from exc
    else:
        payload = arguments

    if not isinstance(payload, dict):
        raise ValueError("arguments must be a JSON object")
    if set(payload) != {"action", "text"}:
        raise ValueError("arguments must contain only action and text")

    action = payload.get("action")
    text = payload.get("text")
    if action not in {"append", "reset", "no_update"}:
        raise ValueError(f"unknown action {action!r}")
    if not isinstance(text, str):
        raise ValueError("text must be a string")

    text = text.strip()
    if action in {"append", "reset"} and not text:
        raise ValueError(f"{action} requires non-empty text")
    if action == "no_update" and text:
        raise ValueError("no_update requires empty text")
    return action, text


class AzureRealtimeAnswerSession:
    def __init__(
        self,
        answer_update_callback=None,
        session_reset_callback=None,
        status_callback=None,
        instructions_provider=None,
        sample_rate=SAMPLE_RATE,
        chunk_size=CHUNK_SIZE,
    ):
        self.answer_update_callback = answer_update_callback
        self.session_reset_callback = session_reset_callback
        self.status_callback = status_callback
        self.instructions_provider = instructions_provider
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size

        self.running = False
        self.auto_answer_enabled = False
        self.loop = None
        self.websocket = None
        self.audio_queue = None
        self.tasks = []
        self._thread = None
        self._send_lock = None
        self._error_retries = 0
        self._connected_once = False
        self._intentional_reset = False
        self._last_audio_enqueue_at = None

        self._turn_counter = 0
        self._current_turn_token = None
        self._active_response_id = None
        self._response_turns = {}
        self._ignored_turns = set()
        self._call_arguments = {}
        self._protocol_errors = {}
        self._committed_responses = set()
        self._retry_counts = {}

        try:
            self.api_key = _required_env("AZURE_OPENAI_REALTIME_API_KEY")
            self.realtime_deployment = _required_env("AZURE_OPENAI_REALTIME_DEPLOYMENT")
            self.url = _realtime_url(self.realtime_deployment)
        except RuntimeError as exc:
            print(f"{timestamp()} {exc}", flush=True)
            self.api_key = None
            self.realtime_deployment = REALTIME_DEPLOYMENT
            self.url = None

    def _instructions(self):
        if self.instructions_provider:
            try:
                return str(self.instructions_provider() or build_realtime_answer_instructions())
            except Exception as exc:
                print(f"{timestamp()} Could not load realtime answer instructions: {exc}", flush=True)
        return build_realtime_answer_instructions()

    async def _send_event(self, event):
        websocket = self.websocket
        if websocket is None:
            return False
        payload = json.dumps(event)
        if self._send_lock is None:
            await websocket.send(payload)
        else:
            async with self._send_lock:
                await websocket.send(payload)
        return True

    def _session_update_event(self):
        return {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": self.realtime_deployment,
                "output_modalities": ["text"],
                "instructions": self._instructions(),
                "max_output_tokens": 2048,
                "parallel_tool_calls": False,
                "tools": [ANSWER_UPDATE_TOOL],
                "tool_choice": {"type": "function", "name": ANSWER_TOOL_NAME},
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": self.sample_rate},
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": VAD_THRESHOLD,
                            "prefix_padding_ms": VAD_PREFIX_PADDING_MS,
                            "silence_duration_ms": VAD_SILENCE_MS,
                            "create_response": False,
                            "interrupt_response": False,
                        },
                    }
                },
            },
        }

    async def configure_session(self):
        await self._send_event(self._session_update_event())

    def _response_create_event(self, turn_token, attempt):
        return {
            "type": "response.create",
            "response": {
                "conversation": "auto",
                "output_modalities": ["text"],
                "instructions": self._instructions(),
                "max_output_tokens": 2048,
                "parallel_tool_calls": False,
                "tools": [ANSWER_UPDATE_TOOL],
                "tool_choice": {"type": "function", "name": ANSWER_TOOL_NAME},
                "metadata": {
                    "client_turn_id": turn_token,
                    "attempt": str(attempt),
                },
            },
        }

    async def _create_response(self, turn_token):
        if not self.auto_answer_enabled or turn_token in self._ignored_turns:
            return
        await self.configure_session()
        attempt = self._retry_counts.get(turn_token, 0)
        await self._send_event(self._response_create_event(turn_token, attempt))
        latency_log("response_requested", self._last_audio_enqueue_at, turn=turn_token, attempt=attempt)
        if self.status_callback:
            self.status_callback("Answering...", "#FFA500")

    async def _cancel_current_response(self):
        turn_token = self._current_turn_token
        if turn_token:
            self._ignored_turns.add(turn_token)
        response_id = self._active_response_id
        if response_id or turn_token:
            event = {"type": "response.cancel"}
            if response_id:
                event["response_id"] = response_id
            await self._send_event(event)
            latency_log("response_cancelled", turn=turn_token, response_id=response_id)
        self._current_turn_token = None
        self._active_response_id = None

    async def _send_function_output(self, call_id, output):
        if not call_id:
            return
        await self._send_event(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(output),
                },
            }
        )

    def _turn_for_response(self, response_id, response=None):
        turn_token = self._response_turns.get(response_id)
        if turn_token:
            return turn_token
        metadata = (response or {}).get("metadata") or {}
        turn_token = metadata.get("client_turn_id")
        if turn_token and response_id:
            self._response_turns[response_id] = turn_token
        return turn_token

    async def _handle_response_created(self, event):
        response = event.get("response") or {}
        response_id = response.get("id") or event.get("response_id")
        turn_token = self._turn_for_response(response_id, response) or self._current_turn_token
        if response_id and turn_token:
            self._response_turns[response_id] = turn_token
        if turn_token in self._ignored_turns:
            if response_id:
                await self._send_event({"type": "response.cancel", "response_id": response_id})
            return
        self._active_response_id = response_id

    async def _handle_function_done(self, event):
        response_id = event.get("response_id")
        turn_token = self._turn_for_response(response_id)
        call_id = event.get("call_id", "")
        if not turn_token or turn_token in self._ignored_turns or turn_token != self._current_turn_token:
            return
        if response_id in self._committed_responses:
            return

        arguments = event.get("arguments")
        if not arguments:
            arguments = self._call_arguments.get(call_id, "")

        try:
            if event.get("name") != ANSWER_TOOL_NAME:
                raise ValueError(f"unexpected function {event.get('name')!r}")
            action, text = validate_answer_update(arguments)
        except ValueError as exc:
            message = str(exc)
            self._protocol_errors[response_id] = message
            print(f"{timestamp()} Invalid realtime answer update: {message}", flush=True)
            await self._send_function_output(
                call_id,
                {
                    "status": "error",
                    "error": message,
                    "instruction": "Call update_visible_answer once with valid action and text arguments.",
                },
            )
            return

        if self.answer_update_callback:
            self.answer_update_callback(action, text)
        await self._send_function_output(call_id, {"status": "applied", "action": action})
        self._committed_responses.add(response_id)
        latency_log("answer_committed", response_id=response_id, action=action, chars=len(text))
        if self.status_callback:
            self.status_callback("Listening...", "#4CAF50")

    async def _handle_response_done(self, event):
        response = event.get("response") or {}
        response_id = response.get("id") or event.get("response_id")
        turn_token = self._turn_for_response(response_id, response)
        status = response.get("status", "")
        ignored = not turn_token or turn_token in self._ignored_turns
        committed = response_id in self._committed_responses
        protocol_error = self._protocol_errors.pop(response_id, "")

        if not ignored and status == "completed" and not committed and not protocol_error:
            protocol_error = "response completed without update_visible_answer"
            print(f"{timestamp()} Invalid realtime answer response: {protocol_error}", flush=True)

        if (
            not ignored
            and protocol_error
            and turn_token == self._current_turn_token
            and self.auto_answer_enabled
        ):
            attempts = self._retry_counts.get(turn_token, 0)
            if attempts < 1:
                self._retry_counts[turn_token] = attempts + 1
                self._active_response_id = None
                print(f"{timestamp()} Retrying realtime answer after protocol error", flush=True)
                await self._create_response(turn_token)
                return
            print(f"{timestamp()} Realtime answer retry failed; keeping the visible answer unchanged", flush=True)
            if self.status_callback:
                self.status_callback("Answer unavailable", "#FF0000")

        if turn_token == self._current_turn_token:
            self._current_turn_token = None
        if response_id == self._active_response_id:
            self._active_response_id = None

        self._response_turns.pop(response_id, None)
        self._committed_responses.discard(response_id)
        if turn_token:
            self._retry_counts.pop(turn_token, None)
            self._ignored_turns.discard(turn_token)

    async def handle_server_event(self, event):
        event_type = event.get("type", "")

        if event_type == "input_audio_buffer.speech_started":
            await self._cancel_current_response()
            if self.status_callback:
                self.status_callback("Listening...", "#4CAF50")
            return

        if event_type == "input_audio_buffer.speech_stopped":
            if self.auto_answer_enabled:
                self._turn_counter += 1
                self._current_turn_token = f"turn-{self._turn_counter}"
                self._retry_counts[self._current_turn_token] = 0
                await self._create_response(self._current_turn_token)
            return

        if event_type == "response.created":
            await self._handle_response_created(event)
            return

        if event_type == "response.function_call_arguments.delta":
            response_id = event.get("response_id")
            turn_token = self._turn_for_response(response_id)
            if turn_token and turn_token not in self._ignored_turns:
                call_id = event.get("call_id", "")
                self._call_arguments[call_id] = self._call_arguments.get(call_id, "") + event.get("delta", "")
            return

        if event_type == "response.function_call_arguments.done":
            await self._handle_function_done(event)
            return

        if event_type in {"response.output_text.delta", "response.output_text.done"}:
            response_id = event.get("response_id")
            turn_token = self._turn_for_response(response_id)
            if turn_token and turn_token not in self._ignored_turns:
                self._protocol_errors[response_id] = "unexpected free-form text output"
            return

        if event_type == "response.done":
            await self._handle_response_done(event)
            return

        if event_type == "error":
            print(f"{timestamp()} Azure Realtime error: {event.get('error', {})}", flush=True)

    async def send_audio_to_azure(self):
        while self.running:
            audio_chunk = await self.audio_queue.get()
            try:
                await self._send_event(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(audio_chunk).decode("ascii"),
                    }
                )
            finally:
                self.audio_queue.task_done()

    async def process_responses(self):
        async for raw_message in self.websocket:
            await self.handle_server_event(json.loads(raw_message))

    def _clear_response_state(self):
        self._current_turn_token = None
        self._active_response_id = None
        self._response_turns.clear()
        self._ignored_turns.clear()
        self._call_arguments.clear()
        self._protocol_errors.clear()
        self._committed_responses.clear()
        self._retry_counts.clear()

    def _discard_queued_audio(self):
        if self.audio_queue is None:
            return
        while True:
            try:
                self.audio_queue.get_nowait()
                self.audio_queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def _run_connection(self):
        send_task = asyncio.create_task(self.send_audio_to_azure())
        process_task = asyncio.create_task(self.process_responses())
        self.tasks = [send_task, process_task]
        done, pending = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            if task.cancelled():
                continue
            exception = task.exception()
            if exception:
                raise exception

    async def run(self):
        if not self.api_key or not self.url:
            print(f"{timestamp()} Cannot start Azure Realtime answering without credentials", flush=True)
            return

        self.audio_queue = asyncio.Queue(maxsize=100)
        self._send_lock = asyncio.Lock()
        while self.running:
            try:
                was_reconnect = self._connected_once
                intentional_reconnect = self._intentional_reset
                self.websocket = await _connect_websocket(self.url, self.api_key)
                self._clear_response_state()
                self._discard_queued_audio()
                await self.configure_session()
                self._error_retries = 0
                self._connected_once = True
                self._intentional_reset = False
                print(
                    f"{timestamp()} Azure desktop Realtime answer session started "
                    f"with deployment {self.realtime_deployment!r}",
                    flush=True,
                )
                if was_reconnect and not intentional_reconnect and self.session_reset_callback:
                    self.session_reset_callback()
                await self._run_connection()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self.running:
                    print(
                        f"{timestamp()} Azure Realtime answer session error for deployment "
                        f"{self.realtime_deployment!r}: {_format_websocket_error(exc)}",
                        flush=True,
                    )
                    if not self._intentional_reset:
                        self._error_retries += 1
            finally:
                for task in self.tasks:
                    if not task.done():
                        task.cancel()
                if self.websocket:
                    try:
                        await self.websocket.close()
                    except Exception:
                        pass
                self.websocket = None
                print(f"{timestamp()} Azure desktop Realtime answer session closed", flush=True)

            if not self.running:
                break
            if not self._intentional_reset and self._error_retries > 3:
                print(f"{timestamp()} Azure Realtime reconnect limit reached", flush=True)
                break
            await asyncio.sleep(1)

        self.running = False

    def add_audio_chunk(self, audio_chunk):
        if not (self.loop and self.running and self.audio_queue) or self.loop.is_closed():
            return
        self._last_audio_enqueue_at = time.perf_counter()

        def enqueue():
            try:
                self.audio_queue.put_nowait(audio_chunk)
            except asyncio.QueueFull:
                pass

        try:
            self.loop.call_soon_threadsafe(enqueue)
        except RuntimeError:
            pass

    def start(self):
        if not self.api_key or not self.url:
            print(
                f"{timestamp()} Cannot start Azure Realtime answering. Set "
                "AZURE_OPENAI_REALTIME_API_KEY, AZURE_OPENAI_REALTIME_ENDPOINT, and "
                "AZURE_OPENAI_REALTIME_DEPLOYMENT.",
                flush=True,
            )
            return False
        if self.running:
            return True

        print(
            f"{timestamp()} Azure desktop Realtime config: chunk_size={self.chunk_size} "
            f"vad_silence_ms={VAD_SILENCE_MS} vad_threshold={VAD_THRESHOLD} "
            f"vad_prefix_padding_ms={VAD_PREFIX_PADDING_MS}",
            flush=True,
        )
        self.running = True

        def run_async_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self.run())
            finally:
                self.loop.close()

        self._thread = threading.Thread(target=run_async_loop, daemon=True)
        self._thread.start()
        return True

    def set_auto_answer_enabled(self, enabled):
        self.auto_answer_enabled = bool(enabled)
        if not self.auto_answer_enabled and self.loop and not self.loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(self._cancel_current_response(), self.loop)
            except RuntimeError:
                pass
        if not self.auto_answer_enabled and self.status_callback:
            self.status_callback("Listening...", "#4CAF50")

    def refresh_instructions(self):
        if self.loop and self.running and not self.loop.is_closed() and self.websocket:
            try:
                asyncio.run_coroutine_threadsafe(self.configure_session(), self.loop)
            except RuntimeError:
                pass

    async def _reset_connection(self):
        self._clear_response_state()
        self._discard_queued_audio()
        if self.websocket:
            await self.websocket.close()

    def reset_context(self):
        self._intentional_reset = True
        if self.loop and self.running and not self.loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(self._reset_connection(), self.loop)
            except RuntimeError:
                pass

    def stop(self):
        self.running = False
        if self.loop and not self.loop.is_closed() and self.websocket:
            try:
                asyncio.run_coroutine_threadsafe(self.websocket.close(), self.loop)
            except RuntimeError:
                pass
        print(f"{timestamp()} Azure desktop Realtime answer session stopped", flush=True)

    def cleanup(self):
        self.stop()
        print(f"{timestamp()} Azure desktop Realtime answer session cleaned up", flush=True)
