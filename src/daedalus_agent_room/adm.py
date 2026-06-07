from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import AgentRoom, TmuxRoster

ADM_SYSTEM_PROMPT = """You are ADM, the owner's local intent dispatcher.

You do not write repo files, touch databases, trade, or claim authority.
Your job is to turn the owner's WeChat transcript into a short routing decision.

Reply in concise Chinese with:
1. 意图
2. 建议找谁
3. 下一步动作
4. 如果不清楚，只问一个最小澄清问题
"""


@dataclass(frozen=True)
class AdmResult:
    source_message_id: str
    topic_id: str
    reply: str
    sent_to_wechat: bool


ModelRunner = Callable[[dict[str, Any], list[str]], str]
WechatSender = Callable[[str], None]


class AdmWorker:
    def __init__(
        self,
        *,
        room: AgentRoom,
        agent_id: str,
        backend: str = "claude",
        cwd: Path | None = None,
        send_wechat: bool = False,
        model_runner: ModelRunner | None = None,
        wechat_sender: WechatSender | None = None,
    ) -> None:
        self.room = room
        self.agent_id = agent_id.strip().lstrip("@")
        if not self.agent_id:
            raise ValueError("agent_id is required")
        self.backend = backend.strip().lower()
        self.cwd = cwd or Path.cwd()
        self.send_wechat = send_wechat
        self._model_runner = model_runner or self._run_model
        self._wechat_sender = wechat_sender or self._send_wechat

    def handle_pending_once(self, *, limit: int = 1) -> list[AdmResult]:
        messages = self.room.pending_for_agent(
            agent_id=self.agent_id,
            limit=limit,
            ack=False,
        )
        results: list[AdmResult] = []
        available_agents = [
            session.agent_id for session in TmuxRoster().list_sessions()
        ]
        for message in messages:
            try:
                reply = self._model_runner(message, available_agents).strip()
            except Exception as exc:  # noqa: BLE001
                reply = f"ADM 处理失败: {str(exc)[:300]}"
            if not reply:
                reply = "ADM 没有生成有效回复。"
            self.room.send_message(
                from_actor=self.agent_id,
                mode="agent_reply",
                topic_id=str(message.get("topic_id") or ""),
                text=reply,
                metadata={
                    "source_message_id": message.get("id"),
                    "source_cursor_index": message.get("cursor_index"),
                    "backend": self.backend,
                },
            )
            sent = False
            if self.send_wechat:
                self._wechat_sender(reply)
                sent = True
            cursor_index = int(message.get("cursor_index", 0) or 0)
            self.room.ack_through(agent_id=self.agent_id, cursor_index=cursor_index)
            results.append(
                AdmResult(
                    source_message_id=str(message.get("id", "")),
                    topic_id=str(message.get("topic_id", "")),
                    reply=reply,
                    sent_to_wechat=sent,
                )
            )
        return results

    def run_forever(self, *, interval_seconds: float = 2.0, limit: int = 1) -> None:
        while True:
            self.handle_pending_once(limit=limit)
            time.sleep(max(0.2, interval_seconds))

    def _run_model(self, message: dict[str, Any], available_agents: list[str]) -> str:
        prompt = _compose_adm_prompt(message, available_agents=available_agents)
        if self.backend == "claude":
            return _run_claude(prompt, cwd=self.cwd)
        if self.backend == "codex":
            return _run_codex(prompt, cwd=self.cwd)
        raise ValueError(f"unsupported ADM backend: {self.backend}")

    def _send_wechat(self, text: str) -> None:
        subprocess.run(
            ["daedalus-wechat", "send-bound", "--stdin"],
            input=text,
            text=True,
            cwd=self.cwd,
            check=True,
        )


def _compose_adm_prompt(message: dict[str, Any], *, available_agents: list[str]) -> str:
    metadata = message.get("metadata") or {}
    raw_transcript = str(metadata.get("raw_transcript") or message.get("text") or "")
    source_kind = str(metadata.get("source_kind") or "room")
    available = ", ".join(available_agents) if available_agents else "none"
    return (
        f"{ADM_SYSTEM_PROMPT}\n\n"
        f"available_tmux_sessions={available}\n"
        f"source_kind={source_kind}\n"
        f"topic_id={message.get('topic_id')}\n\n"
        "Owner message:\n"
        f"{raw_transcript}\n\n"
        "Return only the owner-facing ADM reply."
    )


def _run_claude(prompt: str, *, cwd: Path) -> str:
    result = subprocess.run(
        [
            "claude",
            "-p",
            "--tools",
            "",
            "--output-format",
            "text",
            "--system-prompt",
            ADM_SYSTEM_PROMPT,
            prompt,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run_codex(prompt: str, *, cwd: Path) -> str:
    result = subprocess.run(
        [
            "codex",
            "exec",
            "-C",
            str(cwd),
            "-s",
            "read-only",
            "-a",
            "never",
            prompt,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
