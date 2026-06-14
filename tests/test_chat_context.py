import unittest
from unittest.mock import patch

import chat
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
        session_context.clear_session_context()

    def tearDown(self):
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

    def test_repeat_analysis_includes_prior_exchange_context(self):
        session_context.record_exchange(
            "previous request",
            {"user_query": "Explain BFS.", "response": "Use a queue."},
            "code",
        )

        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=self._mock_response()) as create,
        ):
            chat.analyze_repeat_problem("optimize that", [], "jpeg")

        request_text = create.call_args.kwargs["input"][0]["content"][0]["text"]

        self.assertIn("Previous AI exchange 1", request_text)
        self.assertIn("Use a queue.", request_text)
        self.assertIn("Current analysis mode: repeat.", request_text)

    def test_manual_analysis_can_exclude_transcripts(self):
        session_context.record_transcript("Do not include this transcript.", "desktop")

        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=self._mock_response()) as create,
        ):
            chat.analyze_with_text_input("typed question", [], "jpeg", include_transcripts=False)

        request_text = create.call_args.kwargs["input"][0]["content"][0]["text"]

        self.assertNotIn("Do not include this transcript.", request_text)
        self.assertIn("typed question", request_text)

    def test_auto_answer_includes_context_and_records_exchange(self):
        session_context.record_transcript("My answer mentioned hashing.", "mic")
        session_context.record_transcript("How would you handle collisions?", "desktop")

        with (
            patch.object(chat, "get_auto_answer_client", return_value=object()),
            patch.object(chat, "AUTO_ANSWER_STREAMING", False),
            patch.object(chat, "_responses_create_with_retries", return_value=FakeResponse("Use chaining.")) as create,
        ):
            answer = chat.generate_auto_answer("How would you handle collisions?")

        request_text = create.call_args.kwargs["input"]
        snapshot = session_context.snapshot()

        self.assertEqual(answer, "Use chaining.")
        self.assertIn("My answer mentioned hashing.", request_text)
        self.assertIn("How would you handle collisions?", request_text)
        self.assertEqual(snapshot["exchanges"][0]["mode"], "auto")
        self.assertEqual(snapshot["exchanges"][0]["response"], "Use chaining.")

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
        self.assertEqual(client.responses.kwargs["max_output_tokens"], chat.AUTO_ANSWER_MAX_OUTPUT_TOKENS)


if __name__ == "__main__":
    unittest.main()
