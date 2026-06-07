from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.cli import main
from daedalus_wechat.daemon import BridgeDaemon
from daedalus_wechat.kairos_readout import (
    format_kairos_intraday_alert,
    format_kairos_owner_brief,
    format_kairos_today_readout,
    load_kairos_intraday_alert,
    load_kairos_owner_brief,
    load_kairos_owner_daily_package,
    load_kairos_today_readout,
)


def _sample_payload() -> dict[str, object]:
    return {
        "run_status": "WARN",
        "owner_summary": {
            "advisory_ready": False,
            "authority_state": "report_only",
            "owner_action": "review framework blockers; no trading authority",
            "freshness_statement": "readout is generated from report-only builders",
            "blocked_sections": [],
            "warn_sections": ["canonical_surface", "source_bridge"],
            "no_trade_reasons": ["receipts missing"],
            "report_only_leads": ["canonical thin core exists"],
        },
        "authority": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "live_broker_allowed": False,
        },
    }


def _sample_owner_brief_payload() -> dict[str, object]:
    return {
        "status": "REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF",
        "as_of_date": "2026-06-05",
        "target_trade_date": "2026-06-08",
        "accepted_edges": 0,
        "market_facts": {
            "market_regime": "CHOPPY",
            "emotion_phase": "hot",
            "breadth_up_pct": 59.63,
            "limit_up_count": 88,
            "broken_limit_up_count": 63,
            "first_limit_up_count": 82,
            "highest_continuous_board": 5,
        },
        "industry_concentration": {
            "state": "HIGH_INDUSTRY_CONCENTRATION",
            "top_industry_share_pct": 51.16,
            "hhi": 0.3077,
            "top_industries": [
                {
                    "industry_name": "元器件",
                    "candidate_count": 22,
                    "candidate_share_pct": 51.16,
                }
            ],
        },
        "owner_review_candidates": [
            {
                "review_rank": 1,
                "symbol": "002251.SZ",
                "stock_name": "步步高",
                "industry_name": "超市连锁",
                "tactic_name": "高开后前30分钟承接",
                "owner_confidence_label": "可用参考",
                "evidence_wounds": ["not_industry_neutral_contains_sector_beta"],
                "tactic_support": {
                    "cost_total_pct": 0.272,
                    "date_block_ci_lower_pct": -0.5222,
                    "date_block_ci_upper_pct": 1.6045,
                    "gross_excess_pct": 1.2576,
                    "net_excess_pct": 0.9856,
                    "next_open_close_net_excess_pct": -0.0461,
                    "next_open_close_right_tail_return_ge_5pct_share_pct": 15.0757,
                    "next_open_following_close_net_excess_pct": 0.1271,
                    "next_open_following_close_right_tail_return_ge_5pct_share_pct": 25.1481,
                    "right_tail_return_ge_5pct_share_pct": 43.9801,
                    "right_tail_return_p90_pct": 19.4347,
                    "row_n": 1005,
                    "date_block_effective_n": 32,
                },
            }
        ],
        "environment_diagnostics": {
            "freshness_status": "STALE_FOR_PACKAGE_AS_OF",
            "current_promising_count": 0,
            "diagnostic_promising_count": 6,
        },
        "limit_board_base_rates": [
            {
                "context_state": "sealed_after_break",
                "event_n": 7134,
                "date_count": 811,
                "next_open_to_close_pct": 0.82,
            }
        ],
    }


def _sample_owner_daily_package_payload() -> dict[str, object]:
    return {
        "status": "REPORT_ONLY_SHORT_CYCLE_OWNER_DAILY_PACKAGE",
        "as_of_date": "2026-06-05",
        "target_trade_date": "2026-06-08",
        "accepted_edges": 0,
        "owner_review_brief": {
            "source_status": "REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF",
            "owner_review_candidate_count": 40,
            "source_markdown_path": "/tmp/short_cycle_owner_review_brief_latest.md",
        },
        "intraday_candidate_manifest": {
            "source_status": "REPORT_ONLY_SHORT_CYCLE_INTRADAY_CANDIDATE_MANIFEST",
            "candidate_count": 144,
            "unique_symbol_count": 41,
            "collection_window_count": 3,
            "source_markdown_path": "/tmp/short_cycle_intraday_candidate_manifest_latest.md",
            "edge_collection_contract": {
                "edge_runtime": "Windows ft-edge",
                "transport": "file handoff; no DB writes",
            },
            "collection_windows": [
                {
                    "time_cst": "09:26",
                    "window_id": "opening_print_0926",
                    "owner_use": "opening print observation",
                },
                {
                    "time_cst": "09:36",
                    "window_id": "first5m_preliminary_0936",
                    "owner_use": "first five minute observation",
                },
            ],
        },
    }


def _sample_intraday_alert_payload() -> dict[str, object]:
    return {
        "status": "REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT",
        "as_of_date": "2026-06-05",
        "target_trade_date": "2026-06-08",
        "accepted_edges": 0,
        "realtime_snapshot_status": {
            "status": "PENDING_REALTIME_SNAPSHOT",
            "message": "no realtime snapshot supplied",
            "row_count": 0,
        },
        "market_facts": {
            "market_regime": "CHOPPY",
            "emotion_phase": "hot",
            "limit_up_count": 88,
            "broken_limit_up_count": 63,
            "highest_continuous_board": 5,
        },
        "industry_concentration": {
            "state": "HIGH_INDUSTRY_CONCENTRATION",
            "top_industry_share_pct": 51.16,
        },
        "setup_supply": {
            "state": "MODERATE_SETUP_SUPPLY",
            "stock_watchlist_count": 20,
            "sealed_no_break_watchlist_count": 12,
        },
        "session_windows": [
            {
                "time_cst": "09:26",
                "window_id": "opening_print_0926",
                "owner_use": "read opening print",
                "trust_level": "high_if_snapshot_fresh",
            }
        ],
        "candidate_alerts": [
            {
                "rank": 1,
                "symbol": "002251.SZ",
                "stock_name": "步步高",
                "industry_name": "超市连锁",
                "tactic_id": "high_gap_first30m_hold",
                "owner_confidence_label": "可用参考",
                "evidence_wounds": ["row_level_fdr_holdout_not_available"],
                "support_snapshot": {
                    "net_excess_pct": 0.9856,
                    "right_tail_return_ge_5pct_share_pct": 43.98,
                },
                "runtime_checkpoints": [
                    {
                        "window_id": "opening_print_0926",
                        "trigger_status": "PENDING_REALTIME_SNAPSHOT",
                    },
                    {
                        "window_id": "first5m_preliminary_0936",
                        "trigger_status": "PENDING_REALTIME_SNAPSHOT",
                    },
                    {
                        "window_id": "first30m_confirmation_1001",
                        "trigger_status": "PENDING_REALTIME_SNAPSHOT",
                    },
                ],
            }
        ],
    }


def test_load_kairos_today_readout_reads_report(tmp_path: Path) -> None:
    report_path = tmp_path / "owner_readiness_readout_latest.json"
    report_path.write_text(
        json.dumps(_sample_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_today_readout(report_path)

    assert payload["run_status"] == "WARN"
    assert payload["report_path"] == str(report_path)
    assert payload["owner_summary"]["authority_state"] == "report_only"


def test_load_kairos_today_readout_missing_report_fails_closed(tmp_path: Path) -> None:
    report_path = tmp_path / "missing.json"

    payload = load_kairos_today_readout(report_path)

    assert payload["run_status"] == "MISSING"
    assert payload["owner_summary"]["advisory_ready"] is False
    assert payload["authority"]["authority_delta"] == "none"
    assert "owner_readiness_report" in payload["owner_summary"]["blocked_sections"]


def test_format_kairos_today_readout_keeps_report_only_boundary(tmp_path: Path) -> None:
    report_path = tmp_path / "owner_readiness_readout_latest.json"
    payload = _sample_payload()
    payload["report_path"] = str(report_path)

    text = format_kairos_today_readout(payload)

    assert "Kairos readiness=WARN" in text
    assert "authority_state=report_only" in text
    assert "advisory_ready=false" in text
    assert "boundary=read-only report; not an advisory packet" in text


def test_cli_kairos_today_does_not_require_bridge_state(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    report_path = tmp_path / "owner_readiness_readout_latest.json"
    report_path.write_text(
        json.dumps(_sample_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["daedalus-wechat", "kairos-today", "--report-path", str(report_path)],
    )

    rc = main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "Kairos readiness=WARN" in out
    assert "boundary=read-only report; not an advisory packet" in out


def test_daemon_kairos_today_command_is_read_only() -> None:
    with patch(
        "daedalus_wechat.daemon.load_kairos_today_readout",
        return_value=_sample_payload(),
    ):
        text = BridgeDaemon._handle_command(BridgeDaemon.__new__(BridgeDaemon), "/kairos-today")

    assert "Kairos readiness=WARN" in text
    assert "advisory_ready=false" in text


def test_load_kairos_owner_brief_reads_latest_report(tmp_path: Path) -> None:
    report_path = tmp_path / "short_cycle_owner_review_brief_latest.json"
    report_path.write_text(
        json.dumps(_sample_owner_brief_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_owner_brief(report_path)

    assert payload["status"] == "REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_load_kairos_owner_daily_package_reads_latest_report(tmp_path: Path) -> None:
    report_path = tmp_path / "short_cycle_owner_daily_package_latest.json"
    report_path.write_text(
        json.dumps(_sample_owner_daily_package_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_owner_daily_package(report_path)

    assert payload["status"] == "REPORT_ONLY_SHORT_CYCLE_OWNER_DAILY_PACKAGE"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_format_kairos_owner_brief_keeps_report_only_boundary(tmp_path: Path) -> None:
    payload = _sample_owner_brief_payload()
    payload["report_path"] = str(tmp_path / "brief.json")
    package = _sample_owner_daily_package_payload()
    package["report_path"] = str(tmp_path / "package.json")

    text = format_kairos_owner_brief(payload, daily_package=package)

    assert "Kairos 日包 brief=REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF" in text
    assert "accepted_edges=0" in text
    assert "不是买卖建议" in text
    assert "002251.SZ 步步高" in text
    assert "gross=1.26%" in text
    assert "net=0.99%" in text
    assert "cost=0.27%" in text
    assert "ci=[-0.52%,1.60%]" in text
    assert "tail5=43.98%" in text
    assert "p90=19.43%" in text
    assert "next_close_net=-0.05%" in text
    assert "next_close_tail5=15.08%" in text
    assert "next_follow_net=0.13%" in text
    assert "next_follow_tail5=25.15%" in text
    assert "HIGH_INDUSTRY_CONCENTRATION" in text
    assert "日包总入口" in text
    assert "intraday_manifest=REPORT_ONLY_SHORT_CYCLE_INTRADAY_CANDIDATE_MANIFEST" in text
    assert "rows=144 symbols=41 windows=3 edge_runtime=Windows ft-edge" in text
    assert "09:26 opening_print_0926" in text


def test_cli_brief_does_not_require_bridge_state(tmp_path: Path, capsys, monkeypatch) -> None:
    report_path = tmp_path / "short_cycle_owner_review_brief_latest.json"
    report_path.write_text(
        json.dumps(_sample_owner_brief_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["daedalus-wechat", "brief", "--report-path", str(report_path), "--limit", "1"],
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_owner_daily_package",
        lambda: _sample_owner_daily_package_payload(),
    )

    rc = main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "Kairos 日包 brief=REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF" in out
    assert "日包总入口" in out
    assert "002251.SZ 步步高" in out


def test_daemon_brief_command_is_read_only() -> None:
    with patch(
        "daedalus_wechat.daemon.load_kairos_owner_brief",
        return_value=_sample_owner_brief_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_owner_daily_package",
        return_value=_sample_owner_daily_package_payload(),
    ):
        text = BridgeDaemon._handle_command(BridgeDaemon.__new__(BridgeDaemon), "/brief")

    assert "Kairos 日包 brief=REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF" in text
    assert "accepted_edges=0" in text
    assert "intraday_manifest=REPORT_ONLY_SHORT_CYCLE_INTRADAY_CANDIDATE_MANIFEST" in text


def test_load_kairos_intraday_alert_reads_latest_report(tmp_path: Path) -> None:
    report_path = tmp_path / "short_cycle_intraday_owner_alert_latest.json"
    report_path.write_text(
        json.dumps(_sample_intraday_alert_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_intraday_alert(report_path)

    assert payload["status"] == "REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_format_kairos_intraday_alert_keeps_report_only_boundary(
    tmp_path: Path,
) -> None:
    payload = _sample_intraday_alert_payload()
    payload["report_path"] = str(tmp_path / "intraday.json")

    text = format_kairos_intraday_alert(payload)

    assert "Kairos 盘中 alert=REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT" in text
    assert "accepted_edges=0" in text
    assert "不是买卖建议" in text
    assert "不是GO" in text
    assert "002251.SZ 步步高" in text
    assert "PENDING_REALTIME_SNAPSHOT" in text


def test_cli_intraday_does_not_require_bridge_state(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    report_path = tmp_path / "short_cycle_intraday_owner_alert_latest.json"
    report_path.write_text(
        json.dumps(_sample_intraday_alert_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "daedalus-wechat",
            "intraday",
            "--report-path",
            str(report_path),
            "--limit",
            "1",
        ],
    )

    rc = main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "Kairos 盘中 alert=REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT" in out
    assert "002251.SZ 步步高" in out


def test_daemon_intraday_command_is_read_only() -> None:
    with patch(
        "daedalus_wechat.daemon.load_kairos_intraday_alert",
        return_value=_sample_intraday_alert_payload(),
    ):
        text = BridgeDaemon._handle_command(
            BridgeDaemon.__new__(BridgeDaemon),
            "/intraday",
        )

    assert "Kairos 盘中 alert=REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT" in text
    assert "accepted_edges=0" in text
