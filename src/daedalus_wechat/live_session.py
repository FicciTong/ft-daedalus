from __future__ import annotations

import json
import re
import shlex
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .cli_backend import detect_backend
from .config import default_codex_state_db
from .state import BridgeState, SessionRecord

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
THREAD_ID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
STATUS_LINE_RE = re.compile(r"\bgpt-[^\n]*·[^\n]*\b[0-9a-f]{8}-[0-9a-f-]{28}\b")
CLAUDE_STATUS_LINE_RE = re.compile(
    r"(?:\u256d\u2500|Claude Code|\u25b8\u25b8|claude-opus|claude-sonnet|claude-haiku)"
)
EPHEMERAL_LINE_RE = re.compile(
    r"^[•✻◦]\s+(Working|Baked|Thinking|Waiting|Context compacted|Updated Plan)\b"
)
PLAN_MARKER = "__DAEDALUS_PLAN__\n"


@dataclass(frozen=True)
class LiveReply:
    thread_id: str
    response_text: str


@dataclass(frozen=True)
class FinalScan:
    final_text: str
    end_offset: int


@dataclass(frozen=True)
class MirrorScan:
    progress_texts: list[str]
    final_text: str
    end_offset: int


@dataclass(frozen=True)
class LiveRuntimeStatus:
    tmux_session: str
    exists: bool
    pane_command: str | None
    thread_id: str | None
    pane_cwd: str | None = None
    backend: str = "codex"  # codex | claude | unknown


@dataclass(frozen=True)
class TmuxRuntimeInventoryItem:
    tmux_session: str
    pane_command: str | None
    thread_id: str | None
    pane_cwd: str | None
    switchable: bool
    reason: str
    backend: str = "codex"  # codex | claude | unknown


class LiveCodexSessionManager:
    def __init__(
        self,
        *,
        codex_bin: str,
        default_cwd: Path,
        canonical_tmux_session: str,
        codex_state_db: Path | None = None,
    ) -> None:
        self.codex_bin = codex_bin
        self.default_cwd = default_cwd
        self.canonical_tmux_session = canonical_tmux_session
        self.codex_state_db = codex_state_db or default_codex_state_db()
        self.session_root = Path.home() / ".codex" / "sessions"

    def find_latest_thread(self) -> str | None:
        state_db = self.codex_state_db
        if not state_db.exists():
            return None
        conn = sqlite3.connect(state_db)
        try:
            row = conn.execute(
                """
                select id
                from threads
                where cwd = ?
                order by updated_at desc
                limit 1
                """,
                (str(self.default_cwd),),
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            conn.close()

    def ensure_attached_latest(self, state: BridgeState) -> SessionRecord | None:
        live = self.try_live_session(state)
        if live:
            return live
        thread_id = self.find_latest_thread()
        if not thread_id:
            return None
        record = state.sessions.get(thread_id)
        label = record.label if record else "attached-last"
        source = record.source if record else "auto-attach-latest"
        return self.ensure_resumed_session(
            thread_id=thread_id,
            state=state,
            label=label,
            source=source,
        )

    def ensure_resumed_session(
        self,
        *,
        thread_id: str,
        state: BridgeState,
        label: str,
        source: str,
    ) -> SessionRecord:
        existing = state.sessions.get(thread_id)
        live_status = self._find_live_runtime_status(
            thread_id=thread_id,
            tmux_session=existing.tmux_session if existing else None,
        )
        tmux_session = (
            live_status.tmux_session
            if live_status
            else existing.tmux_session if existing and existing.tmux_session
            else self._tmux_name_for(thread_id)
        )
        if self._tmux_exists(tmux_session):
            current_thread_id = self._extract_thread_id(
                self._capture_clean_text(tmux_session)
            )
            effective_thread_id = current_thread_id or thread_id
        else:
            self._start_tmux_session(
                tmux_session,
                [
                    self.codex_bin,
                    "resume",
                    thread_id,
                    "-C",
                    str(self.default_cwd),
                    "--no-alt-screen",
                ],
            )
            time.sleep(2.0)
            effective_thread_id = (
                self._extract_thread_id(self._capture_clean_text(tmux_session))
                or thread_id
            )
        return state.touch_session(
            effective_thread_id,
            label=label,
            cwd=str(self.default_cwd),
            source=source,
            tmux_session=tmux_session,
        )

    def current_runtime_status(
        self,
        *,
        active_session_id: str | None = None,
        active_tmux_session: str | None = None,
    ) -> LiveRuntimeStatus:
        if active_tmux_session:
            return self._runtime_status_for_tmux(active_tmux_session)
        live_statuses = self.list_live_runtime_statuses()
        if active_session_id:
            for status in live_statuses:
                if status.thread_id == active_session_id:
                    return status
        for status in live_statuses:
            if status.tmux_session == self.canonical_tmux_session:
                return status
        if live_statuses:
            return live_statuses[0]
        return self._runtime_status_for_tmux(self.canonical_tmux_session)

    def list_tmux_runtime_inventory(self) -> list[TmuxRuntimeInventoryItem]:
        items: list[TmuxRuntimeInventoryItem] = []
        for tmux_session in self._list_tmux_sessions():
            status = self._runtime_status_for_tmux(tmux_session)
            if not status.exists:
                items.append(
                    TmuxRuntimeInventoryItem(
                        tmux_session=tmux_session,
                        pane_command=None,
                        thread_id=None,
                        pane_cwd=None,
                        switchable=False,
                        reason="missing",
                    )
                )
                continue
            if status.backend == "unknown":
                reason = "unrecognized-cli"
                switchable = False
            elif status.backend == "claude":
                # Claude Code sessions don't require a Codex-style thread ID
                if not self._is_workspace_tmux(status.pane_cwd):
                    reason = "outside-workspace"
                    switchable = False
                else:
                    reason = "live"
                    switchable = True
            elif not status.thread_id:
                reason = "no-thread"
                switchable = False
            elif not self._is_workspace_tmux(status.pane_cwd):
                reason = "outside-workspace"
                switchable = False
            else:
                reason = "live"
                switchable = True
            items.append(
                TmuxRuntimeInventoryItem(
                    tmux_session=status.tmux_session,
                    pane_command=status.pane_command,
                    thread_id=status.thread_id,
                    pane_cwd=status.pane_cwd,
                    switchable=switchable,
                    reason=reason,
                    backend=status.backend,
                )
            )
        return sorted(
            items,
            key=lambda item: (
                0 if item.tmux_session == self.canonical_tmux_session else 1,
                item.tmux_session,
            ),
        )

    def list_live_runtime_statuses(self) -> list[LiveRuntimeStatus]:
        return [
            LiveRuntimeStatus(
                tmux_session=item.tmux_session,
                exists=True,
                pane_command=item.pane_command,
                thread_id=item.thread_id,
                pane_cwd=item.pane_cwd,
                backend=item.backend,
            )
            for item in self.list_tmux_runtime_inventory()
            if item.switchable
        ]

    def sync_live_sessions(self, state: BridgeState) -> list[SessionRecord]:
        records: list[SessionRecord] = []
        for status in self.list_live_runtime_statuses():
            existing = state.sessions.get(status.thread_id)
            records.append(
                state.touch_session(
                    status.thread_id,
                    label=existing.label if existing else status.tmux_session,
                    cwd=existing.cwd if existing else status.pane_cwd or str(self.default_cwd),
                    source=existing.source if existing else "tmux-live",
                    tmux_session=status.tmux_session,
                )
            )
        return records

    def try_live_session(self, state: BridgeState) -> SessionRecord | None:
        self.sync_live_sessions(state)
        status = self.current_runtime_status(
            active_session_id=state.active_session_id,
            active_tmux_session=state.active_tmux_session,
        )
        if not status.exists or not status.thread_id:
            return None
        existing = state.sessions.get(status.thread_id)
        label = existing.label if existing else status.tmux_session
        source = existing.source if existing else "tmux-live"
        return state.touch_session(
            status.thread_id,
            label=label,
            cwd=existing.cwd if existing else status.pane_cwd or str(self.default_cwd),
            source=source,
            tmux_session=status.tmux_session,
        )

    def require_live_session(self, state: BridgeState) -> SessionRecord:
        self.sync_live_sessions(state)
        status = self.current_runtime_status(
            active_session_id=state.active_session_id,
            active_tmux_session=state.active_tmux_session,
        )
        if not status.exists:
            raise RuntimeError(
                "当前没有 `tmux codex`。请先启动一个固定窗口，例如：\n"
                f"tmux new -s {self.canonical_tmux_session} "
                f"'{self.codex_bin} resume --last -C {self.default_cwd} --no-alt-screen'"
            )
        if status.backend == "unknown":
            raise RuntimeError(
                f"`tmux {status.tmux_session}` 已存在，但里面当前不是 Codex 或 Claude Code "
                f"(pane_current_command={status.pane_command or 'unknown'})。"
                "\n请先 attach 进去并启动 Codex 或 Claude Code session。"
            )
        if status.backend == "claude":
            # Claude Code doesn't require a thread ID to function
            return state.touch_session(
                status.tmux_session,  # use tmux session name as session key
                label=f"claude@{status.tmux_session}",
                cwd=status.pane_cwd or str(self.default_cwd),
                source="tmux-live-claude",
                tmux_session=status.tmux_session,
            )
        if not status.thread_id:
            raise RuntimeError(
                f"`tmux {status.tmux_session}` 已打开，但还没有进入任何 Codex thread。"
                "\n请先 attach 进去执行：\n"
                f"codex resume --last -C {self.default_cwd} --no-alt-screen"
            )
        existing = state.sessions.get(status.thread_id)
        label = existing.label if existing else status.tmux_session
        source = existing.source if existing else "tmux-live"
        return state.touch_session(
            status.thread_id,
            label=label,
            cwd=existing.cwd if existing else status.pane_cwd or str(self.default_cwd),
            source=source,
            tmux_session=status.tmux_session,
        )

    def create_new_session(self, *, state: BridgeState, label: str) -> SessionRecord:
        tmux_session = self.canonical_tmux_session
        if self._tmux_exists(tmux_session):
            current_thread_id = self._extract_thread_id(
                self._capture_clean_text(tmux_session)
            )
            if current_thread_id:
                return state.touch_session(
                    current_thread_id,
                    label=label,
                    cwd=str(self.default_cwd),
                    source="bridge-canonical-existing",
                    tmux_session=tmux_session,
                )
        self._start_tmux_session(
            tmux_session,
            [
                self.codex_bin,
                "-C",
                str(self.default_cwd),
                "--no-alt-screen",
            ],
        )
        thread_id = self._wait_for_thread_id(tmux_session)
        return state.touch_session(
            thread_id,
            label=label,
            cwd=str(self.default_cwd),
            source="bridge-new",
            tmux_session=tmux_session,
        )

    def submit_prompt(self, *, record: SessionRecord, prompt: str) -> SessionRecord:
        tmux_session = self._ensure_running_tmux(record)
        self._inject_prompt(tmux_session, prompt)
        thread_id = (
            self._extract_thread_id(self._capture_clean_text(tmux_session))
            or record.thread_id
        )
        return SessionRecord(
            thread_id=thread_id,
            label=record.label,
            cwd=record.cwd,
            source=record.source,
            created_at=record.created_at,
            updated_at=record.updated_at,
            tmux_session=record.tmux_session,
        )

    def send_prompt(self, *, record: SessionRecord, prompt: str) -> LiveReply:
        tmux_session = self._ensure_running_tmux(record)
        baseline_text = self._capture_clean_text(tmux_session)
        rollout_file = self._resolve_rollout_file(record.thread_id)
        rollout_offset = (
            rollout_file.stat().st_size
            if rollout_file and rollout_file.exists()
            else 0
        )
        self._inject_prompt(tmux_session, prompt)
        response_text = self._wait_for_final_reply(
            rollout_file=rollout_file,
            start_offset=rollout_offset,
        )
        if not response_text:
            response_text = self._collect_response(
                tmux_session=tmux_session,
                baseline_text=baseline_text,
                submitted_prompt=prompt,
            )
        if not response_text:
            response_text = (
                "未捕获到 final reply。"
                "桌面 `tmux codex` 仍然保留完整 live 输出；"
                "如果这次回答还在继续生成，请回到电脑侧查看。"
            )
        thread_id = self._extract_thread_id(self._capture_clean_text(tmux_session)) or record.thread_id
        return LiveReply(thread_id=thread_id, response_text=response_text or "(无文本回复)")

    def attach_hint(self, record: SessionRecord) -> str:
        tmux_session = record.tmux_session or self._tmux_name_for(record.thread_id)
        return f"tmux attach -t {tmux_session}"

    def rollout_size(self, thread_id: str) -> int:
        rollout_file = self._resolve_rollout_file(thread_id)
        if rollout_file is None or not rollout_file.exists():
            return 0
        return int(rollout_file.stat().st_size)

    def latest_mirror_since(self, *, thread_id: str, start_offset: int) -> MirrorScan | None:
        rollout_file = self._resolve_rollout_file(thread_id)
        if rollout_file is None or not rollout_file.exists():
            return None
        offset = int(start_offset)
        size = rollout_file.stat().st_size
        if size < offset:
            offset = 0
        if size == offset:
            return MirrorScan(progress_texts=[], final_text="", end_offset=offset)
        carry = ""
        final_text = ""
        progress_texts: list[str] = []
        with rollout_file.open("r", encoding="utf-8") as fh:
            fh.seek(offset)
            chunk = fh.read()
            end_offset = fh.tell()
        data = carry + chunk
        lines = data.splitlines()
        if data and not data.endswith("\n"):
            carry = lines.pop() if lines else data
        for raw in lines:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            progress = self._extract_progress_text(event)
            if progress:
                progress_texts.append(progress)
            extracted = self._extract_final_text(event)
            if extracted:
                final_text = extracted
        if carry:
            try:
                event = json.loads(carry)
            except json.JSONDecodeError:
                event = None
            if event:
                progress = self._extract_progress_text(event)
                if progress:
                    progress_texts.append(progress)
                extracted = self._extract_final_text(event)
                if extracted:
                    final_text = extracted
        return MirrorScan(progress_texts=progress_texts, final_text=final_text, end_offset=end_offset)

    def latest_final_since(self, *, thread_id: str, start_offset: int) -> FinalScan | None:
        scan = self.latest_mirror_since(thread_id=thread_id, start_offset=start_offset)
        if scan is None:
            return None
        return FinalScan(final_text=scan.final_text, end_offset=scan.end_offset)

    def _ensure_running_tmux(self, record: SessionRecord) -> str:
        tmux_session = record.tmux_session or self._tmux_name_for(record.thread_id)
        if not self._tmux_exists(tmux_session):
            raise RuntimeError(
                f"当前 `tmux {tmux_session}` 不存在。请先启动并在里面打开 Codex。"
            )
        return tmux_session

    def _start_tmux_session(self, tmux_session: str, cmd: list[str]) -> None:
        if self._tmux_exists(tmux_session):
            return
        shell_cmd = shlex.join(cmd)
        subprocess.run(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                tmux_session,
                "-c",
                str(self.default_cwd),
                shell_cmd,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if not self._tmux_exists(tmux_session):
            raise RuntimeError(f"tmux session did not stay alive: {tmux_session}")

    def _inject_prompt(self, tmux_session: str, prompt: str) -> None:
        normalized = prompt.replace("\r\n", "\n").replace("\r", "\n")
        subprocess.run(
            ["tmux", "load-buffer", "-"],
            input=normalized.encode(),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["tmux", "paste-buffer", "-d", "-t", f"{tmux_session}:0.0"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.2)
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{tmux_session}:0.0", "C-m"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _collect_response(
        self,
        *,
        tmux_session: str,
        baseline_text: str,
        submitted_prompt: str,
    ) -> str:
        seen = baseline_text
        visible_seen = ""
        first_visible_deadline = time.monotonic() + 180.0
        hard_deadline = time.monotonic() + 900.0
        last_visible_change_at: float | None = None
        while time.monotonic() < hard_deadline:
            time.sleep(1.0)
            current = self._capture_clean_text(tmux_session)
            if current != seen:
                visible_now = self._extract_visible_after_prompt(current, submitted_prompt)
                visible = self._delta_text(visible_seen, visible_now)
                if visible:
                    visible_seen = visible_now
                    last_visible_change_at = time.monotonic()
                seen = current
                continue
            if last_visible_change_at is None:
                if time.monotonic() >= first_visible_deadline:
                    break
            elif time.monotonic() - last_visible_change_at >= 6.0:
                break
        return self._collapse_text(visible_seen)

    def _wait_for_final_reply(
        self,
        *,
        rollout_file: Path | None,
        start_offset: int,
    ) -> str:
        if rollout_file is None:
            return ""
        deadline = time.monotonic() + 300.0
        offset = start_offset
        carry = ""
        final_text = ""
        saw_task_complete = False
        last_growth_at: float | None = None
        while time.monotonic() < deadline:
            time.sleep(0.5)
            if not rollout_file.exists():
                continue
            size = rollout_file.stat().st_size
            if size < offset:
                offset = 0
            if size == offset:
                if final_text and saw_task_complete:
                    return final_text
                if (
                    final_text
                    and last_growth_at is not None
                    and time.monotonic() - last_growth_at >= 2.0
                ):
                    return final_text
                continue
            with rollout_file.open("r", encoding="utf-8") as fh:
                fh.seek(offset)
                chunk = fh.read()
                offset = fh.tell()
            last_growth_at = time.monotonic()
            data = carry + chunk
            lines = data.splitlines()
            if data and not data.endswith("\n"):
                carry = lines.pop() if lines else data
            else:
                carry = ""
            for raw in lines:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                extracted = self._extract_final_text(event)
                if extracted:
                    final_text = extracted
                if event.get("type") == "event_msg":
                    payload = event.get("payload") or {}
                    if payload.get("type") == "task_complete":
                        saw_task_complete = True
            if final_text and saw_task_complete:
                return final_text
        return final_text

    def _capture_clean_text(self, tmux_session: str) -> str:
        proc = subprocess.run(
            ["tmux", "capture-pane", "-p", "-J", "-t", f"{tmux_session}:0.0", "-S", "-2000"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        raw = proc.stdout.decode(errors="replace")
        text = ANSI_RE.sub("", raw).replace("\r", "")
        lines = [line.rstrip() for line in text.splitlines()]
        filtered: list[str] = []
        for line in lines:
            if STATUS_LINE_RE.match(line):
                continue
            if CLAUDE_STATUS_LINE_RE.match(line):
                continue
            filtered.append(line)
        return "\n".join(filtered).strip("\n")

    def _extract_visible_after_prompt(self, full_text: str, submitted_prompt: str) -> str:
        if not full_text.strip():
            return ""
        first_line = submitted_prompt.splitlines()[0].strip()
        prompt_anchor = f"› {first_line}".strip()
        idx = full_text.rfind(prompt_anchor)
        if idx == -1:
            return ""
        cleaned = full_text[idx + len(prompt_anchor) :].lstrip("\n")
        if cleaned.startswith(submitted_prompt):
            cleaned = cleaned[len(submitted_prompt) :].lstrip("\n")
        lines = [line.rstrip() for line in cleaned.splitlines()]
        filtered: list[str] = []
        for line in lines:
            if not line.strip() and not filtered:
                continue
            if line.lstrip().startswith("› "):
                break
            if STATUS_LINE_RE.search(line):
                continue
            if EPHEMERAL_LINE_RE.search(line):
                continue
            filtered.append(line)
        return "\n".join(filtered).strip("\n")

    def _delta_text(self, old: str, new: str) -> str:
        max_prefix = min(len(old), len(new))
        idx = 0
        while idx < max_prefix and old[idx] == new[idx]:
            idx += 1
        return new[idx:]

    def _collapse_text(self, text: str) -> str:
        lines = [line.rstrip() for line in text.splitlines()]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        collapsed: list[str] = []
        previous_blank = False
        for line in lines:
            is_blank = not line.strip()
            if is_blank and previous_blank:
                continue
            collapsed.append(line)
            previous_blank = is_blank
        return "\n".join(collapsed).strip()

    def _extract_final_text(self, event: dict) -> str:
        event_type = event.get("type")
        payload = event.get("payload") or {}
        if event_type == "event_msg":
            if (
                payload.get("type") == "agent_message"
                and payload.get("phase") == "final_answer"
            ):
                return str(payload.get("message", "")).strip()
            return ""
        if event_type == "response_item":
            if payload.get("type") != "message":
                return ""
            if payload.get("role") != "assistant":
                return ""
            if payload.get("phase") != "final_answer":
                return ""
            content = payload.get("content") or []
            parts: list[str] = []
            for item in content:
                if item.get("type") == "output_text":
                    text = str(item.get("text", "")).strip()
                    if text:
                        parts.append(text)
            return "\n\n".join(parts).strip()
        return ""

    def _extract_progress_text(self, event: dict) -> str:
        event_type = event.get("type")
        payload = event.get("payload") or {}
        if event_type == "event_msg":
            if payload.get("type") != "agent_message":
                return ""
            if payload.get("phase") != "commentary":
                return ""
            message = str(payload.get("message", "")).strip()
            return self._normalize_progress_text(message)
        if event_type == "response_item":
            if payload.get("type") != "function_call":
                return ""
            if payload.get("name") != "update_plan":
                return ""
            plan_text = self._extract_plan_text(payload.get("arguments"))
            if not plan_text:
                return ""
            return f"{PLAN_MARKER}{plan_text}"
        return ""

    def _normalize_progress_text(self, text: str) -> str:
        lines = [line.rstrip() for line in text.splitlines()]
        normalized: list[str] = []
        blank_pending = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if normalized:
                    blank_pending = True
                continue
            if blank_pending:
                normalized.append("")
                blank_pending = False
            normalized.append(stripped)
        return "\n".join(normalized).strip()

    def _extract_plan_text(self, arguments: object) -> str:
        if isinstance(arguments, str):
            raw = arguments.strip()
            if not raw:
                return ""
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return ""
        elif isinstance(arguments, dict):
            payload = arguments
        else:
            return ""
        explanation = str(payload.get("explanation", "")).strip()
        plan = payload.get("plan") or []
        if not explanation and not plan:
            return ""
        lines = ["Plan"]
        if explanation:
            lines.append(explanation)
        status_labels = {
            "in_progress": "进行中",
            "pending": "待办",
            "completed": "完成",
        }
        for index, item in enumerate(plan, start=1):
            if not isinstance(item, dict):
                continue
            step = str(item.get("step", "")).strip()
            if not step:
                continue
            status = status_labels.get(str(item.get("status", "")).strip(), "状态未知")
            lines.append(f"{index}. {status}: {step}")
        return "\n".join(lines).strip()

    def _wait_for_thread_id(self, tmux_session: str) -> str:
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            text = self._capture_clean_text(tmux_session)
            thread_id = self._extract_thread_id(text)
            if thread_id:
                return thread_id
            time.sleep(0.5)
        raise RuntimeError("unable to resolve thread id from live Codex session")

    def _extract_thread_id(self, text: str) -> str | None:
        matches = THREAD_ID_RE.findall(text)
        return matches[-1] if matches else None

    def _resolve_rollout_file(self, thread_id: str) -> Path | None:
        if not self.session_root.exists():
            return None
        matches = sorted(
            self.session_root.rglob(f"*{thread_id}.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return matches[0] if matches else None

    def _tmux_name_for(self, thread_id: str) -> str:
        return self.canonical_tmux_session

    def _find_live_runtime_status(
        self,
        *,
        thread_id: str | None = None,
        tmux_session: str | None = None,
    ) -> LiveRuntimeStatus | None:
        for status in self.list_live_runtime_statuses():
            if thread_id and status.thread_id == thread_id:
                return status
            if tmux_session and status.tmux_session == tmux_session:
                return status
        return None

    def _runtime_status_for_tmux(self, tmux_session: str) -> LiveRuntimeStatus:
        if not self._tmux_exists(tmux_session):
            return LiveRuntimeStatus(
                tmux_session=tmux_session,
                exists=False,
                pane_command=None,
                thread_id=None,
                pane_cwd=None,
                backend="unknown",
            )
        pane_command = self._pane_current_command(tmux_session)
        pane_cwd = self._pane_current_path(tmux_session)
        screen_text = self._capture_clean_text(tmux_session)
        backend = detect_backend(
            pane_command=pane_command,
            screen_text=screen_text,
        )
        thread_id = self._extract_thread_id(screen_text)
        return LiveRuntimeStatus(
            tmux_session=tmux_session,
            exists=True,
            pane_command=pane_command,
            thread_id=thread_id,
            pane_cwd=pane_cwd,
            backend=backend.value,
        )

    def _list_tmux_sessions(self) -> list[str]:
        proc = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            return []
        return [
            line.strip()
            for line in proc.stdout.decode(errors="replace").splitlines()
            if line.strip()
        ]

    def _is_workspace_tmux(self, pane_cwd: str | None) -> bool:
        if not pane_cwd:
            return False
        try:
            path = Path(pane_cwd).resolve(strict=False)
        except OSError:
            return False
        workspace = self.default_cwd.resolve(strict=False)
        return path == workspace or workspace in path.parents

    def _tmux_exists(self, tmux_session: str) -> bool:
        proc = subprocess.run(
            ["tmux", "has-session", "-t", tmux_session],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return proc.returncode == 0

    def _pane_current_command(self, tmux_session: str) -> str | None:
        proc = subprocess.run(
            ["tmux", "display-message", "-p", "-t", f"{tmux_session}:0.0", "#{pane_current_command}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.decode(errors="replace").strip() or None

    def _pane_current_path(self, tmux_session: str) -> str | None:
        proc = subprocess.run(
            ["tmux", "display-message", "-p", "-t", f"{tmux_session}:0.0", "#{pane_current_path}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.decode(errors="replace").strip() or None

    def _tmux_kill(self, tmux_session: str) -> None:
        subprocess.run(
            ["tmux", "kill-session", "-t", tmux_session],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _tmux_rename(self, old_name: str, new_name: str) -> None:
        subprocess.run(
            ["tmux", "rename-session", "-t", old_name, new_name],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
