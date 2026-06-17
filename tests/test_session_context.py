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

    def _auto_answer_target_section(self, context):
        return context.split(
            "Interviewer turns to answer together in the single visible response:\n",
            1,
        )[1].split("\n\n", 1)[0]

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

    def test_auto_answer_context_targets_latest_five_interviewer_turns(self):
        for idx in range(10):
            session_context.record_transcript(f"desktop turn {idx}", "desktop")
        for idx in range(5):
            session_context.record_exchange(
                f"request {idx}",
                {"user_query": f"request {idx}", "response": f"answer {idx}"},
                "general",
            )

        compact_context = session_context.build_auto_answer_context(
            "desktop turn 9",
            transcript_turns=3,
            exchange_count=1,
            target_interviewer_turns=5,
        )
        target_section = self._auto_answer_target_section(compact_context)
        target_lines = target_section.splitlines()

        self.assertEqual(len(target_lines), 5)
        self.assertEqual(target_lines[0], "1. desktop turn 5")
        self.assertEqual(target_lines[-1], "5. desktop turn 9")
        self.assertNotIn("desktop turn 4", target_section)
        self.assertIn("Latest desktop transcript (context, not automatically the question):\ndesktop turn 9", compact_context)
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
        self.assertNotIn("I explained hashing first.", self._auto_answer_target_section(context))

    def test_auto_answer_context_uses_fewer_than_five_without_duplicating_current_turn(self):
        session_context.record_transcript("What is your cache strategy?", "desktop")
        session_context.record_transcript("Assume Redis is available.", "desktop")

        context = session_context.build_auto_answer_context(
            "Assume Redis is available.",
            transcript_turns=2,
            exchange_count=0,
            target_interviewer_turns=5,
        )
        target_lines = self._auto_answer_target_section(context).splitlines()

        self.assertEqual(
            target_lines,
            [
                "1. What is your cache strategy?",
                "2. Assume Redis is available.",
            ],
        )

    def test_auto_answer_segment_keeps_short_gap_topic_shift_same_segment(self):
        session_context.record_transcript("Explain cache invalidation.", "desktop")
        first = session_context.prepare_auto_answer_turn("Explain cache invalidation.", now=100.0)
        session_context.commit_auto_answer_turn(first, "- Use TTLs", now=100.0)
        session_context.record_transcript("What about message queues?", "desktop")

        second = session_context.prepare_auto_answer_turn(
            "What about message queues?",
            segment_gap_seconds=45,
            topic_overlap_min=0.18,
            now=110.0,
        )

        self.assertFalse(second["starts_new_segment"])
        self.assertFalse(second["should_clear_previous_answer"])
        self.assertEqual(
            second["target_turns"],
            ["Explain cache invalidation.", "What about message queues?"],
        )
        self.assertIn("Previous visible auto-answer to update", second["context_text"])

    def test_auto_answer_segment_starts_new_on_hard_reset_phrase(self):
        session_context.record_transcript("Explain cache invalidation.", "desktop")
        first = session_context.prepare_auto_answer_turn("Explain cache invalidation.", now=100.0)
        session_context.commit_auto_answer_turn(first, "- Use TTLs", now=100.0)
        session_context.record_transcript("Next question, explain graph traversal.", "desktop")

        second = session_context.prepare_auto_answer_turn(
            "Next question, explain graph traversal.",
            now=110.0,
        )

        self.assertTrue(second["starts_new_segment"])
        self.assertTrue(second["should_clear_previous_answer"])
        self.assertEqual(second["target_turns"], ["Next question, explain graph traversal."])
        self.assertNotIn("Previous visible auto-answer to update", second["context_text"])

    def test_auto_answer_segment_starts_new_after_gap_with_low_topic_overlap(self):
        session_context.record_transcript("Explain cache invalidation.", "desktop")
        first = session_context.prepare_auto_answer_turn("Explain cache invalidation.", now=100.0)
        session_context.commit_auto_answer_turn(first, "- Use TTLs", now=100.0)
        session_context.record_transcript("How do you design graph traversal?", "desktop")

        second = session_context.prepare_auto_answer_turn(
            "How do you design graph traversal?",
            segment_gap_seconds=45,
            topic_overlap_min=0.18,
            now=160.0,
        )

        self.assertTrue(second["starts_new_segment"])
        self.assertTrue(second["gap_elapsed"])
        self.assertLess(second["topic_overlap"], 0.18)
        self.assertTrue(second["should_clear_previous_answer"])

    def test_auto_answer_segment_keeps_delayed_turn_with_high_topic_overlap(self):
        session_context.record_transcript("Explain database indexes.", "desktop")
        first = session_context.prepare_auto_answer_turn("Explain database indexes.", now=100.0)
        session_context.commit_auto_answer_turn(first, "- Mention B-trees", now=100.0)
        session_context.record_transcript("How do database indexes handle range queries?", "desktop")

        second = session_context.prepare_auto_answer_turn(
            "How do database indexes handle range queries?",
            segment_gap_seconds=45,
            topic_overlap_min=0.18,
            now=160.0,
        )

        self.assertFalse(second["starts_new_segment"])
        self.assertTrue(second["gap_elapsed"])
        self.assertGreaterEqual(second["topic_overlap"], 0.18)
        self.assertFalse(second["should_clear_previous_answer"])

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
        target_section = self._auto_answer_target_section(context)
        self.assertIn("1. Can you explain how you would", target_section)
        self.assertIn("2. The scaling part, especially cache invalidation.", target_section)
        self.assertNotIn("Do you mean the API design or scaling part?", target_section)
        self.assertIn("split across multiple nearby Interviewer turns", context)
        self.assertIn("asked a clarification", context)
        self.assertIn("Only the latest auto-answer is visible", context)

    def test_auto_answer_context_targets_latest_statement_with_recent_question(self):
        session_context.record_transcript("What tradeoffs would you consider for cache invalidation?", "desktop")
        session_context.record_transcript("Do you mean distributed cache invalidation?", "mic")
        session_context.record_transcript("Yes, distributed cache invalidation.", "desktop")

        context = session_context.build_auto_answer_context(
            "Yes, distributed cache invalidation.",
            transcript_turns=3,
            exchange_count=0,
        )
        target_section = self._auto_answer_target_section(context)

        self.assertIn("1. What tradeoffs would you consider for cache invalidation?", target_section)
        self.assertIn("2. Yes, distributed cache invalidation.", target_section)
        self.assertIn(
            "Latest desktop transcript (context, not automatically the question):\n"
            "Yes, distributed cache invalidation.",
            context,
        )
        self.assertIn("Interviewer statements, confirmations, or constraints", context)

    def test_auto_answer_context_keeps_adjacent_interviewer_fragments_in_target_order(self):
        session_context.record_transcript("Can you explain how you would", "desktop")
        session_context.record_transcript("scale Redis in this system", "desktop")

        context = session_context.build_auto_answer_context(
            "scale Redis in this system",
            transcript_turns=2,
            exchange_count=0,
        )
        target_lines = self._auto_answer_target_section(context).splitlines()

        self.assertEqual(
            target_lines,
            [
                "1. Can you explain how you would",
                "2. scale Redis in this system",
            ],
        )
        self.assertIn("combine those turns before answering", context)


if __name__ == "__main__":
    unittest.main()
