from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_wechat_bridge.cli import _send_bound_text
from codex_wechat_bridge.config import BridgeConfig
from codex_wechat_bridge.state import BridgeState


class _FakeWeChat:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None, str]] = []

    def send_text(self, *, to_user_id: str, context_token: str | None, text: str):
        self.sent.append((to_user_id, context_token, text))
        return {}


class _FailingWeChat:
    def send_text(self, *, to_user_id: str, context_token: str | None, text: str):
        raise RuntimeError("ret=-2")


class CliTests(unittest.TestCase):
    def _make_config(self, state_dir: Path) -> BridgeConfig:
        return BridgeConfig(
            codex_bin="codex",
            account_file=state_dir / "account.json",
            state_dir=state_dir,
            default_cwd=Path("/tmp"),
            openclaw_profile="codex-wechat-bridge",
            canonical_tmux_session="codex",
            allowed_users=frozenset(),
            progress_updates_default=True,
        )

    def test_send_bound_text_uses_current_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
            )
            fake_wechat = _FakeWeChat()
            rc = _send_bound_text(
                self._make_config(Path(tmpdir)),
                state,
                "hello bound chat",
                client=fake_wechat,
            )
            self.assertEqual(rc, 0)
            self.assertEqual(
                fake_wechat.sent,
                [("user@im.wechat", "ctx-1", "hello bound chat")],
            )
            lines = (Path(tmpdir) / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            event = json.loads(lines[0])
            self.assertEqual(event["kind"], "relay_outgoing")
            self.assertEqual(event["payload"]["to"], "user@im.wechat")
            self.assertEqual(event["payload"]["text"], "hello bound chat")

    def test_send_bound_text_requires_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(RuntimeError, "No bound WeChat chat context"):
                _send_bound_text(
                    self._make_config(Path(tmpdir)),
                    BridgeState(),
                    "hello",
                    client=_FakeWeChat(),
                )

    def test_send_bound_text_queues_when_send_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
            )
            rc = _send_bound_text(
                self._make_config(Path(tmpdir)),
                state,
                "hello queued chat",
                client=_FailingWeChat(),
            )
            self.assertEqual(rc, 0)
            self.assertEqual(len(state.pending_outbox), 1)
            self.assertEqual(state.pending_outbox[0]["to"], "user@im.wechat")
            self.assertEqual(state.pending_outbox[0]["text"], "hello queued chat")
            lines = (Path(tmpdir) / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            event = json.loads(lines[0])
            self.assertEqual(event["kind"], "relay_queued")


if __name__ == "__main__":
    unittest.main()
