from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from daedalus_wechat.cli import _send_bound_text
from daedalus_wechat.config import BridgeConfig
from daedalus_wechat.state import BridgeState


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
            openclaw_profile="daedalus-wechat",
            canonical_tmux_session="codex",
            allowed_users=frozenset(),
            progress_updates_default=False,
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
            ledger_lines = (Path(tmpdir) / "deliveries.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(ledger_lines), 1)
            delivery = json.loads(ledger_lines[0])
            self.assertEqual(delivery["seq"], 1)
            self.assertEqual(delivery["status"], "sent")
            self.assertEqual(delivery["kind"], "relay")

    def test_send_bound_text_requires_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(RuntimeError, "No bound WeChat chat context"):
                _send_bound_text(
                    self._make_config(Path(tmpdir)),
                    BridgeState(),
                    "hello",
                    client=_FakeWeChat(),
                )

    def test_send_bound_text_reports_failure_without_writing_state(self) -> None:
        """When send fails, CLI should NOT enqueue to shared state file
        (that races the daemon). It should report failure in the event log
        and ledger only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
            )
            rc = _send_bound_text(
                self._make_config(Path(tmpdir)),
                state,
                "hello failed chat",
                client=_FailingWeChat(),
            )
            self.assertEqual(rc, 0)
            # No pending outbox enqueue — avoids daemon state race
            self.assertEqual(len(state.pending_outbox), 0)
            lines = (Path(tmpdir) / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            event = json.loads(lines[0])
            self.assertEqual(event["kind"], "relay_failed")
            ledger_lines = (Path(tmpdir) / "deliveries.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(ledger_lines), 1)
            delivery = json.loads(ledger_lines[0])
            self.assertEqual(delivery["status"], "failed")
            self.assertEqual(delivery["kind"], "relay")
            # Verify state file was NOT written by the CLI
            state_file = Path(tmpdir) / "state.json"
            self.assertFalse(state_file.exists())

    def test_send_bound_text_advances_seq_from_existing_ledger_when_state_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "deliveries.jsonl").write_text(
                json.dumps(
                    {
                        "seq": 5,
                        "ts": "2026-04-01T00:00:00+00:00",
                        "to": "user@im.wechat",
                        "status": "sent",
                        "kind": "relay",
                        "origin": "desktop-direct",
                        "thread": None,
                        "tmux_session": None,
                        "text": "older",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                delivery_seq=1,
            )
            fake_wechat = _FakeWeChat()
            rc = _send_bound_text(
                self._make_config(tmp_path),
                state,
                "hello after stale seq",
                client=fake_wechat,
            )
            self.assertEqual(rc, 0)
            ledger_lines = (tmp_path / "deliveries.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(ledger_lines), 2)
            latest = json.loads(ledger_lines[-1])
            self.assertEqual(latest["seq"], 6)
            self.assertEqual(latest["status"], "sent")


if __name__ == "__main__":
    unittest.main()
