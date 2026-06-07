from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

VALID_MESSAGE_MODES = frozenset(
    {
        "announce",
        "message",
        "task",
        "panel",
        "debate",
        "review_request",
        "agent_reply",
    }
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def default_room_dir() -> Path:
    raw = os.environ.get("DAEDALUS_AGENT_ROOM_DIR")
    if raw and raw.strip():
        return Path(raw).expanduser()
    return Path("~/.local/state/daedalus-agent-room").expanduser()


class CommandRunner(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True)
class AgentSession:
    agent_id: str
    source: str
    alive: bool
    session_name: str
    attached: bool | None = None
    windows: int | None = None


class TmuxRoster:
    """Read-only tmux session discovery.

    This class intentionally uses only `tmux list-sessions`. It never sends
    keys, captures pane output, renames sessions, detaches clients, or kills
    sessions.
    """

    def __init__(self, *, command_runner: CommandRunner | None = None) -> None:
        self._command_runner = command_runner or subprocess.run

    def list_sessions(self) -> list[AgentSession]:
        try:
            result = self._command_runner(
                [
                    "tmux",
                    "list-sessions",
                    "-F",
                    "#{session_name}\t#{session_attached}\t#{session_windows}",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return []
        if result.returncode != 0:
            return []
        sessions: list[AgentSession] = []
        for line in result.stdout.splitlines():
            raw = line.strip()
            if not raw:
                continue
            parts = raw.split("\t")
            session_name = parts[0].strip()
            if not session_name:
                continue
            sessions.append(
                AgentSession(
                    agent_id=session_name,
                    source="tmux",
                    alive=True,
                    session_name=session_name,
                    attached=_parse_bool(parts[1]) if len(parts) > 1 else None,
                    windows=_parse_int(parts[2]) if len(parts) > 2 else None,
                )
            )
        return sessions


class AgentRoom:
    def __init__(self, room_dir: Path | None = None) -> None:
        self.room_dir = (room_dir or default_room_dir()).expanduser()

    @property
    def messages_file(self) -> Path:
        return self.room_dir / "messages.jsonl"

    @property
    def artifact_ledger_file(self) -> Path:
        return self.room_dir / "artifact_ledger.jsonl"

    @property
    def control_file(self) -> Path:
        return self.room_dir / "control.json"

    @property
    def cursor_dir(self) -> Path:
        return self.room_dir / "cursors"

    def send_message(
        self,
        *,
        from_actor: str,
        text: str,
        to: list[str] | None = None,
        mode: str = "message",
        topic_id: str | None = None,
        round_limit: int | None = None,
        write_allowed: bool = False,
        source: str = "local-cli",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mode = _normalize_mode(mode)
        from_actor = _required_text(from_actor, "from_actor")
        body = _required_text(text, "text")
        recipients = _normalize_recipients(to or [])
        control = self.read_control()
        payload: dict[str, Any] = {
            "id": f"msg_{uuid.uuid4().hex}",
            "ts": now_iso(),
            "kind": "room_message",
            "mode": mode,
            "topic_id": topic_id or f"topic_{datetime.now(UTC):%Y%m%d}",
            "from": from_actor,
            "to": recipients,
            "text": body,
            "round_limit": round_limit,
            "write_allowed": bool(write_allowed),
            "source": source,
            "paused_at_send": bool(control.get("paused", False)),
            "metadata": metadata or {},
        }
        self._append_jsonl(self.messages_file, payload)
        return payload

    def record_artifact(
        self,
        *,
        path: str,
        by: str,
        topic_id: str | None = None,
        kind: str = "artifact",
        note: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact_path = _required_text(path, "path")
        payload: dict[str, Any] = {
            "id": f"artifact_{uuid.uuid4().hex}",
            "ts": now_iso(),
            "kind": _required_text(kind, "kind"),
            "topic_id": topic_id or f"topic_{datetime.now(UTC):%Y%m%d}",
            "by": _required_text(by, "by"),
            "path": artifact_path,
            "note": note.strip(),
            "metadata": metadata or {},
        }
        self._append_jsonl(self.artifact_ledger_file, payload)
        return payload

    def read_control(self) -> dict[str, Any]:
        if not self.control_file.exists():
            return {
                "paused": False,
                "updated_at": "",
                "updated_by": "",
                "reason": "",
            }
        try:
            raw = json.loads(self.control_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "paused": True,
                "updated_at": now_iso(),
                "updated_by": "agent_room",
                "reason": "control file unreadable; fail closed",
            }
        return {
            "paused": bool(raw.get("paused", False)),
            "updated_at": str(raw.get("updated_at", "")),
            "updated_by": str(raw.get("updated_by", "")),
            "reason": str(raw.get("reason", "")),
        }

    def set_paused(self, *, paused: bool, by: str, reason: str = "") -> dict[str, Any]:
        payload = {
            "paused": bool(paused),
            "updated_at": now_iso(),
            "updated_by": _required_text(by, "by"),
            "reason": reason.strip(),
        }
        self.room_dir.mkdir(parents=True, exist_ok=True)
        self.control_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        event = {
            "id": f"control_{uuid.uuid4().hex}",
            "ts": payload["updated_at"],
            "kind": "room_paused" if paused else "room_resumed",
            "from": payload["updated_by"],
            "reason": payload["reason"],
        }
        self._append_jsonl(self.messages_file, event)
        return payload

    def status(self, *, sessions: list[AgentSession] | None = None) -> dict[str, Any]:
        control = self.read_control()
        last_messages = self.tail_jsonl(self.messages_file, limit=3)
        return {
            "room_dir": str(self.room_dir),
            "messages_file": str(self.messages_file),
            "artifact_ledger_file": str(self.artifact_ledger_file),
            "paused": control["paused"],
            "pause_reason": control["reason"],
            "message_count": _count_jsonl(self.messages_file),
            "artifact_count": _count_jsonl(self.artifact_ledger_file),
            "session_count": len(sessions or []),
            "sessions": [asdict(session) for session in (sessions or [])],
            "last_messages": last_messages,
        }

    def pending_for_agent(
        self,
        *,
        agent_id: str,
        limit: int = 10,
        ack: bool = False,
    ) -> list[dict[str, Any]]:
        agent = _normalize_agent_id(agent_id)
        if self.read_control()["paused"]:
            return []
        start_index = self._read_cursor(agent)
        rows = self._read_messages_from(start_index=start_index)
        pending: list[dict[str, Any]] = []
        last_seen_index: int | None = None
        for line_index, payload in rows:
            last_seen_index = line_index
            if not self._is_deliverable(payload, agent_id=agent):
                continue
            item = dict(payload)
            item["cursor_index"] = line_index
            pending.append(item)
            if len(pending) >= max(1, limit):
                break
        if ack:
            if pending:
                self._write_cursor(agent, int(pending[-1]["cursor_index"]) + 1)
            elif last_seen_index is not None:
                self._write_cursor(agent, last_seen_index + 1)
        return pending

    def run_watch(
        self,
        *,
        agent_id: str,
        interval_seconds: float = 2.0,
        limit: int = 10,
        once: bool = False,
        from_end: bool = False,
    ):
        """Yield pending messages for one agent and advance its cursor."""
        agent = _normalize_agent_id(agent_id)
        if from_end:
            self.set_cursor_to_end(agent_id=agent)
        while True:
            yield from self.pending_for_agent(agent_id=agent, limit=limit, ack=True)
            if once:
                return
            time.sleep(max(0.2, interval_seconds))

    def set_cursor_to_end(self, *, agent_id: str) -> dict[str, Any]:
        agent = _normalize_agent_id(agent_id)
        next_index = _count_jsonl(self.messages_file)
        self._write_cursor(agent, next_index)
        return {
            "agent_id": agent,
            "next_index": next_index,
            "updated_at": now_iso(),
        }

    def ack_through(self, *, agent_id: str, cursor_index: int) -> dict[str, Any]:
        agent = _normalize_agent_id(agent_id)
        next_index = max(0, int(cursor_index) + 1)
        self._write_cursor(agent, next_index)
        return {
            "agent_id": agent,
            "next_index": next_index,
            "updated_at": now_iso(),
        }

    def tail_jsonl(self, path: Path, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0 or not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                item = {"kind": "unparseable", "text": line}
            rows.append(item)
        return rows

    def _read_messages_from(
        self, *, start_index: int
    ) -> list[tuple[int, dict[str, Any]]]:
        if not self.messages_file.exists():
            return []
        rows: list[tuple[int, dict[str, Any]]] = []
        for line_index, line in enumerate(
            self.messages_file.read_text(encoding="utf-8").splitlines()
        ):
            if line_index < start_index:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append((line_index, payload))
        return rows

    def _is_deliverable(self, payload: dict[str, Any], *, agent_id: str) -> bool:
        if payload.get("kind") != "room_message":
            return False
        if _normalize_agent_id(str(payload.get("from", ""))) == agent_id:
            return False
        recipients = _normalize_recipients(
            [str(value) for value in (payload.get("to") or [])]
        )
        if agent_id in recipients:
            return True
        mode = str(payload.get("mode", "")).strip()
        return not recipients and mode == "announce"

    def _cursor_file(self, agent_id: str) -> Path:
        return self.cursor_dir / f"{_normalize_agent_id(agent_id)}.json"

    def _read_cursor(self, agent_id: str) -> int:
        path = self._cursor_file(agent_id)
        if not path.exists():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        return max(0, int(payload.get("next_index", 0) or 0))

    def _write_cursor(self, agent_id: str, next_index: int) -> None:
        payload = {
            "agent_id": _normalize_agent_id(agent_id),
            "next_index": max(0, int(next_index)),
            "updated_at": now_iso(),
        }
        self.cursor_dir.mkdir(parents=True, exist_ok=True)
        self._cursor_file(agent_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _normalize_mode(mode: str) -> str:
    value = str(mode or "").strip().lower().replace("-", "_")
    if value not in VALID_MESSAGE_MODES:
        allowed = ", ".join(sorted(VALID_MESSAGE_MODES))
        raise ValueError(f"unsupported mode={mode!r}; allowed={allowed}")
    return value


def _normalize_recipients(raw: list[str]) -> list[str]:
    values: list[str] = []
    for item in raw:
        for part in str(item or "").replace(",", " ").split():
            value = _normalize_agent_id(part)
            if value and value not in values:
                values.append(value)
    return values


def _normalize_agent_id(raw: str) -> str:
    return str(raw or "").strip().lstrip("@")


def _required_text(raw: str, label: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{label} is required")
    return value


def _parse_bool(raw: str) -> bool | None:
    value = str(raw or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_int(raw: str) -> int | None:
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)
