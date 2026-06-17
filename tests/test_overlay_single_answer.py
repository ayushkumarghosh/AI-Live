import unittest

from overlay import DraggableOverlay


class FakeSignal:
    def __init__(self):
        self.values = []

    def emit(self, value):
        self.values.append(value)


class OverlayHarness:
    _render_current_answer_basic = DraggableOverlay._render_current_answer_basic

    def __init__(self, show_auto=True):
        self.update_conversation_signal = FakeSignal()
        self.current_answer = ""
        self.show_interviewer_suggestions = show_auto
        self.last_interviewer_question = ""
        self.last_suggested_answer = ""
        self._active_auto_answer_question = ""


class OverlaySingleAnswerTests(unittest.TestCase):
    def test_manual_response_replaces_visible_answer_without_question_labels(self):
        overlay = OverlayHarness()

        DraggableOverlay.update_response(
            overlay,
            {"user_query": "First question?", "response": "First answer."},
        )
        DraggableOverlay.update_response(
            overlay,
            {"user_query": "Second question?", "response": "Second answer."},
        )

        rendered = overlay.update_conversation_signal.values[-1]

        self.assertEqual(overlay.current_answer, "Second answer.")
        self.assertIn("Second answer.", rendered)
        self.assertNotIn("First answer.", rendered)
        self.assertNotIn("First question?", rendered)
        self.assertNotIn("Second question?", rendered)
        self.assertNotIn("You:", rendered)
        self.assertNotIn("AI:", rendered)

    def test_auto_answer_replaces_visible_answer_and_resets_active_turn_when_done(self):
        overlay = OverlayHarness(show_auto=True)

        DraggableOverlay.update_interviewer_qa(
            overlay,
            "What is a cache?",
            "A cache stores reusable results.",
            False,
        )
        DraggableOverlay.update_interviewer_qa(
            overlay,
            "How would you invalidate it?",
            "I would invalidate by key, TTL, or write-through updates.",
            True,
        )

        rendered = overlay.update_conversation_signal.values[-1]

        self.assertEqual(overlay.current_answer, "I would invalidate by key, TTL, or write-through updates.")
        self.assertEqual(overlay._active_auto_answer_question, "")
        self.assertIn("I would invalidate by key, TTL, or write-through updates.", rendered)
        self.assertNotIn("A cache stores reusable results.", rendered)
        self.assertNotIn("How would you invalidate it?", rendered)
        self.assertNotIn("AI:", rendered)

    def test_auto_answer_disabled_does_not_replace_visible_answer(self):
        overlay = OverlayHarness(show_auto=False)
        overlay.current_answer = "Existing manual answer."

        DraggableOverlay.update_interviewer_qa(
            overlay,
            "What is a queue?",
            "A queue is FIFO.",
            True,
        )

        self.assertEqual(overlay.current_answer, "Existing manual answer.")
        self.assertEqual(overlay.update_conversation_signal.values, [])


if __name__ == "__main__":
    unittest.main()
