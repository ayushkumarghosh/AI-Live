import threading
import queue
import time
import sys
import collections.abc
from datetime import datetime
import numpy as np

_numpy_fromstring = np.fromstring


def _fromstring_compat(data, dtype=float, count=-1, sep="", **kwargs):
    if sep == "":
        try:
            return np.frombuffer(data, dtype=dtype, count=count if count >= 0 else -1).copy()
        except TypeError:
            pass
    return _numpy_fromstring(data, dtype=dtype, count=count, sep=sep, **kwargs)


np.fromstring = _fromstring_compat

import soundcard as sc
import soundcard.mediafoundation as _sc_mediafoundation
import warnings
from azure_realtime import AudioStreamer
from azure_realtime import CHUNK_SIZE as AZURE_CHUNK_SIZE
from azure_realtime import LATENCY_LOG_ENABLED as AUTO_ANSWER_LATENCY_LOG
from azure_realtime import SAMPLE_RATE as AZURE_SAMPLE_RATE
from chat import generate_auto_answer

try:
    import pyaudio
except ImportError:
    pyaudio = None

# Filter out SoundcardRuntimeWarning about data discontinuity
warnings.filterwarnings("ignore", message="data discontinuity in recording", category=sc.mediafoundation.SoundcardRuntimeWarning)


def _patch_soundcard_waveformatex_recorder():
    if not sys.platform.startswith("win"):
        return

    try:
        recorder_cls = _sc_mediafoundation._Recorder
        original_init = recorder_cls.__init__
        if getattr(original_init, "_ai_live_waveformatex_patch", False):
            return

        ffi = _sc_mediafoundation._ffi
        com = _sc_mediafoundation._com
        ole32 = _sc_mediafoundation._ole32

        def patched_init(self, ptr, samplerate, channels, blocksize, isloopback, exclusive_mode=False):
            self._ptr = ptr

            if isinstance(channels, int):
                self.channelmap = list(range(channels))
            elif isinstance(channels, collections.abc.Iterable):
                self.channelmap = channels
            else:
                raise TypeError("channels must be iterable or integer")

            if list(range(len(set(self.channelmap)))) != sorted(list(set(self.channelmap))):
                raise TypeError(
                    "Due to limitations of WASAPI, channel maps on Windows "
                    "must be a combination of `range(0, x)`."
                )

            if blocksize is None:
                blocksize = self.deviceperiod[0] * samplerate

            pp_mix_format = ffi.new("WAVEFORMATEXTENSIBLE**")
            hr = self._ptr[0][0].lpVtbl.GetMixFormat(self._ptr[0], pp_mix_format)
            com.check_error(hr)

            fmt = pp_mix_format[0][0].Format
            is_extensible_float = (
                fmt.wFormatTag == 0xFFFE
                and fmt.cbSize == 22
                and pp_mix_format[0][0].SubFormat.Data1 == 0x100000
                and pp_mix_format[0][0].SubFormat.Data2 == 0x0080
                and pp_mix_format[0][0].SubFormat.Data3 == 0xAA00
                and [int(x) for x in pp_mix_format[0][0].SubFormat.Data4[0:4]]
                == [0, 56, 155, 113]
            )
            is_waveformatex_float = fmt.wFormatTag == 3 and fmt.cbSize == 0 and fmt.wBitsPerSample == 32
            if not (is_extensible_float or is_waveformatex_float):
                format_details = f"tag={fmt.wFormatTag} cbSize={fmt.cbSize} bits={fmt.wBitsPerSample}"
                ole32.CoTaskMemFree(pp_mix_format[0])
                raise AssertionError(
                    f"Unsupported WASAPI microphone mix format: {format_details}"
                )

            channels = len(set(self.channelmap))
            fmt.nChannels = channels
            fmt.nSamplesPerSec = int(samplerate)
            fmt.nAvgBytesPerSec = int(samplerate) * channels * 4
            fmt.nBlockAlign = channels * 4
            fmt.wBitsPerSample = 32
            if is_extensible_float:
                pp_mix_format[0][0].Samples = dict(wValidBitsPerSample=32)

            sharemode = (
                ole32.AUDCLNT_SHAREMODE_EXCLUSIVE
                if exclusive_mode
                else ole32.AUDCLNT_SHAREMODE_SHARED
            )
            streamflags = 0x00100000 | 0x80000000 | 0x08000000 | 0x00080000
            if isloopback:
                streamflags |= 0x00020000
            bufferduration = int(blocksize / samplerate * 10000000)

            try:
                hr = self._ptr[0][0].lpVtbl.Initialize(
                    self._ptr[0],
                    sharemode,
                    streamflags,
                    bufferduration,
                    0,
                    pp_mix_format[0],
                    ffi.NULL,
                )
                com.check_error(hr)
            finally:
                ole32.CoTaskMemFree(pp_mix_format[0])

            self.samplerate = samplerate
            self._idle_start_time = None

        patched_init._ai_live_waveformatex_patch = True
        patched_init._ai_live_original_init = original_init
        recorder_cls.__init__ = patched_init
    except Exception as exc:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Could not apply soundcard microphone compatibility patch: {exc}",
            flush=True,
        )


_patch_soundcard_waveformatex_recorder()

# Audio parameters
FORMAT = pyaudio.paInt16 if pyaudio else None
RATE = AZURE_SAMPLE_RATE
CHUNK = AZURE_CHUNK_SIZE


def latency_log(event, start_at=None, **fields):
    if not AUTO_ANSWER_LATENCY_LOG:
        return

    elapsed = ""
    if start_at is not None:
        elapsed = f" +{(time.perf_counter() - start_at) * 1000:.0f}ms"
    details = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    if details:
        details = f" {details}"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] latency live_transcription.{event}{elapsed}{details}", flush=True)


def _source_name(source):
    return getattr(source, "name", "Unknown audio device")


def _float_audio_to_pcm16_bytes(audio_data):
    if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
        audio_data = np.mean(audio_data, axis=1)

    audio_data = np.asarray(audio_data, dtype=np.float32).flatten()
    audio_data = np.clip(audio_data, -1.0, 1.0)
    return (audio_data * 32767).astype(np.int16).tobytes()

class LiveTranscriptionManager:
    def __init__(self, transcription_callback=None, auto_answer_callback=None):
        """
        Initialize the transcription manager
        
        Args:
            transcription_callback: Function to call with transcription results (text, source_type)
        """
        self.transcription_callback = transcription_callback
        self.auto_answer_callback = auto_answer_callback
        
        # Create separate streamers for mic and desktop
        self.mic_streamer = None
        self.desktop_streamer = None
        
        # Store the last desktop transcription and suggested answer
        self.last_desktop_query = ""
        self.last_desktop_answer = ""
        self.last_desktop_turn_id = ""
        self._state_lock = threading.RLock()
        
        # Create flags to control audio capture
        self.mic_capture_running = False
        self.desktop_capture_running = False
        
        # Create audio queues
        self.mic_audio_queue = queue.Queue()
        self.desktop_audio_queue = queue.Queue()
        
    def start_transcription(self):
        """Start both microphone and desktop audio transcription"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting live transcription services", flush=True)
        
        # Start mic transcription
        self.start_mic_transcription()
        
        # Start desktop audio capture and transcription
        self.start_desktop_transcription()
        
        return True
        
    def start_mic_transcription(self):
        """Start microphone transcription"""
        if self.mic_streamer is None:
            # Create mic audio streamer with a custom callback to process data
            def mic_callback(response_data, source_type):
                # For mic, we only need the transcription text
                text = response_data.get("transcription", "")
                if text:
                    # Call the original callback with just the text
                    if self.transcription_callback:
                        self.transcription_callback(text, source_type)
            
            self.mic_streamer = AudioStreamer(
                transcription_callback=mic_callback,
                sample_rate=RATE,
                chunk_size=CHUNK,
                source_type="mic"
            )

            if not self.mic_streamer.start():
                self.mic_streamer = None
                return False
            
            # Start microphone capture in a separate thread
            self.mic_capture_running = True
            mic_thread = threading.Thread(
                target=self.capture_mic_audio,
                daemon=True
            )
            mic_thread.start()

            return True
        return False

    def _microphone_candidates(self):
        candidates = []
        seen_ids = set()

        def add_candidate(mic):
            if mic is None or getattr(mic, "isloopback", False):
                return
            mic_id = getattr(mic, "id", None) or _source_name(mic)
            if mic_id in seen_ids:
                return
            seen_ids.add(mic_id)
            candidates.append(mic)

        try:
            add_candidate(sc.default_microphone())
        except Exception as exc:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Could not read default microphone: {exc}", flush=True)

        try:
            for mic in sc.all_microphones(include_loopback=False):
                add_candidate(mic)
        except Exception as exc:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Could not enumerate microphones: {exc}", flush=True)

        return candidates

    def capture_mic_audio(self):
        """Capture microphone audio and feed it to the mic streamer"""
        microphones = self._microphone_candidates()

        if not microphones:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] No microphone found. Mic transcription disabled.", flush=True)
            return

        for mic in microphones:
            if not self.mic_capture_running:
                return
            if self._capture_single_microphone(mic):
                return

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] No usable microphone could be opened. Mic transcription disabled.",
            flush=True,
        )

    def _capture_single_microphone(self, mic):
        """Capture one microphone until stopped or until that device fails."""
        mic_name = _source_name(mic)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Trying microphone: {mic_name}", flush=True)

        adjusted_blocksize = CHUNK * 2

        try:
            with mic.recorder(samplerate=RATE, channels=1, blocksize=adjusted_blocksize) as recorder:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting microphone recording: {mic_name}", flush=True)
                consecutive_errors = 0
                
                while self.mic_capture_running:
                    try:
                        # Record audio block with try-except to handle discontinuities
                        audio_data = recorder.record(CHUNK)

                        audio_bytes = _float_audio_to_pcm16_bytes(audio_data)

                        # Add to mic streamer
                        if self.mic_streamer and self.mic_streamer.running:
                            self.mic_streamer.add_audio_chunk(audio_bytes)
                        consecutive_errors = 0
                    except Exception as e:
                        consecutive_errors += 1
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipped mic audio block from {mic_name} due to: {e}", flush=True)
                        if consecutive_errors >= 5:
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] Microphone {mic_name} failed after repeated errors.", flush=True)
                            return False

                return True
        except Exception as e:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Microphone {mic_name} failed at {RATE} Hz: "
                f"{type(e).__name__}: {e}",
                flush=True,
            )
            return False
            
    def start_desktop_transcription(self):
        """Start desktop audio capture and transcription"""
        if self.desktop_streamer is None:
            # Create a desktop audio streamer with a custom callback to process data
            def desktop_callback(response_data, source_type):
                # For desktop, transcription is realtime; the suggested answer is generated separately.
                text = response_data.get("transcription", "")
                completed = response_data.get("completed", False)
                
                # Store the latest transcript immediately for UI display.
                if text:
                    with self._state_lock:
                        self.last_desktop_query = text
                        self.last_desktop_turn_id = response_data.get("item_id", "")
                        self.last_desktop_answer = ""
                
                # Call the original callback with the transcription text
                if self.transcription_callback and text:
                    self.transcription_callback(text, source_type)

                if text and completed:
                    threading.Thread(
                        target=self._generate_desktop_answer,
                        args=(text, response_data.get("item_id", ""), response_data.get("timing", {})),
                        daemon=True,
                    ).start()
            
            self.desktop_streamer = AudioStreamer(
                transcription_callback=desktop_callback,
                sample_rate=RATE,
                chunk_size=CHUNK,
                source_type="desktop"
            )
            
            # Start desktop audio capture in a separate thread
            self.desktop_capture_running = True
            desktop_thread = threading.Thread(
                target=self.capture_desktop_audio,
                daemon=True
            )
            desktop_thread.start()
            
            # Start the desktop streamer
            return self.desktop_streamer.start()
        return False
        
    def capture_desktop_audio(self):
        """Capture desktop audio using soundcard with loopback capability and feed it to the desktop streamer"""
        try:
            # Get all loopback-capable microphones
            loopback_mics = sc.all_microphones(include_loopback=True)
            
            if not loopback_mics:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No loopback microphones found. Falling back to PyAudio.")
                self.try_pyaudio_fallback()
                return
                
            # Find the loopback mic for the default speaker
            default_spk = sc.default_speaker()
            loop_mic = next(
                (m for m in loopback_mics if default_spk.name in m.name),
                None
            )
            
            # If no associated loopback mic found, fall back to the first one
            if loop_mic is None:
                loop_mic = loopback_mics[0]
                
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Using loopback mic: {loop_mic.name}")
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting desktop audio capture with soundcard loopback")
            
            # Use a slightly larger blocksize to reduce discontinuities
            adjusted_blocksize = CHUNK * 2
            
            # Record in a loop until desktop_capture_running is False
            with loop_mic.recorder(samplerate=RATE, channels=1, blocksize=adjusted_blocksize) as recorder:
                first_chunk = True
                consecutive_errors = 0
                
                # Add additional debug information
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting recorder with samplerate={RATE}, channels=1, blocksize={adjusted_blocksize}")
                
                while self.desktop_capture_running:
                    try:
                        # Record audio block with try-except to handle discontinuities
                        audio_data = recorder.record(CHUNK)
                        
                        # Debug info for first chunk only
                        if first_chunk:
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] Audio data shape: {audio_data.shape}, dtype: {audio_data.dtype}")
                            first_chunk = False
                        
                        # Convert to raw PCM bytes for Azure realtime transcription
                        audio_bytes = _float_audio_to_pcm16_bytes(audio_data)
                        
                        # Add to desktop streamer - sending raw PCM data
                        if self.desktop_streamer and self.desktop_streamer.running:
                            self.desktop_streamer.add_audio_chunk(audio_bytes)
                        consecutive_errors = 0
                    except Exception as e:
                        consecutive_errors += 1
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipped desktop audio block due to: {e}")
                        if consecutive_errors >= 5:
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop loopback capture failed repeatedly. Trying PyAudio fallback.")
                            self.try_pyaudio_fallback()
                            return
                
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture error with soundcard: {e}")
            self.try_pyaudio_fallback()
            
    def try_pyaudio_fallback(self):
        """Try capturing desktop audio using PyAudio as a fallback"""
        if pyaudio is None:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] PyAudio is not installed. Desktop audio fallback disabled.")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture disabled.")
            return

        try:
            p = pyaudio.PyAudio()
            
            # List all audio devices
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Searching for input devices with PyAudio...")
            stereo_mix_index = None
            
            for i in range(p.get_device_count()):
                device_info = p.get_device_info_by_index(i)
                device_name = device_info.get('name', '').lower()
                inputs = device_info.get('maxInputChannels', 0)
                
                print(f"PyAudio Device {i}: {device_name} (inputs: {inputs})")
                
                if inputs > 0 and ('stereo mix' in device_name or 'what u hear' in device_name):
                    stereo_mix_index = i
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Found PyAudio Stereo Mix: {device_info.get('name')}")
                    break
            
            if stereo_mix_index is None:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No suitable recording device found. Desktop audio capture disabled.")
                return
            
            # Open Stereo Mix stream
            stream = p.open(
                format=FORMAT,
                channels=min(2, p.get_device_info_by_index(stereo_mix_index).get('maxInputChannels')),
                rate=RATE,
                input=True,
                input_device_index=stereo_mix_index,
                frames_per_buffer=CHUNK
            )
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture started with PyAudio")
            
            # Continuous capture loop
            while self.desktop_capture_running:
                try:
                    # Read raw PCM data directly for Azure realtime transcription
                    audio_chunk = stream.read(CHUNK, exception_on_overflow=False)
                    
                    # Convert to mono if stereo
                    if p.get_device_info_by_index(stereo_mix_index).get('maxInputChannels') > 1:
                        audio_array = np.frombuffer(audio_chunk, dtype=np.int16)
                        audio_array = audio_array.reshape(-1, 2)
                        mono_array = np.mean(audio_array, axis=1, dtype=np.int16)
                        audio_chunk = mono_array.tobytes()
                    
                    # Add raw PCM data to desktop streamer - no need for WAV conversion
                    if self.desktop_streamer and self.desktop_streamer.running:
                        self.desktop_streamer.add_audio_chunk(audio_chunk)
                    
                except Exception as e:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Error reading audio: {e}")
                    # No sleep needed here either to improve responsiveness
            
            # Clean up
            stream.stop_stream()
            stream.close()
            p.terminate()
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] PyAudio fallback failed: {e}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Desktop audio capture disabled.")

    def _is_current_desktop_turn(self, transcript, turn_id):
        with self._state_lock:
            if self.last_desktop_query != transcript:
                return False
            if turn_id and self.last_desktop_turn_id and self.last_desktop_turn_id != turn_id:
                return False
            return True

    def _publish_desktop_answer(self, transcript, answer, done, turn_id):
        if not answer or not self._is_current_desktop_turn(transcript, turn_id):
            return
        with self._state_lock:
            self.last_desktop_answer = answer
        if self.auto_answer_callback:
            self.auto_answer_callback(transcript, answer, done)

    def _generate_desktop_answer(self, transcript, turn_id="", timing=None):
        """Generate an auto-answer for a completed desktop transcript."""
        timing = timing or {}
        request_started_at = time.perf_counter()
        latency_log(
            "auto_answer_started",
            timing.get("completed_at"),
            item_id=turn_id,
            chars=len(transcript),
        )

        first_delta_seen = False

        def handle_delta(_delta, partial_answer):
            nonlocal first_delta_seen
            if not self._is_current_desktop_turn(transcript, turn_id):
                return
            if not first_delta_seen:
                first_delta_seen = True
                latency_log("first_answer_token", request_started_at, item_id=turn_id)
            self._publish_desktop_answer(transcript, partial_answer, False, turn_id)

        try:
            answer = generate_auto_answer(transcript, on_delta=handle_delta)
            if answer:
                latency_log("auto_answer_complete", request_started_at, item_id=turn_id, chars=len(answer))
                self._publish_desktop_answer(transcript, answer, True, turn_id)
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Auto-answer generation failed: {e}", flush=True)
    
    def stop_transcription(self):
        """Stop all transcription services"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Stopping all transcription services", flush=True)
        
        # Stop audio capture
        self.mic_capture_running = False
        self.desktop_capture_running = False
        
        # Stop streamers
        if self.mic_streamer:
            self.mic_streamer.stop()
            
        if self.desktop_streamer:
            self.desktop_streamer.stop()
            
    def cleanup(self):
        """Clean up all resources"""
        self.stop_transcription()
        
        if self.mic_streamer:
            self.mic_streamer.cleanup()
            self.mic_streamer = None
            
        if self.desktop_streamer:
            self.desktop_streamer.cleanup()
            self.desktop_streamer = None 
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Live transcription manager cleaned up", flush=True)
