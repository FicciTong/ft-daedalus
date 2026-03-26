from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from queue import Empty, Queue
import threading
import time
from zoneinfo import ZoneInfo

from .config import BridgeConfig
from .delivery_ledger import append_delivery, read_recent_for_user
from .live_session import LiveCodexSessionManager
from .state import BridgeState
from .wechat_api import WeChatClient
from .systemd_notify import notify as systemd_notify

DISPLAY_TZ = ZoneInfo("Asia/Shanghai")


HELP_TEXT = """FT bridge 命令总览

会话:
/status            当前 active session / tmux / cwd
/health            bridge / tmux / thread 健康检查
/sessions          可切换 session 列表
/switch <target>   切换到某个 session
/attach-last       接最近一个 ft-cosmos session
/new [label]       新建一个本地 Codex session
/stop              清空当前 active session

通知:
/notify on         微信收 progress + final
/notify off        微信只收 final
/notify status     查看当前通知模式

追溯:
/recent 10         看最近 10 条 delivery ledger
/recent after 128  从 seq=128 之后继续看

帮助:
/help              显示这页
/menu              同 /help

普通文本消息 = 直接发给当前 `tmux codex` 里的 live session。
如果 `tmux codex` 还没打开 Codex，bridge 会明确提示你先启动/恢复。
"""


@dataclass(frozen=True)
class IncomingMessage:
    from_user_id: str
    context_token: str | None
    body: str
    message_id: str
    is_voice: bool = False
    has_transcript: bool = False


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
        self._lock = threading.RLock()
        self._prompt_queue: Queue[IncomingMessage] = Queue()
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        if self.state.progress_updates_enabled is None:
            self.state.progress_updates_enabled = self.config.progress_updates_default
        self._bootstrap_runtime()
        self._start_mirror_thread()
        self._start_prompt_thread()
        systemd_notify("READY=1")
        systemd_notify("STATUS=bridge running")

    def run_forever(self) -> None:
        while True:
            try:
                response = self.wechat.get_updates(self.state.get_updates_buf)
            except Exception as exc:  # noqa: BLE001
                self._log_event("poll_error", {"error": str(exc)})
                systemd_notify("STATUS=bridge poll error; retrying")
                time.sleep(2.0)
                continue
            ret = response.get("ret")
            errcode = response.get("errcode")
            if ret not in (None, 0) or errcode not in (None, 0):
                self._log_event(
                    "poll_error",
                    {
                        "ret": ret,
                        "errcode": errcode,
                        "errmsg": response.get("errmsg"),
                    },
                )
                if ret == -14 or errcode == -14:
                    with self._lock:
                        self.state.get_updates_buf = ""
                        self._save_state()
                systemd_notify("STATUS=bridge poll error; retrying")
                time.sleep(2.0)
                continue
            with self._lock:
                self.state.get_updates_buf = response.get(
                    "get_updates_buf", self.state.get_updates_buf
                )
                self._save_state()
            for raw in response.get("msgs", []) or []:
                incoming = self._parse_incoming(raw)
                if incoming is None:
                    continue
                body_preview = incoming.body or (
                    "<voice-no-transcript>" if incoming.is_voice else "<empty>"
                )
                self._log_event(
                    "incoming", {"body": body_preview, "from": incoming.from_user_id}
                )
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
        self._bind_peer(incoming.from_user_id, incoming.context_token)
        body = incoming.body.strip()
        if incoming.is_voice and not incoming.has_transcript:
            self._reply(
                incoming.from_user_id,
                incoming.context_token,
                "⚠️ 收到语音，但微信这次没有给出可用转写。我已经刷新会话绑定；你可以重试语音，或直接发文字。",
                kind="progress",
                origin="wechat-voice",
                thread_id=self.state.active_session_id,
            )
            return
        if not body:
            return
        if body.startswith("/") or body.startswith("\\"):
            with self._lock:
                reply = self._handle_command(body)
                thread_id = self.state.active_session_id
            self._reply(
                incoming.from_user_id,
                incoming.context_token,
                reply,
                kind="command",
                origin="wechat-command",
                thread_id=thread_id,
            )
            return
        queue_depth = self._enqueue_prompt(incoming)
        reply = (
            "已收到，开始处理。"
            if queue_depth <= 1
            else f"已收到，已入队。前面还有 {queue_depth - 1} 条。"
        )
        self._reply(
            incoming.from_user_id,
            incoming.context_token,
            reply,
            kind="progress",
            origin="wechat-prompt-queued",
            thread_id=self.state.active_session_id,
        )

    def _handle_command(self, body: str) -> str:
        if body.startswith("\\"):
            body = "/" + body[1:]
        parts = body.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command in {"/help", "/menu"}:
            return HELP_TEXT
        if command == "/status":
            return self._status_text()
        if command == "/health":
            return self._health_text()
        if command == "/notify":
            return self._notify_text(arg)
        if command == "/recent":
            return self._recent_text(arg)
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
            self._sync_mirror_cursor(record.thread_id)
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
            self._sync_mirror_cursor(record.thread_id)
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
            self._sync_mirror_cursor(refreshed.thread_id)
            self._save_state()
            return (
                f"已切换到 session:\n{match}\n"
                f"label={refreshed.label}\n"
                f"tmux={refreshed.tmux_session}\n"
                f"attach={self.runner.attach_hint(refreshed)}"
            )
        return f"未知命令: {command}\n\n{HELP_TEXT}"

    def _notify_text(self, arg: str) -> str:
        normalized = arg.strip().lower()
        if not normalized or normalized == "status":
            return (
                "notify=progress+final"
                if self._progress_updates_enabled()
                else "notify=final-only"
            )
        if normalized in {"on", "progress", "enable"}:
            self.state.progress_updates_enabled = True
            self._save_state()
            return "notify=progress+final"
        if normalized in {"off", "final", "disable"}:
            self.state.progress_updates_enabled = False
            self._save_state()
            return "notify=final-only"
        return "用法: /notify on|off|status"

    def _recent_text(self, arg: str) -> str:
        limit = 6
        after_seq: int | None = None
        normalized = arg.strip()
        if normalized.isdigit():
            limit = max(1, min(int(normalized), 20))
        elif normalized.lower().startswith("after "):
            tail = normalized.split(maxsplit=1)[1].strip()
            if tail.isdigit():
                after_seq = int(tail)
                limit = 20
        target_user = self.state.bound_user_id
        if not target_user:
            return "recent=empty\nhint=先发 /status 绑定当前微信会话"
        path = self.config.delivery_ledger_file
        if not path.exists():
            return "recent=empty\nhint=还没有出站记录"
        items = read_recent_for_user(
            ledger_file=path,
            to_user_id=target_user,
            limit=limit,
            after_seq=after_seq,
        )
        if not items:
            return "recent=empty\nhint=当前会话还没有可补看的已发送消息"
        lines = []
        for item in items:
            ts = self._display_time(item.get("ts"))
            seq = int(item.get("seq", 0) or 0)
            status = str(item.get("status", "unknown"))
            kind = str(item.get("kind", "message"))
            text = str(item.get("text", "")).strip()
            lines.append(f"[{seq}][{status}][{kind}][{ts}] {text}")
        last_seq = int(items[-1].get("seq", 0) or 0)
        return "recent:\n" + "\n\n".join(lines) + f"\n\nnext=/recent after {last_seq}"

    def _enqueue_prompt(self, incoming: IncomingMessage) -> int:
        self._prompt_queue.put(incoming)
        return self._prompt_queue.qsize()

    def _process_prompt(self, incoming: IncomingMessage) -> None:
        with self._lock:
            active_record = self.runner.require_live_session(self.state)
        result = self.runner.send_prompt(record=active_record, prompt=incoming.body)
        with self._lock:
            refreshed = self.state.touch_session(
                result.thread_id,
                label=active_record.label,
                cwd=active_record.cwd,
                source=active_record.source,
                tmux_session=active_record.tmux_session,
            )
            self.state.active_session_id = result.thread_id
            self._sync_mirror_cursor(result.thread_id)
            self._save_state()
        self._reply(
            incoming.from_user_id,
            incoming.context_token,
            result.response_text or "(无文本回复)",
            kind="final",
            origin="wechat-prompt",
            thread_id=refreshed.thread_id,
        )

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
                "status=missing_tmux\n"
                f"tmux={runtime.tmux_session}\n"
                "hint=先启动 canonical tmux"
            )
        if runtime.pane_command not in {"node", "codex"}:
            return (
                "status=tmux_not_codex\n"
                f"tmux={runtime.tmux_session}\n"
                f"pane={runtime.pane_command or 'unknown'}\n"
                "hint=attach 后启动或恢复 codex"
            )
        if not runtime.thread_id:
            return (
                "status=no_thread\n"
                f"tmux={runtime.tmux_session}\n"
                "hint=attach 后 resume --last"
            )
        self.state.active_session_id = runtime.thread_id
        self._save_state()
        record = self.state.sessions.get(self.state.active_session_id)
        if not record:
            return (
                "status=registry_missing\n"
                f"thread={self._short_thread(runtime.thread_id)}\n"
                f"tmux={runtime.tmux_session}"
            )
        return (
            "status=ok\n"
            f"thread={self._short_thread(record.thread_id)}\n"
            f"label={record.label}\n"
            f"tmux={record.tmux_session}\n"
            f"cwd={self._short_cwd(record.cwd)}\n"
            f"notify={'progress+final' if self._progress_updates_enabled() else 'final-only'}\n"
            f"attach={self.runner.attach_hint(record)}"
        )

    def _sessions_text(self) -> str:
        runtime = self.runner.current_runtime_status()
        if not self.state.sessions:
            if runtime.exists:
                return (
                    "sessions=0\n"
                    f"tmux={runtime.tmux_session}\n"
                    f"thread={self._short_thread(runtime.thread_id) if runtime.thread_id else 'none'}"
                )
            return "sessions=0"
        ordered = self._ordered_sessions()
        lines = [f"sessions={len(ordered)}"]
        for idx, record in enumerate(ordered[:20], start=1):
            marker = "*" if record.thread_id == self.state.active_session_id else " "
            lines.append(
                f"{marker}{idx} {record.label} | {self._short_thread(record.thread_id)} | {record.tmux_session or '-'}"
            )
        return (
            "\n".join(lines)
            + "\nuse=/switch 1"
        )

    def _health_text(self) -> str:
        runtime = self.runner.current_runtime_status()
        if not runtime.exists:
            status = "degraded"
        elif runtime.pane_command not in {"node", "codex"}:
            status = "degraded"
        elif not runtime.thread_id:
            status = "degraded"
        else:
            status = "ok"
        access = (
            f"locked:{len(self.config.allowed_users)}"
            if self.config.allowed_users
            else "open"
        )
        wechat_account = getattr(getattr(self.wechat, "account", None), "account_id", "unknown")
        lines = [
            f"health={status}",
            f"tmux={runtime.tmux_session}",
            f"pane={runtime.pane_command or 'none'}",
            f"thread={self._short_thread(runtime.thread_id) if runtime.thread_id else 'none'}",
            f"wechat={wechat_account}",
            f"access={access}",
            f"notify={'progress+final' if self._progress_updates_enabled() else 'final-only'}",
        ]
        return "\n".join(lines)

    def _reply(
        self,
        to_user_id: str,
        context_token: str | None,
        text: str,
        *,
        use_context_token: bool = True,
        kind: str = "message",
        origin: str = "bridge",
        thread_id: str | None = None,
    ) -> None:
        effective_context = context_token if use_context_token else None
        for chunk in self._chunk_text(text):
            try:
                self.wechat.send_text(
                    to_user_id=to_user_id,
                    context_token=effective_context,
                    text=chunk,
                )
                with self._lock:
                    self._log_event("outgoing", {"to": to_user_id, "text": chunk[:400]})
                    append_delivery(
                        state=self.state,
                        state_file=self.config.state_file,
                        ledger_file=self.config.delivery_ledger_file,
                        to_user_id=to_user_id,
                        text=chunk,
                        status="sent",
                        kind=kind,
                        origin=origin,
                        thread_id=thread_id,
                    )
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.state.enqueue_pending_with_meta(
                        to_user_id=to_user_id,
                        text=chunk,
                        kind=kind,
                        origin=origin,
                        thread_id=thread_id,
                    )
                    self._save_state()
                    self._log_event(
                        "queued_outgoing",
                        {"to": to_user_id, "text": chunk[:400], "error": str(exc)},
                    )
                    append_delivery(
                        state=self.state,
                        state_file=self.config.state_file,
                        ledger_file=self.config.delivery_ledger_file,
                        to_user_id=to_user_id,
                        text=chunk,
                        status="queued",
                        kind=kind,
                        origin=origin,
                        thread_id=thread_id,
                        error=str(exc),
                    )
                return

    def _start_mirror_thread(self) -> None:
        thread = threading.Thread(
            target=self._mirror_loop,
            name="codex-wechat-final-mirror",
            daemon=True,
        )
        thread.start()

    def _start_prompt_thread(self) -> None:
        thread = threading.Thread(
            target=self._prompt_worker_loop,
            name="codex-wechat-prompt-worker",
            daemon=True,
        )
        thread.start()

    def _mirror_loop(self) -> None:
        while True:
            time.sleep(1.0)
            try:
                self._mirror_desktop_final_if_any()
            except Exception as exc:  # noqa: BLE001
                self._log_event("mirror_error", {"error": str(exc)})

    def _prompt_worker_loop(self) -> None:
        while True:
            try:
                incoming = self._prompt_queue.get(timeout=1.0)
            except Empty:
                continue
            try:
                self._process_prompt(incoming)
            except Exception as exc:  # noqa: BLE001
                self._reply(
                    incoming.from_user_id,
                    incoming.context_token,
                    f"❌ bridge error: {str(exc)[:300]}",
                    kind="final",
                    origin="wechat-prompt-error",
                )
                self._log_event("prompt_error", {"error": str(exc)})
            finally:
                self._prompt_queue.task_done()

    def _mirror_desktop_final_if_any(self) -> None:
        thread_id = self._current_mirror_thread_id()
        with self._lock:
            to_user_id = self.state.bound_user_id
            bound_context_token = self.state.bound_context_token
            start_offset = self.state.get_mirror_offset(thread_id) if thread_id else 0
        if not thread_id or not to_user_id:
            return
        scan = self.runner.latest_mirror_since(
            thread_id=thread_id,
            start_offset=start_offset,
        )
        if scan is None:
            return
        with self._lock:
            self.state.set_mirror_offset(thread_id, scan.end_offset)
            self._save_state()
        if self._progress_updates_enabled():
            for progress in scan.progress_texts:
                if not progress:
                    continue
                with self._lock:
                    if progress == self.state.get_last_progress_summary(thread_id):
                        continue
                    self.state.set_last_progress_summary(thread_id, progress)
                    self._save_state()
                self._reply(
                    to_user_id,
                    bound_context_token,
                    progress,
                    use_context_token=False,
                    kind="progress",
                    origin="desktop-mirror",
                    thread_id=thread_id,
                )
                self._log_event(
                    "mirrored_progress",
                    {"thread": self._short_thread(thread_id), "to": to_user_id},
                )
        if not scan.final_text:
            return
        self._reply(
            to_user_id,
            bound_context_token,
            scan.final_text,
            use_context_token=False,
            kind="final",
            origin="desktop-mirror",
            thread_id=thread_id,
        )
        self._log_event(
            "mirrored_final",
            {"thread": self._short_thread(thread_id), "to": to_user_id},
        )

    def _current_mirror_thread_id(self) -> str | None:
        runtime = self.runner.current_runtime_status()
        if runtime.exists and runtime.thread_id:
            with self._lock:
                if self.state.active_session_id != runtime.thread_id:
                    self.state.active_session_id = runtime.thread_id
                    existing = self.state.sessions.get(runtime.thread_id)
                    self.state.touch_session(
                        runtime.thread_id,
                        label=existing.label if existing else "live-codex",
                        cwd=existing.cwd if existing else str(self.config.default_cwd),
                        source=existing.source if existing else "tmux-live",
                        tmux_session=runtime.tmux_session,
                    )
                    self._save_state()
            return runtime.thread_id
        with self._lock:
            return self.state.active_session_id

    def _progress_updates_enabled(self) -> bool:
        return bool(self.state.progress_updates_enabled)

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
        is_voice = False
        has_transcript = False
        for item in raw.get("item_list", []) or []:
            if item.get("type") == 1:
                body = str(item.get("text_item", {}).get("text", "")).strip()
                break
            if item.get("type") == 3:
                is_voice = True
                voice_text = item.get("voice_item", {}).get("text")
                if voice_text:
                    body = str(voice_text).strip()
                    has_transcript = True
                    break
        if not body and not is_voice:
            return None
        return IncomingMessage(
            from_user_id=str(raw.get("from_user_id", "")),
            context_token=raw.get("context_token"),
            body=body,
            message_id=str(raw.get("message_id", "")),
            is_voice=is_voice,
            has_transcript=has_transcript,
        )

    def _is_authorized_sender(self, from_user_id: str) -> bool:
        if not self.config.allowed_users:
            return True
        return from_user_id in self.config.allowed_users

    def _bind_peer(self, from_user_id: str, context_token: str | None) -> None:
        with self._lock:
            changed = (
                self.state.bound_user_id != from_user_id
                or self.state.bound_context_token != context_token
            )
            self.state.bound_user_id = from_user_id
            self.state.bound_context_token = context_token
            if changed and self.state.active_session_id:
                self._sync_mirror_cursor(self.state.active_session_id)
            self._save_state()
        self._flush_pending_outbox(from_user_id, context_token)

    def _flush_pending_outbox(self, to_user_id: str, context_token: str | None) -> None:
        with self._lock:
            pending = self.state.pop_pending_for(to_user_id)
            self._save_state()
        if not pending:
            return
        kept: list[dict[str, str]] = []
        for idx, item in enumerate(pending):
            text = item.get("text", "").strip()
            if not text:
                continue
            kind = str(item.get("kind", "message"))
            origin = str(item.get("origin", "bridge"))
            thread_id = str(item.get("thread_id", "")).strip() or None
            try:
                self.wechat.send_text(
                    to_user_id=to_user_id,
                    context_token=None,
                    text=text,
                )
                with self._lock:
                    self._log_event("outgoing", {"to": to_user_id, "text": text[:400]})
                    self._log_event(
                        "flushed_outgoing",
                        {"to": to_user_id, "text": text[:400]},
                    )
                    append_delivery(
                        state=self.state,
                        state_file=self.config.state_file,
                        ledger_file=self.config.delivery_ledger_file,
                        to_user_id=to_user_id,
                        text=text,
                        status="flushed",
                        kind=kind,
                        origin=origin,
                        thread_id=thread_id,
                    )
            except Exception as exc:  # noqa: BLE001
                kept.append(item)
                kept.extend(pending[idx + 1 :])
                with self._lock:
                    self._log_event(
                        "queued_outgoing",
                        {"to": to_user_id, "text": text[:400], "error": str(exc)},
                    )
                    append_delivery(
                        state=self.state,
                        state_file=self.config.state_file,
                        ledger_file=self.config.delivery_ledger_file,
                        to_user_id=to_user_id,
                        text=text,
                        status="queued",
                        kind=kind,
                        origin=origin,
                        thread_id=thread_id,
                        error=str(exc),
                    )
                break
        with self._lock:
            self.state.pending_outbox = kept + self.state.pending_outbox
            self._save_state()

    def _sync_mirror_cursor(self, thread_id: str) -> None:
        self.state.set_mirror_offset(thread_id, self.runner.rollout_size(thread_id))

    def _save_state(self) -> None:
        self.state.save(self.config.state_file)

    def _log_event(self, kind: str, payload: dict) -> None:
        with self._lock:
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

    def _short_thread(self, thread_id: str) -> str:
        return thread_id[:8]

    def _short_cwd(self, cwd: str) -> str:
        home = str(Path.home())
        if cwd.startswith(home):
            return cwd.replace(home, "~", 1)
        return cwd

    def _display_time(self, raw_ts: object) -> str:
        text = str(raw_ts or "").strip()
        if not text:
            return "--:--:--"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return text[11:19] if len(text) >= 19 else "--:--:--"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(DISPLAY_TZ).strftime("%H:%M:%S")
