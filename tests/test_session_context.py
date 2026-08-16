import unittest

import resume_context
import session_context


class SessionContextTests(unittest.TestCase):
    def setUp(self):
        resume_context.clear_resume_context(remove_cache=False)
        session_context.clear_session_context()

    def tearDown(self):
        resume_context.clear_resume_context(remove_cache=False)
        session_context.clear_session_context()

    def test_records_optional_supplied_transcripts_in_order(self):
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

    def test_build_context_includes_recent_manual_context_and_exchanges(self):
        session_context.record_transcript("what is a cache?", "desktop")
        session_context.record_exchange(
            "current request",
            {"user_query": "what is a cache?", "response": "A cache stores reusable results."},
            "general",
        )

        context = session_context.build_context("follow up", "general")

        self.assertIn("Current analysis mode: general.", context)
        self.assertIn("Interviewer: what is a cache?", context)
        self.assertIn("A cache stores reusable results.", context)
        self.assertIn("Current selected text or user request:\nfollow up", context)

    def test_build_context_keeps_ai_exchanges_common_across_modes(self):
        session_context.record_exchange(
            "code request",
            {"user_query": "Solve two sum.", "response": "Use a hash map."},
            "code",
            current_input="Solve two sum.",
        )

        context = session_context.build_context("Tell me about indexes.", "general")

        self.assertIn("Previous AI exchange 1 (code", context)
        self.assertIn("Use a hash map.", context)
        self.assertIn("Current analysis mode: general.", context)

    def test_find_repeated_exchange_matches_same_mode_question(self):
        session_context.record_exchange(
            "code request",
            {"user_query": "Explain BFS.", "response": "Use a queue."},
            "code",
            current_input="Explain BFS.",
        )

        match = session_context.find_repeated_exchange("explain bfs", "code")

        self.assertIsNotNone(match)
        self.assertEqual(match["response"], "Use a queue.")

    def test_find_repeated_exchange_does_not_cross_modes(self):
        session_context.record_exchange(
            "code request",
            {"user_query": "Explain BFS.", "response": "Use a queue."},
            "code",
            current_input="Explain BFS.",
        )

        self.assertIsNone(session_context.find_repeated_exchange("Explain BFS.", "general"))

    def test_find_repeated_exchange_ignores_empty_input(self):
        self.assertIsNone(session_context.find_repeated_exchange("", "code"))

    def test_rolls_older_context_into_summary(self):
        for index in range(session_context.MAX_TRANSCRIPT_TURNS + 2):
            session_context.record_transcript(f"transcript {index}", "desktop")

        snapshot = session_context.snapshot()

        self.assertEqual(len(snapshot["transcripts"]), session_context.MAX_TRANSCRIPT_TURNS)
        self.assertIn("transcript 0", snapshot["summary"])
        self.assertIn("transcript 1", snapshot["summary"])

    def test_clear_session_context_removes_everything(self):
        session_context.record_transcript("hello", "mic")
        session_context.record_exchange(
            "request",
            {"user_query": "request", "response": "answer"},
            "text",
        )

        session_context.clear_session_context()
        snapshot = session_context.snapshot()

        self.assertEqual(snapshot["summary"], "")
        self.assertEqual(snapshot["transcripts"], [])
        self.assertEqual(snapshot["exchanges"], [])

    def test_clear_transcript_context_preserves_exchanges(self):
        session_context.record_transcript("hello", "mic")
        session_context.record_exchange(
            "request",
            {"user_query": "request", "response": "answer"},
            "text",
        )

        session_context.clear_transcript_context()
        snapshot = session_context.snapshot()

        self.assertEqual(snapshot["transcripts"], [])
        self.assertEqual(len(snapshot["exchanges"]), 1)
        self.assertEqual(snapshot["exchanges"][0]["response"], "answer")

    def test_clear_transcript_context_removes_only_transcript_summary(self):
        for index in range(session_context.MAX_TRANSCRIPT_TURNS + 1):
            session_context.record_transcript(f"old transcript {index}", "desktop")
        for index in range(session_context.MAX_AI_EXCHANGES + 1):
            session_context.record_exchange(
                f"old request {index}",
                {"user_query": f"old request {index}", "response": f"old answer {index}"},
                "general",
            )

        session_context.clear_transcript_context()
        snapshot = session_context.snapshot()

        self.assertEqual(snapshot["transcripts"], [])
        self.assertEqual(snapshot["transcript_summary"], "")
        self.assertIn("old answer 0", snapshot["exchange_summary"])


if __name__ == "__main__":
    unittest.main()
