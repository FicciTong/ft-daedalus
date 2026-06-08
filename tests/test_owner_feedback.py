from __future__ import annotations

import json
from pathlib import Path

from daedalus_wechat.cli import main
from daedalus_wechat.owner_feedback import (
    append_owner_feedback,
    feedback_help_text,
    format_owner_feedback_summary,
    handle_owner_feedback_command,
    load_owner_feedback_summary,
    normalize_mark,
)


def test_owner_feedback_appends_firewalled_jsonl(tmp_path: Path) -> None:
    ledger = tmp_path / "owner_feedback.jsonl"

    entry = append_owner_feedback(
        mark="有用",
        text="300319 高开后前30分钟承接值得继续观察",
        source="test",
        ledger_path=ledger,
        captured_at_utc="2026-06-08T07:00:00Z",
    )

    assert entry["mark"] == "useful"
    assert entry["accepted_edges"] == 0
    assert entry["firewall"]["evidence_gate_mutation_allowed"] is False
    assert entry["firewall"]["ranking_mutation_allowed"] is False
    assert entry["firewall"]["trading_authority_allowed"] is False
    payload = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert payload["feedback_id"] == entry["feedback_id"]
    assert payload["route_scope"] == [
        "research_queue_direction_only",
        "owner_review_attention_only",
    ]


def test_owner_feedback_summary_counts_marks(tmp_path: Path) -> None:
    ledger = tmp_path / "owner_feedback.jsonl"
    append_owner_feedback(mark="useful", text="A", source="test", ledger_path=ledger)
    append_owner_feedback(mark="noise", text="B", source="test", ledger_path=ledger)
    append_owner_feedback(mark="观察", text="C", source="test", ledger_path=ledger)

    summary = load_owner_feedback_summary(ledger)

    assert summary["feedback_count"] == 3
    assert summary["mark_counts"] == {"noise": 1, "useful": 1, "watch": 1}
    assert summary["accepted_edges"] == 0
    assert summary["firewall"]["candidate_promotion_allowed"] is False
    text = format_owner_feedback_summary(summary)
    assert "已记录=3" in text
    assert "useful=1" in text
    assert "noise=1" in text
    assert "watch=1" in text
    assert "不改证据门/排名" in text


def test_owner_feedback_command_records_and_blocks_unknown_mark(tmp_path: Path) -> None:
    ledger = tmp_path / "owner_feedback.jsonl"

    recorded = handle_owner_feedback_command(
        "写卡 洗盘突破需要转成 selection policy",
        source="test-command",
        ledger_path=ledger,
    )
    blocked = handle_owner_feedback_command(
        "random 洗盘突破",
        source="test-command",
        ledger_path=ledger,
    )
    status = handle_owner_feedback_command(
        "status",
        source="test-command",
        ledger_path=ledger,
    )

    assert "feedback=recorded" in recorded
    assert "mark=write_card" in recorded
    assert "feedback=blocked" in blocked
    assert feedback_help_text() in blocked
    assert "已记录=1" in status


def test_owner_feedback_mark_aliases_are_explicit() -> None:
    assert normalize_mark("有意思") == "useful"
    assert normalize_mark("噪音") == "noise"
    assert normalize_mark("复核") == "needs_review"
    assert normalize_mark("unknown") is None


def test_owner_feedback_cli_writes_requested_ledger(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    ledger = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(
        "sys.argv",
        [
            "daedalus-wechat",
            "feedback",
            "--path",
            str(ledger),
            "有用",
            "300319 高开承接值得继续观察",
        ],
    )

    assert main() == 0

    out = capsys.readouterr().out
    assert "feedback=recorded" in out
    assert "mark=useful" in out
    payload = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert payload["text"] == "300319 高开承接值得继续观察"
    assert payload["firewall"]["ranking_mutation_allowed"] is False
