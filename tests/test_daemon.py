from __future__ import annotations

import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.config import BridgeConfig
from daedalus_wechat.daemon import BridgeDaemon, IncomingMessage
from daedalus_wechat.incoming_media import (
    SavedIncomingFile,
    SavedIncomingImage,
    SavedIncomingVideo,
)
from daedalus_wechat.live_session import (
    PLAN_MARKER,
    LiveRuntimeStatus,
    TmuxRuntimeInventoryItem,
)
from daedalus_wechat.state import BridgeState, PendingMediaBatch, SessionRecord


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


class _ChunkFailWeChat(_FakeWeChat):
    def __init__(self, *, fail_on_call: int) -> None:
        super().__init__()
        self.calls = 0
        self.fail_on_call = fail_on_call

    def send_text(self, *, to_user_id: str, context_token: str | None, text: str):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("ret=-2")
        return super().send_text(
            to_user_id=to_user_id,
            context_token=context_token,
            text=text,
        )


class _FailOnCallsWeChat(_FakeWeChat):
    def __init__(self, *, fail_on_calls: set[int]) -> None:
        super().__init__()
        self.calls = 0
        self.fail_on_calls = set(fail_on_calls)

    def send_text(self, *, to_user_id: str, context_token: str | None, text: str):
        self.calls += 1
        if self.calls in self.fail_on_calls:
            raise RuntimeError("ret=-2")
        return super().send_text(
            to_user_id=to_user_id,
            context_token=context_token,
            text=text,
        )


class _FakeRunner:
    def __init__(self) -> None:
        self.rollout_sizes: dict[str, int] = {}
        self.finals: dict[tuple[str, int], tuple[str, int]] = {}
        self.progresses: dict[tuple[str, int], tuple[list[str], str, int]] = {}
        self.runtime_thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
        self.submitted: list[tuple[str, str]] = []
        self.runtime_statuses: list[LiveRuntimeStatus] = [
            LiveRuntimeStatus(
                tmux_session="codex",
                exists=True,
                pane_command="node",
                thread_id=self.runtime_thread_id,
                pane_cwd="/tmp",
            )
        ]

    def try_live_session(self, state: BridgeState):
        self.sync_live_sessions(state)
        status = self.current_runtime_status(
            active_session_id=state.active_session_id,
            active_tmux_session=state.active_tmux_session,
        )
        if not status.exists or not status.thread_id:
            return None
        return state.touch_session(
            status.thread_id,
            label=self._label_for(state, status),
            cwd=status.pane_cwd or "/tmp",
            source=self._source_for(state, status),
            tmux_session=status.tmux_session,
        )

    def sync_live_sessions(self, state: BridgeState) -> list[SessionRecord]:
        records: list[SessionRecord] = []
        for status in self.list_live_runtime_statuses():
            if not status.exists or not status.thread_id:
                continue
            records.append(
                state.touch_session(
                    status.thread_id,
                    label=self._label_for(state, status),
                    cwd=status.pane_cwd or "/tmp",
                    source=self._source_for(state, status),
                    tmux_session=status.tmux_session,
                )
            )
        return records

    def current_runtime_status(
        self,
        *,
        active_session_id: str | None = None,
        active_tmux_session: str | None = None,
    ) -> LiveRuntimeStatus:
        if active_tmux_session:
            for status in self._live_statuses():
                if status.tmux_session == active_tmux_session:
                    return status
        statuses = self.list_live_runtime_statuses()
        if active_session_id:
            for status in statuses:
                if status.thread_id == active_session_id:
                    return status
        for status in statuses:
            if status.tmux_session == "codex":
                return status
        return statuses[0]

    def list_live_runtime_statuses(self) -> list[LiveRuntimeStatus]:
        return [
            status
            for status in self._live_statuses()
            if status.exists
            and status.pane_command in {"node", "codex"}
            and bool(status.thread_id)
            and bool(status.pane_cwd)
            and self.runtime_conflict_reason(status) is None
        ]

    def list_tmux_runtime_inventory(self):
        items = []
        for status in self._live_statuses():
            conflict_reason = self.runtime_conflict_reason(status)
            switchable = (
                status.exists
                and status.pane_command in {"node", "codex"}
                and bool(status.thread_id)
                and bool(status.pane_cwd)
                and conflict_reason is None
            )
            items.append(
                TmuxRuntimeInventoryItem(
                    tmux_session=status.tmux_session,
                    pane_command=status.pane_command,
                    thread_id=status.thread_id,
                    pane_cwd=status.pane_cwd,
                    switchable=switchable,
                    reason=conflict_reason
                    or ("live" if switchable else "outside-workspace"),
                )
            )
        return items

    def expected_backend_for_tmux_session(self, tmux_session: str | None) -> str | None:
        name = str(tmux_session or "").strip().lower()
        if not name:
            return None
        if name == "codex":
            return "codex"
        if "opencode" in name or name.startswith("oc-"):
            return "opencode"
        return None

    def runtime_conflict_reason(self, status: LiveRuntimeStatus) -> str | None:
        if not status.thread_id:
            return None
        for other in self._live_statuses():
            if other.tmux_session == status.tmux_session:
                continue
            if other.thread_id == status.thread_id:
                return "duplicate-runtime-id"
        return None

    def ensure_resumed_session(
        self,
        *,
        thread_id: str,
        state: BridgeState,
        label: str,
        source: str,
    ) -> SessionRecord:
        for status in self.runtime_statuses:
            if status.thread_id == thread_id:
                return state.touch_session(
                    thread_id,
                    label=label,
                    cwd=status.pane_cwd or "/tmp",
                    source=source,
                    tmux_session=status.tmux_session,
                )
        return state.touch_session(
            thread_id,
            label=label,
            cwd="/tmp",
            source=source,
            tmux_session="codex",
        )

    def create_new_session(self, *, state: BridgeState, label: str) -> SessionRecord:
        status = self.current_runtime_status(
            active_session_id=state.active_session_id,
            active_tmux_session=state.active_tmux_session,
        )
        return state.touch_session(
            status.thread_id or self.runtime_thread_id,
            label=label,
            cwd=status.pane_cwd or "/tmp",
            source="bridge-new",
            tmux_session=status.tmux_session,
        )

    def attach_hint(self, record: SessionRecord) -> str:
        return f"tmux attach -t {record.tmux_session or 'codex'}"

    def require_live_session(self, state: BridgeState) -> SessionRecord:
        status = self.current_runtime_status(
            active_session_id=state.active_session_id,
            active_tmux_session=state.active_tmux_session,
        )
        thread_id = status.thread_id or self.runtime_thread_id
        return state.touch_session(
            thread_id,
            label=self._label_for(state, status),
            cwd=status.pane_cwd or "/tmp",
            source=self._source_for(state, status),
            tmux_session=status.tmux_session,
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
            from daedalus_wechat.live_session import FinalScan

            return FinalScan(final_text="", end_offset=start_offset)
        text, end_offset = value
        from daedalus_wechat.live_session import FinalScan

        return FinalScan(final_text=text, end_offset=end_offset)

    def latest_mirror_since(self, *, thread_id: str, start_offset: int):
        value = self.progresses.get((thread_id, start_offset))
        if value is None:
            value = self.finals.get((thread_id, start_offset))
            if value is None:
                from daedalus_wechat.live_session import MirrorScan

                return MirrorScan(
                    progress_texts=[], final_texts=[], end_offset=start_offset
                )
            text, end_offset = value
            from daedalus_wechat.live_session import MirrorScan

            return MirrorScan(
                progress_texts=[],
                final_texts=[text] if text else [],
                end_offset=end_offset,
            )
        progress_texts, final_text, end_offset = value
        from daedalus_wechat.live_session import MirrorScan

        return MirrorScan(
            progress_texts=progress_texts,
            final_texts=[final_text] if final_text else [],
            end_offset=end_offset,
        )

    def _label_for(self, state: BridgeState, status: LiveRuntimeStatus) -> str:
        existing = state.sessions.get(status.thread_id or "")
        if existing:
            return existing.label
        return status.tmux_session

    def _source_for(self, state: BridgeState, status: LiveRuntimeStatus) -> str:
        existing = state.sessions.get(status.thread_id or "")
        if existing:
            return existing.source
        return "tmux-live"

    def _live_statuses(self) -> list[LiveRuntimeStatus]:
        normalized: list[LiveRuntimeStatus] = []
        for status in self.runtime_statuses:
            if status.tmux_session == "codex":
                normalized.append(
                    LiveRuntimeStatus(
                        tmux_session=status.tmux_session,
                        exists=status.exists,
                        pane_command=status.pane_command,
                        thread_id=self.runtime_thread_id,
                        pane_cwd=status.pane_cwd,
                        backend=status.backend,
                    )
                )
                continue
            normalized.append(status)
        return normalized


class _TestDaemon(BridgeDaemon):
    def _start_mirror_thread(self) -> None:
        return None

    def _start_outbox_thread(self) -> None:
        return None


class DaemonTests(unittest.TestCase):
    def _make_config(
        self, state_dir: Path, allowed_users: frozenset[str]
    ) -> BridgeConfig:
        return BridgeConfig(
            codex_bin="codex",
            account_file=state_dir / "account.json",
            state_dir=state_dir,
            default_cwd=Path("/tmp"),
            canonical_tmux_session="codex",
            allowed_users=allowed_users,
            progress_updates_default=False,
        )

    def test_authorized_sender_denied_when_allowlist_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = BridgeDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            self.assertFalse(daemon._is_authorized_sender("any-user"))

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

    def test_unauthorized_message_does_not_bind_or_submit_prompt(self) -> None:
        class _PollingWeChat(_FakeWeChat):
            def __init__(self) -> None:
                super().__init__()
                self._responses = iter(
                    [
                        {
                            "get_updates_buf": "buf-1",
                            "msgs": [
                                {
                                    "from_user_id": "other-user@im.wechat",
                                    "context_token": "ctx-1",
                                    "message_id": "m1",
                                    "message_type": 1,
                                    "item_list": [
                                        {
                                            "type": 1,
                                            "text_item": {"text": "hello bridge"},
                                        }
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

        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState()
            runner = _FakeRunner()
            daemon = _TestDaemon(
                config=self._make_config(
                    Path(tmpdir), frozenset({"allowed-user@im.wechat"})
                ),
                wechat=_PollingWeChat(),
                runner=runner,
                state=state,
            )
            with self.assertRaises(KeyboardInterrupt):
                daemon.run_forever()
            self.assertIsNone(state.bound_user_id)
            self.assertEqual(runner.submitted, [])
            assert daemon.wechat.sent
            self.assertIn("未被授权", daemon.wechat.sent[0][2])

    def test_plain_text_requires_explicit_active_session_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(bound_user_id="user@im.wechat")
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi2",
                    exists=True,
                    pane_command="node",
                    thread_id="ses_live",
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset({"user@im.wechat"})),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )

            daemon._handle_incoming(
                IncomingMessage(
                    from_user_id="user@im.wechat",
                    context_token="ctx-1",
                    body="hello",
                    message_id="msg-1",
                )
            )

            self.assertIsNone(state.active_session_id)
            self.assertIsNone(state.active_tmux_session)
            self.assertEqual(
                fake_wechat.sent[-1],
                (
                    "user@im.wechat",
                    "ctx-1",
                    "⚙️ 没有 active session；请先用 /switch <tmux> 选择一个 live session。",
                ),
            )

    def test_invalid_poll_cursor_is_cleared_after_ret_minus_one(self) -> None:
        class _InvalidCursorWeChat(_FakeWeChat):
            def __init__(self) -> None:
                super().__init__()
                self._responses = iter(
                    [
                        {"ret": -1, "errcode": None, "errmsg": None},
                    ]
                )

            def get_updates(self, _buf: str):
                return next(self._responses)

        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(get_updates_buf="bad-buf")
            daemon = _TestDaemon(
                config=self._make_config(
                    Path(tmpdir), frozenset({"allowed-user@im.wechat"})
                ),
                wechat=_InvalidCursorWeChat(),
                runner=_FakeRunner(),
                state=state,
            )
            with patch(
                "daedalus_wechat.daemon.time.sleep", side_effect=KeyboardInterrupt
            ):
                with self.assertRaises(KeyboardInterrupt):
                    daemon.run_forever()
            self.assertEqual(state.get_updates_buf, "")
            persisted = BridgeState.load(Path(tmpdir) / "state.json")
            self.assertEqual(persisted.get_updates_buf, "")

    def test_systemd_status_returns_to_polling_after_recovery(self) -> None:
        class _RecoveringWeChat(_FakeWeChat):
            def __init__(self) -> None:
                super().__init__()
                self._responses = iter(
                    [
                        {"ret": -1, "errcode": None, "errmsg": None},
                        {"get_updates_buf": "buf-2", "msgs": []},
                        KeyboardInterrupt(),
                    ]
                )

            def get_updates(self, _buf: str):
                result = next(self._responses)
                if isinstance(result, BaseException):
                    raise result
                return result

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("daedalus_wechat.daemon.systemd_notify") as notify:
                daemon = _TestDaemon(
                    config=self._make_config(
                        Path(tmpdir), frozenset({"allowed-user@im.wechat"})
                    ),
                    wechat=_RecoveringWeChat(),
                    runner=_FakeRunner(),
                    state=BridgeState(get_updates_buf="bad-buf"),
                )
                with patch("daedalus_wechat.daemon.time.sleep", return_value=None):
                    with self.assertRaises(KeyboardInterrupt):
                        daemon.run_forever()
            status_calls = [args[0] for args, _ in notify.call_args_list if args]
            self.assertIn("STATUS=bridge poll error; retrying", status_calls)
            self.assertIn("STATUS=bridge polling", status_calls)

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

    def test_status_text_heals_stale_missing_active_tmux(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stale_thread = "019d74bd-debd-7772-8c13-53356881614a"
            live_thread = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                active_session_id=stale_thread,
                active_tmux_session="gpt",
                sessions={
                    stale_thread: SessionRecord(
                        thread_id=stale_thread,
                        label="gpt",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="gpt",
                    ),
                    live_thread: SessionRecord(
                        thread_id=live_thread,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_thread_id = live_thread
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=live_thread,
                    pane_cwd="/tmp",
                    backend="codex",
                )
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            text = daemon._status_text()

            self.assertIn("status=ok", text)
            self.assertIn("tmux=codex", text)
            self.assertEqual(state.active_tmux_session, "codex")
            self.assertEqual(state.active_session_id, live_thread)

    def test_status_text_marks_pending_runtime_id_as_provisional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_thread = "pending:opencode"
            state = BridgeState(
                active_session_id=pending_thread,
                active_tmux_session="opencode",
                sessions={
                    pending_thread: SessionRecord(
                        thread_id=pending_thread,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live-provisional",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="opencode",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="opencode",
                    exists=True,
                    pane_command="node",
                    thread_id=pending_thread,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            daemon = BridgeDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            text = daemon._status_text()
            self.assertIn("status=ok", text)
            self.assertIn("thread=provisional", text)
            self.assertIn("runtime_id=pending:opencode", text)
            self.assertIn("label=opencode", text)
            self.assertIn("tmux=opencode", text)

    def test_status_text_is_read_only_when_no_active_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_live"
            state = BridgeState(
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="kimi2",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="kimi2",
                    )
                }
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi2",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            text = daemon._status_text()

            self.assertEqual(
                text, "status=no_active\nhint=先用 /switch <tmux> 选择一个 live session"
            )
            self.assertIsNone(state.active_session_id)
            self.assertIsNone(state.active_tmux_session)

    def test_status_text_in_group_mode_is_room_summary_without_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_kimi"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="kimi",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-12T00:00:00+00:00",
                        updated_at="2026-04-12T00:00:00+00:00",
                        tmux_session="kimi",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            text = daemon._status_text()

            self.assertIn("status=group", text)
            self.assertIn("mode=group", text)
            self.assertIn("members=1", text)
            self.assertIn("focus=none", text)
            self.assertIn("@agent", text)
            self.assertNotIn("status=no_active", text)

    def test_health_text_in_group_mode_is_room_summary_without_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_codex"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-12T00:00:00+00:00",
                        updated_at="2026-04-12T00:00:00+00:00",
                        tmux_session="codex",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="codex",
                )
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            text = daemon._health_text()

            self.assertIn("health=ok", text)
            self.assertIn("mode=group", text)
            self.assertIn("members=1", text)
            self.assertIn("ready_members=1", text)
            self.assertIn("focus=none", text)
            self.assertNotIn("tmux=", text)

    def test_bootstrap_runtime_does_not_auto_select_live_session_without_active(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_live"
            state = BridgeState()
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi2",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            self.assertIsNone(state.active_session_id)
            self.assertIsNone(state.active_tmux_session)

    def test_current_mirror_thread_id_returns_none_without_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_live"
            state = BridgeState()
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi2",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            mirror_thread = daemon._current_mirror_thread_id()

            self.assertIsNone(mirror_thread)
            self.assertIsNone(state.active_session_id)
            self.assertIsNone(state.active_tmux_session)

    def test_sessions_text_shows_excluded_tmux_inventory_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_a = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            thread_b = "11111111-2222-3333-4444-555555555555"
            state = BridgeState(active_session_id=thread_a, sessions={})
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_a,
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="kairos",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_b,
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="stray-shell",
                    exists=True,
                    pane_command="node",
                    thread_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    pane_cwd=None,
                ),
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            text = daemon._handle_command("/sessions")
            self.assertIn("sessions=2", text)
            self.assertIn("excluded=1", text)
            self.assertIn("x stray-shell | outside-workspace", text)

    def test_sessions_text_lists_multiple_live_tmux_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_a = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            thread_b = "11111111-2222-3333-4444-555555555555"
            state = BridgeState(
                active_session_id=thread_b,
                sessions={
                    thread_a: SessionRecord(
                        thread_id=thread_a,
                        label="codex-main",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    thread_b: SessionRecord(
                        thread_id=thread_b,
                        label="123",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="123",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_a,
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="123",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_b,
                    pane_cwd="/tmp",
                ),
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            text = daemon._handle_command("/sessions")
            self.assertIn("sessions=2", text)
            self.assertIn("1 codex | 019cdfe5 | codex live", text)
            self.assertIn("*2 123 | 11111111 | 123 live", text)

    def test_members_text_prefers_tmux_name_over_stale_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_gpt"
            state = BridgeState(
                active_session_id=thread_id,
                active_tmux_session="gpt",
                room_mode_enabled=True,
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-10T00:00:00+00:00",
                        updated_at="2026-04-10T00:00:00+00:00",
                        tmux_session="gpt",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="gpt",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="codex",
                )
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            text = daemon._handle_command("/members")

            self.assertIn("*1 gpt (codex) | ses_gpt", text)
            self.assertNotIn("codex | ses_gpt", text)

    def test_switch_can_target_live_tmux_session_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_a = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            thread_b = "11111111-2222-3333-4444-555555555555"
            state = BridgeState(
                active_session_id=thread_a,
                sessions={
                    thread_a: SessionRecord(
                        thread_id=thread_a,
                        label="codex-main",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    thread_b: SessionRecord(
                        thread_id=thread_b,
                        label="123",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="123",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_a,
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="123",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_b,
                    pane_cwd="/tmp",
                ),
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            text = daemon._handle_command("/switch 123")
            self.assertEqual(state.active_session_id, thread_b)
            self.assertEqual(state.active_tmux_session, "123")
            self.assertIn("已切换到 session:", text)
            self.assertIn("tmux=123", text)
            self.assertIn("attach=tmux attach -t 123", text)

    def test_switch_keeps_old_active_state_until_resume_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_old = "ses_old_active"
            thread_new = "ses_new_target"
            state = BridgeState(
                active_session_id=thread_old,
                active_tmux_session="kimi2",
                sessions={
                    thread_old: SessionRecord(
                        thread_id=thread_old,
                        label="kimi2",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="kimi2",
                    ),
                    thread_new: SessionRecord(
                        thread_id=thread_new,
                        label="kimi1",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="kimi1",
                    ),
                },
            )

            class _SwitchOrderRunner(_FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.observed_active: tuple[str | None, str | None] | None = None
                    self.runtime_statuses = [
                        LiveRuntimeStatus(
                            tmux_session="kimi2",
                            exists=True,
                            pane_command="node",
                            thread_id=thread_old,
                            pane_cwd="/tmp",
                            backend="opencode",
                        ),
                        LiveRuntimeStatus(
                            tmux_session="kimi1",
                            exists=True,
                            pane_command="node",
                            thread_id=thread_new,
                            pane_cwd="/tmp",
                            backend="opencode",
                        ),
                    ]

                def ensure_resumed_session(self, *, thread_id, state, label, source):
                    self.observed_active = (
                        state.active_session_id,
                        state.active_tmux_session,
                    )
                    return super().ensure_resumed_session(
                        thread_id=thread_id,
                        state=state,
                        label=label,
                        source=source,
                    )

            runner = _SwitchOrderRunner()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            text = daemon._handle_command("/switch kimi1")

            self.assertEqual(runner.observed_active, (thread_old, "kimi2"))
            self.assertEqual(state.active_session_id, thread_new)
            self.assertEqual(state.active_tmux_session, "kimi1")
            self.assertIn("tmux=kimi1", text)

    def test_switch_group_enables_room_mode_without_replacing_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_gpt"
            state = BridgeState(
                active_session_id=thread_id,
                active_tmux_session="gpt",
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="gpt",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="gpt",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="gpt",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            text = daemon._handle_command("/switch group")

            self.assertTrue(state.room_mode_enabled)
            self.assertEqual(state.active_tmux_session, "gpt")
            self.assertIn("已切换到 group 模式", text)
            self.assertIn("mode=group", text)

    def test_switch_group_fast_forwards_live_cursors_and_preserves_mirror_backlog(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_gpt = "ses_gpt"
            thread_claude = "ses_claude"
            state = BridgeState(
                active_session_id=thread_gpt,
                active_tmux_session="gpt",
                mirror_offsets={thread_gpt: 10, thread_claude: 20},
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "[claude] old final",
                        "created_at": "2026-04-10T00:00:00+00:00",
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": thread_claude,
                        "tmux_session": "claude",
                        "attempt_count": 1,
                        "last_attempt_at": "2026-04-10T00:00:00+00:00",
                        "last_error": "",
                    },
                    {
                        "to": "user@im.wechat",
                        "text": "keep me",
                        "created_at": "2026-04-10T00:00:00+00:00",
                        "kind": "message",
                        "origin": "bridge",
                        "thread_id": "",
                        "tmux_session": "",
                        "attempt_count": 1,
                        "last_attempt_at": "2026-04-10T00:00:00+00:00",
                        "last_error": "",
                    },
                ],
                sessions={
                    thread_gpt: SessionRecord(
                        thread_id=thread_gpt,
                        label="gpt",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="gpt",
                    ),
                    thread_claude: SessionRecord(
                        thread_id=thread_claude,
                        label="claude",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="claude",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="gpt",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_gpt,
                    pane_cwd="/tmp",
                    backend="codex",
                ),
                LiveRuntimeStatus(
                    tmux_session="claude",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_claude,
                    pane_cwd="/tmp",
                    backend="claude-code",
                ),
            ]
            runner.rollout_sizes[thread_gpt] = 120
            runner.rollout_sizes[thread_claude] = 220
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            text = daemon._handle_command("/switch group")

            self.assertTrue(state.room_mode_enabled)
            self.assertEqual(state.get_mirror_offset(thread_gpt), 120)
            self.assertEqual(state.get_mirror_offset(thread_claude), 220)
            self.assertEqual(len(state.pending_outbox), 2)
            self.assertEqual(
                [item["origin"] for item in state.pending_outbox],
                ["desktop-mirror", "bridge"],
            )
            self.assertIn("mode=group", text)

    def test_group_targeted_message_routes_without_replacing_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_active = "ses_gpt"
            thread_target = "ses_kimi1"
            state = BridgeState(
                active_session_id=thread_active,
                active_tmux_session="gpt",
                room_mode_enabled=True,
                sessions={
                    thread_active: SessionRecord(
                        thread_id=thread_active,
                        label="gpt",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="gpt",
                    ),
                    thread_target: SessionRecord(
                        thread_id=thread_target,
                        label="kimi1",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="kimi1",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="gpt",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_active,
                    pane_cwd="/tmp",
                    backend="opencode",
                ),
                LiveRuntimeStatus(
                    tmux_session="kimi1",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_target,
                    pane_cwd="/tmp",
                    backend="opencode",
                ),
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [{"type": 1, "text_item": {"text": "@kimi1 say hi"}}],
                }
            )
            assert incoming is not None

            daemon._handle_incoming(incoming)

            self.assertEqual(len(runner.submitted), 1)
            self.assertEqual(runner.submitted[0][0], thread_target)
            self.assertIn("say hi", runner.submitted[0][1])
            self.assertEqual(state.active_session_id, thread_active)
            self.assertEqual(state.active_tmux_session, "gpt")
            self.assertEqual(state.room_focus_tmux_session, "kimi1")
            self.assertEqual(
                fake_wechat.sent[-1],
                (
                    "user@im.wechat",
                    "ctx-1",
                    "⚙️ 已注入 @kimi1 terminal，等待 [kimi1] 首条回复。",
                ),
            )

    def test_room_mode_tags_desktop_final_with_speaker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "claude:abc"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="claude",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="claude",
                    )
                },
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._reply(
                "user@im.wechat",
                None,
                "HELLO",
                kind="final",
                origin="desktop-mirror",
                thread_id=thread_id,
                tmux_session="claude",
            )

            self.assertEqual(
                fake_wechat.sent[-1],
                ("user@im.wechat", None, "[claude] ✅ HELLO"),
            )

    def test_room_mode_non_focused_final_is_not_deferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_alpha = "ses_alpha"
            thread_beta = "ses_beta"
            state = BridgeState(
                room_mode_enabled=True,
                bound_user_id="user@im.wechat",
                sessions={
                    thread_alpha: SessionRecord(
                        thread_id=thread_alpha,
                        label="alpha",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="alpha",
                    ),
                    thread_beta: SessionRecord(
                        thread_id=thread_beta,
                        label="beta",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="beta",
                    ),
                },
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._set_room_focus(
                thread_id=thread_alpha,
                tmux_session="alpha",
                trigger="test",
            )
            daemon._reply(
                "user@im.wechat",
                None,
                "OTHER",
                kind="final",
                origin="desktop-mirror",
                thread_id=thread_beta,
                tmux_session="beta",
            )

            self.assertEqual(
                fake_wechat.sent,
                [("user@im.wechat", None, "[beta] ✅ OTHER")],
            )
            self.assertEqual(state.pending_outbox, [])
            self.assertEqual(state.room_focus_tmux_session, "alpha")

            daemon._reply(
                "user@im.wechat",
                None,
                "TARGET",
                kind="final",
                origin="desktop-mirror",
                thread_id=thread_alpha,
                tmux_session="alpha",
            )

            self.assertEqual(
                fake_wechat.sent,
                [
                    ("user@im.wechat", None, "[beta] ✅ OTHER"),
                    ("user@im.wechat", None, "[alpha] ✅ TARGET"),
                ],
            )
            self.assertEqual(state.room_focus_tmux_session, None)

    def test_room_mode_focus_timeout_still_clears_stale_focus(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_alpha = "ses_alpha"
            thread_beta = "ses_beta"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_alpha: SessionRecord(
                        thread_id=thread_alpha,
                        label="alpha",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="alpha",
                    ),
                    thread_beta: SessionRecord(
                        thread_id=thread_beta,
                        label="beta",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="beta",
                    ),
                },
            )
            state.set_room_focus(
                thread_id=thread_alpha,
                tmux_session="alpha",
                started_at=(datetime.now(UTC) - timedelta(seconds=45)).isoformat(),
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            self.assertIsNone(daemon._active_room_focus())

            daemon._reply(
                "user@im.wechat",
                None,
                "OTHER",
                kind="final",
                origin="desktop-mirror",
                thread_id=thread_beta,
                tmux_session="beta",
            )

            self.assertEqual(
                fake_wechat.sent,
                [("user@im.wechat", None, "[beta] ✅ OTHER")],
            )
            self.assertEqual(state.room_focus_tmux_session, None)

    def test_room_mode_new_thread_adopts_tail_without_replaying_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "claude:abc"
            state = BridgeState(
                room_mode_enabled=True,
                bound_user_id="user@im.wechat",
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="claude",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="claude",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="claude",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="claude-code",
                )
            ]
            runner.rollout_sizes[thread_id] = 150
            runner.finals[(thread_id, 0)] = ("OLD", 150)
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )

            daemon._mirror_room_all_members()

            self.assertEqual(fake_wechat.sent, [])
            self.assertEqual(state.get_mirror_offset(thread_id), 150)

            runner.finals[(thread_id, 150)] = ("NEW", 200)

            daemon._mirror_room_all_members()

            self.assertEqual(
                fake_wechat.sent[-1],
                ("user@im.wechat", None, "[claude] ✅ NEW"),
            )
            self.assertEqual(state.get_mirror_offset(thread_id), 200)

    def test_group_mode_voice_fuzzy_match_session_name(self) -> None:
        """Voice transcript 'kimi 零 你好' should match tmux session 'kimi0'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_claude = "ses_claude"
            thread_kimi = "ses_kimi0"
            state = BridgeState(
                active_session_id=thread_claude,
                active_tmux_session="claude",
                room_mode_enabled=True,
                sessions={
                    thread_claude: SessionRecord(
                        thread_id=thread_claude,
                        label="claude",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-06T00:00:00+00:00",
                        updated_at="2026-04-06T00:00:00+00:00",
                        tmux_session="claude",
                    ),
                    thread_kimi: SessionRecord(
                        thread_id=thread_kimi,
                        label="kimi0",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-06T00:00:00+00:00",
                        updated_at="2026-04-06T00:00:00+00:00",
                        tmux_session="kimi0",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="claude",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_claude,
                    pane_cwd="/tmp",
                    backend="claude-code",
                ),
                LiveRuntimeStatus(
                    tmux_session="kimi0",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_kimi,
                    pane_cwd="/tmp",
                    backend="opencode",
                ),
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            # "kimi 零 你好" → normalize → "kimi0" → match kimi0
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [{"type": 1, "text_item": {"text": "kimi 零 你好"}}],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(len(runner.submitted), 1)
            self.assertEqual(runner.submitted[0][0], thread_kimi)

    def test_group_mode_voice_correction_cloud_to_claude(self) -> None:
        """'cloud 你好' (WeChat STT of 'claude') should match 'claude'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_claude = "ses_claude"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_claude: SessionRecord(
                        thread_id=thread_claude,
                        label="claude",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-06T00:00:00+00:00",
                        updated_at="2026-04-06T00:00:00+00:00",
                        tmux_session="claude",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="claude",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_claude,
                    pane_cwd="/tmp",
                    backend="claude-code",
                ),
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [{"type": 1, "text_item": {"text": "cloud 你好"}}],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(len(runner.submitted), 1)
            self.assertEqual(runner.submitted[0][0], thread_claude)

    def test_group_mode_voice_correction_killing_to_kimi(self) -> None:
        """'killing 零' (WeChat STT of 'kimi 零') should match 'kimi0'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_kimi = "ses_kimi0"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_kimi: SessionRecord(
                        thread_id=thread_kimi,
                        label="kimi0",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-06T00:00:00+00:00",
                        updated_at="2026-04-06T00:00:00+00:00",
                        tmux_session="kimi0",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi0",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_kimi,
                    pane_cwd="/tmp",
                    backend="opencode",
                ),
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "killing 零 你好"}}
                    ],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(len(runner.submitted), 1)
            self.assertEqual(runner.submitted[0][0], thread_kimi)

    def test_group_mode_voice_direct_session_name(self) -> None:
        """'claude 你好' should match tmux session 'claude' directly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_claude = "ses_claude"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_claude: SessionRecord(
                        thread_id=thread_claude,
                        label="claude",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-06T00:00:00+00:00",
                        updated_at="2026-04-06T00:00:00+00:00",
                        tmux_session="claude",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="claude",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_claude,
                    pane_cwd="/tmp",
                    backend="claude-code",
                ),
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [{"type": 1, "text_item": {"text": "claude 你好"}}],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(len(runner.submitted), 1)
            self.assertEqual(runner.submitted[0][0], thread_claude)

    def test_group_mode_voice_no_match_prompts_for_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                room_mode_enabled=True,
                sessions={},
            )
            runner = _FakeRunner()
            runner.runtime_statuses = []
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [{"type": 1, "text_item": {"text": "你好世界"}}],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(runner.submitted, [])
            self.assertIn("@agent", fake_wechat.sent[-1][2])

    def test_group_mode_voice_variant_jiama_routes_to_gamma_when_live(self) -> None:
        """'伽马 你好' (STT of 'Gamma') should route to live tmux 'gamma'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_gamma = "ses_gamma"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_gamma: SessionRecord(
                        thread_id=thread_gamma,
                        label="gamma",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-17T00:00:00+00:00",
                        updated_at="2026-04-17T00:00:00+00:00",
                        tmux_session="gamma",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="gamma",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_gamma,
                    pane_cwd="/tmp",
                    backend="codex",
                ),
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [{"type": 1, "text_item": {"text": "伽马 你好"}}],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(len(runner.submitted), 1)
            self.assertEqual(runner.submitted[0][0], thread_gamma)

    def test_group_mode_voice_variant_jiama_noop_when_gamma_not_live(self) -> None:
        """'伽马' variant must not route to anything when no `gamma` session
        is live — the template entry is data-driven by the scan result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_claude = "ses_claude"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_claude: SessionRecord(
                        thread_id=thread_claude,
                        label="claude",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-17T00:00:00+00:00",
                        updated_at="2026-04-17T00:00:00+00:00",
                        tmux_session="claude",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="claude",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_claude,
                    pane_cwd="/tmp",
                    backend="claude-code",
                ),
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [{"type": 1, "text_item": {"text": "伽马 你好"}}],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(runner.submitted, [])
            self.assertIn("@agent", fake_wechat.sent[-1][2])

    def test_group_mode_voice_variant_aerfa_routes_to_alpha(self) -> None:
        """'阿尔法 hello' should route to live tmux 'alpha'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_alpha = "ses_alpha"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_alpha: SessionRecord(
                        thread_id=thread_alpha,
                        label="alpha",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-17T00:00:00+00:00",
                        updated_at="2026-04-17T00:00:00+00:00",
                        tmux_session="alpha",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="alpha",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_alpha,
                    pane_cwd="/tmp",
                    backend="codex",
                ),
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [{"type": 1, "text_item": {"text": "阿尔法 hello"}}],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(len(runner.submitted), 1)
            self.assertEqual(runner.submitted[0][0], thread_alpha)

    def test_group_mode_voice_variant_beita_routes_to_beta(self) -> None:
        """'贝塔' should route to live tmux 'beta'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_beta = "ses_beta"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_beta: SessionRecord(
                        thread_id=thread_beta,
                        label="beta",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-17T00:00:00+00:00",
                        updated_at="2026-04-17T00:00:00+00:00",
                        tmux_session="beta",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="beta",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_beta,
                    pane_cwd="/tmp",
                    backend="codex",
                ),
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [{"type": 1, "text_item": {"text": "贝塔 yo"}}],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(len(runner.submitted), 1)
            self.assertEqual(runner.submitted[0][0], thread_beta)

    def test_group_mode_plain_text_without_target_prompts_for_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_claude"
            state = BridgeState(
                active_session_id=thread_id,
                active_tmux_session="claude",
                room_mode_enabled=True,
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-06T00:00:00+00:00",
                        updated_at="2026-04-06T00:00:00+00:00",
                        tmux_session="claude",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="claude",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="claude",
                )
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "hello without at"}}
                    ],
                }
            )
            assert incoming is not None

            daemon._handle_incoming(incoming)

            self.assertEqual(runner.submitted, [])
            self.assertIsNone(state.room_focus_tmux_session)
            self.assertIn("@agent", fake_wechat.sent[-1][2])
            self.assertIn("不会默认路由", fake_wechat.sent[-1][2])

    def test_group_mode_pending_image_batch_is_claimed_by_next_targeted_message(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_target = "ses_kimi1"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_target: SessionRecord(
                        thread_id=thread_target,
                        label="kimi1",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-10T00:00:00+00:00",
                        updated_at="2026-04-10T00:00:00+00:00",
                        tmux_session="kimi1",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi1",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_target,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            saved_path = Path(tmpdir) / "incoming_media" / "img-1_1.jpg"
            saved_path.parent.mkdir(parents=True, exist_ok=True)
            saved_path.write_bytes(b"image-bytes")
            incoming_image = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-image",
                    "message_id": "img-1",
                    "item_list": [
                        {
                            "type": 2,
                            "image_item": {"url": "https://example.com/test.jpg"},
                        }
                    ],
                }
            )
            assert incoming_image is not None
            with patch(
                "daedalus_wechat.daemon.download_incoming_image",
                return_value=SavedIncomingImage(
                    index=0,
                    path=saved_path,
                    source_url="https://example.com/test.jpg",
                    content_type="image/jpeg",
                    size_bytes=len(b"image-bytes"),
                ),
            ):
                daemon._handle_incoming(incoming_image)
            self.assertEqual(runner.submitted, [])
            self.assertEqual(len(state.pending_media_batches), 1)
            self.assertIn("下一条用 @agent", fake_wechat.sent[-1][2])

            incoming_target = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-target",
                    "message_id": "msg-2",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "@kimi1 你看一下"}}
                    ],
                }
            )
            assert incoming_target is not None
            daemon._handle_incoming(incoming_target)

            self.assertEqual(runner.submitted[-1][0], thread_target)
            submitted_prompt = runner.submitted[-1][1]
            self.assertIn(str(saved_path), submitted_prompt)
            self.assertIn("你看一下", submitted_prompt)
            self.assertEqual(state.pending_media_batches, [])

    def test_group_mode_consecutive_image_messages_merge_into_single_batch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_target = "ses_kimi1"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_target: SessionRecord(
                        thread_id=thread_target,
                        label="kimi1",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-10T00:00:00+00:00",
                        updated_at="2026-04-10T00:00:00+00:00",
                        tmux_session="kimi1",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi1",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_target,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            saved_images: list[SavedIncomingImage] = []
            incoming_images: list[IncomingMessage] = []
            for idx in range(3):
                saved_path = Path(tmpdir) / "incoming_media" / f"img-{idx + 1}_1.jpg"
                saved_path.parent.mkdir(parents=True, exist_ok=True)
                saved_path.write_bytes(f"image-{idx + 1}".encode())
                saved_images.append(
                    SavedIncomingImage(
                        index=0,
                        path=saved_path,
                        source_url=f"https://example.com/test-{idx + 1}.jpg",
                        content_type="image/jpeg",
                        size_bytes=saved_path.stat().st_size,
                    )
                )
                incoming = daemon._parse_incoming(
                    {
                        "message_type": 1,
                        "from_user_id": "user@im.wechat",
                        "context_token": f"ctx-image-{idx + 1}",
                        "message_id": f"img-{idx + 1}",
                        "item_list": [
                            {
                                "type": 2,
                                "image_item": {
                                    "url": f"https://example.com/test-{idx + 1}.jpg"
                                },
                            }
                        ],
                    }
                )
                assert incoming is not None
                incoming_images.append(incoming)

            with patch(
                "daedalus_wechat.daemon.download_incoming_image",
                side_effect=saved_images,
            ):
                for incoming in incoming_images:
                    daemon._handle_incoming(incoming)

            self.assertEqual(len(state.pending_media_batches), 1)
            batch = state.pending_media_batches[0]
            self.assertEqual(
                batch.image_paths, [str(image.path) for image in saved_images]
            )
            self.assertIn("当前这批共 3 张图片", fake_wechat.sent[-1][2])

            incoming_target = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-target",
                    "message_id": "msg-4",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "@kimi1 继续看图"}}
                    ],
                }
            )
            assert incoming_target is not None
            daemon._handle_incoming(incoming_target)

            self.assertEqual(runner.submitted[-1][0], thread_target)
            submitted_prompt = runner.submitted[-1][1]
            for image in saved_images:
                self.assertIn(str(image.path), submitted_prompt)
            self.assertIn("继续看图", submitted_prompt)
            self.assertEqual(state.pending_media_batches, [])

    def test_group_mode_file_only_message_registers_pending_batch_and_claims_on_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_target = "ses_kimi1"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_target: SessionRecord(
                        thread_id=thread_target,
                        label="kimi1",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-10T00:00:00+00:00",
                        updated_at="2026-04-10T00:00:00+00:00",
                        tmux_session="kimi1",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi1",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_target,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            saved_path = Path(tmpdir) / "incoming_media" / "report.docx"
            saved_path.parent.mkdir(parents=True, exist_ok=True)
            saved_path.write_bytes(b"file-bytes")
            incoming_file = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-file",
                    "message_id": "file-1",
                    "item_list": [
                        {
                            "type": 4,
                            "file_item": {
                                "file_name": "report.docx",
                                "media": {
                                    "encrypt_query_param": "file-enc",
                                    "aes_key": "MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
                                },
                            },
                        }
                    ],
                }
            )
            assert incoming_file is not None
            with patch(
                "daedalus_wechat.daemon.download_incoming_file",
                return_value=SavedIncomingFile(
                    index=0,
                    path=saved_path,
                    source_url="https://cdn.example.com/report.docx",
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    size_bytes=saved_path.stat().st_size,
                    file_name="report.docx",
                ),
            ):
                daemon._handle_incoming(incoming_file)
            self.assertEqual(runner.submitted, [])
            self.assertEqual(len(state.pending_media_batches), 1)
            self.assertEqual(
                state.pending_media_batches[0].file_paths, [str(saved_path)]
            )
            self.assertIn("收到 1 个文件。", fake_wechat.sent[-1][2])
            self.assertIn("下一条用 @agent", fake_wechat.sent[-1][2])

            incoming_target = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-target",
                    "message_id": "msg-file-target",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "@kimi1 你看一下这个文件"}}
                    ],
                }
            )
            assert incoming_target is not None
            daemon._handle_incoming(incoming_target)

            self.assertEqual(runner.submitted[-1][0], thread_target)
            submitted_prompt = runner.submitted[-1][1]
            self.assertIn(str(saved_path), submitted_prompt)
            self.assertIn("你看一下这个文件", submitted_prompt)
            self.assertEqual(state.pending_media_batches, [])

    def test_group_mode_video_only_message_registers_pending_batch_and_claims_on_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_target = "ses_kimi1"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_target: SessionRecord(
                        thread_id=thread_target,
                        label="kimi1",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-10T00:00:00+00:00",
                        updated_at="2026-04-10T00:00:00+00:00",
                        tmux_session="kimi1",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi1",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_target,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            saved_path = Path(tmpdir) / "incoming_media" / "clip.mp4"
            saved_path.parent.mkdir(parents=True, exist_ok=True)
            saved_path.write_bytes(b"video-bytes")
            incoming_video = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-video",
                    "message_id": "video-1",
                    "item_list": [
                        {
                            "type": 5,
                            "video_item": {
                                "media": {
                                    "encrypt_query_param": "video-enc",
                                    "aes_key": "MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
                                }
                            },
                        }
                    ],
                }
            )
            assert incoming_video is not None
            with patch(
                "daedalus_wechat.daemon.download_incoming_video",
                return_value=SavedIncomingVideo(
                    index=0,
                    path=saved_path,
                    source_url="https://cdn.example.com/clip.mp4",
                    content_type="video/mp4",
                    size_bytes=saved_path.stat().st_size,
                ),
            ):
                daemon._handle_incoming(incoming_video)
            self.assertEqual(runner.submitted, [])
            self.assertEqual(len(state.pending_media_batches), 1)
            self.assertEqual(
                state.pending_media_batches[0].video_paths, [str(saved_path)]
            )
            self.assertIn("收到 1 个视频。", fake_wechat.sent[-1][2])
            self.assertIn("下一条用 @agent", fake_wechat.sent[-1][2])

            incoming_target = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-target",
                    "message_id": "msg-video-target",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "@kimi1 你看一下这个视频"}}
                    ],
                }
            )
            assert incoming_target is not None
            daemon._handle_incoming(incoming_target)

            self.assertEqual(runner.submitted[-1][0], thread_target)
            submitted_prompt = runner.submitted[-1][1]
            self.assertIn(str(saved_path), submitted_prompt)
            self.assertIn("你看一下这个视频", submitted_prompt)
            self.assertEqual(state.pending_media_batches, [])

    def test_group_mode_claim_coalesces_legacy_split_image_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_target = "ses_kimi1"
            base = datetime.now(UTC) - timedelta(seconds=3)
            image_paths: list[str] = []
            for idx in range(3):
                path = Path(tmpdir) / "incoming_media" / f"legacy-{idx + 1}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"legacy-{idx + 1}".encode())
                image_paths.append(str(path))
            state = BridgeState(
                room_mode_enabled=True,
                pending_media_batches=[
                    PendingMediaBatch(
                        batch_id="img-1",
                        from_user_id="user@im.wechat",
                        message_id="img-1",
                        created_at=base.isoformat(),
                        updated_at=base.isoformat(),
                        image_paths=[image_paths[0]],
                    ),
                    PendingMediaBatch(
                        batch_id="img-2",
                        from_user_id="user@im.wechat",
                        message_id="img-2",
                        created_at=(base + timedelta(seconds=1)).isoformat(),
                        updated_at=(base + timedelta(seconds=1)).isoformat(),
                        image_paths=[image_paths[1]],
                    ),
                    PendingMediaBatch(
                        batch_id="img-3",
                        from_user_id="user@im.wechat",
                        message_id="img-3",
                        created_at=(base + timedelta(seconds=2)).isoformat(),
                        updated_at=(base + timedelta(seconds=2)).isoformat(),
                        image_paths=[image_paths[2]],
                    ),
                ],
                sessions={
                    thread_target: SessionRecord(
                        thread_id=thread_target,
                        label="kimi1",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-10T00:00:00+00:00",
                        updated_at="2026-04-10T00:00:00+00:00",
                        tmux_session="kimi1",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi1",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_target,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )

            incoming_target = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-target",
                    "message_id": "msg-legacy-claim",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "@kimi1 回去看刚才那组图"}}
                    ],
                }
            )
            assert incoming_target is not None
            daemon._handle_incoming(incoming_target)

            submitted_prompt = runner.submitted[-1][1]
            for image_path in image_paths:
                self.assertIn(image_path, submitted_prompt)
            self.assertEqual(state.pending_media_batches, [])
            self.assertEqual(
                fake_wechat.sent[-1],
                (
                    "user@im.wechat",
                    "ctx-target",
                    "⚙️ 已注入 @kimi1 terminal，等待 [kimi1] 首条回复。",
                ),
            )

    def test_group_mode_new_image_batch_supersedes_older_pending_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_target = "ses_kimi1"
            old_time = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
            state = BridgeState(
                room_mode_enabled=True,
                pending_media_batches=[
                    PendingMediaBatch(
                        batch_id="old-batch",
                        from_user_id="user@im.wechat",
                        message_id="old-batch",
                        created_at=old_time,
                        updated_at=old_time,
                        image_paths=[str(Path(tmpdir) / "incoming_media" / "old.jpg")],
                    )
                ],
                sessions={
                    thread_target: SessionRecord(
                        thread_id=thread_target,
                        label="kimi1",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-10T00:00:00+00:00",
                        updated_at="2026-04-10T00:00:00+00:00",
                        tmux_session="kimi1",
                    )
                },
            )
            old_path = Path(state.pending_media_batches[0].image_paths[0])
            old_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.write_bytes(b"old")
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi1",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_target,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            new_path = Path(tmpdir) / "incoming_media" / "new.jpg"
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_bytes(b"new")
            incoming_image = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-image",
                    "message_id": "new-batch",
                    "item_list": [
                        {
                            "type": 2,
                            "image_item": {"url": "https://example.com/new.jpg"},
                        }
                    ],
                }
            )
            assert incoming_image is not None
            with patch(
                "daedalus_wechat.daemon.download_incoming_image",
                return_value=SavedIncomingImage(
                    index=0,
                    path=new_path,
                    source_url="https://example.com/new.jpg",
                    content_type="image/jpeg",
                    size_bytes=new_path.stat().st_size,
                ),
            ):
                daemon._handle_incoming(incoming_image)

            self.assertEqual(len(state.pending_media_batches), 1)
            self.assertEqual(state.pending_media_batches[0].batch_id, "new-batch")
            self.assertEqual(
                state.pending_media_batches[0].image_paths, [str(new_path)]
            )
            self.assertNotIn("待分配图片", fake_wechat.sent[-1][2])

            incoming_target = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-target",
                    "message_id": "msg-target",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "@kimi1 看最新那组图"}}
                    ],
                }
            )
            assert incoming_target is not None
            daemon._handle_incoming(incoming_target)

            submitted_prompt = runner.submitted[-1][1]
            self.assertIn(str(new_path), submitted_prompt)
            self.assertNotIn(str(old_path), submitted_prompt)
            self.assertEqual(state.pending_media_batches, [])

    def test_group_mode_claim_prefers_latest_pending_batch_over_stale_older_batch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_target = "ses_kimi1"
            old_time = datetime.now(UTC) - timedelta(minutes=5)
            new_time = datetime.now(UTC) - timedelta(seconds=5)
            old_path = Path(tmpdir) / "incoming_media" / "old.jpg"
            new_path = Path(tmpdir) / "incoming_media" / "new.jpg"
            old_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.write_bytes(b"old")
            new_path.write_bytes(b"new")
            state = BridgeState(
                room_mode_enabled=True,
                pending_media_batches=[
                    PendingMediaBatch(
                        batch_id="old-batch",
                        from_user_id="user@im.wechat",
                        message_id="old-batch",
                        created_at=old_time.isoformat(),
                        updated_at=old_time.isoformat(),
                        image_paths=[str(old_path)],
                    ),
                    PendingMediaBatch(
                        batch_id="new-batch",
                        from_user_id="user@im.wechat",
                        message_id="new-batch",
                        created_at=new_time.isoformat(),
                        updated_at=new_time.isoformat(),
                        image_paths=[str(new_path)],
                    ),
                ],
                sessions={
                    thread_target: SessionRecord(
                        thread_id=thread_target,
                        label="kimi1",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-10T00:00:00+00:00",
                        updated_at="2026-04-10T00:00:00+00:00",
                        tmux_session="kimi1",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi1",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_target,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )

            incoming_target = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-target",
                    "message_id": "msg-target",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "@kimi1 看最新图片"}}
                    ],
                }
            )
            assert incoming_target is not None
            daemon._handle_incoming(incoming_target)

            submitted_prompt = runner.submitted[-1][1]
            self.assertIn(str(new_path), submitted_prompt)
            self.assertNotIn(str(old_path), submitted_prompt)
            self.assertEqual(state.pending_media_batches, [])

    def test_room_speaker_tag_prefers_tmux_name_over_stale_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_gpt"
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-10T00:00:00+00:00",
                        updated_at="2026-04-10T00:00:00+00:00",
                        tmux_session="gpt",
                    )
                },
            )
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=state,
            )

            tagged = daemon._tag_room_text(
                "HELLO",
                thread_id=thread_id,
                tmux_session=None,
            )

            self.assertEqual(tagged, "[gpt] HELLO")

    def test_group_mode_does_not_auto_attach_global_recent_images_by_keyword(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_target = "ses_kimi1"
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.incoming_media_dir.mkdir(parents=True, exist_ok=True)
            old_image = config.incoming_media_dir / "20260405_old_1.jpg"
            old_image.write_bytes(b"old-image")
            state = BridgeState(
                room_mode_enabled=True,
                sessions={
                    thread_target: SessionRecord(
                        thread_id=thread_target,
                        label="kimi1",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-10T00:00:00+00:00",
                        updated_at="2026-04-10T00:00:00+00:00",
                        tmux_session="kimi1",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kimi1",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_target,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "msg-1",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "@kimi1 看一下图片"}}
                    ],
                }
            )
            assert incoming is not None

            daemon._handle_incoming(incoming)

            submitted_prompt = runner.submitted[-1][1]
            self.assertEqual(submitted_prompt, "看一下图片")
            self.assertNotIn(str(old_image), submitted_prompt)
            self.assertNotIn("Owner 通过微信发送了图片", submitted_prompt)

    def test_current_mirror_thread_id_does_not_overwrite_newer_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_old = "ses_old_active"
            thread_new = "ses_new_target"
            state = BridgeState(
                active_session_id=thread_old,
                active_tmux_session="gpt",
                sessions={
                    thread_old: SessionRecord(
                        thread_id=thread_old,
                        label="gpt",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="gpt",
                    ),
                    thread_new: SessionRecord(
                        thread_id=thread_new,
                        label="kimi2",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="kimi2",
                    ),
                },
            )

            class _NoBootstrapDaemon(_TestDaemon):
                def _bootstrap_runtime(self) -> None:
                    return None

            class _MirrorRaceRunner(_FakeRunner):
                def __init__(self, state_ref: BridgeState) -> None:
                    super().__init__()
                    self._state_ref = state_ref
                    self.calls = 0

                def current_runtime_status(
                    self,
                    *,
                    active_session_id: str | None = None,
                    active_tmux_session: str | None = None,
                ) -> LiveRuntimeStatus:
                    self.calls += 1
                    if self.calls == 1:
                        self._state_ref.active_session_id = thread_new
                        self._state_ref.active_tmux_session = "kimi2"
                        return LiveRuntimeStatus(
                            tmux_session="gpt",
                            exists=True,
                            pane_command="node",
                            thread_id=thread_old,
                            pane_cwd="/tmp",
                            backend="opencode",
                        )
                    return LiveRuntimeStatus(
                        tmux_session="kimi2",
                        exists=True,
                        pane_command="node",
                        thread_id=thread_new,
                        pane_cwd="/tmp",
                        backend="opencode",
                    )

            runner = _MirrorRaceRunner(state)
            daemon = _NoBootstrapDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            thread_id = daemon._current_mirror_thread_id()

            self.assertEqual(thread_id, thread_new)
            self.assertEqual(state.active_session_id, thread_new)
            self.assertEqual(state.active_tmux_session, "kimi2")

    def test_switch_text_marks_pending_runtime_id_as_provisional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_thread = "pending:opencode"
            codex_thread = "019d332d-1bc8-7151-a874-ab0fbc493747"
            state = BridgeState(
                active_session_id=codex_thread,
                active_tmux_session="codex",
                sessions={
                    codex_thread: SessionRecord(
                        thread_id=codex_thread,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    pending_thread: SessionRecord(
                        thread_id=pending_thread,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live-provisional",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="opencode",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=codex_thread,
                    pane_cwd="/tmp",
                    backend="codex",
                ),
                LiveRuntimeStatus(
                    tmux_session="opencode",
                    exists=True,
                    pane_command="node",
                    thread_id=pending_thread,
                    pane_cwd="/tmp",
                    backend="opencode",
                ),
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            text = daemon._handle_command("/switch opencode")
            self.assertEqual(state.active_session_id, pending_thread)
            self.assertEqual(state.active_tmux_session, "opencode")
            self.assertIn("已切换到 session:", text)
            self.assertIn("session=provisional", text)
            self.assertIn("runtime_id=pending:opencode", text)
            self.assertIn("tmux=opencode", text)

    def test_promote_runtime_record_migrates_pending_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:

            class _NoBootstrapDaemon(_TestDaemon):
                def _bootstrap_runtime(self) -> None:
                    return None

            pending_thread = "pending:opencode"
            real_thread = "ses_real_opencode_session"
            state = BridgeState(
                active_session_id=pending_thread,
                active_tmux_session="opencode",
                mirror_offsets={pending_thread: 42},
                recent_delivery_cursors={pending_thread: 7},
                last_progress_summaries={pending_thread: "working"},
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "✅ parked",
                        "created_at": "2026-04-04T00:00:00+00:00",
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": pending_thread,
                        "tmux_session": "opencode",
                        "attempt_count": 1,
                        "last_attempt_at": "2026-04-04T00:00:00+00:00",
                        "last_error": "",
                    }
                ],
                sessions={
                    pending_thread: SessionRecord(
                        thread_id=pending_thread,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live-provisional",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="opencode",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="opencode",
                    exists=True,
                    pane_command="node",
                    thread_id=pending_thread,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            daemon = _NoBootstrapDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            record = daemon._promote_runtime_record(
                old_thread_id=pending_thread,
                new_thread_id=real_thread,
                tmux_session="opencode",
                fallback_label="opencode",
                fallback_cwd="/tmp",
                fallback_source="tmux-live",
            )
            assert record is not None
            self.assertEqual(state.active_session_id, real_thread)
            self.assertEqual(state.active_tmux_session, "opencode")
            self.assertNotIn(pending_thread, state.sessions)
            self.assertIn(real_thread, state.sessions)
            self.assertEqual(state.sessions[real_thread].label, "opencode")
            self.assertEqual(state.get_mirror_offset(real_thread), 42)
            self.assertEqual(state.get_recent_delivery_cursor(real_thread), 7)
            self.assertEqual(state.get_last_progress_summary(real_thread), "working")
            self.assertEqual(state.pending_outbox[0]["thread_id"], real_thread)

    def test_promote_runtime_record_updates_tmux_scope_when_thread_stays_same(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:

            class _NoBootstrapDaemon(_TestDaemon):
                def _bootstrap_runtime(self) -> None:
                    return None

            thread_id = "ses_real_opencode_session"
            state = BridgeState(
                active_session_id=thread_id,
                active_tmux_session="opencode",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "✅ parked",
                        "created_at": "2026-04-04T00:00:00+00:00",
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": thread_id,
                        "tmux_session": "opencode",
                        "attempt_count": 1,
                        "last_attempt_at": "2026-04-04T00:00:00+00:00",
                        "last_error": "",
                    }
                ],
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="gpt",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="opencode",
                    )
                },
            )
            daemon = _NoBootstrapDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=state,
            )

            record = daemon._promote_runtime_record(
                old_thread_id=thread_id,
                new_thread_id=thread_id,
                tmux_session="gpt",
                fallback_label="gpt",
                fallback_cwd="/tmp",
                fallback_source="tmux-live",
            )

            assert record is not None
            self.assertEqual(record.tmux_session, "gpt")
            self.assertEqual(state.sessions[thread_id].tmux_session, "gpt")
            self.assertEqual(state.active_tmux_session, "gpt")
            self.assertEqual(state.pending_outbox[0]["tmux_session"], "gpt")

    def test_current_mirror_thread_promotes_pending_active_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:

            class _NoBootstrapDaemon(_TestDaemon):
                def _bootstrap_runtime(self) -> None:
                    return None

            pending_thread = "pending:opencode"
            real_thread = "ses_real_opencode_session"
            state = BridgeState(
                active_session_id=pending_thread,
                active_tmux_session="opencode",
                sessions={
                    pending_thread: SessionRecord(
                        thread_id=pending_thread,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live-provisional",
                        created_at="2026-04-04T00:00:00+00:00",
                        updated_at="2026-04-04T00:00:00+00:00",
                        tmux_session="opencode",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="opencode",
                    exists=True,
                    pane_command="node",
                    thread_id=real_thread,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            daemon = _NoBootstrapDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            resolved = daemon._current_mirror_thread_id()
            self.assertEqual(resolved, real_thread)
            self.assertEqual(state.active_session_id, real_thread)
            self.assertEqual(state.active_tmux_session, "opencode")
            self.assertNotIn(pending_thread, state.sessions)
            self.assertIn(real_thread, state.sessions)

    def test_plain_message_submits_to_active_tmux_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_codex = "019d332d-1bc8-7151-a874-ab0fbc493747"
            thread_daedalus = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                active_session_id=thread_codex,
                active_tmux_session="daedalus",
                sessions={
                    thread_codex: SessionRecord(
                        thread_id=thread_codex,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    thread_daedalus: SessionRecord(
                        thread_id=thread_daedalus,
                        label="daedalus",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="daedalus",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_codex,
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="daedalus",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_daedalus,
                    pane_cwd="/tmp",
                ),
            ]
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-1",
                    "message_id": "m-1",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "route to daedalus"}}
                    ],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(runner.submitted, [(thread_daedalus, "route to daedalus")])
            self.assertEqual(state.active_tmux_session, "daedalus")
            self.assertEqual(state.active_session_id, thread_daedalus)

    def test_switch_prefers_live_tmux_match_over_historical_tmux_duplicates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_active = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            thread_live_codex = "11111111-2222-3333-4444-555555555555"
            thread_old_codex = "22222222-3333-4444-5555-666666666666"
            state = BridgeState(
                active_session_id=thread_active,
                sessions={
                    thread_active: SessionRecord(
                        thread_id=thread_active,
                        label="kairos",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="kairos",
                    ),
                    thread_live_codex: SessionRecord(
                        thread_id=thread_live_codex,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    thread_old_codex: SessionRecord(
                        thread_id=thread_old_codex,
                        label="old-codex",
                        cwd="/tmp",
                        source="historical",
                        created_at="2026-03-20T00:00:00+00:00",
                        updated_at="2026-03-20T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_thread_id = thread_live_codex
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="kairos",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_active,
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_live_codex,
                    pane_cwd="/tmp",
                ),
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            text = daemon._handle_command("/switch codex")
            self.assertEqual(state.active_session_id, thread_live_codex)
            self.assertEqual(state.active_tmux_session, "codex")
            self.assertIn("tmux=codex", text)

    def test_switch_prefers_exact_numeric_tmux_name_over_list_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_a = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            thread_b = "11111111-2222-3333-4444-555555555555"
            state = BridgeState(
                active_session_id=thread_a,
                sessions={
                    thread_a: SessionRecord(
                        thread_id=thread_a,
                        label="codex-main",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    thread_b: SessionRecord(
                        thread_id=thread_b,
                        label="one",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="1",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_a,
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="1",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_b,
                    pane_cwd="/tmp",
                ),
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            text = daemon._handle_command("/switch 1")
            self.assertEqual(state.active_session_id, thread_b)
            self.assertEqual(state.active_tmux_session, "1")
            self.assertIn("tmux=1", text)

    def test_switch_does_not_bind_stale_tmux_name_without_live_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_opencode = "ses_conflict"
            state = BridgeState(
                active_session_id=thread_opencode,
                sessions={
                    thread_opencode: SessionRecord(
                        thread_id=thread_opencode,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="opencode",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_opencode,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            text = daemon._handle_command("/switch codex")
            self.assertEqual(text, "没有找到 session: codex")

    def test_status_text_reports_runtime_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_conflict"
            state = BridgeState(
                active_session_id=thread_id,
                active_tmux_session="codex",
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_thread_id = thread_id
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="opencode",
                ),
                LiveRuntimeStatus(
                    tmux_session="opencode",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="opencode",
                ),
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            text = daemon._status_text()
            self.assertIn("status=runtime_conflict", text)
            self.assertIn("tmux=codex", text)
            self.assertIn("conflict=duplicate-runtime-id", text)

    def test_status_text_claude_no_thread_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(active_tmux_session="claude")
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="claude",
                    exists=True,
                    pane_command="claude",
                    thread_id=None,
                    pane_cwd="/tmp",
                    backend="claude",
                )
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            text = daemon._status_text()

            self.assertIn("status=no_thread", text)
            self.assertIn("backend=claude", text)
            self.assertIn("Claude Code", text)

    def test_short_thread_keeps_claude_runtime_id_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )

            self.assertEqual(
                daemon._short_thread("claude:9d39ab4b-c37d-4ff8-8104-e83cdd6c4307"),
                "claude:9d39ab4b-c37d-4ff8-8104-e83cdd6c4307",
            )

    def test_sessions_text_marks_active_tmux_when_thread_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_old_codex = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            thread_live_codex = "11111111-2222-3333-4444-555555555555"
            thread_kairos = "22222222-3333-4444-5555-666666666666"
            state = BridgeState(
                active_session_id=thread_old_codex,
                active_tmux_session="codex",
                sessions={
                    thread_old_codex: SessionRecord(
                        thread_id=thread_old_codex,
                        label="old-codex",
                        cwd="/tmp",
                        source="historical",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    thread_live_codex: SessionRecord(
                        thread_id=thread_live_codex,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    thread_kairos: SessionRecord(
                        thread_id=thread_kairos,
                        label="kairos",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="kairos",
                    ),
                },
            )
            runner = _FakeRunner()
            runner.runtime_thread_id = thread_live_codex
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_live_codex,
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="kairos",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_kairos,
                    pane_cwd="/tmp",
                ),
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            text = daemon._handle_command("/sessions")
            self.assertIn("*1 codex | 11111111 | codex live", text)
            self.assertIn(" 2 kairos | 22222222 | kairos live", text)

    def test_status_text_fail_closes_on_selected_tmux_without_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_codex = "019d332d-1bc8-7151-a874-ab0fbc493747"
            state = BridgeState(
                active_session_id=thread_codex,
                active_tmux_session="daedalus",
                sessions={
                    thread_codex: SessionRecord(
                        thread_id=thread_codex,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_codex,
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="daedalus",
                    exists=True,
                    pane_command="node",
                    thread_id=None,
                    pane_cwd="/tmp",
                ),
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            text = daemon._status_text()
            self.assertIn("status=no_thread", text)
            self.assertIn("tmux=daedalus", text)

    def test_current_mirror_thread_id_does_not_fallback_to_old_thread_when_selected_tmux_has_no_thread(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_codex = "019d332d-1bc8-7151-a874-ab0fbc493747"
            state = BridgeState(
                active_session_id=thread_codex,
                active_tmux_session="daedalus",
                sessions={
                    thread_codex: SessionRecord(
                        thread_id=thread_codex,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_codex,
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="daedalus",
                    exists=True,
                    pane_command="node",
                    thread_id=None,
                    pane_cwd="/tmp",
                ),
            ]
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            self.assertIsNone(daemon._current_mirror_thread_id())

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

    def test_bind_peer_same_user_rebind_preserves_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_2a9b9b59cffeTTpVS0iNdPRuoB"
            state = BridgeState(
                active_session_id=thread_id,
                active_tmux_session="opencode",
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                mirror_offsets={thread_id: 17},
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="opencode",
                    )
                },
            )
            runner = _FakeRunner()
            runner.rollout_sizes[thread_id] = 99
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )
            daemon._bind_peer("user@im.wechat", "ctx-2")
            self.assertEqual(state.get_mirror_offset(thread_id), 17)

    def test_new_prompt_does_not_skip_unread_mirror_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_2a9b9b59cffeTTpVS0iNdPRuoB"
            state = BridgeState(
                active_session_id=thread_id,
                active_tmux_session="opencode",
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                mirror_offsets={thread_id: 100},
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="opencode",
                    )
                },
            )
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="opencode",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            runner.rollout_sizes[thread_id] = 150
            runner.progresses[(thread_id, 100)] = ([], "UNREAD_FINAL", 150)
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-2",
                    "message_id": "msg-opencode",
                    "item_list": [{"type": 1, "text_item": {"text": "next prompt"}}],
                }
            )
            assert incoming is not None

            daemon._handle_incoming(incoming)

            self.assertEqual(state.get_mirror_offset(thread_id), 100)
            self.assertEqual(runner.submitted[-1][0], thread_id)
            self.assertEqual(
                fake_wechat.sent[-1],
                ("user@im.wechat", "ctx-2", "⚙️ 已注入 terminal。"),
            )

    def test_new_prompt_opencode_cursor_keeps_last_mutable_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_2a9b9b59cffeTTpVS0iNdPRuoB"
            state = BridgeState(
                active_session_id=thread_id,
                active_tmux_session="opencode",
                mirror_offsets={thread_id: 100},
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="opencode",
                    )
                },
            )
            runner = _FakeRunner()
            runner.progresses[(thread_id, 100)] = (["working"], "", 150)
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=runner,
                state=state,
            )

            daemon._sync_mirror_cursor_for_new_prompt(thread_id)

            self.assertEqual(state.get_mirror_offset(thread_id), 149)

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
                ("user@im.wechat", "ctx-1", "AUTO_FLUSH_OK"),
            )
            self.assertEqual(state.pending_outbox, [])

    def test_flush_pending_outbox_preserves_remaining_after_mid_flush_failure(
        self,
    ) -> None:
        class _FlakyWeChat(_FakeWeChat):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def send_text(
                self, *, to_user_id: str, context_token: str | None, text: str
            ):
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
                    {
                        "to": "user@im.wechat",
                        "text": "FIRST",
                        "created_at": "2026-03-26T00:00:00+00:00",
                    },
                    {
                        "to": "user@im.wechat",
                        "text": "SECOND",
                        "created_at": "2026-03-26T00:00:01+00:00",
                    },
                    {
                        "to": "user@im.wechat",
                        "text": "THIRD",
                        "created_at": "2026-03-26T00:00:02+00:00",
                    },
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
            self.assertEqual(fake_wechat.sent, [("user@im.wechat", "ctx-1", "FIRST")])
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
                ("user@im.wechat", "ctx-cmd", "PENDING_FINAL_OK"),
            )

    def test_notify_command_toggles_progress_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            self.assertEqual(daemon._notify_text("status"), "notify=system+plan+final")
            self.assertEqual(
                daemon._notify_text("on"),
                "notify=system+plan+progress+final",
            )
            self.assertTrue(daemon.state.progress_updates_enabled)
            self.assertEqual(daemon._notify_text("off"), "notify=system+plan+final")
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
            self.assertIn("/log 10", help_text)
            self.assertIn("当前可切换的 live tmux 列表", help_text)
            self.assertIn("当前 active live tmux session", help_text)
            self.assertIn("group 路由与个人默认对象隔离", help_text)
            self.assertIn("/catchup [n]", help_text)
            self.assertIn("/flush", help_text)

    def test_queue_text_summarizes_pending_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    pending_outbox=[
                        {
                            "to": "user@im.wechat",
                            "text": "FIRST PLAN",
                            "created_at": "2026-03-26T00:00:00+00:00",
                            "kind": "plan",
                            "origin": "desktop-mirror",
                            "thread_id": "thread-a",
                        },
                        {
                            "to": "user@im.wechat",
                            "text": "SECOND FINAL",
                            "created_at": "2026-03-26T00:01:00+00:00",
                            "kind": "final",
                            "origin": "desktop-mirror",
                            "thread_id": "thread-a",
                        },
                    ]
                ),
            )
            text = daemon._queue_text()
            self.assertIn("queue=2", text)
            self.assertIn("plan=1", text)
            self.assertIn("final=1", text)
            self.assertIn("sessions=1", text)
            self.assertIn("session[1]=unscoped|count=2|threads=1", text)
            self.assertIn("head=FIRST PLAN", text)
            self.assertIn("tail=SECOND FINAL", text)

    def test_queue_empty_still_shows_latest_effective_delivery_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            config.delivery_ledger_file.write_text(
                '{"seq":5,"ts":"2026-03-26T05:00:01+00:00","to":"user@im.wechat","status":"flushed","kind":"final","origin":"desktop-mirror","tmux_session":"codex","text":"FINAL_OK"}\n',
                encoding="utf-8",
            )
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    active_tmux_session="codex",
                ),
            )
            text = daemon._queue_text()
            self.assertIn("queue=0", text)
            self.assertIn("status=empty", text)
            self.assertIn("recent_effective_seq=5", text)
            self.assertIn("recent_effective=FINAL_OK", text)

    def test_queue_text_breaks_out_multiple_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_a = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            thread_b = "11111111-2222-3333-4444-555555555555"
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    active_session_id=thread_b,
                    sessions={
                        thread_a: SessionRecord(
                            thread_id=thread_a,
                            label="codex",
                            cwd="/tmp",
                            source="tmux-live",
                            created_at="2026-03-26T00:00:00+00:00",
                            updated_at="2026-03-26T00:00:00+00:00",
                            tmux_session="codex",
                        ),
                        thread_b: SessionRecord(
                            thread_id=thread_b,
                            label="kairos",
                            cwd="/tmp",
                            source="tmux-live",
                            created_at="2026-03-26T00:00:00+00:00",
                            updated_at="2026-03-26T00:00:00+00:00",
                            tmux_session="kairos",
                        ),
                    },
                    pending_outbox=[
                        {
                            "to": "user@im.wechat",
                            "text": "FIRST PLAN",
                            "created_at": "2026-03-26T00:00:00+00:00",
                            "kind": "plan",
                            "origin": "desktop-mirror",
                            "thread_id": thread_a,
                        },
                        {
                            "to": "user@im.wechat",
                            "text": "SECOND FINAL",
                            "created_at": "2026-03-26T00:01:00+00:00",
                            "kind": "final",
                            "origin": "desktop-mirror",
                            "thread_id": thread_b,
                        },
                    ],
                ),
            )
            text = daemon._queue_text()
            self.assertIn("active_tmux=codex", text)
            self.assertIn("visible_now=1", text)
            self.assertIn("waiting_other_sessions=1", text)
            self.assertIn("sessions=2", text)
            self.assertIn("session[1]=*codex|count=1|threads=1", text)
            self.assertIn("session[2]=kairos|count=1|threads=1", text)
            self.assertIn("head=FIRST PLAN", text)
            self.assertIn("tail_any=SECOND FINAL", text)

    def test_queue_text_marks_waiting_head_when_active_tmux_has_no_visible_backlog(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_a = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    active_tmux_session="daedalus",
                    sessions={
                        thread_a: SessionRecord(
                            thread_id=thread_a,
                            label="codex",
                            cwd="/tmp",
                            source="tmux-live",
                            created_at="2026-03-26T00:00:00+00:00",
                            updated_at="2026-03-26T00:00:00+00:00",
                            tmux_session="codex",
                        ),
                    },
                    pending_outbox=[
                        {
                            "to": "user@im.wechat",
                            "text": "CODEX ONLY",
                            "created_at": "2026-03-26T00:00:00+00:00",
                            "kind": "progress",
                            "origin": "desktop-mirror",
                            "thread_id": thread_a,
                            "tmux_session": "codex",
                        },
                    ],
                ),
            )
            daemon.state.active_tmux_session = "daedalus"
            text = daemon._queue_text()
            self.assertIn("active_tmux=daedalus", text)
            self.assertIn("visible_now=0", text)
            self.assertIn("waiting_other_sessions=1", text)
            self.assertIn("head_waiting_session=codex", text)
            self.assertIn("head_waiting=CODEX ONLY", text)
            self.assertNotIn("head=CODEX ONLY", text)

    def test_catchup_trims_visible_scope_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    active_tmux_session="daedalus",
                    pending_outbox=[
                        {
                            "to": "user@im.wechat",
                            "text": "OLD ONE",
                            "created_at": "2026-03-26T00:00:00+00:00",
                            "kind": "progress",
                            "origin": "desktop-mirror",
                            "thread_id": "thread-daedalus",
                            "tmux_session": "daedalus",
                        },
                        {
                            "to": "user@im.wechat",
                            "text": "OLD TWO",
                            "created_at": "2026-03-26T00:00:01+00:00",
                            "kind": "progress",
                            "origin": "desktop-mirror",
                            "thread_id": "thread-daedalus",
                            "tmux_session": "daedalus",
                        },
                        {
                            "to": "user@im.wechat",
                            "text": "KEEP ME",
                            "created_at": "2026-03-26T00:00:02+00:00",
                            "kind": "progress",
                            "origin": "desktop-mirror",
                            "thread_id": "thread-daedalus",
                            "tmux_session": "daedalus",
                        },
                        {
                            "to": "user@im.wechat",
                            "text": "OTHER SESSION",
                            "created_at": "2026-03-26T00:00:03+00:00",
                            "kind": "progress",
                            "origin": "desktop-mirror",
                            "thread_id": "thread-codex",
                            "tmux_session": "codex",
                        },
                    ],
                ),
            )
            daemon.state.active_tmux_session = "daedalus"
            text = daemon._catchup_text("1")
            self.assertIn("catchup=ok", text)
            self.assertIn("scope=daedalus", text)
            self.assertIn("dropped=2", text)
            self.assertIn("kept=1", text)
            self.assertEqual(
                [item["text"] for item in daemon.state.pending_outbox],
                ["OTHER SESSION", "KEEP ME"],
            )

    def test_catchup_reports_empty_when_no_visible_scope_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    active_tmux_session="daedalus",
                    pending_outbox=[
                        {
                            "to": "user@im.wechat",
                            "text": "OTHER SESSION",
                            "created_at": "2026-03-26T00:00:03+00:00",
                            "kind": "progress",
                            "origin": "desktop-mirror",
                            "thread_id": "thread-codex",
                            "tmux_session": "codex",
                        },
                    ],
                ),
            )
            daemon.state.active_tmux_session = "daedalus"
            text = daemon._catchup_text("")
            self.assertIn("catchup=empty", text)
            self.assertIn("scope=daedalus", text)

    def test_duplicate_pending_message_is_not_appended_twice(self) -> None:
        state = BridgeState()
        state.enqueue_pending_with_meta(
            to_user_id="user@im.wechat",
            text="SAME",
            kind="plan",
            origin="desktop-mirror",
            thread_id="thread-1",
            tmux_session=None,
            error="ret=-2",
        )
        state.enqueue_pending_with_meta(
            to_user_id="user@im.wechat",
            text="SAME",
            kind="plan",
            origin="desktop-mirror",
            thread_id="thread-1",
            tmux_session=None,
            error="ret=-2",
        )
        self.assertEqual(len(state.pending_outbox), 1)
        self.assertEqual(state.pending_outbox[0]["attempt_count"], 2)

    def test_context_failure_pauses_background_outbox_retry_until_rebind(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "PENDING_FINAL_OK",
                        "created_at": "2026-03-26T00:00:00+00:00",
                        "kind": "final",
                        "origin": "wechat-prompt-submitted",
                        "thread_id": "thread-1",
                    }
                ],
            )
            fake_wechat = _FakeWeChat()
            fake_wechat.fail = True
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._flush_bound_outbox_if_any()
            self.assertTrue(state.outbox_waiting_for_bind)
            self.assertEqual(len(state.pending_outbox), 1)

            attempts_after_failure = len(fake_wechat.sent)
            daemon._flush_bound_outbox_if_any()
            self.assertEqual(len(fake_wechat.sent), attempts_after_failure)
            self.assertEqual(len(state.pending_outbox), 1)

            daemon._bind_peer("user@im.wechat", "ctx-2")
            self.assertFalse(state.outbox_waiting_for_bind)

    def test_desktop_mirror_backlog_does_not_stay_blocked_by_wait_for_bind(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                outbox_waiting_for_bind=True,
                active_tmux_session="codex",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "PENDING_MIRROR_OK",
                        "created_at": "2026-03-26T00:00:00+00:00",
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": "thread-1",
                        "tmux_session": "codex",
                    }
                ],
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._flush_bound_outbox_if_any()
            self.assertEqual(
                fake_wechat.sent, [("user@im.wechat", None, "PENDING_MIRROR_OK")]
            )
            self.assertEqual(state.pending_outbox, [])

    def test_desktop_mirror_ret_minus_2_retries_via_backoff_without_rebind(
        self,
    ) -> None:
        """Under E, a desktop-mirror item explicitly marked for
        rebind-retry (awaiting_rebind_retry=1) no longer needs a real
        _bind_peer call to drain: once its exponential backoff elapses the
        retry loop attempts it on its own, with outbox_waiting_for_bind
        still True. attempt_count=2 → 4s backoff, last_attempt_at=10s ago
        → eligible."""
        with tempfile.TemporaryDirectory() as tmpdir:
            created_at = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
            last_attempt = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                outbox_waiting_for_bind=True,  # carryover from prior failure
                active_tmux_session="codex",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "RETRY_NOW_NO_REBIND",
                        "created_at": created_at,
                        "last_attempt_at": last_attempt,
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": "thread-1",
                        "tmux_session": "codex",
                        "attempt_count": 2,
                        "last_error": "ret=-2",
                        "awaiting_rebind_retry": "1",
                        "rebind_retry_group": "group-1",
                    }
                ],
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._flush_bound_outbox_if_any()

            self.assertEqual(
                fake_wechat.sent,
                [("user@im.wechat", None, "RETRY_NOW_NO_REBIND")],
            )
            self.assertEqual(state.pending_outbox, [])

    def test_pending_item_within_backoff_is_skipped(self) -> None:
        """Backoff prevents hammering: attempt_count=1 → 2s minimum between
        attempts. Item stamped `last_attempt_at` now is skipped on the
        next retry loop tick and stays in the queue."""
        with tempfile.TemporaryDirectory() as tmpdir:
            last_attempt = datetime.now(UTC).isoformat()
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                active_tmux_session="codex",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "TOO_SOON_TO_RETRY",
                        "created_at": last_attempt,
                        "last_attempt_at": last_attempt,
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": "thread-1",
                        "tmux_session": "codex",
                        "attempt_count": 1,
                        "last_error": "ret=-2",
                        "awaiting_rebind_retry": "1",
                        "rebind_retry_group": "group-1",
                    }
                ],
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._flush_bound_outbox_if_any()

            self.assertEqual(fake_wechat.sent, [])
            self.assertEqual(len(state.pending_outbox), 1)

    def test_prune_stale_desktop_mirror_backlog_never_drops_finals(self) -> None:
        """Owner policy: pending desktop-mirror items are never dropped by
        age, regardless of ret=-2 history, awaiting_rebind_retry flag, or
        inactive-thread status. _prune_stale_desktop_mirror_backlog is now
        a no-op."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                active_session_id="thread-active",
                active_tmux_session="codex",
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "OLD_INACTIVE_THREAD_FINAL",
                        "created_at": (
                            datetime.now(UTC) - timedelta(hours=1)
                        ).isoformat(),
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": "thread-inactive",
                        "tmux_session": "kimi0",
                        "attempt_count": 5,
                        "last_error": "ret=-2",
                    },
                    {
                        "to": "user@im.wechat",
                        "text": "OLD_PROGRESS",
                        "created_at": (
                            datetime.now(UTC) - timedelta(hours=2)
                        ).isoformat(),
                        "kind": "progress",
                        "origin": "desktop-mirror",
                        "thread_id": "thread-inactive",
                        "tmux_session": "kimi0",
                    },
                ],
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._prune_stale_desktop_mirror_backlog()

            self.assertEqual(fake_wechat.sent, [])
            # Both items survive — no more age-based drop for any reason.
            self.assertEqual(len(state.pending_outbox), 2)

    def test_ambiguous_desktop_mirror_final_retries_after_bind_and_flushes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                active_tmux_session="codex",
            )
            fake_wechat = _ChunkFailWeChat(fail_on_call=2)
            config = self._make_config(Path(tmpdir), frozenset())
            object.__setattr__(config, "text_chunk_limit", 5)
            daemon = _TestDaemon(
                config=config,
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._reply(
                "user@im.wechat",
                "ctx-1",
                "1234567890ABCDE",
                kind="final",
                origin="desktop-mirror",
                thread_id="thread-1",
                tmux_session="codex",
            )
            self.assertTrue(state.outbox_waiting_for_bind)
            self.assertEqual(len(state.pending_outbox), 3)

            attempts_after_failure = len(fake_wechat.sent)
            daemon._flush_bound_outbox_if_any()
            self.assertEqual(len(fake_wechat.sent), attempts_after_failure)
            self.assertEqual(len(state.pending_outbox), 3)

            daemon._bind_peer("user@im.wechat", "ctx-2")
            daemon._flush_bound_outbox_if_any()

            self.assertFalse(state.outbox_waiting_for_bind)
            self.assertEqual(
                fake_wechat.sent,
                [
                    ("user@im.wechat", None, "✅ 123"),
                    ("user@im.wechat", None, "45678"),
                    ("user@im.wechat", None, "90ABC"),
                    ("user@im.wechat", None, "DE"),
                ],
            )
            self.assertEqual(state.pending_outbox, [])

    def test_ret_minus_2_items_keep_retrying_instead_of_suppressed(self) -> None:
        """Owner policy: desktop-mirror finals with prior ret=-2 retry
        indefinitely via backoff instead of being dropped via
        ambiguous_desktop_mirror_ret_minus_2 suppression. Duplication on
        eventual success is acceptable; silent loss is not."""
        old_attempt = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                active_tmux_session="codex",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "WILL_EVENTUALLY_SUCCEED",
                        "created_at": "2026-04-17T00:00:00+00:00",
                        "last_attempt_at": old_attempt,
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": "thread-1",
                        "tmux_session": "codex",
                        "attempt_count": 5,  # would have been suppressed pre-F
                        "last_error": "ret=-2",
                    }
                ],
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._flush_bound_outbox_if_any()

            # Item delivered — not suppressed.
            self.assertEqual(
                fake_wechat.sent,
                [("user@im.wechat", None, "WILL_EVENTUALLY_SUCCEED")],
            )
            self.assertEqual(state.pending_outbox, [])

    def test_merge_external_state_imports_cli_pending_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._make_config(Path(tmpdir), frozenset())
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                active_session_id="thread-1",
                active_tmux_session="codex",
            )
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=state,
            )

            daemon._save_state()

            external = BridgeState.load(config.state_file)
            external.enqueue_pending_with_meta(
                to_user_id="user@im.wechat",
                text="CLI_PENDING",
                kind="relay",
                origin="desktop-direct",
                thread_id="thread-1",
                tmux_session="codex",
                error="ret=-2",
            )
            time.sleep(0.01)
            external.save(config.state_file)

            daemon._merge_external_state()

            self.assertEqual(len(daemon.state.pending_outbox), 1)
            self.assertEqual(daemon.state.pending_outbox[0]["text"], "CLI_PENDING")
            self.assertEqual(daemon.state.pending_outbox[0]["origin"], "desktop-direct")

    def test_wait_for_bind_only_blocks_context_bound_items_not_desktop_pushes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                outbox_waiting_for_bind=True,
                active_tmux_session="codex",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "PENDING_ACK",
                        "created_at": "2026-03-26T00:00:00+00:00",
                        "kind": "progress",
                        "origin": "wechat-prompt-submitted",
                        "thread_id": "thread-1",
                        "tmux_session": "codex",
                    },
                    {
                        "to": "user@im.wechat",
                        "text": "PENDING_MIRROR_OK",
                        "created_at": "2026-03-26T00:00:01+00:00",
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": "thread-1",
                        "tmux_session": "codex",
                    },
                ],
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._flush_bound_outbox_if_any()

            self.assertEqual(
                fake_wechat.sent, [("user@im.wechat", None, "PENDING_MIRROR_OK")]
            )
            self.assertEqual(len(state.pending_outbox), 1)
            self.assertEqual(
                state.pending_outbox[0]["origin"], "wechat-prompt-submitted"
            )

    def test_desktop_direct_pending_retry_uses_bound_context_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                active_tmux_session="codex",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "DIRECT_OK",
                        "created_at": "2026-03-26T00:00:00+00:00",
                        "kind": "relay",
                        "origin": "desktop-direct",
                        "thread_id": "thread-1",
                        "tmux_session": "codex",
                    }
                ],
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._flush_bound_outbox_if_any()

            self.assertEqual(
                fake_wechat.sent, [("user@im.wechat", "ctx-1", "DIRECT_OK")]
            )
            self.assertEqual(state.pending_outbox, [])

    def test_queue_text_marks_waiting_for_next_wechat_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    outbox_waiting_for_bind=True,
                    pending_outbox=[
                        {
                            "to": "user@im.wechat",
                            "text": "SECOND FINAL",
                            "created_at": "2026-03-26T00:01:00+00:00",
                            "kind": "final",
                            "origin": "desktop-mirror",
                            "thread_id": "thread-a",
                        },
                    ],
                ),
            )
            text = daemon._queue_text()
            self.assertIn("wait=next-wechat-message", text)
            self.assertIn("deliverable_now=1", text)
            self.assertNotIn("blocked_for_rebind=", text)

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

    def test_image_without_message_type_is_still_accepted(self) -> None:
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
                    "context_token": "ctx-image",
                    "message_id": "msg-image",
                    "item_list": [
                        {
                            "type": 2,
                            "image_item": {"url": "https://example.com/test.jpg"},
                        }
                    ],
                }
            )
            self.assertIsNotNone(incoming)
            assert incoming is not None
            self.assertEqual(len(incoming.images), 1)
            self.assertEqual(incoming.images[0].url, "https://example.com/test.jpg")

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

    def test_prompt_is_submitted_to_live_codex_and_acknowledged_immediately(
        self,
    ) -> None:
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

    def test_image_prompt_is_submitted_with_local_file_path(self) -> None:
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
                    "context_token": "ctx-image",
                    "message_id": "msg-image-1",
                    "item_list": [
                        {
                            "type": 2,
                            "image_item": {"url": "https://example.com/test.jpg"},
                        },
                        {"type": 1, "text_item": {"text": "看下这张图"}},
                    ],
                }
            )
            self.assertIsNotNone(incoming)
            assert incoming is not None
            with patch(
                "daedalus_wechat.daemon.download_incoming_image",
                return_value=SavedIncomingImage(
                    index=0,
                    path=Path("/tmp/incoming_media/msg-image-1_1.jpg"),
                    source_url="https://example.com/test.jpg",
                    content_type="image/jpeg",
                    size_bytes=1234,
                ),
            ):
                daemon._handle_incoming(incoming)
            submitted_prompt = runner.submitted[-1][1]
            self.assertEqual(
                submitted_prompt,
                "image 1: /tmp/incoming_media/msg-image-1_1.jpg；Owner 消息：看下这张图",
            )
            self.assertIn("/tmp/incoming_media/msg-image-1_1.jpg", submitted_prompt)
            self.assertIn("看下这张图", submitted_prompt)
            self.assertNotIn("\n", submitted_prompt)
            self.assertNotIn("本地图片文件：", submitted_prompt)
            self.assertNotIn("Owner 通过微信发送了图片", submitted_prompt)
            self.assertNotIn("如果你的判断依赖图片", submitted_prompt)
            self.assertEqual(
                fake_wechat.sent[-1],
                (
                    "user@im.wechat",
                    "ctx-image",
                    "⚙️ 已收到 1 张图片并注入 terminal。",
                ),
            )

    def test_image_only_prompt_stays_neutral_without_auto_interpret_instruction(
        self,
    ) -> None:
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
                    "context_token": "ctx-image-only",
                    "message_id": "msg-image-only",
                    "item_list": [
                        {
                            "type": 2,
                            "image_item": {"url": "https://example.com/test.jpg"},
                        }
                    ],
                }
            )
            assert incoming is not None
            with patch(
                "daedalus_wechat.daemon.download_incoming_image",
                return_value=SavedIncomingImage(
                    index=0,
                    path=Path("/tmp/incoming_media/msg-image-only_1.jpg"),
                    source_url="https://example.com/test.jpg",
                    content_type="image/jpeg",
                    size_bytes=1234,
                ),
            ):
                daemon._handle_incoming(incoming)

            submitted_prompt = runner.submitted[-1][1]
            self.assertEqual(
                submitted_prompt,
                "image 1: /tmp/incoming_media/msg-image-only_1.jpg",
            )
            self.assertNotIn("\n", submitted_prompt)
            self.assertNotIn("本地图片文件：", submitted_prompt)
            self.assertNotIn("Owner 通过微信发送了图片", submitted_prompt)
            self.assertNotIn("Owner 没有附加文字。", submitted_prompt)
            self.assertNotIn("如果你的判断依赖图片", submitted_prompt)
            self.assertNotIn("请直接检查图片", submitted_prompt)

    def test_multiline_text_prompt_is_flattened_before_submission(self) -> None:
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
                    "context_token": "ctx-multiline",
                    "message_id": "msg-multiline",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "第一段\n\n第二段\t第三段"}}
                    ],
                }
            )
            assert incoming is not None

            daemon._handle_incoming(incoming)

            self.assertEqual(runner.submitted[-1][1], "第一段 第二段 第三段")

    def test_image_without_direct_url_fails_closed(self) -> None:
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
                    "context_token": "ctx-image",
                    "message_id": "msg-image-2",
                    "item_list": [
                        {
                            "type": 2,
                            "image_item": {
                                "media": {"encrypt_query_param": "abc"},
                                "aeskey": "00112233",
                            },
                        }
                    ],
                }
            )
            self.assertIsNotNone(incoming)
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(runner.submitted, [])
            self.assertIn("无法取回可用本地文件", fake_wechat.sent[-1][2])

    def test_encrypted_image_without_direct_url_is_downloaded_and_submitted(
        self,
    ) -> None:
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
                    "context_token": "ctx-image",
                    "message_id": "msg-image-3",
                    "item_list": [
                        {
                            "type": 2,
                            "image_item": {
                                "media": {
                                    "encrypt_query_param": "enc-param",
                                    "aes_key": "MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
                                },
                                "aeskey": "00112233445566778899aabbccddeeff",
                            },
                        }
                    ],
                }
            )
            assert incoming is not None
            with patch(
                "daedalus_wechat.daemon.download_incoming_image",
                return_value=SavedIncomingImage(
                    index=0,
                    path=Path("/tmp/incoming_media/msg-image-3_1.png"),
                    source_url="https://ilinkai.weixin.qq.com/download?encrypted_query_param=enc-param",
                    content_type="",
                    size_bytes=2222,
                ),
            ):
                daemon._handle_incoming(incoming)
            self.assertIn(
                "/tmp/incoming_media/msg-image-3_1.png", runner.submitted[-1][1]
            )
            self.assertEqual(
                fake_wechat.sent[-1],
                (
                    "user@im.wechat",
                    "ctx-image",
                    "⚙️ 已收到 1 张图片并注入 terminal。",
                ),
            )

    def test_parse_incoming_image_supports_thumb_media_and_field_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-image",
                    "message_id": "msg-image-4",
                    "item_list": [
                        {
                            "type": 2,
                            "image_item": {
                                "thumb_media": {
                                    "encrypted_query_param": "thumb-enc",
                                    "aesKey": "MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
                                },
                                "aes_key": "00112233445566778899aabbccddeeff",
                            },
                        }
                    ],
                }
            )
            assert incoming is not None
            self.assertEqual(len(incoming.images), 1)
            image = incoming.images[0]
            self.assertEqual(image.media_source, "thumb_media")
            self.assertEqual(image.media_encrypt_query_param, "thumb-enc")
            self.assertEqual(image.aes_key, "00112233445566778899aabbccddeeff")

    def test_parse_incoming_file_supports_media_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-file",
                    "message_id": "msg-file-1",
                    "item_list": [
                        {
                            "type": 4,
                            "file_item": {
                                "file_name": "report.pdf",
                                "media": {
                                    "encrypt_query_param": "file-enc",
                                    "aes_key": "MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
                                    "full_url": "https://cdn.example.com/file.bin",
                                },
                            },
                        }
                    ],
                }
            )
            assert incoming is not None
            self.assertEqual(len(incoming.files), 1)
            file_ref = incoming.files[0]
            self.assertEqual(file_ref.file_name, "report.pdf")
            self.assertEqual(file_ref.media_encrypt_query_param, "file-enc")
            self.assertEqual(
                file_ref.media_aes_key,
                "MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
            )
            self.assertEqual(
                file_ref.media_full_url, "https://cdn.example.com/file.bin"
            )

    def test_parse_incoming_video_supports_media_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            incoming = daemon._parse_incoming(
                {
                    "message_type": 1,
                    "from_user_id": "user@im.wechat",
                    "context_token": "ctx-video",
                    "message_id": "msg-video-1",
                    "item_list": [
                        {
                            "type": 5,
                            "video_item": {
                                "media": {
                                    "encrypt_query_param": "video-enc",
                                    "aes_key": "MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
                                    "full_url": "https://cdn.example.com/clip.mp4",
                                },
                                "thumb_media": {"encrypt_query_param": "thumb-enc"},
                            },
                        }
                    ],
                }
            )
            assert incoming is not None
            self.assertEqual(len(incoming.videos), 1)
            video_ref = incoming.videos[0]
            self.assertEqual(video_ref.media_encrypt_query_param, "video-enc")
            self.assertEqual(
                video_ref.media_aes_key,
                "MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
            )
            self.assertEqual(
                video_ref.media_full_url, "https://cdn.example.com/clip.mp4"
            )

    def test_incoming_file_is_downloaded_and_submitted(self) -> None:
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
                    "context_token": "ctx-file",
                    "message_id": "msg-file-2",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "看这个文件"}},
                        {
                            "type": 4,
                            "file_item": {
                                "file_name": "report.pdf",
                                "media": {
                                    "encrypt_query_param": "file-enc",
                                    "aes_key": "MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
                                },
                            },
                        },
                    ],
                }
            )
            assert incoming is not None
            with patch(
                "daedalus_wechat.daemon.download_incoming_file",
                return_value=SavedIncomingFile(
                    index=0,
                    path=Path("/tmp/incoming_media/report.pdf"),
                    source_url="https://cdn.example.com/report.pdf",
                    content_type="application/pdf",
                    size_bytes=3333,
                    file_name="report.pdf",
                ),
            ):
                daemon._handle_incoming(incoming)
            self.assertIn("/tmp/incoming_media/report.pdf", runner.submitted[-1][1])
            self.assertEqual(
                fake_wechat.sent[-1],
                (
                    "user@im.wechat",
                    "ctx-file",
                    "⚙️ 已收到 1 个文件并注入 terminal。",
                ),
            )

    def test_incoming_video_is_downloaded_and_submitted(self) -> None:
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
                    "context_token": "ctx-video",
                    "message_id": "msg-video-2",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "看这个视频"}},
                        {
                            "type": 5,
                            "video_item": {
                                "media": {
                                    "encrypt_query_param": "video-enc",
                                    "aes_key": "MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
                                },
                            },
                        },
                    ],
                }
            )
            assert incoming is not None
            with patch(
                "daedalus_wechat.daemon.download_incoming_video",
                return_value=SavedIncomingVideo(
                    index=0,
                    path=Path("/tmp/incoming_media/clip.mp4"),
                    source_url="https://cdn.example.com/clip.mp4",
                    content_type="video/mp4",
                    size_bytes=4444,
                ),
            ):
                daemon._handle_incoming(incoming)
            self.assertIn("/tmp/incoming_media/clip.mp4", runner.submitted[-1][1])
            self.assertEqual(
                fake_wechat.sent[-1],
                (
                    "user@im.wechat",
                    "ctx-video",
                    "⚙️ 已收到 1 个视频并注入 terminal。",
                ),
            )

    def test_file_without_aes_key_fails_closed(self) -> None:
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
                    "context_token": "ctx-file",
                    "message_id": "msg-file-3",
                    "item_list": [
                        {
                            "type": 4,
                            "file_item": {
                                "file_name": "report.pdf",
                                "media": {"encrypt_query_param": "file-enc"},
                            },
                        }
                    ],
                }
            )
            assert incoming is not None
            daemon._handle_incoming(incoming)
            self.assertEqual(runner.submitted, [])
            self.assertIn(
                "收到文件，但当前无法取回可用本地文件", fake_wechat.sent[-1][2]
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
            self.assertIn("scope=all", text)
            self.assertIn("progress one", text)
            self.assertIn("FINAL_OK", text)
            self.assertIn("[1][sent][progress][13:00:00] progress one", text)
            self.assertIn("next=/recent after 2", text)

    def test_recent_excludes_command_echo_history_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            config.delivery_ledger_file.write_text(
                "\n".join(
                    [
                        '{"seq":1,"ts":"2026-03-26T05:00:00+00:00","to":"user@im.wechat","status":"sent","kind":"progress","origin":"desktop-mirror","tmux_session":"codex","text":"live progress"}',
                        '{"seq":2,"ts":"2026-03-26T05:00:01+00:00","to":"user@im.wechat","status":"sent","kind":"command","origin":"wechat-command","tmux_session":"codex","text":"nested old transcript"}',
                        '{"seq":3,"ts":"2026-03-26T05:00:02+00:00","to":"user@im.wechat","status":"flushed","kind":"final","origin":"desktop-mirror","tmux_session":"codex","text":"live final"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    active_tmux_session="codex",
                ),
            )
            text = daemon._recent_text("10")
            self.assertIn("live progress", text)
            self.assertIn("live final", text)
            self.assertNotIn("nested old transcript", text)

    def test_recent_stays_with_latest_cluster_instead_of_crossing_old_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            config.delivery_ledger_file.write_text(
                "\n".join(
                    [
                        '{"seq":10,"ts":"2026-03-26T05:00:00+00:00","to":"user@im.wechat","status":"sent","kind":"progress","origin":"desktop-mirror","tmux_session":"codex","text":"very old progress"}',
                        '{"seq":11,"ts":"2026-03-26T05:00:02+00:00","to":"user@im.wechat","status":"sent","kind":"final","origin":"desktop-mirror","tmux_session":"codex","text":"very old final"}',
                        '{"seq":12,"ts":"2026-03-26T05:40:00+00:00","to":"user@im.wechat","status":"sent","kind":"progress","origin":"desktop-mirror","tmux_session":"codex","text":"current progress"}',
                        '{"seq":13,"ts":"2026-03-26T05:40:02+00:00","to":"user@im.wechat","status":"sent","kind":"final","origin":"desktop-mirror","tmux_session":"codex","text":"current final"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    active_tmux_session="codex",
                ),
            )
            text = daemon._recent_text("10")
            self.assertIn("current progress", text)
            self.assertIn("current final", text)
            self.assertNotIn("very old progress", text)
            self.assertNotIn("very old final", text)

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
            self.assertIn("scope=all", text)
            self.assertIn("three", text)
            self.assertNotIn("two", text)
            self.assertIn("next=/recent after 3", text)

    def test_recent_defaults_to_active_tmux_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            config.delivery_ledger_file.write_text(
                "\n".join(
                    [
                        '{"seq":1,"ts":"2026-03-26T05:00:00+00:00","to":"user@im.wechat","status":"sent","kind":"progress","origin":"desktop-mirror","tmux_session":"codex","text":"codex one"}',
                        '{"seq":2,"ts":"2026-03-26T05:00:01+00:00","to":"user@im.wechat","status":"sent","kind":"final","origin":"desktop-mirror","tmux_session":"daedalus","text":"daedalus final"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    active_tmux_session="daedalus",
                ),
            )
            daemon.state.active_tmux_session = "daedalus"
            text = daemon._recent_text("")
            self.assertIn("scope=daedalus", text)
            self.assertIn("daedalus final", text)
            self.assertNotIn("codex one", text)

    def test_recent_all_bypasses_active_tmux_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            config.delivery_ledger_file.write_text(
                "\n".join(
                    [
                        '{"seq":1,"ts":"2026-03-26T05:00:00+00:00","to":"user@im.wechat","status":"sent","kind":"progress","origin":"desktop-mirror","tmux_session":"codex","text":"codex one"}',
                        '{"seq":2,"ts":"2026-03-26T05:00:01+00:00","to":"user@im.wechat","status":"sent","kind":"final","origin":"desktop-mirror","tmux_session":"daedalus","text":"daedalus final"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    active_tmux_session="daedalus",
                ),
            )
            daemon.state.active_tmux_session = "daedalus"
            text = daemon._recent_text("all 10")
            self.assertIn("scope=all", text)
            self.assertIn("[codex] codex one", text)
            self.assertIn("[daedalus] daedalus final", text)

    def test_catchup_replays_latest_effective_messages_when_no_pending_backlog(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            config.delivery_ledger_file.write_text(
                "\n".join(
                    [
                        '{"seq":10,"ts":"2026-03-26T05:00:00+00:00","to":"user@im.wechat","status":"queued","kind":"progress","origin":"desktop-mirror","tmux_session":"codex","text":"retry noise"}',
                        '{"seq":11,"ts":"2026-03-26T05:00:01+00:00","to":"user@im.wechat","status":"flushed","kind":"progress","origin":"desktop-mirror","tmux_session":"codex","text":"real progress"}',
                        '{"seq":12,"ts":"2026-03-26T05:00:02+00:00","to":"user@im.wechat","status":"sent","kind":"final","origin":"desktop-mirror","tmux_session":"codex","text":"real final"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    active_tmux_session="codex",
                ),
            )
            text = daemon._catchup_text("")
            self.assertIn("catchup=ok", text)
            self.assertIn("scope=codex", text)
            self.assertIn("real progress", text)
            self.assertIn("real final", text)
            self.assertNotIn("retry noise", text)
            self.assertIn("next=/catchup", text)

    def test_catchup_advances_cursor_and_reports_up_to_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            config.delivery_ledger_file.write_text(
                "\n".join(
                    [
                        '{"seq":21,"ts":"2026-03-26T05:00:01+00:00","to":"user@im.wechat","status":"flushed","kind":"progress","origin":"desktop-mirror","tmux_session":"codex","text":"one"}',
                        '{"seq":22,"ts":"2026-03-26T05:00:02+00:00","to":"user@im.wechat","status":"sent","kind":"final","origin":"desktop-mirror","tmux_session":"codex","text":"two"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    active_tmux_session="codex",
                ),
            )
            first = daemon._catchup_text("")
            self.assertIn("catchup=ok", first)
            second = daemon._catchup_text("")
            self.assertIn("catchup=up_to_date", second)
            self.assertIn("last_seq=22", second)

    def test_catchup_resets_stale_cursor_and_anchors_to_latest_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            config.delivery_ledger_file.write_text(
                "\n".join(
                    [
                        '{"seq":27383,"ts":"2026-03-28T08:31:05+00:00","to":"user@im.wechat","status":"flushed","kind":"progress","origin":"desktop-mirror","tmux_session":"codex","text":"old cluster progress"}',
                        '{"seq":27384,"ts":"2026-03-28T08:31:07+00:00","to":"user@im.wechat","status":"sent","kind":"final","origin":"desktop-mirror","tmux_session":"codex","text":"old cluster final"}',
                        '{"seq":9238,"ts":"2026-03-30T09:20:40+00:00","to":"user@im.wechat","status":"flushed","kind":"progress","origin":"desktop-mirror","tmux_session":"codex","text":"current progress"}',
                        '{"seq":9239,"ts":"2026-03-30T09:20:41+00:00","to":"user@im.wechat","status":"sent","kind":"final","origin":"desktop-mirror","tmux_session":"codex","text":"current final"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    active_tmux_session="codex",
                    recent_delivery_cursors={"user@im.wechat|codex": 27384},
                ),
            )
            text = daemon._catchup_text("")
            self.assertIn("catchup=ok", text)
            self.assertIn("current progress", text)
            self.assertIn("current final", text)
            self.assertNotIn("old cluster progress", text)
            self.assertNotIn("old cluster final", text)
            self.assertEqual(
                daemon.state.get_recent_delivery_cursor("user@im.wechat|codex"), 9239
            )

    def test_stale_inactive_desktop_mirror_final_is_kept_for_later_scope_flush(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            active_thread = "active-thread"
            parked_thread = "parked-thread"
            state = BridgeState(
                active_session_id=active_thread,
                active_tmux_session="codex",
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "PARKED_FINAL",
                        "created_at": "2026-03-26T00:00:00+00:00",
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": parked_thread,
                        "tmux_session": "opencode",
                        "attempt_count": 1,
                        "last_error": "",
                    }
                ],
                sessions={
                    active_thread: SessionRecord(
                        thread_id=active_thread,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    parked_thread: SessionRecord(
                        thread_id=parked_thread,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="opencode",
                    ),
                },
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._prune_stale_desktop_mirror_backlog()

            self.assertEqual(fake_wechat.sent, [])
            self.assertEqual(
                [item["text"] for item in state.pending_outbox],
                ["PARKED_FINAL"],
            )

    def test_pending_desktop_progress_is_suppressed_when_progress_disabled(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                active_tmux_session="codex",
                progress_updates_enabled=False,
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "OLD_PROGRESS",
                        "created_at": "2026-03-26T00:00:00+00:00",
                        "kind": "progress",
                        "origin": "desktop-mirror",
                        "thread_id": "thread-1",
                        "tmux_session": "codex",
                    }
                ],
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )

            daemon._flush_bound_outbox_if_any()

            self.assertEqual(fake_wechat.sent, [])
            self.assertEqual(state.pending_outbox, [])

    def test_log_text_can_surface_recent_error_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            config = self._make_config(state_dir, frozenset())
            config.state_dir.mkdir(parents=True, exist_ok=True)
            runner = _FakeRunner()
            config.event_log_file.write_text(
                "\n".join(
                    [
                        '{"ts":"2026-03-26T05:00:00+00:00","kind":"incoming","payload":{"from":"user@im.wechat","body":"/status"}}',
                        f'{{"ts":"2026-03-26T05:00:01+00:00","kind":"queued_outgoing","payload":{{"to":"user@im.wechat","thread":"{runner.runtime_thread_id[:8]}","error":"ret=-2","text":"OLD"}}}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            daemon = _TestDaemon(
                config=config,
                wechat=_FakeWeChat(),
                runner=runner,
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    active_session_id=runner.runtime_thread_id,
                    active_tmux_session="codex",
                ),
            )
            text = daemon._log_text("errors 5")
            self.assertIn("log:", text)
            self.assertIn("errors_only=true", text)
            self.assertIn("queued_outgoing", text)
            self.assertIn("ret=-2", text)

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
            runner.progresses[(thread_id, 100)] = (
                ["我先检查 bridge 当前状态。"],
                "FINAL_OK",
                150,
            )
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
            self.assertEqual(
                state.get_last_progress_summary(thread_id), "我先检查 bridge 当前状态。"
            )

    def test_mirror_plan_survives_when_progress_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                active_session_id=thread_id,
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                progress_updates_enabled=False,
                mirror_offsets={thread_id: 100},
                sessions={},
            )
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            runner.progresses[(thread_id, 100)] = (
                [
                    PLAN_MARKER + "Plan\n1. 进行中: 保留 plan",
                    "这条 progress 不该发",
                ],
                "FINAL_OK",
                150,
            )
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            daemon._mirror_desktop_final_if_any()
            self.assertEqual(
                fake_wechat.sent,
                [
                    ("user@im.wechat", None, "📋 Plan\n1. 进行中: 保留 plan"),
                    ("user@im.wechat", None, "✅ FINAL_OK"),
                ],
            )

    def test_queue_command_is_retired(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            self.assertIn("queue=retired", daemon._handle_command("/queue"))

    def test_catchup_command_routes_to_catchup_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            text = daemon._handle_command("/catchup 5")
            self.assertNotIn("catchup=retired", text)
            self.assertIn("catchup=blocked", text)

    def test_flush_command_blocks_without_bound_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            text = daemon._handle_command("/flush")
            self.assertIn("flush=blocked", text)

    def test_flush_command_empty_when_nothing_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(
                    bound_user_id="user@im.wechat",
                    bound_context_token="ctx-1",
                ),
            )
            text = daemon._handle_command("/flush")
            self.assertIn("flush=empty", text)

    def test_flush_command_drains_pending_across_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "msg-codex",
                        "created_at": past,
                        "kind": "message",
                        "origin": "bridge",
                        "thread_id": "",
                        "tmux_session": "codex",
                        "attempt_count": 1,
                        "last_attempt_at": past,
                        "last_error": "",
                    },
                    {
                        "to": "user@im.wechat",
                        "text": "msg-alpha",
                        "created_at": past,
                        "kind": "message",
                        "origin": "bridge",
                        "thread_id": "",
                        "tmux_session": "alpha",
                        "attempt_count": 1,
                        "last_attempt_at": past,
                        "last_error": "",
                    },
                ],
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )
            text = daemon._handle_command("/flush")
            self.assertIn("flush=ok", text)
            self.assertIn("before=2", text)
            self.assertIn("after=0", text)
            sent_texts = [entry[2] for entry in fake_wechat.sent]
            self.assertIn("msg-codex", sent_texts)
            self.assertIn("msg-alpha", sent_texts)
            self.assertEqual(daemon.state.pending_outbox, [])

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

    def test_mirror_prefers_active_live_tmux_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_a = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            thread_b = "11111111-2222-3333-4444-555555555555"
            state = BridgeState(
                active_session_id=thread_b,
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                mirror_offsets={thread_a: 10, thread_b: 20},
                sessions={
                    thread_a: SessionRecord(
                        thread_id=thread_a,
                        label="codex-main",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    thread_b: SessionRecord(
                        thread_id=thread_b,
                        label="123",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="123",
                    ),
                },
            )
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_a,
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="123",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_b,
                    pane_cwd="/tmp",
                ),
            ]
            runner.finals[(thread_b, 20)] = ("ACTIVE_SWITCH_FINAL_OK", 30)
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            daemon._mirror_desktop_final_if_any()
            self.assertEqual(state.active_session_id, thread_b)
            self.assertEqual(
                fake_wechat.sent[-1],
                ("user@im.wechat", None, "✅ ACTIVE_SWITCH_FINAL_OK"),
            )
            self.assertEqual(state.get_mirror_offset(thread_b), 30)

    def test_mirror_does_not_leak_stale_final_after_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_thread = "019d332d-1bc8-7151-a874-ab0fbc493747"
            opencode_thread = "ses_2a9b9b59cffeTTpVS0iNdPRuoB"
            state = BridgeState(
                active_session_id=codex_thread,
                active_tmux_session="codex",
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                mirror_offsets={codex_thread: 100},
                sessions={
                    codex_thread: SessionRecord(
                        thread_id=codex_thread,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    opencode_thread: SessionRecord(
                        thread_id=opencode_thread,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="opencode",
                    ),
                },
            )
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            runner.runtime_thread_id = codex_thread
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )

            def _switch_during_scan(*, thread_id: str, start_offset: int):
                self.assertEqual(thread_id, codex_thread)
                self.assertEqual(start_offset, 100)
                daemon.state.active_session_id = opencode_thread
                daemon.state.active_tmux_session = "opencode"
                from daedalus_wechat.live_session import MirrorScan

                return MirrorScan(
                    progress_texts=[],
                    final_texts=["STALE_CODEX_FINAL"],
                    end_offset=150,
                )

            with patch.object(
                runner, "latest_mirror_since", side_effect=_switch_during_scan
            ):
                daemon._mirror_desktop_final_if_any()

            self.assertEqual(fake_wechat.sent, [])
            self.assertEqual(state.get_mirror_offset(codex_thread), 100)

    def test_mirror_keeps_cursor_when_final_send_is_queued(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_2a9b9b59cffeTTpVS0iNdPRuoB"
            state = BridgeState(
                active_session_id=thread_id,
                active_tmux_session="opencode",
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                mirror_offsets={thread_id: 100},
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="opencode",
                    )
                },
            )
            fake_wechat = _FakeWeChat()
            fake_wechat.fail = True
            runner = _FakeRunner()
            runner.runtime_thread_id = thread_id
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="opencode",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            runner.progresses[(thread_id, 100)] = ([], "OK", 150)
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )

            daemon._mirror_desktop_final_if_any()

            # Offset always advances to prevent duplicate delivery
            self.assertEqual(state.get_mirror_offset(thread_id), 150)

    def test_opencode_mirror_revisits_last_mutable_row_until_final_arrives(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "ses_2a9b9b59cffeTTpVS0iNdPRuoB"
            state = BridgeState(
                active_session_id=thread_id,
                active_tmux_session="opencode",
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                mirror_offsets={thread_id: 100},
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="opencode",
                    )
                },
            )
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="opencode",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ]
            runner.progresses[(thread_id, 100)] = (["working"], "", 150)
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )

            daemon._mirror_desktop_final_if_any()

            self.assertEqual(fake_wechat.sent, [])
            self.assertEqual(state.get_mirror_offset(thread_id), 149)

            runner.progresses[(thread_id, 149)] = ([], "FINAL_OK", 150)

            daemon._mirror_desktop_final_if_any()

            self.assertEqual(
                fake_wechat.sent,
                [("user@im.wechat", None, "✅ FINAL_OK")],
            )
            self.assertEqual(state.get_mirror_offset(thread_id), 150)

    def test_single_mode_inactive_mirror_final_is_sent_immediately(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_thread = "019d332d-1bc8-7151-a874-ab0fbc493747"
            opencode_thread = "ses_2a9b9b59cffeTTpVS0iNdPRuoB"
            state = BridgeState(
                active_session_id=codex_thread,
                active_tmux_session="codex",
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                mirror_offsets={opencode_thread: 100},
                sessions={
                    codex_thread: SessionRecord(
                        thread_id=codex_thread,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    opencode_thread: SessionRecord(
                        thread_id=opencode_thread,
                        label="opencode",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="opencode",
                    ),
                },
            )
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            runner.runtime_thread_id = codex_thread
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id=codex_thread,
                    pane_cwd="/tmp",
                    backend="codex",
                ),
                LiveRuntimeStatus(
                    tmux_session="opencode",
                    exists=True,
                    pane_command="node",
                    thread_id=opencode_thread,
                    pane_cwd="/tmp",
                    backend="opencode",
                ),
            ]
            runner.progresses[(opencode_thread, 100)] = ([], "OK", 150)
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )

            daemon._mirror_room_all_members()

            self.assertEqual(
                fake_wechat.sent,
                [("user@im.wechat", None, "[opencode] ✅ OK")],
            )
            self.assertEqual(state.get_mirror_offset(opencode_thread), 150)
            self.assertEqual(state.pending_outbox, [])

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
            plan_text = daemon._render_reply_text(
                "Plan\n1. 进行中: 实现 plan icon",
                kind="plan",
                origin="desktop-mirror",
            )
            self.assertEqual(final_text, "✅ 规则已收口。")
            self.assertEqual(system_text, "⚙️ 已注入 terminal。")
            self.assertEqual(progress_text, "⏳ 我先检查 bridge 当前状态。")
            self.assertEqual(plan_text, "📋 Plan\n1. 进行中: 实现 plan icon")

    def test_render_reply_text_flattens_markdown_for_wechat(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=_FakeWeChat(),
                runner=_FakeRunner(),
                state=BridgeState(),
            )
            rendered = daemon._render_reply_text(
                "**关键信息：**\n\n"
                "- 标题就是 `[WSL][tmux] opencode cannot copy text in WSL tmux`\n"
                "- 复制链路是 `opencode -> tmux -> 终端 -> 系统剪贴板`\n\n"
                "```tmux\n"
                "set -g allow-passthrough on\n"
                "set -g set-clipboard on\n"
                "```",
                kind="final",
                origin="desktop-mirror",
            )
            self.assertEqual(
                rendered,
                "✅ 关键信息：\n\n"
                "- 标题就是 '[WSL][tmux] opencode cannot copy text in WSL tmux'\n"
                "- 复制链路是 'opencode -> tmux -> 终端 -> 系统剪贴板'\n\n"
                "tmux:\n"
                "> set -g allow-passthrough on\n"
                "> set -g set-clipboard on",
            )

    def test_mirror_plan_with_dedicated_icon(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState(
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                active_session_id="019cdfe5-fa14-74a3-aa31-5451128ea58d",
                progress_updates_enabled=True,
            )
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            thread_id = runner.runtime_thread_id
            runner.progresses[(thread_id, 0)] = (
                [PLAN_MARKER + "Plan\n1. 进行中: 实现 plan icon"],
                "",
                10,
            )
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )
            daemon._mirror_desktop_final_if_any()
            self.assertEqual(
                fake_wechat.sent[-1],
                ("user@im.wechat", None, "📋 Plan\n1. 进行中: 实现 plan icon"),
            )

    def test_room_mode_dedups_repeated_identical_plan_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                room_mode_enabled=True,
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="beta",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="beta",
                    )
                },
                mirror_offsets={thread_id: 100},
            )
            fake_wechat = _FakeWeChat()
            runner = _FakeRunner()
            runner.runtime_statuses = [
                LiveRuntimeStatus(
                    tmux_session="beta",
                    exists=True,
                    pane_command="node",
                    thread_id=thread_id,
                    pane_cwd="/tmp",
                    backend="codex",
                )
            ]
            runner.progresses[(thread_id, 100)] = (
                [PLAN_MARKER + "Plan\n1. 进行中: SAME"],
                "",
                150,
            )
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )

            daemon._mirror_room_all_members()

            runner.progresses[(thread_id, 150)] = (
                [PLAN_MARKER + "Plan\n1. 进行中: SAME"],
                "",
                160,
            )
            daemon._mirror_room_all_members()

            self.assertEqual(
                fake_wechat.sent,
                [("user@im.wechat", None, "[beta] 📋 Plan\n1. 进行中: SAME")],
            )

    def test_active_mirror_dedups_repeated_identical_final_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_id = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                active_session_id=thread_id,
                active_tmux_session="codex",
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                mirror_offsets={thread_id: 100},
                sessions={
                    thread_id: SessionRecord(
                        thread_id=thread_id,
                        label="codex",
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
            runner.runtime_thread_id = thread_id
            runner.progresses[(thread_id, 100)] = ([], "FINAL_OK", 150)
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=runner,
                state=state,
            )

            daemon._mirror_desktop_final_if_any()

            runner.progresses[(thread_id, 150)] = ([], "FINAL_OK", 160)
            daemon._mirror_desktop_final_if_any()

            self.assertEqual(
                fake_wechat.sent,
                [("user@im.wechat", None, "✅ FINAL_OK")],
            )

    def test_desktop_progress_pending_queue_preserves_backlog_for_thread(self) -> None:
        state = BridgeState()
        state.enqueue_pending_with_meta(
            to_user_id="user@im.wechat",
            text="old progress",
            kind="progress",
            origin="desktop-mirror",
            thread_id="thread-1",
            tmux_session="codex",
        )
        state.enqueue_pending_with_meta(
            to_user_id="user@im.wechat",
            text="system ack",
            kind="progress",
            origin="wechat-prompt-submitted",
            thread_id="thread-1",
            tmux_session="codex",
        )
        state.enqueue_pending_with_meta(
            to_user_id="user@im.wechat",
            text="new progress",
            kind="progress",
            origin="desktop-mirror",
            thread_id="thread-1",
            tmux_session="codex",
        )
        self.assertEqual(
            [(item["origin"], item["text"]) for item in state.pending_outbox],
            [
                ("desktop-mirror", "old progress"),
                ("wechat-prompt-submitted", "system ack"),
                ("desktop-mirror", "new progress"),
            ],
        )

    def test_pending_outbox_tracks_overflow_drop_count(self) -> None:
        """pending_outbox caps at max_items (10000 under owner 'no loss'
        policy) and records overflow in pending_outbox_overflow_dropped.
        Oldest items are dropped first so the owner sees the freshest state."""
        state = BridgeState()
        for idx in range(10005):
            state.enqueue_pending_with_meta(
                to_user_id="user@im.wechat",
                text=f"msg-{idx}",
                kind="progress",
                origin="desktop-mirror",
                thread_id="thread-1",
                tmux_session="codex",
            )
        self.assertEqual(len(state.pending_outbox), 10000)
        self.assertEqual(state.pending_outbox_overflow_dropped, 5)
        self.assertEqual(state.pending_outbox[0]["text"], "msg-5")

    def test_reply_failure_queues_remaining_chunks(self) -> None:
        """Non-mirror origins queue remaining chunks on failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState()
            fake_wechat = _ChunkFailWeChat(fail_on_call=2)
            config = self._make_config(Path(tmpdir), frozenset())
            object.__setattr__(config, "text_chunk_limit", 5)
            daemon = _TestDaemon(
                config=config,
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )
            daemon._reply(
                "user@im.wechat",
                "ctx-1",
                "1234567890ABCDE",
                kind="final",
                origin="bridge",
                thread_id="thread-1",
            )
            self.assertEqual(fake_wechat.sent, [("user@im.wechat", "ctx-1", "✅ 123")])
            self.assertEqual(
                [item["text"] for item in state.pending_outbox],
                ["45678", "90ABC", "DE"],
            )

    def test_mirror_reply_failure_waits_for_next_bind_once(self) -> None:
        """Ambiguous desktop finals pause until the next bind refresh."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = BridgeState()
            fake_wechat = _ChunkFailWeChat(fail_on_call=2)
            config = self._make_config(Path(tmpdir), frozenset())
            object.__setattr__(config, "text_chunk_limit", 5)
            daemon = _TestDaemon(
                config=config,
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )
            daemon._reply(
                "user@im.wechat",
                "ctx-1",
                "1234567890ABCDE",
                kind="final",
                origin="desktop-mirror",
                thread_id="thread-1",
            )
            self.assertEqual(fake_wechat.sent, [("user@im.wechat", None, "✅ 123")])
            # Mirror messages queue normally for retry.
            self.assertEqual(
                [item["text"] for item in state.pending_outbox],
                ["45678", "90ABC", "DE"],
            )
            self.assertTrue(state.outbox_waiting_for_bind)
            self.assertEqual(
                {item.get("awaiting_rebind_retry") for item in state.pending_outbox},
                {"1"},
            )
            self.assertEqual(
                len(
                    {
                        item.get("rebind_retry_group", "")
                        for item in state.pending_outbox
                    }
                ),
                1,
            )

    def test_flush_bound_outbox_releases_owner_wide_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            thread_codex = "019d332d-1bc8-7151-a874-ab0fbc493747"
            thread_daedalus = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
            state = BridgeState(
                active_session_id=thread_daedalus,
                active_tmux_session="daedalus",
                bound_user_id="user@im.wechat",
                bound_context_token="ctx-1",
                sessions={
                    thread_codex: SessionRecord(
                        thread_id=thread_codex,
                        label="codex",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="codex",
                    ),
                    thread_daedalus: SessionRecord(
                        thread_id=thread_daedalus,
                        label="daedalus",
                        cwd="/tmp",
                        source="tmux-live",
                        created_at="2026-03-26T00:00:00+00:00",
                        updated_at="2026-03-26T00:00:00+00:00",
                        tmux_session="daedalus",
                    ),
                },
                pending_outbox=[
                    {
                        "to": "user@im.wechat",
                        "text": "CODEX BACKLOG",
                        "created_at": "2026-03-26T00:00:00+00:00",
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": thread_codex,
                        "tmux_session": "codex",
                    },
                    {
                        "to": "user@im.wechat",
                        "text": "DAEDALUS BACKLOG",
                        "created_at": "2026-03-26T00:00:01+00:00",
                        "kind": "final",
                        "origin": "desktop-mirror",
                        "thread_id": thread_daedalus,
                        "tmux_session": "daedalus",
                    },
                ],
            )
            fake_wechat = _FakeWeChat()
            daemon = _TestDaemon(
                config=self._make_config(Path(tmpdir), frozenset()),
                wechat=fake_wechat,
                runner=_FakeRunner(),
                state=state,
            )
            daemon.state.active_session_id = thread_daedalus
            daemon.state.active_tmux_session = "daedalus"
            daemon._flush_bound_outbox_if_any()
            self.assertEqual(
                fake_wechat.sent,
                [
                    ("user@im.wechat", None, "CODEX BACKLOG"),
                    ("user@im.wechat", None, "DAEDALUS BACKLOG"),
                ],
            )
            self.assertEqual(state.pending_outbox, [])


if __name__ == "__main__":
    unittest.main()
