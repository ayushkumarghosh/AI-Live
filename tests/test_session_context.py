import unittest

import session_context


class SessionContextTests(unittest.TestCase):
    def setUp(self):
        session_context.clear_session_context()

    def tearDown(self):
        session_context.clear_session_context()

    def test_records_transcripts_in_order(self):
        session_context.record_transcript("hello from me", "mic")
        session_context.record_transcript("question from interviewer", "desktop")

        snapshot = session_context.snapshot()

        self.assertEqual(
            [turn["text"] for turn in snapshot["transcripts"]],
            ["hello from me", "question from interviewer"],
        )
        self.assertEqual(
            [turn["source"] for turn in snapshot["transcripts"]],
            ["mic", "desktop"],
        )

    def test_build_context_includes_recent_transcripts_and_exchanges(self):
        session_context.record_transcript("what is a cache?", "desktop")
        session_context.record_exchange(
            "current request",
            {"user_query": "what is a cache?", "response": "A cache stores reusable results."},
            "general",
        )

        context = session_context.build_context("follow up", "repeat")

        self.assertIn("Current analysis mode: repeat.", context)
        self.assertIn("Interviewer: what is a cache?", context)
        self.assertIn("A cache stores reusable results.", context)
        self.assertIn("Current selected text or user request:\nfollow up", context)

    def test_rolls_older_context_into_summary(self):
        for idx in range(session_context.MAX_TRANSCRIPT_TURNS + 2):
            session_context.record_transcript(f"transcript {idx}", "desktop")

        snapshot = session_context.snapshot()

        self.assertEqual(len(snapshot["transcripts"]), session_context.MAX_TRANSCRIPT_TURNS)
        self.assertIn("transcript 0", snapshot["summary"])
        self.assertIn("transcript 1", snapshot["summary"])
        self.assertNotIn("transcript 0", [turn["text"] for turn in snapshot["transcripts"]])

    def test_clear_session_context_removes_everything(self):
        session_context.record_transcript("hello", "mic")
        session_context.record_exchange("request", {"user_query": "request", "response": "answer"}, "text")

        session_context.clear_session_context()
        snapshot = session_context.snapshot()

        self.assertEqual(snapshot["summary"], "")
        self.assertEqual(snapshot["transcripts"], [])
        self.assertEqual(snapshot["exchanges"], [])

    def test_clear_transcript_context_preserves_exchanges(self):
        session_context.record_transcript("hello", "mic")
        session_context.record_exchange("request", {"user_query": "request", "response": "answer"}, "text")

        session_context.clear_transcript_context()
        snapshot = session_context.snapshot()

        self.assertEqual(snapshot["transcripts"], [])
        self.assertEqual(len(snapshot["exchanges"]), 1)
        self.assertEqual(snapshot["exchanges"][0]["response"], "answer")

    def test_clear_transcript_context_removes_transcript_summary_only(self):
        for idx in range(session_context.MAX_TRANSCRIPT_TURNS + 1):
            session_context.record_transcript(f"old transcript {idx}", "desktop")
        for idx in range(session_context.MAX_AI_EXCHANGES + 1):
            session_context.record_exchange(
                f"old request {idx}",
                {"user_query": f"old request {idx}", "response": f"old answer {idx}"},
                "general",
            )

        session_context.clear_transcript_context()
        snapshot = session_context.snapshot()

        self.assertEqual(snapshot["transcripts"], [])
        self.assertEqual(snapshot["transcript_summary"], "")
        self.assertIn("old answer 0", snapshot["exchange_summary"])


if __name__ == "__main__":
    unittest.main()
