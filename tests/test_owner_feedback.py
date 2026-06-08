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
    projection = summary["research_route_projection"]
    assert projection["route_item_count"] == 3
    assert projection["route_counts"] == {
        "noise_review_backlog": 1,
        "owner_attention_research_prior": 1,
        "owner_watchlist_research_prior": 1,
    }
    assert projection["accepted_edges"] == 0
    assert projection["recent_route_items"][-1]["route"] == (
        "owner_watchlist_research_prior"
    )
    assert projection["recent_route_items"][-1]["firewall"][
        "evidence_gate_mutation_allowed"
    ] is False
    text = format_owner_feedback_summary(summary)
    assert "已记录=3" in text
    assert "useful=1" in text
    assert "noise=1" in text
    assert "watch=1" in text
    assert "待路由=3" in text
    assert "噪音复盘=1" in text
    assert "最新路由=watch->owner_watchlist_research_prior:C" in text
    assert "不改证据门/排名/候选提升" in text


def test_owner_feedback_routes_write_card_and_surface_blocker(tmp_path: Path) -> None:
    ledger = tmp_path / "owner_feedback.jsonl"
    append_owner_feedback(
        mark="写卡",
        text="洗盘突破需要做成机器可测 pattern",
        source="test",
        ledger_path=ledger,
    )
    append_owner_feedback(
        mark="数据缺口",
        text="利尔达负面事件 wound 要接进候选行",
        source="test",
        ledger_path=ledger,
    )
    append_owner_feedback(
        mark="复核",
        text="强势股股性过滤请 review",
        source="test",
        ledger_path=ledger,
    )

    summary = load_owner_feedback_summary(ledger)
    projection = summary["research_route_projection"]

    assert projection["route_counts"] == {
        "peer_review_backlog": 1,
        "research_card_draft_backlog": 1,
        "surface_blocker_triage": 1,
    }
    assert "must not mutate evidence gates" in projection["claim_boundary"]
    text = format_owner_feedback_summary(summary)
    assert "写卡=1" in text
    assert "数据缺口=1" in text
    assert "复核=1" in text


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
