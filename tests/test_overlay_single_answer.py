import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from overlay import CodeAnswerOverlay, DraggableOverlay


class FakeSignal:
    def __init__(self):
        self.values = []

    def emit(self, value):
        self.values.append(value)


class FakeConversationText:
    def __init__(self):
        self.html_values = []
        self.cleared = False

    def setHtml(self, value):
        self.html_values.append(value)

    def clear(self):
        self.cleared = True


class FakeButton:
    def __init__(self):
        self.tooltip = ""
        self.icon = None

    def setToolTip(self, value):
        self.tooltip = value

    def setIcon(self, value):
        self.icon = value


class OverlayHarness:
    _render_current_answer_basic = DraggableOverlay._render_current_answer_basic
    update_response = DraggableOverlay.update_response
    _set_main_manual_response = DraggableOverlay._set_main_manual_response
    _current_answer_is_manual = DraggableOverlay._current_answer_is_manual
    _move_current_manual_answer_to_secondary_overlay = DraggableOverlay._move_current_manual_answer_to_secondary_overlay

    def __init__(self, show_auto=True):
        self.update_conversation_signal = FakeSignal()
        self.conversation_text = FakeConversationText()
        self.interviewer_suggestion_button = FakeButton()
        self.current_answer = ""
        self.current_answer_origin = ""
        self.current_manual_answer = ""
        self.current_manual_mode = ""
        self.show_interviewer_suggestions = show_auto
        self.last_interviewer_question = ""
        self.last_suggested_answer = ""
        self._active_auto_answer_question = ""
        self.code_overlay_values = []
        self.code_overlay_modes = []
        self.code_overlay_cleared = False

    def _show_manual_response(self, answer, mode=""):
        self.code_overlay_values.append(answer)
        self.code_overlay_modes.append(mode)

    def _show_code_response(self, answer):
        self._show_manual_response(answer, "code")

    def clear_code_answer_overlay(self):
        self.code_overlay_cleared = True

    def _apply_button_style(self, _button):
        pass


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
        self.assertEqual(overlay.current_answer_origin, "manual")
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

    def test_auto_answer_reset_metadata_clears_visible_answer(self):
        overlay = OverlayHarness(show_auto=True)
        overlay.current_answer = "Existing auto answer."
        overlay.last_suggested_answer = "Existing auto answer."
        overlay._active_auto_answer_question = "Old question"

        DraggableOverlay.update_interviewer_qa(
            overlay,
            "Next question, explain graphs.",
            "",
            False,
            True,
        )

        self.assertEqual(overlay.current_answer, "")
        self.assertEqual(overlay.last_suggested_answer, "")
        self.assertEqual(overlay._active_auto_answer_question, "")
        self.assertEqual(overlay.update_conversation_signal.values[-1], "")

    def test_code_analysis_routes_to_secondary_overlay_when_auto_answer_enabled(self):
        overlay = OverlayHarness(show_auto=True)

        DraggableOverlay.update_analysis_response(
            overlay,
            {"user_query": "Solve this", "response": "Use binary search."},
            "code",
        )

        self.assertEqual(overlay.current_answer, "")
        self.assertEqual(overlay.update_conversation_signal.values, [])
        self.assertEqual(overlay.code_overlay_values, ["Use binary search."])
        self.assertEqual(overlay.code_overlay_modes, ["code"])

    def test_code_analysis_uses_main_overlay_when_auto_answer_disabled(self):
        overlay = OverlayHarness(show_auto=False)

        DraggableOverlay.update_analysis_response(
            overlay,
            {"user_query": "Solve this", "response": "Use two pointers."},
            "code",
        )

        self.assertEqual(overlay.current_answer, "Use two pointers.")
        self.assertEqual(overlay.current_answer_origin, "manual")
        self.assertEqual(overlay.current_manual_mode, "code")
        self.assertEqual(overlay.code_overlay_values, [])
        self.assertIn("Use two pointers.", overlay.update_conversation_signal.values[-1])

    def test_general_and_text_analysis_route_to_secondary_overlay_when_auto_answer_enabled(self):
        overlay = OverlayHarness(show_auto=True)

        DraggableOverlay.update_analysis_response(
            overlay,
            {"user_query": "General", "response": "General answer."},
            "general",
        )
        DraggableOverlay.update_analysis_response(
            overlay,
            {"user_query": "Typed", "response": "Typed answer."},
            "text",
        )

        self.assertEqual(overlay.current_answer, "")
        self.assertEqual(overlay.update_conversation_signal.values, [])
        self.assertEqual(overlay.code_overlay_values, ["General answer.", "Typed answer."])
        self.assertEqual(overlay.code_overlay_modes, ["general", "text"])

    def test_auto_answer_does_not_overwrite_secondary_code_overlay(self):
        overlay = OverlayHarness(show_auto=True)

        DraggableOverlay.update_analysis_response(
            overlay,
            {"user_query": "Solve this", "response": "Code answer."},
            "code",
        )
        DraggableOverlay.update_interviewer_qa(
            overlay,
            "Explain caching.",
            "Auto answer.",
            True,
        )

        self.assertEqual(overlay.current_answer, "Auto answer.")
        self.assertEqual(overlay.current_answer_origin, "auto")
        self.assertEqual(overlay.code_overlay_values, ["Code answer."])
        self.assertEqual(overlay.code_overlay_modes, ["code"])
        self.assertIn("Auto answer.", overlay.update_conversation_signal.values[-1])

    def test_enabling_auto_answer_moves_existing_manual_answer_to_secondary_overlay(self):
        self._qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        overlay = OverlayHarness(show_auto=False)
        overlay.current_answer = "Existing general answer."
        overlay.current_answer_origin = "manual"
        overlay.current_manual_mode = "general"

        DraggableOverlay.toggle_interviewer_suggestions(overlay, True)

        self.assertTrue(overlay.show_interviewer_suggestions)
        self.assertEqual(overlay.current_answer, "")
        self.assertEqual(overlay.current_answer_origin, "")
        self.assertEqual(overlay.update_conversation_signal.values[-1], "")
        self.assertEqual(overlay.code_overlay_values, ["Existing general answer."])
        self.assertEqual(overlay.code_overlay_modes, ["general"])

    def test_enabling_auto_answer_does_not_move_visible_auto_answer(self):
        self._qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        overlay = OverlayHarness(show_auto=False)
        overlay.current_answer = "Existing auto answer."
        overlay.current_answer_origin = "auto"
        overlay.last_suggested_answer = "Existing auto answer."

        DraggableOverlay.toggle_interviewer_suggestions(overlay, True)

        self.assertEqual(overlay.current_answer, "Existing auto answer.")
        self.assertEqual(overlay.code_overlay_values, [])

    def test_clear_conversation_display_clears_secondary_code_overlay(self):
        overlay = OverlayHarness(show_auto=True)
        overlay.current_answer = "Main answer."
        overlay.code_overlay_values.append("Code answer.")

        DraggableOverlay.clear_conversation_display(overlay)

        self.assertEqual(overlay.current_answer, "")
        self.assertTrue(overlay.code_overlay_cleared)
        self.assertTrue(overlay.conversation_text.cleared)

    def test_code_answer_overlay_has_main_window_resize_handles(self):
        self._qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        overlay = CodeAnswerOverlay()

        self.assertEqual(
            sorted(handle.position for handle in overlay.handles),
            sorted([
                "top-left", "top-right", "bottom-left", "bottom-right",
                "top", "right", "bottom", "left",
            ]),
        )

        overlay.setGeometry(100, 100, 720, 480)
        overlay.start_resize("bottom-right", QtCore.QPoint(820, 580))
        overlay.do_resize(QtCore.QPoint(920, 680))
        overlay.end_resize()

        self.assertEqual(overlay.width(), 820)
        self.assertEqual(overlay.height(), 580)
        self.assertTrue(overlay._user_resized)

        overlay.start_resize("top-left", QtCore.QPoint(100, 100))
        overlay.do_resize(QtCore.QPoint(2000, 2000))
        overlay.end_resize()

        self.assertEqual(overlay.width(), overlay.minimumWidth())
        self.assertEqual(overlay.height(), overlay.minimumHeight())


if __name__ == "__main__":
    unittest.main()
