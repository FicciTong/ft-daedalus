from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

from .config import BridgeConfig
from .delivery_ledger import append_delivery, read_recent_for_user
from .live_session import LiveCodexSessionManager, PLAN_MARKER
from .state import BridgeState, now_iso
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
/queue             看当前待发送队列概况

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
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        if self.state.progress_updates_enabled is None:
            self.state.progress_updates_enabled = self.config.progress_updates_default
        self._bootstrap_runtime()
        self._start_mirror_thread()
        self._start_outbox_thread()
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
                    item_types = [
                        item.get("type")
                        for item in (raw.get("item_list", []) or [])
                        if isinstance(item, dict)
                    ]
                    if item_types:
                        self._log_event(
                            "ignored_incoming",
                            {
                                "message_type": raw.get("message_type"),
                                "item_types": item_types,
                                "from": raw.get("from_user_id"),
                                "message_id": raw.get("message_id"),
                            },
                        )
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
                "收到语音，但无转写。",
                kind="progress",
                origin="wechat-voice",
                thread_id=self.state.active_session_id,
            )
            self._flush_bound_outbox_if_any()
            return
        if not body:
            self._flush_bound_outbox_if_any()
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
            self._flush_bound_outbox_if_any()
            return
        with self._lock:
            active_record = self.runner.require_live_session(self.state)
            self.state.active_session_id = active_record.thread_id
            self._sync_mirror_cursor(active_record.thread_id)
            self._save_state()
        refreshed = self.runner.submit_prompt(record=active_record, prompt=incoming.body)
        with self._lock:
            self.state.active_session_id = refreshed.thread_id
            self.state.touch_session(
                refreshed.thread_id,
                label=refreshed.label,
                cwd=refreshed.cwd,
                source=refreshed.source,
                tmux_session=refreshed.tmux_session,
            )
            self._save_state()
            thread_id = refreshed.thread_id
        self._log_event(
            "prompt_submitted",
            {
                "thread": self._short_thread(thread_id),
                "from": incoming.from_user_id,
                "body": incoming.body[:400],
            },
        )
        self._reply(
            incoming.from_user_id,
            incoming.context_token,
            "已注入 terminal。",
            kind="progress",
            origin="wechat-prompt-submitted",
            thread_id=thread_id,
        )
        self._flush_bound_outbox_if_any()

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
        if command == "/queue":
            return self._queue_text()
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
        rendered = self._render_reply_text(text, kind=kind, origin=origin)
        chunks = self._chunk_text(rendered)
        for idx, chunk in enumerate(chunks):
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
                remaining = chunks[idx:]
                with self._lock:
                    if self._should_wait_for_bind(exc):
                        self.state.outbox_waiting_for_bind = True
                    for pending_chunk in remaining:
                        self.state.enqueue_pending_with_meta(
                            to_user_id=to_user_id,
                            text=pending_chunk,
                            kind=kind,
                            origin=origin,
                            thread_id=thread_id,
                            error=str(exc),
                        )
                    self._save_state()
                    self._log_event(
                        "queued_outgoing",
                        {
                            "to": to_user_id,
                            "text": chunk[:400],
                            "queued_chunks": len(remaining),
                            "error": str(exc),
                        },
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

    def _render_reply_text(self, text: str, *, kind: str, origin: str) -> str:
        body = self._strip_known_tags(text.strip())
        if not body:
            body = "(空回复)"
        if kind == "final":
            return self._prepend_icon(body, "✅")
        if kind == "plan":
            return self._prepend_icon(body, "📋")
        if self._is_system_reply(kind=kind, origin=origin):
            return self._prepend_icon(body, "⚙️")
        if kind == "progress":
            return self._prepend_icon(body, "⏳")
        return body

    def _is_system_reply(self, *, kind: str, origin: str) -> bool:
        if kind == "command":
            return True
        return origin in {
            "bridge",
            "wechat-command",
            "wechat-voice",
            "wechat-prompt-submitted",
            "wechat-prompt-error",
        }

    def _prepend_icon(self, text: str, icon: str) -> str:
        normalized = text.rstrip()
        if normalized.startswith(f"{icon} ") or normalized == icon:
            return normalized
        return f"{icon} {normalized}"

    def _strip_known_tags(self, text: str) -> str:
        normalized = text.rstrip()
        for icon in ("⚙️", "⏳", "✅", "📋"):
            if normalized.startswith(f"{icon} "):
                normalized = normalized[len(icon) + 1 :].lstrip()
        for known in ("SYSTEM", "FINAL"):
            for suffix in (f"\n\n{known}", f" {known}"):
                if normalized.endswith(suffix):
                    normalized = normalized[: -len(suffix)].rstrip()
        return normalized

    def _start_mirror_thread(self) -> None:
        thread = threading.Thread(
            target=self._mirror_loop,
            name="codex-wechat-final-mirror",
            daemon=True,
        )
        thread.start()

    def _start_outbox_thread(self) -> None:
        thread = threading.Thread(
            target=self._outbox_retry_loop,
            name="codex-wechat-outbox-retry",
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

    def _outbox_retry_loop(self) -> None:
        while True:
            time.sleep(self.config.outbox_retry_interval_seconds)
            try:
                self._flush_bound_outbox_if_any()
            except Exception as exc:  # noqa: BLE001
                self._log_event("outbox_retry_error", {"error": str(exc)})

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
                kind = self._classify_mirror_text_kind(progress)
                body = self._strip_plan_marker(progress)
                if kind == "progress":
                    with self._lock:
                        if body == self.state.get_last_progress_summary(thread_id):
                            continue
                        self.state.set_last_progress_summary(thread_id, body)
                        self._save_state()
                self._reply(
                    to_user_id,
                    bound_context_token,
                    body,
                    kind=kind,
                    origin="desktop-mirror",
                    thread_id=thread_id,
                )
                self._log_event(
                    "mirrored_plan" if kind == "plan" else "mirrored_progress",
                    {"thread": self._short_thread(thread_id), "to": to_user_id},
                )
        if not scan.final_text:
            return
        self._reply(
            to_user_id,
            bound_context_token,
            scan.final_text,
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

    def _classify_mirror_text_kind(self, text: str) -> str:
        if text.startswith(PLAN_MARKER):
            return "plan"
        return "progress"

    def _strip_plan_marker(self, text: str) -> str:
        if text.startswith(PLAN_MARKER):
            return text[len(PLAN_MARKER) :].lstrip()
        return text

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
        message_type = raw.get("message_type")
        if message_type == 2:
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
            self.state.outbox_waiting_for_bind = False
            if changed and self.state.active_session_id:
                self._sync_mirror_cursor(self.state.active_session_id)
            self._save_state()

    def _flush_bound_outbox_if_any(self) -> None:
        with self._lock:
            to_user_id = self.state.bound_user_id
            context_token = self.state.bound_context_token
            has_pending = bool(self.state.pending_outbox)
            waiting_for_bind = self.state.outbox_waiting_for_bind
        if not to_user_id or not has_pending or waiting_for_bind:
            return
        self._flush_pending_outbox(to_user_id, context_token)

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
                    context_token=context_token,
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
                item["last_attempt_at"] = now_iso()
                item["attempt_count"] = int(item.get("attempt_count", 1) or 1) + 1
                item["last_error"] = str(exc)
                kept.append(item)
                kept.extend(pending[idx + 1 :])
                with self._lock:
                    if self._should_wait_for_bind(exc):
                        self.state.outbox_waiting_for_bind = True
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

    def _should_wait_for_bind(self, exc: Exception) -> bool:
        return "ret=-2" in str(exc)

    def _save_state(self) -> None:
        self.state.save(self.config.state_file)

    def _queue_text(self) -> str:
        items = list(self.state.pending_outbox)
        if not items:
            lines = ["queue=0", "status=empty"]
            if self.state.pending_outbox_overflow_dropped:
                lines.append(
                    f"overflow_dropped={self.state.pending_outbox_overflow_dropped}"
                )
            return "\n".join(lines)
        now = datetime.now(UTC)
        oldest_seconds: float = 0.0
        stuck_count = 0
        kind_counts: dict[str, int] = {}
        for item in items:
            kind = str(item.get("kind", "message"))
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            created_at = str(item.get("created_at", "")).strip()
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    age = max(0.0, (now - dt.astimezone(UTC)).total_seconds())
                    oldest_seconds = max(oldest_seconds, age)
                    if age >= 120:
                        stuck_count += 1
                except ValueError:
                    pass
        lines = [
            f"queue={len(items)}",
            f"oldest_age_s={int(oldest_seconds)}",
            f"stuck_ge_120s={stuck_count}",
        ]
        if self.state.pending_outbox_overflow_dropped:
            lines.append(
                f"overflow_dropped={self.state.pending_outbox_overflow_dropped}"
            )
        if self.state.outbox_waiting_for_bind:
            lines.append("wait=next-wechat-message")
        for kind, count in sorted(kind_counts.items()):
            lines.append(f"{kind}={count}")
        preview = items[0]
        lines.append(
            "head="
            + str(preview.get("text", "")).strip().replace("\n", " ")[:120]
        )
        if len(items) > 1:
            tail = items[-1]
            lines.append(
                "tail="
                + str(tail.get("text", "")).strip().replace("\n", " ")[:120]
            )
        return "\n".join(lines)

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
