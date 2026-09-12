import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from overlay_cursor import MouseRouting


class Port:
    def __init__(self):
        self.transparent = {10: True, 20: True}
        self.wheels = []
    def capture(self, hwnd):
        self.transparent[hwnd] = False
    def release(self, hwnd):
        self.transparent[hwnd] = True
    def wheel(self, hwnd, message, data, x, y):
        self.wheels.append((hwnd, message, data, x, y))


class MouseRoutingTests(unittest.TestCase):
    def setUp(self):
        self.port = Port()
        self.router = MouseRouting(self.port)

    def test_click_switches_to_native_overlay_input_until_release_is_processed(self):
        self.assertFalse(self.router.route(0x201, 0, 10, 50, 60, 1.0))
        self.assertFalse(self.port.transparent[10])
        self.router.route(0x202, 0, 10, 50, 60, 1.1)
        self.assertFalse(self.port.transparent[10])
        self.router.settle(1.3)
        self.assertTrue(self.port.transparent[10])

    def test_drag_started_outside_does_not_get_stolen_when_crossing_overlay(self):
        self.router.route(0x201, 0, None, 5, 5, 1.0)
        self.router.route(0x200, 0, 10, 50, 60, 1.1)
        self.router.route(0x202, 0, 10, 50, 60, 1.2)
        self.assertTrue(self.port.transparent[10])

    def test_overlay_drag_retains_its_window_outside_bounds(self):
        self.router.route(0x201, 0, 10, 50, 60, 1.0)
        self.router.route(0x200, 0, 20, 500, 600, 1.1)
        self.assertFalse(self.port.transparent[10])
        self.assertTrue(self.port.transparent[20])
        self.router.route(0x202, 0, None, 900, 900, 1.2)
        self.router.settle(1.4)
        self.assertTrue(self.port.transparent[10])

    def test_wheel_is_suppressed_and_posted_only_to_overlay(self):
        self.assertTrue(self.router.route(0x20a, 0xff880000, 10, -50, 60, 1.0))
        self.assertEqual(self.port.wheels, [(10, 0x20a, 0xff880000, -50, 60)])
        self.assertFalse(self.port.transparent[10])
        self.router.settle(1.2)
        self.assertTrue(self.port.transparent[10])

    def test_wheel_outside_overlay_is_untouched(self):
        self.assertFalse(self.router.route(0x20a, 0x780000, None, 5, 5, 1.0))
        self.assertEqual(self.port.wheels, [])

    def test_multiple_buttons_keep_capture_until_last_release(self):
        self.router.route(0x201, 0, 10, 50, 60, 1.0)
        self.router.route(0x204, 0, 10, 50, 60, 1.1)
        self.router.route(0x202, 0, None, 500, 600, 1.2)
        self.router.settle(2.0)
        self.assertFalse(self.port.transparent[10])
        self.router.route(0x205, 0, None, 500, 600, 2.1)
        self.router.settle(2.3)
        self.assertTrue(self.port.transparent[10])

    def test_double_click_does_not_release_during_second_press(self):
        self.router.route(0x201, 0, 10, 50, 60, 1.0)
        self.router.route(0x202, 0, 10, 50, 60, 1.05)
        self.router.route(0x201, 0, 10, 50, 60, 1.1)
        self.router.settle(1.3)
        self.assertFalse(self.port.transparent[10])

    def test_wheel_during_external_drag_is_not_redirected(self):
        self.router.route(0x201, 0, None, 5, 5, 1.0)
        self.assertFalse(self.router.route(0x20a, 0x780000, 10, 50, 60, 1.1))
        self.assertEqual(self.port.wheels, [])
