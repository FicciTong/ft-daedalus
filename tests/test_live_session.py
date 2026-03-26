from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_wechat_bridge.live_session import LiveCodexSessionManager


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
            with patch("codex_wechat_bridge.live_session.time.sleep", lambda _: None):
                with patch(
                    "codex_wechat_bridge.live_session.time.monotonic",
                    side_effect=lambda: next(ticks),
                ):
                    reply = self.runner._wait_for_final_reply(
                        rollout_file=rollout,
                        start_offset=0,
                    )
            self.assertEqual(reply, "WECHAT_FINAL_ONLY_OK")


if __name__ == "__main__":
    unittest.main()
