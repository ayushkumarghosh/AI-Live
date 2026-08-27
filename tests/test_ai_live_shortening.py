from contextlib import nullcontext
import unittest
from unittest.mock import patch

import ai_live


class ImmediateThread:
    def __init__(self, target=None, **_kwargs):
        self.target = target

    def start(self):
        self.target()


class FakeOverlay:
    def __init__(self):
        self.is_processing = False
        self.current_session_id = ""
        self.statuses = []

    def set_processing(self, value):
        self.is_processing = bool(value)

    def update_status(self, status, color):
        self.statuses.append((status, color))


class ShortenAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.original_overlay = ai_live.overlay
        ai_live.overlay = FakeOverlay()

    def tearDown(self):
        ai_live.overlay = self.original_overlay

    def test_shortening_replaces_history_and_queues_the_ui_update(self):
        calls = []
        previous_answer = "Original manual answer."
        shortened_answer = "Shorter manual answer."

        with (
            patch("ai_live.threading.Thread", ImmediateThread),
            patch("ai_live._with_rate_limit", return_value=nullcontext()),
            patch(
                "ai_live.shorten_analysis_answer",
                return_value={"user_query": "Shorten", "response": shortened_answer},
            ) as shorten,
            patch("ai_live.replace_latest_exchange_response", return_value=True) as replace,
            patch("ai_live._run_on_ui", side_effect=lambda *args: calls.append(args)),
        ):
            ai_live.process_shorten_analysis(previous_answer, "general")

        shorten.assert_called_once_with(previous_answer, "general")
        replace.assert_called_once_with("general", previous_answer, shortened_answer)
        self.assertIn(
            ("update_shortened_analysis_response", {"user_query": "Shorten", "response": shortened_answer}, "general"),
            calls,
        )
        self.assertIn(("set_processing", False), calls)

    def test_stale_shortened_result_does_not_replace_history_or_update_the_ui(self):
        calls = []

        def stale_response(*_args):
            ai_live.overlay.current_session_id = "newer_request"
            return {"user_query": "Shorten", "response": "Shorter manual answer."}

        with (
            patch("ai_live.threading.Thread", ImmediateThread),
            patch("ai_live._with_rate_limit", return_value=nullcontext()),
            patch("ai_live.shorten_analysis_answer", side_effect=stale_response),
            patch("ai_live.replace_latest_exchange_response") as replace,
            patch("ai_live._run_on_ui", side_effect=lambda *args: calls.append(args)),
        ):
            ai_live.process_shorten_analysis("Original manual answer.", "code")

        replace.assert_not_called()
        self.assertEqual(calls, [])

    def test_shortening_failure_keeps_the_existing_answer_in_place(self):
        calls = []

        with (
            patch("ai_live.threading.Thread", ImmediateThread),
            patch("ai_live._with_rate_limit", return_value=nullcontext()),
            patch("ai_live.shorten_analysis_answer", side_effect=ValueError("Answer is already at its minimum length.")),
            patch("ai_live.replace_latest_exchange_response") as replace,
            patch("ai_live._run_on_ui", side_effect=lambda *args: calls.append(args)),
        ):
            ai_live.process_shorten_analysis("A", "general")

        replace.assert_not_called()
        self.assertNotIn("update_shortened_analysis_response", [call[0] for call in calls])
        self.assertIn(("update_status", "Answer already concise", "#FFA500"), calls)
        self.assertIn(("set_processing", False), calls)


if __name__ == "__main__":
    unittest.main()
