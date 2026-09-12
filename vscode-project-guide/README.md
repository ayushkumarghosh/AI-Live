# AI-Live Project Guide companion

This extension connects trusted **local Windows** VS Code workspaces to the AI-Live overlay. It reports workspace folders and the workspace display name, the active file, unsaved-file status, editor diagnostics, and captured terminal output. The overlay uses the display name to match the selected editor window when fitting guidance over its text area. The overlay can request opening an existing file at a location. The extension does not edit or save files and cannot execute terminal commands.

## Install

1. Build the VSIX with `npm ci`, `npm test`, and `npm run package` in this directory.
2. In VS Code, use **Extensions → … → Install from VSIX** and select `ai-live-project-guide-0.1.1.vsix`.
3. Open a trusted local folder and start AI-Live. Click **Project Guide** in the overlay, then **Refresh**.

The status bar shows whether the overlay is connected. No VS Code command or typed overlay prompt is required during guidance. Select a workspace and problem file in the overlay, follow its suggestions, and make edits yourself in VS Code.

Connection discovery uses `%LOCALAPPDATA%\AI-Live\project-guide\connection.json` and an authenticated loopback endpoint. Credentials are regenerated when the bridge starts. The overlay displays Codex guidance directly. Project contents are read by the separate Codex reader; this extension reports metadata, diagnostics, and bounded terminal output over the local bridge.

WSL, SSH, containers, virtual filesystems, and untrusted workspaces are unsupported in this release. The Codex CLI must be installed and signed in separately. The extension does not install it or change your authentication.

Requires VS Code 1.93 or newer. Reload VS Code after installing the update. Terminal capture uses shell integration and records only commands started after activation, keeping the last 32,000 characters of the latest command per terminal in memory. **Check terminal output** reviews this evidence with Codex; it does not run commands or recover earlier scrollback.
