"""In-memory interview sessions: no database, no login. A session lives until it expires or the server stops."""

import threading
import time
import uuid
from dataclasses import dataclass, field

from app.coach import Feedback, Submission

MAX_SESSIONS = 200  # oldest sessions are dropped beyond this, so memory stays bounded
TTL_SECONDS = 2 * 60 * 60


@dataclass
class Session:
    id: str
    client_id: str
    created: float
    last_used: float
    lock: threading.Lock = field(default_factory=threading.Lock)  # one turn at a time per session
    head: str | None = None  # checkpoint to continue from after a failed turn; None means the latest
    submission: Submission | None = None
    feedback: Feedback | None = None

    def config(self) -> dict:
        configurable = {"thread_id": self.id}
        if self.head:
            configurable["checkpoint_id"] = self.head
        return {"configurable": configurable}


class SessionStore:
    def __init__(self, checkpointer, max_sessions: int = MAX_SESSIONS, ttl_seconds: float = TTL_SECONDS):
        self._checkpointer = checkpointer
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self.max_sessions, self.ttl = max_sessions, ttl_seconds

    def create(self, client_id: str) -> Session:
        now = time.monotonic()
        session = Session(uuid.uuid4().hex, client_id, now, now)
        with self._lock:
            self._evict(now)
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        now = time.monotonic()
        with self._lock:
            session = self._sessions.get(session_id)
            if session and now - session.last_used > self.ttl:
                self._drop(session_id)
                return None
            if session:
                session.last_used = now
            return session

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._drop(session_id)

    def _evict(self, now: float) -> None:
        for sid in [s.id for s in self._sessions.values() if now - s.last_used > self.ttl]:
            self._drop(sid)
        while len(self._sessions) >= self.max_sessions:
            self._drop(min(self._sessions.values(), key=lambda s: s.last_used).id)

    def _drop(self, session_id: str) -> None:
        if self._sessions.pop(session_id, None):
            self._checkpointer.delete_thread(session_id)
