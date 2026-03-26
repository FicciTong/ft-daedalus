from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_wechat_bridge.config import BridgeConfig
from codex_wechat_bridge.daemon import BridgeDaemon
from codex_wechat_bridge.live_session import LiveRuntimeStatus
from codex_wechat_bridge.state import SessionRecord
from codex_wechat_bridge.state import BridgeState


class _FakeWeChat:
    def __init__(self) -> None:
        self.account = type("Account", (), {"account_id": "test-bot"})()
        self.sent: list[tuple[str, str | None, str]] = []

    def send_text(self, *, to_user_id: str, context_token: str | None, text: str):
        self.sent.append((to_user_id, context_token, text))
        return {}


class _FakeRunner:
    def __init__(self) -> None:
        self.rollout_sizes: dict[str, int] = {}
        self.finals: dict[tuple[str, int], tuple[str, int]] = {}
        self.progresses: dict[tuple[str, int], tuple[list[str], str, int]] = {}
        self.runtime_thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"

    def try_live_session(self, state: BridgeState):
        return None

    def current_runtime_status(self) -> LiveRuntimeStatus:
        return LiveRuntimeStatus(
            tmux_session="codex",
            exists=True,
            pane_command="node",
            thread_id=self.runtime_thread_id,
        )

    def attach_hint(self, record: SessionRecord) -> str:
        return "tmux attach -t codex"

    def rollout_size(self, thread_id: str) -> int:
        return self.rollout_sizes.get(thread_id, 0)

    def latest_final_since(self, *, thread_id: str, start_offset: int):
        value = self.finals.get((thread_id, start_offset))
        if value is None:
            from codex_wechat_bridge.live_session import FinalScan

            return FinalScan(final_text="", end_offset=start_offset)
        text, end_offset = value
        from codex_wechat_bridge.live_session import FinalScan

        return FinalScan(final_text=text, end_offset=end_offset)

    def latest_mirror_since(self, *, thread_id: str, start_offset: int):
        value = self.progresses.get((thread_id, start_offset))
        if value is None:
            value = self.finals.get((thread_id, start_offset))
            if value is None:
                from codex_wechat_bridge.live_session import MirrorScan

                return MirrorScan(progress_texts=[], final_text="", end_offset=start_offset)
            text, end_offset = value
            from codex_wechat_bridge.live_session import MirrorScan

            return MirrorScan(progress_texts=[], final_text=text, end_offset=end_offset)
        progress_texts, final_text, end_offset = value
        from codex_wechat_bridge.live_session import MirrorScan

        return MirrorScan(progress_texts=progress_texts, final_text=final_text, end_offset=end_offset)


class _TestDaemon(BridgeDaemon):
    def _start_mirror_thread(self) -> None:
        return None


class DaemonTests(unittest.TestCase):
    def _make_config(self, state_dir: Path, allowed_users: frozenset[str]) -> BridgeConfig:
        return BridgeConfig(
            codex_bin="codex",
            account_file=state_dir / "account.json",
            state_dir=state_dir,
            default_cwd=Path("/tmp"),
            openclaw_profile="codex-wechat-bridge",
            canonical_tmux_session="codex",
            allowed_users=allowed_users,
            progress_updates_default=True,
        )

    def test_authorized_sender_allowed_when_allowlist_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = BridgeDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            self.assertTrue(daemon._is_authorized_sender("any-user"))

    def test_authorized_sender_respects_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = BridgeDaemon(
                config=self._make_config(
                    Path(tmpdir), frozenset({"allowed-user@im.wechat"})
                ),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            self.assertTrue(daemon._is_authorized_sender("allowed-user@im.wechat"))
            self.assertFalse(daemon._is_authorized_sender("other-user@im.wechat"))

    def test_health_text_is_mobile_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                active_session_id="019cdfe5-fa14-74a3-aa31-5451128ea58d",
                sessions={},
            )
            fake_wechat = _FakeWeChat()
            daemon = BridgeDaemon(
                config=self._make_config(
                    Path(tmpdir), frozenset({"allowed-user@im.wechat"})
                ),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )
            text = daemon._health_text()
            self.assertIn("health=ok", text)
            self.assertIn("tmux=codex", text)
            self.assertIn("thread=019cdfe5", text)
            self.assertIn("wechat=test-bot", text)
            self.assertIn("access=locked:1", text)

    def test_status_text_is_mobile_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                active_session_id=thread_id,
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="attached-last",
                        cwd="/home/test/dev/ft-cosmos",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    )
                },
            )
            fake_wechat = _FakeWeChat()
            daemon = BridgeDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )
            text = daemon._status_text()
            self.assertIn("status=ok", text)
            self.assertIn("thread=019cdfe5", text)
            self.assertIn("label=attached-last", text)
            self.assertIn("tmux=codex", text)
            self.assertIn("attach=tmux attach -t codex", text)

    def test_bind_peer_syncs_current_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(active_session_id=thread_id, sessions={})
            runner = _FakeRunner()
            runner.rollout_sizes[thread_id] = 42
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            daemon._bind_peer("user@im.wechat", "ctx-1")
            self.assertEqual(state.get_mirror_offset(thread_id), 42)

    def test_notify_command_toggles_progress_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            self.assertEqual(daemon._notify_text("status"), "notify=progress+final")
            self.assertEqual(daemon._notify_text("on"), "notify=progress+final")
            self.assertTrue(daemon.state.progress_updates_enabled)
            self.assertEqual(daemon._notify_text("off"), "notify=final-only")
            self.assertFalse(daemon.state.progress_updates_enabled)

    def test_recent_replays_latest_outgoing_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            config.event_log_file.write_text(
                "\n".join(
                    [
                        '{"ts":"2026-03-26T05:00:00+00:00","kind":"outgoing","payload":{"to":"user@im.wechat","text":"progress one"}}',
                        '{"ts":"2026-03-26T05:00:01+00:00","kind":"relay_outgoing","payload":{"to":"user@im.wechat","text":"FINAL_OK"}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(bound_user_id="user@im.wechat"),
            )
            text = daemon._recent_text("2")
            self.assertIn("recent:", text)
            self.assertIn("progress one", text)
            self.assertIn("FINAL_OK", text)

    def test_mirror_desktop_final_back_to_wechat(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                active_session_id=thread_id,
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                mirror_offsets={thread_id: 100},
                sessions={},
            )
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            runner.finals[(thread_id, 100)] = ("DESKTOP_FINAL_OK", 150)
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            daemon._mirror_desktop_final_if_any()
            self.assertEqual(fake_wechat.sent[-1], ("user@im.wechat", "ctx-1", "DESKTOP_FINAL_OK"))
            self.assertEqual(state.get_mirror_offset(thread_id), 150)

    def test_mirror_progress_first_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                active_session_id=thread_id,
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                progress_updates_enabled=True,
                mirror_offsets={thread_id: 100},
                sessions={},
            )
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            runner.progresses[(thread_id, 100)] = (["我先检查 bridge 当前状态。"], "FINAL_OK", 150)
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            daemon._mirror_desktop_final_if_any()
            self.assertEqual(fake_wechat.sent[0], ("user@im.wechat", "ctx-1", "我先检查 bridge 当前状态。"))
            self.assertEqual(fake_wechat.sent[1], ("user@im.wechat", "ctx-1", "FINAL_OK"))
            self.assertEqual(state.get_last_progress_summary(thread_id), "我先检查 bridge 当前状态。")

    def test_mirror_follows_current_tmux_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_thread = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            new_thread = "11111111-2222-3333-4444-555555555555"
            state = BridgeState(
                active_session_id=old_thread,
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                mirror_offsets={old_thread: 10, new_thread: 20},
                sessions={
                    old_thread: SessionRecord(
                        thread_id=old_thread,
                        label="old",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    )
                },
            )
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            runner.runtime_thread_id = new_thread
            runner.finals[(new_thread, 20)] = ("NEW_THREAD_FINAL_OK", 30)
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            daemon._mirror_desktop_final_if_any()
            self.assertEqual(state.active_session_id, new_thread)
            self.assertEqual(state.sessions[new_thread].tmux_session, "codex")
            self.assertEqual(fake_wechat.sent[-1], ("user@im.wechat", "ctx-1", "NEW_THREAD_FINAL_OK"))
            self.assertEqual(state.get_mirror_offset(new_thread), 30)


if __name__ == "__main__":
    unittest.main()
