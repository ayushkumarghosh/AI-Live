import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from overlay import CodeAnswerOverlay, DraggableOverlay


class FakeSignal:
    def __init__(self):
        self.values = []

    def emit(self, *values):
        self.values.append(values[0] if len(values) == 1 else values)


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
        self.auto_answer_toggled_signal = FakeSignal()
        self.conversation_text = FakeConversationText()
        self.interviewer_suggestion_button = FakeButton()
        self.current_answer = ""
        self.current_answer_origin = ""
        self.current_manual_answer = ""
        self.current_manual_mode = ""
        self.show_interviewer_suggestions = show_auto
        self.last_suggested_answer = ""
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
    def test_reset_starts_a_new_visible_answer(self):
        overlay = OverlayHarness(show_auto=True)
        overlay.current_answer = "Old topic answer."
        overlay.current_answer_origin = "auto"

        DraggableOverlay.apply_realtime_answer_update(
            overlay,
            "reset",
            "New topic answer.",
        )

        self.assertEqual(overlay.current_answer, "New topic answer.")
        self.assertEqual(overlay.current_answer_origin, "auto")
        self.assertEqual(overlay.last_suggested_answer, "New topic answer.")
        self.assertIn("New topic answer.", overlay.update_conversation_signal.values[-1])
        self.assertNotIn("Old topic answer.", overlay.update_conversation_signal.values[-1])

    def test_related_followup_appends_one_new_paragraph(self):
        overlay = OverlayHarness(show_auto=True)
        overlay.current_answer = "I would start with a cache-aside design."
        overlay.current_answer_origin = "auto"

        DraggableOverlay.apply_realtime_answer_update(
            overlay,
            "append",
            "For invalidation, I would combine TTLs with event-driven eviction.",
        )

        self.assertEqual(
            overlay.current_answer,
            "I would start with a cache-aside design.\n\n"
            "For invalidation, I would combine TTLs with event-driven eviction.",
        )
        self.assertIn("For invalidation", overlay.update_conversation_signal.values[-1])

    def test_same_topic_correction_is_appended_without_rewriting_previous_text(self):
        overlay = OverlayHarness(show_auto=True)
        overlay.current_answer = "A B-tree keeps keys ordered."

        DraggableOverlay.apply_realtime_answer_update(
            overlay,
            "append",
            "More precisely, database indexes commonly use B+ trees so leaf nodes can be scanned efficiently.",
        )

        self.assertTrue(overlay.current_answer.startswith("A B-tree keeps keys ordered.\n\nMore precisely,"))

    def test_no_update_preserves_visible_answer(self):
        overlay = OverlayHarness(show_auto=True)
        overlay.current_answer = "Existing answer."

        DraggableOverlay.apply_realtime_answer_update(overlay, "no_update", "")

        self.assertEqual(overlay.current_answer, "Existing answer.")
        self.assertEqual(overlay.update_conversation_signal.values, [])

    def test_append_strips_an_exact_repeated_visible_answer_prefix(self):
        overlay = OverlayHarness(show_auto=True)
        overlay.current_answer = "Existing answer."

        DraggableOverlay.apply_realtime_answer_update(
            overlay,
            "append",
            "Existing answer.\n\nOnly this sentence is new.",
        )

        self.assertEqual(overlay.current_answer, "Existing answer.\n\nOnly this sentence is new.")
        self.assertEqual(overlay.current_answer.count("Existing answer."), 1)

    def test_auto_answer_disabled_ignores_realtime_update(self):
        overlay = OverlayHarness(show_auto=False)
        overlay.current_answer = "Existing manual answer."

        DraggableOverlay.apply_realtime_answer_update(overlay, "reset", "Auto answer.")

        self.assertEqual(overlay.current_answer, "Existing manual answer.")
        self.assertEqual(overlay.update_conversation_signal.values, [])

    def test_manual_response_replaces_visible_answer_without_question_labels(self):
        overlay = OverlayHarness(show_auto=False)

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
        self.assertNotIn("Second question?", rendered)

    def test_manual_analysis_routes_to_secondary_overlay_when_auto_answer_enabled(self):
        overlay = OverlayHarness(show_auto=True)

        DraggableOverlay.update_analysis_response(
            overlay,
            {"user_query": "Solve this", "response": "Use binary search."},
            "code",
        )
        DraggableOverlay.update_analysis_response(
            overlay,
            {"user_query": "Typed", "response": "Typed answer."},
            "text",
        )

        self.assertEqual(overlay.current_answer, "")
        self.assertEqual(overlay.code_overlay_values, ["Use binary search.", "Typed answer."])
        self.assertEqual(overlay.code_overlay_modes, ["code", "text"])

    def test_manual_analysis_uses_main_overlay_when_auto_answer_disabled(self):
        overlay = OverlayHarness(show_auto=False)

        DraggableOverlay.update_analysis_response(
            overlay,
            {"user_query": "Solve this", "response": "Use two pointers."},
            "code",
        )

        self.assertEqual(overlay.current_answer, "Use two pointers.")
        self.assertEqual(overlay.current_answer_origin, "manual")
        self.assertIn("Use two pointers.", overlay.update_conversation_signal.values[-1])

    def test_enabling_auto_answer_moves_manual_answer_and_emits_runtime_toggle(self):
        self._qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        overlay = OverlayHarness(show_auto=False)
        overlay.current_answer = "Existing general answer."
        overlay.current_answer_origin = "manual"
        overlay.current_manual_mode = "general"

        DraggableOverlay.toggle_interviewer_suggestions(overlay, True)

        self.assertTrue(overlay.show_interviewer_suggestions)
        self.assertEqual(overlay.current_answer, "")
        self.assertEqual(overlay.code_overlay_values, ["Existing general answer."])
        self.assertEqual(overlay.auto_answer_toggled_signal.values, [True])

    def test_reenabling_auto_answer_restores_the_last_committed_auto_answer(self):
        self._qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        overlay = OverlayHarness(show_auto=False)
        overlay.current_answer = "Temporary manual answer."
        overlay.current_answer_origin = "manual"
        overlay.last_suggested_answer = "Earlier combined auto answer."

        DraggableOverlay.toggle_interviewer_suggestions(overlay, True)

        self.assertEqual(overlay.current_answer, "Earlier combined auto answer.")
        self.assertEqual(overlay.current_answer_origin, "auto")

    def test_clear_conversation_display_clears_main_and_secondary_answers(self):
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
            sorted(
                [
                    "top-left",
                    "top-right",
                    "bottom-left",
                    "bottom-right",
                    "top",
                    "right",
                    "bottom",
                    "left",
                ]
            ),
        )

        overlay.setGeometry(100, 100, 720, 480)
        overlay.start_resize("bottom-right", QtCore.QPoint(820, 580))
        overlay.do_resize(QtCore.QPoint(920, 680))
        overlay.end_resize()
        self.assertEqual(overlay.width(), 820)
        self.assertEqual(overlay.height(), 580)


if __name__ == "__main__":
    unittest.main()
