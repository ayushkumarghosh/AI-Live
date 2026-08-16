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


if __name__ == "__main__":
    unittest.main()
