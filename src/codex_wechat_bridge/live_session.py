from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import re
import shlex
import sqlite3
import subprocess
import time
from pathlib import Path

from .state import BridgeState, SessionRecord


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
THREAD_ID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
STATUS_LINE_RE = re.compile(r"\bgpt-[^\n]*·[^\n]*\b[0-9a-f]{8}-[0-9a-f-]{28}\b")
EPHEMERAL_LINE_RE = re.compile(
    r"^[•✻◦]\s+(Working|Baked|Thinking|Waiting|Context compacted|Updated Plan)\b"
)


@dataclass(frozen=True)
class LiveReply:
    thread_id: str
    response_text: str


@dataclass(frozen=True)
class LiveRuntimeStatus:
    tmux_session: str
    exists: bool
    pane_command: str | None
    thread_id: str | None


class LiveCodexSessionManager:
    def __init__(
        self,
        *,
        codex_bin: str,
        default_cwd: Path,
        canonical_tmux_session: str,
    ) -> None:
        self.codex_bin = codex_bin
        self.default_cwd = default_cwd
        self.canonical_tmux_session = canonical_tmux_session
        self.session_root = Path.home() / ".codex" / "sessions"

    def find_latest_thread(self) -> str | None:
        state_db = Path.home() / ".codex" / "state_5.sqlite"
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
        tmux_session = self._tmux_name_for(thread_id)
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

    def current_runtime_status(self) -> LiveRuntimeStatus:
        tmux_session = self.canonical_tmux_session
        if not self._tmux_exists(tmux_session):
            return LiveRuntimeStatus(
                tmux_session=tmux_session,
                exists=False,
                pane_command=None,
                thread_id=None,
            )
        pane_command = self._pane_current_command(tmux_session)
        thread_id = self._extract_thread_id(self._capture_clean_text(tmux_session))
        return LiveRuntimeStatus(
            tmux_session=tmux_session,
            exists=True,
            pane_command=pane_command,
            thread_id=thread_id,
        )

    def try_live_session(self, state: BridgeState) -> SessionRecord | None:
        status = self.current_runtime_status()
        if not status.exists or not status.thread_id:
            return None
        existing = state.sessions.get(status.thread_id)
        label = existing.label if existing else "live-codex"
        source = existing.source if existing else "tmux-live"
        return state.touch_session(
            status.thread_id,
            label=label,
            cwd=str(self.default_cwd),
            source=source,
            tmux_session=status.tmux_session,
        )

    def require_live_session(self, state: BridgeState) -> SessionRecord:
        status = self.current_runtime_status()
        if not status.exists:
            raise RuntimeError(
                "当前没有 `tmux codex`。请先启动一个固定窗口，例如：\n"
                f"tmux new -s {self.canonical_tmux_session} "
                f"'{self.codex_bin} resume --last -C {self.default_cwd} --no-alt-screen'"
            )
        if status.pane_command not in {"node", "codex"}:
            raise RuntimeError(
                f"`tmux {status.tmux_session}` 已存在，但里面当前不是 Codex "
                f"(pane_current_command={status.pane_command or 'unknown'})。"
                "\n请先 attach 进去并启动/恢复一条 Codex session。"
            )
        if not status.thread_id:
            raise RuntimeError(
                f"`tmux {status.tmux_session}` 已打开，但还没有进入任何 Codex thread。"
                "\n请先 attach 进去执行：\n"
                f"codex resume --last -C {self.default_cwd} --no-alt-screen"
            )
        existing = state.sessions.get(status.thread_id)
        label = existing.label if existing else "live-codex"
        source = existing.source if existing else "tmux-live"
        return state.touch_session(
            status.thread_id,
            label=label,
            cwd=str(self.default_cwd),
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

    def send_prompt(self, *, record: SessionRecord, prompt: str) -> LiveReply:
        tmux_session = self._ensure_running_tmux(record)
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
