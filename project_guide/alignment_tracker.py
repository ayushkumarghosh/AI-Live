"""Follow the selected VS Code editor while a guidance step is displayed."""
import ctypes
import os
import threading
from ctypes import wintypes

import numpy as np
from PyQt6 import QtCore, QtGui

from .editor_alignment import WindowsEditorLocator, text_row_center
from .files import GuideError


def logical_viewport(bounds):
    """Convert UIA physical pixels using the monitor's physical and Qt origins."""
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD),
                    ('device', wintypes.WCHAR * 32)]

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    monitor = user32.MonitorFromWindow(bounds['hwnd'], 2)
    info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    screen = next((s for s in QtGui.QGuiApplication.screens() if s.name() == info.device), None)
    if screen is None:
        return None
    origin, scale = screen.geometry(), screen.devicePixelRatio()
    left, top, right, bottom = bounds['viewport']
    rect = QtCore.QRect(round(origin.x() + (left - info.monitor.left) / scale),
                        round(origin.y() + (top - info.monitor.top) / scale),
                        round((right - left) / scale), round((bottom - top) / scale))
    return screen, rect


def measure_gutter(screen, viewport, pitch=24):
    """Measure gray line-number ink, excluding colorful breakpoint markers."""
    area = viewport.intersected(screen.geometry())
    if area.height() < pitch * 4:
        return None
    image = screen.grabWindow(0).toImage()
    if image.isNull():
        return None
    image = image.scaled(screen.geometry().size()).convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes())
    pixels = np.frombuffer(pointer, dtype=np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)
    top = area.top() - screen.geometry().top()
    # VS Code's standard gutter: exclude the glyph margin and code columns.
    left = viewport.left() - screen.geometry().left() + 24
    right = min(left + 41, image.width())
    if left < 0 or right <= left:
        return None
    center = text_row_center(pixels[top:top + area.height(), left:right, :3], pitch)
    return None if center is None else area.top() + center


class EditorAlignmentTracker(QtCore.QObject):
    measured = QtCore.pyqtSignal(int, object)

    def __init__(self, panel, state_provider):
        super().__init__(panel)
        self.panel = panel
        self.state_provider = state_provider
        self._generation = 0
        self._inflight = False
        self._last_fit = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.request)
        self.measured.connect(self.receive)

    def start(self):
        self.status('Finding VS Code editor...')
        self._last_fit = None
        if os.name != 'nt':
            self.status('Editor alignment is available on Windows.')
            return
        if not self.timer.isActive():
            self._generation += 1
            self._last_fit = None
            self.timer.start()
        self.request()

    def status(self, message):
        self.panel.banner.setText(message)
        self.panel.banner.setToolTip(message)
        self.panel.banner.show()

    def stop(self):
        self.timer.stop()
        self._generation += 1
        self._last_fit = None

    def request(self):
        if self._inflight or not self.panel.isVisible():
            return
        if self.panel._guidance_html is None:
            self.stop()
            return
        try:
            root, active, workspace_name = self.state_provider()
        except (GuideError, OSError, ValueError) as exc:
            self.stop()
            self.panel.release_editor()
            self.status('Cannot fit editor: ' + str(exc))
            return
        self._inflight = True
        generation = self._generation

        def measure():
            locator = None
            result = None
            try:
                locator = WindowsEditorLocator()
                result = locator.locate(root, active, workspace_name)
            except ImportError as exc:
                result = {'error': 'Editor alignment dependency missing: ' + str(exc)
                          + '. Install requirements.txt with the Python running AI-Live.',
                          'fatal': True}
            except Exception as exc:
                result = {'error': 'Cannot read VS Code editor: ' + str(exc)}
            finally:
                if locator:
                    try:
                        locator.close()
                    except Exception:
                        pass
            try:
                self.measured.emit(generation, result)
            except RuntimeError:
                pass  # The application has closed while the native call was pending.

        threading.Thread(target=measure, daemon=True).start()

    def receive(self, generation, bounds):
        self._inflight = False
        if generation != self._generation or not self.timer.isActive() or not self.panel.isVisible():
            return
        if self.panel._guidance_html is None:
            return
        if bounds and 'error' in bounds:
            self.status(bounds['error'])
            if bounds.get('fatal'):
                self.stop()
            return
        if not bounds:
            self.status('Cannot find the selected VS Code editor. Open its file in the connected workspace.')
            return
        if not bounds['foreground']:
            self.status('Switch to VS Code to fit the guide to its editor.')
            return
        try:
            converted = logical_viewport(bounds)
            if converted is None:
                self.status('Cannot locate the editor display.')
                return
            screen, viewport = converted
            center = measure_gutter(screen, viewport)
            native_row = bounds.get('row')
            if center is None and native_row:
                scale = screen.devicePixelRatio()
                if abs(native_row[5] / scale - 24) < 0.5:
                    center = viewport.top() + (native_row[4] + native_row[5] / 2
                                               - bounds['viewport'][1]) / scale
        except (OSError, ValueError, RuntimeError) as exc:
            self.status('Cannot measure editor: ' + str(exc))
            return  # Monitor/window disappeared between measurement and delivery.
        if center is None:
            self.status('Cannot detect editor rows. Show line numbers with 24 px line height in VS Code.')
            return
        # Keep all controls on screen if the editor window extends off a monitor.
        rect = viewport.intersected(screen.availableGeometry())
        if rect.width() < 420 or rect.height() < 280:
            self.status('Editor area is too small to fit the guide (minimum 420 x 280).')
            return
        fit = (rect, round(center, 1), 24)
        if fit != self._last_fit or self.panel._editor_fit is None:
            self.panel.fit_editor(*fit)
            self._last_fit = fit
        self.status('Fitted to editor · guidance between code rows')
