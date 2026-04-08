from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .cli_backend import CliBackend
from .config import BridgeConfig
from .delivery_ledger import append_delivery, read_recent_for_user
from .incoming_media import (
    IncomingImageRef,
    SavedIncomingImage,
    download_incoming_image,
)
from .live_session import OPENCODE_SESSION_PREFIX, PLAN_MARKER, LiveCodexSessionManager
from .room_transcript import (
    append_room_message,
)
from .state import BridgeState, SessionRecord, now_iso
from .systemd_notify import notify as systemd_notify
from .wechat_api import DEFAULT_CDN_BASE_URL, WeChatClient

DISPLAY_TZ = ZoneInfo("Asia/Shanghai")
STALE_AUTO_FLUSH_SECONDS = 300.0
WAIT_FOR_BIND_TIMEOUT_SECONDS = 60.0
_SEND_DEDUP_WINDOW_SECONDS = 30.0
OWNER_VISIBLE_RECENT_CLUSTER_SECONDS = 1800.0
STALE_DESKTOP_MIRROR_DROP_SECONDS = 600.0
ROOM_ROUTE_RE = re.compile(r"^[＠@](?P<target>[A-Za-z0-9_.:-]+)\s*(?P<body>[\s\S]*)$")

# Digit words → ASCII digits for voice transcript normalization
_CN_DIGITS: dict[str, str] = {
    # Chinese
    "零": "0", "一": "1", "二": "2", "三": "3", "四": "4",
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
    "〇": "0",
    # English (voice may produce these)
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}


def _normalize_voice(text: str) -> str:
    """Normalize voice transcript for tmux session name matching.

    Strips spaces, lowercases, replaces Chinese digits with ASCII.
    'kimi 零' → 'kimi0', 'GPT' → 'gpt', 'claude' → 'claude'
    """
    out = text.lower()
    for cn, digit in _CN_DIGITS.items():
        out = out.replace(cn, digit)
    out = out.replace(" ", "")
    return out


# Voice transcription corrections: WeChat STT commonly garbles these.
# Maps misheard fragments → correct fragment (applied before normalization).
_VOICE_CORRECTIONS: dict[str, str] = {
    "eclaudee": "claude", "eclaude": "claude", "claudee": "claude",
    "克cloud": "claude", "cloud": "claude",
    "克劳德": "claude", "克洛德": "claude", "克劳": "claude",
    "claode": "claude", "claud": "claude",
    "killing": "kimi", "kimmy": "kimi", "keemy": "kimi",
    "奇米": "kimi", "可米": "kimi",
    "吉皮提": "gpt", "杰皮提": "gpt",
}


def _apply_voice_corrections(text: str) -> str:
    """Apply known voice transcription corrections before normalization."""
    out = text
    for wrong, right in sorted(_VOICE_CORRECTIONS.items(), key=lambda x: -len(x[0])):
        idx = out.lower().find(wrong.lower())
        if idx != -1:
            out = out[:idx] + right + out[idx + len(wrong):]
    return out


HELP_TEXT = """FT bridge 命令总览（支持 `/command` 和 `\\command`）

会话:
/status            当前 active session / tmux / cwd
/health            bridge / tmux / thread 健康检查
/sessions          当前可切换的 live tmux 列表
/members           当前 room 可见参与者
/switch <target>   切换到某个 session
/switch group      进入 room 模式（个人 switch 保留）
/attach-last       接最近一个 ft-cosmos session
/new [label]       绑定 canonical live runtime（不会自动新建 tmux）
/stop              清空当前 active session

通知:
/notify on         微信收 system + plan + progress + final
/notify off        微信收 system + plan + final
/notify status     查看当前通知模式

追溯:
/recent 10         看当前 active tmux 最近 10 条有效 delivery ledger
/recent after 128  从 seq=128 之后继续看当前 active tmux（高级调试）
/recent all 10     看所有 session 最近 10 条
/log 10            看当前 bridge 最近事件/错误日志

帮助:
/help              显示这页
/menu              同 /help

普通文本消息 = 直接发给当前 active live tmux session。
group 模式下可用 `@agent 消息` 定向发给某个参与者，所有桌面 final 会带说话人标签回到同一个聊天。
如果当前 active tmux 还没打开受支持的 live runtime，bridge 会明确提示你先启动/恢复。
/sessions 只显示当前 workspace 下、看起来像 live runtime 的 tmux。
个人模式下同一时刻只会有一个 active live session；group 模式是 additive，不替代个人 /switch。
bridge 会后台定期检查并冲洗 pending backlog，无需 /queue /catchup。
"""


@dataclass(frozen=True)
class IncomingMessage:
    from_user_id: str
    context_token: str | None
    body: str
    message_id: str
    is_voice: bool = False
    has_transcript: bool = False
    images: tuple[IncomingImageRef, ...] = ()


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
        self._last_outbox_watchdog_signature = ""
        self._last_external_state_mtime_ns = 0
        self._send_dedup_cache: dict[int, float] = {}  # hash(text) -> monotonic time
        self._room_final_dedup: dict[int, float] = {}  # hash((thread,text)) -> mono time
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
                if self._should_reset_poll_cursor(ret=ret, errcode=errcode):
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
            systemd_notify("STATUS=bridge polling")
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
                        tmux_session=self.state.active_tmux_session,
                    )
                    self._log_event("error", {"error": str(exc)})

    def _handle_incoming(self, incoming: IncomingMessage) -> None:
        self._bind_peer(incoming.from_user_id, incoming.context_token)
        body = incoming.body.strip()
        room_target, _ = self._extract_room_target(body)
        if incoming.is_voice and not incoming.has_transcript:
            self._reply(
                incoming.from_user_id,
                incoming.context_token,
                "收到语音，但无转写。",
                kind="progress",
                origin="wechat-voice",
                thread_id=self.state.active_session_id,
                tmux_session=self.state.active_tmux_session,
            )
            self._flush_bound_outbox_if_any()
            return
        if not body and not incoming.images:
            self._flush_bound_outbox_if_any()
            return
        if (body.startswith("/") or body.startswith("\\")) and not incoming.images:
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
                tmux_session=self.state.active_tmux_session,
            )
            self._flush_bound_outbox_if_any()
            return
        if self._room_mode_enabled() and room_target:
            if self._route_room_message(incoming, target=room_target):
                return
        if self._room_mode_enabled() and not room_target:
            # Images without @agent: accept silently (will be picked up by next @agent message)
            if incoming.images and not body:
                saved_images, _ = self._materialize_incoming_images(incoming)
                if saved_images:
                    self._reply(
                        incoming.from_user_id,
                        incoming.context_token,
                        f"收到 {len(saved_images)} 张图片。用 @agent 指定谁来看。",
                        kind="progress",
                        origin="wechat-room-target",
                        thread_id=None,
                        tmux_session=None,
                    )
                self._flush_bound_outbox_if_any()
                return
            # Try voice/text fuzzy match before rejecting
            voice_match, voice_body = self._voice_fuzzy_match_agent(body)
            if voice_match:
                rewritten = IncomingMessage(
                    from_user_id=incoming.from_user_id,
                    context_token=incoming.context_token,
                    body=voice_body,
                    message_id=incoming.message_id,
                    is_voice=incoming.is_voice,
                    has_transcript=incoming.has_transcript,
                    images=incoming.images,
                )
                if self._route_room_message(rewritten, target=voice_match):
                    return
            self._reply(
                incoming.from_user_id,
                incoming.context_token,
                "group 模式下请用 @agent 指定对象。\n例: @claude 你好",
                kind="progress",
                origin="wechat-prompt-error",
                thread_id=None,
                tmux_session=None,
            )
            self._flush_bound_outbox_if_any()
            return
        with self._lock:
            if not self.state.active_session_id and not self.state.active_tmux_session:
                hint = (
                    "没有 active session；请先用 /switch <tmux> 选择一个 live session。"
                )
                self._reply(
                    incoming.from_user_id,
                    incoming.context_token,
                    hint,
                    kind="progress",
                    origin="wechat-prompt-error",
                    thread_id=None,
                    tmux_session=None,
                )
                self._flush_bound_outbox_if_any()
                return
        saved_images, image_failures = self._materialize_incoming_images(incoming)
        if incoming.images and not saved_images:
            error_text = "收到图片，但当前无法取回可用本地文件。"
            if image_failures:
                error_text = f"{error_text}\n" + "\n".join(
                    f"- {reason}" for reason in image_failures
                )
            self._reply(
                incoming.from_user_id,
                incoming.context_token,
                error_text,
                kind="progress",
                origin="wechat-prompt-error",
                thread_id=self.state.active_session_id,
                tmux_session=self.state.active_tmux_session,
            )
            self._flush_bound_outbox_if_any()
            return
        with self._lock:
            active_record = self.runner.require_live_session(self.state)
            self.state.active_session_id = active_record.thread_id
            self.state.active_tmux_session = active_record.tmux_session
            self._save_state()
        self._sync_mirror_cursor_for_new_prompt(active_record.thread_id)
        prompt = self._compose_prompt(
            incoming=incoming,
            saved_images=saved_images,
            image_failures=image_failures,
        )
        refreshed = self.runner.submit_prompt(record=active_record, prompt=prompt)
        with self._lock:
            if (
                active_record.thread_id != refreshed.thread_id
                and active_record.tmux_session == refreshed.tmux_session
            ):
                self._promote_runtime_record(
                    old_thread_id=active_record.thread_id,
                    new_thread_id=refreshed.thread_id,
                    tmux_session=refreshed.tmux_session,
                    fallback_label=refreshed.label,
                    fallback_cwd=refreshed.cwd,
                    fallback_source=refreshed.source,
                )
            self.state.active_session_id = refreshed.thread_id
            self.state.active_tmux_session = refreshed.tmux_session
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
                "body": prompt[:400],
            },
        )
        ack_text = "已注入 terminal。"
        if saved_images:
            ack_text = f"已收到 {len(saved_images)} 张图片并注入 terminal。"
        self._reply(
            incoming.from_user_id,
            incoming.context_token,
            ack_text,
            kind="progress",
            origin="wechat-prompt-submitted",
            thread_id=thread_id,
            tmux_session=refreshed.tmux_session,
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
        if command == "/members":
            return self._members_text()
        if command == "/notify":
            return self._notify_text(arg)
        if command == "/recent":
            return self._recent_text(arg)
        if command == "/queue":
            return (
                "queue=retired\n"
                "hint=bridge 会后台自动冲洗 backlog；用 /recent 看最近有效消息，用 /log 看错误。"
            )
        if command == "/catchup":
            return (
                "catchup=retired\n"
                "hint=bridge 会后台自动冲洗 backlog；用 /recent 看最近有效消息，用 /log 看错误。"
            )
        if command == "/log":
            return self._log_text(arg)
        if command == "/sessions":
            live_records = self.runner.sync_live_sessions(self.state)
            self._save_state()
            return self._sessions_text(live_records)
        if command == "/stop":
            self.state.active_session_id = None
            self.state.active_tmux_session = None
            self.state.room_mode_enabled = False
            self._save_state()
            return "已清空 active session。"
        if command == "/attach-last":
            record = self.runner.ensure_attached_latest(self.state)
            if not record:
                return "没有找到最近的 ft-cosmos 本地 live runtime session。"
            self.state.active_session_id = record.thread_id
            self.state.active_tmux_session = record.tmux_session
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
            self.state.room_mode_enabled = False
            self.state.active_session_id = record.thread_id
            self.state.active_tmux_session = record.tmux_session
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
            if arg.strip().lower() == "group":
                self.state.room_mode_enabled = True
                self._save_state()
                active = self.state.active_tmux_session or "none"
                return f"已切换到 group 模式。\nactive_direct={active}\n{self._members_text()}"
            with self._lock:
                live_records = self.runner.sync_live_sessions(self.state)
                self._save_state()
                match = self._resolve_session(arg, live_records=live_records)
                if not match:
                    return f"没有找到 session: {arg}"
                record = self.state.sessions[match]
            refreshed = self.runner.ensure_resumed_session(
                thread_id=record.thread_id,
                state=self.state,
                label=record.label,
                source=record.source,
            )
            refreshed.updated_at = datetime.now(UTC).isoformat()
            with self._lock:
                self.state.room_mode_enabled = False
                self.state.active_session_id = refreshed.thread_id
                self.state.active_tmux_session = refreshed.tmux_session
                self._sync_mirror_cursor(refreshed.thread_id)
                self._save_state()
            lines = [
                "已切换到 session:",
                *self._session_identity_lines(refreshed.thread_id, key="session"),
                f"label={refreshed.label}",
                f"tmux={refreshed.tmux_session}",
                f"attach={self.runner.attach_hint(refreshed)}",
            ]
            return "\n".join(lines)
        return f"未知命令: {command}\n\n{HELP_TEXT}"

    def _notify_text(self, arg: str) -> str:
        normalized = arg.strip().lower()
        if not normalized or normalized == "status":
            return f"notify={self._notify_mode_text()}"
        if normalized in {"on", "progress", "enable"}:
            self.state.progress_updates_enabled = True
            self._save_state()
            return f"notify={self._notify_mode_text()}"
        if normalized in {"off", "final", "disable"}:
            self.state.progress_updates_enabled = False
            self._save_state()
            return f"notify={self._notify_mode_text()}"
        return "用法: /notify on|off|status"

    def _recent_text(self, arg: str) -> str:
        limit = 6
        after_seq: int | None = None
        scope_all = False
        normalized = arg.strip()
        tokens = normalized.split()
        if tokens and tokens[0].lower() == "all":
            scope_all = True
            normalized = " ".join(tokens[1:]).strip()
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
        items, scope_label, scope_tmux = self._read_effective_recent_items(
            to_user_id=target_user,
            limit=limit,
            after_seq=after_seq,
            scope_all=scope_all,
        )
        if not items:
            if scope_tmux:
                return (
                    "recent=empty\n"
                    f"scope={scope_tmux}\n"
                    "hint=当前 active tmux 还没有可补看的有效已发送消息；可用 /recent all 看全局"
                )
            return "recent=empty\nscope=all\nhint=当前会话还没有可补看的有效已发送消息"
        lines = self._render_recent_lines(items, scope_all=scope_all)
        last_seq = int(items[-1].get("seq", 0) or 0)
        next_cmd = (
            f"/recent all after {last_seq}"
            if scope_all
            else f"/recent after {last_seq}"
        )
        return (
            f"recent:\nscope={scope_label}\n"
            + "\n\n".join(lines)
            + f"\n\nnext={next_cmd}"
        )

    def _catchup_text(self, arg: str) -> str:
        keep_last = 5
        normalized = arg.strip()
        if normalized:
            if not normalized.isdigit():
                return (
                    "用法: /catchup [n]\n"
                    "说明: 先裁当前 active tmux 的旧 backlog，再补看最近/新增的有效消息"
                )
            keep_last = max(1, min(int(normalized), 20))
        target_user = self.state.bound_user_id
        if not target_user:
            return "catchup=blocked\nhint=先发 /status 绑定当前微信会话"
        active_tmux = self.state.active_tmux_session
        dropped, kept = self.state.trim_pending_for_scope(
            to_user_id=target_user,
            tmux_session=active_tmux,
            keep_last=keep_last,
        )
        scope_key = self._recent_cursor_scope_key(
            to_user_id=target_user,
            tmux_session=active_tmux,
        )
        cursor = self.state.get_recent_delivery_cursor(scope_key)
        latest_items, _, _ = self._read_effective_recent_items(
            to_user_id=target_user,
            limit=1,
            after_seq=None,
            scope_all=False,
        )
        latest_seq = int(latest_items[-1].get("seq", 0) or 0) if latest_items else 0
        if cursor is not None and latest_seq and cursor > latest_seq:
            self.state.clear_recent_delivery_cursor(scope_key)
            cursor = None
        items, scope_label, _ = self._read_effective_recent_items(
            to_user_id=target_user,
            limit=keep_last if cursor is None else 20,
            after_seq=cursor,
            scope_all=False,
        )
        if items:
            last_seq = int(items[-1].get("seq", 0) or 0)
            self.state.set_recent_delivery_cursor(scope_key, last_seq)
        self._save_state()
        if not items and dropped == 0 and kept == 0:
            if cursor is not None:
                return (
                    "catchup=up_to_date\n"
                    f"scope={scope_label}\n"
                    f"last_seq={cursor}\n"
                    "hint=当前 active tmux 没有新的有效聊天消息，也没有待裁 backlog"
                )
            return (
                "catchup=empty\n"
                f"scope={scope_label}\n"
                "hint=当前 active tmux 没有 backlog，也没有可补看的有效聊天消息"
            )
        lines = ["catchup=ok", f"scope={scope_label}"]
        if dropped or kept:
            lines.append(f"backlog_dropped={dropped}")
            lines.append(f"backlog_kept={kept}")
        if items:
            lines.append("recent:")
            lines.extend(self._render_recent_lines(items, scope_all=False))
            lines.append("next=/catchup")
        else:
            lines.append("recent=none")
        return "\n".join(lines)

    def _recent_cursor_scope_key(
        self, *, to_user_id: str, tmux_session: str | None
    ) -> str:
        scope = str(tmux_session or "").strip() or "all"
        return f"{to_user_id}|{scope}"

    def _read_effective_recent_items(
        self,
        *,
        to_user_id: str,
        limit: int,
        after_seq: int | None,
        scope_all: bool,
    ) -> tuple[list[dict], str, str | None]:
        path = self.config.delivery_ledger_file
        active_tmux = None if scope_all else self.state.active_tmux_session
        if not path.exists():
            return ([], active_tmux or "all", active_tmux)
        items = read_recent_for_user(
            ledger_file=path,
            to_user_id=to_user_id,
            limit=limit,
            after_seq=after_seq,
            tmux_session=active_tmux,
            effective_only=True,
            include_command_kinds=False,
            recent_cluster_seconds=(
                OWNER_VISIBLE_RECENT_CLUSTER_SECONDS if after_seq is None else None
            ),
        )
        fallback_to_all = False
        if not items and active_tmux:
            all_items = read_recent_for_user(
                ledger_file=path,
                to_user_id=to_user_id,
                limit=limit,
                after_seq=after_seq,
                tmux_session=None,
                effective_only=True,
                include_command_kinds=False,
                recent_cluster_seconds=(
                    OWNER_VISIBLE_RECENT_CLUSTER_SECONDS if after_seq is None else None
                ),
            )
            if all_items and all(
                not str(item.get("tmux_session", "")).strip() for item in all_items
            ):
                items = all_items
                active_tmux = None
                fallback_to_all = True
        scope_label = active_tmux or ("all-fallback" if fallback_to_all else "all")
        return (items, scope_label, active_tmux)

    def _render_recent_lines(self, items: list[dict], *, scope_all: bool) -> list[str]:
        lines: list[str] = []
        for item in items:
            ts = self._display_time(item.get("ts"))
            seq = int(item.get("seq", 0) or 0)
            status = str(item.get("status", "unknown"))
            kind = str(item.get("kind", "message"))
            text = str(item.get("text", "")).strip()
            item_tmux = str(item.get("tmux_session", "")).strip()
            scope_suffix = f"[{item_tmux or 'unknown'}]" if scope_all else ""
            lines.append(f"[{seq}][{status}][{kind}][{ts}]{scope_suffix} {text}")
        return lines

    def _log_text(self, arg: str) -> str:
        limit = 10
        errors_only = False
        scope_all = False
        normalized = arg.strip()
        if normalized:
            tokens = normalized.split()
            filtered_tokens: list[str] = []
            for token in tokens:
                lowered = token.lower()
                if lowered == "errors":
                    errors_only = True
                    continue
                if lowered == "all":
                    scope_all = True
                    continue
                filtered_tokens.append(token)
            if filtered_tokens:
                tail = filtered_tokens[-1]
                if tail.isdigit():
                    limit = max(1, min(int(tail), 20))
        path = self.config.event_log_file
        if not path.exists():
            return "log=empty\nhint=还没有 bridge 事件日志"
        active_thread = self._short_thread(self.state.active_session_id or "")
        target_user = self.state.bound_user_id
        events: list[dict] = []
        for raw in reversed(path.read_text(encoding="utf-8").splitlines()):
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = str(item.get("kind", "")).strip()
            payload = (
                item.get("payload", {})
                if isinstance(item.get("payload", {}), dict)
                else {}
            )
            if errors_only and "error" not in kind and not payload.get("error"):
                continue
            if not scope_all:
                payload_thread = str(payload.get("thread", "")).strip()
                payload_to = str(payload.get("to", "")).strip()
                if payload_thread and active_thread and payload_thread != active_thread:
                    continue
                if payload_to and target_user and payload_to != target_user:
                    continue
            events.append(item)
            if len(events) >= limit:
                break
        if not events:
            scope_label = (
                "all" if scope_all else (self.state.active_tmux_session or "current")
            )
            return f"log=empty\nscope={scope_label}\nhint=当前过滤条件下还没有匹配的 bridge 事件"
        events.reverse()
        scope_label = (
            "all" if scope_all else (self.state.active_tmux_session or "current")
        )
        lines = [
            "log:",
            f"scope={scope_label}",
            f"errors_only={str(errors_only).lower()}",
        ]
        for item in events:
            ts = self._display_time(item.get("ts"))
            kind = str(item.get("kind", "event")).strip()
            payload = (
                item.get("payload", {})
                if isinstance(item.get("payload", {}), dict)
                else {}
            )
            summary = self._summarize_log_payload(payload)
            lines.append(f"[{ts}][{kind}] {summary}")
        return "\n".join(lines)

    def _summarize_log_payload(self, payload: dict) -> str:
        parts: list[str] = []
        if payload.get("thread"):
            parts.append(f"thread={payload['thread']}")
        if payload.get("to"):
            parts.append(f"to={payload['to']}")
        if payload.get("from"):
            parts.append(f"from={payload['from']}")
        if payload.get("error"):
            parts.append(f"error={payload['error']}")
        text = str(payload.get("text", "")).strip()
        if text:
            parts.append(text.replace("\n", " ")[:120])
        if not parts:
            parts.append(json.dumps(payload, ensure_ascii=False)[:160])
        return " | ".join(parts)

    def _bootstrap_runtime(self) -> None:
        self.runner.sync_live_sessions(self.state)
        if not self.state.active_session_id and not self.state.active_tmux_session:
            return
        record = self.runner.try_live_session(self.state)
        if record:
            self.state.active_session_id = record.thread_id
            self.state.active_tmux_session = record.tmux_session
            self._save_state()

    def _is_active_record(self, record) -> bool:
        return self._is_active_thread(record.thread_id, record.tmux_session)

    def _is_active_thread(
        self, thread_id: str | None, tmux_session: str | None = None
    ) -> bool:
        if not tmux_session and thread_id:
            record = self.state.sessions.get(thread_id)
            tmux_session = record.tmux_session if record else None
        if self.state.active_tmux_session and tmux_session:
            return tmux_session == self.state.active_tmux_session
        return bool(thread_id and thread_id == self.state.active_session_id)

    def _promote_runtime_record(
        self,
        *,
        old_thread_id: str | None,
        new_thread_id: str | None,
        tmux_session: str | None,
        fallback_label: str,
        fallback_cwd: str,
        fallback_source: str,
    ) -> SessionRecord | None:
        old_id = str(old_thread_id or "").strip()
        new_id = str(new_thread_id or "").strip()
        tmux_name = str(tmux_session or "").strip() or None
        if not old_id or not new_id:
            return self.state.sessions.get(new_id) if new_id else None
        if old_id == new_id:
            record = self.state.sessions.get(new_id)
            label = record.label if record else fallback_label
            cwd = record.cwd if record else fallback_cwd
            source = record.source if record else fallback_source
            if tmux_name or not record:
                record = self.state.touch_session(
                    new_id,
                    label=label,
                    cwd=cwd,
                    source=source,
                    tmux_session=tmux_name,
                )
            if tmux_name:
                for item in self.state.pending_outbox:
                    if str(item.get("thread_id", "")).strip() != new_id:
                        continue
                    item["tmux_session"] = tmux_name
                if self.state.active_session_id == new_id:
                    self.state.active_tmux_session = tmux_name
            return record
        old_record = self.state.sessions.pop(old_id, None)
        new_record = self.state.sessions.get(new_id)
        label = (
            new_record.label
            if new_record
            else old_record.label
            if old_record
            else fallback_label
        )
        cwd = (
            new_record.cwd
            if new_record
            else old_record.cwd
            if old_record
            else fallback_cwd
        )
        source = (
            new_record.source
            if new_record
            else old_record.source
            if old_record
            else fallback_source
        )
        record = self.state.touch_session(
            new_id,
            label=label,
            cwd=cwd,
            source=source,
            tmux_session=tmux_name,
        )
        old_offset = self.state.mirror_offsets.pop(old_id, None)
        if old_offset is not None:
            self.state.set_mirror_offset(
                new_id,
                max(self.state.get_mirror_offset(new_id), int(old_offset)),
            )
        old_cursor = self.state.recent_delivery_cursors.pop(old_id, None)
        if old_cursor is not None and new_id not in self.state.recent_delivery_cursors:
            self.state.set_recent_delivery_cursor(new_id, int(old_cursor))
        old_summary = self.state.last_progress_summaries.pop(old_id, None)
        if old_summary and not self.state.get_last_progress_summary(new_id):
            self.state.set_last_progress_summary(new_id, old_summary)
        for item in self.state.pending_outbox:
            if str(item.get("thread_id", "")).strip() != old_id:
                continue
            item["thread_id"] = new_id
            if tmux_name:
                item["tmux_session"] = tmux_name
        if self.state.active_session_id == old_id:
            self.state.active_session_id = new_id
            if tmux_name:
                self.state.active_tmux_session = tmux_name
        return record

    def _resolve_session(
        self, query: str, live_records: list | None = None
    ) -> str | None:
        query = query.strip()
        listed = self._listed_sessions(live_records)
        live_exact_matches = [
            record.thread_id
            for record in listed
            if query == record.thread_id
            or query == record.label
            or query == (record.tmux_session or "")
        ]
        if len(live_exact_matches) == 1:
            return live_exact_matches[0]
        if query in self.state.sessions:
            return query
        if live_records is None:
            exact_candidates = [
                thread_id
                for thread_id, record in self.state.sessions.items()
                if record.label == query
                or (record.tmux_session and record.tmux_session == query)
            ]
            if len(exact_candidates) == 1:
                return exact_candidates[0]
        if query.isdigit():
            index = int(query)
            if 1 <= index <= len(listed):
                return listed[index - 1].thread_id
        candidates = [
            thread_id
            for thread_id, record in self.state.sessions.items()
            if thread_id.startswith(query)
            or (
                live_records is None
                and (
                    record.label == query
                    or (record.tmux_session and record.tmux_session == query)
                )
            )
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _ordered_sessions(self) -> list:
        return sorted(
            self.state.sessions.values(), key=lambda item: item.updated_at, reverse=True
        )

    def _listed_sessions(self, live_records: list | None = None) -> list:
        if live_records:
            return list(live_records)
        return self._ordered_sessions()

    def _status_text(self) -> str:
        self.runner.sync_live_sessions(self.state)
        if not self.state.active_session_id and not self.state.active_tmux_session:
            lines = ["status=no_active"]
            if self._room_mode_enabled():
                lines.append("mode=group")
                lines.append(
                    "hint=先用 @agent 定向消息，或 /switch <tmux> 选择默认 live session"
                )
            else:
                lines.append("hint=先用 /switch <tmux> 选择一个 live session")
            return "\n".join(lines)
        runtime = self.runner.current_runtime_status(
            active_session_id=self.state.active_session_id,
            active_tmux_session=self.state.active_tmux_session,
        )
        conflict_reason = None
        if hasattr(self.runner, "runtime_conflict_reason"):
            conflict_reason = self.runner.runtime_conflict_reason(runtime)
        if not runtime.exists:
            return (
                "status=missing_tmux\n"
                f"tmux={runtime.tmux_session}\n"
                "hint=先启动 canonical tmux"
            )
        if runtime.backend == "unknown":
            return (
                "status=tmux_no_cli\n"
                f"tmux={runtime.tmux_session}\n"
                f"pane={runtime.pane_command or 'unknown'}\n"
                "hint=attach 后启动 Codex、OpenCode 或 Claude"
            )
        if conflict_reason is not None:
            lines = [
                "status=runtime_conflict",
                f"tmux={runtime.tmux_session}",
                f"backend={runtime.backend}",
                f"conflict={conflict_reason}",
            ]
            lines.append("hint=先恢复 shell/runtime 隔离")
            return "\n".join(lines)
        if not runtime.thread_id:
            no_thread_hint = "hint=attach 后进入 live session"
            if runtime.backend == CliBackend.OPENCODE.value:
                no_thread_hint = "hint=attach 后进入 live session；OpenCode 首条 prompt 后会绑定 session"
            elif runtime.backend == CliBackend.CLAUDE.value:
                no_thread_hint = "hint=attach 后确认 Claude Code 已进入当前项目会话"
            return (
                "status=no_thread\n"
                f"tmux={runtime.tmux_session}\n"
                f"backend={runtime.backend}\n"
                f"{no_thread_hint}"
            )
        record = self.state.sessions.get(runtime.thread_id)
        if not record:
            return (
                "status=registry_missing\n"
                f"thread={self._short_thread(runtime.thread_id)}\n"
                f"tmux={runtime.tmux_session}"
            )
        lines = [
            "status=ok",
            *self._session_identity_lines(record.thread_id, key="thread"),
            f"label={record.label}",
            f"tmux={record.tmux_session}",
            f"backend={runtime.backend}",
            f"cwd={self._short_cwd(record.cwd)}",
            f"notify={self._notify_mode_text()}",
            f"attach={self.runner.attach_hint(record)}",
        ]
        if self._room_mode_enabled():
            lines.insert(1, "mode=group")
        return "\n".join(lines)

    def _sessions_text(self, live_records: list | None = None) -> str:
        runtime = self.runner.current_runtime_status(
            active_session_id=self.state.active_session_id,
            active_tmux_session=self.state.active_tmux_session,
        )
        listed = self._listed_sessions(live_records)
        inventory = []
        if hasattr(self.runner, "list_tmux_runtime_inventory"):
            inventory = list(self.runner.list_tmux_runtime_inventory())
        excluded = [item for item in inventory if not item.switchable]
        if not listed:
            if runtime.exists:
                lines = [
                    "sessions=0",
                    f"tmux={runtime.tmux_session}",
                    f"thread={self._short_thread(runtime.thread_id) if runtime.thread_id else 'none'}",
                ]
                if excluded:
                    lines.append(f"excluded={len(excluded)}")
                    for item in excluded[:5]:
                        lines.append(f"x {item.tmux_session} | {item.reason}")
                return "\n".join(lines)
            return "sessions=0"
        live_thread_ids = {record.thread_id for record in (live_records or [])}
        lines = [f"sessions={len(listed)}"]
        if self._room_mode_enabled():
            lines.append("mode=group")
        for idx, record in enumerate(listed[:20], start=1):
            marker = "*" if self._is_active_record(record) else " "
            live_marker = " live" if record.thread_id in live_thread_ids else ""
            lines.append(
                f"{marker}{idx} {record.label} | {self._short_thread(record.thread_id)} | {record.tmux_session or '-'}{live_marker}"
            )
        if excluded:
            lines.append(f"excluded={len(excluded)}")
            for item in excluded[:5]:
                lines.append(f"x {item.tmux_session} | {item.reason}")
        return "\n".join(lines) + "\nuse=/switch 1"

    def _health_text(self) -> str:
        self.runner.sync_live_sessions(self.state)
        runtime = self.runner.current_runtime_status(
            active_session_id=self.state.active_session_id,
            active_tmux_session=self.state.active_tmux_session,
        )
        conflict_reason = None
        if hasattr(self.runner, "runtime_conflict_reason"):
            conflict_reason = self.runner.runtime_conflict_reason(runtime)
        if not runtime.exists:
            status = "degraded"
        elif runtime.backend == "unknown":
            status = "degraded"
        elif conflict_reason is not None:
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
        wechat_account = getattr(
            getattr(self.wechat, "account", None), "account_id", "unknown"
        )
        lines = [
            f"health={status}",
            f"tmux={runtime.tmux_session}",
            f"pane={runtime.pane_command or 'none'}",
            f"backend={runtime.backend}",
            f"thread={self._short_thread(runtime.thread_id) if runtime.thread_id else 'none'}",
            f"wechat={wechat_account}",
            f"access={access}",
            f"notify={self._notify_mode_text()}",
        ]
        if self._room_mode_enabled():
            lines.append("mode=group")
        if conflict_reason is not None:
            lines.append(f"conflict={conflict_reason}")
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
        tmux_session: str | None = None,
    ) -> bool:
        effective_context = self._effective_send_context(
            context_token=context_token,
            use_context_token=use_context_token,
            origin=origin,
        )
        rendered = self._render_reply_text(text, kind=kind, origin=origin)
        if self._room_mode_enabled() and str(origin or "").strip() == "desktop-mirror":
            rendered = self._tag_room_text(
                rendered,
                thread_id=thread_id,
                tmux_session=tmux_session,
            )
        chunks = self._chunk_text(rendered)
        for idx, chunk in enumerate(chunks):
            # Dedup: suppress re-sending identical text within a short window.
            # WeChat iLink API can return ret=-2 even when the message was
            # actually delivered, causing the retry loop to re-send the same
            # content multiple times.
            chunk_hash = hash((to_user_id, chunk))
            now_mono = time.monotonic()
            with self._lock:
                last_sent_at = self._send_dedup_cache.get(chunk_hash)
                if last_sent_at is not None and (now_mono - last_sent_at) < _SEND_DEDUP_WINDOW_SECONDS:
                    self._log_event(
                        "send_dedup_suppressed",
                        {"to": to_user_id, "text": chunk[:200], "age_s": round(now_mono - last_sent_at, 1)},
                    )
                    continue
            try:
                self.wechat.send_text(
                    to_user_id=to_user_id,
                    context_token=effective_context,
                    text=chunk,
                )
                with self._lock:
                    self._send_dedup_cache[chunk_hash] = now_mono
                    # Prune old entries to prevent unbounded growth.
                    if len(self._send_dedup_cache) > 500:
                        cutoff = now_mono - _SEND_DEDUP_WINDOW_SECONDS * 2
                        self._send_dedup_cache = {
                            k: v for k, v in self._send_dedup_cache.items() if v > cutoff
                        }
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
                        tmux_session=tmux_session,
                    )
            except Exception as exc:  # noqa: BLE001
                remaining = chunks[idx:]
                is_mirror = str(origin or "").strip() in {
                    "desktop-mirror",
                    "desktop-direct",
                }
                with self._lock:
                    # Record in dedup cache even on failure — the API may have
                    # delivered despite returning an error (ret=-2).
                    self._send_dedup_cache[chunk_hash] = now_mono
                    if self._should_wait_for_bind(exc) and not is_mirror:
                        # Mirror messages never block on bind — they queue
                        # normally and retry without clogging the outbox.
                        self.state.outbox_waiting_for_bind = True
                        self.state.outbox_waiting_for_bind_since = now_iso()
                    for pending_chunk in remaining:
                        self.state.enqueue_pending_with_meta(
                            to_user_id=to_user_id,
                            text=pending_chunk,
                            kind=kind,
                            origin=origin,
                            thread_id=thread_id,
                            tmux_session=tmux_session,
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
                        tmux_session=tmux_session,
                        error=str(exc),
                    )
                return False
        return True

    def _render_reply_text(self, text: str, *, kind: str, origin: str) -> str:
        body = self._strip_known_tags(text.strip())
        body = self._normalize_markdown_for_wechat(body)
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
            "wechat-room-target",
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

    def _normalize_markdown_for_wechat(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return ""

        code_blocks: list[str] = []

        def stash_code_block(match: re.Match[str]) -> str:
            language = str(match.group(1) or "").strip()
            block = str(match.group(2) or "")
            token = f"\x00CODEBLOCK{len(code_blocks)}\x00"
            code_blocks.append(
                self._format_wechat_code_block(block=block, language=language)
            )
            return token

        normalized = re.sub(
            r"```([^\n`]*)\n(.*?)```",
            stash_code_block,
            normalized,
            flags=re.DOTALL,
        )
        normalized = re.sub(
            r"`([^`\n]+)`",
            lambda match: f"'{match.group(1)}'",
            normalized,
        )
        normalized = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", normalized)
        normalized = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", normalized)
        normalized = re.sub(r"__([^_\n]+)__", r"\1", normalized)
        normalized = re.sub(r"~~([^~\n]+)~~", r"\1", normalized)
        normalized = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", normalized)
        normalized = re.sub(r"[ \t]+\n", "\n", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()

        for index, code_block in enumerate(code_blocks):
            normalized = normalized.replace(
                f"\x00CODEBLOCK{index}\x00",
                code_block,
            )
        return normalized.strip()

    def _format_wechat_code_block(self, *, block: str, language: str) -> str:
        lines = [line.rstrip() for line in block.strip("\n").splitlines()]
        if not lines:
            return ""
        rendered: list[str] = []
        if language:
            rendered.append(f"{language}:")
        rendered.extend(">" if not line else f"> {line}" for line in lines)
        return "\n".join(rendered)

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
            time.sleep(0.2)
            try:
                if self._room_mode_enabled():
                    self._mirror_room_all_members()
                else:
                    self._mirror_desktop_final_if_any()
                    self._queue_inactive_desktop_finals_if_any()
            except Exception as exc:  # noqa: BLE001
                self._log_event("mirror_error", {"error": str(exc)})

    def _outbox_retry_loop(self) -> None:
        while True:
            time.sleep(self.config.outbox_retry_interval_seconds)
            try:
                self._merge_external_state()
                self._prune_stale_desktop_mirror_backlog()
                self._outbox_watchdog_tick()
                self._flush_bound_outbox_if_any()
            except Exception as exc:  # noqa: BLE001
                self._log_event("outbox_retry_error", {"error": str(exc)})

    def _mirror_desktop_final_if_any(self) -> None:
        thread_id = self._current_mirror_thread_id()
        with self._lock:
            to_user_id = self.state.bound_user_id
            bound_context_token = self.state.bound_context_token
            start_offset = self.state.get_mirror_offset(thread_id) if thread_id else 0
            selected_tmux_session = self.state.active_tmux_session
        if not thread_id or not to_user_id:
            return
        mirror_tmux_session = self._tmux_for_thread(thread_id) or selected_tmux_session
        scan = self.runner.latest_mirror_since(
            thread_id=thread_id,
            start_offset=start_offset,
        )
        if scan is None:
            return
        if not self._is_active_thread(thread_id, mirror_tmux_session):
            return
        if not scan.final_texts:
            with self._lock:
                if not self._is_active_thread(thread_id, mirror_tmux_session):
                    return
                self.state.set_mirror_offset(
                    thread_id,
                    self._next_mirror_offset_without_final(
                        thread_id=thread_id,
                        start_offset=start_offset,
                        scan_end_offset=scan.end_offset,
                    ),
                )
                self._save_state()
        for progress in scan.progress_texts:
            if not progress:
                continue
            if not self._is_active_thread(thread_id, mirror_tmux_session):
                return
            kind = self._classify_mirror_text_kind(progress)
            body = self._strip_plan_marker(progress)
            if kind == "progress":
                if not self._progress_updates_enabled():
                    continue
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
                tmux_session=mirror_tmux_session,
            )
            self._log_event(
                "mirrored_plan" if kind == "plan" else "mirrored_progress",
                {"thread": self._short_thread(thread_id), "to": to_user_id},
            )
        if not scan.final_texts:
            return
        if not self._is_active_thread(thread_id, mirror_tmux_session):
            return
        # Always advance offset first — never re-scan the same range
        with self._lock:
            if not self._is_active_thread(thread_id, mirror_tmux_session):
                return
            self.state.set_mirror_offset(thread_id, scan.end_offset)
            self._save_state()
        now = time.monotonic()
        for final_text in scan.final_texts:
            # Dedup: same final text within 10s window → skip
            final_key = hash(final_text)
            last = getattr(self, "_last_mirrored_final", None)
            if last and last[0] == final_key and (now - last[1]) < 10.0:
                continue
            self._last_mirrored_final = (final_key, now)
            self._reply(
                to_user_id,
                bound_context_token,
                final_text,
                kind="final",
                origin="desktop-mirror",
                thread_id=thread_id,
                tmux_session=mirror_tmux_session,
            )
            if self._room_mode_enabled():
                speaker = mirror_tmux_session or self._short_thread(thread_id)
                append_room_message(
                    transcript_file=self.config.room_transcript_file,
                    speaker=speaker,
                    direction="outbound",
                    body=final_text[:2000],
                )
            self._log_event(
                "mirrored_final",
                {"thread": self._short_thread(thread_id), "to": to_user_id},
            )

    def _mirror_room_all_members(self) -> None:
        """Group mode: mirror progress + plan + final for ALL live sessions."""
        with self._lock:
            to_user_id = self.state.bound_user_id
            bound_context_token = self.state.bound_context_token
        if not to_user_id:
            return
        for status in self.runner.list_live_runtime_statuses():
            thread_id = str(status.thread_id or "").strip()
            tmux_session = str(status.tmux_session or "").strip()
            if not thread_id or not tmux_session:
                continue
            with self._lock:
                start_offset = self.state.get_mirror_offset(thread_id)
            scan = self.runner.latest_mirror_since(
                thread_id=thread_id, start_offset=start_offset,
            )
            if scan is None or scan.end_offset == start_offset:
                continue
            # Progress / plan
            for progress in scan.progress_texts:
                if not progress:
                    continue
                kind = self._classify_mirror_text_kind(progress)
                body = self._strip_plan_marker(progress)
                if kind == "progress":
                    if not self._progress_updates_enabled():
                        continue
                    with self._lock:
                        if body == self.state.get_last_progress_summary(thread_id):
                            continue
                        self.state.set_last_progress_summary(thread_id, body)
                        self._save_state()
                self._reply(
                    to_user_id, bound_context_token, body,
                    kind=kind, origin="desktop-mirror",
                    thread_id=thread_id, tmux_session=tmux_session,
                )
            # Advance offset
            with self._lock:
                if scan.final_texts:
                    self.state.set_mirror_offset(thread_id, scan.end_offset)
                else:
                    self.state.set_mirror_offset(
                        thread_id,
                        self._next_mirror_offset_without_final(
                            thread_id=thread_id,
                            start_offset=start_offset,
                            scan_end_offset=scan.end_offset,
                        ),
                    )
                self._save_state()
            # Finals
            now = time.monotonic()
            for final_text in scan.final_texts:
                final_key = hash((thread_id, final_text))
                last = self._room_final_dedup.get(final_key)
                if last is not None and (now - last) < 10.0:
                    continue
                self._room_final_dedup[final_key] = now
                self._reply(
                    to_user_id, bound_context_token, final_text,
                    kind="final", origin="desktop-mirror",
                    thread_id=thread_id, tmux_session=tmux_session,
                )
                speaker = tmux_session or self._short_thread(thread_id)
                append_room_message(
                    transcript_file=self.config.room_transcript_file,
                    speaker=speaker, direction="outbound",
                    body=final_text[:2000],
                )
            # Prune old dedup entries
            if len(self._room_final_dedup) > 200:
                cutoff = now - 30.0
                self._room_final_dedup = {
                    k: v for k, v in self._room_final_dedup.items() if v > cutoff
                }

    def _queue_inactive_desktop_finals_if_any(self) -> None:
        with self._lock:
            to_user_id = self.state.bound_user_id
            active_thread_id = str(self.state.active_session_id or "").strip()
            active_tmux_session = str(self.state.active_tmux_session or "").strip()
            room_mode_enabled = self.state.room_mode_enabled
        if not to_user_id:
            return
        for status in self.runner.list_live_runtime_statuses():
            thread_id = str(status.thread_id or "").strip()
            tmux_session = str(status.tmux_session or "").strip()
            if not thread_id or not tmux_session:
                continue
            if thread_id == active_thread_id and tmux_session == active_tmux_session:
                continue
            with self._lock:
                start_offset = self.state.get_mirror_offset(thread_id)
            scan = self.runner.latest_mirror_since(
                thread_id=thread_id,
                start_offset=start_offset,
            )
            if scan is None or scan.end_offset == start_offset:
                continue
            with self._lock:
                if self._is_active_thread(thread_id, tmux_session):
                    continue
            # Advance offset before send — prevents retry storms on
            # ret=-2 failures.  For scans without finals, keep the tail
            # row hot so OpenCode in-place phase updates are re-scanned
            # (same logic as the active mirror path).
            with self._lock:
                if scan.final_texts:
                    next_offset = scan.end_offset
                else:
                    next_offset = self._next_mirror_offset_without_final(
                        thread_id=thread_id,
                        start_offset=start_offset,
                        scan_end_offset=scan.end_offset,
                    )
                self.state.set_mirror_offset(thread_id, next_offset)
                self._save_state()
            for final_text in scan.final_texts:
                if room_mode_enabled:
                    self._reply(
                        to_user_id,
                        self.state.bound_context_token,
                        final_text,
                        kind="final",
                        origin="desktop-mirror",
                        thread_id=thread_id,
                        tmux_session=tmux_session,
                    )
                else:
                    with self._lock:
                        self.state.enqueue_pending_with_meta(
                            to_user_id=to_user_id,
                            text=self._render_reply_text(
                                final_text,
                                kind="final",
                                origin="desktop-mirror",
                            ),
                            kind="final",
                            origin="desktop-mirror",
                            thread_id=thread_id,
                            tmux_session=tmux_session,
                        )
                if room_mode_enabled:
                    speaker = tmux_session or self._short_thread(thread_id)
                    append_room_message(
                        transcript_file=self.config.room_transcript_file,
                        speaker=speaker,
                        direction="outbound",
                        body=final_text[:2000],
                    )
                self._log_event(
                    "mirrored_final"
                    if room_mode_enabled
                    else "queued_inactive_mirrored_final",
                    {
                        "thread": self._short_thread(thread_id),
                        "to": to_user_id,
                        "tmux_session": tmux_session,
                    },
                )

    def _current_mirror_thread_id(self) -> str | None:
        with self._lock:
            active_session_id = self.state.active_session_id
            active_tmux_session = self.state.active_tmux_session
            snapshot_active_session_id = active_session_id
            snapshot_active_tmux_session = active_tmux_session
        if not active_session_id and not active_tmux_session:
            return None
        runtime = self.runner.current_runtime_status(
            active_session_id=active_session_id,
            active_tmux_session=active_tmux_session,
        )
        conflict_reason = None
        if hasattr(self.runner, "runtime_conflict_reason"):
            conflict_reason = self.runner.runtime_conflict_reason(runtime)
        if conflict_reason is not None:
            return None
        if runtime.exists and runtime.thread_id:
            with self._lock:
                if (
                    self.state.active_session_id != snapshot_active_session_id
                    or self.state.active_tmux_session != snapshot_active_tmux_session
                ):
                    return self.state.active_session_id
                if (
                    self.state.active_session_id != runtime.thread_id
                    or self.state.active_tmux_session != runtime.tmux_session
                ):
                    previous_thread_id = self.state.active_session_id
                    self.state.active_session_id = runtime.thread_id
                    self.state.active_tmux_session = runtime.tmux_session
                    existing = self.state.sessions.get(runtime.thread_id)
                    self._promote_runtime_record(
                        old_thread_id=previous_thread_id,
                        new_thread_id=runtime.thread_id,
                        tmux_session=runtime.tmux_session,
                        fallback_label=existing.label if existing else "live-codex",
                        fallback_cwd=existing.cwd
                        if existing
                        else str(self.config.default_cwd),
                        fallback_source=existing.source if existing else "tmux-live",
                    )
                    self._save_state()
            return runtime.thread_id
        if active_tmux_session and runtime.tmux_session == active_tmux_session:
            return None
        with self._lock:
            return self.state.active_session_id

    def _progress_updates_enabled(self) -> bool:
        return bool(self.state.progress_updates_enabled)

    def _notify_mode_text(self) -> str:
        if self._progress_updates_enabled():
            return "system+plan+progress+final"
        return "system+plan+final"

    def _classify_mirror_text_kind(self, text: str) -> str:
        if text.startswith(PLAN_MARKER):
            return "plan"
        # Heuristic: multi-line substantial text is a plan, not a status update.
        if text.count("\n") >= 3 and len(text) >= 120:
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

    def _materialize_incoming_images(
        self, incoming: IncomingMessage
    ) -> tuple[list[SavedIncomingImage], list[str]]:
        saved: list[SavedIncomingImage] = []
        failures: list[str] = []
        for image in incoming.images:
            try:
                saved_image = download_incoming_image(
                    image,
                    target_dir=self.config.incoming_media_dir,
                    message_id=incoming.message_id or "wechat-image",
                    cdn_base_url=str(
                        getattr(
                            getattr(self.wechat, "account", None),
                            "cdn_base_url",
                            DEFAULT_CDN_BASE_URL,
                        )
                        or DEFAULT_CDN_BASE_URL
                    ).strip(),
                )
            except Exception as exc:  # noqa: BLE001
                reason = str(exc)
                failures.append(f"image {image.index + 1}: {reason}")
                self._log_event(
                    "incoming_image_unavailable",
                    {
                        "message_id": incoming.message_id,
                        "index": image.index + 1,
                        "url": image.url[:400],
                        "reason": reason,
                        "has_media_info": image.has_media_info,
                        "media_source": image.media_source,
                        "has_encrypt_query": bool(image.media_encrypt_query_param),
                        "has_aes": bool(image.aes_key or image.media_aes_key),
                        "media_keys": list(image.media_keys),
                        "thumb_media_keys": list(image.thumb_media_keys),
                    },
                )
                continue
            saved.append(saved_image)
            self._log_event(
                "incoming_image_saved",
                {
                    "message_id": incoming.message_id,
                    "index": saved_image.index + 1,
                    "path": str(saved_image.path),
                    "bytes": saved_image.size_bytes,
                    "content_type": saved_image.content_type,
                },
            )
        return saved, failures

    def _compose_prompt(
        self,
        *,
        incoming: IncomingMessage,
        saved_images: list[SavedIncomingImage],
        image_failures: list[str],
    ) -> str:
        body = incoming.body.strip()
        if not saved_images and not image_failures:
            return body
        parts: list[str] = []
        if saved_images:
            lines = [
                "Owner 通过微信发送了图片。",
                "如果你的判断依赖图片，请先查看这些本地图片文件，再回答。",
            ]
            for image in saved_images:
                lines.append(f"- image {image.index + 1}: {image.path}")
            parts.append("\n".join(lines))
        if image_failures:
            parts.append(
                "图片 ingress 备注：\n"
                + "\n".join(f"- {reason}" for reason in image_failures)
            )
        if body:
            parts.append("Owner 消息：\n" + body)
        elif saved_images:
            parts.append("Owner 没有附加文字。请直接检查图片，并如实说明你看到的内容。")
        return "\n\n".join(part.strip() for part in parts if part.strip())

    def _parse_incoming(self, raw: dict) -> IncomingMessage | None:
        message_type = raw.get("message_type")
        if message_type == 2:
            return None
        body_parts: list[str] = []
        is_voice = False
        has_transcript = False
        images: list[IncomingImageRef] = []
        for item in raw.get("item_list", []) or []:
            if item.get("type") == 1:
                text = str(item.get("text_item", {}).get("text", "")).strip()
                if text:
                    body_parts.append(text)
                continue
            if item.get("type") == 2:
                image_item = item.get("image_item", {}) or {}
                media = image_item.get("media")
                thumb_media = image_item.get("thumb_media")
                media_dict = media if isinstance(media, dict) else {}
                thumb_media_dict = thumb_media if isinstance(thumb_media, dict) else {}
                chosen_media = media_dict
                chosen_source = "media"
                if not self._first_non_empty(
                    media_dict,
                    "encrypt_query_param",
                    "encrypted_query_param",
                    "encryptQueryParam",
                ) and self._first_non_empty(
                    thumb_media_dict,
                    "encrypt_query_param",
                    "encrypted_query_param",
                    "encryptQueryParam",
                ):
                    chosen_media = thumb_media_dict
                    chosen_source = "thumb_media"
                images.append(
                    IncomingImageRef(
                        index=len(images),
                        url=str(image_item.get("url", "")).strip(),
                        has_media_info=bool(media_dict or thumb_media_dict),
                        aes_key=self._first_non_empty(
                            image_item, "aeskey", "aes_key", "aesKey"
                        ),
                        media_encrypt_query_param=(
                            self._first_non_empty(
                                chosen_media,
                                "encrypt_query_param",
                                "encrypted_query_param",
                                "encryptQueryParam",
                            )
                        ),
                        media_aes_key=(
                            self._first_non_empty(
                                chosen_media,
                                "aes_key",
                                "aesKey",
                            )
                        ),
                        media_source=chosen_source if chosen_media else "",
                        media_keys=tuple(sorted(media_dict.keys())),
                        thumb_media_keys=tuple(sorted(thumb_media_dict.keys())),
                    )
                )
                continue
            if item.get("type") == 3:
                is_voice = True
                voice_text = item.get("voice_item", {}).get("text")
                if voice_text:
                    body_parts.append(str(voice_text).strip())
                    has_transcript = True
                continue
        body = "\n".join(part for part in body_parts if part).strip()
        if not body and not is_voice and not images:
            return None
        return IncomingMessage(
            from_user_id=str(raw.get("from_user_id", "")),
            context_token=raw.get("context_token"),
            body=body,
            message_id=str(raw.get("message_id", "")),
            is_voice=is_voice,
            has_transcript=has_transcript,
            images=tuple(images),
        )

    @staticmethod
    def _first_non_empty(mapping: dict, *keys: str) -> str:
        for key in keys:
            value = mapping.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    def _is_authorized_sender(self, from_user_id: str) -> bool:
        if not self.config.allowed_users:
            return False
        return from_user_id in self.config.allowed_users

    def _recent_incoming_images(self, *, limit: int = 5) -> list[SavedIncomingImage]:
        """Return the most recent incoming images by filename (timestamp-sorted)."""
        media_dir = self.config.incoming_media_dir
        if not media_dir.is_dir():
            return []
        image_files = sorted(
            (f for f in media_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}),
            key=lambda p: p.name,
            reverse=True,
        )
        return [
            SavedIncomingImage(
                index=i,
                path=f,
                source_url="",
                content_type="",
                size_bytes=f.stat().st_size,
            )
            for i, f in enumerate(image_files[:limit])
        ]

    def _bind_peer(self, from_user_id: str, context_token: str | None) -> None:
        with self._lock:
            previous_user_id = self.state.bound_user_id
            previous_context_token = self.state.bound_context_token
            had_binding = bool(previous_user_id or previous_context_token)
            self.state.bound_user_id = from_user_id
            self.state.bound_context_token = context_token
            self.state.outbox_waiting_for_bind = False
            self.state.outbox_waiting_for_bind_since = ""
            if self.state.active_session_id and (
                previous_user_id != from_user_id or not had_binding
            ):
                self._sync_mirror_cursor(self.state.active_session_id)
            self._save_state()

    def _room_mode_enabled(self) -> bool:
        return bool(self.state.room_mode_enabled)

    def _voice_fuzzy_match_agent(self, body: str) -> tuple[str | None, str]:
        """Try to match the beginning of a voice transcript to a live tmux session name.

        The user must say the actual session name (e.g. 'oc kimi zero', 'claude',
        'oc gpt'). Spaces and Chinese digits are normalized before matching.

        Returns (matched_tmux_session, remaining_body) or (None, body).
        """
        text = body.strip()
        if not text:
            return None, body

        # Apply voice transcription corrections first, then normalize
        corrected = _apply_voice_corrections(text)
        normalized = _normalize_voice(corrected)
        if not normalized:
            return None, body

        # Get current live session names
        live_records = self.runner.sync_live_sessions(self.state)
        self._save_state()
        live_names = [r.tmux_session for r in live_records if r.tmux_session]

        # Wide matching: owner always tries to say a session name first.
        # Dynamically check if a prefix of the normalized input is a
        # substring of any live session name. Fully dynamic, no hardcoded
        # prefix/suffix stripping.
        best_match: str | None = None
        best_len: int = 0
        min_match = 3  # minimum prefix length to avoid spurious matches
        # Try longest prefixes first
        for prefix_len in range(min(len(normalized), 20), min_match - 1, -1):
            prefix = normalized[:prefix_len]
            # Skip if prefix contains non-ASCII-alnum (likely message body)
            if not all(c.isascii() and c.isalnum() for c in prefix):
                continue
            matches = [n for n in live_names if prefix in n.lower()]
            if not matches:
                continue
            if len(matches) == 1:
                best_match = matches[0]
                best_len = prefix_len
                break
            # Multiple matches: if input has a digit right after the matched
            # prefix, use it to disambiguate (e.g. "kimi1" → prefer kimi1)
            rest = normalized[prefix_len:]
            if rest and rest[0].isdigit():
                digit = rest[0]
                digit_matches = [n for n in matches if n.lower().endswith(digit)]
                if len(digit_matches) == 1:
                    best_match = digit_matches[0]
                    best_len = prefix_len + 1  # consume the digit too
                    break
            # Fall back to longest session name among matches
            best_match = sorted(matches, key=len, reverse=True)[0]
            best_len = prefix_len
            break

        if best_match is None:
            return None, body

        # Find where the session name ends in the CORRECTED text
        # Walk corrected text consuming chars that contribute to the normalized match
        consumed = 0
        matched_norm = 0
        while consumed < len(corrected) and matched_norm < best_len:
            ch = corrected[consumed]
            # Check if this char is a Chinese digit
            if ch in _CN_DIGITS:
                matched_norm += 1
                consumed += 1
            elif ch == " ":
                consumed += 1  # skip space (normalized away)
            else:
                matched_norm += 1
                consumed += 1

        remainder = corrected[consumed:].lstrip(" ,，。:：、")
        return best_match, remainder

    def _extract_room_target(self, body: str) -> tuple[str | None, str]:
        match = ROOM_ROUTE_RE.match(str(body or "").strip())
        if not match:
            return None, str(body or "").strip()
        target = str(match.group("target") or "").strip()
        remainder = str(match.group("body") or "").strip()
        return (target or None), remainder

    def _room_speaker_label(
        self, *, thread_id: str | None, tmux_session: str | None
    ) -> str | None:
        speaker = str(tmux_session or "").strip()
        if speaker:
            return speaker
        normalized_thread = str(thread_id or "").strip()
        if not normalized_thread:
            return None
        record = self.state.sessions.get(normalized_thread)
        if record and record.label:
            return record.label
        return self._short_thread(normalized_thread)

    def _tag_room_text(
        self, text: str, *, thread_id: str | None, tmux_session: str | None
    ) -> str:
        speaker = self._room_speaker_label(
            thread_id=thread_id, tmux_session=tmux_session
        )
        if not speaker:
            return text
        return f"[{speaker}] {text}"

    def _members_text(self) -> str:
        live_records = self.runner.sync_live_sessions(self.state)
        self._save_state()
        lines = [
            f"mode={'group' if self._room_mode_enabled() else 'single'}",
            f"members={len(live_records)}",
        ]
        for idx, record in enumerate(live_records[:20], start=1):
            marker = "*" if self._is_active_record(record) else " "
            lines.append(
                f"{marker}{idx} {record.tmux_session or record.label} | {record.label} | {self._short_thread(record.thread_id)}"
            )
        lines.append("use=@agent 消息")
        return "\n".join(lines)

    def _route_room_message(self, incoming: IncomingMessage, *, target: str) -> bool:
        with self._lock:
            live_records = self.runner.sync_live_sessions(self.state)
            self._save_state()
            match = self._resolve_session(target, live_records=live_records)
            if not match:
                self._reply(
                    incoming.from_user_id,
                    incoming.context_token,
                    f"没有找到参与者: {target}",
                    kind="progress",
                    origin="wechat-prompt-error",
                    thread_id=self.state.active_session_id,
                    tmux_session=self.state.active_tmux_session,
                )
                self._flush_bound_outbox_if_any()
                return True
            record = self.state.sessions[match]
        refreshed = self.runner.ensure_resumed_session(
            thread_id=record.thread_id,
            state=self.state,
            label=record.label,
            source=record.source,
        )
        refreshed.updated_at = datetime.now(UTC).isoformat()
        with self._lock:
            self.state.touch_session(
                refreshed.thread_id,
                label=refreshed.label,
                cwd=refreshed.cwd,
                source=refreshed.source,
                tmux_session=refreshed.tmux_session,
            )
            self._save_state()
        saved_images, image_failures = self._materialize_incoming_images(incoming)
        if incoming.images and not saved_images:
            self._reply(
                incoming.from_user_id,
                incoming.context_token,
                "收到图片，但当前无法取回可用本地文件。",
                kind="progress",
                origin="wechat-prompt-error",
                thread_id=refreshed.thread_id,
                tmux_session=refreshed.tmux_session,
            )
            self._flush_bound_outbox_if_any()
            return True
        target_name, stripped_body = self._extract_room_target(incoming.body)
        effective_body = stripped_body if target_name else incoming.body
        # In room mode, if no images attached but message mentions images/photos,
        # auto-attach recent incoming images so agent can find them.
        if self._room_mode_enabled() and not saved_images:
            image_keywords = ("图", "照片", "photo", "image", "截图", "screenshot", "看图", "看一下图", "看看图")
            body_lower = (effective_body or "").lower()
            if any(kw in body_lower for kw in image_keywords):
                saved_images = self._recent_incoming_images(limit=5)
        prompt = self._compose_prompt(
            incoming=IncomingMessage(
                from_user_id=incoming.from_user_id,
                context_token=incoming.context_token,
                body=effective_body,
                message_id=incoming.message_id,
                is_voice=incoming.is_voice,
                has_transcript=incoming.has_transcript,
                images=incoming.images,
            ),
            saved_images=saved_images,
            image_failures=image_failures,
        )
        # Record owner message to room transcript (agents read it on demand)
        if self._room_mode_enabled():
            append_room_message(
                transcript_file=self.config.room_transcript_file,
                speaker="owner",
                direction="inbound",
                body=f"@{target} {effective_body}".strip(),
                images=[str(img.path) for img in saved_images] if saved_images else None,
            )
        self.runner.submit_prompt(record=refreshed, prompt=prompt)
        self._log_event(
            "prompt_submitted",
            {
                "thread": self._short_thread(refreshed.thread_id),
                "from": incoming.from_user_id,
                "body": prompt[:400],
                "room_target": target,
            },
        )
        self._reply(
            incoming.from_user_id,
            incoming.context_token,
            f"已注入 @{target} terminal。",
            kind="progress",
            origin="wechat-room-target",
            thread_id=refreshed.thread_id,
            tmux_session=refreshed.tmux_session,
        )
        self._flush_bound_outbox_if_any()
        return True

    def _flush_bound_outbox_if_any(self) -> None:
        with self._lock:
            to_user_id = self.state.bound_user_id
            context_token = self.state.bound_context_token
            active_tmux_session = self.state.active_tmux_session
            room_mode_enabled = self.state.room_mode_enabled
            # Auto-clear wait_for_bind after timeout so backlog doesn't
            # accumulate indefinitely waiting for an inbound message.
            if self.state.outbox_waiting_for_bind:
                wfb_set_at = str(
                    getattr(self.state, "outbox_waiting_for_bind_since", "") or ""
                ).strip()
                if wfb_set_at:
                    try:
                        dt = datetime.fromisoformat(wfb_set_at)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=UTC)
                        age = (datetime.now(UTC) - dt.astimezone(UTC)).total_seconds()
                        if age >= WAIT_FOR_BIND_TIMEOUT_SECONDS:
                            self.state.outbox_waiting_for_bind = False
                            self._log_event(
                                "wait_for_bind_auto_cleared",
                                {"age_seconds": round(age, 1)},
                            )
                    except ValueError:
                        pass
            delivery_stats = self._scope_pending_delivery_stats(
                to_user_id=to_user_id,
                tmux_session=active_tmux_session,
            )
        has_pending = (
            self.state.has_pending_for_user(to_user_id=to_user_id)
            if room_mode_enabled and to_user_id
            else delivery_stats["visible_count"] > 0
        )
        deliverable_now = (
            has_pending
            if room_mode_enabled
            else delivery_stats["deliverable_now_count"] > 0
        )
        if not to_user_id or not has_pending or not deliverable_now:
            return
        if room_mode_enabled:
            self._flush_pending_outbox_all(to_user_id, context_token)
        else:
            self._flush_pending_outbox(
                to_user_id,
                context_token,
                tmux_session=active_tmux_session,
            )

    def _prune_stale_desktop_mirror_backlog(self) -> None:
        with self._lock:
            if not self.state.pending_outbox:
                return
            active_thread_id = str(self.state.active_session_id or "").strip()
            kept: list[dict[str, str]] = []
            dropped: list[dict[str, str]] = []
            for item in self.state.pending_outbox:
                if self._should_drop_stale_desktop_mirror_item(
                    item,
                    active_thread_id=active_thread_id,
                ):
                    dropped.append(item)
                else:
                    kept.append(item)
            if not dropped:
                return
            self.state.pending_outbox = kept
            if not self.state.pending_outbox:
                self.state.outbox_waiting_for_bind = False
                self.state.outbox_waiting_for_bind_since = ""
            self._save_state()
            bound_user_id = self.state.bound_user_id
        for item in dropped:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            thread_id = str(item.get("thread_id", "")).strip() or None
            tmux_session = (
                self._tmux_for_thread(thread_id)
                or str(item.get("tmux_session", "")).strip()
                or None
            )
            reason = "stale_desktop_mirror_backlog"
            self._log_event(
                "suppressed_outgoing",
                {
                    "to": bound_user_id,
                    "text": text[:400],
                    "kind": str(item.get("kind", "message")),
                    "reason": reason,
                },
            )
            append_delivery(
                state=self.state,
                state_file=self.config.state_file,
                ledger_file=self.config.delivery_ledger_file,
                to_user_id=str(item.get("to", "") or bound_user_id or ""),
                text=text,
                status="suppressed",
                kind=str(item.get("kind", "message")),
                origin=str(item.get("origin", "bridge")),
                thread_id=thread_id,
                tmux_session=tmux_session,
                error=reason,
            )

    def _outbox_watchdog_tick(self) -> None:
        with self._lock:
            to_user_id = self.state.bound_user_id
            active_tmux_session = self.state.active_tmux_session
            stats = self._scope_pending_delivery_stats(
                to_user_id=to_user_id,
                tmux_session=active_tmux_session,
            )
            oldest_age_s = self._visible_pending_oldest_age_seconds(
                to_user_id=to_user_id,
                tmux_session=active_tmux_session,
            )
        if stats["visible_count"] <= 0:
            self._last_outbox_watchdog_signature = ""
            return
        if (
            stats["blocked_for_rebind_count"] > 0
            and stats["deliverable_now_count"] <= 0
        ):
            systemd_notify(
                f"STATUS=bridge backlog waiting-bind pending={stats['visible_count']}"
            )
        else:
            systemd_notify(
                "STATUS="
                f"bridge backlog pending={stats['visible_count']} "
                f"deliverable={stats['deliverable_now_count']}"
            )
        if oldest_age_s < STALE_AUTO_FLUSH_SECONDS:
            self._last_outbox_watchdog_signature = ""
            return
        signature = (
            f"{stats['visible_count']}|{stats['deliverable_now_count']}|"
            f"{stats['blocked_for_rebind_count']}|{int(oldest_age_s)}|"
            f"{active_tmux_session or ''}"
        )
        if signature == self._last_outbox_watchdog_signature:
            return
        self._last_outbox_watchdog_signature = signature
        self._log_event(
            "outbox_watchdog_pending",
            {
                "visible_count": stats["visible_count"],
                "deliverable_now_count": stats["deliverable_now_count"],
                "blocked_for_rebind_count": stats["blocked_for_rebind_count"],
                "oldest_age_s": int(oldest_age_s),
                "tmux_session": active_tmux_session or "",
            },
        )

    def _flush_pending_outbox(
        self,
        to_user_id: str,
        context_token: str | None,
        *,
        tmux_session: str | None,
    ) -> None:
        with self._lock:
            pending = self.state.pop_pending_for_scope(
                to_user_id=to_user_id,
                tmux_session=tmux_session,
            )
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
            if self._should_suppress_pending_item(kind=kind, origin=origin):
                with self._lock:
                    self._log_event(
                        "suppressed_outgoing",
                        {"to": to_user_id, "text": text[:400], "kind": kind},
                    )
                    append_delivery(
                        state=self.state,
                        state_file=self.config.state_file,
                        ledger_file=self.config.delivery_ledger_file,
                        to_user_id=to_user_id,
                        text=text,
                        status="suppressed",
                        kind=kind,
                        origin=origin,
                        thread_id=thread_id,
                        tmux_session=self._tmux_for_thread(thread_id) or tmux_session,
                    )
                continue
            # Stale items (old + retried) bypass wait_for_bind so they
            # don't accumulate forever. Fresh items still respect the bind.
            if (
                self.state.outbox_waiting_for_bind
                and self._pending_item_requires_rebind_pause(item, origin=origin)
                and not self._is_stale_pending_for_auto_flush(item)
            ):
                kept.append(item)
                continue
            # Dedup: if this exact text was already sent (or attempted)
            # within the dedup window, skip the send but keep in pending
            # so it doesn't vanish from state.
            flush_hash = hash((to_user_id, text))
            now_mono = time.monotonic()
            with self._lock:
                last_sent_at = self._send_dedup_cache.get(flush_hash)
            if last_sent_at is not None and (now_mono - last_sent_at) < _SEND_DEDUP_WINDOW_SECONDS:
                with self._lock:
                    self._log_event(
                        "flush_dedup_suppressed",
                        {"to": to_user_id, "text": text[:200], "age_s": round(now_mono - last_sent_at, 1)},
                    )
                kept.append(item)
                continue
            effective_context = self._effective_send_context(
                context_token=context_token,
                use_context_token=True,
                origin=origin,
            )
            try:
                self.wechat.send_text(
                    to_user_id=to_user_id,
                    context_token=effective_context,
                    text=text,
                )
                with self._lock:
                    self._send_dedup_cache[flush_hash] = now_mono
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
                        tmux_session=self._tmux_for_thread(thread_id) or tmux_session,
                    )
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._send_dedup_cache[flush_hash] = now_mono
                item["last_attempt_at"] = now_iso()
                item["attempt_count"] = int(item.get("attempt_count", 1) or 1) + 1
                item["last_error"] = str(exc)
                kept.append(item)
                kept.extend(pending[idx + 1 :])
                with self._lock:
                    if self._should_wait_for_bind(exc):
                        self.state.outbox_waiting_for_bind = True
                        self.state.outbox_waiting_for_bind_since = now_iso()
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
                        tmux_session=self._tmux_for_thread(thread_id) or tmux_session,
                        error=str(exc),
                    )
                break
        with self._lock:
            self.state.pending_outbox = kept + self.state.pending_outbox
            self._save_state()

    def _flush_pending_outbox_all(
        self,
        to_user_id: str,
        context_token: str | None,
    ) -> None:
        with self._lock:
            pending = self.state.pop_pending_for_user(to_user_id=to_user_id)
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
            resolved_tmux_session = (
                self._tmux_for_thread(thread_id)
                or str(item.get("tmux_session", "")).strip()
                or None
            )
            if self._should_suppress_pending_item(kind=kind, origin=origin):
                continue
            flush_hash = hash((to_user_id, text))
            now_mono = time.monotonic()
            with self._lock:
                last_sent_at = self._send_dedup_cache.get(flush_hash)
            if last_sent_at is not None and (now_mono - last_sent_at) < _SEND_DEDUP_WINDOW_SECONDS:
                with self._lock:
                    self._log_event(
                        "flush_all_dedup_suppressed",
                        {"to": to_user_id, "text": text[:200], "age_s": round(now_mono - last_sent_at, 1)},
                    )
                kept.append(item)
                continue
            effective_context = self._effective_send_context(
                context_token=context_token,
                use_context_token=True,
                origin=origin,
            )
            try:
                self.wechat.send_text(
                    to_user_id=to_user_id,
                    context_token=effective_context,
                    text=text,
                )
                with self._lock:
                    self._send_dedup_cache[flush_hash] = now_mono
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
                        tmux_session=resolved_tmux_session,
                    )
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._send_dedup_cache[flush_hash] = now_mono
                item["last_attempt_at"] = now_iso()
                item["attempt_count"] = int(item.get("attempt_count", 1) or 1) + 1
                item["last_error"] = str(exc)
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
                        tmux_session=resolved_tmux_session,
                        error=str(exc),
                    )
                break
        with self._lock:
            self.state.pending_outbox = kept + self.state.pending_outbox
            self._save_state()

    def _pending_item_age_seconds(self, item: dict[str, str]) -> float:
        created_at = str(item.get("created_at", "")).strip()
        if not created_at:
            return 0.0
        try:
            dt = datetime.fromisoformat(created_at)
        except ValueError:
            return 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - dt.astimezone(UTC)).total_seconds())

    def _visible_pending_oldest_age_seconds(
        self, *, to_user_id: str | None, tmux_session: str | None
    ) -> float:
        if not to_user_id:
            return 0.0
        active_scope = str(tmux_session or "").strip()
        oldest = 0.0
        for item in self.state.pending_outbox:
            if item.get("to") != to_user_id:
                continue
            item_scope = str(item.get("tmux_session", "")).strip()
            if item_scope and item_scope != active_scope:
                continue
            oldest = max(oldest, self._pending_item_age_seconds(item))
        return oldest

    def _is_stale_pending_for_auto_flush(self, item: dict[str, str]) -> bool:
        attempt_count = int(item.get("attempt_count", 1) or 1)
        last_error = str(item.get("last_error", "")).strip()
        if attempt_count <= 1 and not last_error:
            return False
        return self._pending_item_age_seconds(item) >= STALE_AUTO_FLUSH_SECONDS

    def _should_drop_stale_desktop_mirror_item(
        self,
        item: dict[str, str],
        *,
        active_thread_id: str,
    ) -> bool:
        if str(item.get("origin", "")).strip() != "desktop-mirror":
            return False
        if self._pending_item_age_seconds(item) < STALE_DESKTOP_MIRROR_DROP_SECONDS:
            return False
        thread_id = str(item.get("thread_id", "")).strip()
        kind = str(item.get("kind", "message")).strip()
        last_error = str(item.get("last_error", "")).strip()
        attempt_count = int(item.get("attempt_count", 1) or 1)
        if "ret=-2" in last_error and attempt_count >= 2:
            return True
        if thread_id and active_thread_id and thread_id != active_thread_id:
            if kind == "final":
                return False
            return True
        return False

    def _sync_mirror_cursor(self, thread_id: str) -> None:
        self.state.set_mirror_offset(thread_id, self.runner.rollout_size(thread_id))

    def _next_mirror_offset_without_final(
        self,
        *,
        thread_id: str | None,
        start_offset: int,
        scan_end_offset: int,
    ) -> int:
        end_offset = int(scan_end_offset)
        if str(thread_id or "").strip().startswith(OPENCODE_SESSION_PREFIX):
            # OpenCode can update the newest text part in place from commentary to
            # final_answer. Keep the tail row hot so the next scan can still catch it.
            return max(int(start_offset), end_offset - 1)
        return end_offset

    def _sync_mirror_cursor_for_new_prompt(self, thread_id: str) -> None:
        with self._lock:
            start_offset = self.state.get_mirror_offset(thread_id)
        scan = self.runner.latest_mirror_since(
            thread_id=thread_id,
            start_offset=start_offset,
        )
        if scan is None:
            return
        if scan.final_texts:
            return
        with self._lock:
            current_offset = self.state.get_mirror_offset(thread_id)
            if current_offset != start_offset:
                return
            self.state.set_mirror_offset(
                thread_id,
                self._next_mirror_offset_without_final(
                    thread_id=thread_id,
                    start_offset=start_offset,
                    scan_end_offset=scan.end_offset,
                ),
            )
            self._save_state()

    def _should_wait_for_bind(self, exc: Exception) -> bool:
        return "ret=-2" in str(exc)

    def _origin_uses_live_context(self, origin: str) -> bool:
        normalized = str(origin or "").strip()
        return normalized not in {"desktop-mirror", "desktop-direct"}

    def _pending_item_requires_rebind_pause(
        self,
        item: dict[str, str],
        *,
        origin: str,
    ) -> bool:
        if self._origin_uses_live_context(origin):
            return True
        if str(origin or "").strip() not in {"desktop-mirror", "desktop-direct"}:
            return False
        return "ret=-2" in str(item.get("last_error", "")).strip()

    def _should_suppress_pending_item(self, *, kind: str, origin: str) -> bool:
        return (
            kind == "progress"
            and origin == "desktop-mirror"
            and not self._progress_updates_enabled()
        )

    def _effective_send_context(
        self,
        *,
        context_token: str | None,
        use_context_token: bool,
        origin: str,
    ) -> str | None:
        if not use_context_token:
            return None
        # Desktop mirror traffic must stay context-free. Older bound contexts can
        # be accepted by the API while still failing to surface the delayed live
        # reply in the owner's visible chat lane.
        if str(origin or "").strip() == "desktop-mirror":
            return None
        # Other live/inbound-originated replies still prefer the latest bound
        # context and rely on the client-side ret=-2 fallback when needed.
        return context_token

    def _scope_pending_delivery_stats(
        self, *, to_user_id: str | None, tmux_session: str | None
    ) -> dict[str, int]:
        if not to_user_id:
            return {
                "visible_count": 0,
                "deliverable_now_count": 0,
                "blocked_for_rebind_count": 0,
                "stale_auto_flush_blocked_count": 0,
            }
        active_scope = str(tmux_session or "").strip()
        visible_items = [
            item
            for item in self.state.pending_outbox
            if item.get("to") == to_user_id
            and (
                not str(item.get("tmux_session", "")).strip()
                or str(item.get("tmux_session", "")).strip() == active_scope
            )
        ]
        blocked_for_rebind_count = 0
        if self.state.outbox_waiting_for_bind:
            blocked_for_rebind_count = sum(
                1
                for item in visible_items
                if self._pending_item_requires_rebind_pause(
                    item,
                    origin=str(item.get("origin", "bridge")),
                )
            )
        # Stale items bypass wait_for_bind, so they are deliverable even
        # when the bind flag is set.
        stale_bypass_count = sum(
            1
            for item in visible_items
            if self._is_stale_pending_for_auto_flush(item)
            and self._origin_uses_live_context(str(item.get("origin", "bridge")))
        )
        effective_blocked = max(blocked_for_rebind_count - stale_bypass_count, 0)
        return {
            "visible_count": len(visible_items),
            "deliverable_now_count": max(
                len(visible_items) - effective_blocked,
                0,
            ),
            "blocked_for_rebind_count": effective_blocked,
            "stale_bypass_count": stale_bypass_count,
        }

    def _should_reset_poll_cursor(self, *, ret: object, errcode: object) -> bool:
        # Invalid or stale poll cursors should be cleared so the bridge can
        # resume from the server's current stream instead of retrying forever.
        return ret in {-1, -14} or errcode in {-1, -14}

    def _pending_item_key(
        self, item: dict[str, str]
    ) -> tuple[str, str, str, str, str, str]:
        return (
            str(item.get("to", "")),
            str(item.get("text", "")).strip(),
            str(item.get("kind", "message")),
            str(item.get("origin", "bridge")),
            str(item.get("thread_id", "")),
            str(item.get("tmux_session", "")),
        )

    def _merge_external_state(self) -> None:
        state_file = self.config.state_file
        if not state_file.exists():
            return
        try:
            mtime_ns = state_file.stat().st_mtime_ns
        except OSError:
            return
        if mtime_ns <= self._last_external_state_mtime_ns:
            return
        try:
            external = BridgeState.load(state_file)
        except Exception:  # noqa: BLE001
            return
        with self._lock:
            if external.delivery_seq > self.state.delivery_seq:
                self.state.delivery_seq = external.delivery_seq
            if not self.state.bound_user_id and external.bound_user_id:
                self.state.bound_user_id = external.bound_user_id
            if not self.state.bound_context_token and external.bound_context_token:
                self.state.bound_context_token = external.bound_context_token
            if not self.state.active_session_id and external.active_session_id:
                self.state.active_session_id = external.active_session_id
            if not self.state.active_tmux_session and external.active_tmux_session:
                self.state.active_tmux_session = external.active_tmux_session
            if external.room_mode_enabled and not self.state.room_mode_enabled:
                self.state.room_mode_enabled = True
            if (
                external.outbox_waiting_for_bind
                and not self.state.outbox_waiting_for_bind
            ):
                self.state.outbox_waiting_for_bind = True
                self.state.outbox_waiting_for_bind_since = (
                    external.outbox_waiting_for_bind_since
                    or self.state.outbox_waiting_for_bind_since
                )
            if (
                external.pending_outbox_overflow_dropped
                > self.state.pending_outbox_overflow_dropped
            ):
                self.state.pending_outbox_overflow_dropped = (
                    external.pending_outbox_overflow_dropped
                )
            for thread_id, record in external.sessions.items():
                if thread_id not in self.state.sessions:
                    self.state.sessions[thread_id] = record

            existing = {
                self._pending_item_key(item): item for item in self.state.pending_outbox
            }
            for ext_item in external.pending_outbox:
                key = self._pending_item_key(ext_item)
                current = existing.get(key)
                if current is None:
                    cloned = dict(ext_item)
                    self.state.pending_outbox.append(cloned)
                    existing[key] = cloned
                    continue
                current["attempt_count"] = max(
                    int(current.get("attempt_count", 1) or 1),
                    int(ext_item.get("attempt_count", 1) or 1),
                )
                ext_last_attempt = str(ext_item.get("last_attempt_at", "")).strip()
                cur_last_attempt = str(current.get("last_attempt_at", "")).strip()
                if ext_last_attempt and ext_last_attempt > cur_last_attempt:
                    current["last_attempt_at"] = ext_last_attempt
                if ext_item.get("last_error") and not current.get("last_error"):
                    current["last_error"] = str(ext_item.get("last_error", ""))
                ext_created = str(ext_item.get("created_at", "")).strip()
                cur_created = str(current.get("created_at", "")).strip()
                if ext_created and (not cur_created or ext_created < cur_created):
                    current["created_at"] = ext_created
            self._last_external_state_mtime_ns = mtime_ns

    def _save_state(self) -> None:
        self.state.save(self.config.state_file)
        try:
            self._last_external_state_mtime_ns = (
                self.config.state_file.stat().st_mtime_ns
            )
        except OSError:
            pass

    def _queue_text(self) -> str:
        items = list(self.state.pending_outbox)
        active_tmux = str(self.state.active_tmux_session or "").strip()
        target_user = self.state.bound_user_id
        recent_items: list[dict] = []
        recent_scope = active_tmux or "all"
        if target_user:
            recent_items, recent_scope, _ = self._read_effective_recent_items(
                to_user_id=target_user,
                limit=1,
                after_seq=None,
                scope_all=False,
            )
        if not items:
            lines = ["queue=0", "status=empty"]
            if active_tmux:
                lines.append(f"active_tmux={active_tmux}")
            if recent_items:
                latest = recent_items[-1]
                lines.append(f"recent_scope={recent_scope}")
                lines.append(f"recent_effective_seq={int(latest.get('seq', 0) or 0)}")
                lines.append(
                    f"recent_effective_kind={str(latest.get('kind', 'message'))}"
                )
                lines.append(
                    f"recent_effective_time={self._display_time(latest.get('ts'))}"
                )
                lines.append(
                    "recent_effective="
                    + str(latest.get("text", "")).strip().replace("\n", " ")[:120]
                )
                lines.append(
                    "hint=/recent 看最近有效消息；bridge 会后台自动冲洗 backlog"
                )
            if self.state.pending_outbox_overflow_dropped:
                lines.append(
                    f"overflow_dropped={self.state.pending_outbox_overflow_dropped}"
                )
            return "\n".join(lines)
        now = datetime.now(UTC)
        oldest_seconds: float = 0.0
        stuck_count = 0
        kind_counts: dict[str, int] = {}
        tmux_counts: dict[str, int] = {}
        tmux_threads: dict[str, set[str]] = {}
        tmux_order: list[str] = []
        active_visible_count = 0
        waiting_count = 0
        blocked_for_rebind_count = 0
        stale_auto_flush_blocked_count = 0
        for item in items:
            kind = str(item.get("kind", "message"))
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            thread_id = str(item.get("thread_id", "")).strip() or "unscoped"
            item_tmux = (
                str(item.get("tmux_session", "")).strip()
                or self._tmux_for_thread(thread_id)
                or "unscoped"
            )
            if item_tmux not in tmux_counts:
                tmux_order.append(item_tmux)
            tmux_counts[item_tmux] = tmux_counts.get(item_tmux, 0) + 1
            tmux_threads.setdefault(item_tmux, set()).add(thread_id)
            if not item_tmux or item_tmux == "unscoped" or item_tmux == active_tmux:
                active_visible_count += 1
                if (
                    self.state.outbox_waiting_for_bind
                    and self._origin_uses_live_context(
                        str(item.get("origin", "bridge"))
                    )
                ):
                    blocked_for_rebind_count += 1
                if self._is_stale_pending_for_auto_flush(item):
                    stale_auto_flush_blocked_count += 1
            else:
                waiting_count += 1
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
        deliverable_now_count = active_visible_count - blocked_for_rebind_count
        lines.append(f"deliverable_now={max(deliverable_now_count, 0)}")
        if blocked_for_rebind_count:
            lines.append(f"blocked_for_rebind={blocked_for_rebind_count}")
        if stale_auto_flush_blocked_count:
            lines.append(f"stale_auto_flush_blocked={stale_auto_flush_blocked_count}")
        if self.state.active_tmux_session:
            lines.append(f"active_tmux={self.state.active_tmux_session}")
        lines.append(f"visible_now={active_visible_count}")
        lines.append(f"waiting_other_sessions={waiting_count}")
        for kind, count in sorted(kind_counts.items()):
            lines.append(f"{kind}={count}")
        lines.append(f"sessions={len(tmux_counts)}")
        for idx, item_tmux in enumerate(tmux_order[:5], start=1):
            marker = "*" if active_tmux and item_tmux == active_tmux else ""
            thread_count = len(
                {
                    thread
                    for thread in tmux_threads.get(item_tmux, set())
                    if thread and thread != "unscoped"
                }
            )
            lines.append(
                f"session[{idx}]={marker}{self._queue_tmux_display(item_tmux)}|count={tmux_counts[item_tmux]}|threads={thread_count}"
            )
        visible_items = [
            item
            for item in items
            if (
                (
                    str(item.get("tmux_session", "")).strip()
                    or self._tmux_for_thread(
                        str(item.get("thread_id", "")).strip() or None
                    )
                    or ""
                )
                in {"", active_tmux}
            )
        ]
        if visible_items:
            preview = visible_items[0]
            lines.append(
                "head=" + str(preview.get("text", "")).strip().replace("\n", " ")[:120]
            )
        elif items:
            waiting_preview = items[0]
            waiting_tmux = (
                str(waiting_preview.get("tmux_session", "")).strip()
                or self._tmux_for_thread(
                    str(waiting_preview.get("thread_id", "")).strip() or None
                )
                or "unscoped"
            )
            lines.append(
                f"head_waiting_session={self._queue_tmux_display(waiting_tmux)}"
            )
            lines.append(
                "head_waiting="
                + str(waiting_preview.get("text", "")).strip().replace("\n", " ")[:120]
            )
        if len(visible_items) > 1:
            tail = visible_items[-1]
            lines.append(
                "tail=" + str(tail.get("text", "")).strip().replace("\n", " ")[:120]
            )
        elif len(items) > 1:
            tail = items[-1]
            lines.append(
                "tail_any=" + str(tail.get("text", "")).strip().replace("\n", " ")[:120]
            )
        if recent_items:
            latest = recent_items[-1]
            lines.append(f"recent_effective_seq={int(latest.get('seq', 0) or 0)}")
            lines.append(
                f"recent_effective_time={self._display_time(latest.get('ts'))}"
            )
        return "\n".join(lines)

    def _queue_tmux_display(self, tmux_session: str) -> str:
        if not tmux_session or tmux_session == "unscoped":
            return "unscoped"
        return tmux_session

    def _tmux_for_thread(self, thread_id: str | None) -> str | None:
        normalized_thread = str(thread_id or "").strip()
        if not normalized_thread or normalized_thread == "unscoped":
            return None
        record = self.state.sessions.get(normalized_thread)
        if not record or not record.tmux_session:
            return None
        return record.tmux_session

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
        if thread_id.startswith("claude:"):
            return thread_id
        return thread_id[:8]

    def _is_pending_runtime_id(self, thread_id: str | None) -> bool:
        return bool(thread_id and thread_id.startswith("pending:"))

    def _session_identity_lines(self, thread_id: str, *, key: str) -> list[str]:
        if self._is_pending_runtime_id(thread_id):
            return [
                f"{key}=provisional",
                f"runtime_id={thread_id}",
                "note=waiting for first real runtime session id",
            ]
        return [
            f"{key}={self._short_thread(thread_id) if key == 'thread' else thread_id}"
        ]

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
