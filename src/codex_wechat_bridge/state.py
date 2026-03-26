from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
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
    get_updates_buf: str = ""
    bound_user_id: str | None = None
    bound_context_token: str | None = None
    progress_updates_enabled: bool | None = None
    mirror_offsets: dict[str, int] = field(default_factory=dict)
    last_progress_summaries: dict[str, str] = field(default_factory=dict)
    pending_outbox: list[dict[str, str]] = field(default_factory=list)
    sessions: dict[str, SessionRecord] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "BridgeState":
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
            get_updates_buf=raw.get("get_updates_buf", ""),
            bound_user_id=raw.get("bound_user_id"),
            bound_context_token=raw.get("bound_context_token"),
            progress_updates_enabled=raw.get("progress_updates_enabled"),
            mirror_offsets={
                str(key): int(value)
                for key, value in (raw.get("mirror_offsets", {}) or {}).items()
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
                }
                for item in (raw.get("pending_outbox", []) or [])
                if str(item.get("to", "")).strip() and str(item.get("text", "")).strip()
            ],
            sessions=sessions,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "active_session_id": self.active_session_id,
                    "get_updates_buf": self.get_updates_buf,
                    "bound_user_id": self.bound_user_id,
                    "bound_context_token": self.bound_context_token,
                    "progress_updates_enabled": self.progress_updates_enabled,
                    "mirror_offsets": self.mirror_offsets,
                    "last_progress_summaries": self.last_progress_summaries,
                    "pending_outbox": self.pending_outbox,
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

    def get_last_progress_summary(self, thread_id: str) -> str:
        return str(self.last_progress_summaries.get(thread_id, ""))

    def set_last_progress_summary(self, thread_id: str, summary: str) -> None:
        self.last_progress_summaries[thread_id] = str(summary)

    def enqueue_pending(self, *, to_user_id: str, text: str) -> None:
        body = text.strip()
        if not to_user_id or not body:
            return
        self.pending_outbox.append(
            {
                "to": str(to_user_id),
                "text": body,
                "created_at": now_iso(),
            }
        )
        self.pending_outbox = self.pending_outbox[-100:]

    def pop_pending_for(self, to_user_id: str) -> list[dict[str, str]]:
        matched: list[dict[str, str]] = []
        kept: list[dict[str, str]] = []
        for item in self.pending_outbox:
            if item.get("to") == to_user_id:
                matched.append(item)
            else:
                kept.append(item)
        self.pending_outbox = kept
        return matched
