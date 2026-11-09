# Project Guide validation

## Chosen session and program-terminal review - 2026-09-13

- The first Check output opens a cancellable asynchronous CLI session picker, scoped to the project and excluding own exec sessions. Selection persists; Change session reopens the picker. Exact prompt matching is removed: the latest completed turn is reviewed against current guide context.
- Check terminal output independently selects a captured program terminal and immediately reviews its existing output. It does not replace the Codex session selection. Duplicate-evidence and cancellation protections remain.
- Python suite: 218 tests, 213 passed and 5 opt-in tests skipped. Tests cover first selection and reuse, stale picker responses, selected-session identity validation, program error review, and edited prompt acceptance.
- Independent review found a cancelled-picker Retry route that incorrectly invoked generation. Fixed it to reopen session selection; all 16 UI tests passed including the new regression.
- Actual Codex session listing returned two choices for the project. Reading a chosen session yielded 5,251 characters with deliberately different prompt context, without generating a new Codex response. Program-terminal routing is covered with captured-output fixtures; no program was executed or GUI automated in this change.

- Built `dist/AI-Live-Prompt-Guide-Review.exe`; all five embedded guide modules match final source, and the executable read-only helper passed its smoke test.

## Automatic Codex CLI session selection - 2026-09-13

- Prompt Guide now reads saved conversations using app-server thread/list and thread/read. Selection uses descending updated_at order, exact canonical project folder, cli source, and non-ephemeral sessions; app-owned exec requests are excluded. Selection is automatic on every check. Editor context still uses the companion; Code Guide terminal checks remain unchanged.
- No session is resumed and no turn is submitted. The latest saved turn must be completed and the displayed prompt must occur in its conversation. Relevant follow-up user and assistant messages are included, while reasoning and terminal redraws are omitted. Consumed session/turn identities remain protected across session switches. Cancelled requests cannot commit session selection or review state.
- Python suite: 211 tests, 206 passed and 5 opt-in tests skipped. Focused coverage includes pagination, own-session exclusion, wrong-project exclusion, latest-session selection, unfinished/missing/mismatched response handling, follow-up messages, duplicate checks across switches, cancellation, and removal of manual selection UI.
- A subsequent 37-test targeted run passed, including recovery from an oversized answer through a concise follow-up while preserving complete recent turns and disclosing omitted history.
- Independent review identified Windows npm-launcher child-process cleanup; corrected shutdown to terminate only the owned reader process tree. All 9 reader tests passed, including the new lifecycle regression.
- Actual local Codex app-server read succeeded for the user's project CLI session: a completed turn yielded 2,377 characters of user/assistant messages. The same terminal's previous capture had been dominated by spinner animation. No UI automation or user-session generation was performed.

- Built `dist/AI-Live-Prompt-Guide-Sessions.exe`. Verified its embedded session-reader code matches final source, executed that embedded reader against the actual saved CLI session, and smoke-tested the executable read-only helper. No app GUI was launched for these package checks.

## Live capture inspection — 2026-09-12

- Added authenticated read-only GET /captures; all 13 bridge tests pass, including unauthorized/Origin rejection and stale report omission. Launched the source app with Project Guide open and read an actual VS Code extension report successfully (HTTP 200).
- The selected pwsh terminal running codex reported running=true and truncated=true. The sampled 32,000-character capture contained 29,123 Braille spinner glyphs and otherwise whitespace, with no readable response. Saved the exact sample to ignored build/vscode-codex-capture-0.txt. This demonstrates that animation redraws can evict useful response text; allowing truncated reviews alone does not repair capture fidelity.
- The running source app includes this endpoint; previously built executables do not. No terminal commands were submitted and no VS Code UI was automated.

## Long interactive capture correction — 2026-09-12

- Removed the unconditional rejection of truncated terminal captures. The extension's rolling 32,000-character buffer can discard older turns while retaining a complete latest response. The reviewer receives the original truncation flag, reviews retained output against the current prompt and saved files, and discloses the limitation. Missing essential evidence still retains guidance and requests a concise restatement in the existing conversation.
- Regression tests first reproduced the old rejection. Session and controller coverage now verifies reviewable truncated tails, unchanged-evidence rejection after advancement, and retry without losing the prompt when evidence is inconclusive.
- Python suite: 201 tests, 196 passed and 5 opt-in tests skipped. Extension compilation and all 15 tests passed; the extension protocol and package are unchanged.
- Real Codex regression passed for both sufficient retained requirements output and a cut-off test result. The initial assertion was corrected to allow a valid design-approval clarification as well as a next investigation prompt. Fixture source remained unchanged. These tests use simulated terminal evidence; actual VS Code UI capture was not exercised.

- Built `dist/AI-Live-Prompt-Guide-Capture.exe`; verified the updated review instructions in its embedded archive and successfully exercised its packaged read-only helper without launching the GUI.

## Solution-focused approach correction — 2026-09-12

- Removed instructions to explain assistant/operator responsibilities and the adaptive workflow inside the approach. The approach now covers the actual solution's behavior, logic, components, data flow, dependencies, tradeoffs and edge cases, grounded in relevant saved source when available. Workflow instructions remain confined to prompt generation and handoffs.
- The strengthened live regression failed against the previous policy because the approach mentioned Codex and operator roles. It passed after the correction, with substantive project content and no Codex/CLI/prompt/operator/state-capsule terms in the fixture's approach.
- All 15 targeted runner/UI tests passed, along with the real Codex regression. No GUI interaction was used.
- Built `dist/AI-Live-Prompt-Guide-Solution.exe`; verified the corrected instructions in its embedded archive and smoke-tested the packaged read-only helper successfully.

## Detailed approach before the first prompt — 2026-09-12

- Expanded the generated approach into a project-specific end-to-end explanation: success criteria, technical direction, investigation/design decisions, implementation phases and dependencies, risks, operator verification, delivery, and how evidence changes the next step. Uninspected details remain provisional; future prompts are not pre-generated.
- Fixed first-prompt sequencing after clarification: the full approach is shown before the first accepted prompt regardless of which request produced it. Later checks remain adaptive; Approach reopens the explanation.
- All 39 targeted UI/runner tests passed. The live Codex requirements-first check passed with a substantive approach kept separate from the prompt. No actual GUI interaction was used.
- Built `dist/AI-Live-Prompt-Guide-Approach.exe`; verified its embedded approach instructions and successfully smoke-tested its read-only helper without launching the GUI.

## Adaptive prompt policy — 2026-09-12

- Embedded the user's full **Adaptive prompting for software work** document in `project_guide/prompt_policy.py`, with app-specific mapping to the existing prompt response contract. Code Guide's instructions and the extension protocol are unchanged.
- A new live requirements-first test failed against the prior policy because the prompt skipped `STATE_1` and included source/design work. It passed after the policy change.
- Three opt-in real Codex tests passed: requirements-only first prompt, manual verification handoff after a scoped diff, and incorporation of a new spoken requirement into the next prompt. Guide requests left all fixture files unchanged. These evaluate generated instructions with simulated terminal evidence, not actual UI/terminal or audio operation.
- Python suite: 196 tests, 192 passed and 4 opt-in tests skipped in the default run. Independent review reported no important findings in the policy integration.
- Built `dist/AI-Live-Prompt-Guide-Adaptive.exe`; inspected its embedded Python archive to confirm the complete supplied policy is present. Its packaged read-only helper initialized and read a disposable fixture successfully without launching the GUI.

## Prompt Guide — 2026-09-12

- Added a separate one-prompt-at-a-time Codex workflow, manual pinned-terminal checks, and relevant spoken requirement updates from Auto-Answer.
- Python suite: 194 tests, 192 passed and 2 opt-in integration tests skipped. Coverage includes prompt history, initial uncertainty, clarification/retry, duplicate evidence, cancellation races, terminal selection, mid-speech project switching, bounded conversation updates, and code-mode regressions.
- Companion: TypeScript compilation and all 15 tests passed, including ANSI streams split across chunks, formatting-only volume, surrogate-safe truncation, capture identities, and multilingual reports under the bridge byte limit.
- Opt-in real Codex prompt smoke test passed separately: initial prompt generation and a second review incorporating a simulated spoken requirement. Both guide calls left all fixture files unchanged. Terminal output was a fixture, not actual VS Code capture; no live audio was used.
- Prompt panel rendered offscreen with Windows fonts and visually inspected. The first render needed explicit Windows font loading in the offscreen test process; production font configuration was unchanged.
- Independent review found and prompted fixes for request-token cancellation races, initial uncertainty recovery, clarification repinning, speech-start context isolation, and raw ANSI capture inflation.
- Built `dist/AI-Live-Prompt-Guide.exe` and companion 0.1.2. Verified the new guide modules are embedded, and the executable's stdio helper initialized and read an unchanged disposable fixture without launching the GUI. Actual VS Code interactive terminal capture and live audio extraction have not been manually validated; those require a separate interactive acceptance check.

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
