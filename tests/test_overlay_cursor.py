"""Native boundary tests; simulated APIs never install hooks on the user's desktop."""
import ctypes
from ctypes import wintypes
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import Mock
from PyQt6 import QtWidgets
from overlay_cursor import WindowsInput, OverlayCursorMode, MSLLHOOKSTRUCT, LAYERED, TRANSPARENT


class NativeInputTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.styles = {0x100000001: LAYERED | 0x8000000, 0x100000002: LAYERED}
        self.api.GetWindowLongW.side_effect = lambda hwnd, _: self.styles.get(hwnd, 0)
        self.api.SetWindowLongW.side_effect = self.set_style
        self.api.IsWindow.return_value = True
        self.api.IsWindowVisible.return_value = True
        self.api.GetAsyncKeyState.return_value = 0
        self.api.SetWindowsHookExW.return_value = 0x100000009
        self.api.CallNextHookEx.return_value = 7
        self.api.PostMessageW.return_value = True
        self.backend = WindowsInput(self.api)
        self.backend.start()
        self.backend.update(set(self.styles))

    def set_style(self, hwnd, index, style):
        old = self.styles[hwnd]
        self.styles[hwnd] = style
        return old

    def test_stop_restores_interception_before_removing_hook(self):
        def unhook(handle):
            self.assertTrue(all(not s & TRANSPARENT for s in self.styles.values()))
            return True
        self.api.UnhookWindowsHookEx.side_effect = unhook
        self.backend.stop()
        self.assertEqual(self.styles[0x100000001], LAYERED | 0x8000000)
        self.assertIsNone(self.backend.handle)

    def test_wheel_preserves_signed_coordinates_delta_and_modifiers(self):
        self.api.GetAsyncKeyState.side_effect = lambda vk: 0x8000 if vk == 17 else 0
        self.backend.wheel(0x100000001, 0x20e, 0xff880000, -100, -50)
        self.api.PostMessageW.assert_called_once_with(0x100000001, 0x20e, 0xff880008,
                                                     ((-50 & 0xffff) << 16) | (-100 & 0xffff))

    def test_window_above_overlay_prevents_interception(self):
        self.api.WindowFromPoint.return_value = 99
        self.api.GetAncestor.return_value = 99
        self.api.GetTopWindow.return_value = 99
        self.assertIsNone(self.backend.target_at(wintypes.POINT(50, 60)))

    def test_topmost_registered_overlay_is_selected_with_64_bit_handle(self):
        self.api.WindowFromPoint.return_value = 99
        self.api.GetAncestor.return_value = 99
        self.api.GetTopWindow.return_value = 0x100000001
        def rectangle(hwnd, pointer):
            rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = -100, 0, 100, 100
            return True
        self.api.GetWindowRect.side_effect = rectangle
        self.assertEqual(self.backend.target_at(wintypes.POINT(-50, 60)), 0x100000001)
        self.backend.hit_tests[0x100000001] = lambda point, rect: point.y >= 80
        self.api.GetWindow.return_value = 99
        self.assertIsNone(self.backend.target_at(wintypes.POINT(-50, 60)))
        self.assertEqual(self.backend.target_at(wintypes.POINT(-50, 90)), 0x100000001)

    def test_failed_wheel_consumes_event_and_restores_ordinary_input(self):
        self.backend.target_at = lambda point: 0x100000001
        self.api.PostMessageW.return_value = False
        event = MSLLHOOKSTRUCT()
        event.pt.x, event.pt.y, event.mouseData = 50, 60, 0x780000
        self.assertEqual(self.backend._hook(0, 0x20a, ctypes.addressof(event)), 1)
        self.assertIsNone(self.backend.handle)
        self.assertTrue(all(not s & TRANSPARENT for s in self.styles.values()))
        self.assertIn('wheel', self.backend.error)

    def test_native_button_callback_restores_overlay_before_passing_input(self):
        self.backend.target_at = lambda point: 0x100000001
        event = MSLLHOOKSTRUCT()
        event.pt.x, event.pt.y = 50, 60
        self.assertEqual(self.backend._hook(0, 0x201, ctypes.addressof(event)), 7)
        self.assertFalse(self.styles[0x100000001] & TRANSPARENT)

    def test_removed_or_nonlayered_windows_do_not_remain_click_through(self):
        self.backend.update({0x100000002})
        self.assertFalse(self.styles[0x100000001] & TRANSPARENT)
        self.styles[0x100000002] = TRANSPARENT
        self.backend.update({0x100000002})
        self.assertFalse(self.styles[0x100000002] & TRANSPARENT)

    def test_failed_restoration_keeps_hook_and_handles_until_retry_succeeds(self):
        self.api.SetWindowLongW.side_effect = OSError('temporary style failure')
        self.assertFalse(self.backend.stop())
        self.assertTrue(self.backend.windows)
        self.assertIsNotNone(self.backend.handle)
        self.api.UnhookWindowsHookEx.assert_not_called()
        self.api.SetWindowLongW.side_effect = self.set_style
        self.assertTrue(self.backend.stop())
        self.assertIsNone(self.backend.handle)
        self.assertTrue(all(not s & TRANSPARENT for s in self.styles.values()))


class CursorModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_mode_is_off_by_default_and_failed_hook_never_enables_it(self):
        backend = Mock()
        backend.start.side_effect = OSError('hook unavailable')
        mode = OverlayCursorMode(self.app, backend)
        self.addCleanup(mode.deleteLater)
        self.assertFalse(mode.enabled)
        self.assertFalse(mode.set_enabled(True))
        backend.update.assert_not_called()
        self.assertEqual(mode.last_error, 'hook unavailable')

    def test_disabling_restores_input_and_stops_updates(self):
        backend = Mock(error='')
        mode = OverlayCursorMode(self.app, backend)
        self.addCleanup(mode.deleteLater)
        self.assertTrue(mode.set_enabled(True))
        self.assertTrue(mode.timer.isActive())
        self.assertFalse(mode.set_enabled(False))
        self.assertFalse(mode.timer.isActive())
        backend.stop.assert_called_once()

    def test_mode_turns_off_when_gui_refresh_has_stalled(self):
        import time
        backend = Mock(error='')
        mode = OverlayCursorMode(self.app, backend)
        self.addCleanup(mode.deleteLater)
        self.assertTrue(mode.set_enabled(True))
        mode.last_refresh = time.monotonic() - 1
        mode.refresh()
        self.assertFalse(mode.enabled)
        self.assertIn('paused', mode.last_error)
