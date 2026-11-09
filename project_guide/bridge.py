"""Authenticated loopback rendezvous; the only outbound command opens a file."""
import copy
import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .files import GuideError, ProjectFiles


def data_directory():
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share')) / 'AI-Live' / 'project-guide'


class ProjectBridge:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else data_directory()
        self.discovery = self.directory / 'connection.json'
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.clients = {}
        self.focus_order = 0
        self.commands = {}
        self.refresh_requests = {}
        self.condition = threading.Condition(self.lock)
        self.server = None

    def start(self):
        if self.server:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Never log bearer tokens or project contents.

            def reply(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.headers.get('Origin') or not hmac.compare_digest(
                        self.headers.get('Authorization', ''), 'Bearer ' + bridge.token):
                    self.reply(401, {'error': 'Unauthorized'})
                    return
                if self.path != '/captures':
                    self.reply(404, {'error': 'Unknown endpoint'})
                    return
                # Read-only diagnostic snapshot; never expose tokens or queue
                # commands. Expired/disconnected reports are omitted by windows().
                self.reply(200, {'windows': [
                    {'window': state['window'], 'roots': state['roots'],
                     'terminal': state.get('terminal'),
                     'terminals': state.get('terminals', []),
                     'age_seconds': max(0, time.monotonic() - state['seen'])}
                    for state in bridge.windows()]})

            def do_POST(self):
                # Drain a bounded body before responding, including rejections.
                # Leaving bytes unread can reset the TCP connection on Windows
                # before the client receives the 401/404 response.
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    if not 0 < length <= 1024 * 1024:
                        raise ValueError('Invalid payload size')
                    self.connection.settimeout(3)
                    raw = self.rfile.read(length)
                except (ValueError, OSError):
                    self.reply(400, {'error': 'Invalid request body'})
                    return
                if self.headers.get('Origin') or not hmac.compare_digest(
                        self.headers.get('Authorization', ''), 'Bearer ' + bridge.token):
                    self.reply(401, {'error': 'Unauthorized'})
                    return
                if self.path != '/poll':
                    self.reply(404, {'error': 'Unknown endpoint'})
                    return
                try:
                    body = json.loads(raw)
                    response = bridge.poll(body)
                except (ValueError, TypeError, KeyError, OSError, GuideError):
                    self.reply(400, {'error': 'Invalid workspace report'})
                    return
                self.reply(200, response)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / (self.token[:12] + '.tmp')
        temporary.write_text(json.dumps({'url': self.url, 'token': self.token, 'version': 1}), encoding='utf-8')
        os.replace(temporary, self.discovery)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def poll(self, body):
        if not isinstance(body, dict):
            raise ValueError('Invalid report')
        window = body['window']
        if not isinstance(window, str) or not 1 <= len(window) <= 100:
            raise ValueError('Invalid window')
        if body.get('remote') is not False or body.get('trusted') is not True:
            with self.lock:
                self.clients.pop(window, None)
                self.commands.pop(window, None)
            return {'commands': [], 'refresh': ''}
        roots = body['roots']
        if not isinstance(roots, list) or len(roots) > 30 or not all(isinstance(p, str) for p in roots):
            raise ValueError('Invalid roots')
        roots = [str(Path(p).resolve(strict=True)) for p in roots if Path(p).is_absolute() and Path(p).is_dir()]
        active = body.get('active')
        if active is not None and not isinstance(active, str):
            raise ValueError('Invalid document')
        workspace_name = body.get('workspaceName')
        if workspace_name is not None and (not isinstance(workspace_name, str) or len(workspace_name) > 1000):
            raise ValueError('Invalid workspace name')
        dirty = body.get('dirty', [])
        terminal = body.get('terminal')
        terminal = self._validate_terminal(terminal) if terminal is not None else None
        terminals = body.get('terminals', [])
        if not isinstance(terminals, list) or len(terminals) > 20:
            raise ValueError('Invalid terminals')
        terminals = [self._validate_terminal(item, identity_required=True) for item in terminals]
        if len({item['id'] for item in terminals}) != len(terminals):
            raise ValueError('Duplicate terminal id')
        diagnostics = body.get('diagnostics', [])
        if (not isinstance(dirty, list) or not all(isinstance(p, str) for p in dirty) or
                not isinstance(diagnostics, list) or len(diagnostics) > 500):
            raise ValueError('Invalid editor state')
        now = time.monotonic()
        with self.lock:
            previous = self.clients.get(window, {})
            focused = body.get('focused') is True
            if focused and not previous.get('focused'):
                self.focus_order += 1
                focus_time = self.focus_order
            else:
                focus_time = previous.get('focus_time', 0)
            self.clients[window] = dict(window=window, roots=roots, active=active,
                workspace_name=workspace_name,
                terminal=terminal, terminals=terminals,
                dirty=dirty, diagnostics=diagnostics, focused=focused, focus_time=focus_time, seen=now,
                ack=body.get('ack', ''))
            self.condition.notify_all()
            return {'commands': self.commands.pop(window, []), 'refresh': self.refresh_requests.get(window, '')}

    @staticmethod
    def _validate_terminal(terminal, identity_required=False):
        if not isinstance(terminal, dict):
            raise ValueError('Invalid terminal')
        fields = ('name', 'cwd', 'command', 'output', 'running', 'truncated', 'exit_code')
        for field, limit in [('name', 200), ('cwd', 4000), ('command', 2000), ('output', 32000)]:
            if not isinstance(terminal.get(field), str) or len(terminal[field]) > limit:
                raise ValueError('Invalid terminal ' + field)
        if (type(terminal.get('running')) is not bool or type(terminal.get('truncated')) is not bool or
                (terminal.get('exit_code') is not None and type(terminal['exit_code']) is not int)):
            raise ValueError('Invalid terminal status')
        identity = ('id', 'execution_id', 'revision')
        if identity_required or any(field in terminal for field in identity):
            for field in identity[:2]:
                if not isinstance(terminal.get(field), str) or not 1 <= len(terminal[field]) <= 100:
                    raise ValueError('Invalid terminal ' + field)
            if type(terminal.get('revision')) is not int or not 0 <= terminal['revision'] <= 9007199254740991:
                raise ValueError('Invalid terminal revision')
            fields += identity
        return {key: terminal.get(key) for key in fields}

    @staticmethod
    def _terminal_in_root(terminal, root):
        try:
            cwd = terminal['cwd']
            return bool(cwd) and Path(cwd).is_absolute() and Path(cwd).resolve().is_relative_to(Path(root).resolve())
        except (OSError, ValueError):
            return False

    def terminals(self, window, root):
        """Return captured terminals in this project from the current report."""
        return [terminal for terminal in self.state(window, root).get('terminals', [])
                if self._terminal_in_root(terminal, root)]

    def windows(self):
        with self.lock:
            return sorted([copy.deepcopy(c) for c in self.clients.values() if time.monotonic() - c['seen'] < 6],
                          key=lambda c: c['focus_time'], reverse=True)

    def state(self, window, root):
        for state in self.windows():
            if state['window'] == window and str(Path(root).resolve()) in state['roots']:
                return state
        raise GuideError('VS Code disconnected or the selected folder closed. Reopen it, then click Retry.')

    def open_location(self, window, root, relative, line):
        self.state(window, root)
        path = ProjectFiles(root).resolve(relative, exists=True)
        if not path.is_file():
            raise GuideError('Create this file yourself in VS Code first.')
        with self.lock:
            self.commands.setdefault(window, []).append(dict(type='open', root=str(Path(root).resolve()),
                                                             path=str(path), line=max(1, int(line))))

    def terminal_output(self, window, root, terminal_id=None):
        state = self.fresh_state(window, root)
        if terminal_id is not None:
            terminal = next((item for item in state.get('terminals', []) if item['id'] == terminal_id), None)
            if terminal is None:
                raise GuideError('The pinned terminal closed or is no longer captured. Select a terminal again.')
        else:
            terminal = state.get('terminal')
        if not terminal:
            raise GuideError('No terminal command output captured. Reload VS Code with the updated AI-Live '
                             'extension, then run your command in a terminal with shell integration enabled '
                             'and click Check terminal output again.')
        if not terminal['cwd'] or not Path(terminal['cwd']).is_absolute():
            raise GuideError('The terminal did not report its working folder. Use a shell with VS Code shell integration.')
        if not self._terminal_in_root(terminal, root):
            raise GuideError('Select a terminal whose last command ran inside this project, then check again.')
        if not terminal['output'].strip() and terminal['exit_code'] is None:
            raise GuideError('The terminal command has not produced output yet. Wait for output and check again.')
        return terminal

    def fresh_state(self, window, root):
        self.state(window, root)
        token = secrets.token_hex(12)
        deadline = time.monotonic() + 4
        with self.condition:
            self.refresh_requests[window] = token
            self.condition.notify_all()
            while self.clients.get(window, {}).get('ack') != token:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GuideError('VS Code did not acknowledge a fresh editor check. Click Retry.')
                self.condition.wait(remaining)
        return self.state(window, root)

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        try:
            if json.loads(self.discovery.read_text(encoding='utf-8')).get('token') == self.token:
                self.discovery.unlink()
        except (OSError, ValueError):
            pass
