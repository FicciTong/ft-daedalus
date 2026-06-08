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

MARK_ROUTE_PROJECTION = {
    "useful": {
        "route": "owner_attention_research_prior",
        "next_action": "prioritize similar owner-review units for comparison only",
    },
    "watch": {
        "route": "owner_watchlist_research_prior",
        "next_action": "keep on the owner-visible watch surface and gather outcomes",
    },
    "write_card": {
        "route": "research_card_draft_backlog",
        "next_action": "draft or bind a machine-executable hypothesis before evidence",
    },
    "surface_blocker": {
        "route": "surface_blocker_triage",
        "next_action": "verify the missing surface before rerunning affected cells",
    },
    "needs_review": {
        "route": "peer_review_backlog",
        "next_action": "route to read-only review before changing research direction",
    },
    "noise": {
        "route": "noise_review_backlog",
        "next_action": "inspect why owner saw noise; do not auto-demote evidence",
    },
}

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


def default_owner_feedback_route_queue_path() -> Path:
    """Return the derived research-route queue artifact path."""

    daedalus_root = Path(__file__).resolve().parents[2]
    return (
        daedalus_root
        / "var"
        / "reports"
        / "kairos_owner_feedback"
        / "owner_feedback_research_routes_latest.json"
    )


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


def _project_feedback_route(entry: dict[str, Any]) -> dict[str, Any]:
    mark = str(entry.get("mark") or "unknown")
    projection = MARK_ROUTE_PROJECTION.get(
        mark,
        {
            "route": "unknown_mark_review",
            "next_action": "review mark mapping before routing",
        },
    )
    text = str(entry.get("text") or "").strip()
    return {
        "feedback_id": entry.get("feedback_id"),
        "captured_at_utc": entry.get("captured_at_utc"),
        "mark": mark,
        "route": projection["route"],
        "next_action": projection["next_action"],
        "text": text,
        "text_preview": text[:80],
        "accepted_edges": 0,
        "firewall": {
            "research_queue_direction_only": True,
            "owner_review_attention_only": True,
            "evidence_gate_mutation_allowed": False,
            "ranking_mutation_allowed": False,
            "candidate_promotion_allowed": False,
            "trading_authority_allowed": False,
            "advisory_claim_allowed": False,
            "owner_pnl_claim_allowed": False,
        },
    }


def _feedback_route_projection(
    entries: list[dict[str, Any]],
    *,
    recent_limit: int,
) -> dict[str, Any]:
    route_items = [_project_feedback_route(entry) for entry in entries]
    route_counts = Counter(str(item.get("route") or "unknown") for item in route_items)
    recent = route_items[-recent_limit:] if recent_limit > 0 else []
    return {
        "contract": "daedalus_wechat.owner_feedback_research_route_projection",
        "status": (
            "OWNER_FEEDBACK_RESEARCH_ROUTE_PROJECTION_READY"
            if route_items
            else "OWNER_FEEDBACK_RESEARCH_ROUTE_PROJECTION_EMPTY"
        ),
        "route_item_count": len(route_items),
        "route_counts": dict(sorted(route_counts.items())),
        "recent_route_items": recent,
        "accepted_edges": 0,
        "authority_boundary": {
            "accepted_edges": 0,
            "report_only": True,
            "authority_delta": "none",
            "evidence_gate_mutation_allowed": False,
            "ranking_mutation_allowed": False,
            "candidate_promotion_allowed": False,
            "trading_authority_allowed": False,
            "advisory_claim_allowed": False,
            "owner_pnl_claim_allowed": False,
        },
        "claim_boundary": (
            "owner feedback routes research attention only; it must not mutate "
            "evidence gates, rankings, candidate promotion, trading authority, "
            "advisory claims, or owner-PnL claims"
        ),
    }


def export_owner_feedback_route_queue(
    *,
    ledger_path: Path | None = None,
    output_path: Path | None = None,
    recent_limit: int = 20,
) -> dict[str, Any]:
    """Write a derived report-only research-route queue from feedback entries."""

    path = ledger_path or default_owner_feedback_path()
    out_path = output_path or default_owner_feedback_route_queue_path()
    entries = _read_entries(path)
    projection = _feedback_route_projection(entries, recent_limit=recent_limit)
    payload = {
        **projection,
        "source_ledger_path": str(path),
        "output_path": str(out_path),
        "generated_at_utc": _utc_now_iso(),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def load_owner_feedback_summary(
    ledger_path: Path | None = None,
    *,
    recent_limit: int = 3,
) -> dict[str, Any]:
    path = ledger_path or default_owner_feedback_path()
    entries = _read_entries(path)
    mark_counts = Counter(str(entry.get("mark") or "unknown") for entry in entries)
    recent = entries[-recent_limit:] if recent_limit > 0 else []
    route_projection = _feedback_route_projection(entries, recent_limit=recent_limit)
    return {
        "contract": CONTRACT,
        "status": "OWNER_FEEDBACK_LEDGER_READY" if path.exists() else "OWNER_FEEDBACK_LEDGER_EMPTY",
        "ledger_path": str(path),
        "feedback_count": len(entries),
        "mark_counts": dict(sorted(mark_counts.items())),
        "recent_feedback": recent,
        "research_route_projection": route_projection,
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
    route_projection = (
        summary.get("research_route_projection")
        if isinstance(summary.get("research_route_projection"), dict)
        else {}
    )
    route_counts = (
        route_projection.get("route_counts")
        if isinstance(route_projection.get("route_counts"), dict)
        else {}
    )
    recent_routes = (
        route_projection.get("recent_route_items")
        if isinstance(route_projection.get("recent_route_items"), list)
        else []
    )
    recent_text = "none"
    if recent:
        last = recent[-1]
        if isinstance(last, dict):
            text = str(last.get("text") or "").strip()
            recent_text = f"{last.get('mark', 'unknown')}:{text[:40]}"
    recent_route_text = "none"
    if recent_routes:
        last_route = recent_routes[-1]
        if isinstance(last_route, dict):
            recent_route_text = (
                f"{last_route.get('mark', 'unknown')}->"
                f"{last_route.get('route', 'unknown')}:"
                f"{str(last_route.get('text_preview') or '')[:30]}"
            )
    return (
        "反馈回路: "
        f"已记录={summary.get('feedback_count', 0)} "
        f"useful={marks.get('useful', 0)} "
        f"noise={marks.get('noise', 0)} "
        f"watch={marks.get('watch', 0)} "
        f"write_card={marks.get('write_card', 0)} "
        f"surface_blocker={marks.get('surface_blocker', 0)} "
        f"needs_review={marks.get('needs_review', 0)} "
        f"待路由={route_projection.get('route_item_count', 0)} "
        f"写卡={route_counts.get('research_card_draft_backlog', 0)} "
        f"数据缺口={route_counts.get('surface_blocker_triage', 0)} "
        f"复核={route_counts.get('peer_review_backlog', 0)} "
        f"噪音复盘={route_counts.get('noise_review_backlog', 0)} "
        f"最近={recent_text} "
        f"最新路由={recent_route_text} "
        "防火墙=只导研究/注意力,不改证据门/排名/候选提升"
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
