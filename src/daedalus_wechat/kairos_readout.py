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
    "default_kairos_readout_path",
    "format_kairos_today_readout",
    "load_kairos_today_readout",
]
