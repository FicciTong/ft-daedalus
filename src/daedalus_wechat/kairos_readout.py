from __future__ import annotations

import json
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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _format_daily_package_handoff(package: dict[str, Any] | None) -> list[str]:
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
    intraday_manifest = _as_dict(package.get("intraday_candidate_manifest"))
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
            f"rows={_fmt_num(owner_brief.get('owner_review_candidate_count'))}"
        ),
        (
            f"- intraday_manifest={intraday_manifest.get('source_status', 'unknown')} "
            f"rows={_fmt_num(intraday_manifest.get('candidate_count'))} "
            f"symbols={_fmt_num(intraday_manifest.get('unique_symbol_count'))} "
            f"windows={_fmt_num(intraday_manifest.get('collection_window_count'))} "
            f"edge_runtime={edge_contract.get('edge_runtime', 'unknown')}"
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
    lines.append(f"- package_artifact={report_path}")
    return lines


def format_kairos_owner_brief(
    payload: dict[str, Any],
    *,
    candidate_limit: int = 12,
    daily_package: dict[str, Any] | None = None,
) -> str:
    """Render the latest owner review brief as a compact mobile readout."""

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
    ]

    lines.extend(_format_daily_package_handoff(daily_package))

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
        return "\n".join(
            [
                f"Kairos intraday={status}",
                f"report_path={report_path}",
                *[f"error={item}" for item in errors[:4]],
                "boundary=read-only report; not advisory; accepted_edges=0",
            ]
        )

    snapshot = _as_dict(payload.get("realtime_snapshot_status"))
    market = _as_dict(payload.get("market_facts"))
    concentration = _as_dict(payload.get("industry_concentration"))
    setup = _as_dict(payload.get("setup_supply"))
    candidates = _as_list(payload.get("candidate_alerts"))

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
        lines.append(
            f"- #{_fmt_num(row.get('rank'))} "
            f"{row.get('symbol', 'unknown')} {row.get('stock_name', '')} "
            f"[{row.get('industry_name', 'unknown')}] "
            f"{row.get('tactic_id', 'unknown')} "
            f"label={row.get('owner_confidence_label', 'unknown')} "
            f"net={_fmt_pct(support.get('net_excess_pct'))} "
            f"tail5={_fmt_pct(support.get('right_tail_return_ge_5pct_share_pct'))} "
            f"open={_as_dict(checkpoints.get('opening_print_0926')).get('trigger_status')} "
            f"5m={_as_dict(checkpoints.get('first5m_preliminary_0936')).get('trigger_status')} "
            f"30m={_as_dict(checkpoints.get('first30m_confirmation_1001')).get('trigger_status')} "
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
    "default_kairos_intraday_alert_path",
    "default_kairos_owner_daily_package_path",
    "default_kairos_owner_brief_path",
    "default_kairos_readout_path",
    "format_kairos_intraday_alert",
    "format_kairos_owner_brief",
    "format_kairos_today_readout",
    "load_kairos_intraday_alert",
    "load_kairos_owner_daily_package",
    "load_kairos_owner_brief",
    "load_kairos_today_readout",
]
