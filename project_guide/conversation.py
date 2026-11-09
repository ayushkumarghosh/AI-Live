"""Thread-safe retained spoken project updates, scoped to a selection token."""

from hashlib import sha256
from threading import RLock


class ProjectUpdateStore:
    """Use a fresh session token per selection. Snapshots never consume updates.

    Revisions restart on selection changes. Only consecutive equal normalized
    source updates are deduplicated. dropped_updates reports history lost to the
    queue bound; an update has truncated=True when its source text exceeded the
    text bound (absent means false).
    """

    def __init__(self, max_updates=64, max_text_chars=2000):
        if max_updates <= 0 or max_text_chars <= 0:
            raise ValueError("update and text limits must be positive")
        self._max_updates = max_updates
        self._max_text_chars = max_text_chars
        self._lock = RLock()
        self._session_id = ""
        self._revision = 0
        self._updates = []
        self._dropped_updates = 0
        self._last_source_digest = None

    @property
    def active_session_id(self):
        with self._lock:
            return self._session_id

    def activate(self, session_id):
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        with self._lock:
            if session_id != self._session_id:
                self.clear()
                self._session_id = session_id

    def clear(self):
        with self._lock:
            self._session_id = ""
            self._revision = 0
            self._updates = []
            self._dropped_updates = 0
            self._last_source_digest = None

    def record(self, session_id, text):
        """Return whether a new update was retained for the active token."""
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        text = text.strip()
        # Compare full source text without retaining unbounded text in memory.
        source_digest = sha256(text.encode('utf-8', errors='surrogatepass')).digest()
        truncated = len(text) > self._max_text_chars
        if truncated:
            text = text[:self._max_text_chars - 1] + "…"
        with self._lock:
            if not session_id or session_id != self._session_id or not text:
                return False
            if source_digest == self._last_source_digest:
                return False
            self._revision += 1
            self._last_source_digest = source_digest
            update = {"revision": self._revision, "text": text}
            if truncated:
                update["truncated"] = True
            self._updates.append(update)
            if len(self._updates) > self._max_updates:
                self._updates.pop(0)
                self._dropped_updates += 1
            return True

    def snapshot(self, session_id):
        with self._lock:
            current = bool(session_id) and session_id == self._session_id
            return {
                "session_id": session_id,
                "revision": self._revision if current else 0,
                "updates": [dict(update) for update in self._updates] if current else [],
                "dropped_updates": self._dropped_updates if current else 0,
            }


# Shared by the controller and realtime session unless explicitly injected.
project_update_store = ProjectUpdateStore()
