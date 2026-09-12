import unittest
import numpy as np

from project_guide.editor_alignment import editor_geometry, text_row_center


class EditorGeometryTests(unittest.TestCase):
    def test_measurements_reuse_one_accessibility_connection(self):
        import queue
        from unittest.mock import patch
        from project_guide.alignment_tracker import EditorAlignmentTracker
        requests = queue.Queue()
        requests.put((1, 'root', 'a.py', None))
        requests.put((1, 'root', 'b.py', None))
        requests.put(None)
        results = []
        with patch('project_guide.alignment_tracker.WindowsEditorLocator') as factory:
            EditorAlignmentTracker.measure_loop(requests, lambda *args: results.append(args))
        factory.assert_called_once()
        self.assertEqual(factory.return_value.locate.call_count, 2)
        factory.return_value.close.assert_called_once()
        self.assertEqual(len(results), 2)

    def test_uses_editor_content_not_sidebar_tabs_or_minimap(self):
        geometry = editor_geometry((580, 88, 1494, 850), (650, 424, 1420, 448))
        self.assertEqual(geometry, (650, 88, 770, 762, 424, 24))

    def test_rejects_hidden_caret_and_non_editor_rectangles(self):
        for row in [(0, 0, 0, 0), (580, 88, 1400, 89), (500, 100, 600, 124)]:
            with self.subTest(row=row):
                self.assertIsNone(editor_geometry((580, 88, 1494, 850), row))

    def test_measures_text_phase_after_partial_scrolling_with_a_colored_breakpoint(self):
        gutter = np.full((240, 50, 3), 30, dtype=np.uint8)
        for center in range(7, 240, 24):
            gutter[max(0, center - 4):center + 5, 20:27] = 130
        gutter[35:48, 2:14] = [240, 40, 40]
        self.assertAlmostEqual(text_row_center(gutter), 7, delta=0.15)

    def test_blank_gutter_cannot_claim_alignment(self):
        self.assertIsNone(text_row_center(np.full((240, 50, 3), 30)))
        self.assertIsNone(text_row_center(np.full((240, 50, 3), 130)))

    def test_one_line_file_can_still_align(self):
        gutter = np.full((240, 50, 3), 30, dtype=np.uint8)
        gutter[3:12, 20:24] = 130
        self.assertAlmostEqual(text_row_center(gutter), 7, delta=0.1)
