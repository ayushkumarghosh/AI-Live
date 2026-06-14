import unittest
from unittest.mock import patch

from live_transcription import LiveTranscriptionManager


class LiveTranscriptionManagerTests(unittest.TestCase):
    def test_mic_transcript_callback_forwards_to_shared_callback(self):
        forwarded = []
        created_streamers = []

        class FakeAudioStreamer:
            def __init__(self, transcription_callback=None, **_kwargs):
                self.transcription_callback = transcription_callback
                self.running = False
                created_streamers.append(self)

            def start(self):
                self.running = True
                return True

        class FakeThread:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                pass

        manager = LiveTranscriptionManager(transcription_callback=lambda *args: forwarded.append(args))

        with (
            patch("live_transcription.AudioStreamer", FakeAudioStreamer),
            patch("live_transcription.threading.Thread", FakeThread),
        ):
            self.assertTrue(manager.start_mic_transcription())

        created_streamers[0].transcription_callback({"transcription": "my spoken answer"}, "mic")

        self.assertEqual(forwarded, [("my spoken answer", "mic")])
        self.assertTrue(created_streamers[0].running)

    def test_stale_auto_answer_is_not_published(self):
        published = []
        manager = LiveTranscriptionManager(auto_answer_callback=lambda *args: published.append(args))
        manager.last_desktop_query = "old question"
        manager.last_desktop_turn_id = "turn-1"

        def fake_generate(_transcript, on_delta=None):
            manager.last_desktop_query = "new question"
            if on_delta:
                on_delta("old", "old answer")
            return "old answer"

        with patch("live_transcription.generate_auto_answer", side_effect=fake_generate):
            manager._generate_desktop_answer("old question", "turn-1", {"completed_at": None})

        self.assertEqual(published, [])
        self.assertEqual(manager.last_desktop_answer, "")

    def test_current_auto_answer_publishes_partial_and_final(self):
        published = []
        manager = LiveTranscriptionManager(auto_answer_callback=lambda *args: published.append(args))
        manager.last_desktop_query = "current question"
        manager.last_desktop_turn_id = "turn-2"

        def fake_generate(_transcript, on_delta=None):
            if on_delta:
                on_delta("partial", "partial answer")
            return "partial answer final"

        with patch("live_transcription.generate_auto_answer", side_effect=fake_generate):
            manager._generate_desktop_answer("current question", "turn-2", {"completed_at": None})

        self.assertEqual(
            published,
            [
                ("current question", "partial answer", False),
                ("current question", "partial answer final", True),
            ],
        )
        self.assertEqual(manager.last_desktop_answer, "partial answer final")


if __name__ == "__main__":
    unittest.main()
