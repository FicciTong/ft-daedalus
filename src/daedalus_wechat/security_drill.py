from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import BridgeConfig, load_config
from .daemon import BridgeDaemon
from .state import BridgeState


@dataclass(frozen=True)
class SecurityDrillResult:
    status: str
    report_path: Path
    payload: dict[str, Any]


class _FakeWeChat:
    def __init__(self, incoming_user: str) -> None:
        self.sent: list[tuple[str | None, str | None, str]] = []
        self._responses = iter(
            [
                {
                    "get_updates_buf": "security-drill-buf-1",
                    "msgs": [
                        {
                            "from_user_id": incoming_user,
                            "context_token": "security-drill-ctx",
                            "message_id": "security-drill-msg-1",
                            "message_type": 1,
                            "item_list": [
                                {"type": 1, "text_item": {"text": "hello bridge"}}
                            ],
                        }
                    ],
                },
                KeyboardInterrupt(),
            ]
        )

    def get_updates(self, _buf: str):
        result = next(self._responses)
        if isinstance(result, BaseException):
            raise result
        return result

    def send_text(
        self,
        *,
        to_user_id: str | None,
        context_token: str | None,
        text: str,
    ) -> None:
        self.sent.append((to_user_id, context_token, text))


class _FakeRunner:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def sync_live_sessions(self, state: BridgeState):
        return []

    def try_live_session(self, _state: BridgeState):
        return None

    def current_runtime_status(self, **_kwargs):
        return type("RuntimeStatus", (), {"exists": False, "tmux_session": "codex"})()

    def require_live_session(self, _state: BridgeState):
        raise AssertionError("unauthorized drill must not reach require_live_session")

    def submit_prompt(self, *, record, prompt: str):
        self.submitted.append(prompt)
        raise AssertionError("unauthorized drill must not reach submit_prompt")


class _DrillDaemon(BridgeDaemon):
    def _start_mirror_thread(self) -> None:
        return None

    def _start_outbox_thread(self) -> None:
        return None


def run_security_drill(
    *,
    config: BridgeConfig | None = None,
    report_path: Path | None = None,
) -> SecurityDrillResult:
    cfg = config or load_config()
    repo_root = Path(__file__).resolve().parents[3]
    out_path = (
        report_path
        if report_path is not None
        else repo_root / "var" / "reports" / "bridge" / "daedalus_security_drill_latest.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    unauthorized_user = "unauthorized-user@im.wechat"
    with tempfile.TemporaryDirectory(prefix="daedalus-security-drill-") as tmpdir:
        drill_root = Path(tmpdir)
        drill_cfg = replace(
            cfg,
            state_dir=drill_root / "state",
            account_file=drill_root / "account.json",
        )
        state = BridgeState()
        runner = _FakeRunner()
        wechat = _FakeWeChat(incoming_user=unauthorized_user)
        daemon = _DrillDaemon(
            config=drill_cfg,
            wechat=wechat,
            runner=runner,
            state=state,
        )

        unauthorized_blocked = False
        try:
            daemon.run_forever()
        except KeyboardInterrupt:
            unauthorized_blocked = True

    allowlist_configured = bool(cfg.allowed_users)
    codex_state_db = cfg.codex_state_db
    state_db_source = str(getattr(cfg, "codex_state_db_source", "default_resolved") or "default_resolved")
    state_db_resolution = _codex_state_db_resolution(
        codex_state_db,
        source=state_db_source,
    )
    unauthorized_reply_seen = any("未被授权" in msg[2] for msg in wechat.sent)

    status = "SUCCESS"
    if not unauthorized_blocked or not unauthorized_reply_seen or runner.submitted:
        status = "FAIL"
    elif state_db_resolution == "fallback_matching_state_sqlite":
        status = "WARN"
    elif not allowlist_configured:
        status = "WARN"

    payload = {
        "contract": "daedalus.security_drill",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": status,
        "allowlist_configured": allowlist_configured,
        "allowed_user_count": len(cfg.allowed_users),
        "default_cwd": str(cfg.default_cwd),
        "codex_state_db": str(codex_state_db),
        "codex_state_db_source": state_db_source,
        "codex_state_db_exists": codex_state_db.exists(),
        "codex_state_db_resolution": state_db_resolution,
        "unauthorized_sender": unauthorized_user,
        "unauthorized_sender_blocked_before_bind": state.bound_user_id is None,
        "unauthorized_sender_did_not_submit_prompt": not runner.submitted,
        "unauthorized_sender_received_denial_reply": unauthorized_reply_seen,
        "notes": (
            [
                "allowlist is empty: bridge is fail-closed but not owner-usable until at least one sender is configured."
            ]
            if not allowlist_configured
            else (
                [
                    "codex state DB still resolves through default fallback; pin an explicit authority path before treating the drill as fully clean."
                ]
                if state_db_resolution == "fallback_matching_state_sqlite"
                else []
            )
        ),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return SecurityDrillResult(status=status, report_path=out_path, payload=payload)


def _codex_state_db_resolution(path: Path, *, source: str) -> str:
    if source in {"env_explicit", "env_file_explicit"}:
        return "configured_explicit_path"
    if path.name == "state.sqlite":
        return "canonical_state_sqlite"
    if path.name.startswith("state") and path.suffix == ".sqlite":
        return "fallback_matching_state_sqlite"
    return "configured_explicit_path"


__all__ = ["SecurityDrillResult", "run_security_drill"]
