"""Read persisted CLI conversations without resuming or submitting any turns."""
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from .files import GuideError
from .runner import codex_command, NO_WINDOW


class SessionReader:
    def __init__(self, cancelled=None):
        self.cancelled = cancelled or threading.Event()
        self.process = None
        self.messages = queue.Queue()
        self.sequence = 0

    def __enter__(self):
        self.process = subprocess.Popen(
            [*codex_command(), 'app-server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', creationflags=NO_WINDOW)
        def receive():
            try:
                for line in self.process.stdout:
                    try:
                        self.messages.put(json.loads(line))
                    except ValueError:
                        continue
            finally:
                self.messages.put(None)
        self.reader = threading.Thread(target=receive, daemon=True)
        self.reader.start()
        try:
            self.call('initialize', {'clientInfo': {'name': 'ai_live_session_reader', 'version': '1.0'}})
            self.process.stdin.write('{"method":"initialized"}\n')
            self.process.stdin.flush()
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        if self.process:
            if self.process.poll() is None:
                # npm's Node launcher can own a native app-server child. Killing
                # only the launcher on Windows leaves that child and its pipes.
                if os.name == 'nt':
                    try:
                        subprocess.run(['taskkill.exe', '/PID', str(self.process.pid), '/T', '/F'],
                                       capture_output=True, creationflags=NO_WINDOW, timeout=10)
                    except (OSError, subprocess.TimeoutExpired):
                        self.process.kill()
                else:
                    self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            self.reader.join(timeout=1)
            self.process.stdin.close()
            self.process.stdout.close()

    def call(self, method, params):
        if self.cancelled.is_set():
            raise GuideError('Cancelled.')
        self.sequence += 1
        self.process.stdin.write(json.dumps({'id': self.sequence, 'method': method, 'params': params}) + '\n')
        self.process.stdin.flush()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.cancelled.is_set():
                raise GuideError('Cancelled.')
            try:
                message = self.messages.get(timeout=0.1)
            except queue.Empty:
                continue
            if message is None:
                raise GuideError('Codex session reader disconnected. Retry.')
            if message.get('id') != self.sequence:
                continue
            if 'error' in message:
                raise GuideError('Codex could not read saved sessions. Check the CLI version and retry.')
            return message['result']
        raise GuideError('Timed out reading the Codex session. Retry.')

    def list_sessions(self, root):
        root = Path(root).resolve()
        cursor = None
        selected = []
        for _ in range(100):
            params = {'sourceKinds': ['cli'], 'sortKey': 'updated_at', 'sortDirection': 'desc',
                      'archived': False, 'limit': 100}
            if cursor:
                params['cursor'] = cursor
            page = self.call('thread/list', params)
            selected.extend(t for t in page.get('data', []) if t.get('source') == 'cli'
                            and not t.get('ephemeral', False) and t.get('cwd')
                            and Path(t['cwd']).resolve() == root)
            cursor = page.get('nextCursor')
            if not cursor or len(selected) >= 50:
                return selected[:50]
        return selected[:50]

    def read(self, root, thread_id):
        result = self.call('thread/read', {'threadId': thread_id, 'includeTurns': True})['thread']
        if (result.get('id') != thread_id or result.get('source') != 'cli'
                or result.get('ephemeral', False) or Path(result['cwd']).resolve() != Path(root).resolve()):
            raise GuideError('The selected Codex session is not available for this project. Choose a session again.')
        return result

    def latest(self, root):
        # Filter by source as well as ephemeral: our guide uses exec --ephemeral.
        # Scan in server recency order and compare canonical paths locally so
        # Windows path casing does not defeat exact server-side cwd filters.
        root = Path(root).resolve()
        cursor = None
        for _ in range(100):
            params = {'sourceKinds': ['cli'], 'sortKey': 'updated_at', 'sortDirection': 'desc',
                      'archived': False, 'limit': 100}
            if cursor:
                params['cursor'] = cursor
            page = self.call('thread/list', params)
            for thread in page.get('data', []):
                if (thread.get('source') == 'cli' and not thread.get('ephemeral', False)
                        and thread.get('cwd') and Path(thread['cwd']).resolve() == root):
                    result = self.call('thread/read', {'threadId': thread['id'], 'includeTurns': True})['thread']
                    if result.get('source') != 'cli' or Path(result['cwd']).resolve() != root:
                        raise GuideError('Codex session identity changed during the check. Retry.')
                    return result
            next_cursor = page.get('nextCursor')
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        raise GuideError('No saved Codex CLI session found for this project. Start Codex in the project folder, '
                         'submit the current prompt, and click Check output after it responds.')


def normalized(text):
    return ' '.join(text.split())


def session_evidence(thread, current_prompt):
    turns = thread.get('turns', [])
    if not turns:
        raise GuideError('The latest Codex session has no saved response yet. Wait and check again.')
    # Never fall back to an older completed response while a newer turn runs.
    turn = turns[-1]
    if turn.get('status') != 'completed':
        raise GuideError('The latest Codex response is not saved as complete yet. Wait and check again.')
    items = turn.get('items', [])
    # The user pins the session. Prompt text is review context, not an identity
    # check: users may edit prompts or submit manual verification follow-ups.
    relevant = turns[-1:]
    output = []
    for entry in relevant:
        parts = []
        for item in entry.get('items', []):
            if item.get('type') == 'userMessage':
                parts.append('User: ' + '\n'.join(p.get('text', '') for p in item.get('content', [])
                                                 if p.get('type') == 'text'))
            elif item.get('type') == 'agentMessage':
                parts.append('Codex: ' + item.get('text', ''))
        output.append('\n\n'.join(parts))
    if not any(item.get('type') == 'agentMessage' and item.get('text', '').strip() for item in items):
        raise GuideError('The latest saved turn has no Codex answer yet. Wait and check again.')
    if len(output[-1]) > 100000:
        raise GuideError('The saved response exceeds the review limit. Ask Codex for a concise response '
                         'covering the current prompt, then check again.')
    # Keep complete turns, allowing a concise follow-up to recover from an
    # oversized earlier answer. The original prompt is also in guide context.
    truncated = False
    while len('\n\n'.join(output)) > 100000:
        output.pop(0)
        truncated = True
    text = '\n\n'.join(output)
    return {'source': 'codex_session', 'id': thread['id'], 'execution_id': turn['id'],
            'revision': thread.get('updatedAt', 0), 'name': thread.get('name') or thread['id'],
            'cwd': thread['cwd'], 'command': 'codex', 'output': text,
            'running': False, 'truncated': truncated, 'exit_code': None}


def read_latest_output(root, current_prompt, cancelled=None):
    with SessionReader(cancelled) as reader:
        return session_evidence(reader.latest(root), current_prompt)


def read_session_output(root, thread_id, current_prompt, cancelled=None):
    with SessionReader(cancelled) as reader:
        return session_evidence(reader.read(root, thread_id), current_prompt)
