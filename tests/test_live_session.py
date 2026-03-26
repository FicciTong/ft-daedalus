from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.live_session import LiveCodexSessionManager
from daedalus_wechat.state import SessionRecord


class LiveSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = LiveCodexSessionManager(
            codex_bin="codex",
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

    def test_send_prompt_falls_back_to_visible_pane_reply_when_final_missing(self) -> None:
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
            with patch.object(self.runner, "_capture_clean_text", side_effect=["baseline", "baseline"]):
                with patch.object(self.runner, "_resolve_rollout_file", return_value=None):
                    with patch.object(self.runner, "_inject_prompt") as inject_mock:
                        with patch.object(self.runner, "_wait_for_final_reply", return_value=""):
                            with patch.object(
                                self.runner,
                                "_collect_response",
                                return_value="VISIBLE_REPLY_OK",
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
            with patch.object(
                self.runner,
                "_capture_clean_text",
                return_value="... 019cdfe5-fa14-74a3-aa31-5451128ea58d ...",
            ):
                with patch.object(self.runner, "_inject_prompt") as inject_mock:
                    submitted = self.runner.submit_prompt(record=record, prompt="hello")
        inject_mock.assert_called_once_with("codex", "hello")
        self.assertEqual(submitted.thread_id, record.thread_id)
        self.assertEqual(submitted.tmux_session, "codex")


if __name__ == "__main__":
    unittest.main()
