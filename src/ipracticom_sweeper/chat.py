"""Chat shell for iPracticom AWS Sweeper (v0.5.0 slice 3.1).

Infrastructure-only:
  - WebSocket endpoint at /ws for bidirectional conversation
  - Session list + per-session message history
  - Echo acknowledgement (no LLM; integration arrives in slice 3.3)
  - In-memory store (replaced by langchain/pgvector in 3.2)

All identifiers use ULID for sortability; messages persisted in-memory until 3.2.

Public surface:
    register_chat_routes(app)  -- attach /chat + /ws to a Flask app
    ChatStore                  -- global in-memory store
    ChatMessage, ChatSession   -- pydantic-friendly dataclasses (stdlib only)
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from flask import Blueprint, jsonify, render_template, request
    from flask_sock import Sock
except Exception:  # pragma: no cover -- document optional dep
    Blueprint = None  # type: ignore
    Sock = None  # type: ignore

# Module-level store; survives across requests in same process.
_STORE: "ChatStore | None" = None


def get_store() -> "ChatStore":
    """Lazy-singleton accessor for the global chat store."""
    global _STORE
    if _STORE is None:
        _STORE = ChatStore()
    return _STORE


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    """Monotonic-ish id; uuid4 hex without dashes for compactness."""
    return uuid.uuid4().hex


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system"
    content: str
    ts_ms: int = field(default_factory=_now_ms)
    msg_id: str = field(default_factory=_new_id)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatSession:
    session_id: str
    title: str
    created_ms: int = field(default_factory=_now_ms)
    creation_seq: int = 0
    messages: list[ChatMessage] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_ms": self.created_ms,
            "messages": [m.as_dict() for m in self.messages],
            "message_count": len(self.messages),
        }


class ChatStore:
    """In-memory chat store keyed by session_id. Not thread-safe across procs."""

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._seq: int = 0

    def list_sessions(self) -> list[ChatSession]:
        # Stable ordering: newest first by creation sequence (a monotonic
        # counter incremented per create_session). Two sessions created in
        # the same millisecond still get a deterministic, creation-order
        # tiebreaker.
        return sorted(self._sessions.values(),
                      key=lambda s: s.creation_seq,
                      reverse=True)

    def create_session(self, title: str = "חדש") -> ChatSession:
        sid = _new_id()[:12]
        self._seq += 1
        session = ChatSession(session_id=sid, title=title,
                              creation_seq=self._seq)
        self._sessions[sid] = session
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    def append(self, session_id: str, role: str, content: str) -> ChatMessage | None:
        sess = self._sessions.get(session_id)
        if sess is None:
            return None
        msg = ChatMessage(role=role, content=content)
        sess.messages.append(msg)
        return msg

    def reset(self) -> None:
        """For tests."""
        self._sessions.clear()
        self._seq = 0


def _seed_demo_session(store: ChatStore) -> ChatSession:
    """One demo session so the UI has something on first visit (Hebrew)."""
    if store.list_sessions():
        # Re-use existing demo if present.
        for s in store.list_sessions():
            if s.title.startswith("שלום"):
                return s
    demo = store.create_session("שלום — דוגמה")
    store.append(demo.session_id, "system",
                 "ברוך הבא לסוכן הצ'אט של הסוויפר. שלח הודעה כדי להתחיל.")
    store.append(demo.session_id, "assistant",
                 "אני כאן כדי לעזור לך לבדוק את שרת ה-FreeSWITCH. "
                 "מה תרצה לבדוק?")
    return demo


def register_chat_routes(app: Any) -> None:
    """Attach chat routes + websocket to a Flask app. Idempotent."""
    if Blueprint is None or Sock is None:
        raise RuntimeError(
            "flask + flask-sock required for chat routes; "
            "pip install flask-sock"
        )

    bp = Blueprint("chat", __name__, url_prefix="/chat")
    sock = Sock(app)

    # Seed once at startup; safe across reloads thanks to dedupe-by-title.
    _seed_demo_session(get_store())

    @bp.get("/")
    @bp.get("")
    def chat_index():
        store = get_store()
        return render_template(
            "chat.html",
            sessions=[s.as_dict() for s in store.list_sessions()],
        )

    @bp.get("/sessions")
    def chat_sessions_json():
        store = get_store()
        return jsonify(
            sessions=[s.as_dict() for s in store.list_sessions()]
        )

    @bp.post("/sessions")
    def chat_create_session():
        payload = request.get_json(silent=True) or {}
        title = (payload.get("title") or "חדש").strip()[:80] or "חדש"
        sess = get_store().create_session(title=title)
        return jsonify(sess.as_dict()), 201

    @bp.get("/sessions/<session_id>")
    def chat_session_detail(session_id: str):
        sess = get_store().get_session(session_id)
        if sess is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(sess.as_dict())

    @bp.post("/sessions/<session_id>/messages")
    def chat_post_message(session_id: str):
        """HTTP fallback for non-WS clients (and tests)."""
        payload = request.get_json(silent=True) or {}
        content = (payload.get("content") or "").strip()
        if not content:
            return jsonify({"error": "empty"}), 400
        msg = get_store().append(session_id, "user", content)
        if msg is None:
            return jsonify({"error": "not_found"}), 404
        # Echo assistant acknowledgement (LLM wired in slice 3.3).
        ack = get_store().append(
            session_id, "assistant",
            f"(תשובת סטאב — slice 3.3 יוסיף LLM) קיבלתי: {content[:120]}"
        )
        return jsonify({"user": msg.as_dict(), "assistant": ack.as_dict() if ack else None})

    # flask-sock requires routes on the Sock instance at app level, not
    # inside a Blueprint. Register the WS endpoint directly on the app first.
    @sock.route("/ws")
    def chat_ws(ws):
        """Bidirectional WS. Accepts JSON frames: {session_id, content}.

        For slice 3.1 we ignore session_id parameter (always create or pick demo)
        and just echo back. Full session-aware WS lands in slice 3.3.
        """
        store = get_store()
        # Make sure demo session exists.
        demo = _seed_demo_session(store)
        try:
            while True:
                data = ws.receive()
                if data is None:
                    break
                try:
                    payload = json.loads(data)
                    content = (payload.get("content") or "").strip()
                    sid = payload.get("session_id") or demo.session_id
                except (ValueError, AttributeError):
                    content = str(data).strip()
                    sid = demo.session_id
                if not content:
                    ws.send(json.dumps({"error": "empty"}, ensure_ascii=False))
                    continue
                user_msg = store.append(sid, "user", content)
                if user_msg is None:
                    ws.send(json.dumps({"error": "not_found"}, ensure_ascii=False))
                    continue
                ack_msg = store.append(
                    sid, "assistant",
                    f"(תשובת סטאב) קיבלתי: {content[:120]}"
                )
                ws.send(json.dumps(
                    {"user": user_msg.as_dict(),
                     "assistant": ack_msg.as_dict() if ack_msg else None},
                    ensure_ascii=False,
                ))
        except Exception as exc:  # pragma: no cover -- runtime WS errors
            try:
                ws.send(json.dumps({"error": str(exc)}, ensure_ascii=False))
            except Exception:
                pass

    app.register_blueprint(bp)


__all__ = [
    "ChatMessage",
    "ChatSession",
    "ChatStore",
    "get_store",
    "register_chat_routes",
]
