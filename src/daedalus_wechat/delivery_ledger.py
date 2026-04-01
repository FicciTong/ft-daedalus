from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .state import BridgeState

EFFECTIVE_DELIVERY_STATUSES = frozenset({"sent", "flushed"})


def _parse_ts(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def append_delivery(
    *,
    state: BridgeState,
    state_file: Path | None = None,
    ledger_file: Path,
    to_user_id: str,
    text: str,
    status: str,
    kind: str,
    origin: str,
    thread_id: str | None = None,
    tmux_session: str | None = None,
    error: str | None = None,
) -> int:
    seq = state.next_delivery_seq()
    if state_file is not None:
        state.save(state_file)
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seq": seq,
        "ts": datetime.now(UTC).isoformat(),
        "to": to_user_id,
        "status": status,
        "kind": kind,
        "origin": origin,
        "thread": thread_id[:8] if thread_id else None,
        "tmux_session": str(tmux_session or "").strip() or None,
        "text": text,
    }
    if error:
        payload["error"] = error
    with ledger_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return seq


def read_recent_for_user(
    *,
    ledger_file: Path,
    to_user_id: str,
    limit: int = 6,
    after_seq: int | None = None,
    tmux_session: str | None = None,
    effective_only: bool = False,
    include_command_kinds: bool = True,
    recent_cluster_seconds: float | None = None,
) -> list[dict]:
    if not ledger_file.exists():
        return []
    results: list[dict] = []
    lines = ledger_file.read_text(encoding="utf-8").splitlines()
    scope = str(tmux_session or "").strip()
    if after_seq is not None:
        for raw in lines:
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if item.get("to") != to_user_id:
                continue
            if scope and str(item.get("tmux_session", "")).strip() != scope:
                continue
            if effective_only and str(item.get("status", "")).strip() not in EFFECTIVE_DELIVERY_STATUSES:
                continue
            if not include_command_kinds and str(item.get("kind", "")).strip() == "command":
                continue
            seq = int(item.get("seq", 0) or 0)
            if seq <= after_seq:
                continue
            results.append(item)
            if len(results) >= limit:
                break
        return results
    newest_ts: datetime | None = None
    for raw in reversed(lines):
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if item.get("to") != to_user_id:
            continue
        if scope and str(item.get("tmux_session", "")).strip() != scope:
            continue
        if effective_only and str(item.get("status", "")).strip() not in EFFECTIVE_DELIVERY_STATUSES:
            continue
        if not include_command_kinds and str(item.get("kind", "")).strip() == "command":
            continue
        if recent_cluster_seconds is not None:
            item_ts = _parse_ts(item.get("ts"))
            if newest_ts is None and item_ts is not None:
                newest_ts = item_ts
            elif newest_ts is not None and item_ts is not None:
                if (newest_ts - item_ts).total_seconds() > recent_cluster_seconds:
                    break
        results.append(item)
        if len(results) >= limit:
            break
    results.reverse()
    return results
