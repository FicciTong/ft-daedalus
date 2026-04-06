"""Room transcript log for group mode.

Appends every group-mode message (owner inbound + agent outbound) to a
JSONL file so any agent can see recent room context when @-mentioned.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def append_room_message(
    *,
    transcript_file: Path,
    speaker: str,
    direction: str,
    body: str,
    images: list[str] | None = None,
) -> None:
    """Append one message to the room transcript."""
    entry = {
        "ts": _now_iso(),
        "speaker": speaker,
        "direction": direction,
        "body": body[:2000],
    }
    if images:
        entry["images"] = images[:10]
    transcript_file.parent.mkdir(parents=True, exist_ok=True)
    with transcript_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_recent_room_messages(
    *,
    transcript_file: Path,
    limit: int = 20,
) -> list[dict]:
    """Read the most recent N messages from the transcript."""
    if not transcript_file.exists():
        return []
    lines: list[str] = []
    try:
        with transcript_file.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    recent = lines[-limit:] if len(lines) > limit else lines
    result: list[dict] = []
    for line in recent:
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


def format_room_context(messages: list[dict], *, limit: int = 20) -> str:
    """Format recent room messages as readable context for agent prompts."""
    if not messages:
        return ""
    lines = ["[Room 最近对话记录]"]
    for msg in messages[-limit:]:
        speaker = msg.get("speaker", "?")
        body = msg.get("body", "").strip()
        if not body:
            continue
        prefix = "→" if msg.get("direction") == "inbound" else "←"
        lines.append(f"{prefix} [{speaker}] {body[:300]}")
    return "\n".join(lines)
