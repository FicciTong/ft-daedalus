from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

from .config import BridgeConfig
from .live_session import LiveCodexSessionManager
from .state import BridgeState
from .wechat_api import WeChatClient


HELP_TEXT = """可用命令:
/help            显示帮助
/status          查看当前 active session
/sessions        列出 bridge 已知 sessions
/new [label]     新建一个本地 Codex session 并切过去
/switch <编号|id前缀|label|tmux> 切换 active session
/attach-last     接管 ft-cosmos 最近一个本地 Codex session
/stop            取消当前 active session

普通文本消息会直接续写 `tmux codex` 里当前活着的那条 session。
如果 `tmux codex` 还没打开 Codex，bridge 会明确提示你先去启动/恢复。
"""


@dataclass(frozen=True)
class IncomingMessage:
    from_user_id: str
    context_token: str | None
    body: str
    message_id: str


class BridgeDaemon:
    def __init__(
        self,
        *,
        config: BridgeConfig,
        wechat: WeChatClient,
        runner: LiveCodexSessionManager,
        state: BridgeState,
    ) -> None:
        self.config = config
        self.wechat = wechat
        self.runner = runner
        self.state = state
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self._bootstrap_runtime()

    def run_forever(self) -> None:
        while True:
            response = self.wechat.get_updates(self.state.get_updates_buf)
            self.state.get_updates_buf = response.get(
                "get_updates_buf", self.state.get_updates_buf
            )
            self._save_state()
            for raw in response.get("msgs", []) or []:
                incoming = self._parse_incoming(raw)
                if incoming is None:
                    continue
                self._log_event("incoming", {"body": incoming.body, "from": incoming.from_user_id})
                if not self._is_authorized_sender(incoming.from_user_id):
                    self._reply(
                        incoming.from_user_id,
                        incoming.context_token,
                        "❌ 当前微信账号未被授权控制此 bridge。",
                    )
                    self._log_event(
                        "unauthorized",
                        {"from": incoming.from_user_id},
                    )
                    continue
                try:
                    self._handle_incoming(incoming)
                except Exception as exc:  # noqa: BLE001
                    self._reply(
                        incoming.from_user_id,
                        incoming.context_token,
                        f"❌ bridge error: {str(exc)[:300]}",
                    )
                    self._log_event("error", {"error": str(exc)})

    def _handle_incoming(self, incoming: IncomingMessage) -> None:
        body = incoming.body.strip()
        if not body:
            return
        if body.startswith("/") or body.startswith("\\"):
            reply = self._handle_command(body)
        else:
            reply = self._handle_prompt(body)
        self._reply(incoming.from_user_id, incoming.context_token, reply)

    def _handle_command(self, body: str) -> str:
        if body.startswith("\\"):
            body = "/" + body[1:]
        parts = body.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command == "/help":
            return HELP_TEXT
        if command == "/status":
            return self._status_text()
        if command == "/sessions":
            return self._sessions_text()
        if command == "/stop":
            self.state.active_session_id = None
            self._save_state()
            return "已清空 active session。"
        if command == "/attach-last":
            record = self.runner.ensure_attached_latest(self.state)
            if not record:
                return "没有找到最近的 ft-cosmos 本地 Codex session。"
            self.state.active_session_id = record.thread_id
            self._save_state()
            return (
                f"已接管最近 session:\n{record.thread_id}\n"
                f"label={record.label}\n"
                f"tmux={record.tmux_session}\n"
                f"attach={self.runner.attach_hint(record)}"
            )
        if command == "/new":
            label = arg or f"session-{datetime.now(UTC).strftime('%m%d-%H%M%S')}"
            record = self.runner.create_new_session(state=self.state, label=label)
            self.state.active_session_id = record.thread_id
            self._save_state()
            return (
                f"已新建并切换到 session:\n{record.thread_id}\n"
                f"label={label}\n"
                f"tmux={record.tmux_session}\n"
                f"attach={self.runner.attach_hint(record)}"
            )
        if command == "/switch":
            if not arg:
                return "用法: /switch <编号|thread_id前缀|label|tmux>"
            match = self._resolve_session(arg)
            if not match:
                return f"没有找到 session: {arg}"
            self.state.active_session_id = match
            record = self.state.sessions[match]
            refreshed = self.runner.ensure_resumed_session(
                thread_id=record.thread_id,
                state=self.state,
                label=record.label,
                source=record.source,
            )
            refreshed.updated_at = datetime.now(UTC).isoformat()
            self._save_state()
            return (
                f"已切换到 session:\n{match}\n"
                f"label={refreshed.label}\n"
                f"tmux={refreshed.tmux_session}\n"
                f"attach={self.runner.attach_hint(refreshed)}"
            )
        return f"未知命令: {command}\n\n{HELP_TEXT}"

    def _handle_prompt(self, body: str) -> str:
        active_record = self.runner.require_live_session(self.state)
        result = self.runner.send_prompt(record=active_record, prompt=body)
        refreshed = self.state.touch_session(
            result.thread_id,
            label=active_record.label,
            cwd=active_record.cwd,
            source=active_record.source,
            tmux_session=active_record.tmux_session,
        )
        self.state.active_session_id = result.thread_id
        self._save_state()
        return result.response_text or "(无文本回复)"

    def _bootstrap_runtime(self) -> None:
        record = self.runner.try_live_session(self.state)
        if record:
            self.state.active_session_id = record.thread_id
            self._save_state()

    def _resolve_session(self, query: str) -> str | None:
        query = query.strip()
        ordered = self._ordered_sessions()
        if query.isdigit():
            index = int(query)
            if 1 <= index <= len(ordered):
                return ordered[index - 1].thread_id
        if query in self.state.sessions:
            return query
        candidates = [
            thread_id
            for thread_id, record in self.state.sessions.items()
            if thread_id.startswith(query)
            or record.label == query
            or (record.tmux_session and record.tmux_session == query)
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _ordered_sessions(self) -> list:
        return sorted(
            self.state.sessions.values(), key=lambda item: item.updated_at, reverse=True
        )

    def _status_text(self) -> str:
        runtime = self.runner.current_runtime_status()
        if not runtime.exists:
            return (
                "当前 canonical tmux 不存在。\n"
                f"tmux={runtime.tmux_session}\n"
                "请先启动：\n"
                f"tmux new -s {runtime.tmux_session} "
                f"'{self.config.codex_bin} resume --last -C {self.config.default_cwd} --no-alt-screen'"
            )
        if runtime.pane_command not in {"node", "codex"}:
            return (
                "当前 canonical tmux 已存在，但里面不是 Codex。\n"
                f"tmux={runtime.tmux_session}\n"
                f"pane_current_command={runtime.pane_command or 'unknown'}\n"
                "请先 attach 进去并启动/恢复 Codex。"
            )
        if not runtime.thread_id:
            return (
                "当前 canonical tmux 已打开，但还没有进入任何 Codex thread。\n"
                f"tmux={runtime.tmux_session}\n"
                "请先 attach 后执行：\n"
                f"codex resume --last -C {self.config.default_cwd} --no-alt-screen"
            )
        self.state.active_session_id = runtime.thread_id
        self._save_state()
        record = self.state.sessions.get(self.state.active_session_id)
        if not record:
            return f"当前 active session={self.state.active_session_id}，但 registry 里缺记录。"
        return (
            "当前 active session:\n"
            f"id={record.thread_id}\n"
            f"label={record.label}\n"
            f"cwd={record.cwd}\n"
            f"source={record.source}\n"
            f"tmux={record.tmux_session}\n"
            f"attach={self.runner.attach_hint(record)}\n"
            f"updated_at={record.updated_at}"
        )

    def _sessions_text(self) -> str:
        runtime = self.runner.current_runtime_status()
        if not self.state.sessions:
            if runtime.exists:
                return (
                    "bridge 里还没有已知 session 记录，但 canonical tmux 已存在。\n"
                    f"tmux={runtime.tmux_session}\n"
                    f"thread={runtime.thread_id or 'none'}"
                )
            return "bridge 里还没有已知 session。"
        ordered = self._ordered_sessions()
        lines = []
        for idx, record in enumerate(ordered[:20], start=1):
            marker = "*" if record.thread_id == self.state.active_session_id else " "
            lines.append(
                f"{marker} [{idx}] {record.label} | {record.thread_id[:8]} | {record.tmux_session or '-'} | {record.updated_at}"
            )
        return (
            "已知 sessions:\n"
            + "\n".join(lines)
            + "\n\n当前 canonical tmux:\n"
            + runtime.tmux_session
            + "\n\n切换示例:\n/switch 1\n/switch attached-last\n/switch codex"
        )

    def _reply(self, to_user_id: str, context_token: str | None, text: str) -> None:
        for chunk in self._chunk_text(text):
            self.wechat.send_text(
                to_user_id=to_user_id, context_token=context_token, text=chunk
            )
            self._log_event("outgoing", {"to": to_user_id, "text": chunk[:400]})

    def _chunk_text(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return ["(空回复)"]
        limit = self.config.text_chunk_limit
        if len(text) <= limit:
            return [text]
        chunks: list[str] = []
        current = text
        while current:
            piece = current[:limit]
            chunks.append(piece)
            current = current[limit:]
        return chunks

    def _parse_incoming(self, raw: dict) -> IncomingMessage | None:
        if raw.get("message_type") != 1:
            return None
        body = ""
        for item in raw.get("item_list", []) or []:
            if item.get("type") == 1:
                body = str(item.get("text_item", {}).get("text", "")).strip()
                break
            if item.get("type") == 3:
                voice_text = item.get("voice_item", {}).get("text")
                if voice_text:
                    body = str(voice_text).strip()
                    break
        if not body:
            return None
        return IncomingMessage(
            from_user_id=str(raw.get("from_user_id", "")),
            context_token=raw.get("context_token"),
            body=body,
            message_id=str(raw.get("message_id", "")),
        )

    def _is_authorized_sender(self, from_user_id: str) -> bool:
        if not self.config.allowed_users:
            return True
        return from_user_id in self.config.allowed_users

    def _save_state(self) -> None:
        self.state.save(self.config.state_file)

    def _log_event(self, kind: str, payload: dict) -> None:
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        with self.config.event_log_file.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "ts": datetime.now(UTC).isoformat(),
                        "kind": kind,
                        "payload": payload,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
