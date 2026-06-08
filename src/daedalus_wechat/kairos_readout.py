from __future__ import annotations

import json
from collections import Counter
from json import JSONDecodeError
from pathlib import Path
from typing import Any


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
}


def _wound_label(wound: Any) -> str:
    name = str(wound)
    return WOUND_LABEL_ZH.get(name, name)


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
            f"status={alert.get('status', 'unknown')} "
            f"observed={_fmt_num(projection.get('observed_candidate_count'))} "
            f"pending={_fmt_num(projection.get('pending_candidate_count'))} "
            f"trigger={readiness.get('status', 'unknown')} "
            f"snapshot={snapshot.get('status', 'unknown')}"
        )
    ]
    if triggered:
        lines.append(f"盘中触发 Top {len(triggered)}:")
        for row, hits in triggered:
            windows = ",".join(str(hit.get("window_id")) for hit in hits)
            first30m = {
                str(hit.get("window_id")): hit for hit in hits
            }.get("first30m_confirmation_1001", {})
            lines.append(
                f"- #{_fmt_num(row.get('rank'))} "
                f"{row.get('symbol', 'unknown')} {row.get('stock_name', '')} "
                f"[{row.get('industry_name', 'unknown')}] "
                f"{row.get('tactic_id', 'unknown')} "
                f"windows={windows} "
                f"first30m={_fmt_ratio_pct(first30m.get('first30m_return_pct'))} "
                f"wounds={_fmt_wound_list(_as_list(row.get('evidence_wounds')), limit=2)}"
            )
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
    ]


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
    ]
    for row in top_rows[:limit]:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('hypothesis_id', 'unknown')} "
            f"horizon={row.get('horizon_id', 'unknown')} "
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
    forward_shadow_track_record: dict[str, Any] | None = None,
    hypothesis_scout_readout: dict[str, Any] | None = None,
    owner_review_truth_units: dict[str, Any] | None = None,
) -> str:
    """Render a short owner-visible daily brief for WeChat."""

    _ = intraday_manifest, forward_shadow_track_record

    if owner_review_truth_units is None:
        owner_review_truth_units = load_kairos_owner_review_truth_units()

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
    candidates = [
        item for item in _as_list(payload.get("owner_review_candidates"))
        if isinstance(item, dict)
    ]
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
            f"{market.get('market_regime', 'unknown')} "
            f"emotion={market.get('emotion_phase', 'unknown')} "
            f"breadth={_fmt_pct(market.get('breadth_up_pct'))} "
            f"涨停={_fmt_num(market.get('limit_up_count'))} "
            f"炸板={_fmt_num(market.get('broken_limit_up_count'))} "
            f"高度={_fmt_num(market.get('highest_continuous_board'))}"
        ),
        (
            "集中度: "
            f"{concentration.get('state', 'unknown')} "
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
    ]

    lines.extend(_format_compact_intraday_status(intraday_alert, limit=3))

    strategy_hints = _format_compact_strategy_hints(candidates)
    if strategy_hints:
        lines.append(strategy_hints)

    lines.append(f"明天重点 Top {min(candidate_limit, len(candidates))}:")
    for item in candidates[:candidate_limit]:
        support = _as_dict(item.get("tactic_support"))
        wounds = _fmt_wound_list(_as_list(item.get("evidence_wounds")), limit=2)
        lines.append(
            f"- #{_fmt_num(item.get('review_rank'))} "
            f"{item.get('symbol', 'unknown')} {item.get('stock_name', '')} "
            f"[{item.get('industry_name', 'unknown')}] "
            f"{item.get('tactic_name', item.get('tactic_id', 'unknown'))} "
            f"{item.get('owner_confidence_label', 'unknown')} "
            f"net={_fmt_pct(support.get('net_excess_pct'))} "
            f"tail5={_fmt_pct(support.get('right_tail_return_ge_5pct_share_pct'))} "
            f"n={_fmt_num(support.get('row_n'))}/days={_fmt_num(support.get('date_block_effective_n'))} "
            f"伤口={wounds}"
        )

    lines.extend(
        [
            (
                "研究队列: "
                f"truth_units={_fmt_num(truth_units.get('truth_unit_count'))} "
                f"strict={_fmt_num(_as_dict(truth_units.get('route_counts')).get('strict_candidate_review_only'))} "
                f"tail_watch={_fmt_num(_as_dict(truth_units.get('route_counts')).get('owner_review_tail_watch'))} "
                f"scout_cells={_fmt_num(scout_counts.get('scout_cell_count'))} "
                f"pending={_fmt_num(scout_counts.get('dispatchable_pending_run_cell_count'))} "
                f"done={_fmt_num(scout_counts.get('daywalk_report_materialized_cell_count'))}"
            ),
            (
                "证据覆盖: "
                f"windows={_fmt_num(truth_coverage.get('observed_window_count'))} "
                f"horizons={_fmt_num(truth_coverage.get('horizon_count'))} "
                f"multi_window_units={_fmt_num(truth_coverage.get('multi_window_truth_unit_count'))}"
            ),
            (
                "Scout重点: "
                f"{_fmt_named_counts(_as_list(scout_surface.get('top_families')), limit=2)}; "
                f"{_fmt_named_counts(_as_list(scout_surface.get('top_hypotheses')), limit=2)}"
            ),
        ]
    )
    scout_condition_hints = _format_compact_scout_condition_hints(scout_surface)
    if scout_condition_hints:
        lines.append(scout_condition_hints)

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
    forward_shadow_track_record: dict[str, Any] | None = None,
    hypothesis_scout_readout: dict[str, Any] | None = None,
    owner_review_truth_units: dict[str, Any] | None = None,
) -> str:
    """Render the latest owner review brief as a compact mobile readout."""

    if owner_review_truth_units is None:
        owner_review_truth_units = load_kairos_owner_review_truth_units()

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
        lines.append(
            f"- #{_fmt_num(item.get('review_rank'))} "
            f"{item.get('symbol', 'unknown')} {item.get('stock_name', '')} "
            f"[{item.get('industry_name', 'unknown')}] "
            f"{item.get('tactic_name', item.get('tactic_id', 'unknown'))} "
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
    "default_kairos_forward_shadow_track_record_path",
    "default_kairos_hypothesis_scout_readout_path",
    "default_kairos_intraday_candidate_manifest_path",
    "default_kairos_intraday_alert_path",
    "default_kairos_owner_review_truth_units_path",
    "default_kairos_owner_daily_package_path",
    "default_kairos_owner_brief_path",
    "default_kairos_readout_path",
    "format_kairos_intraday_alert",
    "format_kairos_owner_brief",
    "format_kairos_owner_brief_compact",
    "format_kairos_today_readout",
    "load_kairos_forward_shadow_track_record",
    "load_kairos_hypothesis_scout_readout",
    "load_kairos_intraday_candidate_manifest",
    "load_kairos_intraday_alert",
    "load_kairos_owner_review_truth_units",
    "load_kairos_owner_daily_package",
    "load_kairos_owner_brief",
    "load_kairos_today_readout",
]
