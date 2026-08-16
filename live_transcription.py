import collections.abc
import sys
import threading
import warnings
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

from azure_realtime import AzureRealtimeAnswerSession
from azure_realtime import CHUNK_SIZE as AZURE_CHUNK_SIZE
from azure_realtime import SAMPLE_RATE as AZURE_SAMPLE_RATE

try:
    import pyaudio
except ImportError:
    pyaudio = None


warnings.filterwarnings(
    "ignore",
    message="data discontinuity in recording",
    category=sc.mediafoundation.SoundcardRuntimeWarning,
)


def timestamp():
    return f"[{datetime.now().strftime('%H:%M:%S')}]"


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
                raise AssertionError(f"Unsupported WASAPI mix format: {format_details}")

            channel_count = len(set(self.channelmap))
            fmt.nChannels = channel_count
            fmt.nSamplesPerSec = int(samplerate)
            fmt.nAvgBytesPerSec = int(samplerate) * channel_count * 4
            fmt.nBlockAlign = channel_count * 4
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
        print(f"{timestamp()} Could not apply soundcard compatibility patch: {exc}", flush=True)


_patch_soundcard_waveformatex_recorder()

FORMAT = pyaudio.paInt16 if pyaudio else None
RATE = AZURE_SAMPLE_RATE
CHUNK = AZURE_CHUNK_SIZE


def _float_audio_to_pcm16_bytes(audio_data):
    if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
        audio_data = np.mean(audio_data, axis=1)
    audio_data = np.asarray(audio_data, dtype=np.float32).flatten()
    audio_data = np.clip(audio_data, -1.0, 1.0)
    return (audio_data * 32767).astype(np.int16).tobytes()


class LiveAudioManager:
    def __init__(
        self,
        answer_update_callback=None,
        session_reset_callback=None,
        status_callback=None,
        instructions_provider=None,
    ):
        self.answer_update_callback = answer_update_callback
        self.session_reset_callback = session_reset_callback
        self.status_callback = status_callback
        self.instructions_provider = instructions_provider
        self.realtime_session = None
        self.desktop_capture_running = False
        self.capture_thread = None

    def start(self):
        if self.realtime_session is not None:
            return False

        print(f"{timestamp()} Starting desktop audio Realtime answering", flush=True)
        self.realtime_session = AzureRealtimeAnswerSession(
            answer_update_callback=self.answer_update_callback,
            session_reset_callback=self.session_reset_callback,
            status_callback=self.status_callback,
            instructions_provider=self.instructions_provider,
            sample_rate=RATE,
            chunk_size=CHUNK,
        )
        if not self.realtime_session.start():
            self.realtime_session = None
            return False

        self.desktop_capture_running = True
        self.capture_thread = threading.Thread(target=self.capture_desktop_audio, daemon=True)
        self.capture_thread.start()
        return True

    def set_auto_answer_enabled(self, enabled):
        if self.realtime_session:
            self.realtime_session.set_auto_answer_enabled(enabled)

    def refresh_instructions(self):
        if self.realtime_session:
            self.realtime_session.refresh_instructions()

    def reset_context(self):
        if self.realtime_session:
            self.realtime_session.reset_context()

    def capture_desktop_audio(self):
        try:
            loopback_mics = sc.all_microphones(include_loopback=True)
            if not loopback_mics:
                print(f"{timestamp()} No loopback microphones found. Falling back to PyAudio.", flush=True)
                self.try_pyaudio_fallback()
                return

            default_speaker = sc.default_speaker()
            loopback_mic = next(
                (mic for mic in loopback_mics if default_speaker.name in mic.name),
                loopback_mics[0],
            )
            print(f"{timestamp()} Using desktop loopback device: {loopback_mic.name}", flush=True)

            adjusted_blocksize = CHUNK * 2
            with loopback_mic.recorder(
                samplerate=RATE,
                channels=1,
                blocksize=adjusted_blocksize,
            ) as recorder:
                consecutive_errors = 0
                while self.desktop_capture_running:
                    try:
                        audio_data = recorder.record(CHUNK)
                        audio_bytes = _float_audio_to_pcm16_bytes(audio_data)
                        if self.realtime_session and self.realtime_session.running:
                            self.realtime_session.add_audio_chunk(audio_bytes)
                        consecutive_errors = 0
                    except Exception as exc:
                        consecutive_errors += 1
                        print(f"{timestamp()} Skipped desktop audio block: {exc}", flush=True)
                        if consecutive_errors >= 5:
                            print(
                                f"{timestamp()} Desktop loopback failed repeatedly. Trying PyAudio fallback.",
                                flush=True,
                            )
                            self.try_pyaudio_fallback()
                            return
        except Exception as exc:
            print(f"{timestamp()} Desktop audio capture error: {exc}", flush=True)
            self.try_pyaudio_fallback()

    def try_pyaudio_fallback(self):
        if pyaudio is None:
            print(f"{timestamp()} PyAudio is not installed. Desktop audio capture is disabled.", flush=True)
            return

        audio = None
        stream = None
        try:
            audio = pyaudio.PyAudio()
            stereo_mix_index = None
            stereo_mix_channels = 1
            for index in range(audio.get_device_count()):
                device = audio.get_device_info_by_index(index)
                name = device.get("name", "").lower()
                inputs = int(device.get("maxInputChannels", 0))
                if inputs > 0 and ("stereo mix" in name or "what u hear" in name):
                    stereo_mix_index = index
                    stereo_mix_channels = min(2, inputs)
                    break

            if stereo_mix_index is None:
                print(f"{timestamp()} No PyAudio loopback input was found.", flush=True)
                return

            stream = audio.open(
                format=FORMAT,
                channels=stereo_mix_channels,
                rate=RATE,
                input=True,
                input_device_index=stereo_mix_index,
                frames_per_buffer=CHUNK,
            )
            print(f"{timestamp()} Desktop audio capture started with PyAudio", flush=True)

            while self.desktop_capture_running:
                audio_chunk = stream.read(CHUNK, exception_on_overflow=False)
                if stereo_mix_channels > 1:
                    audio_array = np.frombuffer(audio_chunk, dtype=np.int16).reshape(-1, stereo_mix_channels)
                    audio_chunk = np.mean(audio_array, axis=1, dtype=np.int16).tobytes()
                if self.realtime_session and self.realtime_session.running:
                    self.realtime_session.add_audio_chunk(audio_chunk)
        except Exception as exc:
            print(f"{timestamp()} PyAudio fallback failed: {exc}", flush=True)
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if audio is not None:
                audio.terminate()

    def stop(self):
        self.desktop_capture_running = False
        if self.realtime_session:
            self.realtime_session.stop()

    def cleanup(self):
        self.stop()
        if self.realtime_session:
            self.realtime_session.cleanup()
            self.realtime_session = None
        print(f"{timestamp()} Live desktop audio manager cleaned up", flush=True)
