from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTRACT = "daedalus_wechat.owner_feedback_ledger"
ENTRY_CONTRACT = "daedalus_wechat.owner_feedback_entry"

ALLOWED_MARKS = (
    "useful",
    "noise",
    "watch",
    "write_card",
    "surface_blocker",
    "needs_review",
)

MARK_ALIASES = {
    "有用": "useful",
    "有意思": "useful",
    "useful": "useful",
    "噪音": "noise",
    "垃圾": "noise",
    "noise": "noise",
    "观察": "watch",
    "关注": "watch",
    "watch": "watch",
    "写卡": "write_card",
    "写战法": "write_card",
    "write_card": "write_card",
    "数据缺口": "surface_blocker",
    "缺数据": "surface_blocker",
    "surface_blocker": "surface_blocker",
    "需要review": "needs_review",
    "复核": "needs_review",
    "needs_review": "needs_review",
}


def default_owner_feedback_path() -> Path:
    """Return the local append-only owner-feedback ledger path."""

    daedalus_root = Path(__file__).resolve().parents[2]
    return daedalus_root / "var" / "reports" / "kairos_owner_feedback" / "owner_feedback.jsonl"


def normalize_mark(mark: str) -> str | None:
    normalized = mark.strip().lower()
    if not normalized:
        return None
    return MARK_ALIASES.get(normalized)


def feedback_help_text() -> str:
    return (
        "用法: /feedback <mark> <内容>\n"
        "mark=useful|noise|watch|write_card|surface_blocker|needs_review\n"
        "中文可用: 有用/噪音/观察/写卡/数据缺口/复核\n"
        "边界: feedback 只导研究方向和 owner 注意力；不改证据门、不改排名、不产生交易权威。"
    )


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _feedback_id(*, captured_at_utc: str, mark: str, text: str, source: str) -> str:
    digest = hashlib.sha256(
        f"{captured_at_utc}|{mark}|{text}|{source}".encode()
    ).hexdigest()[:16]
    return f"owner_feedback_{digest}"


def build_owner_feedback_entry(
    *,
    mark: str,
    text: str,
    source: str,
    captured_at_utc: str | None = None,
) -> dict[str, Any]:
    canonical_mark = normalize_mark(mark)
    clean_text = text.strip()
    if canonical_mark is None:
        raise ValueError(f"unknown feedback mark {mark!r}")
    if not clean_text:
        raise ValueError("feedback text is empty")
    captured = captured_at_utc or _utc_now_iso()
    return {
        "contract": ENTRY_CONTRACT,
        "feedback_id": _feedback_id(
            captured_at_utc=captured,
            mark=canonical_mark,
            text=clean_text,
            source=source,
        ),
        "captured_at_utc": captured,
        "source": source,
        "mark": canonical_mark,
        "text": clean_text,
        "route_scope": [
            "research_queue_direction_only",
            "owner_review_attention_only",
        ],
        "firewall": {
            "authority_delta": "none",
            "accepted_edges": 0,
            "report_only": True,
            "evidence_gate_mutation_allowed": False,
            "ranking_mutation_allowed": False,
            "candidate_promotion_allowed": False,
            "trading_authority_allowed": False,
            "advisory_claim_allowed": False,
            "owner_pnl_claim_allowed": False,
        },
        "accepted_edges": 0,
    }


def append_owner_feedback(
    *,
    mark: str,
    text: str,
    source: str,
    ledger_path: Path | None = None,
    captured_at_utc: str | None = None,
) -> dict[str, Any]:
    path = ledger_path or default_owner_feedback_path()
    entry = build_owner_feedback_entry(
        mark=mark,
        text=text,
        source=source,
        captured_at_utc=captured_at_utc,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return {**entry, "ledger_path": str(path)}


def _read_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def load_owner_feedback_summary(
    ledger_path: Path | None = None,
    *,
    recent_limit: int = 3,
) -> dict[str, Any]:
    path = ledger_path or default_owner_feedback_path()
    entries = _read_entries(path)
    mark_counts = Counter(str(entry.get("mark") or "unknown") for entry in entries)
    recent = entries[-recent_limit:] if recent_limit > 0 else []
    return {
        "contract": CONTRACT,
        "status": "OWNER_FEEDBACK_LEDGER_READY" if path.exists() else "OWNER_FEEDBACK_LEDGER_EMPTY",
        "ledger_path": str(path),
        "feedback_count": len(entries),
        "mark_counts": dict(sorted(mark_counts.items())),
        "recent_feedback": recent,
        "accepted_edges": 0,
        "firewall": {
            "feedback_route_scope": [
                "research_queue_direction_only",
                "owner_review_attention_only",
            ],
            "evidence_gate_mutation_allowed": False,
            "ranking_mutation_allowed": False,
            "candidate_promotion_allowed": False,
            "trading_authority_allowed": False,
            "advisory_claim_allowed": False,
        },
    }


def format_owner_feedback_summary(summary: dict[str, Any]) -> str:
    marks = summary.get("mark_counts") if isinstance(summary.get("mark_counts"), dict) else {}
    recent = summary.get("recent_feedback") if isinstance(summary.get("recent_feedback"), list) else []
    recent_text = "none"
    if recent:
        last = recent[-1]
        if isinstance(last, dict):
            text = str(last.get("text") or "").strip()
            recent_text = f"{last.get('mark', 'unknown')}:{text[:40]}"
    return (
        "反馈回路: "
        f"已记录={summary.get('feedback_count', 0)} "
        f"useful={marks.get('useful', 0)} "
        f"noise={marks.get('noise', 0)} "
        f"watch={marks.get('watch', 0)} "
        f"write_card={marks.get('write_card', 0)} "
        f"surface_blocker={marks.get('surface_blocker', 0)} "
        f"needs_review={marks.get('needs_review', 0)} "
        f"最近={recent_text} "
        "防火墙=只导研究/注意力,不改证据门/排名"
    )


def handle_owner_feedback_command(
    arg: str,
    *,
    source: str,
    ledger_path: Path | None = None,
) -> str:
    body = arg.strip()
    if not body or body.lower() in {"help", "帮助"}:
        return feedback_help_text()
    if body.lower() in {"status", "状态"}:
        return format_owner_feedback_summary(
            load_owner_feedback_summary(ledger_path=ledger_path)
        )
    mark, _, text = body.partition(" ")
    if not text.strip():
        return feedback_help_text()
    try:
        entry = append_owner_feedback(
            mark=mark,
            text=text,
            source=source,
            ledger_path=ledger_path,
        )
    except ValueError as exc:
        return f"feedback=blocked reason={exc}\n{feedback_help_text()}"
    return (
        "feedback=recorded\n"
        f"mark={entry['mark']}\n"
        f"feedback_id={entry['feedback_id']}\n"
        f"ledger={entry['ledger_path']}\n"
        "边界: 只导研究方向和 owner 注意力；不改证据门、不改排名、不产生交易权威。"
    )
