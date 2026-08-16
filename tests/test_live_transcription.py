import unittest
from unittest.mock import patch

import numpy as np

from live_transcription import LiveAudioManager, _float_audio_to_pcm16_bytes


class FakeRealtimeSession:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.running = False
        self.enabled_values = []
        self.refresh_count = 0
        self.reset_count = 0
        self.audio_chunks = []
        self.cleaned = False
        self.__class__.instances.append(self)

    def start(self):
        self.running = True
        return True

    def set_auto_answer_enabled(self, enabled):
        self.enabled_values.append(bool(enabled))

    def refresh_instructions(self):
        self.refresh_count += 1

    def reset_context(self):
        self.reset_count += 1

    def add_audio_chunk(self, chunk):
        self.audio_chunks.append(chunk)

    def stop(self):
        self.running = False

    def cleanup(self):
        self.cleaned = True
        self.running = False


class FakeThread:
    def __init__(self, target=None, **_kwargs):
        self.target = target
        self.started = False

    def start(self):
        self.started = True


class LiveAudioManagerTests(unittest.TestCase):
    def setUp(self):
        FakeRealtimeSession.instances = []

    def test_start_creates_one_desktop_realtime_session_and_no_mic_path(self):
        updates = []
        manager = LiveAudioManager(
            answer_update_callback=lambda action, text: updates.append((action, text)),
            instructions_provider=lambda: "instructions",
        )

        with (
            patch("live_transcription.AzureRealtimeAnswerSession", FakeRealtimeSession),
            patch("live_transcription.threading.Thread", FakeThread),
        ):
            self.assertTrue(manager.start())

        self.assertEqual(len(FakeRealtimeSession.instances), 1)
        session = FakeRealtimeSession.instances[0]
        self.assertIs(session, manager.realtime_session)
        self.assertIs(session.kwargs["answer_update_callback"], manager.answer_update_callback)
        self.assertFalse(hasattr(manager, "mic_streamer"))
        self.assertTrue(manager.capture_thread.started)

    def test_manager_forwards_toggle_resume_refresh_and_context_reset(self):
        manager = LiveAudioManager()
        manager.realtime_session = FakeRealtimeSession()

        manager.set_auto_answer_enabled(True)
        manager.set_auto_answer_enabled(False)
        manager.refresh_instructions()
        manager.reset_context()

        self.assertEqual(manager.realtime_session.enabled_values, [True, False])
        self.assertEqual(manager.realtime_session.refresh_count, 1)
        self.assertEqual(manager.realtime_session.reset_count, 1)

    def test_cleanup_stops_capture_and_realtime_session(self):
        manager = LiveAudioManager()
        session = FakeRealtimeSession()
        manager.realtime_session = session
        manager.desktop_capture_running = True

        manager.cleanup()

        self.assertFalse(manager.desktop_capture_running)
        self.assertTrue(session.cleaned)
        self.assertIsNone(manager.realtime_session)

    def test_float_desktop_audio_is_converted_to_mono_pcm16(self):
        stereo = np.array([[1.0, -1.0], [0.5, 0.5]], dtype=np.float32)

        pcm = np.frombuffer(_float_audio_to_pcm16_bytes(stereo), dtype=np.int16)

        self.assertEqual(pcm.tolist(), [0, 16383])


if __name__ == "__main__":
    unittest.main()
