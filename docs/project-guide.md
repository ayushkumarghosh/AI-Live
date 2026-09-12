# Project Guide

Project Guide turns a saved problem statement into step-by-step suggestions. It never applies changes. All controls are buttons; edit and save code yourself in VS Code.

## Setup

1. Install Codex CLI and complete `codex login` outside the overlay. `codex login status` must succeed. This implementation requires a CLI supporting `exec --ignore-user-config`, `--ignore-rules`, `--output-schema`, and `--yolo`; tested with 0.153.4.
2. Install the companion VSIX using VS Code's **Install from VSIX** action. Build it using `npm ci`, `npm test`, and `npm run package` in `vscode-project-guide`, or use the VSIX produced by `build_exe.ps1`.
3. Open a trusted local Windows workspace. Start AI-Live and click **Project Guide**. The companion connects automatically; click **Refresh** if it is still starting.

Codex authentication is reused, while user configuration, rules, plugins, hooks, shell, editing, browser, and computer-use capabilities are excluded from guide runs. The CLI's built-in default model is used, rather than the existing Azure manual-analysis model. The guide sends selected project content to Codex through the signed-in account.

## Workflow

Select a connected workspace folder; the most recently focused window is recommended. Choose a problem file using the paged file buttons and preview. The active text file is recommended, with README files near the top. The chosen folder and file remain pinned even when you change editor tabs or windows.

After analysis, review the task summary and click **Start guidance**. Each step shows an operation, file, exact location anchor, unified diff, and explanation. Diffs show old/new line numbers, red removed lines, green added lines, and surrounding context with syntax highlighting. **Previous** and **Next** only navigate. **Copy code** copies replacement/insertion text without diff markers or unchanged context (empty for deletion); **Copy diff** copies the complete unified patch. **Open location** opens an existing file without applying changes. Create new files manually. **Explain** shows the explanation; **More detail** asks Codex for expanded guidance.

### Fit guidance over the editor

After **Start guidance**, click inside the selected VS Code editor. The guide automatically fits its visible editing area and follows changes to the window and editor layout while VS Code is in the foreground. Its reading area becomes transparent, with 12px monospaced guidance text between the editor's existing 24px rows. The title bar moves out of the reading area; status and action buttons remain at the bottom, including **Close guide**. Diffs retain their colors and old/new numbers, using text columns so table padding cannot shift the row grid. Guide scrolling advances by whole rows. Narrow editors use compact controls in three columns, and the project/status label stays on one line so it cannot force the overlay taller than the editor. Hover the label to read a long path.

The fitter reads Windows accessibility geometry and measures the phase of the gray line numbers from a temporary local screen capture. It does not save or transmit that capture or change VS Code settings. Keep editor line numbers visible and the editor line spacing at 24px. The capture exclusion and shared opacity settings still apply to the real guide. A native editor-row rectangle is used as a fallback when available. If the editor cannot be measured, the normal movable guide stays available; focus the editor and use **Fit editor** to retry. Picking another project/problem restores the normal panel.

Named multi-root workspaces need the rebuilt companion VSIX, which reports the workspace display name for window matching. Custom VS Code window titles that omit both the file and workspace names cannot be matched automatically.

**Check my changes** reviews saved code and the current editor diagnostics and revises remaining guidance. **Final review** checks the whole problem. Results distinguish “Looks complete”, “Needs changes”, and “Cannot verify”. No project code or tests are executed; listed test commands are for you to run.

Codex guidance is displayed as supplied. Codex is instructed to base each diff on the current saved file, group overlapping edits, and include accurate hunk ranges and context. The app does not validate patches against saved files, adjust suggested line numbers, fingerprint files, or request automatic corrections. Copy works immediately; Open location uses the supplied line. Only the JSON structure needed to display the response is checked. Request **Check my changes** to refresh guidance after saving edits.

On Windows, click the pointer icon beside the opacity control to enable **Underlying cursor (experimental)** for the overlays. It defaults to off. While idle, mouse hover reaches the application underneath so that application chooses its own cursor, without app-specific cursor detection. Button presses temporarily restore normal overlay input for clicks, text selection, dragging, and resizing; scrolling is routed to the overlay. The cursor can return to the overlay's normal shape during a gesture. Click the pointer icon again to disable the mode.

This experiment also permits underlying hover effects and tooltips. It relies on a Windows low-level mouse hook: if the application stalls, Windows can remove the hook and clicks may reach the application underneath. A timer detects a stall after the application recovers and turns the mode off, but cannot guarantee input isolation during the stall. Use normal mode when that guarantee matters.

Clarifications use two to four answer buttons. When a question cannot be resolved that way, update the problem statement in VS Code and click **Retry**, or choose another file. Codex reads saved files; save your edits when you want them included in a requested review. Unsaved or changed files do not block guidance, Copy, or Open. Cancelled or superseded results never replace current guidance. Clear Context cancels the guide and discards its in-memory session.

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

For interactive acceptance, install the VSIX, open two local windows, choose the recommended root, select a problem, answer a clarification, and close/reopen the guide. Edit without saving and confirm guidance and Copy remain available; use Check my changes explicitly to request another review. Verify Copy/Open, manual new-file creation, cancellation, Clear Context, disconnection, and final review. These checks require an actual VS Code session; automated offscreen UI tests do not substitute for them.

## File picker and Auto-Answer context

Workspace and problem-file lists use the available panel height; file previews return to the full reading area. The workflow remains button-only.

Auto-Answer receives the selected problem statement, workspace, task summary, accepted clarification choices, current step and code, and latest review findings. Context updates as guidance changes, without restarting audio. Long sections are truncated to keep the audio prompt bounded. Switching to another workspace or Clear Context removes the previous guide context. Closing the guide preserves the selected session. Guidance is reference material; suggested edits do not imply that files were changed or tests were run. No file-content validation is added.
