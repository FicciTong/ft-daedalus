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
            sessions=sessions,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "active_session_id": self.active_session_id,
                    "get_updates_buf": self.get_updates_buf,
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
