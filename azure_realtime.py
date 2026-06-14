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

REALTIME_DEPLOYMENT = os.getenv(
    "AZURE_OPENAI_REALTIME_DEPLOYMENT",
    os.getenv("AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT", "gpt-realtime-whisper"),
)
TRANSCRIPTION_MODEL = os.getenv("AZURE_OPENAI_TRANSCRIPTION_MODEL") or (
    REALTIME_DEPLOYMENT if "transcribe" in REALTIME_DEPLOYMENT else "whisper-1"
)


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
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Invalid {name}={value!r}; using {default}", flush=True)
        return default


configure_console_encoding()

SAMPLE_RATE = parse_int_env("SAMPLE_RATE", 24000)
if SAMPLE_RATE != 24000:
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Azure realtime transcription expects 24000 Hz PCM input; "
        f"using 24000 instead of {SAMPLE_RATE}",
        flush=True,
    )
    SAMPLE_RATE = 24000
CHANNELS = parse_int_env("CHANNELS", 1)
CHUNK_SIZE = parse_int_env("CHUNK_SIZE", 1024)
VAD_SILENCE_MS = parse_int_env("AZURE_OPENAI_VAD_SILENCE_MS", 350)
VAD_PREFIX_PADDING_MS = parse_int_env("AZURE_OPENAI_VAD_PREFIX_PADDING_MS", 300)
LATENCY_LOG_ENABLED = os.getenv("AUTO_ANSWER_LATENCY_LOG", "false").strip().lower() in {"1", "true", "yes", "on"}


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
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Invalid {name}={value!r}; using {default}", flush=True)
        return default


VAD_THRESHOLD = parse_float_env("AZURE_OPENAI_VAD_THRESHOLD", 0.5)


def latency_log(source_type, event, start_at=None, **fields):
    if not LATENCY_LOG_ENABLED:
        return

    elapsed = ""
    if start_at:
        elapsed = f" +{(time.perf_counter() - start_at) * 1000:.0f}ms"
    details = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    if details:
        details = f" {details}"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] latency {source_type}.{event}{elapsed}{details}", flush=True)


def _required_env(name, fallback_name=None):
    value = os.getenv(name, "").strip()
    if not value and fallback_name:
        value = os.getenv(fallback_name, "").strip()
    if not value:
        if fallback_name:
            raise RuntimeError(
                f"{name} is not set, and fallback {fallback_name} is not set. "
                "Add one of them to .env or your environment."
            )
        raise RuntimeError(f"{name} is not set. Add it to .env or your environment.")
    return value


def _realtime_url(deployment):
    endpoint = _required_env("AZURE_OPENAI_TRANSCRIPTION_ENDPOINT", "AZURE_OPENAI_ENDPOINT").rstrip("/")
    parsed = urlparse(endpoint)
    host = parsed.netloc or parsed.path
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
    if body:
        return f"{exc}; status={status}; body={body}"
    return f"{exc}; status={status}"


async def _connect_websocket(url, api_key):
    headers = [("api-key", api_key)]
    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, max_size=None)


class AudioStreamer:
    def __init__(
        self,
        transcription_callback=None,
        sample_rate=SAMPLE_RATE,
        chunk_size=CHUNK_SIZE,
        source_type="mic",
        session_handle=None,
    ):
        self.stream = None
        self.audio_queue = None
        self.transcription_callback = transcription_callback
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.running = False
        self.loop = None
        self.websocket = None
        self.tasks = []
        self.source_type = source_type
        self.session_handle = session_handle
        self._error_retries = 0
        self._first_audio_enqueue_at = None
        self._last_audio_enqueue_at = None

        try:
            self.api_key = _required_env("AZURE_OPENAI_TRANSCRIPTION_API_KEY", "AZURE_OPENAI_API_KEY")
            self.realtime_deployment = REALTIME_DEPLOYMENT
            self.transcription_model = TRANSCRIPTION_MODEL
            self.url = _realtime_url(self.realtime_deployment)
        except RuntimeError as exc:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {exc}", flush=True)
            self.api_key = None
            self.realtime_deployment = REALTIME_DEPLOYMENT
            self.transcription_model = TRANSCRIPTION_MODEL
            self.url = None

    async def capture_audio(self, external_stream=None):
        if external_stream:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Using external audio stream", flush=True)
            while self.running:
                try:
                    data = await asyncio.to_thread(
                        external_stream.read,
                        self.chunk_size,
                        exception_on_overflow=False,
                    )
                    if self.audio_queue:
                        await self.audio_queue.put(data)
                    await asyncio.sleep(0.01)
                except Exception as exc:
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] Error capturing {self.source_type} audio: {exc}",
                        flush=True,
                    )
                    await asyncio.sleep(0.1)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for audio to be fed via add_audio_chunk", flush=True)
            while self.running:
                await asyncio.sleep(0.1)

    async def configure_session(self):
        session_update = {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": self.sample_rate},
                        "transcription": {
                            "model": self.transcription_model,
                            "language": "en",
                            "prompt": "Transcribe and transliterate speech to English.",
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": VAD_THRESHOLD,
                            "prefix_padding_ms": VAD_PREFIX_PADDING_MS,
                            "silence_duration_ms": VAD_SILENCE_MS,
                            "create_response": False,
                        },
                    },
                },
            },
        }
        await self.websocket.send(json.dumps(session_update))

    async def send_audio_to_azure(self):
        while self.running:
            try:
                audio_chunk = await self.audio_queue.get()
                if self.websocket:
                    await self.websocket.send(
                        json.dumps(
                            {
                                "type": "input_audio_buffer.append",
                                "audio": base64.b64encode(audio_chunk).decode("ascii"),
                            }
                        )
                    )
                self.audio_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Error sending {self.source_type} audio to Azure: {exc}",
                    flush=True,
                )
                await asyncio.sleep(0.1)

    async def process_responses(self):
        partials = {}
        timings = {}
        while self.running:
            try:
                async for raw_message in self.websocket:
                    event = json.loads(raw_message)
                    event_type = event.get("type", "")
                    item_id = event.get("item_id") or event.get("id") or "default"

                    if event_type == "conversation.item.input_audio_transcription.delta":
                        if item_id not in timings:
                            timings[item_id] = {
                                "first_delta_at": time.perf_counter(),
                                "last_audio_enqueue_at": self._last_audio_enqueue_at,
                            }
                            latency_log(
                                self.source_type,
                                "first_transcript_delta",
                                self._last_audio_enqueue_at,
                                item_id=item_id,
                            )
                        partials[item_id] = partials.get(item_id, "") + event.get("delta", "")
                        continue

                    if event_type == "conversation.item.input_audio_transcription.completed":
                        transcript = event.get("transcript") or partials.pop(item_id, "")
                        transcript = transcript.strip()
                        timing = timings.pop(item_id, {})
                        completed_at = time.perf_counter()
                        timing["completed_at"] = completed_at
                        latency_log(
                            self.source_type,
                            "transcription_completed",
                            timing.get("first_delta_at") or timing.get("last_audio_enqueue_at"),
                            item_id=item_id,
                            chars=len(transcript),
                        )
                        if self.transcription_callback and transcript:
                            self.transcription_callback(
                                {
                                    "transcription": transcript,
                                    "completed": True,
                                    "item_id": item_id,
                                    "timing": timing,
                                },
                                self.source_type,
                            )
                        continue

                    if event_type == "error":
                        error = event.get("error", {})
                        print(
                            f"[{datetime.now().strftime('%H:%M:%S')}] Azure realtime error for "
                            f"{self.source_type}: {error}",
                            flush=True,
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Error processing {self.source_type} Azure response: {exc}",
                    flush=True,
                )
                self._error_retries += 1
                if self._error_retries <= 3:
                    for task in self.tasks:
                        if task is not asyncio.current_task():
                            task.cancel()
                    return
                self.running = False
                return

    def add_audio_chunk(self, audio_chunk):
        if not (self.loop and self.running and self.audio_queue) or self.loop.is_closed():
            return

        enqueued_at = time.perf_counter()
        self._last_audio_enqueue_at = enqueued_at
        if self._first_audio_enqueue_at is None:
            self._first_audio_enqueue_at = enqueued_at
            latency_log(self.source_type, "first_audio_enqueue")

        def enqueue():
            try:
                self.audio_queue.put_nowait(audio_chunk)
            except asyncio.QueueFull:
                pass

        try:
            self.loop.call_soon_threadsafe(enqueue)
        except RuntimeError:
            pass

    async def run(self, external_stream=None):
        if not self.api_key or not self.url:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Cannot start Azure realtime transcription without credentials", flush=True)
            return

        self.audio_queue = asyncio.Queue(maxsize=100)
        while self.running:
            try:
                self.websocket = await _connect_websocket(self.url, self.api_key)
                await self.configure_session()
                self._error_retries = 0
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Azure {self.source_type} transcription session started",
                    flush=True,
                )

                capture_task = asyncio.create_task(self.capture_audio(external_stream))
                send_task = asyncio.create_task(self.send_audio_to_azure())
                process_task = asyncio.create_task(self.process_responses())
                self.tasks = [capture_task, send_task, process_task]

                await asyncio.gather(*self.tasks)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Error in {self.source_type} Azure transcriber "
                    f"for realtime deployment {self.realtime_deployment!r}: {_format_websocket_error(exc)}",
                    flush=True,
                )
                self._error_retries += 1
                if self._error_retries > 3:
                    self.running = False
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
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] {self.source_type.capitalize()} Azure session closed",
                    flush=True,
                )

            if self.running and self._error_retries <= 3:
                await asyncio.sleep(1)
                continue
            break

    def start(self, external_stream=None):
        if not self.api_key:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Cannot start Azure realtime transcription. "
                "Set AZURE_OPENAI_TRANSCRIPTION_API_KEY and AZURE_OPENAI_TRANSCRIPTION_ENDPOINT.",
                flush=True,
            )
            return False

        def run_async_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.running = True
            self.loop.run_until_complete(self.run(external_stream))

        thread = threading.Thread(target=run_async_loop, daemon=True)
        thread.start()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Azure {self.source_type} transcriber started", flush=True)
        return True

    def stop(self):
        self.running = False
        if self.loop:
            for task in self.tasks:
                if not task.done():
                    task.cancel()
            if self.websocket:
                try:
                    asyncio.run_coroutine_threadsafe(self.websocket.close(), self.loop)
                except Exception:
                    pass

        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.source_type.capitalize()} Azure transcriber stopped", flush=True)

    def cleanup(self):
        self.stop()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.source_type.capitalize()} Azure transcriber cleaned up", flush=True)
