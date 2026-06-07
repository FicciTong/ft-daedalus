from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import AgentRoom

ROOM_AGENT_SYSTEM_PROMPT = """You are one local agent in the owner's visible room.

Rules:
- Reply to the owner in concise Chinese.
- Do not edit files, touch databases, run trading actions, or claim authority.
- Treat this as owner-visible coordination, not a private side channel.
- If the requested work requires implementation, say what you can do next and
  wait for the owner or main writer to actually assign execution authority.
"""


@dataclass(frozen=True)
class RoomPumpResult:
    agent_id: str
    source_message_id: str
    topic_id: str
    mode: str
    reply: str
    backend: str
    sent_to_room: bool
    skipped: bool = False


ModelRunner = Callable[[dict[str, Any]], str]


class RoomPumpWorker:
    def __init__(
        self,
        *,
        room: AgentRoom,
        agent_id: str,
        backend: str,
        cwd: Path,
        codex_bin: str = "codex",
        claude_bin: str = "claude",
        opencode_bin: str = "opencode",
        timeout_seconds: float = 180.0,
        model_runner: ModelRunner | None = None,
    ) -> None:
        self.room = room
        self.agent_id = agent_id.strip().lstrip("@")
        if not self.agent_id:
            raise ValueError("agent_id is required")
        self.backend = str(backend or "unknown").strip().lower()
        self.cwd = cwd
        self.codex_bin = codex_bin
        self.claude_bin = claude_bin
        self.opencode_bin = opencode_bin
        self.timeout_seconds = max(5.0, float(timeout_seconds))
        self._model_runner = model_runner or self._run_model

    def handle_pending_once(self, *, limit: int = 1) -> list[RoomPumpResult]:
        messages = self.room.pending_for_agent(
            agent_id=self.agent_id,
            limit=limit,
            ack=False,
        )
        results: list[RoomPumpResult] = []
        for message in messages:
            cursor_index = int(message.get("cursor_index", 0) or 0)
            if self._should_skip_message(message):
                self.room.ack_through(
                    agent_id=self.agent_id,
                    cursor_index=cursor_index,
                )
                results.append(self._skipped_result(message, reply="skipped"))
                continue
            try:
                reply = self._model_runner(message).strip()
            except Exception as exc:  # noqa: BLE001
                reply = f"自动回复失败: {str(exc)[:300]}"
            if not reply:
                reply = "自动回复没有生成有效内容。"
            self.room.send_message(
                from_actor=self.agent_id,
                mode="agent_reply",
                topic_id=str(message.get("topic_id") or ""),
                text=reply,
                source="agent-room-pump",
                metadata={
                    "source_message_id": message.get("id"),
                    "source_cursor_index": cursor_index,
                    "backend": self.backend,
                    "owner_visible": True,
                },
            )
            self.room.ack_through(agent_id=self.agent_id, cursor_index=cursor_index)
            results.append(
                RoomPumpResult(
                    agent_id=self.agent_id,
                    source_message_id=str(message.get("id", "")),
                    topic_id=str(message.get("topic_id", "")),
                    mode=str(message.get("mode", "")),
                    reply=reply,
                    backend=self.backend,
                    sent_to_room=True,
                )
            )
        return results

    def _should_skip_message(self, message: dict[str, Any]) -> bool:
        metadata = message.get("metadata") or {}
        if str(message.get("mode", "")).strip() == "agent_reply":
            return True
        return bool(metadata.get("terminal_delivery"))

    def _skipped_result(self, message: dict[str, Any], *, reply: str) -> RoomPumpResult:
        return RoomPumpResult(
            agent_id=self.agent_id,
            source_message_id=str(message.get("id", "")),
            topic_id=str(message.get("topic_id", "")),
            mode=str(message.get("mode", "")),
            reply=reply,
            backend=self.backend,
            sent_to_room=False,
            skipped=True,
        )

    def _run_model(self, message: dict[str, Any]) -> str:
        prompt = _compose_room_agent_prompt(
            agent_id=self.agent_id,
            backend=self.backend,
            message=message,
        )
        if self.backend == "codex":
            return _run_codex(
                prompt,
                cwd=self.cwd,
                codex_bin=self.codex_bin,
                timeout_seconds=self.timeout_seconds,
            )
        if self.backend in {"claude", "claude-code"}:
            return _run_claude(
                prompt,
                cwd=self.cwd,
                claude_bin=self.claude_bin,
                timeout_seconds=self.timeout_seconds,
            )
        if self.backend == "opencode":
            return (
                "我看到了这条 room 消息，但 OpenCode 当前没有启用自动回复。"
                "原因: 本机 OpenCode agent 配置是 allow-all，不能作为无人值守 "
                "read-only pump。请 owner 明确 @codex 或 @claude，或者先配置 "
                "OpenCode 的只读自动回复 agent。"
            )
        return f"我看到了这条 room 消息，但 backend={self.backend or 'unknown'} 暂未启用自动回复。"


def _compose_room_agent_prompt(
    *,
    agent_id: str,
    backend: str,
    message: dict[str, Any],
) -> str:
    recipients = ", ".join(str(value) for value in (message.get("to") or [])) or "all"
    return (
        f"{ROOM_AGENT_SYSTEM_PROMPT}\n"
        f"agent_id={agent_id}\n"
        f"backend={backend}\n"
        f"topic_id={message.get('topic_id')}\n"
        f"mode={message.get('mode')}\n"
        f"from={message.get('from')}\n"
        f"to={recipients}\n"
        f"round_limit={message.get('round_limit')}\n\n"
        "Owner-visible room message:\n"
        f"{message.get('text', '')}\n\n"
        "Reply as this agent only. Do not mention private reasoning."
    )


def _run_codex(
    prompt: str,
    *,
    cwd: Path,
    codex_bin: str,
    timeout_seconds: float,
) -> str:
    with tempfile.NamedTemporaryFile("r+", encoding="utf-8") as output_file:
        result = subprocess.run(
            [
                codex_bin,
                "exec",
                "-C",
                str(cwd),
                "-s",
                "read-only",
                "--ephemeral",
                "--color",
                "never",
                "--output-last-message",
                output_file.name,
                prompt,
            ],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        output_file.seek(0)
        reply = output_file.read().strip()
    if reply:
        return reply
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(stderr[:500] or f"codex exited {result.returncode}")
    return result.stdout.strip()


def _run_claude(
    prompt: str,
    *,
    cwd: Path,
    claude_bin: str,
    timeout_seconds: float,
) -> str:
    result = subprocess.run(
        [
            claude_bin,
            "-p",
            "--tools",
            "",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            "--output-format",
            "text",
            "--system-prompt",
            ROOM_AGENT_SYSTEM_PROMPT,
            prompt,
        ],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(stderr[:500] or f"claude exited {result.returncode}")
    return result.stdout.strip()
