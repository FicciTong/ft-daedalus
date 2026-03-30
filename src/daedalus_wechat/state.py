from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class SessionRecord:
    thread_id: str
    label: str
    cwd: str
    source: str
    created_at: str
    updated_at: str
    tmux_session: str | None = None


@dataclass
class BridgeState:
    active_session_id: str | None = None
    active_tmux_session: str | None = None
    get_updates_buf: str = ""
    bound_user_id: str | None = None
    bound_context_token: str | None = None
    progress_updates_enabled: bool | None = None
    delivery_seq: int = 0
    outbox_waiting_for_bind: bool = False
    outbox_waiting_for_bind_since: str = ""
    mirror_offsets: dict[str, int] = field(default_factory=dict)
    recent_delivery_cursors: dict[str, int] = field(default_factory=dict)
    last_progress_summaries: dict[str, str] = field(default_factory=dict)
    pending_outbox: list[dict[str, str]] = field(default_factory=list)
    pending_outbox_overflow_dropped: int = 0
    sessions: dict[str, SessionRecord] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> BridgeState:
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        sessions: dict[str, SessionRecord] = {}
        for key, value in raw.get("sessions", {}).items():
            sessions[key] = SessionRecord(
                thread_id=str(value.get("thread_id", key)),
                label=str(value.get("label", key)),
                cwd=str(value.get("cwd", "")),
                source=str(value.get("source", "")),
                created_at=str(value.get("created_at", now_iso())),
                updated_at=str(value.get("updated_at", now_iso())),
                tmux_session=(
                    str(value["tmux_session"]).strip()
                    if value.get("tmux_session")
                    else None
                ),
            )
        return cls(
            active_session_id=raw.get("active_session_id"),
            active_tmux_session=raw.get("active_tmux_session"),
            get_updates_buf=raw.get("get_updates_buf", ""),
            bound_user_id=raw.get("bound_user_id"),
            bound_context_token=raw.get("bound_context_token"),
            progress_updates_enabled=raw.get("progress_updates_enabled"),
            delivery_seq=int(raw.get("delivery_seq", 0) or 0),
            outbox_waiting_for_bind=bool(raw.get("outbox_waiting_for_bind", False)),
            outbox_waiting_for_bind_since=str(raw.get("outbox_waiting_for_bind_since", "")),
            mirror_offsets={
                str(key): int(value)
                for key, value in (raw.get("mirror_offsets", {}) or {}).items()
            },
            recent_delivery_cursors={
                str(key): int(value)
                for key, value in (raw.get("recent_delivery_cursors", {}) or {}).items()
            },
            last_progress_summaries={
                str(key): str(value)
                for key, value in (raw.get("last_progress_summaries", {}) or {}).items()
            },
            pending_outbox=[
                {
                    "to": str(item.get("to", "")),
                    "text": str(item.get("text", "")),
                    "created_at": str(item.get("created_at", now_iso())),
                    "kind": str(item.get("kind", "message")),
                    "origin": str(item.get("origin", "bridge")),
                    "thread_id": (
                        str(item.get("thread_id")).strip()
                        if item.get("thread_id")
                        else ""
                    ),
                    "tmux_session": (
                        str(item.get("tmux_session")).strip()
                        if item.get("tmux_session")
                        else (
                            sessions[str(item.get("thread_id")).strip()].tmux_session or ""
                            if str(item.get("thread_id", "")).strip() in sessions
                            else ""
                        )
                    ),
                    "attempt_count": int(item.get("attempt_count", 1) or 1),
                    "last_attempt_at": str(
                        item.get("last_attempt_at", item.get("created_at", now_iso()))
                    ),
                    "last_error": str(item.get("last_error", "")),
                }
                for item in (raw.get("pending_outbox", []) or [])
                if str(item.get("to", "")).strip() and str(item.get("text", "")).strip()
            ],
            pending_outbox_overflow_dropped=int(
                raw.get("pending_outbox_overflow_dropped", 0) or 0
            ),
            sessions=sessions,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "active_session_id": self.active_session_id,
                    "active_tmux_session": self.active_tmux_session,
                    "get_updates_buf": self.get_updates_buf,
                    "bound_user_id": self.bound_user_id,
                    "bound_context_token": self.bound_context_token,
                    "progress_updates_enabled": self.progress_updates_enabled,
                    "delivery_seq": self.delivery_seq,
                    "outbox_waiting_for_bind": self.outbox_waiting_for_bind,
                    "mirror_offsets": self.mirror_offsets,
                    "recent_delivery_cursors": self.recent_delivery_cursors,
                    "last_progress_summaries": self.last_progress_summaries,
                    "pending_outbox": self.pending_outbox,
                    "pending_outbox_overflow_dropped": self.pending_outbox_overflow_dropped,
                    "sessions": {
                        key: asdict(value) for key, value in self.sessions.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    def touch_session(
        self,
        thread_id: str,
        *,
        label: str,
        cwd: str,
        source: str,
        tmux_session: str | None = None,
    ) -> SessionRecord:
        current = self.sessions.get(thread_id)
        created_at = current.created_at if current else now_iso()
        record = SessionRecord(
            thread_id=thread_id,
            label=label,
            cwd=cwd,
            source=source,
            created_at=created_at,
            updated_at=now_iso(),
            tmux_session=tmux_session or (current.tmux_session if current else None),
        )
        self.sessions[thread_id] = record
        return record

    def get_mirror_offset(self, thread_id: str) -> int:
        return int(self.mirror_offsets.get(thread_id, 0))

    def set_mirror_offset(self, thread_id: str, offset: int) -> None:
        self.mirror_offsets[thread_id] = int(offset)

    def get_recent_delivery_cursor(self, scope_key: str) -> int | None:
        if scope_key not in self.recent_delivery_cursors:
            return None
        return int(self.recent_delivery_cursors[scope_key])

    def set_recent_delivery_cursor(self, scope_key: str, seq: int) -> None:
        self.recent_delivery_cursors[str(scope_key)] = int(seq)

    def clear_recent_delivery_cursor(self, scope_key: str) -> None:
        self.recent_delivery_cursors.pop(str(scope_key), None)

    def get_last_progress_summary(self, thread_id: str) -> str:
        return str(self.last_progress_summaries.get(thread_id, ""))

    def set_last_progress_summary(self, thread_id: str, summary: str) -> None:
        self.last_progress_summaries[thread_id] = str(summary)

    def enqueue_pending(self, *, to_user_id: str, text: str) -> None:
        self.enqueue_pending_with_meta(
            to_user_id=to_user_id,
            text=text,
            kind="message",
            origin="bridge",
            thread_id=None,
            tmux_session=None,
        )

    def enqueue_pending_with_meta(
        self,
        *,
        to_user_id: str,
        text: str,
        kind: str,
        origin: str,
        thread_id: str | None,
        tmux_session: str | None,
        error: str | None = None,
    ) -> None:
        body = text.strip()
        if not to_user_id or not body:
            return
        resolved_tmux_session = self._resolve_pending_tmux_session(
            thread_id=thread_id,
            tmux_session=tmux_session,
        )
        dedupe_key = (
            str(to_user_id),
            body,
            str(kind),
            str(origin),
            str(thread_id or ""),
            str(resolved_tmux_session or ""),
        )
        now = now_iso()
        for item in self.pending_outbox:
            item_key = (
                str(item.get("to", "")),
                str(item.get("text", "")).strip(),
                str(item.get("kind", "message")),
                str(item.get("origin", "bridge")),
                str(item.get("thread_id", "")),
                str(item.get("tmux_session", "")),
            )
            if item_key != dedupe_key:
                continue
            item["last_attempt_at"] = now
            item["attempt_count"] = int(item.get("attempt_count", 1) or 1) + 1
            if error:
                item["last_error"] = str(error)
            return
        self.pending_outbox.append(
            {
                "to": str(to_user_id),
                "text": body,
                "created_at": now,
                "kind": str(kind),
                "origin": str(origin),
                "thread_id": str(thread_id or ""),
                "tmux_session": str(resolved_tmux_session or ""),
                "attempt_count": 1,
                "last_attempt_at": now,
                "last_error": str(error or ""),
            }
        )
        max_items = 1000
        overflow = len(self.pending_outbox) - max_items
        if overflow > 0:
            self.pending_outbox_overflow_dropped += overflow
            self.pending_outbox = self.pending_outbox[-max_items:]

    def has_pending_for_scope(
        self, *, to_user_id: str, tmux_session: str | None
    ) -> bool:
        active_scope = str(tmux_session or "").strip()
        for item in self.pending_outbox:
            if item.get("to") != to_user_id:
                continue
            item_scope = str(item.get("tmux_session", "")).strip()
            if not item_scope or item_scope == active_scope:
                return True
        return False

    def pop_pending_for_scope(
        self, *, to_user_id: str, tmux_session: str | None
    ) -> list[dict[str, str]]:
        matched: list[dict[str, str]] = []
        kept: list[dict[str, str]] = []
        active_scope = str(tmux_session or "").strip()
        for item in self.pending_outbox:
            item_scope = str(item.get("tmux_session", "")).strip()
            if item.get("to") == to_user_id and (
                not item_scope or item_scope == active_scope
            ):
                matched.append(item)
            else:
                kept.append(item)
        self.pending_outbox = kept
        return matched

    def trim_pending_for_scope(
        self, *, to_user_id: str, tmux_session: str | None, keep_last: int
    ) -> tuple[int, int]:
        if keep_last < 0:
            keep_last = 0
        active_scope = str(tmux_session or "").strip()
        scoped: list[dict[str, str]] = []
        kept: list[dict[str, str]] = []
        for item in self.pending_outbox:
            item_scope = str(item.get("tmux_session", "")).strip()
            if item.get("to") == to_user_id and (
                not item_scope or item_scope == active_scope
            ):
                scoped.append(item)
            else:
                kept.append(item)
        if not scoped:
            return (0, 0)
        retained = scoped[-keep_last:] if keep_last else []
        dropped = max(0, len(scoped) - len(retained))
        self.pending_outbox = kept + retained
        return (dropped, len(retained))

    def _resolve_pending_tmux_session(
        self, *, thread_id: str | None, tmux_session: str | None
    ) -> str | None:
        normalized_tmux = str(tmux_session or "").strip()
        if normalized_tmux:
            return normalized_tmux
        normalized_thread = str(thread_id or "").strip()
        if not normalized_thread:
            return None
        record = self.sessions.get(normalized_thread)
        if not record or not record.tmux_session:
            return None
        return record.tmux_session

    def next_delivery_seq(self) -> int:
        self.delivery_seq += 1
        return self.delivery_seq
