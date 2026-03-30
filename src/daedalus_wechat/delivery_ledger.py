from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .state import BridgeState

EFFECTIVE_DELIVERY_STATUSES = frozenset({"sent", "flushed"})


def append_delivery(
    *,
    state: BridgeState,
    state_file: Path,
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
            seq = int(item.get("seq", 0) or 0)
            if seq <= after_seq:
                continue
            results.append(item)
            if len(results) >= limit:
                break
        return results
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
        results.append(item)
        if len(results) >= limit:
            break
    results.reverse()
    return results
