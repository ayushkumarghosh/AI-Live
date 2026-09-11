# Project Guide validation

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
