import unittest
from unittest.mock import patch

import chat
import resume_context
import session_context


class FakeResponse:
    def __init__(self, output_text):
        self.output_text = output_text


class FakeStream:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self.events)


class FakeStreamingResponses:
    def __init__(self, events):
        self.events = events
        self.kwargs = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        return FakeStream(self.events)


class FakeStreamingClient:
    def __init__(self, events):
        self.responses = FakeStreamingResponses(events)


class ChatContextTests(unittest.TestCase):
    def setUp(self):
        resume_context.clear_resume_context(remove_cache=False)
        session_context.clear_session_context()

    def tearDown(self):
        resume_context.clear_resume_context(remove_cache=False)
        session_context.clear_session_context()

    def _mock_response(self, output_text='{"user_query":"latest question","response":"latest answer"}'):
        return FakeResponse(output_text)

    def test_manual_analysis_includes_shared_context_and_records_response(self):
        session_context.record_transcript("Tell me about indexes.", "desktop")

        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=self._mock_response()) as create,
        ):
            result = chat.analyze_general_problem_no_thinking("selected follow-up", [], "jpeg")

        request_text = create.call_args.kwargs["input"][0]["content"][0]["text"]

        self.assertEqual(result["response"], "latest answer")
        self.assertIn("Current analysis mode: general.", request_text)
        self.assertIn("Interviewer: Tell me about indexes.", request_text)
        self.assertIn("selected follow-up", request_text)
        self.assertEqual(session_context.snapshot()["exchanges"][0]["mode"], "general")

    def test_manual_analysis_context_is_shared_across_modes(self):
        session_context.record_exchange(
            "previous code request",
            {"user_query": "Solve two sum.", "response": "Use a hash map."},
            "code",
            current_input="Solve two sum.",
        )

        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=self._mock_response()) as create,
        ):
            chat.analyze_general_problem_no_thinking("Tell me about indexes.", [], "jpeg")

        request_text = create.call_args.kwargs["input"][0]["content"][0]["text"]

        self.assertIn("Previous AI exchange 1", request_text)
        self.assertIn("Use a hash map.", request_text)
        self.assertIn("Current analysis mode: general.", request_text)

    def test_general_analysis_includes_resume_context_when_loaded(self):
        resume_context.set_resume_context(
            "resume.pdf",
            "# Candidate\n\nOwned search ranking improvements and Redis cache migration.",
            persist=False,
        )

        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=self._mock_response()) as create,
        ):
            chat.analyze_general_problem_no_thinking("Tell me about your search project.", [], "jpeg")

        request_text = create.call_args.kwargs["input"][0]["content"][0]["text"]
        instructions = create.call_args.kwargs["instructions"]

        self.assertIn("Candidate resume context:", request_text)
        self.assertIn("Owned search ranking improvements", request_text)
        self.assertIn("Do not invent resume details.", instructions)

    def test_repeated_code_analysis_includes_correction_and_screen_error_instruction(self):
        session_context.record_exchange(
            "previous code request",
            {"user_query": "Explain BFS.", "response": "Use recursion only."},
            "code",
            current_input="Explain BFS.",
        )

        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=self._mock_response()) as create,
        ):
            chat.analyze_code_problem("explain bfs", ["fake-image"], "jpeg")

        request_text = create.call_args.kwargs["input"][0]["content"][0]["text"]
        instructions = create.call_args.kwargs["instructions"]

        self.assertIn("Automatic repeat correction:", request_text)
        self.assertIn("Prior answer:\nUse recursion only.", request_text)
        self.assertIn("Screenshot context is attached.", request_text)
        self.assertIn("visible compiler, runtime, test, editor, or UI errors", instructions)

    def test_repeated_general_analysis_includes_correction_context(self):
        session_context.record_exchange(
            "previous general request",
            {"user_query": "Tell me about indexes.", "response": "Indexes always make writes faster."},
            "general",
            current_input="Tell me about indexes.",
        )

        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=self._mock_response()) as create,
        ):
            chat.analyze_general_problem_no_thinking("Tell me about indexes.", [], "jpeg")

        request_text = create.call_args.kwargs["input"][0]["content"][0]["text"]

        self.assertIn("Automatic repeat correction:", request_text)
        self.assertIn("Prior answer:\nIndexes always make writes faster.", request_text)

    def test_first_time_analysis_does_not_include_correction_context(self):
        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=self._mock_response()) as create,
        ):
            chat.analyze_code_problem("Explain BFS.", [], "jpeg")

        code_request_text = create.call_args.kwargs["input"][0]["content"][0]["text"]
        code_instructions = create.call_args.kwargs["instructions"]

        self.assertNotIn("Automatic repeat correction:", code_request_text)
        self.assertNotIn("previous analysis request", code_instructions)

        session_context.clear_session_context()
        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=self._mock_response()) as create,
        ):
            chat.analyze_general_problem_no_thinking("Tell me about indexes.", [], "jpeg")

        general_request_text = create.call_args.kwargs["input"][0]["content"][0]["text"]
        general_instructions = create.call_args.kwargs["instructions"]

        self.assertNotIn("Automatic repeat correction:", general_request_text)
        self.assertNotIn("previous analysis request", general_instructions)

    def test_manual_analysis_can_exclude_transcripts(self):
        session_context.record_transcript("Do not include this transcript.", "desktop")

        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=self._mock_response()) as create,
        ):
            chat.analyze_with_text_input("typed question", [], "jpeg", include_transcripts=False)

        request_text = create.call_args.kwargs["input"][0]["content"][0]["text"]
        instructions = create.call_args.kwargs["instructions"]

        self.assertNotIn("Do not include this transcript.", request_text)
        self.assertIn("typed question", request_text)
        self.assertIn(chat.candidate_answer_style_prompt, instructions)

    def test_auto_answer_includes_context_and_records_exchange(self):
        session_context.record_transcript("What is hashing?", "desktop")
        session_context.record_transcript("My answer mentioned hashing.", "mic")
        session_context.record_transcript("How would you handle collisions?", "desktop")

        with (
            patch.object(chat, "get_auto_answer_client", return_value=object()),
            patch.object(chat, "AUTO_ANSWER_STREAMING", False),
            patch.object(chat, "_responses_create_with_retries", return_value=FakeResponse("Use chaining.")) as create,
        ):
            answer = chat.generate_auto_answer("How would you handle collisions?")

        request_text = create.call_args.kwargs["input"]
        instructions = create.call_args.kwargs["instructions"]
        snapshot = session_context.snapshot()

        self.assertEqual(answer, "Use chaining.")
        self.assertIn("My answer mentioned hashing.", request_text)
        self.assertIn("Interviewer turns to answer together in the single visible response:", request_text)
        self.assertIn("1. What is hashing?", request_text)
        self.assertIn("2. How would you handle collisions?", request_text)
        self.assertIn("How would you handle collisions?", request_text)
        self.assertIn("Interviewee/Candidate: My answer mentioned hashing.", request_text)
        self.assertIn(chat.candidate_answer_style_prompt, instructions)
        self.assertIn("microphone audio is the Interviewee/Candidate", instructions)
        self.assertIn("not as questions to answer", instructions)
        self.assertIn("Only the latest generated answer is visible", instructions)
        self.assertEqual(snapshot["exchanges"][0]["mode"], "auto")
        self.assertEqual(snapshot["exchanges"][0]["response"], "Use chaining.")
        self.assertIn(
            "Interviewer turns to answer together in the single visible response:",
            snapshot["exchanges"][0]["user_query"],
        )
        self.assertIn("What is hashing?", snapshot["exchanges"][0]["user_query"])
        self.assertIn("How would you handle collisions?", snapshot["exchanges"][0]["user_query"])

    def test_streaming_auto_answer_accumulates_deltas_and_records_once(self):
        client = FakeStreamingClient(
            [
                {"type": "response.output_text.delta", "delta": "Use "},
                {"type": "response.output_text.delta", "delta": "chaining."},
            ]
        )
        partials = []

        with (
            patch.object(chat, "get_auto_answer_client", return_value=client),
            patch.object(chat, "AUTO_ANSWER_STREAMING", True),
        ):
            answer = chat.generate_auto_answer(
                "How would you handle collisions?",
                on_delta=lambda _delta, partial: partials.append(partial),
            )

        snapshot = session_context.snapshot()

        self.assertEqual(answer, "Use chaining.")
        self.assertEqual(partials, ["Use ", "Use chaining."])
        self.assertEqual(len(snapshot["exchanges"]), 1)
        self.assertEqual(snapshot["exchanges"][0]["response"], "Use chaining.")
        self.assertIn(
            "Interviewer turns to answer together in the single visible response:",
            snapshot["exchanges"][0]["user_query"],
        )
        self.assertIn("How would you handle collisions?", snapshot["exchanges"][0]["user_query"])
        self.assertIn(chat.candidate_answer_style_prompt, client.responses.kwargs["instructions"])
        self.assertIn("Only the latest generated answer is visible", client.responses.kwargs["instructions"])
        self.assertEqual(client.responses.kwargs["max_output_tokens"], chat.AUTO_ANSWER_MAX_OUTPUT_TOKENS)

    def test_same_segment_revision_returns_model_output_exactly(self):
        previous = (
            "I would start with chaining because it is simple and predictable.\n\n"
            "- Keep each bucket as a small list.\n"
            "- Resize when the load factor grows.\n\n"
            "```python\n"
            "def lookup(key):\n"
            "    return table[key]\n"
            "```"
        )
        revised = (
            "I would start with chaining because it is simple and predictable.\n\n"
            "- Keep each bucket as a small list.\n"
            "- Resize when the load factor grows.\n\n"
            "```python\n"
            "def lookup(key):\n"
            "    return table[key]\n"
            "```\n\n"
            "For worst case, I would mention that chaining can degrade to O(n), so I would keep buckets small and monitor hash quality."
        )
        session_context.record_transcript("How would you handle collisions?", "desktop")
        first = session_context.prepare_auto_answer_turn("How would you handle collisions?", now=100.0)
        session_context.commit_auto_answer_turn(first, previous, now=100.0)
        session_context.record_transcript("What about worst-case lookup?", "desktop")
        partials = []

        with (
            patch.object(chat, "get_auto_answer_client", return_value=object()),
            patch.object(chat, "AUTO_ANSWER_STREAMING", True),
            patch.object(chat, "AUTO_ANSWER_SEGMENT_GAP_SECONDS", 1_000_000_000_000.0),
            patch.object(
                chat,
                "_responses_create_with_retries",
                return_value=FakeResponse(revised),
            ) as create,
        ):
            answer = chat.generate_auto_answer(
                "What about worst-case lookup?",
                previous_answer=previous,
                on_delta=lambda _delta, partial: partials.append(partial),
            )

        self.assertEqual(answer, revised)
        self.assertEqual(partials, [])
        self.assertIn("complete updated visible answer", create.call_args.kwargs["instructions"])
        self.assertIn("no local patching or post-processing", create.call_args.kwargs["instructions"])
        self.assertNotIn("append_after", create.call_args.kwargs["instructions"])
        self.assertNotIn("replace_block", create.call_args.kwargs["instructions"])
        self.assertIn("Exact previous visible answer", create.call_args.kwargs["input"])
        self.assertIn(previous, create.call_args.kwargs["input"])
        self.assertIn("The UI will display exactly what you return", create.call_args.kwargs["input"])
        self.assertEqual(session_context.snapshot()["auto_answer_segment"]["last_answer"], answer)

    def test_same_segment_revision_does_not_append_or_parse_model_output(self):
        previous = "Previous visible answer."
        raw_model_output = '  {"ops":[{"op":"append_after","block_id":1,"text":"new"}]}  '
        session_context.record_transcript("Initial topic", "desktop")
        first = session_context.prepare_auto_answer_turn("Initial topic", now=100.0)
        session_context.commit_auto_answer_turn(first, previous, now=100.0)
        session_context.record_transcript("Follow-up", "desktop")

        with (
            patch.object(chat, "get_auto_answer_client", return_value=object()),
            patch.object(chat, "AUTO_ANSWER_STREAMING", False),
            patch.object(chat, "AUTO_ANSWER_SEGMENT_GAP_SECONDS", 1_000_000_000_000.0),
            patch.object(
                chat,
                "_responses_create_with_retries",
                return_value=FakeResponse(raw_model_output),
            ),
        ):
            answer = chat.generate_auto_answer("Follow-up", previous_answer=previous)

        self.assertEqual(answer, raw_model_output)

    def test_stale_auto_answer_does_not_commit_segment_or_exchange_history(self):
        session_context.record_transcript("How does a cache work?", "desktop")

        with (
            patch.object(chat, "get_auto_answer_client", return_value=object()),
            patch.object(chat, "AUTO_ANSWER_STREAMING", False),
            patch.object(chat, "_responses_create_with_retries", return_value=FakeResponse("Use TTLs.")),
        ):
            answer = chat.generate_auto_answer("How does a cache work?", is_current=lambda: False)

        snapshot = session_context.snapshot()
        self.assertEqual(answer, "Use TTLs.")
        self.assertEqual(snapshot["exchanges"], [])
        self.assertEqual(snapshot["auto_answer_segment"]["segment_id"], 0)
        self.assertEqual(snapshot["auto_answer_segment"]["last_answer"], "")

    def test_stale_new_segment_does_not_clear_previous_answer(self):
        previous = "- Use TTLs."
        session_context.record_transcript("Explain cache invalidation.", "desktop")
        first = session_context.prepare_auto_answer_turn("Explain cache invalidation.", now=100.0)
        session_context.commit_auto_answer_turn(first, previous, now=100.0)
        session_context.record_transcript("Next question, explain graph traversal.", "desktop")
        resets = []

        with (
            patch.object(chat, "get_auto_answer_client", return_value=object()),
            patch.object(chat, "AUTO_ANSWER_STREAMING", False),
            patch.object(chat, "_responses_create_with_retries", return_value=FakeResponse("Use BFS.")),
        ):
            chat.generate_auto_answer(
                "Next question, explain graph traversal.",
                previous_answer=previous,
                on_reset=lambda: resets.append("reset"),
                is_current=lambda: False,
            )

        self.assertEqual(resets, [])
        self.assertEqual(session_context.snapshot()["auto_answer_segment"]["last_answer"], previous)


if __name__ == "__main__":
    unittest.main()
