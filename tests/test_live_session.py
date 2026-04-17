from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from daedalus_wechat.cli_backend import CliBackend
from daedalus_wechat.live_session import (
    PLAN_MARKER,
    LiveCodexSessionManager,
    LiveRuntimeStatus,
)
from daedalus_wechat.state import BridgeState, SessionRecord


class LiveSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = LiveCodexSessionManager(
            codex_bin="codex",
            opencode_bin="opencode",
            default_cwd=Path("/tmp"),
            canonical_tmux_session="codex",
        )

    def test_extract_final_text_ignores_commentary(self) -> None:
        event = {
            "type": "event_msg",
            "payload": {
                "type": "agent_message",
                "phase": "commentary",
                "message": "noise",
            },
        }
        self.assertEqual(self.runner._extract_final_text(event), "")

    def test_extract_final_text_reads_event_msg_final(self) -> None:
        event = {
            "type": "event_msg",
            "payload": {
                "type": "agent_message",
                "phase": "final_answer",
                "message": "FINAL_OK",
            },
        }
        self.assertEqual(self.runner._extract_final_text(event), "FINAL_OK")

    def test_extract_claude_text_end_turn_is_final(self) -> None:
        event = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "OK"}],
            },
        }
        self.assertEqual(self.runner._extract_claude_text(event), ("final", "OK"))

    def test_extract_claude_text_no_stop_text_only_is_progress(self) -> None:
        event = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "stop_reason": None,
                "content": [{"type": "text", "text": "I'm Claude."}],
            },
        }
        kind, text = self.runner._extract_claude_text(event)
        self.assertEqual(kind, "progress")
        self.assertIn("Claude", text)

    def test_extract_claude_text_tool_use_with_text_is_progress(self) -> None:
        event = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "stop_reason": None,
                "content": [
                    {"type": "tool_use", "id": "toolu_123", "name": "Bash"},
                    {"type": "text", "text": "working"},
                ],
            },
        }
        kind, text = self.runner._extract_claude_text(event)
        self.assertEqual(kind, "progress")
        self.assertIn("working", text)

    def test_extract_progress_text_keeps_full_commentary_block(self) -> None:
        event = {
            "type": "event_msg",
            "payload": {
                "type": "agent_message",
                "phase": "commentary",
                "message": "我先检查 bridge 当前状态，然后再看事件日志。\n后面这句不该发。",
            },
        }
        self.assertEqual(
            self.runner._extract_progress_text(event),
            "我先检查 bridge 当前状态，然后再看事件日志。\n后面这句不该发。",
        )

    def test_extract_progress_text_reads_update_plan_function_call(self) -> None:
        event = {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "update_plan",
                "arguments": json.dumps(
                    {
                        "explanation": "切到更小的主线切片。",
                        "plan": [
                            {"step": "检查 bridge 当前状态", "status": "completed"},
                            {"step": "实现 plan icon", "status": "in_progress"},
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        }
        self.assertEqual(
            self.runner._extract_progress_text(event),
            PLAN_MARKER
            + "Plan\n切到更小的主线切片。\n1. 完成: 检查 bridge 当前状态\n2. 进行中: 实现 plan icon",
        )

    def test_inject_prompt_uses_send_keys_for_opencode_runtime_even_in_codex_tmux(
        self,
    ) -> None:
        with patch.object(
            self.runner,
            "_runtime_status_for_tmux",
            return_value=LiveRuntimeStatus(
                tmux_session="codex",
                exists=True,
                pane_command="node",
                thread_id="ses_demo",
                pane_cwd="/tmp",
                backend=CliBackend.OPENCODE.value,
            ),
        ), patch("daedalus_wechat.live_session.time.sleep", lambda _: None), patch(
            "daedalus_wechat.live_session.subprocess.run"
        ) as run_mock:
            self.runner._inject_prompt("codex", "line one\nline two")

        self.assertEqual(
            run_mock.call_args_list,
            [
                call(
                    ["tmux", "send-keys", "-t", "codex:0.0", "line one line two"],
                    check=True,
                    stdout=-1,
                    stderr=-1,
                ),
                call(
                    ["tmux", "send-keys", "-t", "codex:0.0", "C-m"],
                    check=True,
                    stdout=-1,
                    stderr=-1,
                ),
            ],
        )

    def test_inject_prompt_uses_send_keys_for_codex_runtime(self) -> None:
        with patch.object(
            self.runner,
            "_runtime_status_for_tmux",
            return_value=LiveRuntimeStatus(
                tmux_session="codex",
                exists=True,
                pane_command="codex",
                thread_id="019cdfe5-fa14-74a3-aa31-5451128ea58d",
                pane_cwd="/tmp",
                backend=CliBackend.CODEX.value,
            ),
        ), patch("daedalus_wechat.live_session.time.sleep", lambda _: None), patch(
            "daedalus_wechat.live_session.subprocess.run"
        ) as run_mock:
            self.runner._inject_prompt("codex", "line one\nline two")

        self.assertEqual(
            run_mock.call_args_list,
            [
                call(
                    ["tmux", "send-keys", "-t", "codex:0.0", "line one line two"],
                    check=True,
                    stdout=-1,
                    stderr=-1,
                ),
                call(
                    ["tmux", "send-keys", "-t", "codex:0.0", "C-m"],
                    check=True,
                    stdout=-1,
                    stderr=-1,
                ),
            ],
        )

    def test_inject_prompt_uses_paste_buffer_for_claude_runtime(self) -> None:
        with patch.object(
            self.runner,
            "_runtime_status_for_tmux",
            return_value=LiveRuntimeStatus(
                tmux_session="claude",
                exists=True,
                pane_command="claude",
                thread_id="claude:demo",
                pane_cwd="/tmp",
                backend=CliBackend.CLAUDE.value,
            ),
        ), patch("daedalus_wechat.live_session.time.sleep", lambda _: None), patch(
            "daedalus_wechat.live_session.subprocess.run"
        ) as run_mock:
            self.runner._inject_prompt("claude", "line one\nline two")

        self.assertEqual(
            run_mock.call_args_list,
            [
                call(
                    ["tmux", "load-buffer", "-"],
                    input=b"line one\nline two",
                    check=True,
                    stdout=-1,
                    stderr=-1,
                ),
                call(
                    ["tmux", "paste-buffer", "-d", "-t", "claude:0.0"],
                    check=True,
                    stdout=-1,
                    stderr=-1,
                ),
                call(
                    ["tmux", "send-keys", "-t", "claude:0.0", "C-m"],
                    check=True,
                    stdout=-1,
                    stderr=-1,
                ),
            ],
        )

    def test_current_runtime_status_falls_back_when_active_tmux_is_missing(self) -> None:
        missing = LiveRuntimeStatus(
            tmux_session="gpt",
            exists=False,
            pane_command=None,
            thread_id=None,
            pane_cwd=None,
            backend="unknown",
        )
        codex = LiveRuntimeStatus(
            tmux_session="codex",
            exists=True,
            pane_command="node",
            thread_id="019cdfe5-fa14-74a3-aa31-5451128ea58d",
            pane_cwd="/tmp",
            backend=CliBackend.CODEX.value,
        )

        with patch.object(
            self.runner,
            "_runtime_status_for_tmux",
            side_effect=lambda tmux: missing if tmux == "gpt" else codex,
        ), patch.object(
            self.runner,
            "list_live_runtime_statuses",
            return_value=[codex],
        ):
            status = self.runner.current_runtime_status(
                active_session_id="stale-thread",
                active_tmux_session="gpt",
            )

        self.assertEqual(status.tmux_session, "codex")
        self.assertEqual(status.thread_id, "019cdfe5-fa14-74a3-aa31-5451128ea58d")

    def test_wait_for_final_reply_returns_final_without_task_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rollout = Path(tmpdir) / "rollout.jsonl"
            rollout.write_text(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "agent_message",
                            "phase": "final_answer",
                            "message": "WECHAT_FINAL_ONLY_OK",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            ticks = iter([0.0, 0.1, 0.2, 0.3, 2.6, 2.7, 2.8])
            with patch("daedalus_wechat.live_session.time.sleep", lambda _: None):
                with patch(
                    "daedalus_wechat.live_session.time.monotonic",
                    side_effect=lambda: next(ticks),
                ):
                    reply = self.runner._wait_for_final_reply(
                        rollout_file=rollout,
                        start_offset=0,
                    )
            self.assertEqual(reply, "WECHAT_FINAL_ONLY_OK")

    def test_send_prompt_falls_back_to_visible_pane_reply_when_final_missing(
        self,
    ) -> None:
        record = SessionRecord(
            thread_id="019cdfe5-fa14-74a3-aa31-5451128ea58d",
            label="attached-last",
            cwd="/tmp",
            source="tmux-live",
            created_at="2026-03-26T00:00:00+00:00",
            updated_at="2026-03-26T00:00:00+00:00",
            tmux_session="codex",
        )
        with patch.object(self.runner, "_ensure_running_tmux", return_value="codex"):
            with patch.object(
                self.runner, "_capture_clean_text", side_effect=["baseline", "baseline"]
            ):
                with patch.object(
                    self.runner, "_resolve_rollout_file", return_value=None
                ):
                    with patch.object(self.runner, "_inject_prompt") as inject_mock:
                        with patch.object(
                            self.runner, "_wait_for_final_reply", return_value=""
                        ):
                            with patch.object(
                                self.runner,
                                "_collect_response",
                                return_value="VISIBLE_REPLY_OK",
                            ):
                                with patch.object(
                                    self.runner,
                                    "_runtime_status_for_tmux",
                                    return_value=LiveRuntimeStatus(
                                        tmux_session="codex",
                                        exists=True,
                                        pane_command="codex",
                                        thread_id=record.thread_id,
                                        pane_cwd="/tmp",
                                    ),
                                ):
                                    reply = self.runner.send_prompt(
                                        record=record,
                                        prompt="hello",
                                    )
        inject_mock.assert_called_once()
        self.assertEqual(reply.response_text, "VISIBLE_REPLY_OK")

    def test_submit_prompt_injects_without_waiting_for_final(self) -> None:
        record = SessionRecord(
            thread_id="019cdfe5-fa14-74a3-aa31-5451128ea58d",
            label="attached-last",
            cwd="/tmp",
            source="tmux-live",
            created_at="2026-03-26T00:00:00+00:00",
            updated_at="2026-03-26T00:00:00+00:00",
            tmux_session="codex",
        )
        with patch.object(self.runner, "_ensure_running_tmux", return_value="codex"):
            with patch.object(self.runner, "_inject_prompt") as inject_mock:
                with patch.object(
                    self.runner,
                    "_runtime_status_for_tmux",
                    return_value=LiveRuntimeStatus(
                        tmux_session="codex",
                        exists=True,
                        pane_command="codex",
                        thread_id=record.thread_id,
                        pane_cwd="/tmp",
                    ),
                ):
                    submitted = self.runner.submit_prompt(record=record, prompt="hello")
        inject_mock.assert_called_once_with("codex", "hello")
        self.assertEqual(submitted.thread_id, record.thread_id)

    def test_submit_prompt_prefers_runtime_thread_over_stale_pane_history(self) -> None:
        record = SessionRecord(
            thread_id="019cdfe5-fa14-74a3-aa31-5451128ea58d",
            label="attached-last",
            cwd="/tmp",
            source="tmux-live",
            created_at="2026-03-26T00:00:00+00:00",
            updated_at="2026-03-26T00:00:00+00:00",
            tmux_session="codex",
        )
        fresh_thread = "019d332d-1bc8-7151-a874-ab0fbc493747"
        with patch.object(self.runner, "_ensure_running_tmux", return_value="codex"):
            with patch.object(self.runner, "_inject_prompt") as inject_mock:
                with patch.object(
                    self.runner,
                    "_runtime_status_for_tmux",
                    return_value=LiveRuntimeStatus(
                        tmux_session="codex",
                        exists=True,
                        pane_command="codex",
                        thread_id=fresh_thread,
                        pane_cwd="/tmp",
                    ),
                ):
                    submitted = self.runner.submit_prompt(record=record, prompt="hello")
        inject_mock.assert_called_once_with("codex", "hello")
        self.assertEqual(submitted.thread_id, fresh_thread)
        self.assertEqual(submitted.tmux_session, "codex")

    def test_latest_mirror_since_reads_opencode_final_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    create table session (
                        id text primary key,
                        directory text not null,
                        time_created integer not null,
                        time_updated integer not null,
                        time_archived integer
                    );
                    create table message (
                        id text primary key,
                        session_id text not null,
                        time_created integer not null,
                        time_updated integer not null,
                        data text not null
                    );
                    create table part (
                        id text primary key,
                        message_id text not null,
                        session_id text not null,
                        time_created integer not null,
                        time_updated integer not null,
                        data text not null
                    );
                    """
                )
                conn.execute(
                    "insert into session (id, directory, time_created, time_updated, time_archived) values (?, ?, ?, ?, null)",
                    ("ses_test", "/tmp", 10, 20),
                )
                conn.execute(
                    "insert into message (id, session_id, time_created, time_updated, data) values (?, ?, ?, ?, ?)",
                    (
                        "msg_assistant",
                        "ses_test",
                        10,
                        20,
                        json.dumps({"role": "assistant"}, ensure_ascii=False),
                    ),
                )
                conn.execute(
                    "insert into part (id, message_id, session_id, time_created, time_updated, data) values (?, ?, ?, ?, ?, ?)",
                    (
                        "part_final",
                        "msg_assistant",
                        "ses_test",
                        10,
                        20,
                        json.dumps(
                            {
                                "type": "text",
                                "text": "OPENCODE_FINAL_OK",
                                "metadata": {"openai": {"phase": "final_answer"}},
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            self.runner.opencode_state_db = db_path
            scan = self.runner.latest_mirror_since(thread_id="ses_test", start_offset=0)
        self.assertIsNotNone(scan)
        assert scan is not None
        self.assertEqual(scan.final_texts, ["OPENCODE_FINAL_OK"])
        self.assertEqual(scan.progress_texts, [])
        self.assertGreater(scan.end_offset, 0)

    def test_latest_mirror_since_reads_claude_final_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_root = Path(tmpdir) / ".claude" / "projects" / "proj"
            projects_root.mkdir(parents=True, exist_ok=True)
            session_id = "9d39ab4b-c37d-4ff8-8104-e83cdd6c4307"
            session_file = projects_root / f"{session_id}.jsonl"
            session_file.write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "stop_reason": "end_turn",
                            "content": [{"type": "text", "text": "OK"}],
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            self.runner.claude_projects_root = Path(tmpdir) / ".claude" / "projects"
            scan = self.runner.latest_mirror_since(
                thread_id=f"claude:{session_id}",
                start_offset=0,
            )
        self.assertIsNotNone(scan)
        assert scan is not None
        self.assertEqual(scan.final_texts, ["OK"])
        self.assertEqual(scan.progress_texts, [])
        self.assertGreater(scan.end_offset, 0)

    def test_latest_mirror_since_keeps_opencode_final_with_later_commentary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    create table session (
                        id text primary key,
                        directory text not null,
                        time_created integer not null,
                        time_updated integer not null,
                        time_archived integer
                    );
                    create table message (
                        id text primary key,
                        session_id text not null,
                        time_created integer not null,
                        time_updated integer not null,
                        data text not null
                    );
                    create table part (
                        id text primary key,
                        message_id text not null,
                        session_id text not null,
                        time_created integer not null,
                        time_updated integer not null,
                        data text not null
                    );
                    """
                )
                conn.execute(
                    "insert into session (id, directory, time_created, time_updated, time_archived) values (?, ?, ?, ?, null)",
                    ("ses_test", "/tmp", 10, 40),
                )
                conn.execute(
                    "insert into message (id, session_id, time_created, time_updated, data) values (?, ?, ?, ?, ?)",
                    (
                        "msg_final",
                        "ses_test",
                        10,
                        20,
                        json.dumps({"role": "assistant"}, ensure_ascii=False),
                    ),
                )
                conn.execute(
                    "insert into message (id, session_id, time_created, time_updated, data) values (?, ?, ?, ?, ?)",
                    (
                        "msg_progress",
                        "ses_test",
                        30,
                        40,
                        json.dumps({"role": "assistant"}, ensure_ascii=False),
                    ),
                )
                conn.execute(
                    "insert into part (id, message_id, session_id, time_created, time_updated, data) values (?, ?, ?, ?, ?, ?)",
                    (
                        "part_final",
                        "msg_final",
                        "ses_test",
                        10,
                        20,
                        json.dumps(
                            {
                                "type": "text",
                                "text": "OK",
                                "metadata": {"openai": {"phase": "final_answer"}},
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                conn.execute(
                    "insert into part (id, message_id, session_id, time_created, time_updated, data) values (?, ?, ?, ?, ?, ?)",
                    (
                        "part_progress",
                        "msg_progress",
                        "ses_test",
                        30,
                        40,
                        json.dumps(
                            {
                                "type": "text",
                                "text": "later commentary",
                                "metadata": {"openai": {"phase": "commentary"}},
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            self.runner.opencode_state_db = db_path
            scan = self.runner.latest_mirror_since(thread_id="ses_test", start_offset=0)
        self.assertIsNotNone(scan)
        assert scan is not None
        self.assertEqual(scan.final_texts, ["OK"])
        self.assertEqual(scan.progress_texts, ["later commentary"])
        self.assertGreater(scan.end_offset, 0)

    def test_latest_mirror_since_reads_opencode_stop_finished_text_as_final(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    create table session (
                        id text primary key,
                        directory text not null,
                        time_created integer not null,
                        time_updated integer not null,
                        time_archived integer
                    );
                    create table message (
                        id text primary key,
                        session_id text not null,
                        time_created integer not null,
                        time_updated integer not null,
                        data text not null
                    );
                    create table part (
                        id text primary key,
                        message_id text not null,
                        session_id text not null,
                        time_created integer not null,
                        time_updated integer not null,
                        data text not null
                    );
                    """
                )
                conn.execute(
                    "insert into session (id, directory, time_created, time_updated, time_archived) values (?, ?, ?, ?, null)",
                    ("ses_test", "/tmp", 10, 20),
                )
                conn.execute(
                    "insert into message (id, session_id, time_created, time_updated, data) values (?, ?, ?, ?, ?)",
                    (
                        "msg_assistant",
                        "ses_test",
                        10,
                        20,
                        json.dumps({"role": "assistant"}, ensure_ascii=False),
                    ),
                )
                conn.execute(
                    "insert into part (id, message_id, session_id, time_created, time_updated, data) values (?, ?, ?, ?, ?, ?)",
                    (
                        "part_text",
                        "msg_assistant",
                        "ses_test",
                        10,
                        20,
                        json.dumps({"type": "text", "text": " OK"}, ensure_ascii=False),
                    ),
                )
                conn.execute(
                    "insert into part (id, message_id, session_id, time_created, time_updated, data) values (?, ?, ?, ?, ?, ?)",
                    (
                        "part_finish",
                        "msg_assistant",
                        "ses_test",
                        11,
                        21,
                        json.dumps(
                            {"type": "step-finish", "reason": "stop"},
                            ensure_ascii=False,
                        ),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            self.runner.opencode_state_db = db_path
            scan = self.runner.latest_mirror_since(thread_id="ses_test", start_offset=0)
        self.assertIsNotNone(scan)
        assert scan is not None
        self.assertEqual(scan.final_texts, ["OK"])
        self.assertEqual(scan.progress_texts, [])
        self.assertGreater(scan.end_offset, 0)

    def test_submit_prompt_resolves_opencode_session_from_db_after_inject(self) -> None:
        record = SessionRecord(
            thread_id="pending:opencode",
            label="opencode",
            cwd="/tmp",
            source="tmux-live-provisional",
            created_at="2026-03-26T00:00:00+00:00",
            updated_at="2026-03-26T00:00:00+00:00",
            tmux_session="opencode",
        )
        with patch.object(self.runner, "_ensure_running_tmux", return_value="opencode"):
            with patch.object(self.runner, "_inject_prompt") as inject_mock:
                with patch.object(
                    self.runner,
                    "_runtime_status_for_tmux",
                    side_effect=[
                        LiveRuntimeStatus(
                            tmux_session="opencode",
                            exists=True,
                            pane_command="opencode",
                            thread_id=None,
                            pane_cwd="/tmp",
                            backend="opencode",
                        ),
                        LiveRuntimeStatus(
                            tmux_session="opencode",
                            exists=True,
                            pane_command="opencode",
                            thread_id="ses_after",
                            pane_cwd="/tmp",
                            backend="opencode",
                        ),
                    ],
                ):
                    with patch.object(
                        self.runner,
                        "_latest_opencode_session_info",
                        side_effect=[("ses_before", 10), ("ses_after", 25)],
                    ):
                        with patch.object(
                            self.runner, "_set_tmux_runtime_id"
                        ) as set_hint:
                            submitted = self.runner.submit_prompt(
                                record=record, prompt="hello"
                            )
        inject_mock.assert_called_once_with("opencode", "hello")
        set_hint.assert_called_with("opencode", "ses_after")
        self.assertEqual(submitted.thread_id, "ses_after")

    def test_runtime_status_prefers_hinted_opencode_backend_for_node_shell(
        self,
    ) -> None:
        with patch.object(self.runner, "_tmux_exists", return_value=True):
            with patch.object(
                self.runner, "_pane_current_command", return_value="node"
            ):
                with patch.object(
                    self.runner, "_pane_current_path", return_value="/tmp"
                ):
                    with patch.object(
                        self.runner, "_capture_clean_text", return_value=""
                    ):
                        with patch.object(
                            self.runner, "_pane_start_command", return_value=""
                        ):
                            with patch.object(
                                self.runner,
                                "_get_tmux_runtime_id",
                                return_value="ses_owner_opencode",
                            ):
                                status = self.runner._runtime_status_for_tmux(
                                    "opencode"
                                )
        self.assertEqual(status.backend, "opencode")
        self.assertEqual(status.thread_id, "ses_owner_opencode")

    def test_runtime_status_does_not_promote_shell_from_stale_hint(self) -> None:
        with patch.object(self.runner, "_tmux_exists", return_value=True):
            with patch.object(
                self.runner, "_pane_current_command", return_value="bash"
            ):
                with patch.object(
                    self.runner, "_pane_current_path", return_value="/tmp"
                ):
                    with patch.object(
                        self.runner, "_capture_clean_text", return_value=""
                    ):
                        with patch.object(
                            self.runner, "_pane_start_command", return_value=""
                        ):
                            with patch.object(
                                self.runner,
                                "_get_tmux_runtime_id",
                                return_value="ses_owner_opencode",
                            ):
                                with patch.object(
                                    self.runner, "_pane_pid", return_value=1234
                                ):
                                    with patch(
                                        "daedalus_wechat.live_session.detect_backend",
                                        return_value=CliBackend.UNKNOWN,
                                    ):
                                        status = self.runner._runtime_status_for_tmux(
                                            "alpha"
                                        )
        self.assertEqual(status.backend, "unknown")
        self.assertIsNone(status.thread_id)

    def test_runtime_status_prefers_detected_codex_backend_over_stale_opencode_hint_for_shell(
        self,
    ) -> None:
        latest_thread = "019d332d-1bc8-7151-a874-ab0fbc493747"
        with patch.object(self.runner, "_tmux_exists", return_value=True):
            with patch.object(
                self.runner, "_pane_current_command", return_value="bash"
            ):
                with patch.object(
                    self.runner, "_pane_current_path", return_value="/tmp"
                ):
                    with patch.object(
                        self.runner, "_capture_clean_text", return_value=""
                    ):
                        with patch.object(
                            self.runner, "_pane_start_command", return_value=""
                        ):
                            with patch.object(
                                self.runner,
                                "_get_tmux_runtime_id",
                                return_value="ses_owner_opencode",
                            ):
                                with patch.object(
                                    self.runner, "_pane_pid", return_value=1234
                                ):
                                    with patch(
                                        "daedalus_wechat.live_session.detect_backend",
                                        return_value=CliBackend.CODEX,
                                    ):
                                        with patch.object(
                                            self.runner,
                                            "find_latest_thread",
                                            return_value=latest_thread,
                                        ):
                                            status = self.runner._runtime_status_for_tmux(
                                                "codex"
                                            )
        self.assertEqual(status.backend, "codex")
        self.assertEqual(status.thread_id, latest_thread)

    def test_runtime_status_prefers_detected_codex_backend_over_stale_opencode_hint_for_node(
        self,
    ) -> None:
        latest_thread = "019d332d-1bc8-7151-a874-ab0fbc493747"
        with patch.object(self.runner, "_tmux_exists", return_value=True):
            with patch.object(
                self.runner, "_pane_current_command", return_value="node"
            ):
                with patch.object(
                    self.runner, "_pane_current_path", return_value="/tmp"
                ):
                    with patch.object(
                        self.runner, "_capture_clean_text", return_value=""
                    ):
                        with patch.object(
                            self.runner, "_pane_start_command", return_value=""
                        ):
                            with patch.object(
                                self.runner,
                                "_get_tmux_runtime_id",
                                return_value="ses_owner_opencode",
                            ):
                                with patch.object(
                                    self.runner, "_pane_pid", return_value=1234
                                ):
                                    with patch(
                                        "daedalus_wechat.live_session.detect_backend",
                                        return_value=CliBackend.CODEX,
                                    ):
                                        with patch.object(
                                            self.runner,
                                            "find_latest_thread",
                                            return_value=latest_thread,
                                        ):
                                            status = self.runner._runtime_status_for_tmux(
                                                "gpt"
                                            )
        self.assertEqual(status.backend, "codex")
        self.assertEqual(status.thread_id, latest_thread)

    def test_resolve_opencode_session_prefers_db_truth_over_pending_tmux_hint(
        self,
    ) -> None:
        with patch.object(
            self.runner,
            "_get_tmux_runtime_id",
            return_value="pending:opencode",
        ):
            with patch.object(
                self.runner,
                "_latest_opencode_session_info",
                return_value=("ses_old", 123),
            ):
                resolved = self.runner._resolve_opencode_session_id(
                    tmux_session="opencode",
                    pane_cwd="/tmp",
                )
        self.assertEqual(resolved, "ses_old")

    def test_resolve_runtime_thread_id_prefers_codex_proc_rollout_file(
        self,
    ) -> None:
        pane_thread = "019d74bd-debd-7772-8c13-53356881614a"
        latest_thread = "019d6add-22bb-73f3-b236-e805d401943e"
        rollout_path = Path(
            f"/home/ft/.codex/sessions/2026/04/10/rollout-2026-04-10T08-14-53-{pane_thread}.jsonl"
        )
        with patch.object(self.runner, "_pane_pid", return_value=1234):
            with patch.object(self.runner, "_proc_descendants", return_value=[5678]):
                with patch.object(
                    self.runner,
                    "_proc_open_paths",
                    side_effect=[
                        [],
                        [str(rollout_path)],
                    ],
                ):
                    with patch.object(
                        self.runner,
                        "find_latest_thread",
                        return_value=latest_thread,
                    ):
                        resolved = self.runner._resolve_runtime_thread_id(
                            tmux_session="gpt",
                            pane_cwd="/tmp",
                            screen_text="",
                            backend="codex",
                        )
        self.assertEqual(resolved, pane_thread)

    def test_inventory_marks_duplicate_runtime_ids_without_guessing_backend(
        self,
    ) -> None:
        with patch.object(
            self.runner,
            "_list_tmux_sessions",
            return_value=["codex", "opencode"],
        ):
            with patch.object(
                self.runner,
                "_runtime_status_for_tmux",
                side_effect=[
                    LiveRuntimeStatus(
                        tmux_session="codex",
                        exists=True,
                        pane_command="node",
                        thread_id="ses_shared",
                        pane_cwd="/tmp",
                        backend="opencode",
                    ),
                    LiveRuntimeStatus(
                        tmux_session="opencode",
                        exists=True,
                        pane_command="node",
                        thread_id="ses_shared",
                        pane_cwd="/tmp",
                        backend="opencode",
                    ),
                    LiveRuntimeStatus(
                        tmux_session="opencode",
                        exists=True,
                        pane_command="node",
                        thread_id="ses_shared",
                        pane_cwd="/tmp",
                        backend="opencode",
                    ),
                    LiveRuntimeStatus(
                        tmux_session="codex",
                        exists=True,
                        pane_command="node",
                        thread_id="ses_shared",
                        pane_cwd="/tmp",
                        backend="opencode",
                    ),
                ],
            ):
                items = self.runner.list_tmux_runtime_inventory()
        # duplicate-runtime-id sessions are now switchable (needed for group mode)
        self.assertEqual(items[0].reason, "live")
        self.assertTrue(items[0].switchable)
        self.assertEqual(items[1].reason, "live")
        self.assertTrue(items[1].switchable)

    def test_resolve_opencode_session_prefers_tmux_title_before_latest_cwd(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    create table session (
                        id text primary key,
                        directory text not null,
                        title text not null,
                        time_created integer not null,
                        time_updated integer not null,
                        time_archived integer
                    );
                    """
                )
                conn.execute(
                    "insert into session (id, directory, title, time_created, time_updated, time_archived) values (?, ?, ?, ?, ?, ?)",
                    ("ses_latest", "/tmp", "other", 10, 200, None),
                )
                conn.execute(
                    "insert into session (id, directory, title, time_created, time_updated, time_archived) values (?, ?, ?, ?, ?, ?)",
                    ("ses_match", "/tmp", "kimi1", 10, 100, None),
                )
                conn.commit()
            finally:
                conn.close()
            self.runner.opencode_state_db = db_path

            with patch.object(self.runner, "_get_tmux_runtime_id", return_value=None):
                resolved = self.runner._resolve_opencode_session_id(
                    tmux_session="kimi1",
                    pane_cwd="/tmp",
                )

        self.assertEqual(resolved, "ses_match")

    def test_resolve_opencode_session_prefers_db_truth_over_stale_tmux_hint(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    create table session (
                        id text primary key,
                        directory text not null,
                        title text not null,
                        time_created integer not null,
                        time_updated integer not null,
                        time_archived integer
                    );
                    """
                )
                conn.execute(
                    "insert into session (id, directory, title, time_created, time_updated, time_archived) values (?, ?, ?, ?, ?, ?)",
                    ("ses_match", "/tmp", "kimi2", 10, 100, None),
                )
                conn.commit()
            finally:
                conn.close()
            self.runner.opencode_state_db = db_path

            with patch.object(
                self.runner,
                "_get_tmux_runtime_id",
                return_value="ses_stale_hint",
            ):
                resolved = self.runner._resolve_opencode_session_id(
                    tmux_session="kimi2",
                    pane_cwd="/tmp",
                )

        self.assertEqual(resolved, "ses_match")

    def test_resolve_codex_thread_id_falls_back_to_tmux_runtime_id(self) -> None:
        """When codex rollout-file resolution fails (e.g. multiple codex
        instances share one workspace cwd — alpha/beta/gamma case), the
        resolver must respect an explicit @daedalus_runtime_id tmux option."""
        pinned = "019d8ce9-b087-76a1-b0c4-deadbeef0001"
        with patch.object(
            self.runner,
            "_current_codex_rollout_file",
            return_value=None,
        ), patch.object(
            self.runner,
            "_get_tmux_runtime_id",
            return_value=pinned,
        ):
            resolved = self.runner._resolve_codex_thread_id(tmux_session="gamma")
        self.assertEqual(resolved, pinned)

    def test_resolve_codex_thread_id_persists_to_tmux_on_success(self) -> None:
        """After a successful rollout-file resolution, the resolver writes the
        thread_id back to @daedalus_runtime_id so the next sync is stable
        even if codex later rotates the rollout file."""
        thread_id = "019dabcd-0000-72aa-b0c4-cafefeed0001"
        rollout = Path(f"/tmp/rollout-{thread_id}.jsonl")
        with patch.object(
            self.runner,
            "_current_codex_rollout_file",
            return_value=rollout,
        ), patch.object(
            self.runner,
            "_extract_codex_thread_id_from_path",
            return_value=thread_id,
        ), patch.object(
            self.runner,
            "_get_tmux_runtime_id",
            return_value=None,
        ), patch.object(
            self.runner,
            "_set_tmux_runtime_id",
        ) as set_mock:
            resolved = self.runner._resolve_codex_thread_id(tmux_session="alpha")
        self.assertEqual(resolved, thread_id)
        set_mock.assert_called_once_with("alpha", thread_id)

    def test_resolve_claude_session_id_prefers_open_project_jsonl(self) -> None:
        session_id = "9d39ab4b-c37d-4ff8-8104-e83cdd6c4307"
        session_file = Path(
            f"/home/ft/.claude/projects/-home-ft-dev-ft-cosmos/{session_id}.jsonl"
        )
        with patch.object(
            self.runner,
            "_current_claude_session_file",
            return_value=session_file,
        ):
            resolved = self.runner._resolve_claude_session_id(tmux_session="claude")

        self.assertEqual(resolved, f"claude:{session_id}")

    def test_ensure_resumed_session_routes_opencode_thread_to_opencode_tmux(
        self,
    ) -> None:
        state = BridgeState(
            sessions={
                "ses_conflict": SessionRecord(
                    thread_id="ses_conflict",
                    label="opencode",
                    cwd="/tmp",
                    source="tmux-live",
                    created_at="2026-03-26T00:00:00+00:00",
                    updated_at="2026-03-26T00:00:00+00:00",
                    tmux_session="codex",
                )
            }
        )
        with patch.object(self.runner, "_find_live_runtime_status", return_value=None):
            with patch.object(
                self.runner,
                "_tmux_exists",
                side_effect=lambda name: name == "opencode",
            ):
                with patch.object(
                    self.runner,
                    "_runtime_status_for_tmux",
                    return_value=LiveRuntimeStatus(
                        tmux_session="opencode",
                        exists=True,
                        pane_command="opencode",
                        thread_id="ses_conflict",
                        pane_cwd="/tmp",
                        backend="opencode",
                    ),
                ):
                    with patch.object(self.runner, "_set_tmux_runtime_id") as set_hint:
                        record = self.runner.ensure_resumed_session(
                            thread_id="ses_conflict",
                            state=state,
                            label="opencode",
                            source="tmux-live",
                        )
        self.assertEqual(record.tmux_session, "opencode")
        set_hint.assert_called_with("opencode", "ses_conflict")

    def test_ensure_resumed_session_routes_pending_opencode_thread_to_opencode_tmux(
        self,
    ) -> None:
        state = BridgeState(
            sessions={
                "pending:opencode": SessionRecord(
                    thread_id="pending:opencode",
                    label="opencode",
                    cwd="/tmp",
                    source="tmux-live-provisional",
                    created_at="2026-04-04T00:00:00+00:00",
                    updated_at="2026-04-04T00:00:00+00:00",
                    tmux_session="opencode",
                )
            }
        )
        with patch.object(self.runner, "_find_live_runtime_status", return_value=None):
            with patch.object(
                self.runner,
                "_tmux_exists",
                side_effect=lambda name: name == "opencode",
            ):
                with patch.object(
                    self.runner,
                    "_runtime_status_for_tmux",
                    return_value=LiveRuntimeStatus(
                        tmux_session="opencode",
                        exists=True,
                        pane_command="node",
                        thread_id="pending:opencode",
                        pane_cwd="/tmp",
                        backend="opencode",
                    ),
                ):
                    with patch.object(self.runner, "_set_tmux_runtime_id") as set_hint:
                        record = self.runner.ensure_resumed_session(
                            thread_id="pending:opencode",
                            state=state,
                            label="opencode",
                            source="tmux-live-provisional",
                        )
        self.assertEqual(record.tmux_session, "opencode")
        set_hint.assert_called_with("opencode", "pending:opencode")

    def test_ensure_resumed_session_does_not_create_missing_tmux(self) -> None:
        state = BridgeState(
            sessions={
                "pending:opencode": SessionRecord(
                    thread_id="pending:opencode",
                    label="opencode",
                    cwd="/tmp",
                    source="tmux-live-provisional",
                    created_at="2026-04-04T00:00:00+00:00",
                    updated_at="2026-04-04T00:00:00+00:00",
                    tmux_session="opencode",
                )
            }
        )
        with patch.object(self.runner, "_find_live_runtime_status", return_value=None):
            with patch.object(self.runner, "_tmux_exists", return_value=False):
                with self.assertRaises(RuntimeError) as exc_info:
                    self.runner.ensure_resumed_session(
                        thread_id="pending:opencode",
                        state=state,
                        label="opencode",
                        source="tmux-live-provisional",
                    )
        self.assertIn("不会自动创建 session", str(exc_info.exception))

    def test_create_new_session_does_not_create_missing_tmux(self) -> None:
        state = BridgeState()
        with patch.object(self.runner, "_tmux_exists", return_value=False):
            with self.assertRaises(RuntimeError) as exc_info:
                self.runner.create_new_session(state=state, label="owner")
        self.assertIn("不会自动创建 session", str(exc_info.exception))

    def test_preferred_canonical_backend_accepts_claude_tmux_name(self) -> None:
        runner = LiveCodexSessionManager(
            codex_bin="codex",
            opencode_bin="opencode",
            default_cwd=Path("/tmp"),
            canonical_tmux_session="claude",
        )

        self.assertEqual(runner._preferred_canonical_backend(), CliBackend.CLAUDE.value)

    def test_list_live_runtime_statuses_filters_to_workspace_codex_sessions(
        self,
    ) -> None:
        with patch.object(
            self.runner,
            "_list_tmux_sessions",
            return_value=["codex", "123", "foreign", "idle"],
        ):
            with patch.object(
                self.runner,
                "_runtime_status_for_tmux",
                side_effect=lambda tmux_session: {
                    "codex": LiveRuntimeStatus(
                        tmux_session="codex",
                        exists=True,
                        pane_command="node",
                        thread_id="019cdfe5-fa14-74a3-aa31-5451128ea58d",
                        pane_cwd="/tmp",
                    ),
                    "123": LiveRuntimeStatus(
                        tmux_session="123",
                        exists=True,
                        pane_command="codex",
                        thread_id="11111111-2222-3333-4444-555555555555",
                        pane_cwd="/tmp/subdir",
                    ),
                    "foreign": LiveRuntimeStatus(
                        tmux_session="foreign",
                        exists=True,
                        pane_command="node",
                        thread_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                        pane_cwd="/var/tmp",
                    ),
                    "idle": LiveRuntimeStatus(
                        tmux_session="idle",
                        exists=True,
                        pane_command="bash",
                        thread_id=None,
                        pane_cwd="/tmp",
                    ),
                }[tmux_session],
            ):
                statuses = self.runner.list_live_runtime_statuses()
        self.assertEqual([item.tmux_session for item in statuses], ["codex", "123"])

    def test_sync_live_sessions_preserves_existing_labels(self) -> None:
        state = BridgeState(
            sessions={
                "019cdfe5-fa14-74a3-aa31-5451128ea58d": SessionRecord(
                    thread_id="019cdfe5-fa14-74a3-aa31-5451128ea58d",
                    label="main-live",
                    cwd="/tmp",
                    source="tmux-live",
                    created_at="2026-03-26T00:00:00+00:00",
                    updated_at="2026-03-26T00:00:00+00:00",
                    tmux_session="codex",
                )
            }
        )
        with patch.object(
            self.runner,
            "list_live_runtime_statuses",
            return_value=[
                LiveRuntimeStatus(
                    tmux_session="codex",
                    exists=True,
                    pane_command="node",
                    thread_id="019cdfe5-fa14-74a3-aa31-5451128ea58d",
                    pane_cwd="/tmp",
                ),
                LiveRuntimeStatus(
                    tmux_session="123",
                    exists=True,
                    pane_command="node",
                    thread_id="11111111-2222-3333-4444-555555555555",
                    pane_cwd="/tmp/ft-kairos",
                ),
            ],
        ):
            records = self.runner.sync_live_sessions(state)
        self.assertEqual([item.label for item in records], ["main-live", "123"])
        self.assertEqual(
            state.sessions["11111111-2222-3333-4444-555555555555"].cwd, "/tmp/ft-kairos"
        )

    def test_sync_live_sessions_rewrites_legacy_codex_label_for_opencode(self) -> None:
        state = BridgeState(
            sessions={
                "ses_legacy_opencode": SessionRecord(
                    thread_id="ses_legacy_opencode",
                    label="codex",
                    cwd="/tmp",
                    source="tmux-live",
                    created_at="2026-04-04T00:00:00+00:00",
                    updated_at="2026-04-04T00:00:00+00:00",
                    tmux_session="opencode",
                )
            }
        )
        with patch.object(
            self.runner,
            "list_live_runtime_statuses",
            return_value=[
                LiveRuntimeStatus(
                    tmux_session="opencode",
                    exists=True,
                    pane_command="node",
                    thread_id="ses_legacy_opencode",
                    pane_cwd="/tmp/ft-cosmos",
                    backend="opencode",
                )
            ],
        ):
            records = self.runner.sync_live_sessions(state)
        self.assertEqual(records[0].label, "opencode")
        self.assertEqual(state.sessions["ses_legacy_opencode"].label, "opencode")

    def test_sync_live_sessions_renames_generic_opencode_label_when_tmux_moves(
        self,
    ) -> None:
        state = BridgeState(
            sessions={
                "ses_old_opencode": SessionRecord(
                    thread_id="ses_old_opencode",
                    label="opencode",
                    cwd="/tmp",
                    source="tmux-live",
                    created_at="2026-04-04T00:00:00+00:00",
                    updated_at="2026-04-04T00:00:00+00:00",
                    tmux_session="opencode",
                )
            }
        )
        with patch.object(
            self.runner,
            "list_live_runtime_statuses",
            return_value=[
                LiveRuntimeStatus(
                    tmux_session="opencode-debug-20260404",
                    exists=True,
                    pane_command="node",
                    thread_id="ses_old_opencode",
                    pane_cwd="/tmp",
                    backend="opencode",
                )
            ],
        ):
            records = self.runner.sync_live_sessions(state)
        self.assertEqual(records[0].label, "opencode-debug-20260404")
        self.assertEqual(
            state.sessions["ses_old_opencode"].label,
            "opencode-debug-20260404",
        )

    def test_runtime_status_prefers_latest_thread_with_fresher_rollout(self) -> None:
        stale_thread = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
        fresh_thread = "019d332d-1bc8-7151-a874-ab0fbc493747"
        with tempfile.TemporaryDirectory() as tmpdir:
            session_root = Path(tmpdir) / "sessions"
            session_root.mkdir(parents=True, exist_ok=True)
            stale_rollout = session_root / f"stale-{stale_thread}.jsonl"
            fresh_rollout = session_root / f"fresh-{fresh_thread}.jsonl"
            stale_rollout.write_text("stale\n", encoding="utf-8")
            fresh_rollout.write_text("fresh\n", encoding="utf-8")
            os.utime(stale_rollout, (1000, 1000))
            os.utime(fresh_rollout, (2000, 2000))
            self.runner.session_root = session_root
            with patch.object(self.runner, "_tmux_exists", return_value=True):
                with patch.object(
                    self.runner, "_pane_current_command", return_value="codex"
                ):
                    with patch.object(
                        self.runner, "_pane_current_path", return_value="/tmp"
                    ):
                        with patch.object(self.runner, "_pane_pid", return_value=None):
                            with patch.object(
                                self.runner,
                                "_capture_clean_text",
                                return_value=f"old log {stale_thread}",
                            ):
                                with patch.object(
                                    self.runner,
                                    "find_latest_thread",
                                    return_value=fresh_thread,
                                ):
                                    status = self.runner._runtime_status_for_tmux("codex")
        self.assertEqual(status.thread_id, fresh_thread)

    def test_find_latest_thread_ignores_spawn_child_when_root_exists(self) -> None:
        root_thread = "019d332d-1bc8-7151-a874-ab0fbc493747"
        child_thread = "019d46e2-1b23-7e01-941b-269961074b52"
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.sqlite"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    create table threads (
                        id text primary key,
                        rollout_path text not null,
                        created_at integer not null,
                        updated_at integer not null,
                        source text not null,
                        model_provider text not null,
                        cwd text not null,
                        title text not null,
                        sandbox_policy text not null,
                        approval_mode text not null,
                        tokens_used integer not null default 0,
                        has_user_event integer not null default 0,
                        archived integer not null default 0
                    );
                    create table thread_spawn_edges (
                        parent_thread_id text not null,
                        child_thread_id text not null,
                        status text
                    );
                    """
                )
                conn.execute(
                    """
                    insert into threads (
                        id, rollout_path, created_at, updated_at, source,
                        model_provider, cwd, title, sandbox_policy, approval_mode, archived
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        root_thread,
                        "/tmp/root.jsonl",
                        100,
                        200,
                        "cli",
                        "openai",
                        "/tmp",
                        "root",
                        "workspace-write",
                        "never",
                    ),
                )
                conn.execute(
                    """
                    insert into threads (
                        id, rollout_path, created_at, updated_at, source,
                        model_provider, cwd, title, sandbox_policy, approval_mode, archived
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        child_thread,
                        "/tmp/child.jsonl",
                        100,
                        300,
                        '{"subagent":true}',
                        "openai",
                        "/tmp",
                        "child",
                        "workspace-write",
                        "never",
                    ),
                )
                conn.execute(
                    """
                    insert into thread_spawn_edges (
                        parent_thread_id, child_thread_id, status
                    ) values (?, ?, ?)
                    """,
                    (root_thread, child_thread, "open"),
                )
                conn.commit()
            finally:
                conn.close()
            self.runner.codex_state_db = db_path
            self.assertEqual(self.runner.find_latest_thread(), root_thread)

    def test_find_latest_thread_falls_back_to_child_when_only_child_exists(
        self,
    ) -> None:
        child_thread = "019d46e2-1b23-7e01-941b-269961074b52"
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.sqlite"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    create table threads (
                        id text primary key,
                        rollout_path text not null,
                        created_at integer not null,
                        updated_at integer not null,
                        source text not null,
                        model_provider text not null,
                        cwd text not null,
                        title text not null,
                        sandbox_policy text not null,
                        approval_mode text not null,
                        tokens_used integer not null default 0,
                        has_user_event integer not null default 0,
                        archived integer not null default 0
                    );
                    create table thread_spawn_edges (
                        parent_thread_id text not null,
                        child_thread_id text not null,
                        status text
                    );
                    """
                )
                conn.execute(
                    """
                    insert into threads (
                        id, rollout_path, created_at, updated_at, source,
                        model_provider, cwd, title, sandbox_policy, approval_mode, archived
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        child_thread,
                        "/tmp/child.jsonl",
                        100,
                        300,
                        '{"subagent":true}',
                        "openai",
                        "/tmp",
                        "child",
                        "workspace-write",
                        "never",
                    ),
                )
                conn.execute(
                    """
                    insert into thread_spawn_edges (
                        parent_thread_id, child_thread_id, status
                    ) values (?, ?, ?)
                    """,
                    ("parent", child_thread, "open"),
                )
                conn.commit()
            finally:
                conn.close()
            self.runner.codex_state_db = db_path
            self.assertEqual(self.runner.find_latest_thread(), child_thread)

    def test_runtime_status_ignores_newer_spawn_child_rollout_for_mirror_resolution(
        self,
    ) -> None:
        stale_thread = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
        root_thread = "019d332d-1bc8-7151-a874-ab0fbc493747"
        child_thread = "019d46e2-1b23-7e01-941b-269961074b52"
        with tempfile.TemporaryDirectory() as tmpdir:
            session_root = Path(tmpdir) / "sessions"
            session_root.mkdir(parents=True, exist_ok=True)
            stale_rollout = session_root / f"stale-{stale_thread}.jsonl"
            root_rollout = session_root / f"root-{root_thread}.jsonl"
            child_rollout = session_root / f"child-{child_thread}.jsonl"
            stale_rollout.write_text("stale\n", encoding="utf-8")
            root_rollout.write_text("root\n", encoding="utf-8")
            child_rollout.write_text("child\n", encoding="utf-8")
            os.utime(stale_rollout, (1000, 1000))
            os.utime(root_rollout, (2000, 2000))
            os.utime(child_rollout, (3000, 3000))
            db_path = Path(tmpdir) / "state.sqlite"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    create table threads (
                        id text primary key,
                        rollout_path text not null,
                        created_at integer not null,
                        updated_at integer not null,
                        source text not null,
                        model_provider text not null,
                        cwd text not null,
                        title text not null,
                        sandbox_policy text not null,
                        approval_mode text not null,
                        tokens_used integer not null default 0,
                        has_user_event integer not null default 0,
                        archived integer not null default 0
                    );
                    create table thread_spawn_edges (
                        parent_thread_id text not null,
                        child_thread_id text not null,
                        status text
                    );
                    """
                )
                for thread_id, updated_at, source in (
                    (root_thread, 2000, "cli"),
                    (
                        child_thread,
                        3000,
                        (
                            f'{{"subagent":{{"thread_spawn":{{"parent_thread_id":"{root_thread}"}}}}}}'
                        ),
                    ),
                ):
                    conn.execute(
                        """
                        insert into threads (
                            id, rollout_path, created_at, updated_at, source,
                            model_provider, cwd, title, sandbox_policy, approval_mode, archived
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                        """,
                        (
                            thread_id,
                            f"/tmp/{thread_id}.jsonl",
                            100,
                            updated_at,
                            source,
                            "openai",
                            "/tmp",
                            thread_id,
                            "workspace-write",
                            "never",
                        ),
                    )
                conn.execute(
                    """
                    insert into thread_spawn_edges (
                        parent_thread_id, child_thread_id, status
                    ) values (?, ?, ?)
                    """,
                    (root_thread, child_thread, "open"),
                )
                conn.commit()
            finally:
                conn.close()
            self.runner.session_root = session_root
            self.runner.codex_state_db = db_path
            with patch.object(self.runner, "_tmux_exists", return_value=True):
                with patch.object(
                    self.runner, "_pane_current_command", return_value="codex"
                ):
                    with patch.object(
                        self.runner, "_pane_current_path", return_value="/tmp"
                    ):
                        with patch.object(self.runner, "_pane_pid", return_value=None):
                            with patch.object(
                                self.runner,
                                "_capture_clean_text",
                                return_value=f"stale pane text {stale_thread}",
                            ):
                                status = self.runner._runtime_status_for_tmux("codex")
        self.assertEqual(status.thread_id, root_thread)

    def test_runtime_status_keeps_pane_thread_outside_workspace(self) -> None:
        stale_thread = "019cdfe5-fa14-74a3-aa31-5451128ea58d"
        fresh_thread = "019d332d-1bc8-7151-a874-ab0fbc493747"
        with tempfile.TemporaryDirectory() as tmpdir:
            session_root = Path(tmpdir) / "sessions"
            session_root.mkdir(parents=True, exist_ok=True)
            (session_root / f"fresh-{fresh_thread}.jsonl").write_text(
                "fresh\n", encoding="utf-8"
            )
            self.runner.session_root = session_root
            with patch.object(self.runner, "_tmux_exists", return_value=True):
                with patch.object(
                    self.runner, "_pane_current_command", return_value="codex"
                ):
                    with patch.object(
                        self.runner, "_pane_current_path", return_value="/var/tmp"
                    ):
                        with patch.object(self.runner, "_pane_pid", return_value=None):
                            with patch.object(
                                self.runner,
                                "_capture_clean_text",
                                return_value=f"old log {stale_thread}",
                            ):
                                with patch.object(
                                    self.runner,
                                    "_get_tmux_runtime_id",
                                    return_value=None,
                                ):
                                    with patch.object(
                                        self.runner,
                                        "find_latest_thread",
                                        return_value=fresh_thread,
                                    ):
                                        status = self.runner._runtime_status_for_tmux(
                                            "codex"
                                        )
        self.assertEqual(status.thread_id, stale_thread)


if __name__ == "__main__":
    unittest.main()
