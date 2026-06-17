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
        session_context.record_exchange(
            "code request",
            {"user_query": "Explain BFS.", "response": "Use a queue."},
            "code",
            current_input="Explain BFS.",
        )

        self.assertIsNone(session_context.find_repeated_exchange("", "code"))

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

    def test_auto_answer_context_is_compact_and_keeps_latest_question(self):
        for idx in range(10):
            session_context.record_transcript(f"turn {idx}", "desktop")
        for idx in range(5):
            session_context.record_exchange(
                f"request {idx}",
                {"user_query": f"request {idx}", "response": f"answer {idx}"},
                "general",
            )

        compact_context = session_context.build_auto_answer_context("turn 9", transcript_turns=3, exchange_count=1)

        self.assertIn("Latest desktop transcript (context, not automatically the question):\nturn 9", compact_context)
        self.assertIn("turn 9", compact_context)
        self.assertNotIn("turn 0", compact_context)
        self.assertIn("answer 4", compact_context)
        self.assertNotIn("answer 0", compact_context)

    def test_auto_answer_context_labels_mic_as_interviewee_candidate(self):
        session_context.record_transcript("I explained hashing first.", "mic")
        session_context.record_transcript("How do you handle collisions?", "desktop")

        context = session_context.build_auto_answer_context(
            "How do you handle collisions?",
            transcript_turns=2,
            exchange_count=0,
        )

        self.assertIn("Interviewee/Candidate: I explained hashing first.", context)
        self.assertIn("Interviewer: How do you handle collisions?", context)
        self.assertIn("microphone transcriptions of what the candidate already said", context)

    def test_auto_answer_context_guides_paused_question_and_clarification(self):
        session_context.record_transcript("Can you explain how you would", "desktop")
        session_context.record_transcript("Do you mean the API design or scaling part?", "mic")
        session_context.record_transcript("The scaling part, especially cache invalidation.", "desktop")

        context = session_context.build_auto_answer_context(
            "The scaling part, especially cache invalidation.",
            transcript_turns=3,
            exchange_count=0,
        )

        self.assertIn("Interviewer: Can you explain how you would", context)
        self.assertIn("Interviewee/Candidate: Do you mean the API design or scaling part?", context)
        self.assertIn("Interviewer: The scaling part, especially cache invalidation.", context)
        self.assertIn("Recent interviewer questions/follow-ups to answer:\n- Can you explain how you would", context)
        self.assertIn("split across multiple nearby Interviewer turns", context)
        self.assertIn("asked a clarification", context)
        self.assertIn("Produce one answer only.", context)

    def test_auto_answer_context_targets_recent_question_not_latest_statement(self):
        session_context.record_transcript("What tradeoffs would you consider for cache invalidation?", "desktop")
        session_context.record_transcript("Do you mean distributed cache invalidation?", "mic")
        session_context.record_transcript("Yes, distributed cache invalidation.", "desktop")

        context = session_context.build_auto_answer_context(
            "Yes, distributed cache invalidation.",
            transcript_turns=3,
            exchange_count=0,
        )
        focus_section = context.split("Recent interviewer questions/follow-ups to answer:\n", 1)[1].split("\n\n", 1)[0]

        self.assertIn("- What tradeoffs would you consider for cache invalidation?", focus_section)
        self.assertNotIn("Yes, distributed cache invalidation.", focus_section)
        self.assertIn(
            "Latest desktop transcript (context, not automatically the question):\n"
            "Yes, distributed cache invalidation.",
            context,
        )
        self.assertIn("use it as context for the recent interviewer question instead", context)

    def test_auto_answer_context_merges_adjacent_interviewer_question_fragments(self):
        session_context.record_transcript("Can you explain how you would", "desktop")
        session_context.record_transcript("scale Redis in this system", "desktop")

        context = session_context.build_auto_answer_context(
            "scale Redis in this system",
            transcript_turns=2,
            exchange_count=0,
        )
        focus_section = context.split("Recent interviewer questions/follow-ups to answer:\n", 1)[1].split("\n\n", 1)[0]

        self.assertIn("- Can you explain how you would scale Redis in this system", focus_section)


if __name__ == "__main__":
    unittest.main()
