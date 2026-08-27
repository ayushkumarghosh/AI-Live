import unittest
from unittest.mock import patch

import chat
import resume_context
import session_context


class FakeResponse:
    def __init__(self, output_text):
        self.output_text = output_text


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
        self.assertEqual(create.call_args.kwargs["reasoning"], {"effort": "low"})
        self.assertIn("Current analysis mode: general.", request_text)
        self.assertIn("Interviewer: Tell me about indexes.", request_text)
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
        self.assertEqual(create.call_args.kwargs["reasoning"], {"effort": "medium"})
        self.assertIn("Automatic repeat correction:", request_text)
        self.assertIn("Prior answer:\nUse recursion only.", request_text)
        self.assertIn("visible compiler, runtime, test, editor, or UI errors", instructions)

    def test_first_time_analysis_does_not_include_correction_context(self):
        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=self._mock_response()) as create,
        ):
            chat.analyze_code_problem("Explain BFS.", [], "jpeg")

        request_text = create.call_args.kwargs["input"][0]["content"][0]["text"]
        instructions = create.call_args.kwargs["instructions"]
        self.assertNotIn("Automatic repeat correction:", request_text)
        self.assertNotIn("previous analysis request", instructions)

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

    def test_shorten_analysis_uses_only_previous_answer_and_does_not_record_exchange(self):
        previous_answer = " ".join(f"word{index}" for index in range(20))
        shortened_answer = " ".join(f"word{index}" for index in range(17))

        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(
                chat,
                "_responses_create_with_retries",
                return_value=self._mock_response(
                    '{"user_query":"Shorten","response":"' + shortened_answer + '"}'
                ),
            ) as create,
        ):
            result = chat.shorten_analysis_answer(previous_answer, "code")

        request = create.call_args.kwargs
        request_text = request["input"][0]["content"][0]["text"]
        self.assertEqual(result["response"], shortened_answer)
        self.assertIn(previous_answer, request_text)
        self.assertNotIn("Session context", request_text)
        self.assertIn("Aim for 17 non-whitespace tokens.", request["instructions"])
        self.assertIn("complete, runnable", request["instructions"])
        self.assertEqual(request["text"]["verbosity"], "low")
        self.assertEqual(session_context.snapshot()["exchanges"], [])

    def test_shorten_analysis_retries_once_when_first_output_is_not_shorter(self):
        previous_answer = " ".join(f"word{index}" for index in range(20))
        shortened_answer = " ".join(f"word{index}" for index in range(17))
        responses = [
            self._mock_response('{"user_query":"Shorten","response":"' + previous_answer + '"}'),
            self._mock_response('{"user_query":"Shorten","response":"' + shortened_answer + '"}'),
        ]

        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", side_effect=responses) as create,
        ):
            result = chat.shorten_analysis_answer(previous_answer, "general")

        self.assertEqual(result["response"], shortened_answer)
        self.assertEqual(create.call_count, 2)
        self.assertIn("This is a retry", create.call_args.kwargs["instructions"])

    def test_shorten_analysis_rejects_two_outputs_outside_the_allowed_range(self):
        previous_answer = " ".join(f"word{index}" for index in range(20))

        with (
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(
                chat,
                "_responses_create_with_retries",
                return_value=self._mock_response(
                    '{"user_query":"Shorten","response":"' + previous_answer + '"}'
                ),
            ) as create,
        ):
            with self.assertRaisesRegex(ValueError, "10–20%"):
                chat.shorten_analysis_answer(previous_answer, "general")

        self.assertEqual(create.call_count, 2)

    def test_shorten_analysis_does_not_over_shorten_a_very_short_answer(self):
        with self.assertRaisesRegex(ValueError, "already too concise"):
            chat.shorten_analysis_answer("one two three", "general")


if __name__ == "__main__":
    unittest.main()
