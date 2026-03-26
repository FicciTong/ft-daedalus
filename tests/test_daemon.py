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
        self.fail = False

    def send_text(self, *, to_user_id: str, context_token: str | None, text: str):
        if self.fail:
            raise RuntimeError("ret=-2")
        self.sent.append((to_user_id, context_token, text))
        return {}


class _FakeRunner:
    def __init__(self) -> None:
        self.rollout_sizes: dict[str, int] = {}
        self.finals: dict[tuple[str, int], tuple[str, int]] = {}
        self.progresses: dict[tuple[str, int], tuple[list[str], str, int]] = {}
        self.runtime_thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
        self.submitted: list[tuple[str, str]] = []

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

    def require_live_session(self, state: BridgeState) -> SessionRecord:
        return state.touch_session(
            self.runtime_thread_id,
            label="attached-last",
            cwd="/tmp",
            source="tmux-live",
            tmux_session="codex",
        )

    def submit_prompt(self, *, record: SessionRecord, prompt: str) -> SessionRecord:
        self.submitted.append((record.thread_id, prompt))
        return SessionRecord(
            thread_id=record.thread_id,
            label=record.label,
            cwd=record.cwd,
            source=record.source,
            created_at=record.created_at,
            updated_at=record.updated_at,
            tmux_session=record.tmux_session,
        )

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
            openclaw_profile="daedalus-wechat",
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

    def test_bind_peer_does_not_flush_pending_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                active_session_id=thread_id,
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "PENDING_FINAL_OK",
                        "created_at": "2026-03-26T00:00:00+00:00",
                    }
                ],
            )
            runner = _FakeRunner()
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            daemon._bind_peer("user@im.wechat", "ctx-1")
            self.assertEqual(fake_wechat.sent, [])
            self.assertEqual(len(state.pending_outbox), 1)

    def test_background_flush_uses_existing_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                active_session_id=thread_id,
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "AUTO_FLUSH_OK",
                        "created_at": "2026-03-26T00:00:00+00:00",
                    }
                ],
            )
            runner = _FakeRunner()
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            daemon._flush_bound_outbox_if_any()
            self.assertEqual(
                fake_wechat.sent[-1],
                ("user@im.wechat", None, "AUTO_FLUSH_OK"),
            )
            self.assertEqual(state.pending_outbox, [])

    def test_flush_pending_outbox_preserves_remaining_after_mid_flush_failure(self) -> None:
        class _FlakyWeChat(_FakeWeChat):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def send_text(self, *, to_user_id: str, context_token: str | None, text: str):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("ret=-2")
                return super().send_text(
                    to_user_id=to_user_id,
                    context_token=context_token,
                    text=text,
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                active_session_id=thread_id,
                pending_outbox=[
                    {"to": "user@im.wechat", "text": "FIRST", "created_at": "2026-03-26T00:00:00+00:00"},
                    {"to": "user@im.wechat", "text": "SECOND", "created_at": "2026-03-26T00:00:01+00:00"},
                    {"to": "user@im.wechat", "text": "THIRD", "created_at": "2026-03-26T00:00:02+00:00"},
                ],
            )
            runner = _FakeRunner()
            fake_wechat = _FlakyWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            daemon._bind_peer("user@im.wechat", "ctx-1")
            daemon._flush_bound_outbox_if_any()
            self.assertEqual(fake_wechat.sent, [("user@im.wechat", None, "FIRST")])
            self.assertEqual(
                [item["text"] for item in state.pending_outbox],
                ["SECOND", "THIRD"],
            )

    def test_command_reply_precedes_pending_outbox_flush(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_wechat = _FakeWeChat()
            state = BridgeState(
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "PENDING_FINAL_OK",
                        "created_at": "2026-03-26T00:00:00+00:00",
                    }
                ]
            )
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-cmd",
                    "message_id": "msg-status",
                    "item_list": [{"type": 1, "text_item": {"text": "/status"}}],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertTrue(fake_wechat.sent[0][2].startswith("⚙️ status="))
            self.assertEqual(
                fake_wechat.sent[1],
                ("user@im.wechat", None, "PENDING_FINAL_OK"),
            )

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

    def test_help_and_menu_show_mobile_command_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            help_text = daemon._handle_command("/help")
            menu_text = daemon._handle_command("/menu")
            self.assertEqual(help_text, menu_text)
            self.assertIn("FT bridge 命令总览", help_text)
            self.assertIn("/status", help_text)
            self.assertIn("/health", help_text)
            self.assertIn("/sessions", help_text)
            self.assertIn("/notify on", help_text)
            self.assertIn("/recent after 128", help_text)

    def test_voice_without_transcript_refreshes_binding_and_replies_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-voice",
                    "message_id": "msg-1",
                    "item_list": [{"type": 3, "voice_item": {}}],
                }
            )
            self.assertIsNotNone(incoming)
            assert incoming is not None
            self.assertTrue(incoming.is_voice)
            self.assertFalse(incoming.has_transcript)
            daemon._handle_incoming(incoming)
            self.assertEqual(daemon.state.bound_user_id, "user@im.wechat")
            self.assertEqual(daemon.state.bound_context_token, "ctx-voice")
            self.assertEqual(fake_wechat.sent[-1][2], "⚙️ 收到语音，但无转写。")

    def test_voice_without_message_type_is_still_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            incoming = daemon._parse_incoming(
                {
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-voice",
                    "message_id": "msg-voice-no-type",
                    "item_list": [{"type": 3, "voice_item": {}}],
                }
            )
            self.assertIsNotNone(incoming)
            assert incoming is not None
            self.assertTrue(incoming.is_voice)
            self.assertFalse(incoming.has_transcript)

    def test_explicit_bot_message_type_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 2,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-bot",
                    "message_id": "msg-bot",
                    "item_list": [{"type": 1, "text_item": {"text": "ignore me"}}],
                }
            )
            self.assertIsNone(incoming)

    def test_prompt_is_submitted_to_live_codex_and_acknowledged_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=BridgeState(
                    active_session_id="019cdfe5-fa14-74a3-aa31-5451128ea58d",
                ),
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-text",
                    "message_id": "msg-2",
                    "item_list": [{"type": 1, "text_item": {"text": "hello bridge"}}],
                }
            )
            self.assertIsNotNone(incoming)
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(
                runner.submitted[-1],
                ("019cdfe5-fa14-74a3-aa31-5451128ea58d", "hello bridge"),
            )
            self.assertEqual(
                fake_wechat.sent[-1],
                (
                    "user@im.wechat",
                    "ctx-text",
                    "⚙️ 已注入 terminal。",
                ),
            )

    def test_recent_replays_latest_outgoing_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            config.delivery_ledger_file.write_text(
                "\n".join(
                    [
                        '{"seq":1,"ts":"2026-03-26T05:00:00+00:00","to":"user@im.wechat","status":"sent","kind":"progress","origin":"desktop-mirror","text":"progress one"}',
                        '{"seq":2,"ts":"2026-03-26T05:00:01+00:00","to":"user@im.wechat","status":"sent","kind":"final","origin":"desktop-mirror","text":"FINAL_OK"}',
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
            self.assertIn("[1][sent][progress][13:00:00]", text)
            self.assertIn("next=/recent after 2", text)

    def test_recent_after_seq_uses_stable_delivery_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            config.delivery_ledger_file.write_text(
                "\n".join(
                    [
                        '{"seq":1,"ts":"2026-03-26T05:00:00+00:00","to":"user@im.wechat","status":"sent","kind":"progress","origin":"desktop-mirror","text":"one"}',
                        '{"seq":2,"ts":"2026-03-26T05:00:01+00:00","to":"user@im.wechat","status":"queued","kind":"final","origin":"desktop-mirror","text":"two"}',
                        '{"seq":3,"ts":"2026-03-26T05:00:02+00:00","to":"user@im.wechat","status":"flushed","kind":"final","origin":"desktop-mirror","text":"three"}',
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
            text = daemon._recent_text("after 1")
            self.assertNotIn("one", text)
            self.assertIn("two", text)
            self.assertIn("three", text)
            self.assertIn("next=/recent after 3", text)

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
            self.assertEqual(
                fake_wechat.sent[-1],
                ("user@im.wechat", None, "✅ DESKTOP_FINAL_OK"),
            )
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
            self.assertEqual(
                fake_wechat.sent[0],
                ("user@im.wechat", None, "⏳ 我先检查 bridge 当前状态。"),
            )
            self.assertEqual(
                fake_wechat.sent[1],
                ("user@im.wechat", None, "✅ FINAL_OK"),
            )
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
            self.assertEqual(
                fake_wechat.sent[-1],
                ("user@im.wechat", None, "✅ NEW_THREAD_FINAL_OK"),
            )
            self.assertEqual(state.get_mirror_offset(new_thread), 30)

    def test_command_reply_gets_system_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-cmd",
                    "message_id": "msg-status",
                    "item_list": [{"type": 1, "text_item": {"text": "/status"}}],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertTrue(fake_wechat.sent[-1][2].startswith("⚙️ "))

    def test_final_and_system_tags_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            final_text = daemon._render_reply_text(
                "规则已收口。\n\nSYSTEM",
                kind="final",
                origin="bridge",
            )
            system_text = daemon._render_reply_text(
                "已注入 terminal。\n\nFINAL",
                kind="progress",
                origin="wechat-prompt-submitted",
            )
            progress_text = daemon._render_reply_text(
                "我先检查 bridge 当前状态。",
                kind="progress",
                origin="desktop-mirror",
            )
            self.assertEqual(final_text, "✅ 规则已收口。")
            self.assertEqual(system_text, "⚙️ 已注入 terminal。")
            self.assertEqual(progress_text, "⏳ 我先检查 bridge 当前状态。")


if __name__ == "__main__":
    unittest.main()
