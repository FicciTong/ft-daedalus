from __future__ import annotations

import gzip
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .state import BridgeState

EFFECTIVE_DELIVERY_STATUSES = frozenset({"sent", "flushed"})

# Rotate when a JSONL file exceeds this size.
_ROTATE_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10 MB
# Keep this many archived rotations per file stem.
_ROTATE_RETAIN_COUNT = 3


def rotate_jsonl_if_needed(
    path: Path,
    *,
    threshold_bytes: int = _ROTATE_THRESHOLD_BYTES,
    retain: int = _ROTATE_RETAIN_COUNT,
) -> Path | None:
    """Rotate *path* if it exceeds *threshold_bytes*.

    The live file is gzip-compressed into ``<stem>.<timestamp>.jsonl.gz``
    and replaced with an empty file. Old archives beyond *retain* are pruned.
    Returns the archive path if rotation happened, else ``None``.
    """
    if not path.exists():
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size < threshold_bytes:
        return None
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    archive = path.with_suffix(f".{ts}.jsonl.gz")
    with path.open("rb") as src, gzip.open(archive, "wb") as dst:
        shutil.copyfileobj(src, dst)
    # Truncate the live file (preserves inode for any open handles).
    with path.open("w", encoding="utf-8"):
        pass
    # Prune old archives.
    stem = path.stem  # e.g. "deliveries"
    archives = sorted(
        (
            p
            for p in path.parent.iterdir()
            if p.name.startswith(f"{stem}.") and p.name.endswith(".jsonl.gz")
        ),
        key=lambda p: p.stat().st_mtime,
    )
    for stale in archives[:-retain]:
        stale.unlink(missing_ok=True)
    return archive


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


def _last_seq(ledger_file: Path) -> int:
    if not ledger_file.exists():
        return 0
    try:
        with ledger_file.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            pos = fh.tell()
            chunk = b""
            while pos > 0 and chunk.count(b"\n") < 8:
                step = min(8192, pos)
                pos -= step
                fh.seek(pos)
                chunk = fh.read(step) + chunk
    except OSError:
        return 0
    for raw in reversed(chunk.decode("utf-8", errors="replace").splitlines()):
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        return int(item.get("seq", 0) or 0)
    return 0


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
    state.delivery_seq = max(state.delivery_seq, _last_seq(ledger_file))
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


def _tail_lines(path: Path, *, max_bytes: int = 512 * 1024) -> list[str]:
    """Read the last *max_bytes* of *path* and return decoded lines."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            pos = fh.tell()
            read_size = min(max_bytes, pos)
            fh.seek(pos - read_size)
            chunk = fh.read(read_size)
    except OSError:
        return []
    text = chunk.decode("utf-8", errors="replace")
    # Drop potentially partial first line if we didn't read from BOF.
    lines = text.splitlines()
    if read_size < pos and lines:
        lines = lines[1:]
    return lines


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
    scope = str(tmux_session or "").strip()

    def _matches(item: dict) -> bool:
        if item.get("to") != to_user_id:
            return False
        if scope and str(item.get("tmux_session", "")).strip() != scope:
            return False
        if effective_only and str(item.get("status", "")).strip() not in EFFECTIVE_DELIVERY_STATUSES:
            return False
        if not include_command_kinds and str(item.get("kind", "")).strip() == "command":
            return False
        return True

    if after_seq is not None:
        # Forward scan from tail (after rotation, the file is small).
        results: list[dict] = []
        for raw in _tail_lines(ledger_file, max_bytes=2 * 1024 * 1024):
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not _matches(item):
                continue
            if int(item.get("seq", 0) or 0) <= after_seq:
                continue
            results.append(item)
            if len(results) >= limit:
                break
        return results

    # Recent tail query — read only the tail of the file.
    results = []
    newest_ts: datetime | None = None
    for raw in reversed(_tail_lines(ledger_file)):
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not _matches(item):
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
