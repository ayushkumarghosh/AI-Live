import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets
from overlay import (DraggableOverlay, InputOverlay, CodeAnswerOverlay,
                     PrivateTextContextPopup, PrivateResumeMenuPopup)
from project_guide.ui import ProjectGuidePanel


class OverlayOpacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.main = DraggableOverlay()
        self.windows = [self.main]

    def tearDown(self):
        self.main.change_opacity(90)
        for window in reversed(self.windows):
            window.close()
            window.deleteLater()

    def make_overlays(self):
        windows = [InputOverlay(self.main), CodeAnswerOverlay(self.main),
                   ProjectGuidePanel(self.main),
                   PrivateTextContextPopup(self.main.conversation_text),
                   PrivateResumeMenuPopup(self.main, "resume.pdf")]
        self.windows.extend(windows)
        return windows

    def test_slider_updates_all_existing_overlays(self):
        self.make_overlays()
        for value in (20, 65, 100):
            self.main.header_opacity_slider.setValue(value)
            for window in self.windows:
                with self.subTest(window=type(window).__name__, value=value):
                    self.assertAlmostEqual(window.windowOpacity(), value / 100, delta=0.005)
            self.assertEqual(self.main.opacity_slider.value(), value)

    def test_new_overlays_inherit_current_slider_value(self):
        self.main.opacity_slider.setValue(40)
        for window in self.make_overlays():
            with self.subTest(window=type(window).__name__):
                self.assertAlmostEqual(window.windowOpacity(), 0.4, delta=0.005)
        self.assertEqual(self.main.header_opacity_slider.value(), 40)
