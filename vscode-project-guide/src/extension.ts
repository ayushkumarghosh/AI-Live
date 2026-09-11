import * as vscode from 'vscode';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import * as http from 'node:http';
import {randomUUID} from 'node:crypto';
import {Connection, validConnection, resolveOpen} from './protocol';

let timer: ReturnType<typeof setInterval> | undefined;
let stopped = false;

function post(connection: Connection, body: unknown): Promise<{commands: unknown[]; refresh?: string}> {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = http.request(connection.url + '/poll', {method: 'POST', timeout: 2500,
      headers: {'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data),
        Authorization: 'Bearer ' + connection.token}}, res => {
      let response = '';
      res.setEncoding('utf8');
      res.on('data', chunk => {
        response += chunk;
        if (response.length > 1024 * 1024) req.destroy(new Error('Response too large'));
      });
      res.on('end', () => {
        try {
          if (res.statusCode !== 200) throw new Error('Bridge unavailable');
          resolve(JSON.parse(response));
        } catch (error) { reject(error); }
      });
      res.on('error', reject);
    });
    req.on('timeout', () => req.destroy(new Error('Bridge timeout')));
    req.on('error', reject);
    req.end(data);
  });
}

export function activate(context: vscode.ExtensionContext): void {
  stopped = false;
  const window = randomUUID();
  let busy = false;
  let again = false;
  let ack = '';
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 50);
  status.text = '$(link) AI-Live: waiting';
  status.tooltip = 'Project Guide reads workspace metadata. All guidance controls are in the AI-Live overlay.';
  status.show();
  context.subscriptions.push(status);

  const poll = async () => {
    if (busy) { again = true; return; }
    if (stopped || process.platform !== 'win32' || !process.env.LOCALAPPDATA) return;
    busy = true;
    try {
      const file = path.join(process.env.LOCALAPPDATA, 'AI-Live', 'project-guide', 'connection.json');
      const connection: unknown = JSON.parse(await fs.readFile(file, 'utf8'));
      if (!validConnection(connection)) throw new Error('Invalid bridge');
      const folders = vscode.workspace.workspaceFolders ?? [];
      const remote = !!vscode.env.remoteName || folders.some(f => f.uri.scheme !== 'file');
      const roots = await Promise.all(folders.filter(f => f.uri.scheme === 'file').map(f => fs.realpath(f.uri.fsPath)));
      const active = vscode.window.activeTextEditor?.document.uri;
      const diagnostics = vscode.languages.getDiagnostics().flatMap(([uri, entries]) =>
        uri.scheme === 'file' && vscode.workspace.getWorkspaceFolder(uri) ?
          entries.map(d => ({path: uri.fsPath, line: d.range.start.line + 1,
            severity: d.severity, message: d.message.slice(0, 2000)})) : []).slice(0, 500);
      const response = await post(connection, {
        window, roots, remote, ack, trusted: vscode.workspace.isTrusted, focused: vscode.window.state.focused,
        active: active?.scheme === 'file' ? active.fsPath : null,
        dirty: vscode.workspace.textDocuments.filter(d => d.isDirty && d.uri.scheme === 'file' &&
          vscode.workspace.getWorkspaceFolder(d.uri)).map(d => d.uri.fsPath), diagnostics,
      });
      if (response.refresh && response.refresh !== ack) { ack = response.refresh; again = true; }
      status.text = remote ? '$(link) AI-Live: local only' : '$(link) AI-Live: connected';
      if (remote || !vscode.workspace.isTrusted || !Array.isArray(response.commands)) return;
      for (const value of response.commands) {
        const command = await resolveOpen(value, roots);
        if (!command) continue;
        const document = await vscode.workspace.openTextDocument(vscode.Uri.file(command.path));
        const editor = await vscode.window.showTextDocument(document, {preview: true, preserveFocus: true});
        const line = Math.min(command.line - 1, document.lineCount - 1);
        const position = new vscode.Position(line, 0);
        editor.selection = new vscode.Selection(position, position);
        editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
      }
    } catch {
      status.text = '$(link) AI-Live: waiting';
    } finally {
      busy = false;
      if (again) { again = false; setImmediate(() => void poll()); }
    }
  };
  timer = setInterval(() => void poll(), 1000);
  context.subscriptions.push(vscode.window.onDidChangeWindowState(() => void poll()));
  context.subscriptions.push(vscode.workspace.onDidSaveTextDocument(() => void poll()));
  context.subscriptions.push(vscode.workspace.onDidChangeTextDocument(() => void poll()));
  context.subscriptions.push(vscode.window.onDidChangeActiveTextEditor(() => void poll()));
  context.subscriptions.push({dispose: deactivate});
  void poll();
}

export function deactivate(): void {
  stopped = true;
  if (timer) clearInterval(timer);
  timer = undefined;
}
