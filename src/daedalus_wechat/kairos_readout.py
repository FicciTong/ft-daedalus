from __future__ import annotations

import json
import re
from collections import Counter
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .owner_feedback import format_owner_feedback_summary, load_owner_feedback_summary

ARCHIVE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def default_kairos_readout_path() -> Path:
    """Return the workbench-local Kairos owner readiness latest report path."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "product"
        / "owner_readiness_readout_latest.json"
    )


def default_kairos_owner_brief_path() -> Path:
    """Return the workbench-local Kairos short-cycle owner brief path."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "research_substrate"
        / "short_cycle_owner_review_brief_latest.json"
    )


def default_kairos_owner_daily_package_path() -> Path:
    """Return the workbench-local Kairos short-cycle owner daily package path."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "research_substrate"
        / "short_cycle_owner_daily_package_latest.json"
    )


def default_kairos_intraday_alert_path() -> Path:
    """Return the workbench-local Kairos short-cycle intraday alert path."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "research_substrate"
        / "short_cycle_intraday_owner_alert_latest.json"
    )


def default_kairos_intraday_candidate_manifest_path() -> Path:
    """Return the workbench-local Kairos short-cycle intraday manifest path."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "research_substrate"
        / "short_cycle_intraday_candidate_manifest_latest.json"
    )


def default_kairos_intraday_eod_review_queue_path() -> Path:
    """Return the workbench-local Kairos intraday EOD replay review path."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "research_substrate"
        / "short_cycle_intraday_eod_review_queue_latest.json"
    )


def default_kairos_intraday_eod_outcome_review_path() -> Path:
    """Return the workbench-local Kairos intraday EOD outcome review path."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "research_substrate"
        / "short_cycle_intraday_eod_outcome_review_latest.json"
    )


def default_kairos_owner_daily_archive_root() -> Path:
    """Return the workbench-local dated Kairos owner daily archive root."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "research_substrate"
        / "owner_daily_archive"
    )


def kairos_owner_daily_archive_paths(report_date: str) -> dict[str, Path]:
    """Return dated archive paths for one owner-visible report date."""
    clean_date = report_date.strip()
    if not ARCHIVE_DATE_RE.match(clean_date):
        raise ValueError("archive report date must use YYYY-MM-DD")
    root = default_kairos_owner_daily_archive_root() / clean_date
    return {
        "root": root,
        "owner_review_brief": root / "owner_review_brief.json",
        "owner_daily_package": root / "owner_daily_package.json",
        "intraday_owner_alert": root / "intraday_owner_alert.json",
        "intraday_eod_review_queue": root / "intraday_eod_review_queue.json",
        "intraday_eod_outcome_review": root / "intraday_eod_outcome_review.json",
    }


def _load_kairos_owner_daily_archive_index() -> dict[str, Any]:
    """Load the owner daily archive index if present."""
    root = default_kairos_owner_daily_archive_root()
    index_path = root / "index.json"
    if not index_path.is_file():
        return {}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (JSONDecodeError, OSError):
        return {}
    return _as_dict(payload)


def _fallback_kairos_owner_daily_archive_days(limit: int) -> list[dict[str, Any]]:
    root = default_kairos_owner_daily_archive_root()
    if not root.is_dir():
        return []
    days: list[dict[str, Any]] = []
    for item in root.iterdir():
        if not item.is_dir() or not ARCHIVE_DATE_RE.match(item.name):
            continue
        if (item / "owner_review_brief.json").is_file():
            days.append(
                {
                    "report_date": item.name,
                    "summary": {
                        "report_date": item.name,
                        "surface_count": 1,
                        "surfaces": ["owner_review_brief"],
                        "accepted_edges": 0,
                        "statuses": {
                            "owner_review_brief": (
                                "ARCHIVED_OWNER_REVIEW_BRIEF_PRESENT"
                            )
                        },
                    },
                }
            )
    return sorted(days, key=lambda row: str(row.get("report_date") or ""), reverse=True)[
        : max(0, limit)
    ]


def list_kairos_owner_daily_archive_days(limit: int = 20) -> list[dict[str, Any]]:
    """List dated owner daily archives with index summaries, newest first."""
    index = _load_kairos_owner_daily_archive_index()
    days: list[dict[str, Any]] = []
    for item in _as_list(index.get("days")):
        row = _as_dict(item)
        report_date = str(row.get("report_date") or "")
        if not ARCHIVE_DATE_RE.match(report_date):
            continue
        days.append(row)
    if not days:
        return _fallback_kairos_owner_daily_archive_days(limit)
    return sorted(days, key=lambda row: str(row.get("report_date") or ""), reverse=True)[
        : max(0, limit)
    ]


def list_kairos_owner_daily_archive_dates(limit: int = 20) -> list[str]:
    """List dated owner daily archive dates, newest first."""
    return [
        str(row.get("report_date"))
        for row in list_kairos_owner_daily_archive_days(limit=limit)
        if row.get("report_date")
    ]


def _format_archive_tier_counts(summary: dict[str, Any]) -> str:
    tiers = _as_dict(summary.get("evidence_tier_counts"))
    if not tiers:
        return "tier=暂无"
    return (
        "tier="
        f"验证{_fmt_num(tiers.get('VALIDATED_EDGE', 0))}/"
        f"支持{_fmt_num(tiers.get('SUPPORTED_OBSERVATION', 0))}/"
        f"观察{_fmt_num(tiers.get('OBSERVATION', 0))}"
    )


def _append_archive_count(
    pieces: list[str],
    *,
    label: str,
    value: Any,
) -> None:
    if value is not None:
        pieces.append(f"{label}={_fmt_num(value)}")


def _append_archive_count_map(
    pieces: list[str],
    *,
    label: str,
    value: Any,
) -> None:
    if _as_dict(value):
        pieces.append(f"{label}={_fmt_count_map(value)}")


def _format_archive_day_line(row: dict[str, Any]) -> str:
    summary = _as_dict(row.get("summary"))
    report_date = row.get("report_date")
    pieces = [
        f"- {report_date}",
        f"target={summary.get('target_trade_date') or 'None'}",
        f"as_of={summary.get('as_of_date') or 'None'}",
        f"rows={_fmt_num(summary.get('owner_review_candidate_count'))}",
        _format_archive_tier_counts(summary),
    ]
    if summary.get("intraday_status"):
        pieces.append(f"intraday={summary.get('intraday_status')}")
        if summary.get("intraday_triggered_unit_count") is not None:
            pieces.append(
                f"triggered={_fmt_num(summary.get('intraday_triggered_unit_count'))}"
            )
    _append_archive_count(
        pieces,
        label="触发事件",
        value=summary.get("intraday_trigger_event_count"),
    )
    _append_archive_count(
        pieces,
        label="当前触发",
        value=summary.get("intraday_current_triggered_event_count"),
    )
    _append_archive_count(
        pieces,
        label="失效保留",
        value=summary.get("intraday_no_longer_triggered_event_count"),
    )
    _append_archive_count(
        pieces,
        label="观察缺口",
        value=summary.get("intraday_current_observation_missing_event_count"),
    )
    if summary.get("intraday_universe_row_count") is not None:
        pieces.append(
            "universe="
            f"{_fmt_num(summary.get('intraday_universe_priced_row_count'))}/"
            f"{_fmt_num(summary.get('intraday_universe_row_count'))}"
        )
    if summary.get("intraday_universe_candidate_count") is not None:
        pieces.append(
            "候选观测="
            f"{_fmt_num(summary.get('intraday_universe_candidate_observed_count'))}/"
            f"{_fmt_num(summary.get('intraday_universe_candidate_count'))}"
        )
    if summary.get("intraday_eod_review_status"):
        pieces.append(f"eod_queue={summary.get('intraday_eod_review_status')}")
    _append_archive_count(
        pieces,
        label="eod_units",
        value=summary.get("eod_review_candidate_unit_count"),
    )
    _append_archive_count(
        pieces,
        label="曾触发",
        value=summary.get("eod_review_ever_triggered_candidate_count"),
    )
    _append_archive_count(
        pieces,
        label="当前候选",
        value=summary.get("eod_review_current_triggered_candidate_count"),
    )
    _append_archive_count(
        pieces,
        label="pending",
        value=summary.get("eod_review_pending_or_missing_candidate_count"),
    )
    if summary.get("intraday_eod_outcome_status"):
        pieces.append(f"eod_outcome={summary.get('intraday_eod_outcome_status')}")
    if summary.get("eod_outcome_candidate_unit_count") is not None:
        pieces.append(
            "outcome_matched="
            f"{_fmt_num(summary.get('eod_outcome_matched_panel_row_count'))}/"
            f"{_fmt_num(summary.get('eod_outcome_candidate_unit_count'))}"
        )
    if summary.get("feedback_status"):
        pieces.append(f"反馈={summary.get('feedback_status')}")
    _append_archive_count(
        pieces,
        label="反馈队列",
        value=summary.get("feedback_queue_item_count"),
    )
    _append_archive_count(
        pieces,
        label="已路由",
        value=summary.get("feedback_intaked_route_item_count"),
    )
    _append_archive_count_map(
        pieces,
        label="反馈动作",
        value=summary.get("feedback_research_action_counts"),
    )
    if summary.get("forward_shadow_lifecycle_state"):
        pieces.append(f"forward_shadow={summary.get('forward_shadow_lifecycle_state')}")
    _append_archive_count(
        pieces,
        label="shadow_pending",
        value=summary.get("forward_shadow_pending_trigger_count"),
    )
    _append_archive_count(
        pieces,
        label="shadow_fired",
        value=summary.get("forward_shadow_trigger_fired_count"),
    )
    if summary.get("minute_price_volume_candidate_count") is not None:
        pieces.append(
            "分钟量价="
            f"{_fmt_num(summary.get('minute_price_volume_ready_count'))}/"
            f"{_fmt_num(summary.get('minute_price_volume_candidate_count'))}"
        )
    _append_archive_count(
        pieces,
        label="分钟缺口",
        value=summary.get("minute_price_volume_missing_count"),
    )
    _append_archive_count_map(
        pieces,
        label="分钟量价标记",
        value=summary.get("price_volume_flag_counts"),
    )
    if summary.get("volume_anchor_universe_match_count") is not None:
        pieces.append(
            "量价锚="
            f"{_fmt_num(summary.get('volume_anchor_shape_pass_count'))}/"
            f"{_fmt_num(summary.get('volume_anchor_universe_match_count'))}"
        )
    _append_archive_count_map(
        pieces,
        label="锚模式",
        value=summary.get("volume_anchor_mode_counts"),
    )
    if summary.get("volume_anchor_outcome_event_count") is not None:
        pieces.append(
            "锚回放="
            f"{_fmt_num(summary.get('volume_anchor_outcome_industry_mapped_event_count'))}/"
            f"{_fmt_num(summary.get('volume_anchor_outcome_event_count'))}"
        )
    if summary.get("volume_anchor_outcome_status"):
        pieces.append(f"锚回放状态={summary.get('volume_anchor_outcome_status')}")
    if summary.get("latest_generated_at_utc"):
        pieces.append(f"latest={summary.get('latest_generated_at_utc')}")
    pieces.append(f"surfaces={_fmt_num(summary.get('surface_count'))}")
    pieces.append(f"accepted_edges={_fmt_num(summary.get('accepted_edges', 0))}")
    return " ".join(pieces)


def format_kairos_owner_daily_archive_dates(limit: int = 20) -> str:
    days = list_kairos_owner_daily_archive_days(limit=limit)
    if not days:
        return (
            "Kairos 日报历史: 暂无可回看日期\n"
            f"archive_root={default_kairos_owner_daily_archive_root()}\n"
            "边界: report-only / accepted_edges=0"
        )
    lines = [f"Kairos 日报历史: 可回看 {len(days)} 天"]
    lines.extend(_format_archive_day_line(_as_dict(row)) for row in days)
    lines.append("用法: /brief YYYY-MM-DD 或 daedalus-wechat brief --date YYYY-MM-DD")
    lines.append("边界: report-only / accepted_edges=0")
    return "\n".join(lines)


def load_kairos_owner_daily_archive(report_date: str) -> dict[str, Any]:
    """Load one dated owner daily archive bundle without falling back to latest."""
    try:
        paths = kairos_owner_daily_archive_paths(report_date)
    except ValueError as exc:
        missing = _missing_owner_brief_payload(
            default_kairos_owner_daily_archive_root() / report_date,
            status="BLOCKED",
            reason=str(exc),
        )
        return {
            "report_date": report_date,
            "archive_root": str(default_kairos_owner_daily_archive_root() / report_date),
            "owner_review_brief": missing,
            "owner_daily_package": _missing_owner_daily_package_payload(
                default_kairos_owner_daily_archive_root() / report_date,
                status="BLOCKED",
                reason=str(exc),
            ),
            "intraday_owner_alert": _missing_intraday_alert_payload(
                default_kairos_owner_daily_archive_root() / report_date,
                status="BLOCKED",
                reason=str(exc),
            ),
            "intraday_eod_review_queue": _missing_intraday_eod_review_queue_payload(
                default_kairos_owner_daily_archive_root() / report_date,
                status="BLOCKED",
                reason=str(exc),
            ),
            "intraday_eod_outcome_review": (
                _missing_intraday_eod_outcome_review_payload(
                    default_kairos_owner_daily_archive_root() / report_date,
                    status="BLOCKED",
                    reason=str(exc),
                )
            ),
            "accepted_edges": 0,
        }
    return {
        "report_date": report_date,
        "archive_root": str(paths["root"]),
        "owner_review_brief": load_kairos_owner_brief(paths["owner_review_brief"]),
        "owner_daily_package": load_kairos_owner_daily_package(
            paths["owner_daily_package"]
        ),
        "intraday_owner_alert": load_kairos_intraday_alert(
            paths["intraday_owner_alert"]
        ),
        "intraday_eod_review_queue": load_kairos_intraday_eod_review_queue(
            paths["intraday_eod_review_queue"]
        ),
        "intraday_eod_outcome_review": load_kairos_intraday_eod_outcome_review(
            paths["intraday_eod_outcome_review"]
        ),
        "accepted_edges": 0,
    }


def default_kairos_hypothesis_scout_readout_path() -> Path:
    """Return the workbench-local Kairos short-cycle hypothesis scout path."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "research_substrate"
        / "short_cycle_hypothesis_scout_readout_latest.json"
    )


def default_kairos_owner_review_truth_units_path() -> Path:
    """Return the workbench-local owner-review truth-unit readout path."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "research_substrate"
        / "short_cycle_owner_review_truth_units_from_cached_retry_latest.json"
    )


def default_kairos_owner_feedback_route_intake_path() -> Path:
    """Return the workbench-local Kairos owner-feedback research intake path."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "research_substrate"
        / "owner_feedback_research_route_intake_latest.json"
    )


def default_kairos_forward_shadow_track_record_path() -> Path:
    """Return the workbench-local Kairos forward-shadow track-record path."""
    cosmos_root = Path(__file__).resolve().parents[3]
    return (
        cosmos_root
        / "ft-kairos"
        / "var"
        / "reports"
        / "research_substrate"
        / "short_cycle_forward_shadow_track_record_latest.json"
    )


def _missing_payload(report_path: Path, *, status: str, reason: str) -> dict[str, Any]:
    return {
        "report_contract": "daedalus_wechat.kairos_today_readout",
        "readout_source": "fail_closed",
        "run_status": status,
        "report_path": str(report_path),
        "owner_summary": {
            "advisory_ready": False,
            "authority_state": "report_only",
            "blocked_sections": ["owner_readiness_report"],
            "warn_sections": [],
            "no_trade_reasons": [reason],
            "report_only_leads": [],
            "owner_action": "restore Kairos owner readiness report before use",
            "freshness_statement": "owner readiness report unavailable",
        },
        "authority": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "owner_pnl_claim_allowed": False,
            "consumer_cutover_allowed": False,
            "live_broker_allowed": False,
            "auto_order_allowed": False,
        },
    }


def load_kairos_today_readout(report_path: Path | None = None) -> dict[str, Any]:
    path = report_path or default_kairos_readout_path()
    if not path.is_file():
        return _missing_payload(
            path,
            status="MISSING",
            reason="Kairos owner readiness report is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return _missing_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos owner readiness report is invalid JSON: {exc.msg}",
        )
    except OSError as exc:
        return _missing_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos owner readiness report cannot be read: {exc}",
        )
    if not isinstance(payload, dict):
        return _missing_payload(
            path,
            status="BLOCKED",
            reason="Kairos owner readiness report root is not an object",
        )
    payload = dict(payload)
    payload["report_path"] = str(path)
    return payload


def _missing_owner_brief_payload(
    report_path: Path, *, status: str, reason: str
) -> dict[str, Any]:
    return {
        "contract": "daedalus_wechat.kairos_owner_brief_readout",
        "readout_source": "fail_closed",
        "status": status,
        "report_path": str(report_path),
        "as_of_date": None,
        "target_trade_date": None,
        "accepted_edges": 0,
        "authority_boundary": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "owner_pnl_claim_allowed": False,
            "consumer_cutover_allowed": False,
            "live_broker_allowed": False,
            "auto_order_allowed": False,
        },
        "errors": [reason],
    }


def _missing_intraday_alert_payload(
    report_path: Path, *, status: str, reason: str
) -> dict[str, Any]:
    return {
        "contract": "daedalus_wechat.kairos_intraday_alert_readout",
        "readout_source": "fail_closed",
        "status": status,
        "report_path": str(report_path),
        "as_of_date": None,
        "target_trade_date": None,
        "accepted_edges": 0,
        "realtime_snapshot_status": {
            "status": "MISSING",
            "message": reason,
        },
        "authority_boundary": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "owner_pnl_claim_allowed": False,
            "consumer_cutover_allowed": False,
            "live_broker_allowed": False,
            "auto_order_allowed": False,
        },
        "errors": [reason],
    }


def _missing_intraday_candidate_manifest_payload(
    report_path: Path, *, status: str, reason: str
) -> dict[str, Any]:
    return {
        "contract": "daedalus_wechat.kairos_intraday_candidate_manifest_readout",
        "readout_source": "fail_closed",
        "status": status,
        "report_path": str(report_path),
        "as_of_date": None,
        "target_trade_date": None,
        "accepted_edges": 0,
        "authority_boundary": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "owner_pnl_claim_allowed": False,
            "consumer_cutover_allowed": False,
            "live_broker_allowed": False,
            "auto_order_allowed": False,
        },
        "errors": [reason],
    }


def _missing_intraday_eod_review_queue_payload(
    report_path: Path, *, status: str, reason: str
) -> dict[str, Any]:
    return {
        "contract": "daedalus_wechat.kairos_intraday_eod_review_queue_readout",
        "readout_source": "fail_closed",
        "status": status,
        "report_path": str(report_path),
        "target_trade_date": None,
        "accepted_edges": 0,
        "candidate_review_unit_summary": {},
        "intraday_universe_observation_scope": {},
        "authority_boundary": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "owner_pnl_claim_allowed": False,
            "consumer_cutover_allowed": False,
            "live_broker_allowed": False,
            "auto_order_allowed": False,
        },
        "errors": [reason],
    }


def _missing_intraday_eod_outcome_review_payload(
    report_path: Path, *, status: str, reason: str
) -> dict[str, Any]:
    return {
        "contract": "daedalus_wechat.kairos_intraday_eod_outcome_review_readout",
        "readout_source": "fail_closed",
        "status": status,
        "report_path": str(report_path),
        "target_trade_date": None,
        "accepted_edges": 0,
        "summary": {},
        "group_horizon_stats": {},
        "blocker": {"reason": reason},
        "authority_boundary": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "owner_pnl_claim_allowed": False,
            "consumer_cutover_allowed": False,
            "live_broker_allowed": False,
            "auto_order_allowed": False,
        },
        "errors": [reason],
    }


def _missing_owner_daily_package_payload(
    report_path: Path, *, status: str, reason: str
) -> dict[str, Any]:
    return {
        "contract": "daedalus_wechat.kairos_owner_daily_package_readout",
        "readout_source": "fail_closed",
        "status": status,
        "report_path": str(report_path),
        "as_of_date": None,
        "target_trade_date": None,
        "accepted_edges": 0,
        "authority_boundary": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "owner_pnl_claim_allowed": False,
            "consumer_cutover_allowed": False,
            "live_broker_allowed": False,
            "auto_order_allowed": False,
        },
        "errors": [reason],
    }


def _missing_forward_shadow_track_record_payload(
    report_path: Path, *, status: str, reason: str
) -> dict[str, Any]:
    return {
        "contract": "daedalus_wechat.kairos_forward_shadow_track_record_readout",
        "readout_source": "fail_closed",
        "status": status,
        "report_path": str(report_path),
        "as_of_date": None,
        "target_trade_date": None,
        "accepted_edges": 0,
        "authority_boundary": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "owner_pnl_claim_allowed": False,
            "consumer_cutover_allowed": False,
            "live_broker_allowed": False,
            "auto_order_allowed": False,
        },
        "errors": [reason],
    }


def _missing_hypothesis_scout_readout_payload(
    report_path: Path, *, status: str, reason: str
) -> dict[str, Any]:
    return {
        "contract": "daedalus_wechat.kairos_hypothesis_scout_readout",
        "readout_source": "fail_closed",
        "status": status,
        "report_path": str(report_path),
        "accepted_edges": 0,
        "authority_boundary": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "owner_pnl_claim_allowed": False,
            "consumer_cutover_allowed": False,
            "live_broker_allowed": False,
            "auto_order_allowed": False,
        },
        "errors": [reason],
    }


def _missing_owner_review_truth_units_payload(
    report_path: Path, *, status: str, reason: str
) -> dict[str, Any]:
    return {
        "contract": "daedalus_wechat.kairos_owner_review_truth_units_readout",
        "readout_source": "fail_closed",
        "status": status,
        "report_path": str(report_path),
        "accepted_edges": 0,
        "authority_boundary": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "owner_pnl_claim_allowed": False,
            "consumer_cutover_allowed": False,
            "live_broker_allowed": False,
            "auto_order_allowed": False,
        },
        "errors": [reason],
    }


def _missing_owner_feedback_route_intake_payload(
    report_path: Path, *, status: str, reason: str
) -> dict[str, Any]:
    return {
        "contract": "daedalus_wechat.kairos_owner_feedback_route_intake_readout",
        "readout_source": "fail_closed",
        "status": status,
        "report_path": str(report_path),
        "accepted_edges": 0,
        "queue_item_count": 0,
        "research_action_counts": {},
        "source_route_counts": {},
        "next_actions": [
            {
                "action": "restore_kairos_feedback_route_intake",
                "reason": reason,
            }
        ],
        "authority_boundary": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "owner_pnl_claim_allowed": False,
            "consumer_cutover_allowed": False,
            "live_broker_allowed": False,
            "auto_order_allowed": False,
        },
        "errors": [reason],
    }


def load_kairos_owner_brief(report_path: Path | None = None) -> dict[str, Any]:
    path = report_path or default_kairos_owner_brief_path()
    if not path.is_file():
        return _missing_owner_brief_payload(
            path,
            status="MISSING",
            reason="Kairos short-cycle owner review brief is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return _missing_owner_brief_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos short-cycle owner review brief is invalid JSON: {exc.msg}",
        )
    except OSError as exc:
        return _missing_owner_brief_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos short-cycle owner review brief cannot be read: {exc}",
        )
    if not isinstance(payload, dict):
        return _missing_owner_brief_payload(
            path,
            status="BLOCKED",
            reason="Kairos short-cycle owner review brief root is not an object",
        )
    payload = dict(payload)
    payload["report_path"] = str(path)
    return payload


def load_kairos_owner_daily_package(report_path: Path | None = None) -> dict[str, Any]:
    path = report_path or default_kairos_owner_daily_package_path()
    if not path.is_file():
        return _missing_owner_daily_package_payload(
            path,
            status="MISSING",
            reason="Kairos short-cycle owner daily package is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return _missing_owner_daily_package_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos short-cycle owner daily package is invalid JSON: {exc.msg}",
        )
    except OSError as exc:
        return _missing_owner_daily_package_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos short-cycle owner daily package cannot be read: {exc}",
        )
    if not isinstance(payload, dict):
        return _missing_owner_daily_package_payload(
            path,
            status="BLOCKED",
            reason="Kairos short-cycle owner daily package root is not an object",
        )
    payload = dict(payload)
    payload["report_path"] = str(path)
    return payload


def load_kairos_hypothesis_scout_readout(
    report_path: Path | None = None,
) -> dict[str, Any]:
    path = report_path or default_kairos_hypothesis_scout_readout_path()
    if not path.is_file():
        return _missing_hypothesis_scout_readout_payload(
            path,
            status="MISSING",
            reason="Kairos short-cycle hypothesis scout readout is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return _missing_hypothesis_scout_readout_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos hypothesis scout readout is invalid JSON: {exc.msg}",
        )
    except OSError as exc:
        return _missing_hypothesis_scout_readout_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos hypothesis scout readout cannot be read: {exc}",
        )
    if not isinstance(payload, dict):
        return _missing_hypothesis_scout_readout_payload(
            path,
            status="BLOCKED",
            reason="Kairos hypothesis scout readout root is not an object",
        )
    payload = dict(payload)
    payload["report_path"] = str(path)
    return payload


def load_kairos_owner_review_truth_units(
    report_path: Path | None = None,
) -> dict[str, Any]:
    path = report_path or default_kairos_owner_review_truth_units_path()
    if not path.is_file():
        return _missing_owner_review_truth_units_payload(
            path,
            status="MISSING",
            reason="Kairos owner-review truth-unit readout is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return _missing_owner_review_truth_units_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos owner-review truth-unit readout is invalid JSON: {exc.msg}",
        )
    except OSError as exc:
        return _missing_owner_review_truth_units_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos owner-review truth-unit readout cannot be read: {exc}",
        )
    if not isinstance(payload, dict):
        return _missing_owner_review_truth_units_payload(
            path,
            status="BLOCKED",
            reason="Kairos owner-review truth-unit readout root is not an object",
        )
    payload = dict(payload)
    payload["report_path"] = str(path)
    return payload


def load_kairos_owner_feedback_route_intake(
    report_path: Path | None = None,
) -> dict[str, Any]:
    path = report_path or default_kairos_owner_feedback_route_intake_path()
    if not path.is_file():
        return _missing_owner_feedback_route_intake_payload(
            path,
            status="MISSING",
            reason="Kairos owner-feedback research route intake is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return _missing_owner_feedback_route_intake_payload(
            path,
            status="BLOCKED",
            reason=(
                "Kairos owner-feedback research route intake is invalid JSON: "
                f"{exc.msg}"
            ),
        )
    except OSError as exc:
        return _missing_owner_feedback_route_intake_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos owner-feedback research route intake cannot be read: {exc}",
        )
    if not isinstance(payload, dict):
        return _missing_owner_feedback_route_intake_payload(
            path,
            status="BLOCKED",
            reason="Kairos owner-feedback research route intake root is not an object",
        )
    payload = dict(payload)
    payload["report_path"] = str(path)
    return payload


def load_kairos_forward_shadow_track_record(
    report_path: Path | None = None,
) -> dict[str, Any]:
    path = report_path or default_kairos_forward_shadow_track_record_path()
    if not path.is_file():
        return _missing_forward_shadow_track_record_payload(
            path,
            status="MISSING",
            reason="Kairos short-cycle forward-shadow track record is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return _missing_forward_shadow_track_record_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos forward-shadow track record is invalid JSON: {exc.msg}",
        )
    except OSError as exc:
        return _missing_forward_shadow_track_record_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos forward-shadow track record cannot be read: {exc}",
        )
    if not isinstance(payload, dict):
        return _missing_forward_shadow_track_record_payload(
            path,
            status="BLOCKED",
            reason="Kairos forward-shadow track record root is not an object",
        )
    payload = dict(payload)
    payload["report_path"] = str(path)
    return payload


def load_kairos_intraday_alert(report_path: Path | None = None) -> dict[str, Any]:
    path = report_path or default_kairos_intraday_alert_path()
    if not path.is_file():
        return _missing_intraday_alert_payload(
            path,
            status="MISSING",
            reason="Kairos short-cycle intraday owner alert is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return _missing_intraday_alert_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos short-cycle intraday owner alert is invalid JSON: {exc.msg}",
        )
    except OSError as exc:
        return _missing_intraday_alert_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos short-cycle intraday owner alert cannot be read: {exc}",
        )
    if not isinstance(payload, dict):
        return _missing_intraday_alert_payload(
            path,
            status="BLOCKED",
            reason="Kairos short-cycle intraday owner alert root is not an object",
        )
    payload = dict(payload)
    payload["report_path"] = str(path)
    return payload


def load_kairos_intraday_candidate_manifest(
    report_path: Path | None = None,
) -> dict[str, Any]:
    path = report_path or default_kairos_intraday_candidate_manifest_path()
    if not path.is_file():
        return _missing_intraday_candidate_manifest_payload(
            path,
            status="MISSING",
            reason="Kairos short-cycle intraday candidate manifest is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return _missing_intraday_candidate_manifest_payload(
            path,
            status="BLOCKED",
            reason=(
                "Kairos short-cycle intraday candidate manifest is invalid JSON: "
                f"{exc.msg}"
            ),
        )
    except OSError as exc:
        return _missing_intraday_candidate_manifest_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos short-cycle intraday candidate manifest cannot be read: {exc}",
        )
    if not isinstance(payload, dict):
        return _missing_intraday_candidate_manifest_payload(
            path,
            status="BLOCKED",
            reason="Kairos short-cycle intraday candidate manifest root is not an object",
        )
    payload = dict(payload)
    payload["report_path"] = str(path)
    return payload


def load_kairos_intraday_eod_review_queue(
    report_path: Path | None = None,
) -> dict[str, Any]:
    path = report_path or default_kairos_intraday_eod_review_queue_path()
    if not path.is_file():
        return _missing_intraday_eod_review_queue_payload(
            path,
            status="MISSING",
            reason="Kairos intraday EOD review queue is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return _missing_intraday_eod_review_queue_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos intraday EOD review queue is invalid JSON: {exc.msg}",
        )
    except OSError as exc:
        return _missing_intraday_eod_review_queue_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos intraday EOD review queue cannot be read: {exc}",
        )
    if not isinstance(payload, dict):
        return _missing_intraday_eod_review_queue_payload(
            path,
            status="BLOCKED",
            reason="Kairos intraday EOD review queue root is not an object",
        )
    payload = dict(payload)
    payload["report_path"] = str(path)
    return payload


def load_kairos_intraday_eod_outcome_review(
    report_path: Path | None = None,
) -> dict[str, Any]:
    path = report_path or default_kairos_intraday_eod_outcome_review_path()
    if not path.is_file():
        return _missing_intraday_eod_outcome_review_payload(
            path,
            status="MISSING",
            reason="Kairos intraday EOD outcome review is missing",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return _missing_intraday_eod_outcome_review_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos intraday EOD outcome review is invalid JSON: {exc.msg}",
        )
    except OSError as exc:
        return _missing_intraday_eod_outcome_review_payload(
            path,
            status="BLOCKED",
            reason=f"Kairos intraday EOD outcome review cannot be read: {exc}",
        )
    if not isinstance(payload, dict):
        return _missing_intraday_eod_outcome_review_payload(
            path,
            status="BLOCKED",
            reason="Kairos intraday EOD outcome review root is not an object",
        )
    payload = dict(payload)
    payload["report_path"] = str(path)
    return payload


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "None"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_num(value: Any) -> str:
    if value is None:
        return "None"
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return str(value)
    if as_float.is_integer():
        return str(int(as_float))
    return f"{as_float:.4g}"


def _fmt_ratio_pct(value: Any) -> str:
    if value is None:
        return "None"
    try:
        return f"{float(value) * 100.0:.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_ci(lower: Any, upper: Any) -> str:
    if lower is None and upper is None:
        return "[None,None]"
    return f"[{_fmt_pct(lower)},{_fmt_pct(upper)}]"


def _fmt_right_tail_cluster_membership(row: dict[str, Any]) -> str:
    membership = _as_dict(row.get("cross_horizon_right_tail_membership"))
    if (
        membership.get("status")
        != "REPORT_ONLY_CROSS_HORIZON_RIGHT_TAIL_CLUSTER_MEMBER"
    ):
        return ""
    cluster_key = membership.get("cluster_key") or "matched_cluster"
    return f"右尾簇={cluster_key}"


WOUND_LABEL_ZH = {
    "score_is_watchlist_ranking_heuristic_not_edge_score": "排序分只是观察优先级",
    "row_level_fdr_holdout_not_available": "单票未过FDR/holdout",
    "not_industry_neutral_contains_sector_beta": "未行业中性/含板块beta",
    "static_cost_stamp_not_fill_simulator": "静态成本/非真实成交模拟",
    "block_condition_daywalk_source_not_cached_retry": "板块条件daywalk/非主缓存路径",
    "hypothesis_daywalk_source_not_cached_retry": "通用daywalk/非主缓存路径",
    "net_static_cost_not_available_for_source": "未接净成本",
    "date_block_ci_not_available_for_source": "未接日期分块CI",
    "right_tail_not_available_for_source": "未接右尾统计",
    "date_block_ci_crosses_zero": "日期CI穿零",
    "low_date_support": "日期支撑不足",
    "cluster_is_correlated_setup_not_independent_edge": "同簇相关/非独立机会",
    "stock_personality_selection_policy_not_integrated": "未接股性/质地筛选",
    "context_fit_stock_texture_not_evaluated": "板块符合但个股质地未评估",
    "ma_posture_strength_filter_not_integrated": "未接均线强势姿态筛选",
}

MARKET_REGIME_LABEL_ZH = {
    "CHOPPY": "震荡",
    "HOT": "偏热",
    "COLD": "偏冷",
    "TREND": "趋势",
    "RISK_OFF": "退潮",
}

EMOTION_PHASE_LABEL_ZH = {
    "hot": "热",
    "cold": "冷",
    "choppy": "震荡",
    "repair": "修复",
    "risk_off": "退潮",
}

CONCENTRATION_LABEL_ZH = {
    "HIGH_INDUSTRY_CONCENTRATION": "行业高度集中",
    "MODERATE_INDUSTRY_CONCENTRATION": "行业中度集中",
    "LOW_INDUSTRY_CONCENTRATION": "行业分散",
}

INTRADAY_STATUS_LABEL_ZH = {
    "REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT": "观察包就绪",
    "TRIGGER_FIELDS_PENDING": "触发字段待补",
    "TRIGGER_FIELDS_READY": "触发字段就绪",
    "REALTIME_SNAPSHOT_READY": "实时快照就绪",
    "PENDING_REALTIME_SNAPSHOT": "实时快照待补",
    "MISSING": "缺失",
    "BLOCKED": "阻塞",
}

TACTIC_LABEL_ZH = {
    "high_gap_first30m_hold": "高开后前30分钟承接",
    "first30m_shakeout_recover": "前30分钟下探修复",
    "prior_strength_orderly_pullback": "前强有序回踩",
    "prior_weak_close_reclaim_volume": "前弱收盘放量修复",
    "leader_orderly_flat_pullback": "龙头有序横盘回踩",
    "prior_limit_gap_down_reclaim": "限涨后低开修复",
}

WINDOW_LABEL_ZH = {
    "opening_print_0926": "开盘",
    "first5m_preliminary_0936": "前5分钟",
    "first30m_confirmation_1001": "前30分钟确认",
}

EVIDENCE_TIER_LABEL_ZH = {
    "VALIDATED_EDGE": "已验证边际",
    "SUPPORTED_OBSERVATION": "支持观察",
    "OBSERVATION": "普通观察",
}


def _wound_label(wound: Any) -> str:
    name = str(wound)
    return WOUND_LABEL_ZH.get(name, name)


def _evidence_tier_label(tier: Any) -> str:
    key = str(tier or "OBSERVATION")
    return EVIDENCE_TIER_LABEL_ZH.get(key, key)


def _zh_label(value: Any, labels: dict[str, str]) -> str:
    key = str(value or "unknown")
    return labels.get(key, key)


def _fmt_window_labels(window_ids: list[Any]) -> str:
    labels = [WINDOW_LABEL_ZH.get(str(item), str(item)) for item in window_ids if item]
    return ",".join(labels) if labels else "none"


def _fmt_wound_counter(counter: Counter[str], *, limit: int = 4) -> str:
    parts = [
        f"{_wound_label(name)}={_fmt_num(count)}"
        for name, count in counter.most_common(limit)
    ]
    return " ".join(parts) if parts else "none"


def _fmt_wound_list(wounds: list[Any], *, limit: int = 3) -> str:
    labels = [_wound_label(item) for item in wounds[:limit] if item]
    return ",".join(labels) if labels else "none"


def _format_intraday_snapshot_blocker(
    *,
    snapshot: dict[str, Any],
    alert: dict[str, Any],
) -> str | None:
    status = str(snapshot.get("status") or "")
    if not status.startswith("BLOCKED"):
        return None
    parts = [f"reason={status}"]
    message = snapshot.get("message")
    if message:
        parts.append(f"message={message}")
    generated_at = snapshot.get("generated_at_utc") or alert.get("generated_at_utc")
    if generated_at:
        parts.append(f"generated={generated_at}")
    max_observation = snapshot.get("max_observation_time_utc")
    if max_observation:
        parts.append(f"max_observation={max_observation}")
    snapshot_time = snapshot.get("snapshot_time")
    if snapshot_time:
        parts.append(f"snapshot_time={snapshot_time}")
    errors = alert.get("errors")
    if isinstance(errors, list) and errors:
        parts.append(f"errors={','.join(str(item) for item in errors[:4])}")
    return "- intraday_alert_blocker " + " ".join(parts)


def _triggered_intraday_rows(
    alert: dict[str, Any], *, limit: int = 8
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    rows: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for row in _as_list(alert.get("candidate_alerts")):
        if not isinstance(row, dict):
            continue
        hits = [
            checkpoint
            for checkpoint in _as_list(row.get("runtime_checkpoints"))
            if isinstance(checkpoint, dict) and checkpoint.get("triggered") is True
        ]
        if hits:
            rows.append((row, hits))
    rows.sort(
        key=lambda item: (
            int(item[0].get("rank") or 999999),
            str(item[0].get("symbol") or ""),
        )
    )
    return rows[:limit]


def _format_intraday_triggered_rows(
    alert: dict[str, Any], *, limit: int = 8
) -> list[str]:
    triggered_rows = _triggered_intraday_rows(alert, limit=limit)
    if not triggered_rows:
        return []

    lines = [
        f"- intraday_triggered_rows={len(triggered_rows)} top_limit={limit}",
        "- intraday_triggered_boundary=observed trigger rows only; not edge, not GO, not advice",
    ]
    for row, hits in triggered_rows:
        by_window = {str(hit.get("window_id")): hit for hit in hits}
        windows = ",".join(str(hit.get("window_id")) for hit in hits)
        first30m = by_window.get("first30m_confirmation_1001", {})
        first5m = by_window.get("first5m_preliminary_0936", {})
        opening = by_window.get("opening_print_0926", {})
        lines.append(
            f"- trigger #{_fmt_num(row.get('rank'))} "
            f"{row.get('symbol', 'unknown')} {row.get('stock_name', '')} "
            f"[{row.get('industry_name', 'unknown')}] "
            f"{row.get('tactic_id', 'unknown')} "
            f"windows={windows} "
            f"gap={_fmt_ratio_pct(opening.get('gap_pct'))} "
            f"first5m={_fmt_ratio_pct(first5m.get('first5m_return_pct'))} "
            f"first30m={_fmt_ratio_pct(first30m.get('first30m_return_pct'))} "
            f"drawdown30m={_fmt_ratio_pct(first30m.get('drawdown_30m_from_open'))} "
            f"label={row.get('owner_confidence_label', 'unknown')} "
            f"wounds={len(_as_list(row.get('evidence_wounds')))}"
        )
    return lines


def _format_compact_intraday_status(
    alert: dict[str, Any] | None,
    *,
    limit: int = 3,
    tactic_names_zh: dict[str, str] | None = None,
) -> list[str]:
    alert = _as_dict(alert)
    if not alert:
        return ["盘中: 暂无 intraday alert artifact"]

    projection = _as_dict(alert.get("observation_projection_status"))
    readiness = _as_dict(alert.get("trigger_field_readiness_status"))
    snapshot = _as_dict(alert.get("realtime_snapshot_status"))
    triggered = _triggered_intraday_rows(alert, limit=limit)

    lines = [
        (
            "盘中: "
            f"{_zh_label(alert.get('status'), INTRADAY_STATUS_LABEL_ZH)} "
            f"已观察={_fmt_num(projection.get('observed_candidate_count'))} "
            f"待观察={_fmt_num(projection.get('pending_candidate_count'))} "
            f"触发字段={_zh_label(readiness.get('status'), INTRADAY_STATUS_LABEL_ZH)} "
            f"快照={_zh_label(snapshot.get('status'), INTRADAY_STATUS_LABEL_ZH)}"
        )
    ]
    if triggered:
        lines.append(f"盘中触发 Top {len(triggered)}:")
        for row, hits in triggered:
            windows = _fmt_window_labels([hit.get("window_id") for hit in hits])
            first30m = {
                str(hit.get("window_id")): hit for hit in hits
            }.get("first30m_confirmation_1001", {})
            tactic_id = str(row.get("tactic_id") or "unknown")
            tactic_name = (
                _as_dict(tactic_names_zh).get(tactic_id)
                or row.get("tactic_name")
                or TACTIC_LABEL_ZH.get(tactic_id)
                or tactic_id
            )
            lines.append(
                f"- #{_fmt_num(row.get('rank'))} "
                f"{row.get('symbol', 'unknown')} {row.get('stock_name', '')} "
                f"[{row.get('industry_name', 'unknown')}] "
                f"{tactic_name} "
                f"窗口={windows} "
                f"first30m={_fmt_ratio_pct(first30m.get('first30m_return_pct'))} "
                f"伤口={_fmt_wound_list(_as_list(row.get('evidence_wounds')), limit=2)}"
            )
    return lines


def _format_compact_intraday_eod_review(
    review: dict[str, Any] | None,
) -> list[str]:
    review = _as_dict(review)
    if not review:
        return ["盘中复盘: 暂无 EOD replay review queue"]

    status = str(review.get("status") or "UNKNOWN")
    accepted_edges = review.get("accepted_edges", 0)
    target = review.get("target_trade_date") or "unknown"
    errors = _as_list(review.get("errors"))
    if errors:
        return [
            (
                "盘中复盘: "
                f"{status} target={target} accepted_edges={accepted_edges} "
                f"error={errors[0]}"
            ),
            "盘中复盘边界: report-only / 不回填历史latest / 非买卖建议",
        ]

    summary = _as_dict(review.get("candidate_review_unit_summary"))
    by_state = _as_dict(summary.get("by_state"))
    scope = _as_dict(review.get("intraday_universe_observation_scope"))
    universe = _as_dict(scope.get("universe_summary"))
    missing_surfaces = _as_list(scope.get("missing_intraday_universe_surfaces"))

    candidate_count = (
        review.get("candidate_review_unit_count")
        or summary.get("candidate_review_unit_count")
    )
    current_triggered = (
        summary.get("current_triggered_candidate_count")
        or review.get("current_triggered_event_count")
    )
    lines = [
        (
            "盘中EOD复盘: "
            f"{status} target={target} "
            f"候选={_fmt_num(candidate_count)} "
            f"当前触发={_fmt_num(current_triggered)} "
            f"曾触发={_fmt_num(summary.get('ever_triggered_candidate_count'))} "
            f"未触发={_fmt_num(summary.get('never_triggered_candidate_count'))} "
            f"缺字段={_fmt_num(summary.get('pending_or_missing_candidate_count'))} "
            f"events={_fmt_num(review.get('event_count'))}"
        )
    ]
    if by_state:
        lines.append(f"盘中EOD状态: {_fmt_count_map(by_state)}")
    if universe:
        lines.append(
            "全A盘中观察: "
            f"rows={_fmt_num(universe.get('row_count'))} "
            f"上涨={_fmt_num(universe.get('advancer_count'))} "
            f"下跌={_fmt_num(universe.get('decliner_count'))} "
            f"+2={_fmt_num(universe.get('up_2pct_count'))} "
            f"-2={_fmt_num(universe.get('down_2pct_count'))} "
            f"候选覆盖={_fmt_num(universe.get('candidate_observed_in_universe_count'))}/"
            f"{_fmt_num(universe.get('candidate_symbol_count'))}"
        )
    if missing_surfaces:
        lines.append(
            "全A盘中缺口: "
            + ",".join(str(item) for item in missing_surfaces[:4])
        )
    replay_path = review.get("replay_archive_path")
    if replay_path:
        lines.append(f"盘中EOD replay={replay_path}")
    lines.append("盘中复盘边界: report-only / retained列表不删除旧触发 / accepted_edges=0")
    return lines


def _preferred_outcome_horizon(horizons: list[Any]) -> dict[str, Any]:
    by_id = {
        str(row.get("horizon_id")): row
        for row in horizons
        if isinstance(row, dict)
    }
    for horizon_id in (
        "next_open_to_following_close",
        "next_open_to_d3_close",
        "next_open_to_d5_close",
        "next_open_to_next_close",
    ):
        row = by_id.get(horizon_id)
        if row:
            return row
    return {}


def _format_outcome_group_line(stats: dict[str, Any], group_id: str, label: str) -> str:
    group = _as_dict(stats.get(group_id))
    horizon = _preferred_outcome_horizon(_as_list(group.get("horizons")))
    if not horizon:
        return f"{label}=n{_fmt_num(group.get('matched_panel_row_count'))} no_horizon"
    return (
        f"{label}=n{_fmt_num(group.get('matched_panel_row_count'))} "
        f"{horizon.get('horizon_id', 'unknown')} "
        f"net={_fmt_pct(horizon.get('mean_net_static_cost_return_pct'))} "
        f"胜率={_fmt_pct(horizon.get('positive_share_pct'))}"
    )


def _format_intraday_outcome_waterline(blocker: dict[str, Any]) -> str | None:
    waterline = _as_dict(blocker.get("forward_panel_waterline"))
    if not waterline:
        return None
    entry_min = waterline.get("forward_outcome_panel_entry_date_min") or "unknown"
    entry_max = waterline.get("forward_outcome_panel_entry_date_max") or "unknown"
    signal_min = waterline.get("forward_outcome_panel_signal_date_min") or "unknown"
    signal_max = waterline.get("forward_outcome_panel_signal_date_max") or "unknown"
    target = waterline.get("target_trade_date") or blocker.get("target_trade_date") or "unknown"
    target_rows = waterline.get("target_entry_date_row_count")
    generated_at = waterline.get("forward_outcome_panel_generated_at_utc") or "unknown"
    return (
        "盘中结果水线: "
        f"panel_entry={entry_min}..{entry_max} "
        f"panel_signal={signal_min}..{signal_max} "
        f"target={target} target_rows={_fmt_num(target_rows)} "
        f"generated={generated_at} pending不是负证据"
    )


def _format_compact_intraday_eod_outcome_review(
    review: dict[str, Any] | None,
) -> list[str]:
    review = _as_dict(review)
    if not review:
        return ["盘中结果: 暂无 EOD outcome review"]

    status = str(review.get("status") or "UNKNOWN")
    accepted_edges = review.get("accepted_edges", 0)
    target = review.get("target_trade_date") or "unknown"
    errors = _as_list(review.get("errors"))
    if errors:
        return [
            (
                "盘中结果: "
                f"{status} target={target} accepted_edges={accepted_edges} "
                f"error={errors[0]}"
            ),
            "盘中结果边界: report-only / pending不是负证据 / 非买卖建议",
        ]

    summary = _as_dict(review.get("summary"))
    lines = [
        (
            "盘中结果: "
            f"{status} target={target} "
            f"matched={_fmt_num(summary.get('matched_panel_row_count'))}/"
            f"{_fmt_num(summary.get('candidate_review_unit_count'))} "
            f"触发={_fmt_num(summary.get('current_triggered_unit_count'))} "
            f"未触发={_fmt_num(summary.get('never_triggered_unit_count'))} "
            f"可比较={summary.get('can_compare_triggered_vs_denominator')}"
        )
    ]
    blocker = _as_dict(review.get("blocker"))
    if blocker:
        lines.append(
            "盘中结果阻塞: "
            f"{blocker.get('blocker_id', blocker.get('reason', 'unknown'))} "
            f"next={blocker.get('next_action', 'unknown')}"
        )
        waterline = _format_intraday_outcome_waterline(blocker)
        if waterline:
            lines.append(waterline)
    stats = _as_dict(review.get("group_horizon_stats"))
    if summary.get("matched_panel_row_count"):
        lines.append(
            "盘中结果分组: "
            + " | ".join(
                [
                    _format_outcome_group_line(stats, "current_triggered", "触发组"),
                    _format_outcome_group_line(stats, "never_triggered", "未触发组"),
                    _format_outcome_group_line(stats, "all_candidates", "全候选"),
                ]
            )
        )
    lines.append("盘中结果边界: report-only / pending不是负证据 / accepted_edges=0")
    return lines


def _fmt_counter(counter: Counter[str], *, limit: int = 4) -> str:
    parts = [
        f"{name}={_fmt_num(count)}"
        for name, count in counter.most_common(limit)
    ]
    return " ".join(parts) if parts else "none"


def _float_or(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _truth_unit_review_sort_key(row: dict[str, Any]) -> tuple[int, float, float, float]:
    route = row.get("owner_review_route")
    route_priority = {
        "strict_candidate_review_only": 4,
        "owner_review_tail_watch": 3,
        "right_tail_but_mean_negative_review_only": 2,
        "observation_only_net_cost_missing": 1,
    }.get(str(route), 0)
    return (
        route_priority,
        _float_or(row.get("owner_review_score_not_evidence")),
        _float_or(row.get("latest_executable_excess_pct_gross")),
        _float_or(row.get("latest_executable_row_n")),
    )


def _fmt_count_map(value: Any) -> str:
    counts = _as_dict(value)
    if not counts:
        return "none"
    return " ".join(
        f"{key}={_fmt_num(counts[key])}"
        for key in sorted(counts, key=lambda item: str(item))
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _format_daily_package_handoff(
    package: dict[str, Any] | None,
    *,
    owner_brief_payload: dict[str, Any] | None = None,
    intraday_manifest_payload: dict[str, Any] | None = None,
    intraday_alert: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(package, dict):
        return []

    status = str(package.get("status") or "UNKNOWN")
    accepted_edges = package.get("accepted_edges", 0)
    report_path = package.get("report_path", "unknown")
    errors = package.get("errors")
    if isinstance(errors, list) and errors:
        return [
            "",
            "日包总入口:",
            f"- package={status} accepted_edges={accepted_edges}",
            *[f"- error={item}" for item in errors[:2]],
            f"- artifact={report_path}",
        ]

    owner_brief = _as_dict(package.get("owner_review_brief"))
    owner_brief_source = "package"
    if not owner_brief:
        brief_payload = _as_dict(owner_brief_payload)
        brief_candidates = _as_list(brief_payload.get("owner_review_candidates"))
        if brief_payload.get("status"):
            owner_brief = {
                "source_status": brief_payload.get("status"),
                "owner_review_candidate_count": len(brief_candidates),
            }
            owner_brief_source = "latest_owner_brief_fallback"
    intraday_manifest = _as_dict(package.get("intraday_candidate_manifest"))
    intraday_manifest_source = "package"
    if not intraday_manifest:
        manifest_payload = _as_dict(intraday_manifest_payload)
        manifest_status = manifest_payload.get("status")
        if manifest_status:
            manifest_windows = _as_list(manifest_payload.get("collection_windows"))
            intraday_manifest = {
                "source_status": manifest_status,
                "candidate_count": manifest_payload.get("candidate_count"),
                "unique_symbol_count": manifest_payload.get("unique_symbol_count"),
                "collection_window_count": len(manifest_windows),
                "collection_windows": manifest_windows,
                "edge_collection_contract": manifest_payload.get(
                    "edge_collection_contract"
                ),
                "source_markdown_path": manifest_payload.get("markdown_path"),
            }
            intraday_manifest_source = "latest_intraday_manifest_fallback"
    windows = _as_list(intraday_manifest.get("collection_windows"))
    edge_contract = _as_dict(intraday_manifest.get("edge_collection_contract"))

    lines = [
        "",
        "日包总入口:",
        (
            f"- package={status} as_of={package.get('as_of_date', 'unknown')} "
            f"target={package.get('target_trade_date', 'unknown')} "
            f"accepted_edges={accepted_edges}"
        ),
        (
            f"- owner_brief={owner_brief.get('source_status', 'unknown')} "
            f"rows={_fmt_num(owner_brief.get('owner_review_candidate_count'))} "
            f"source={owner_brief_source}"
        ),
        (
            f"- intraday_manifest={intraday_manifest.get('source_status', 'unknown')} "
            f"rows={_fmt_num(intraday_manifest.get('candidate_count'))} "
            f"symbols={_fmt_num(intraday_manifest.get('unique_symbol_count'))} "
            f"windows={_fmt_num(intraday_manifest.get('collection_window_count'))} "
            f"edge_runtime={edge_contract.get('edge_runtime', 'unknown')} "
            f"source={intraday_manifest_source}"
        ),
    ]
    for row in windows[:3]:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('time_cst')} {row.get('window_id')}: "
            f"{row.get('owner_use')}"
        )
    source_md = intraday_manifest.get("source_markdown_path")
    if source_md:
        lines.append(f"- intraday_md={source_md}")
    alert = _as_dict(intraday_alert)
    if alert:
        projection = _as_dict(alert.get("observation_projection_status"))
        readiness = _as_dict(alert.get("trigger_field_readiness_status"))
        source_counts = _as_dict(projection.get("candidate_source_counts"))
        snapshot = _as_dict(alert.get("realtime_snapshot_status"))
        lines.append(
            f"- intraday_alert={alert.get('status', 'unknown')} "
            f"rows={_fmt_num(alert.get('candidate_count'))} "
            f"observed={_fmt_num(projection.get('observed_candidate_count'))} "
            f"pending={_fmt_num(projection.get('pending_candidate_count'))} "
            f"topn={_fmt_num(source_counts.get('topn_owner_review'))} "
            f"right_tail_supp={_fmt_num(source_counts.get('cross_horizon_right_tail_supplement'))} "
            f"clusters={_fmt_num(projection.get('cross_horizon_right_tail_cluster_count'))} "
            f"snapshot={snapshot.get('status', 'unknown')}"
        )
        if readiness:
            lines.append(
                f"- intraday_trigger_readiness={readiness.get('status', 'unknown')} "
                f"resolved={_fmt_num(readiness.get('resolved_count'))} "
                f"pending={_fmt_num(readiness.get('pending_count'))} "
                f"pending_windows={readiness.get('pending_window_ids')}"
            )
        lines.extend(_format_intraday_triggered_rows(alert))
        blocker = _format_intraday_snapshot_blocker(
            snapshot=snapshot,
            alert=alert,
        )
        if blocker:
            lines.append(blocker)
        alert_md = alert.get("markdown_path")
        if alert_md:
            lines.append(f"- intraday_alert_md={alert_md}")
    lines.append(f"- package_artifact={report_path}")
    return lines


def _format_explosive_posture(payload: dict[str, Any]) -> list[str]:
    posture = _as_dict(payload.get("explosive_short_cycle_posture"))
    if not posture:
        return []
    setup = _as_dict(posture.get("setup_supply"))
    tape = _as_dict(posture.get("right_tail_tape"))
    concentration = _as_dict(posture.get("concentration"))
    return [
        "",
        "短线暴利/右尾温度计:",
        (
            f"- state={posture.get('posture_state', 'unknown')} "
            f"setup={_fmt_num(setup.get('owner_candidate_count'))} "
            f"watchlist={_fmt_num(setup.get('stock_watchlist_count'))} "
            f"强封无炸={_fmt_num(setup.get('limit_board_continuation_candidate_count'))} "
            f"setup_state={setup.get('state', 'unknown')}"
        ),
        (
            f"- tape={tape.get('state', 'unknown')} "
            f"涨停={_fmt_num(tape.get('limit_up_count'))} "
            f"高度={_fmt_num(tape.get('highest_continuous_board'))} "
            f"炸板={_fmt_num(tape.get('broken_limit_up_count'))} "
            f"top_industry_share={_fmt_pct(concentration.get('top_industry_share_pct'))}"
        ),
        f"- passive_timing={setup.get('passive_timing_read', 'unknown')}",
        "- boundary=setup supply is a thermometer/research input, not position sizing",
        "- 右尾是每个战法/筛选/执行行内结果维度, 不是独立战法 silo",
    ]


def _format_stock_personality_selection_policy_backlog(
    payload: dict[str, Any],
) -> list[str]:
    backlog = _as_dict(payload.get("stock_personality_selection_policy_backlog"))
    if not backlog:
        return []
    full_summary = _as_dict(
        payload.get("stock_trait_full_candidate_prefilter_summary")
    )
    policies = _as_list(backlog.get("policies"))
    first_policy = _as_dict(policies[0]) if policies else {}
    wounds = ",".join(
        _wound_label(item) for item in _as_list(backlog.get("candidate_row_wounds"))[:3]
    )
    lines = [
        "",
        "股性/质地筛选:",
        (
            f"- state={backlog.get('status', 'unknown')} "
            f"policies={_fmt_num(backlog.get('policy_count'))} "
            f"row_wounds={wounds or 'none'} "
            "ranking_effect=未应用/只显示伤口"
        ),
        (
            f"- first={first_policy.get('name_zh', 'unknown')} "
            f"obs={','.join(str(item) for item in _as_list(first_policy.get('owner_observation_ids'))[:3])} "
            "boundary=只导研究,未PIT验证前不改排名"
        ),
    ]
    if full_summary:
        lines.append(
            "- 全候选股性: "
            f"候选={_fmt_num(full_summary.get('candidate_count'))} "
            f"通过={_fmt_num(full_summary.get('pass_count'))} "
            f"失败/不完整={_fmt_num(full_summary.get('fail_or_incomplete_count'))} "
            f"缺数据={_fmt_num(full_summary.get('missing_trait_row_count'))} "
            "排名影响=未应用"
        )
        fail_rows = [
            f"#{_fmt_num(row.get('rank'))} {row.get('symbol')} {row.get('stock_name')}"
            for row in _as_list(full_summary.get("top_fail_or_incomplete_rows"))[:5]
            if isinstance(row, dict)
        ]
        if fail_rows:
            lines.append(f"- 股性失败样本: {', '.join(fail_rows)}")
    route_backlog = _as_dict(backlog.get("owner_observation_route_backlog"))
    if route_backlog:
        lines.append(
            "- 观察转规格: "
            f"{route_backlog.get('status', 'unknown')} "
            f"queue={_fmt_num(route_backlog.get('queue_item_count'))} "
            f"specs={_fmt_num(route_backlog.get('spec_candidate_count'))} "
            f"股性相关={_fmt_num(route_backlog.get('stock_personality_relevant_candidate_count'))} "
            "排名影响=未应用"
        )
        spec_rows = []
        for row in _as_list(route_backlog.get("spec_candidates"))[:5]:
            item = _as_dict(row)
            observation_ids = ",".join(
                str(value)
                for value in _as_list(item.get("owner_observation_ids"))[:2]
            )
            spec_rows.append(
                f"{item.get('name_zh') or item.get('policy_id')}({observation_ids})"
            )
        if spec_rows:
            lines.append(f"- 观察规格候选: {', '.join(spec_rows)}")
    return lines


def _format_official_hard_risk_candidate_summary(
    payload: dict[str, Any],
) -> list[str]:
    summary = _as_dict(payload.get("official_hard_risk_candidate_summary"))
    if not summary:
        return []
    lines = [
        "",
        "官方硬风险候选:",
        (
            f"- 候选={_fmt_num(summary.get('candidate_count'))} "
            f"硬风险={_fmt_num(summary.get('hard_risk_candidate_count'))} "
            "排名影响=未应用 report_only=true"
        ),
    ]
    for row in _as_list(summary.get("top_rows"))[:3]:
        item = _as_dict(row)
        title = str(item.get("latest_title") or "unknown")
        if len(title) > 52:
            title = f"{title[:52]}..."
        lines.append(
            f"- #{_fmt_num(item.get('rank'))} "
            f"{item.get('symbol', 'unknown')} {item.get('stock_name', '')} "
            f"{item.get('latest_date', 'unknown')} "
            f"{item.get('latest_announcement_kind', 'unknown')} "
            f"{title}"
        )
    return lines


def _format_environment_conditioned_diagnostics(
    package: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(package, dict):
        return []
    sweep = _as_dict(package.get("environment_conditioned_ab_sweep"))
    if not sweep:
        return []
    summary = _as_dict(sweep.get("summary"))
    wounds = _as_dict(sweep.get("diagnostic_wounds"))
    route_counts = _as_dict(wounds.get("route_counts")) or _as_dict(
        summary.get("route_counts")
    )
    return [
        "",
        "环境条件化 A/B 伤口:",
        (
            f"- freshness={summary.get('freshness_status', 'unknown')} "
            f"current_promising={_fmt_num(summary.get('promising_count'))} "
            f"diagnostic_promising={_fmt_num(summary.get('diagnostic_promising_count'))} "
            f"denominator={_fmt_num(wounds.get('trial_denominator_case_count'))} "
            f"posthoc={wounds.get('candidate_variants_selected_posthoc', 'unknown')}"
        ),
        (
            f"- routes promising={_fmt_num(route_counts.get('PROMISING_REVIEW_ONLY'))} "
            f"placebo_weak={_fmt_num(route_counts.get('PLACEBO_CONTROL_WEAK'))} "
            f"not_better={_fmt_num(route_counts.get('NOT_BETTER_THAN_POOLED'))} "
            "support_insufficient="
            f"{_fmt_num(route_counts.get('SUPPORT_INSUFFICIENT', wounds.get('support_insufficient_count', 0)))}"
        ),
        (
            f"- fdr pass={_fmt_num(wounds.get('fdr_pass_count'))} "
            f"tested={_fmt_num(wounds.get('fdr_tested_case_count'))} "
            f"q={wounds.get('fdr_q', 'unknown')} "
            f"procedure={wounds.get('fdr_procedure', 'unknown')} "
            "diagnostic_only=true"
        ),
        (
            f"- date_block_ci ready="
            f"{_fmt_num(wounds.get('date_block_ci_ready_count'))} "
            f"crosses_zero="
            f"{_fmt_num(wounds.get('date_block_ci_crosses_zero_count'))} "
            f"low_support="
            f"{_fmt_num(wounds.get('date_block_ci_low_date_support_count'))} "
            f"method={wounds.get('date_block_ci_method', 'unknown')} "
            "diagnostic_only=true"
        ),
        (
            f"- trust_gate={wounds.get('uses_environment_fingerprint_trust_gate', 'unknown')} "
            f"trusted_axes={_fmt_num(wounds.get('trusted_axis_count'))} "
            f"features={_fmt_num(wounds.get('similarity_feature_count'))} "
            f"blocked_axes={','.join(str(x) for x in _as_list(wounds.get('blocked_axes_not_used'))[:3])}"
        ),
        "- boundary=diagnostic routing only; not edge, not GO, not advice",
    ]


def _format_shortest_legal_next_open_horizon(
    package: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(package, dict):
        return []
    sweep = _as_dict(package.get("long_window_cached_retry_sweep"))
    diagnostic = _as_dict(sweep.get("next_open_following_close_diagnostic_summary"))
    if not diagnostic:
        return []
    rows = _as_list(diagnostic.get("top_positive_net_rows"))
    lines = [
        "",
        "T+1合法最短持有诊断:",
        (
            f"- horizon={diagnostic.get('horizon_id', 'unknown')} "
            f"status={diagnostic.get('status', 'unknown')} "
            f"positive_net={_fmt_num(diagnostic.get('positive_net_hypothesis_count'))}"
            f"/{_fmt_num(diagnostic.get('hypothesis_count'))} "
            f"windows={_fmt_num(diagnostic.get('positive_net_window_count'))} "
            f"cost_killed={_fmt_num(diagnostic.get('cost_killed_hypothesis_count'))} "
            f"right_tail_ready="
            f"{_fmt_num(diagnostic.get('right_tail_ready_hypothesis_count'))}"
        ),
        (
            "- boundary=shortest legal next-open holding diagnostic; "
            "report-only, not edge, not GO, not advice"
        ),
    ]
    if rows:
        lines.append("- top_net:")
    for item in rows[:3]:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"  {item.get('hypothesis_id', 'unknown')} "
            f"net={_fmt_pct(item.get('best_net_excess_pct'))} "
            f"tail5={_fmt_pct(item.get('right_tail_return_ge_5pct_max_share_pct'))} "
            f"p90={_fmt_pct(item.get('right_tail_return_p90_max_pct'))} "
            f"windows={_fmt_num(item.get('windows_tested'))} "
            f"next={item.get('evolution_next_action', 'review')}"
        )
    return lines


def _format_long_window_route_counts(payload: dict[str, Any]) -> list[str]:
    stability = _as_dict(payload.get("long_window_stability"))
    machine_routes = _as_dict(stability.get("machine_route_counts"))
    adapt_routes = _as_dict(stability.get("adapt_route_counts"))
    if not machine_routes and not adapt_routes:
        return []
    return [
        "",
        "Long-window研究路由:",
        (
            f"- machine_routes {_fmt_count_map(machine_routes)} "
            "research_clock_only=true not_GO=true"
        ),
        (
            f"- adapt_routes {_fmt_count_map(adapt_routes)} "
            "research_clock_only=true not_GO=true"
        ),
        (
            "- boundary=machine route counts are research next actions; "
            "not stock advice, not validated edge"
        ),
    ]


def _route_example_key(item: dict[str, Any]) -> str:
    return str(item.get("machine_route") or item.get("adapt_route") or "UNKNOWN_ROUTE")


def _format_long_window_route_examples(payload: dict[str, Any], *, limit: int = 4) -> list[str]:
    stability = _as_dict(payload.get("long_window_stability"))
    rows = [
        item
        for item in (
            _as_list(stability.get("top_keep_rows"))
            + _as_list(stability.get("top_adapt_rows"))
        )
        if isinstance(item, dict)
    ]
    if not rows:
        return []

    examples: list[dict[str, Any]] = []
    seen_routes: set[str] = set()
    for item in rows:
        route = _route_example_key(item)
        if route in seen_routes:
            continue
        seen_routes.add(route)
        examples.append(item)
        if len(examples) >= limit:
            break

    if not examples:
        return []

    lines = ["- route_examples:"]
    for item in examples:
        ready_windows = _as_list(item.get("cross_horizon_ready_window_ids"))
        lines.append(
            f"  {item.get('hypothesis_id', 'unknown')} "
            f"route={_route_example_key(item)} "
            f"cand_windows={_fmt_num(item.get('candidate_window_count'))} "
            f"ready_windows={_fmt_num(len(ready_windows))} "
            f"follow_net={_fmt_pct(item.get('next_open_following_close_best_net_excess_pct'))} "
            "follow_tail5="
            f"{_fmt_pct(item.get('next_open_following_close_right_tail_return_ge_5pct_max_share_pct'))} "
            f"windows={_fmt_num(item.get('windows_tested'))}"
        )
    lines.append("- route_examples_boundary=examples are research routing samples, not stock advice")
    return lines


def _format_cross_horizon_consensus(payload: dict[str, Any], *, limit: int = 5) -> list[str]:
    stability = _as_dict(payload.get("long_window_stability"))
    consensus = _as_dict(stability.get("cross_horizon_right_tail_consensus"))
    rows = [item for item in _as_list(consensus.get("top_rows")) if isinstance(item, dict)]
    if not rows:
        return []

    lines = [
        "",
        f"跨horizon右尾共识假设 Top {min(limit, len(rows))}:",
        (
            f"- status={consensus.get('status', 'unknown')} "
            f"support_state={consensus.get('support_state', 'unknown')} "
            f"hypotheses={_fmt_num(consensus.get('hypothesis_count'))} "
            f"multi_ready="
            f"{_fmt_num(consensus.get('both_horizon_multi_window_ready_hypothesis_count'))} "
            f"min_windows={_fmt_num(consensus.get('multi_window_min_ready_threshold'))} "
            "diagnostic_only=true"
        ),
    ]
    for item in rows[:limit]:
        lines.append(
            f"- {item.get('hypothesis_id', 'unknown')} "
            f"min_ready={_fmt_num(item.get('min_right_tail_ready_window_count'))} "
            f"same_close_net="
            f"{_fmt_pct(item.get('next_open_close_best_net_excess_pct'))} "
            f"same_close_tail5="
            f"{_fmt_pct(item.get('next_open_close_tail5_max_share_pct'))} "
            f"follow_net="
            f"{_fmt_pct(item.get('next_open_following_close_best_net_excess_pct'))} "
            f"follow_tail5="
            f"{_fmt_pct(item.get('next_open_following_close_tail5_max_share_pct'))} "
            f"windows={_fmt_num(item.get('windows_tested'))} "
            f"action={item.get('evolution_next_action', 'review')}"
        )
    lines.append(
        "- boundary=report-only consensus; same_close is diagnostic; "
        "legal horizon still has no validated edge, no GO, no advice"
    )
    return lines


def _flatten_forward_shadow_track_record(track: dict[str, Any]) -> dict[str, Any]:
    if not track:
        return {}
    if isinstance(track.get("summary"), dict):
        summary = _as_dict(track.get("summary"))
        observed_from = _as_dict(track.get("observed_from"))
        return {
            "source_status": track.get("status"),
            "source_report_path": track.get("report_path"),
            "source_markdown_path": track.get("markdown_path"),
            "freeze_id": track.get("freeze_id"),
            "as_of_date": track.get("as_of_date"),
            "target_trade_date": track.get("target_trade_date"),
            "open_state_waterline": observed_from.get("open_state_waterline"),
            "lifecycle_state": summary.get("lifecycle_state"),
            "next_action": summary.get("next_action"),
            "candidate_track_count": summary.get("candidate_track_count"),
            "trigger_fired_count": summary.get("trigger_fired_count"),
            "pending_trigger_count": summary.get("pending_trigger_count"),
            "following_observed_count": summary.get("following_observed_count"),
            "following_scoreable_candidate_count": summary.get(
                "following_scoreable_candidate_count"
            ),
            "d3_observed_count": summary.get("d3_observed_count"),
            "d5_observed_count": summary.get("d5_observed_count"),
            "scoreable_candidate_count": summary.get("scoreable_candidate_count"),
            "next_observation_targets": summary.get("next_observation_targets"),
        }
    return dict(track)


def _merge_forward_shadow_track_records(
    primary: dict[str, Any],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in fallback.items():
        if merged.get(key) in ("", None) and value not in ("", None):
            merged[key] = value
    return merged


def _format_forward_shadow_track_record(
    package: dict[str, Any] | None,
    *,
    track_record: dict[str, Any] | None = None,
) -> list[str]:
    embedded_track = (
        _flatten_forward_shadow_track_record(
            _as_dict(package.get("forward_shadow_track_record"))
        )
        if isinstance(package, dict)
        else {}
    )
    fallback_track = _flatten_forward_shadow_track_record(_as_dict(track_record))
    track = _merge_forward_shadow_track_records(embedded_track, fallback_track)
    if not track:
        return []

    target_rows: list[str] = []
    for item in _as_list(track.get("next_observation_targets"))[:2]:
        if not isinstance(item, dict):
            continue
        target_rows.append(
            f"{item.get('target', 'unknown')}@{item.get('date', 'unknown')}"
            f" count={_fmt_num(item.get('candidate_count'))}"
            f" reason={item.get('reason', 'unknown')}"
        )

    lines = [
        "",
        "Forward-shadow闭环:",
        (
            f"- source={track.get('source_status', 'unknown')} "
            f"freeze={track.get('freeze_id', 'unknown')} "
            f"as_of={track.get('as_of_date', 'unknown')} "
            f"target={track.get('target_trade_date', 'unknown')} "
            f"open_state_waterline={track.get('open_state_waterline', 'unknown')}"
        ),
        (
            f"- lifecycle={track.get('lifecycle_state', 'unknown')} "
            f"next={track.get('next_action', 'unknown')}"
        ),
        (
            f"- records={_fmt_num(track.get('candidate_track_count'))} "
            f"fired={_fmt_num(track.get('trigger_fired_count'))} "
            f"pending={_fmt_num(track.get('pending_trigger_count'))} "
            f"following={_fmt_num(track.get('following_observed_count'))} "
            f"following_scoreable="
            f"{_fmt_num(track.get('following_scoreable_candidate_count'))} "
            f"d3={_fmt_num(track.get('d3_observed_count'))} "
            f"d5={_fmt_num(track.get('d5_observed_count'))} "
            f"scoreable={_fmt_num(track.get('scoreable_candidate_count'))}"
        ),
    ]
    if target_rows:
        lines.append(f"- next_targets={'; '.join(target_rows)}")
    lines.append(
        "- boundary=frozen candidate track record; pending is not failed trade, not negative edge"
    )
    return lines


def _format_weak_signal_queue(payload: dict[str, Any], *, limit: int) -> list[str]:
    queue = _as_list(payload.get("weak_signal_review_queue"))
    if not queue:
        return []

    lines = [
        "",
        f"弱信号观察队列 Top {min(limit, len(queue))}:",
        "- boundary=pattern-level review queue; not edge, not stock advice",
    ]
    for item in queue[:limit]:
        if not isinstance(item, dict):
            continue
        wounds = _as_list(item.get("wounds"))
        first_wound = _wound_label(wounds[0]) if wounds else "none"
        lines.append(
            f"- {item.get('hypothesis_id', 'unknown')} "
            f"horizon={item.get('horizon_id', 'unknown')} "
            f"window={item.get('window_id', 'unknown')} "
            f"route={item.get('route', 'unknown')} "
            f"gross={_fmt_pct(item.get('gross_excess_pct'))} "
            f"net={_fmt_pct(item.get('net_excess_pct'))} "
            f"win={_fmt_pct(item.get('win_rate_pct'))} "
            f"n={_fmt_num(item.get('row_n'))}/days={_fmt_num(item.get('date_block_effective_n'))} "
            f"wounds={len(wounds)} first={first_wound} "
            f"next={item.get('next_action', 'review')}"
        )
    return lines


def _format_cross_horizon_clusters(payload: dict[str, Any], *, limit: int = 3) -> list[str]:
    clusters = _as_dict(payload.get("cross_horizon_right_tail_candidate_clusters"))
    stability = _as_dict(payload.get("long_window_stability"))
    consensus_readout = _as_dict(stability.get("cross_horizon_right_tail_consensus"))
    top_clusters = _as_list(clusters.get("top_clusters"))
    if not top_clusters:
        return []
    lines = [
        "",
        "跨horizon右尾交集:",
        (
            f"- status={clusters.get('status', 'unknown')} "
            f"clusters={_fmt_num(clusters.get('matched_cluster_count'))} "
            f"stocks={_fmt_num(clusters.get('matched_stock_candidate_count'))} "
            f"consensus={_fmt_num(clusters.get('consensus_hypothesis_count'))} "
            "diagnostic_only=true"
        ),
    ]
    if consensus_readout:
        lines.append(
            f"- support_state={consensus_readout.get('support_state', 'unknown')} "
            f"multi_window_ready="
            f"{_fmt_num(consensus_readout.get('both_horizon_multi_window_ready_hypothesis_count'))} "
            f"single_window_only="
            f"{_fmt_num(consensus_readout.get('both_horizon_single_window_only_hypothesis_count'))} "
            f"min_windows={_fmt_num(consensus_readout.get('multi_window_min_ready_threshold'))}"
        )
        if consensus_readout.get("support_warning"):
            lines.append(f"- support_warning={consensus_readout.get('support_warning')}")
        support_width_backlog = _as_dict(consensus_readout.get("support_width_backlog"))
        if support_width_backlog.get("candidate_count"):
            lines.append(
                "- support_width_backlog "
                f"status={support_width_backlog.get('status', 'unknown')} "
                f"count={_fmt_num(support_width_backlog.get('candidate_count'))} "
                f"route={support_width_backlog.get('route', 'unknown')} "
                f"min_windows={_fmt_num(support_width_backlog.get('min_ready_threshold'))} "
                "research_clock_only=true"
            )
    trait_summary = _as_dict(payload.get("right_tail_cluster_stock_trait_summary"))
    if trait_summary:
        lines.append(
            "- 右尾簇股性: "
            f"成员={_fmt_num(trait_summary.get('member_count'))} "
            f"通过={_fmt_num(trait_summary.get('pass_count'))} "
            f"失败/不完整={_fmt_num(trait_summary.get('fail_or_incomplete_count'))} "
            f"缺数据={_fmt_num(trait_summary.get('missing_trait_row_count'))} "
            f"簇={_fmt_num(trait_summary.get('cluster_count'))} "
            "排名影响=未应用"
        )
        pass_rows = [
            str(row.get("stock_name") or row.get("symbol"))
            for row in _as_list(trait_summary.get("top_pass_rows"))[:4]
            if isinstance(row, dict)
        ]
        if pass_rows:
            lines.append(f"- 右尾簇股性通过: {', '.join(pass_rows)}")
    for row in top_clusters[:limit]:
        if not isinstance(row, dict):
            continue
        consensus = _as_dict(row.get("consensus_snapshot"))
        stocks = ", ".join(
            str(stock.get("stock_name") or stock.get("symbol"))
            for stock in _as_list(row.get("top_stocks"))[:4]
            if isinstance(stock, dict)
        )
        lines.append(
            f"- {row.get('tactic_id', 'unknown')}::{row.get('industry_name', 'unknown')} "
            f"rows={_fmt_num(row.get('candidate_count'))} "
            f"top={stocks or 'none'} "
            f"close_tail5={_fmt_pct(consensus.get('next_open_close_tail5_max_share_pct'))} "
            f"follow_tail5={_fmt_pct(consensus.get('next_open_following_close_tail5_max_share_pct'))} "
            f"ready_min={_fmt_num(consensus.get('min_right_tail_ready_window_count'))} "
            f"action={consensus.get('evolution_next_action', 'review')}"
        )
    lines.append("- boundary=cluster is one correlated setup; not independent stock edges")
    return lines


def _fmt_named_counts(rows: list[Any], *, limit: int = 3) -> str:
    parts: list[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "unknown"))
        zh_name = (
            row.get("hypothesis_name_zh")
            or row.get("family_name_zh")
            or row.get("name_zh")
        )
        label = f"{zh_name}/{name}" if zh_name else name
        parts.append(f"{label}={_fmt_num(row.get('count'))}")
    return " ".join(parts) if parts else "none"


def _fmt_named_counts_owner(rows: list[Any], *, limit: int = 3) -> str:
    parts: list[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        name = (
            row.get("hypothesis_name_zh")
            or row.get("family_name_zh")
            or row.get("name_zh")
            or row.get("name")
            or "unknown"
        )
        parts.append(f"{name}={_fmt_num(row.get('count'))}")
    return " ".join(parts) if parts else "none"


def _format_compact_strategy_hints(
    candidates: list[dict[str, Any]],
    *,
    limit: int = 2,
) -> str | None:
    parts: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        tactic_id = str(item.get("tactic_id") or item.get("tactic_name") or "")
        if not tactic_id or tactic_id in seen:
            continue
        seen.add(tactic_id)
        metadata = _as_dict(item.get("strategy_metadata_zh"))
        name = (
            metadata.get("name_zh")
            or item.get("tactic_name")
            or item.get("tactic_id")
            or "unknown"
        )
        pattern = metadata.get("pattern_zh")
        selection = metadata.get("selection_policy_zh")
        if not pattern and not selection:
            continue
        detail = "；".join(str(value) for value in (pattern, selection) if value)
        parts.append(f"{name}: {detail}")
        if len(parts) >= limit:
            break
    if not parts:
        return None
    return "战法条件: " + " | ".join(parts)


def _format_compact_scout_condition_hints(
    scout_surface: dict[str, Any],
    *,
    limit: int = 2,
) -> str | None:
    parts: list[str] = []
    for row in _as_list(scout_surface.get("top_families"))[:limit]:
        if not isinstance(row, dict):
            continue
        name = row.get("family_name_zh") or row.get("name")
        condition = row.get("condition_summary_zh")
        if name and condition:
            parts.append(f"{name}: {condition}")
    if not parts:
        return None
    return "Scout条件: " + " | ".join(str(part) for part in parts)


def _format_compact_scout_needs_spec_hints(
    scout_surface: dict[str, Any],
    scout_counts: dict[str, Any],
    *,
    limit: int = 3,
) -> str | None:
    examples = _as_list(scout_surface.get("needs_executable_spec_examples"))
    if not examples:
        return None
    names: dict[str, int] = {}
    for row in examples:
        if not isinstance(row, dict):
            continue
        metadata = _as_dict(row.get("owner_visible_metadata_zh"))
        name = (
            metadata.get("hypothesis_name_zh")
            or row.get("hypothesis_id")
            or "unknown"
        )
        names[str(name)] = names.get(str(name), 0) + 1
    if not names:
        return None
    total = scout_counts.get("needs_executable_spec_cell_count")
    if len(names) == 1 and total is not None:
        name = next(iter(names))
        return f"Scout待定义: {name}={_fmt_num(total)}"
    parts = [
        f"{name}={_fmt_num(count)}"
        for name, count in sorted(names.items(), key=lambda item: (-item[1], item[0]))[
            :limit
        ]
    ]
    return "Scout待定义: " + " ".join(parts)


def _format_compact_materialized_outcome_summary(
    scout: dict[str, Any],
) -> str | None:
    summary = _as_dict(scout.get("daywalk_outcome_summary"))
    if not summary:
        scout_surface = _as_dict(scout.get("owner_review_surface"))
        summary = _as_dict(scout_surface.get("materialized_daywalk_outcome_summary"))
    route_counts = _as_dict(summary.get("route_counts"))
    if not route_counts:
        return None
    return (
        "已跑结果: "
        f"truth_units={_fmt_num(summary.get('truth_unit_count'))} "
        f"严格={_fmt_num(route_counts.get('strict_candidate_review_only'))} "
        f"右尾={_fmt_num(route_counts.get('owner_review_tail_watch'))} "
        f"support不足={_fmt_num(route_counts.get('needs_support_before_review'))} "
        f"成本缺={_fmt_num(route_counts.get('observation_only_net_cost_missing'))} "
        f"成本杀={_fmt_num(route_counts.get('observation_only_net_cost_killed'))} "
        f"右尾负均值={_fmt_num(route_counts.get('right_tail_but_mean_negative_review_only'))}"
    )


def _format_compact_feedback_route_intake(intake: dict[str, Any]) -> str:
    status = str(intake.get("status") or "UNKNOWN")
    action_counts = _as_dict(intake.get("research_action_counts"))
    next_actions = _as_list(intake.get("next_actions"))
    latest_action = "none"
    if next_actions and isinstance(next_actions[0], dict):
        latest_action = str(next_actions[0].get("action") or "unknown")
    action_text = _fmt_named_counts_owner(
        [
            {"name": name, "count": count}
            for name, count in sorted(action_counts.items())
        ],
        limit=3,
    )
    return (
        "反馈接入Kairos: "
        f"{status} "
        f"queue={_fmt_num(intake.get('queue_item_count'))} "
        f"source_total={_fmt_num(intake.get('source_total_route_item_count'))} "
        f"动作={action_text} "
        f"next={latest_action} "
        "边界=只导研究,不改证据门/排名"
    )


def _format_scout_example(row: dict[str, Any]) -> str:
    missing = _as_list(row.get("missing_surface_requirements"))
    missing_text = ",".join(str(item) for item in missing[:3]) if missing else "none"
    metadata = _as_dict(row.get("owner_visible_metadata_zh"))
    hypothesis_name = metadata.get("hypothesis_name_zh") or row.get(
        "hypothesis_id",
        "unknown",
    )
    family_name = metadata.get("family_name_zh") or row.get("family", "unknown")
    condition_summary = metadata.get("condition_summary_zh")
    condition_text = f" condition={condition_summary}" if condition_summary else ""
    return (
        f"{hypothesis_name}({row.get('hypothesis_id', 'unknown')}) "
        f"family={family_name}/{row.get('family', 'unknown')} "
        f"horizon={row.get('horizon_id', 'unknown')} "
        f"route={row.get('route', 'unknown')} "
        f"dispatch={row.get('execution_dispatch', 'unknown')} "
        f"missing={missing_text} "
        f"next={row.get('next_action', 'review')}"
        f"{condition_text}"
    )


def _format_hypothesis_scout_readout(
    scout: dict[str, Any] | None,
    *,
    limit: int = 2,
) -> list[str]:
    if not isinstance(scout, dict):
        return []

    errors = _as_list(scout.get("errors"))
    if errors:
        return [
            "",
            "Broad scout intake:",
            (
                f"- scout={scout.get('status', 'unknown')} "
                f"accepted_edges={scout.get('accepted_edges', 0)}"
            ),
            *[f"- error={item}" for item in errors[:2]],
            f"- artifact={scout.get('report_path', 'unknown')}",
            "- boundary=scout unavailable; no evidence, no edge, no GO, no advice",
        ]

    counts = _as_dict(scout.get("counts"))
    surface = _as_dict(scout.get("owner_review_surface"))
    top_families = _as_list(surface.get("top_families"))
    top_hypotheses = _as_list(surface.get("top_hypotheses"))
    dispatchable = _as_list(surface.get("dispatchable_examples"))
    materialized = _as_list(surface.get("already_materialized_daywalk_examples"))
    needs_spec = _as_list(surface.get("needs_executable_spec_examples"))
    pending_surface = _as_list(surface.get("pending_surface_examples"))

    lines = [
        "",
        "Broad scout intake:",
        (
            f"- scout={scout.get('status', 'unknown')} "
            f"surface={surface.get('surface_status', 'unknown')} "
            f"cells={_fmt_num(counts.get('scout_cell_count'))} "
            f"hypotheses={_fmt_num(counts.get('hypothesis_card_count'))} "
            f"dispatchable={_fmt_num(counts.get('dispatchable_pending_run_cell_count'))} "
            f"materialized_daywalk={_fmt_num(counts.get('daywalk_report_materialized_cell_count'))} "
            f"specialized_readout={_fmt_num(counts.get('specialized_readout_ready_cell_count'))} "
            f"needs_spec={_fmt_num(counts.get('needs_executable_spec_cell_count'))} "
            f"pending_surface={_fmt_num(counts.get('pending_surface_cell_count'))} "
            f"accepted_edges={scout.get('accepted_edges', 0)}"
        ),
        (
            f"- top_families {_fmt_named_counts(top_families, limit=4)}; "
            f"top_hypotheses {_fmt_named_counts(top_hypotheses, limit=4)}"
        ),
    ]
    for row in dispatchable[:limit]:
        if isinstance(row, dict):
            lines.append(f"- dispatchable: {_format_scout_example(row)}")
    for row in materialized[:limit]:
        if isinstance(row, dict):
            paths = _as_list(row.get("existing_daywalk_report_paths"))
            first_path = paths[0] if paths else "unknown"
            lines.append(
                f"- already_materialized: {_format_scout_example(row)} "
                f"report={first_path}"
            )
    for row in needs_spec[:limit]:
        if isinstance(row, dict):
            lines.append(f"- needs_spec: {_format_scout_example(row)}")
    for row in pending_surface[:limit]:
        if isinstance(row, dict):
            lines.append(f"- pending_surface: {_format_scout_example(row)}")
    markdown_path = scout.get("markdown_path")
    if markdown_path:
        lines.append(f"- scout_md={markdown_path}")
    lines.append(
        "- boundary=scout denominator only; not evidence, not edge, not GO, not advice"
    )
    return lines


def _format_owner_review_truth_units(
    truth_units: dict[str, Any] | None,
    *,
    limit: int = 4,
) -> list[str]:
    if not isinstance(truth_units, dict):
        return []

    errors = _as_list(truth_units.get("errors"))
    if errors:
        return [
            "",
            "Owner-review truth units:",
            (
                f"- truth_units={truth_units.get('status', 'unknown')} "
                f"accepted_edges={truth_units.get('accepted_edges', 0)}"
            ),
            *[f"- error={item}" for item in errors[:2]],
            f"- artifact={truth_units.get('report_path', 'unknown')}",
            "- boundary=truth-unit readout unavailable; no evidence, no edge, no GO, no advice",
        ]

    top_rows = _as_list(truth_units.get("top_truth_units"))
    route_counts = _as_dict(truth_units.get("route_counts"))
    confidence_counts = _as_dict(truth_units.get("confidence_counts"))
    tier_counts = _as_dict(truth_units.get("evidence_tier_counts"))
    lines = [
        "",
        "Owner-review truth units:",
        (
            f"- truth_units={truth_units.get('status', 'unknown')} "
            f"units={_fmt_num(truth_units.get('truth_unit_count'))} "
            f"variants={_fmt_num(truth_units.get('variant_truth_unit_count'))} "
            f"source_results={_fmt_num(truth_units.get('source_result_count'))} "
            f"accepted_edges={truth_units.get('accepted_edges', 0)}"
        ),
        (
            f"- routes strict={_fmt_num(route_counts.get('strict_candidate_review_only'))} "
            f"tail_watch={_fmt_num(route_counts.get('owner_review_tail_watch'))} "
            f"tail_negative={_fmt_num(route_counts.get('right_tail_but_mean_negative_review_only'))} "
            f"thin={_fmt_num(route_counts.get('needs_support_before_review'))}"
        ),
        (
            f"- confidence usable={_fmt_num(confidence_counts.get('usable_reference_net_ci_positive'))} "
            f"tail_support={_fmt_num(confidence_counts.get('owner_tail_watch_support_ok'))} "
            f"sample_ok={_fmt_num(confidence_counts.get('observation_sample_ok_not_confirmed'))}"
        ),
        (
            f"- evidence_tiers supported={_fmt_num(tier_counts.get('SUPPORTED_OBSERVATION', 0))} "
            f"observation={_fmt_num(tier_counts.get('OBSERVATION', 0))} "
            f"validated={_fmt_num(tier_counts.get('VALIDATED_EDGE', 0))}"
        ),
    ]
    for row in top_rows[:limit]:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('hypothesis_id', 'unknown')} "
            f"horizon={row.get('horizon_id', 'unknown')} "
            f"证据层={_evidence_tier_label(row.get('evidence_tier'))} "
            f"route={row.get('owner_review_route', 'unknown')} "
            f"latest={row.get('latest_verdict', 'unknown')} "
            f"net={_fmt_pct(row.get('latest_executable_excess_pct_net_static_cost'))} "
            f"tail5={_fmt_pct(row.get('latest_right_tail_return_ge_5pct_share_pct'))} "
            f"p90={_fmt_pct(row.get('latest_right_tail_return_p90_pct'))} "
            f"n={_fmt_num(row.get('latest_executable_row_n'))}/days={_fmt_num(row.get('latest_date_cluster_n'))} "
            f"windows={_fmt_num(row.get('observed_window_count'))} "
            f"ci_cross={row.get('latest_date_block_ci_crosses_zero')}"
        )
    strict_block_rows = [
        row
        for row in _as_list(truth_units.get("all_truth_units"))
        if isinstance(row, dict)
        and row.get("source_type") == "block_condition_daywalk"
        and row.get("owner_review_route") == "strict_candidate_review_only"
    ][:3]
    if strict_block_rows:
        lines.append("- block_condition_strict_candidates:")
        for row in strict_block_rows:
            wounds = _fmt_wound_list(_as_list(row.get("presentation_wounds")))
            lines.append(
                f"  - {row.get('hypothesis_id', 'unknown')} "
                f"horizon={row.get('horizon_id', 'unknown')} "
                f"latest={row.get('latest_verdict', 'unknown')} "
                f"gross={_fmt_pct(row.get('latest_executable_excess_pct_gross'))} "
                f"n={_fmt_num(row.get('latest_executable_row_n'))}/"
                f"days={_fmt_num(row.get('latest_date_cluster_n'))} "
                f"source=block_condition_daywalk "
                f"证据层={_evidence_tier_label(row.get('evidence_tier'))} "
                f"not_edge=true wounds={wounds}"
            )
    generic_daywalk_rows_all = [
        row
        for row in _as_list(truth_units.get("all_truth_units"))
        if isinstance(row, dict)
        and row.get("source_type") == "hypothesis_daywalk"
    ]
    generic_daywalk_candidate_rows = [
        row
        for row in generic_daywalk_rows_all
        if row.get("latest_verdict") == "CANDIDATE_ONLY"
    ]
    generic_daywalk_rows_positive = [
        row
        for row in generic_daywalk_candidate_rows or generic_daywalk_rows_all
        if _float_or(row.get("latest_executable_excess_pct_gross"), -1.0) > 0.0
    ]
    generic_daywalk_rows = sorted(
        generic_daywalk_rows_positive or generic_daywalk_rows_all,
        key=_truth_unit_review_sort_key,
        reverse=True,
    )[:3]
    if generic_daywalk_rows:
        lines.append("- generic_daywalk_truth_units:")
        for row in generic_daywalk_rows:
            wounds = _fmt_wound_list(_as_list(row.get("presentation_wounds")))
            lines.append(
                f"  - {row.get('hypothesis_id', 'unknown')} "
                f"family={row.get('family', 'unknown')} "
                f"horizon={row.get('horizon_id', 'unknown')} "
                f"latest={row.get('latest_verdict', 'unknown')} "
                f"gross={_fmt_pct(row.get('latest_executable_excess_pct_gross'))} "
                f"n={_fmt_num(row.get('latest_executable_row_n'))}/"
                f"days={_fmt_num(row.get('latest_date_cluster_n'))} "
                f"source=hypothesis_daywalk "
                f"证据层={_evidence_tier_label(row.get('evidence_tier'))} "
                f"not_edge=true wounds={wounds}"
            )
    report_path = truth_units.get("report_path")
    if report_path:
        lines.append(f"- truth_units_artifact={report_path}")
    lines.append(
        "- boundary=lower presentation threshold only; score/rank is not evidence, edge, GO, or advice"
    )
    return lines


def format_kairos_owner_brief_compact(
    payload: dict[str, Any],
    *,
    candidate_limit: int = 6,
    daily_package: dict[str, Any] | None = None,
    intraday_manifest: dict[str, Any] | None = None,
    intraday_alert: dict[str, Any] | None = None,
    intraday_eod_review_queue: dict[str, Any] | None = None,
    intraday_eod_outcome_review: dict[str, Any] | None = None,
    forward_shadow_track_record: dict[str, Any] | None = None,
    hypothesis_scout_readout: dict[str, Any] | None = None,
    owner_review_truth_units: dict[str, Any] | None = None,
    owner_feedback_summary: dict[str, Any] | None = None,
    owner_feedback_route_intake: dict[str, Any] | None = None,
) -> str:
    """Render a short owner-visible daily brief for WeChat."""

    _ = intraday_manifest, forward_shadow_track_record

    if owner_review_truth_units is None:
        owner_review_truth_units = load_kairos_owner_review_truth_units()
    if intraday_eod_review_queue is None:
        intraday_eod_review_queue = load_kairos_intraday_eod_review_queue()
    if intraday_eod_outcome_review is None:
        intraday_eod_outcome_review = load_kairos_intraday_eod_outcome_review()
    if owner_feedback_summary is None:
        owner_feedback_summary = load_owner_feedback_summary()
    if owner_feedback_route_intake is None:
        owner_feedback_route_intake = load_kairos_owner_feedback_route_intake()

    status = str(payload.get("status") or "UNKNOWN")
    as_of = payload.get("as_of_date") or "unknown"
    target = payload.get("target_trade_date") or "unknown"
    accepted_edges = payload.get("accepted_edges", 0)
    report_path = payload.get("report_path", "unknown")
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return "\n".join(
            [
                f"Kairos 日包={status}",
                f"artifact={report_path}",
                *[f"error={item}" for item in errors[:3]],
                "边界: report-only / accepted_edges=0 / 非买卖建议",
            ]
        )

    market = _as_dict(payload.get("market_facts"))
    concentration = _as_dict(payload.get("industry_concentration"))
    posture = _as_dict(payload.get("explosive_short_cycle_posture"))
    setup = _as_dict(posture.get("setup_supply"))
    tape = _as_dict(posture.get("right_tail_tape"))
    env_diag = _as_dict(payload.get("environment_diagnostics"))
    env_rigor = _as_dict(env_diag.get("rigor_summary"))
    candidates = [
        item for item in _as_list(payload.get("owner_review_candidates"))
        if isinstance(item, dict)
    ]
    tactic_names_zh = {
        str(item.get("tactic_id")): str(
            _as_dict(item.get("strategy_metadata_zh")).get("name_zh")
            or item.get("tactic_name")
            or item.get("tactic_id")
        )
        for item in candidates
        if item.get("tactic_id")
    }
    truth_units = _as_dict(owner_review_truth_units)
    truth_coverage = _as_dict(truth_units.get("coverage_summary"))
    scout = _as_dict(hypothesis_scout_readout)
    scout_counts = _as_dict(scout.get("counts"))
    scout_surface = _as_dict(scout.get("owner_review_surface"))

    lines = [
        f"Kairos 日包 {as_of} -> {target}",
        f"边界: report-only / accepted_edges={accepted_edges} / 非买卖建议",
        (
            "市场: "
            f"{_zh_label(market.get('market_regime'), MARKET_REGIME_LABEL_ZH)} "
            f"情绪={_zh_label(market.get('emotion_phase'), EMOTION_PHASE_LABEL_ZH)} "
            f"breadth={_fmt_pct(market.get('breadth_up_pct'))} "
            f"涨停={_fmt_num(market.get('limit_up_count'))} "
            f"炸板={_fmt_num(market.get('broken_limit_up_count'))} "
            f"高度={_fmt_num(market.get('highest_continuous_board'))}"
        ),
        (
            "行业集中: "
            f"{_zh_label(concentration.get('state'), CONCENTRATION_LABEL_ZH)} "
            f"top={_fmt_pct(concentration.get('top_industry_share_pct'))} "
            f"HHI={_fmt_num(concentration.get('hhi'))}"
        ),
        (
            "右尾温度计: "
            f"setup={_fmt_num(setup.get('owner_candidate_count'))} "
            f"watchlist={_fmt_num(setup.get('stock_watchlist_count'))} "
            f"强封无炸={_fmt_num(setup.get('limit_board_continuation_candidate_count'))} "
            f"涨停={_fmt_num(tape.get('limit_up_count'))} "
            f"炸板={_fmt_num(tape.get('broken_limit_up_count'))}"
        ),
        "右尾是每个战法/筛选/执行行内结果维度, 不是独立战法 silo",
    ]
    if env_diag:
        lines.append(
            "环境诊断: "
            f"cases={_fmt_num(env_diag.get('case_count'))} "
            f"当前候选={_fmt_num(env_diag.get('current_promising_count'))} "
            f"FDR过={_fmt_num(env_rigor.get('fdr_pass_count'))}/"
            f"{_fmt_num(env_rigor.get('fdr_known_count'))} "
            f"CI未穿0={_fmt_num(env_rigor.get('date_block_ci_non_cross_zero_count'))} "
            f"CI穿0={_fmt_num(env_rigor.get('date_block_ci_crosses_zero_count'))} "
            f"posthoc={_fmt_num(env_rigor.get('posthoc_variant_selection_count'))} "
            f"伤口={_fmt_num(env_rigor.get('case_wound_count'))} "
            f"fresh={env_diag.get('freshness_status', 'unknown')} "
            "边界=report-only"
        )

    lines.extend(_format_stock_personality_selection_policy_backlog(payload))
    lines.extend(_format_official_hard_risk_candidate_summary(payload))

    lines.extend(
        _format_compact_intraday_status(
            intraday_alert,
            limit=3,
            tactic_names_zh=tactic_names_zh,
        )
    )
    lines.extend(_format_compact_intraday_eod_review(intraday_eod_review_queue))
    lines.extend(_format_compact_intraday_eod_outcome_review(intraday_eod_outcome_review))

    strategy_hints = _format_compact_strategy_hints(candidates)
    if strategy_hints:
        lines.append(strategy_hints)

    lines.extend(_format_cross_horizon_clusters(payload, limit=2))

    lines.append(f"明天重点 Top {min(candidate_limit, len(candidates))}:")
    for item in candidates[:candidate_limit]:
        support = _as_dict(item.get("tactic_support"))
        wounds = _fmt_wound_list(_as_list(item.get("evidence_wounds")), limit=2)
        right_tail_cluster = _fmt_right_tail_cluster_membership(item)
        lines.append(
            f"- #{_fmt_num(item.get('review_rank'))} "
            f"{item.get('symbol', 'unknown')} {item.get('stock_name', '')} "
            f"[{item.get('industry_name', 'unknown')}] "
            f"{item.get('tactic_name', item.get('tactic_id', 'unknown'))} "
            f"证据层={_evidence_tier_label(item.get('evidence_tier'))} "
            f"{item.get('owner_confidence_label', 'unknown')} "
            f"净超额={_fmt_pct(support.get('net_excess_pct'))} "
            f"右尾5={_fmt_pct(support.get('right_tail_return_ge_5pct_share_pct'))} "
            f"{right_tail_cluster + ' ' if right_tail_cluster else ''}"
            f"样本={_fmt_num(support.get('row_n'))}/天={_fmt_num(support.get('date_block_effective_n'))} "
            f"伤口={wounds}"
        )

    lines.extend(
        [
            (
                "研究队列: "
                f"可审单元={_fmt_num(truth_units.get('truth_unit_count'))} "
                f"严格候选={_fmt_num(_as_dict(truth_units.get('route_counts')).get('strict_candidate_review_only'))} "
                f"右尾观察={_fmt_num(_as_dict(truth_units.get('route_counts')).get('owner_review_tail_watch'))} "
                f"scout总数={_fmt_num(scout_counts.get('scout_cell_count'))} "
                f"待跑={_fmt_num(scout_counts.get('dispatchable_pending_run_cell_count'))} "
                f"已跑={_fmt_num(scout_counts.get('daywalk_report_materialized_cell_count'))} "
                f"专用readout={_fmt_num(scout_counts.get('specialized_readout_ready_cell_count'))} "
                f"待定义={_fmt_num(scout_counts.get('needs_executable_spec_cell_count'))}"
            ),
            (
                "证据覆盖: "
                f"窗口={_fmt_num(truth_coverage.get('observed_window_count'))} "
                f"horizon={_fmt_num(truth_coverage.get('horizon_count'))} "
                f"多窗单元={_fmt_num(truth_coverage.get('multi_window_truth_unit_count'))}"
            ),
            (
                "Scout重点: "
                f"{_fmt_named_counts_owner(_as_list(scout_surface.get('top_families')), limit=2)}; "
                f"{_fmt_named_counts_owner(_as_list(scout_surface.get('top_hypotheses')), limit=2)}"
            ),
        ]
    )
    materialized_outcome_summary = _format_compact_materialized_outcome_summary(scout)
    if materialized_outcome_summary:
        lines.append(materialized_outcome_summary)
    scout_condition_hints = _format_compact_scout_condition_hints(scout_surface)
    if scout_condition_hints:
        lines.append(scout_condition_hints)
    scout_needs_spec_hints = _format_compact_scout_needs_spec_hints(
        scout_surface,
        scout_counts,
    )
    if scout_needs_spec_hints:
        lines.append(scout_needs_spec_hints)
    lines.append(format_owner_feedback_summary(owner_feedback_summary))
    lines.append(_format_compact_feedback_route_intake(owner_feedback_route_intake))

    package_path = _as_dict(daily_package).get("report_path")
    if package_path:
        lines.append(f"package={package_path}")
    lines.append(f"brief={report_path}")
    lines.append("完整诊断: /brief full；盘中: /intraday")
    return "\n".join(lines)


def format_kairos_owner_brief(
    payload: dict[str, Any],
    *,
    candidate_limit: int = 12,
    daily_package: dict[str, Any] | None = None,
    intraday_manifest: dict[str, Any] | None = None,
    intraday_alert: dict[str, Any] | None = None,
    intraday_eod_review_queue: dict[str, Any] | None = None,
    intraday_eod_outcome_review: dict[str, Any] | None = None,
    forward_shadow_track_record: dict[str, Any] | None = None,
    hypothesis_scout_readout: dict[str, Any] | None = None,
    owner_review_truth_units: dict[str, Any] | None = None,
) -> str:
    """Render the latest owner review brief as a compact mobile readout."""

    if owner_review_truth_units is None:
        owner_review_truth_units = load_kairos_owner_review_truth_units()
    if intraday_eod_review_queue is None:
        intraday_eod_review_queue = load_kairos_intraday_eod_review_queue()
    if intraday_eod_outcome_review is None:
        intraday_eod_outcome_review = load_kairos_intraday_eod_outcome_review()

    status = str(payload.get("status") or "UNKNOWN")
    as_of = payload.get("as_of_date") or "unknown"
    target = payload.get("target_trade_date") or "unknown"
    accepted_edges = payload.get("accepted_edges", 0)
    report_path = payload.get("report_path", "unknown")
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return "\n".join(
            [
                f"Kairos brief={status}",
                f"report_path={report_path}",
                *[f"error={item}" for item in errors[:3]],
                "boundary=read-only report; not an advisory packet; accepted_edges=0",
            ]
        )

    market = payload.get("market_facts")
    if not isinstance(market, dict):
        market = {}
    concentration = payload.get("industry_concentration")
    if not isinstance(concentration, dict):
        concentration = {}
    candidates = payload.get("owner_review_candidates")
    if not isinstance(candidates, list):
        candidates = []
    label_counts: Counter[str] = Counter()
    wound_counts: Counter[str] = Counter()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        label_counts[str(item.get("owner_confidence_label") or "unknown")] += 1
        for wound in _as_list(item.get("evidence_wounds")):
            wound_counts[str(wound)] += 1
    env_diag = payload.get("environment_diagnostics")
    if not isinstance(env_diag, dict):
        env_diag = {}
    base_rates = payload.get("limit_board_base_rates")
    if not isinstance(base_rates, list):
        base_rates = []

    lines = [
        f"Kairos 日包 brief={status}",
        f"as_of={as_of} target={target} accepted_edges={accepted_edges}",
        "boundary=report-only / 不是买卖建议 / 不是 validated edge",
        "",
        "市场事实:",
        (
            f"- regime={market.get('market_regime', 'unknown')} "
            f"emotion={market.get('emotion_phase', 'unknown')} "
            f"breadth={_fmt_pct(market.get('breadth_up_pct'))} "
            f"涨停={_fmt_num(market.get('limit_up_count'))} "
            f"炸板={_fmt_num(market.get('broken_limit_up_count'))} "
            f"首板={_fmt_num(market.get('first_limit_up_count'))} "
            f"高度={_fmt_num(market.get('highest_continuous_board'))}"
        ),
        "",
        "候选行业集中度:",
        (
            f"- state={concentration.get('state', 'unknown')} "
            f"top_share={_fmt_pct(concentration.get('top_industry_share_pct'))} "
            f"HHI={_fmt_num(concentration.get('hhi'))}"
        ),
        "",
        "候选摘要:",
        f"- rows={_fmt_num(len(candidates))} labels={_fmt_counter(label_counts)}",
        f"- top_wounds={_fmt_wound_counter(wound_counts, limit=3)}",
    ]

    lines.extend(
        _format_daily_package_handoff(
            daily_package,
            owner_brief_payload=payload,
            intraday_manifest_payload=intraday_manifest,
            intraday_alert=intraday_alert,
        )
    )
    lines.extend(["", "盘中EOD复盘:"])
    lines.extend(_format_compact_intraday_eod_review(intraday_eod_review_queue))
    lines.extend(_format_compact_intraday_eod_outcome_review(intraday_eod_outcome_review))
    lines.extend(_format_environment_conditioned_diagnostics(daily_package))
    lines.extend(_format_shortest_legal_next_open_horizon(daily_package))
    lines.extend(_format_long_window_route_counts(payload))
    lines.extend(_format_long_window_route_examples(payload))
    lines.extend(_format_cross_horizon_consensus(payload))
    lines.extend(
        _format_forward_shadow_track_record(
            daily_package,
            track_record=forward_shadow_track_record,
        )
    )
    lines.extend(_format_explosive_posture(payload))
    lines.extend(
        _format_owner_review_truth_units(
            owner_review_truth_units,
            limit=min(candidate_limit, 4),
        )
    )
    lines.extend(
        _format_hypothesis_scout_readout(
            hypothesis_scout_readout,
            limit=min(candidate_limit, 2),
        )
    )
    lines.extend(_format_weak_signal_queue(payload, limit=min(candidate_limit, 5)))
    lines.extend(_format_cross_horizon_clusters(payload, limit=3))

    top_industries = concentration.get("top_industries")
    if isinstance(top_industries, list):
        for item in top_industries[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('industry_name', 'unknown')}: "
                f"{_fmt_num(item.get('candidate_count'))} "
                f"({_fmt_pct(item.get('candidate_share_pct'))})"
            )

    lines.extend(["", f"明天值得看 Top {min(candidate_limit, len(candidates))}:"])
    for item in candidates[:candidate_limit]:
        if not isinstance(item, dict):
            continue
        support = item.get("tactic_support")
        if not isinstance(support, dict):
            support = {}
        net = support.get("net_excess_pct")
        net_text = _fmt_pct(net) if net is not None else "None"
        wounds = item.get("evidence_wounds")
        wound_count = len(wounds) if isinstance(wounds, list) else 0
        right_tail_cluster = _fmt_right_tail_cluster_membership(item)
        lines.append(
            f"- #{_fmt_num(item.get('review_rank'))} "
            f"{item.get('symbol', 'unknown')} {item.get('stock_name', '')} "
            f"[{item.get('industry_name', 'unknown')}] "
            f"{item.get('tactic_name', item.get('tactic_id', 'unknown'))} "
            f"证据层={_evidence_tier_label(item.get('evidence_tier'))} "
            f"label={item.get('owner_confidence_label', 'unknown')} "
            f"gross={_fmt_pct(support.get('gross_excess_pct'))} "
            f"net={net_text} "
            f"baseline={support.get('baseline_scope', 'unknown')} "
            f"cost={_fmt_pct(support.get('cost_total_pct'))} "
            f"ci={_fmt_ci(support.get('date_block_ci_lower_pct'), support.get('date_block_ci_upper_pct'))} "
            f"tail5={_fmt_pct(support.get('right_tail_return_ge_5pct_share_pct'))} "
            f"p90={_fmt_pct(support.get('right_tail_return_p90_pct'))} "
            f"next_close_net={_fmt_pct(support.get('next_open_close_net_excess_pct'))} "
            f"next_close_tail5={_fmt_pct(support.get('next_open_close_right_tail_return_ge_5pct_share_pct'))} "
            f"next_follow_net={_fmt_pct(support.get('next_open_following_close_net_excess_pct'))} "
            f"next_follow_tail5={_fmt_pct(support.get('next_open_following_close_right_tail_return_ge_5pct_share_pct'))} "
            f"{right_tail_cluster + ' ' if right_tail_cluster else ''}"
            f"n={_fmt_num(support.get('row_n'))}/days={_fmt_num(support.get('date_block_effective_n'))} "
            f"wounds={wound_count}"
        )

    if env_diag:
        lines.extend(
            [
                "",
                "环境条件化诊断:",
                (
                    f"- freshness={env_diag.get('freshness_status', 'unknown')} "
                    f"current_promising={_fmt_num(env_diag.get('current_promising_count'))} "
                    f"diagnostic_promising={_fmt_num(env_diag.get('diagnostic_promising_count'))}"
                ),
            ]
        )

    if base_rates:
        lines.extend(["", "封单/炸板基率:"])
        for item in base_rates[:4]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('context_state', 'unknown')}: "
                f"events={_fmt_num(item.get('event_n'))} "
                f"days={_fmt_num(item.get('date_count'))} "
                f"次日开到收={_fmt_pct(item.get('next_open_to_close_pct'))}"
            )

    lines.extend(
        [
            "",
            "禁止误读: rank不是edge; rows不是独立edge; 未行业中性; "
            "仍需cost/CI/FDR/holdout/forward-shadow; accepted_edges=0",
            f"artifact={report_path}",
        ]
    )
    return "\n".join(lines)


def format_kairos_intraday_alert(
    payload: dict[str, Any], *, candidate_limit: int = 12
) -> str:
    """Render the latest intraday owner alert as a compact mobile readout."""

    status = str(payload.get("status") or "UNKNOWN")
    as_of = payload.get("as_of_date") or "unknown"
    target = payload.get("target_trade_date") or "unknown"
    accepted_edges = payload.get("accepted_edges", 0)
    report_path = payload.get("report_path", "unknown")
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        snapshot = _as_dict(payload.get("realtime_snapshot_status"))
        blocker = _format_intraday_snapshot_blocker(
            snapshot=snapshot,
            alert=payload,
        )
        return "\n".join(
            [
                f"Kairos intraday={status}",
                f"report_path={report_path}",
                *([blocker] if blocker else []),
                *[f"error={item}" for item in errors[:4]],
                "boundary=read-only report; not advisory; accepted_edges=0",
            ]
        )

    snapshot = _as_dict(payload.get("realtime_snapshot_status"))
    market = _as_dict(payload.get("market_facts"))
    concentration = _as_dict(payload.get("industry_concentration"))
    setup = _as_dict(payload.get("setup_supply"))
    projection = _as_dict(payload.get("observation_projection_status"))
    source_counts = _as_dict(projection.get("candidate_source_counts"))
    candidates = _as_list(payload.get("candidate_alerts"))
    right_tail_supplements = [
        row
        for row in candidates
        if isinstance(row, dict)
        and row.get("intraday_alert_source") == "cross_horizon_right_tail_supplement"
    ]

    lines = [
        f"Kairos 盘中 alert={status}",
        f"as_of={as_of} target={target} accepted_edges={accepted_edges}",
        "boundary=report-only / 不是买卖建议 / 不是GO / 不是 validated edge",
        (
            f"snapshot={snapshot.get('status', 'unknown')} "
            f"rows={_fmt_num(snapshot.get('row_count'))} "
            f"time={snapshot.get('snapshot_time', 'None')}"
        ),
        (
            f"market={market.get('market_regime', 'unknown')}/"
            f"{market.get('emotion_phase', 'unknown')} "
            f"涨停={_fmt_num(market.get('limit_up_count'))} "
            f"炸板={_fmt_num(market.get('broken_limit_up_count'))} "
            f"高度={_fmt_num(market.get('highest_continuous_board'))}"
        ),
        (
            f"industry={concentration.get('state', 'unknown')} "
            f"top_share={_fmt_pct(concentration.get('top_industry_share_pct'))}"
        ),
        (
            f"setup_supply={setup.get('state', 'unknown')} "
            f"watchlist={_fmt_num(setup.get('stock_watchlist_count'))} "
            f"sealed={_fmt_num(setup.get('sealed_no_break_watchlist_count'))}"
        ),
        (
            f"alert_sources topn={_fmt_num(source_counts.get('topn_owner_review'))} "
            f"right_tail_supp={_fmt_num(source_counts.get('cross_horizon_right_tail_supplement'))} "
            f"clusters={_fmt_num(projection.get('cross_horizon_right_tail_cluster_count'))}"
        ),
        "",
        "时间窗:",
    ]
    for row in _as_list(payload.get("session_windows")):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('time_cst')} {row.get('window_id')}: "
            f"{row.get('owner_use')} ({row.get('trust_level')})"
        )

    trigger_lines = _format_intraday_triggered_rows(payload)
    if trigger_lines:
        lines.extend(["", "盘中已触发:"])
        lines.extend(trigger_lines)

    lines.extend(["", f"盘中候选 Top {min(candidate_limit, len(candidates))}:"])
    for row in candidates[:candidate_limit]:
        if not isinstance(row, dict):
            continue
        checkpoints = {
            str(item.get("window_id")): item
            for item in _as_list(row.get("runtime_checkpoints"))
            if isinstance(item, dict)
        }
        support = _as_dict(row.get("support_snapshot"))
        cluster = _as_dict(row.get("cross_horizon_right_tail_cluster"))
        lines.append(
            f"- #{_fmt_num(row.get('rank'))} "
            f"{row.get('symbol', 'unknown')} {row.get('stock_name', '')} "
            f"[{row.get('industry_name', 'unknown')}] "
            f"{row.get('tactic_id', 'unknown')} "
            f"source={row.get('intraday_alert_source', 'unknown')} "
            f"cluster={cluster.get('cluster_key', '')} "
            f"label={row.get('owner_confidence_label', 'unknown')} "
            f"net={_fmt_pct(support.get('net_excess_pct'))} "
            f"tail5={_fmt_pct(support.get('right_tail_return_ge_5pct_share_pct'))} "
            f"open={_as_dict(checkpoints.get('opening_print_0926')).get('trigger_status')} "
            f"5m={_as_dict(checkpoints.get('first5m_preliminary_0936')).get('trigger_status')} "
            f"30m={_as_dict(checkpoints.get('first30m_confirmation_1001')).get('trigger_status')} "
            f"wounds={len(_as_list(row.get('evidence_wounds')))}"
        )

    if right_tail_supplements:
        lines.extend(
            [
                "",
                f"右尾补充候选 Top {min(5, len(right_tail_supplements))}:",
                "- boundary=cluster是相关setup,不是独立股票edge; 只做盘中观察补充",
            ]
        )
        for row in right_tail_supplements[:5]:
            support = _as_dict(row.get("support_snapshot"))
            cluster = _as_dict(row.get("cross_horizon_right_tail_cluster"))
            lines.append(
                f"- #{_fmt_num(row.get('rank'))} "
                f"{row.get('symbol', 'unknown')} {row.get('stock_name', '')} "
                f"[{row.get('industry_name', 'unknown')}] "
                f"{row.get('tactic_id', 'unknown')} "
                f"cluster={cluster.get('cluster_key', 'unknown')} "
                f"net={_fmt_pct(support.get('net_excess_pct'))} "
                f"tail5={_fmt_pct(support.get('right_tail_return_ge_5pct_share_pct'))} "
                f"wounds={len(_as_list(row.get('evidence_wounds')))}"
            )

    lines.extend(
        [
            "",
            "禁止误读: pending=没有实时快照; stale不许推断; 一字/涨停开不暗示可成交; "
            "alert不是买卖指令; accepted_edges=0",
            f"artifact={report_path}",
        ]
    )
    return "\n".join(lines)


def format_kairos_today_readout(payload: dict[str, Any]) -> str:
    status = str(payload.get("run_status") or "UNKNOWN").upper()
    summary = payload.get("owner_summary")
    if not isinstance(summary, dict):
        summary = {}
    authority = payload.get("authority")
    if not isinstance(authority, dict):
        authority = {}

    def _items(name: str) -> list[str]:
        value = summary.get(name)
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    blocked = _items("blocked_sections")
    warn = _items("warn_sections")
    no_trade = _items("no_trade_reasons")
    leads = _items("report_only_leads")
    advisory_ready = bool(summary.get("advisory_ready"))
    authority_state = str(summary.get("authority_state") or "unknown")

    lines = [
        f"Kairos readiness={status}",
        f"report_path={payload.get('report_path', 'unknown')}",
        f"authority_state={authority_state}",
        f"authority_delta={authority.get('authority_delta', 'none')}",
        f"advisory_ready={str(advisory_ready).lower()}",
        f"owner_action={summary.get('owner_action', 'unknown')}",
        f"freshness={summary.get('freshness_statement', 'unknown')}",
        "blocked_sections=" + (", ".join(blocked) if blocked else "none"),
        "warn_sections=" + (", ".join(warn) if warn else "none"),
    ]
    if no_trade:
        lines.append("no_trade_reasons:")
        lines.extend(f"- {item}" for item in no_trade)
    if leads:
        lines.append("report_only_leads:")
        lines.extend(f"- {item}" for item in leads)
    lines.append("boundary=read-only report; not an advisory packet")
    return "\n".join(lines)


__all__ = [
    "ARCHIVE_DATE_RE",
    "default_kairos_forward_shadow_track_record_path",
    "default_kairos_hypothesis_scout_readout_path",
    "default_kairos_intraday_candidate_manifest_path",
    "default_kairos_intraday_alert_path",
    "default_kairos_intraday_eod_outcome_review_path",
    "default_kairos_intraday_eod_review_queue_path",
    "default_kairos_owner_daily_archive_root",
    "default_kairos_owner_feedback_route_intake_path",
    "default_kairos_owner_review_truth_units_path",
    "default_kairos_owner_daily_package_path",
    "default_kairos_owner_brief_path",
    "default_kairos_readout_path",
    "format_kairos_owner_daily_archive_dates",
    "format_kairos_intraday_alert",
    "format_kairos_owner_brief",
    "format_kairos_owner_brief_compact",
    "format_kairos_today_readout",
    "kairos_owner_daily_archive_paths",
    "list_kairos_owner_daily_archive_days",
    "list_kairos_owner_daily_archive_dates",
    "load_kairos_forward_shadow_track_record",
    "load_kairos_hypothesis_scout_readout",
    "load_kairos_intraday_candidate_manifest",
    "load_kairos_intraday_alert",
    "load_kairos_intraday_eod_outcome_review",
    "load_kairos_intraday_eod_review_queue",
    "load_kairos_owner_daily_archive",
    "load_kairos_owner_feedback_route_intake",
    "load_kairos_owner_review_truth_units",
    "load_kairos_owner_daily_package",
    "load_kairos_owner_brief",
    "load_kairos_today_readout",
]
