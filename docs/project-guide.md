# Project Guide

Project Guide turns a saved problem statement into step-by-step suggestions. It never applies changes. All controls are buttons; edit and save code yourself in VS Code.

## Setup

1. Install Codex CLI and complete `codex login` outside the overlay. `codex login status` must succeed. This implementation requires a CLI supporting `exec --ignore-user-config`, `--ignore-rules`, `--output-schema`, and `--yolo`; tested with 0.153.4.
2. Install the companion VSIX using VS Code's **Install from VSIX** action. Build it using `npm ci`, `npm test`, and `npm run package` in `vscode-project-guide`, or use the VSIX produced by `build_exe.ps1`.
3. Open a trusted local Windows workspace. Start AI-Live and click **Project Guide**. The companion connects automatically; click **Refresh** if it is still starting.

Codex authentication is reused, while user configuration, rules, plugins, hooks, shell, editing, browser, and computer-use capabilities are excluded from guide runs. The CLI's built-in default model is used, rather than the existing Azure manual-analysis model. The guide sends selected project content to Codex through the signed-in account.

## Workflow

Select a connected workspace folder; the most recently focused window is recommended. Choose a problem file using the paged file buttons and preview. The active text file is recommended, with README files near the top. The chosen folder and file remain pinned even when you change editor tabs or windows.

After analysis, review the task summary and click **Start guidance**. Each step shows an operation, file, exact location anchor, code, and explanation. **Previous** and **Next** only navigate. **Copy code** copies the snippet; **Open location** opens an existing file without applying changes. Create new files manually. **Explain** shows the explanation; **More detail** asks Codex for expanded guidance.

**Check my changes** reviews saved code and the current editor diagnostics and revises remaining guidance. **Final review** checks the whole problem. Results distinguish “Looks complete”, “Needs changes”, and “Cannot verify”. No project code or tests are executed; listed test commands are for you to run.

Codex guidance is displayed as supplied. The app does not check snippets against saved files, adjust suggested line numbers, fingerprint files, or request automatic corrections. Copy works immediately; Open location uses the supplied line. Only the JSON structure needed to display the response is checked.

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
