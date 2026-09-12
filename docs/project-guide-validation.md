# Project Guide validation

## Experimental custom input routing — 2026-09-11

- Replaced native cursor lookup with an opt-in pointer button. Idle hover reaches the underlying window; native button gestures and intercepted wheel events target the overlay.
- Python suite: 127 tests, 126 passed and 1 opt-in integration skipped. Coverage includes multi-button gestures, external drags, wheel routing, 64-bit handles, z-order, native callback failure, failed input restoration, and recovery after an application stall.
- Live Windows acceptance in an isolated fixture using the production CodeAnswerOverlay: hand and I-beam cursors matched underlying controls; clicks/double-clicks reached only the overlay; text selection, scrolling, title dragging and corner resizing worked. This was not a live VS Code/Chrome acceptance test.
- Fixture: `venv/Scripts/python.exe docs/probes/overlay_input_demo.py`; no audio or network. Its background counters make accidental input visible.
- Review prompted fixes that retain the hook when style restoration fails and disable experimental mode after a detected stall. Windows hook timeout remains an input-isolation limitation during a stall; the mode defaults to off.
- The earlier native cursor implementation and its limitations below are historical and superseded.
- Packaging: built `dist/AI-Live-Project-Guide-Cursor.exe` and verified its embedded cursor module, diff module and pointer icon. The packaged main application was not launched; live acceptance used the source fixture.

## Diff and cursor update — 2026-09-11

- Follow-up crash correction: use `wintypes.MSG.hWnd` in the native cursor event filter. Regression tests reproduce the reported `WM_SETCURSOR` path with real ctypes messages, including a null window handle. All 24 cursor, opacity, and guide UI tests passed with the `python` interpreter used to launch the app.
- Python suite: 118 tests, 117 passed, 1 opt-in live integration skipped. Added coverage for diff hunk numbering, create/delete patches, no-final-newline markers, literal markup, and separate Copy code/Copy diff behavior.
- Companion: TypeScript compilation and all 3 protocol tests passed.
- Packaging: built `dist/AI-Live-Project-Guide-Diff.exe`; verified the new cursor/diff modules are bundled and the executable's read-only helper can read a disposable fixture. The GUI was not launched.
- Diff presentation: rendered offscreen with Windows fonts and visually inspected; fixed narrow gutters that initially wrapped multi-digit line numbers.
- Cursor: simulated Windows calls cover 64-bit handles, negative monitor coordinates, child selection, native class cursors, resize shapes, timeouts, caching, and preserved mouse event routing. Independent review found no remaining issues within this limited scope.
- Exact per-element cursor mirroring in VS Code/Chrome is **not supported**. Native registered cursors and window resize cursors are supported on a best-effort basis. Live desktop cursor behavior and the new Codex diff response contract have not been interactively validated.

## Earlier baseline validation

Validated on Windows 11 with Python 3.12.10 and Codex CLI 0.153.4.

- Python suite: 97 tests, 96 passed and the opt-in live integration test skipped in the default run. Regression tests confirm direct acceptance of Codex answers without file reads or automatic correction, immediate copying, and opening the supplied line number.
- Companion extension: TypeScript compilation and all 3 protocol tests passed, including an actual Windows junction fixture.
- Live Codex integration: initial analysis returned a targeted edit; final review recognized a simulated manual fix. Complete fixture contents, including hidden configuration, remained unchanged by both Codex calls. A project-local startup-hook fixture did not execute.
- Windows sandbox probe: fixture reads succeeded; modifying an existing file and creating a new file were denied.
- UI: offscreen rendering checked; tests cover button-only presentation, clarification restoration after close/reopen, and ignored cancelled completions.
- Bridge: tests cover authentication, rejected command endpoints, multiple windows, pinned selection, fresh editor acknowledgments, untrusted/remote exclusion, and discovery-file cleanup.
- Packaging: VSIX built; the windowed executable's stdio reader successfully initialized and read a disposable text fixture without opening the GUI.
- Independent review: identified and corrected clarification restoration, stale editor-state checks, and junction-root handling; follow-up found no additional important controller lifecycle issues.

Interactive acceptance in an actual VS Code session has **not** been performed. The user's instructions require permission before computer use. The manual checklist is in `project-guide.md`; installation and interactive acceptance remain separate from the automated checks above.
