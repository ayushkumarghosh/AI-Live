import json
import os
import queue
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

import ai_live
import chat
import session_context
from overlay import DraggableOverlay
from tests.test_ai_live_shortening import ImmediateThread


class HSAnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        session_context.clear_session_context()
        self.addCleanup(session_context.clear_session_context)

    def test_toolbar_requests_followups_and_shortening(self):
        overlay = DraggableOverlay()
        self.addCleanup(overlay.close)
        overlay.show_interviewer_suggestions = False
        overlay.hs_answer_signal.connect(ai_live.process_hs_answer)
        overlay.shorten_analysis_signal.connect(ai_live.process_shorten_analysis)
        overlay.clear_history_signal.connect(ai_live.stop_processing_and_clear_history)
        self.assertEqual(overlay.hs_answer_button._wide_text, "HS answer")
        slot = overlay.command_buttons.index(overlay.hs_answer_button)
        self.assertIs(overlay.command_buttons[slot - 1], overlay.code_analyze_button)
        self.assertIs(overlay.command_buttons[slot + 1], overlay.general_analyze_button_regular)

        guide = chat.HERTZ_GUIDE_PATH.read_text(encoding="utf-8-sig")
        answer = " ".join(f"word{i}" for i in range(20))
        shorter = " ".join(answer.split()[:17])
        response = SimpleNamespace(output_text=json.dumps({"user_query": "How do reviews work?", "response": answer}))
        screenshots = queue.Queue()
        screenshots.put("queued")
        with (
            patch.object(ai_live, "overlay", overlay),
            patch.object(ai_live.threading, "Thread", ImmediateThread),
            patch.object(ai_live, "_with_rate_limit", return_value=nullcontext()),
            patch.object(ai_live, "_run_on_ui", side_effect=lambda name, *args: getattr(overlay, name)(*args)),
            patch("overlay.screenshot_queue", screenshots),
            patch.object(ai_live, "capture_screenshot", return_value="captured") as capture,
            patch.object(chat, "get_analysis_client", return_value=object()),
            patch.object(chat, "_responses_create_with_retries", return_value=response) as create,
        ):
            overlay.screenshot_toggle_button.setChecked(True)
            overlay.hs_answer_button.click()
            content = create.call_args.kwargs["input"][0]["content"]
            self.assertIn(guide, content[-1]["text"])
            self.assertEqual(content[1]["image_url"], "data:image/jpeg;base64,queued")
            capture.assert_not_called()
            self.assertEqual(overlay.current_manual_answer, answer)
            self.assertNotIn(guide[:100], session_context.snapshot()["exchanges"][0]["user_content"])

            overlay.hs_answer_button.click()
            capture.assert_called_once()
            overlay.screenshot_toggle_button.setChecked(False)
            overlay.hs_answer_button.click()
            content = create.call_args.kwargs["input"][0]["content"]
            self.assertTrue(all(part["type"] == "input_text" for part in content))
            self.assertIn("How do reviews work?", content[0]["text"])
            self.assertIn(guide, content[-1]["text"])
            capture.assert_called_once()

            create.return_value = SimpleNamespace(output_text=json.dumps({"user_query": "Shorten", "response": shorter}))
            overlay.shorten_button.click()
            self.assertEqual(overlay.current_manual_answer, shorter)
            self.assertEqual(session_context.snapshot()["exchanges"][-1]["response"], shorter)

            chat.analyze_general_problem_no_thinking("Follow up", [], "jpeg")
            self.assertNotIn(guide[:100], str(create.call_args.kwargs))
            overlay.clear_button.click()
            self.assertEqual(session_context.snapshot()["exchanges"], [])
            overlay.hs_answer_button.click()
            content = create.call_args.kwargs["input"][0]["content"]
            self.assertNotIn("How do reviews work?", content[0]["text"])
            self.assertIn(guide, content[-1]["text"])

    def test_unreadable_guide_stops_request(self):
        with (
            patch.object(chat, "HERTZ_GUIDE_PATH") as path,
            patch.object(chat, "get_analysis_client") as client,
        ):
            path.read_text.side_effect = FileNotFoundError("missing guide")
            with self.assertRaisesRegex(ValueError, "Could not read Project Hertz.md"):
                chat.analyze_hs_answer("", [], "jpeg")
            client.assert_not_called()
