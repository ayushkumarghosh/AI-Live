"""Experimental hover pass-through with native overlay click/drag handling."""
import ctypes
from ctypes import wintypes
import sys
import time
from PyQt6 import QtCore, QtWidgets

TRANSPARENT = 0x20
LAYERED = 0x80000
WHEELS = (0x020A, 0x020E)
DOWN = {0x0201: 1, 0x0204: 2, 0x0207: 4, 0x020B: 8}
UP = {0x0202: 1, 0x0205: 2, 0x0208: 4, 0x020C: 8}


class MouseRouting:
    """Track whole gestures, including drags beginning outside an overlay."""
    def __init__(self, port):
        self.port = port
        self.buttons = set()
        self.active = None
        self.release_at = None

    def route(self, message, data, target, x, y, now):
        if message in DOWN:
            button = (DOWN[message], data >> 16 if message == 0x020B else 0)
            if not self.buttons:
                if self.active and self.active != target:
                    self.port.release(self.active)
                    self.active = None
                if target:
                    self.port.capture(target)
                    self.active = target
            self.buttons.add(button)
            self.release_at = None
        elif message in UP:
            button = (UP[message], data >> 16 if message == 0x020C else 0)
            self.buttons.discard(button)
            if not self.buttons and self.active:
                # Allow native release/clicked/context-menu handling to finish.
                self.release_at = now + 0.12
        elif message in WHEELS:
            if self.buttons and not self.active:
                return False
            target = self.active if self.buttons else target
            if target:
                if self.active and self.active != target:
                    self.port.release(self.active)
                self.port.capture(target)
                self.active = target
                self.port.wheel(target, message, data, x, y)
                if not self.buttons:
                    self.release_at = now + 0.12
                return True
        return False

    def settle(self, now):
        if not self.buttons and self.active and self.release_at is not None and now >= self.release_at:
            self.port.release(self.active)
            self.active = self.release_at = None


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('pt', wintypes.POINT), ('mouseData', wintypes.DWORD),
                ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class WindowsInput:
    def __init__(self, api=None):
        self.api = api if api is not None else ctypes.WinDLL('user32', use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)
        signatures = {
            'SetWindowsHookExW': ([ctypes.c_int, self.callback_type, wintypes.HINSTANCE, wintypes.DWORD], wintypes.HANDLE),
            'CallNextHookEx': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t], ctypes.c_ssize_t),
            'UnhookWindowsHookEx': ([wintypes.HANDLE], wintypes.BOOL),
            'GetWindowLongW': ([wintypes.HWND, ctypes.c_int], ctypes.c_long),
            'SetWindowLongW': ([wintypes.HWND, ctypes.c_int, ctypes.c_long], ctypes.c_long),
            'GetWindowRect': ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            'GetTopWindow': ([wintypes.HWND], wintypes.HWND),
            'GetWindow': ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            'WindowFromPoint': ([wintypes.POINT], wintypes.HWND),
            'GetAncestor': ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            'IsWindow': ([wintypes.HWND], wintypes.BOOL),
            'IsWindowVisible': ([wintypes.HWND], wintypes.BOOL),
            'GetAsyncKeyState': ([ctypes.c_int], ctypes.c_short),
            'PostMessageW': ([wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        self.handle = None
        self.callback = self.callback_type(self._hook)
        self.windows = set()
        self.hit_tests = {}
        self.button_routes = {}
        self.button_gesture = None
        self.error = ''
        self.routing = MouseRouting(self)

    def start(self):
        if self.handle:
            return
        self.error = ''
        self.routing = MouseRouting(self)
        for vk, button in ((1, 1), (2, 2), (4, 4), (5, 8), (6, 8)):
            if self.api.GetAsyncKeyState(vk) & 0x8000:
                self.routing.buttons.add((button, vk - 4 if button == 8 else 0))
        self.handle = self.api.SetWindowsHookExW(14, self.callback, None, 0)
        if not self.handle:
            raise OSError('Windows could not install the mouse hook.')

    def _transparent(self, hwnd, enabled):
        if not self.api.IsWindow(hwnd):
            return
        style = self.api.GetWindowLongW(hwnd, -20)
        desired = style | TRANSPARENT if enabled else style & ~TRANSPARENT
        if style != desired:
            ctypes.set_last_error(0)
            result = self.api.SetWindowLongW(hwnd, -20, desired)
            if not result and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())

    def capture(self, hwnd):
        self._transparent(hwnd, False)

    def release(self, hwnd):
        if self.handle and hwnd in self.windows:
            self._transparent(hwnd, True)

    def update(self, windows):
        if not self.handle:
            return
        # Qt owns per-pixel compositing; never add WS_EX_LAYERED ourselves.
        eligible = {hwnd for hwnd in windows if self.api.GetWindowLongW(hwnd, -20) & LAYERED}
        for hwnd in self.windows - eligible:
            self._transparent(hwnd, False)
        self.windows = eligible
        for hwnd in self.windows:
            self._transparent(hwnd, hwnd != self.routing.active)
        self.routing.settle(time.monotonic())

    def target_at(self, point):
        # An unrelated window above our overlays must keep its input.
        actual = self.api.GetAncestor(self.api.WindowFromPoint(point), 2)
        hwnd = self.api.GetTopWindow(None)
        for _ in range(256):
            if not hwnd:
                break
            if hwnd in self.windows and self.api.IsWindowVisible(hwnd):
                rect = wintypes.RECT()
                if (self.api.GetWindowRect(hwnd, ctypes.byref(rect))
                        and rect.left <= point.x < rect.right and rect.top <= point.y < rect.bottom):
                    hit_test = self.hit_tests.get(hwnd)
                    if hit_test is None or hit_test(point, rect):
                        return hwnd
            if hwnd == actual:
                break
            hwnd = self.api.GetWindow(hwnd, 2)
        return None

    def wheel(self, hwnd, message, data, x, y):
        modifiers = 0
        for vk, flag in ((1, 1), (2, 2), (16, 4), (17, 8), (4, 16), (5, 32), (6, 64)):
            if self.api.GetAsyncKeyState(vk) & 0x8000:
                modifiers |= flag
        wparam = (data & 0xffff0000) | modifiers
        position = (x & 0xffff) | ((y & 0xffff) << 16)
        if not self.api.PostMessageW(hwnd, message, wparam, position):
            raise OSError('Could not deliver wheel input to the overlay.')

    def _hook(self, code, message, pointer):
        if code >= 0 and self.handle:
            try:
                if message in DOWN or message in UP or message in WHEELS:
                    event = MSLLHOOKSTRUCT.from_address(pointer)
                    target = self.target_at(event.pt)
                    if message == 0x0201 and target in self.button_routes and not self.routing.buttons:
                        route = self.button_routes[target]
                        self.button_gesture = route
                        route('down', event.pt.x, event.pt.y)
                        return 1
                    if message == 0x0202 and self.button_gesture:
                        route, self.button_gesture = self.button_gesture, None
                        route('up', event.pt.x, event.pt.y)
                        return 1
                    if self.routing.route(message, event.mouseData, target, event.pt.x, event.pt.y, time.monotonic()):
                        return 1
            except Exception as exc:
                # Restore ordinary input and swallow this uncertain event. Never
                # propagate exceptions across the ctypes/native callback boundary.
                self.error = str(exc)
                self.stop()
                return 1
        return self.api.CallNextHookEx(self.handle, code, message, pointer)

    def stop(self):
        if self.button_gesture:
            route, self.button_gesture = self.button_gesture, None
            try:
                route('cancel', 0, 0)
            except Exception:
                pass  # A destroyed Qt receiver must not prevent native cleanup.
        failed = set()
        for hwnd in tuple(self.windows):
            try:
                self._transparent(hwnd, False)
            except OSError as exc:
                failed.add(hwnd)
                self.error = 'Could not restore overlay input: ' + str(exc)
        self.windows = failed
        if failed:
            # Keep interception alive and retry; never advertise off while a
            # visible window remains transparent with no protecting hook.
            return False
        if self.handle:
            self.api.UnhookWindowsHookEx(self.handle)
            self.handle = None
        self.routing = MouseRouting(self)
        return True


class OverlayCursorMode(QtCore.QObject):
    changed = QtCore.pyqtSignal(bool)

    def __init__(self, app, backend=None, windows_provider=None):
        super().__init__(app)
        self.app, self.backend = app, backend
        self.windows_provider = windows_provider
        self.enabled = False
        self.last_error = ''
        self.last_refresh = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.refresh)
        app.aboutToQuit.connect(self.close)

    def set_enabled(self, enabled):
        if enabled == self.enabled:
            return self.enabled
        if not enabled:
            self.close()
            return self.enabled
        try:
            if self.backend is None:
                if sys.platform != 'win32' or self.app.platformName() != 'windows':
                    raise OSError('Underlying cursor mode requires the Windows desktop.')
                self.backend = WindowsInput()
            self.backend.start()
            self.enabled = True
            self.last_error = ''
            self.last_refresh = time.monotonic()
            self.refresh()
            if self.enabled:
                self.timer.start()
                self.changed.emit(True)
        except (OSError, RuntimeError) as exc:
            self.last_error = str(exc)
            self.close()
        return self.enabled

    def refresh(self):
        if not self.enabled:
            return
        try:
            now = time.monotonic()
            if self.last_refresh is not None and now - self.last_refresh > 0.25:
                raise OSError('Cursor mode paused after an application stall; normal input restored.')
            self.last_refresh = now
            if self.backend.error:
                raise OSError(self.backend.error)
            candidates = (self.windows_provider() if self.windows_provider else
                          [w for w in self.app.topLevelWidgets()
                           if w.property('uses_overlay_opacity') and not w.property('fitted_input_routing')])
            visible = [w for w in candidates if w.isVisible() and not w.isMinimized()]
            windows = {int(w.winId()) for w in visible}
            self.backend.hit_tests = {int(w.winId()): w.fitted_native_hit_test for w in visible
                                      if w.property('fitted_input_routing')}
            self.backend.button_routes = {int(w.winId()): w.queue_fitted_button for w in visible
                                          if w.property('fitted_input_routing')}
            self.backend.update(windows)
        except (OSError, RuntimeError) as exc:
            self.last_error = str(exc)
            self.close()

    def close(self):
        self.timer.stop()
        if self.backend and self.backend.stop() is False:
            self.last_error = self.backend.error
            self.enabled = True
            self.timer.start()
            self.changed.emit(True)
            return
        was_enabled, self.enabled = self.enabled, False
        if was_enabled:
            self.changed.emit(False)


def install_cursor_mirroring(app):
    """The mode is opt-in, shared by every registered overlay in the app."""
    if not hasattr(app, '_overlay_cursor_mode'):
        app._overlay_cursor_mode = OverlayCursorMode(app)
    return app._overlay_cursor_mode
