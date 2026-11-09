# Project Guide

Project Guide turns a saved problem statement into step-by-step suggestions. It never applies changes. All controls are buttons; edit and save code yourself in VS Code.

## Setup

1. Install Codex CLI and complete `codex login` outside the overlay. `codex login status` must succeed. This implementation requires a CLI supporting `exec --ignore-user-config`, `--ignore-rules`, `--output-schema`, and `--yolo`; tested with 0.153.4.
2. Install the companion VSIX using VS Code's **Install from VSIX** action. Build it using `npm ci`, `npm test`, and `npm run package` in `vscode-project-guide`, or use the VSIX produced by `build_exe.ps1`.
3. Open a trusted local Windows workspace. Start AI-Live and click **Project Guide**. The companion connects automatically; click **Refresh** if it is still starting.

Codex authentication is reused, while user configuration, rules, plugins, hooks, shell, editing, browser, and computer-use capabilities are excluded from guide runs. The CLI's built-in default model is used, rather than the existing Azure manual-analysis model. The guide sends selected project content to Codex through the signed-in account.

## Workflow

After choosing the saved problem file, select **Code Guide** for manual code edits or **Prompt Guide** for Codex prompts. Code Guide retains the existing diff workflow below.

### Prompt Guide

Before the first prompt, **Full approach** explains how the actual project will work: its intended behavior, solution logic, components, data flow, implementation dependencies, edge cases, tradeoffs, and concrete examples/checks. It does not explain the prompt-sharing workflow or mention Codex, CLI, prompts, assistant roles, state capsules, or guide controls. The guide can inspect relevant saved source to ground the solution; uninspected details remain clearly provisional. Click **Show prompt** when ready. This screen also appears when the first prompt follows clarification answers; **Approach** reopens it later. Future prompts are still generated one at a time.

Prompt generation follows the supplied **Adaptive prompting for software work** policy, embedded in the app. A fresh session starts by extracting requirements from the selected document and asking Codex for `STATE_1`. Later prompts follow the evidence: focused investigation, correction of unsupported findings, design, approved scoped edits, review, manual verification, and delivery. Investigation prompts request compact numbered state capsules; editing prompts request complete diffs and stop at the approved scope.

Every generated coding prompt prohibits running commands. You run commands and browser checks yourself. When a correct diff needs verification, the guide shows an operator handoff in **Output review**, with the location, command or UI steps, expected observations, evidence to share, and stopping point. The current prompt remains visible while verification is pending. Use **Check terminal output** to review program command results, or report results and browser observations in your Codex conversation and use **Check output**. A successful build alone does not establish behavioral acceptance.

The guide explains which current files to supply to Codex. Files read by the app are not automatically attached to the interactive CLI. Generated prompts request available non-command read tools or ask you for attachments when those tools are unavailable. Codex uses explicit read-only/scoped-edit instructions rather than assuming Cline's Plan/Act controls. State capsules remain in conversation; the guide does not create a notes file automatically.

Start Codex in the selected project folder. On the first **Check output**, choose a saved Codex CLI session; the guide remembers it for subsequent checks. **Change session** lets you choose another. The list excludes the app’s own ephemeral exec requests and other projects. The companion still provides editor context, diagnostics, and program-terminal captures.

The app's separate Codex runner reads saved project files, explains an approach, and generates one prompt. Click **Show prompt**, then **Copy prompt** and paste/submit it in your interactive Codex terminal. When Codex's response is ready, click **Check output**. The app reads the saved Codex conversation through its app-server API and reviews it alongside saved files, then supplies one next prompt, a clarification, an inconclusive finding, or a completion result. A corrective prompt may be the next step when Codex reports an error. No future prompt list is generated.

**Previous prompt** and **Next prompt** browse retained history; checking is available only on the latest prompt. **Approach** reopens the explanation. The prompt panel stays movable and does not fit between editor rows. Closing it preserves the session; changing the project/problem or Clear Context discards it. The latest 100 prompts are retained in memory.

With Auto-Answer enabled, its audio model also extracts concise, relevant spoken project requirements, corrections, and decisions into a separate context field. These updates do not change the visible answer rules. The next requested prompt incorporates relevant changes and explains what changed; unrelated conversation is ignored. Ambiguous requirements produce clarification choices. Suggested AI answers are not treated as user decisions. Updates arriving during generation wait until the following request. A compact accepted-requirements record persists, with a bounded queue of pending audio updates; gaps and truncation are reported in model context. Extraction is model-based and is not a full transcript.

Checks read the latest completed saved turn from the chosen session. The current guide prompt is supplied as review context and does not need to match the submitted text exactly. Missing or unfinished responses retain guidance, and session/turn IDs prevent duplicate advancement. The reviewer checks relevance and asks for clarification when needed. **Check terminal output** separately lists captured project terminals so you can select one that already contains a program error or unexpected output. Terminal selection does not change the chosen Codex session. Neither action submits prompts or executes the program.

### Code Guide

Select a connected workspace folder; the most recently focused window is recommended. Choose a problem file using the paged file buttons and preview. The active text file is recommended, with README files near the top. The chosen folder and file remain pinned even when you change editor tabs or windows.

After analysis, read **Full approach** on its own screen, then click **Next** to open the first step. Like Prompt Guide, this explains the actual solution: intended behavior, logic, components and data flow, order of changes, dependencies, edge cases, tradeoffs, and validation examples. It scales to the problem's complexity and appears after any initial clarification answers. The full approach is not repeated on step screens. Each step then shows an operation, file, exact location anchor, unified diff, and explanation. Diffs show old/new line numbers, red removed lines, green added lines, and surrounding context with syntax highlighting. **Previous** and **Next** only navigate. Create new files manually. **Explain** shows the explanation; **More detail** asks Codex for expanded guidance.

Code Guide shares the selected problem, approach, current step, and accepted requirements with Auto Answer. Explicit relevant spoken requirements, corrections, and decisions are retained for this guide session; Auto Answer's own suggested answer is not a requirement. **Next** checks new spoken updates before continuing. A material change revises the affected remaining steps; unchanged requirements preserve the existing guidance exactly. **Next** continues to the requested step after the check, including after a retry, instead of returning to the approach screen. If that step was removed, it shows a surviving step. **Update requirements** checks updates without advancing, including on the last step, and shows the updated approach when requirements change. Normal reviews also receive the retained context. Unclear changes produce clarification choices. Audio arriving during generation waits for the next request, and changing the project or problem clears the old audio context.

### Fit guidance over the editor

After advancing from the approach screen, click inside the selected VS Code editor. The guide automatically fits its visible editing area and follows changes to the window and editor layout while VS Code is in the foreground. Its reading area becomes transparent, with 12px monospaced guidance text between the editor's existing 24px rows. The title bar moves out of the reading area; status and action buttons remain at the bottom, including **Close guide**. Diffs retain their colors and old/new numbers, using text columns so table padding cannot shift the row grid. Guide scrolling advances by whole rows. Narrow editors use compact controls in three columns, and the project/status label stays on one line so it cannot force the overlay taller than the editor. Hover the label to read a long path.

The fitter reads Windows accessibility geometry and measures the phase of the gray line numbers from a temporary local screen capture. It does not save or transmit that capture or change VS Code settings. Keep editor line numbers visible and the editor line spacing at 24px. The capture exclusion and shared opacity settings still apply to the real guide. A native editor-row rectangle is used as a fallback when available. If the editor cannot be measured, the normal movable guide stays available; focus the editor and use **Fit editor** to retry. Picking another project/problem restores the normal panel.

Named multi-root workspaces need the rebuilt companion VSIX, which reports the workspace display name for window matching. Custom VS Code window titles that omit both the file and workspace names cannot be matched automatically.

**Check my changes** reviews saved code and the current editor diagnostics and revises remaining guidance. **Final review** checks the whole problem. Results distinguish “Looks complete”, “Needs changes”, and “Cannot verify”. No project code or tests are executed; listed test commands are for you to run.

Codex guidance is displayed as supplied. Codex is instructed to base each diff on the current saved file, group overlapping edits, and include accurate hunk ranges and context. The app does not validate patches against saved files, adjust suggested line numbers, fingerprint files, or request automatic corrections. Only the JSON structure needed to display the response is checked. Request **Check my changes** to refresh guidance after saving edits.

On Windows, click the pointer icon beside the opacity control to enable **Underlying cursor (experimental)** for the overlays. It defaults to off. While idle, mouse hover reaches the application underneath so that application chooses its own cursor, without app-specific cursor detection. Button presses temporarily restore normal overlay input for clicks, text selection, dragging, and resizing; scrolling is routed to the overlay. The cursor can return to the overlay's normal shape during a gesture. Click the pointer icon again to disable the mode.

This experiment also permits underlying hover effects and tooltips. It relies on a Windows low-level mouse hook: if the application stalls, Windows can remove the hook and clicks may reach the application underneath. A timer detects a stall after the application recovers and turns the mode off, but cannot guarantee input isolation during the stall. Use normal mode when that guarantee matters.

Clarifications use two to four answer buttons. When a question cannot be resolved that way, update the problem statement in VS Code and click **Retry**, or choose another file. Codex reads saved files; save your edits when you want them included in a requested review. Unsaved or changed files do not block guidance. Cancelled or superseded results never replace current guidance. Clear Context cancels the guide and discards its in-memory session.

## Boundaries and recovery

- Only local Windows folders are supported. For multi-root workspaces, select one root.
- The read-only reader exposes only file listing, UTF-8 text reads, and literal text searches. It rejects absolute paths, traversal, alternate data streams, reserved Windows names, and paths resolving outside the root.
- Private configuration (`.env`, `.git`, `.codex`, `.vscode`), dependencies, caches, and build output are excluded. Text files must be at most 1 MiB; file listing is bounded to 10,000 files. Select a smaller folder if a limit is reached.
- Codex runs with `--yolo`, bypassing CLI approvals and sandbox enforcement. There is no pre-analysis sandbox probe. The guidance prompt and restricted reader tools remain, but OS sandbox enforcement is no longer provided.
- The app stores only bridge discovery credentials on disk, outside projects. Guide context is in memory and lost when the app closes. Codex may maintain its own authentication/runtime caches.
- Each Codex request times out after four minutes. There are no automatic answer-correction requests. If Codex is missing, not signed in, disconnected, or times out, use **Retry** after fixing the reported setup issue. A disconnected VS Code window must reconnect before checks continue.

## Verification

Run `venv/Scripts/python.exe -m unittest discover -s tests` and `npm test` in the companion directory. The opt-in real Codex test uses a disposable fixture and checks that project contents are unchanged:

```powershell
$env:AI_LIVE_CODEX_SMOKE = '1'
venv/Scripts/python.exe -m unittest tests.test_project_guide_live -v
Remove-Item Env:AI_LIVE_CODEX_SMOKE
```

For interactive acceptance, install the VSIX, open two local windows, choose the recommended root, select a problem, answer a clarification, and close/reopen the guide. Edit without saving and confirm guidance remains available; use Check my changes explicitly to request another review. Verify fitted button clicks and editor passthrough, terminal output checks, manual new-file creation, cancellation, Clear Context, disconnection, and final review. These checks require an actual VS Code session; automated offscreen UI tests do not substitute for them.

## File picker and Auto-Answer context

Workspace and problem-file lists use the available panel height; file previews return to the full reading area. The workflow remains button-only.

Auto-Answer receives the selected problem statement, workspace, task summary, accepted clarification choices, current step and code, and latest review findings. Context updates as guidance changes, without restarting audio. Long sections are truncated to keep the audio prompt bounded. Switching to another workspace or Clear Context removes the previous guide context. Closing the guide preserves the selected session. Guidance is reference material; suggested edits do not imply that files were changed or tests were run. No file-content validation is added.

## Terminal output checks

Install companion version 0.1.1 and reload VS Code. Run your command in a terminal with shell integration enabled, then click **Check terminal output**. The guide asks Codex to review the active terminal's latest captured command, output, working folder, running state, and exit code alongside saved project files. The command must have run inside the selected project. This button does not execute commands.

Output is retained in memory from commands started after the extension loads, capped to the latest 32,000 characters per terminal. Truncation and commands still running are reported explicitly. Older scrollback and terminals without shell integration are unavailable. Captured output is sent to Codex only when you request a terminal check.

While fitted, mouse input passes through to VS Code except for guide buttons. Button clicks are delivered through the Qt event queue; pressing a button and releasing outside it cancels the click.

Use **Scroll up** and **Scroll down** to move the guide three text rows per click while fitted. Scrolling preserves the interleaved alignment and stops at the beginning or end. The mouse wheel continues scrolling VS Code. Guide buttons use compact padding and spacing, with up to five columns in wider fitted editors.

### Captured-output diagnostics

The source app exposes authenticated `GET /captures` on its loopback bridge. It returns recent connected window reports, terminal identities, capture age, and retained output without queuing commands. Use the bearer token from the local connection discovery file; browser Origin requests are rejected. This is the extension capture, not a reconstruction of the visible terminal screen. Disconnected reports are omitted after six seconds.
