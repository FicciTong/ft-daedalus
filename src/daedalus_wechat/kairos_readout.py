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


def _fmt_ci(lower: Any, upper: Any) -> str:
    if lower is None and upper is None:
        return "[None,None]"
    return f"[{_fmt_pct(lower)},{_fmt_pct(upper)}]"


def _fmt_counter(counter: Counter[str], *, limit: int = 4) -> str:
    parts = [
        f"{name}={_fmt_num(count)}"
        for name, count in counter.most_common(limit)
    ]
    return " ".join(parts) if parts else "none"


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


def _format_forward_shadow_track_record(
    package: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(package, dict):
        return []
    track = _as_dict(package.get("forward_shadow_track_record"))
    if not track:
        return []
    return [
        "",
        "Forward-shadow闭环:",
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
        "- boundary=frozen candidate track record; pending is not failed trade, not negative edge",
    ]


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
        first_wound = wounds[0] if wounds else "none"
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
        f"- top_wounds={_fmt_counter(wound_counts, limit=3)}",
    ]

    lines.extend(_format_daily_package_handoff(daily_package))
    lines.extend(_format_environment_conditioned_diagnostics(daily_package))
    lines.extend(_format_shortest_legal_next_open_horizon(daily_package))
    lines.extend(_format_forward_shadow_track_record(daily_package))
    lines.extend(_format_explosive_posture(payload))
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
