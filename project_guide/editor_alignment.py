"""Read VS Code's native editor rectangles without changing editor contents or focus."""
import ctypes
from pathlib import Path
from ctypes import wintypes

import numpy as np


def text_row_center(image, pitch=24):
    """Find the phase of VS Code's gray line-number glyphs in a gutter image.

    The image stays local and is discarded after measurement. Combining many
    rows avoids letting the caret, a breakpoint, or one digit set the phase.
    """
    rgb = np.asarray(image, dtype=float)[:, :, :3]
    low, high = rgb.min(axis=2), rgb.max(axis=2)
    ink = (high - low < 25) & (low > 65) & (high < 225)
    density = ink.sum(axis=1).astype(float)
    if np.count_nonzero(density) < 4 or density.sum() < 12:
        return None
    phase = np.arange(len(density)) * (2 * np.pi / pitch)
    wave = np.sum(density * np.exp(1j * phase))
    if abs(wave) / density.sum() < 0.35:
        return None
    return float(np.angle(wave) * pitch / (2 * np.pi) % pitch)


def editor_geometry(viewport, row):
    """Monaco's native edit context spans the text columns at the current caret row."""
    left, top, right, bottom = viewport
    x, y, end, row_bottom = row
    pitch = row_bottom - y
    if (not 8 <= pitch <= 160 or not left <= x < end <= right + 2
            or not top <= y < row_bottom <= bottom or bottom - top < pitch * 3):
        return None
    return x, top, min(end, right) - x, bottom - top, y, pitch


class WindowsEditorLocator:
    """Created and used on one worker thread: COM objects never cross Qt threads."""

    def __init__(self):
        import comtypes.client
        self.comtypes = __import__('comtypes')
        self.comtypes.CoInitialize()
        self.uia_module = comtypes.client.GetModule('UIAutomationCore.dll')
        self.uia = comtypes.client.CreateObject(self.uia_module.CUIAutomation,
                                               interface=self.uia_module.IUIAutomation)
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    def close(self):
        self.uia = None
        self.comtypes.CoUninitialize()

    def windows(self, root, active, workspace_name=None):
        matches = []
        root_name = (workspace_name or Path(root).name).casefold()
        file_name = Path(active).name.casefold() if active else ''
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def visit(hwnd, _):
            if not self.user32.IsWindowVisible(hwnd) or self.user32.IsIconic(hwnd):
                return True
            title = ctypes.create_unicode_buffer(self.user32.GetWindowTextLengthW(hwnd) + 1)
            self.user32.GetWindowTextW(hwnd, title, len(title))
            name = title.value.casefold()
            if 'visual studio code' in name and root_name in name and (not file_name or file_name in name):
                matches.append(hwnd)
            return True

        self.user32.EnumWindows(visit, 0)
        return matches

    @staticmethod
    def rectangle(element):
        r = element.CurrentBoundingRectangle
        return r.left, r.top, r.right, r.bottom

    def locate(self, root, active, workspace_name=None):
        matches = self.windows(root, active, workspace_name)
        if len(matches) != 1:
            return None
        hwnd = matches[0]
        window = self.uia.ElementFromHandle(hwnd)
        main = window.FindFirst(4, self.uia.CreatePropertyCondition(30011, 'workbench.parts.editor'))
        if not main:
            return None
        edits = main.FindAll(4, self.uia.CreatePropertyCondition(30003, 50004))
        candidates = []
        for i in range(edits.Length):
            edit = edits.GetElement(i)
            if 'native-edit-context' not in edit.CurrentClassName:
                continue
            row = self.rectangle(edit)
            parent = self.uia.RawViewWalker.GetParentElement(edit)
            for _ in range(8):
                if not parent:
                    break
                if parent.CurrentClassName == 'overflow-guard':
                    viewport = self.rectangle(parent)
                    geometry = editor_geometry(viewport, row)
                    candidates.append((bool(edit.CurrentHasKeyboardFocus), (viewport, geometry)))
                    break
                parent = self.uia.RawViewWalker.GetParentElement(parent)
        focused = [geometry for focus, geometry in candidates if focus]
        geometry = focused[0] if len(focused) == 1 else candidates[0][1] if len(candidates) == 1 else None
        if geometry is None:
            return None
        return dict(hwnd=hwnd, viewport=geometry[0], row=geometry[1],
                    foreground=self.user32.GetForegroundWindow() == hwnd)
