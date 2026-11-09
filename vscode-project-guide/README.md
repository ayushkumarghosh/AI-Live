# AI-Live Project Guide companion

This extension connects trusted **local Windows** VS Code workspaces to the AI-Live overlay. It reports workspace folders and the workspace display name, the active file, unsaved-file status, editor diagnostics, and captured terminal output. The overlay uses the display name to match the selected editor window when fitting guidance over its text area. The overlay can request opening an existing file at a location. The extension does not edit or save files and cannot execute terminal commands.

## Install

1. Build the VSIX with `npm ci`, `npm test`, and `npm run package` in this directory.
2. In VS Code, use **Extensions → … → Install from VSIX** and select `ai-live-project-guide-0.1.2.vsix`.
3. Open a trusted local folder and start AI-Live. Click **Project Guide** in the overlay, then **Refresh**.

The status bar shows whether the overlay is connected. No VS Code command or typed overlay prompt is required during guidance. Select a workspace and problem file in the overlay, follow its suggestions, and make edits yourself in VS Code.

Connection discovery uses `%LOCALAPPDATA%\AI-Live\project-guide\connection.json` and an authenticated loopback endpoint. Credentials are regenerated when the bridge starts. The overlay displays Codex guidance directly. Project contents are read by the separate Codex reader; this extension reports metadata, diagnostics, and bounded terminal output over the local bridge.

WSL, SSH, containers, virtual filesystems, and untrusted workspaces are unsupported in this release. The Codex CLI must be installed and signed in separately. The extension does not install it or change your authentication.

Requires VS Code 1.93 or newer. Reload VS Code after installing the update. Terminal capture uses shell integration and records only commands started after activation, keeping the last 32,000 characters of the latest command per terminal in memory. **Check terminal output** reviews this evidence with Codex; it does not run commands or recover earlier scrollback.


Terminal reports include the legacy active `terminal` and a `terminals` array containing at most the 20 most recently started captured terminals. Each record has a stable terminal `id`, a new `execution_id` for each shell execution, and a `revision` starting at zero and incrementing for each nonempty output chunk. Completion updates status without incrementing revision. Reports clean ANSI formatting and retain at most 32,000 characters per output. Closing a terminal removes its capture.

The Python bridge exposes `terminals(window, root)` for current captures whose working folder is inside the selected root. `terminal_output(window, root, terminal_id=None)` requests a fresh acknowledged report. Supplying an ID pins selection to that terminal and rejects missing, closed, or out-of-project captures without falling back to the active terminal. Omitting the ID keeps the existing active-terminal behavior, including support for older reports without identity fields.


Reports are serialized under the bridge's 1 MiB UTF-8 JSON limit. Diagnostics have a 128 KiB encoded budget; array terminal outputs share the remaining space and report `truncated: true` when clipped. Budgeting preserves all reported terminal IDs, execution IDs, revisions, status, and the legacy active output (up to 32,000 cleaned characters). It does not mutate capture buffers. Oversized metadata alone fails the report rather than silently dropping roots, dirty paths, or terminal identities.

Capture strips ANSI formatting incrementally before applying the text limit. Escape sequences split across stream chunks retain constant-size parser state; formatting alone does not set `truncated`. TUI cursor and screen-control sequences are removed to produce a text transcript, not a reconstruction of the terminal screen. Validation uses automated fixtures; no live interactive TUI validation has been performed.
