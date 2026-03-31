from __future__ import annotations

import json
import tempfile
from pathlib import Path

from daedalus_wechat.config import BridgeConfig
from daedalus_wechat.security_drill import run_security_drill


def _make_config(tmpdir: Path, allowed_users: frozenset[str]) -> BridgeConfig:
    return BridgeConfig(
        codex_bin="codex",
        account_file=tmpdir / "account.json",
        state_dir=tmpdir / "state",
        default_cwd=Path("/tmp"),
        openclaw_profile="daedalus-wechat",
        canonical_tmux_session="codex",
        allowed_users=allowed_users,
        progress_updates_default=False,
        codex_state_db=tmpdir / ".codex" / "state.sqlite",
    )


def test_security_drill_succeeds_when_allowlist_present() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = _make_config(root, frozenset({"allowed-user@im.wechat"}))
        cfg.codex_state_db.parent.mkdir(parents=True, exist_ok=True)
        cfg.codex_state_db.write_text("", encoding="utf-8")
        report_path = root / "drill.json"

        result = run_security_drill(config=cfg, report_path=report_path)

        assert result.status == "SUCCESS"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["allowlist_configured"] is True
        assert payload["codex_state_db_source"] == "default_resolved"
        assert payload["unauthorized_sender_blocked_before_bind"] is True
        assert payload["unauthorized_sender_did_not_submit_prompt"] is True
        assert payload["unauthorized_sender_received_denial_reply"] is True


def test_security_drill_warns_when_allowlist_missing_but_still_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = _make_config(root, frozenset())
        report_path = root / "drill.json"

        result = run_security_drill(config=cfg, report_path=report_path)

        assert result.status == "WARN"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["allowlist_configured"] is False
        assert payload["unauthorized_sender_blocked_before_bind"] is True


def test_security_drill_warns_when_state_db_is_default_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = BridgeConfig(
            codex_bin="codex",
            account_file=root / "account.json",
            state_dir=root / "state",
            default_cwd=Path("/tmp"),
            openclaw_profile="daedalus-wechat",
            canonical_tmux_session="codex",
            allowed_users=frozenset({"allowed-user@im.wechat"}),
            progress_updates_default=False,
            codex_state_db=root / ".codex" / "state_7.sqlite",
            codex_state_db_source="default_resolved",
        )
        cfg.codex_state_db.parent.mkdir(parents=True, exist_ok=True)
        cfg.codex_state_db.write_text("", encoding="utf-8")
        report_path = root / "drill.json"

        result = run_security_drill(config=cfg, report_path=report_path)

        assert result.status == "WARN"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["codex_state_db_resolution"] == "fallback_matching_state_sqlite"
        assert any("default fallback" in note for note in payload["notes"])


def test_security_drill_does_not_touch_live_state_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = _make_config(root, frozenset({"allowed-user@im.wechat"}))
        cfg.codex_state_db.parent.mkdir(parents=True, exist_ok=True)
        cfg.codex_state_db.write_text("", encoding="utf-8")
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        live_state = {
            "active_session_id": None,
            "active_tmux_session": None,
            "get_updates_buf": "live-buf-1",
            "bound_user_id": "allowed-user@im.wechat",
            "bound_context_token": "ctx-live",
            "progress_updates_enabled": True,
            "delivery_seq": 0,
            "outbox_waiting_for_bind": False,
            "mirror_offsets": {},
            "last_progress_summaries": {},
            "pending_outbox": [],
            "pending_outbox_overflow_dropped": 0,
            "sessions": {},
        }
        cfg.state_file.write_text(
            json.dumps(live_state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        result = run_security_drill(config=cfg, report_path=root / "drill.json")

        assert result.status == "SUCCESS"
        persisted = json.loads(cfg.state_file.read_text(encoding="utf-8"))
        assert persisted["get_updates_buf"] == "live-buf-1"
        assert persisted["bound_user_id"] == "allowed-user@im.wechat"
