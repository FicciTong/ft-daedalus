from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.cli import main
from daedalus_wechat.daemon import BridgeDaemon
from daedalus_wechat.kairos_readout import (
    format_kairos_today_readout,
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
