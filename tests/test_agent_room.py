from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from daedalus_agent_room.adm import AdmWorker
from daedalus_agent_room.cli import main
from daedalus_agent_room.core import AgentRoom, TmuxRoster
from daedalus_agent_room.pump import RoomPumpWorker


class AgentRoomTests(unittest.TestCase):
    def test_send_message_appends_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            room = AgentRoom(Path(tmpdir))
            payload = room.send_message(
                from_actor="owner",
                to=["codex-a", "@claude-a"],
                mode="debate",
                text="讨论 5 轮，不准写代码",
                round_limit=5,
            )

            self.assertEqual(payload["from"], "owner")
            self.assertEqual(payload["to"], ["codex-a", "claude-a"])
            self.assertEqual(payload["mode"], "debate")
            self.assertEqual(payload["round_limit"], 5)
            self.assertFalse(payload["write_allowed"])

            lines = room.messages_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["id"], payload["id"])
            self.assertEqual(record["text"], "讨论 5 轮，不准写代码")

    def test_pause_resume_writes_control_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            room = AgentRoom(Path(tmpdir))

            paused = room.set_paused(paused=True, by="owner", reason="stop loop")
            self.assertTrue(paused["paused"])
            self.assertTrue(room.read_control()["paused"])

            resumed = room.set_paused(paused=False, by="owner", reason="continue")
            self.assertFalse(resumed["paused"])
            self.assertFalse(room.read_control()["paused"])

            events = [
                json.loads(line)
                for line in room.messages_file.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [event["kind"] for event in events], ["room_paused", "room_resumed"]
            )

    def test_artifact_ledger_appends_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            room = AgentRoom(Path(tmpdir))
            payload = room.record_artifact(
                path="var/reports/research_os/daily_packet_latest.json",
                by="codex-a",
                topic_id="topic-1",
                note="ready for review",
            )

            self.assertEqual(payload["by"], "codex-a")
            rows = room.artifact_ledger_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0])["topic_id"], "topic-1")

    def test_tmux_roster_is_read_only_list_sessions(self) -> None:
        commands: list[list[str]] = []

        def fake_runner(
            args: list[str],
            *,
            check: bool = False,
            capture_output: bool = False,
            text: bool = False,
        ) -> subprocess.CompletedProcess[str]:
            commands.append(args)
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="codex-a\t1\t2\nclaude-a\t0\t1\n",
                stderr="",
            )

        sessions = TmuxRoster(command_runner=fake_runner).list_sessions()

        self.assertEqual(
            [session.agent_id for session in sessions], ["codex-a", "claude-a"]
        )
        self.assertEqual(
            commands,
            [
                [
                    "tmux",
                    "list-sessions",
                    "-F",
                    "#{session_name}\t#{session_attached}\t#{session_windows}",
                ]
            ],
        )
        flattened = " ".join(commands[0])
        self.assertNotIn("send-keys", flattened)
        self.assertNotIn("kill", flattened)
        self.assertNotIn("rename", flattened)

    def test_cli_send_writes_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rc = main(
                [
                    "--room-dir",
                    tmpdir,
                    "send",
                    "--from",
                    "owner",
                    "--to",
                    "codex-a",
                    "--mode",
                    "task",
                    "修 packet",
                ]
            )

            self.assertEqual(rc, 0)
            rows = (
                (Path(tmpdir) / "messages.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            self.assertEqual(len(rows), 1)
            payload = json.loads(rows[0])
            self.assertEqual(payload["mode"], "task")
            self.assertEqual(payload["to"], ["codex-a"])

    def test_adm_worker_replies_and_advances_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            room = AgentRoom(Path(tmpdir))
            room.send_message(
                from_actor="owner",
                to=["adm"],
                mode="task",
                text="帮我判断应该找谁",
            )
            sent: list[str] = []
            worker = AdmWorker(
                room=room,
                agent_id="adm",
                model_runner=lambda message, agents: "意图: 分派\n建议找: codex",
                wechat_sender=sent.append,
                send_wechat=True,
            )

            results = worker.handle_pending_once()

            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].sent_to_wechat)
            self.assertEqual(sent, ["意图: 分派\n建议找: codex"])
            rows = [
                json.loads(line)
                for line in room.messages_file.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(rows[-1]["from"], "adm")
            self.assertEqual(rows[-1]["mode"], "agent_reply")
            self.assertEqual(room.pending_for_agent(agent_id="adm"), [])

    def test_room_pump_worker_consumes_announce_and_writes_agent_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            room = AgentRoom(Path(tmpdir))
            source = room.send_message(
                from_actor="owner",
                mode="announce",
                text="hi",
                source="wechat-room-broadcast",
            )
            seen: list[str] = []
            worker = RoomPumpWorker(
                room=room,
                agent_id="codex",
                backend="codex",
                cwd=Path(tmpdir),
                model_runner=lambda message: seen.append(message["id"]) or "收到",
            )

            results = worker.handle_pending_once()

            self.assertEqual(seen, [source["id"]])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].reply, "收到")
            rows = [
                json.loads(line)
                for line in room.messages_file.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(rows[-1]["from"], "codex")
            self.assertEqual(rows[-1]["mode"], "agent_reply")
            self.assertEqual(rows[-1]["source"], "agent-room-pump")
            self.assertEqual(room.pending_for_agent(agent_id="codex"), [])

    def test_room_pump_worker_skips_terminal_delivery_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            room = AgentRoom(Path(tmpdir))
            room.send_message(
                from_actor="owner",
                to=["codex"],
                mode="message",
                text="already terminal-delivered",
                source="wechat-room-target-terminal",
                metadata={"terminal_delivery": True},
            )
            worker = RoomPumpWorker(
                room=room,
                agent_id="codex",
                backend="codex",
                cwd=Path(tmpdir),
                model_runner=lambda _message: "should not run",
            )

            results = worker.handle_pending_once()

            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].skipped)
            rows = room.messages_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)
            self.assertEqual(room.pending_for_agent(agent_id="codex"), [])
