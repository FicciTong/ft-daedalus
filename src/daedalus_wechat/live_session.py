from __future__ import annotations

import json
import os
import re
import shlex
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .cli_backend import CliBackend, detect_backend
from .config import default_codex_state_db, default_opencode_state_db
from .state import BridgeState, SessionRecord

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
THREAD_ID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
STATUS_LINE_RE = re.compile(r"\bgpt-[^\n]*·[^\n]*\b[0-9a-f]{8}-[0-9a-f-]{28}\b")
EPHEMERAL_LINE_RE = re.compile(
    r"^[•✻◦]\s+(Working|Baked|Thinking|Waiting|Context compacted|Updated Plan)\b"
)
PLAN_MARKER = "__DAEDALUS_PLAN__\n"
TMUX_RUNTIME_ID_OPTION = "@daedalus_runtime_id"
OPENCODE_SESSION_PREFIX = "ses_"
CLAUDE_SESSION_PREFIX = "claude:"
PENDING_RUNTIME_PREFIX = "pending:"
CLAUDE_SESSION_FILE_RE = re.compile(
    r"/\.claude/projects/[^/]+/(?P<session_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl(?: \(deleted\))?$"
)


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
    final_texts: list[str]
    end_offset: int


@dataclass(frozen=True)
class LiveRuntimeStatus:
    tmux_session: str
    exists: bool
    pane_command: str | None
    thread_id: str | None
    pane_cwd: str | None = None
    backend: str = "codex"  # codex | opencode | unknown


@dataclass(frozen=True)
class TmuxRuntimeInventoryItem:
    tmux_session: str
    pane_command: str | None
    thread_id: str | None
    pane_cwd: str | None
    switchable: bool
    reason: str
    backend: str = "codex"  # codex | opencode | unknown


class LiveCodexSessionManager:
    def __init__(
        self,
        *,
        codex_bin: str,
        opencode_bin: str,
        default_cwd: Path,
        canonical_tmux_session: str,
        codex_state_db: Path | None = None,
        opencode_state_db: Path | None = None,
    ) -> None:
        self.codex_bin = codex_bin
        self.opencode_bin = opencode_bin
        self.default_cwd = default_cwd
        self.canonical_tmux_session = canonical_tmux_session
        self.codex_state_db = codex_state_db or default_codex_state_db()
        self.opencode_state_db = opencode_state_db or default_opencode_state_db()
        self.session_root = Path.home() / ".codex" / "sessions"
        self.claude_projects_root = Path.home() / ".claude" / "projects"

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
                  and archived = 0
                  and id not in (
                    select child_thread_id
                    from thread_spawn_edges
                  )
                order by updated_at desc
                limit 1
                """,
                (str(self.default_cwd),),
            ).fetchone()
            if row:
                return str(row[0])
            row = conn.execute(
                """
                select id
                from threads
                where cwd = ?
                  and archived = 0
                order by updated_at desc
                limit 1
                """,
                (str(self.default_cwd),),
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            conn.close()

    def find_latest_opencode_session(
        self,
        *,
        pane_cwd: str | None = None,
        tmux_session: str | None = None,
    ) -> str | None:
        info = self._latest_opencode_session_info(
            pane_cwd=pane_cwd,
            tmux_session=tmux_session,
        )
        return info[0] if info else None

    def _preferred_canonical_backend(self) -> str:
        session_name = self.canonical_tmux_session.strip().lower()
        if "claude" in session_name:
            return CliBackend.CLAUDE.value
        if "opencode" in session_name or session_name.startswith("oc-"):
            return CliBackend.OPENCODE.value
        return CliBackend.CODEX.value

    def _backend_for_runtime_id(self, runtime_id: str | None) -> str:
        if self._is_pending_runtime_id(runtime_id):
            tmux_name = str(runtime_id or "")[len(PENDING_RUNTIME_PREFIX) :]
            expected_backend = self.expected_backend_for_tmux_session(tmux_name)
            if expected_backend:
                return expected_backend
        if self._is_claude_runtime_id(runtime_id):
            return CliBackend.CLAUDE.value
        if self._is_opencode_runtime_id(runtime_id):
            return CliBackend.OPENCODE.value
        return CliBackend.CODEX.value

    def _tmux_name_for_backend(self, backend: str) -> str:
        if backend == self._preferred_canonical_backend():
            return self.canonical_tmux_session
        return backend

    def expected_backend_for_tmux_session(self, tmux_session: str | None) -> str | None:
        name = str(tmux_session or "").strip().lower()
        if not name:
            return None
        if name == self.canonical_tmux_session.strip().lower():
            return self._preferred_canonical_backend()
        if "claude" in name:
            return CliBackend.CLAUDE.value
        if "opencode" in name or name.startswith("oc-"):
            return CliBackend.OPENCODE.value
        if "codex" in name:
            return CliBackend.CODEX.value
        return None

    def runtime_conflict_reason(self, status: LiveRuntimeStatus) -> str | None:
        if (
            not status.exists
            or not status.thread_id
            or status.backend == CliBackend.UNKNOWN.value
        ):
            return None
        for tmux_session in self._list_tmux_sessions():
            if tmux_session == status.tmux_session:
                continue
            other = self._runtime_status_for_tmux(tmux_session)
            if (
                not other.exists
                or not other.thread_id
                or other.backend == CliBackend.UNKNOWN.value
            ):
                continue
            if other.thread_id == status.thread_id:
                return "duplicate-runtime-id"
        return None

    def _resolved_live_label(
        self,
        *,
        existing: SessionRecord | None,
        status: LiveRuntimeStatus,
    ) -> str:
        default_label = status.tmux_session or status.backend or "live-runtime"
        if existing is None:
            return default_label
        current = existing.label.strip()
        if not current:
            return default_label
        current_lower = current.lower()
        tmux_lower = (status.tmux_session or "").strip().lower()
        # If the tmux session was renamed since last sync, refresh the label.
        old_tmux = (existing.tmux_session or "").strip().lower()
        if tmux_lower and old_tmux and tmux_lower != old_tmux:
            return default_label
        # Auto-derived labels (purely alphanumeric) that drifted from the
        # current tmux name get refreshed; user-set labels with dashes/spaces
        # (e.g. "main-live") are preserved.
        if tmux_lower and current_lower != tmux_lower and current.isalnum():
            return default_label
        if (
            current_lower == status.backend
            and tmux_lower
            and tmux_lower != current_lower
        ):
            return default_label
        if (
            status.backend == CliBackend.OPENCODE.value
            and "codex" in current_lower
            and "opencode" not in current_lower
        ):
            return default_label
        if (
            status.backend == CliBackend.CODEX.value
            and "opencode" in current_lower
            and "codex" not in current_lower
        ):
            return default_label
        if status.backend == CliBackend.CLAUDE.value and "claude" not in current_lower:
            return default_label
        return existing.label

    def ensure_attached_latest(self, state: BridgeState) -> SessionRecord | None:
        live = self.try_live_session(state)
        if live:
            return live
        canonical_status = self._runtime_status_for_tmux(self.canonical_tmux_session)
        backend = self._preferred_canonical_backend()
        if (
            canonical_status.exists
            and canonical_status.backend != CliBackend.UNKNOWN.value
            and self.runtime_conflict_reason(canonical_status) is None
        ):
            backend = canonical_status.backend
        if backend == CliBackend.OPENCODE.value:
            thread_id = self.find_latest_opencode_session(
                pane_cwd=canonical_status.pane_cwd,
                tmux_session=canonical_status.tmux_session,
            )
        else:
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
        thread_backend = self._backend_for_runtime_id(thread_id)
        live_status = self._find_live_runtime_status(
            thread_id=thread_id,
            tmux_session=existing.tmux_session if existing else None,
        )
        tmux_session = (
            live_status.tmux_session
            if live_status
            else existing.tmux_session
            if existing and existing.tmux_session
            else self._tmux_name_for(thread_id)
        )
        if not self._tmux_exists(tmux_session):
            fallback_tmux = self._tmux_name_for(thread_id)
            if fallback_tmux != tmux_session and self._tmux_exists(fallback_tmux):
                tmux_session = fallback_tmux
        if self._tmux_exists(tmux_session):
            runtime_status = self._runtime_status_for_tmux(tmux_session)
            runtime_conflict = self.runtime_conflict_reason(runtime_status)
            if runtime_conflict is not None or (
                runtime_status.backend != CliBackend.UNKNOWN.value
                and runtime_status.backend != thread_backend
            ):
                fallback_tmux = self._tmux_name_for(thread_id)
                if fallback_tmux != tmux_session:
                    tmux_session = fallback_tmux
                    runtime_status = (
                        self._runtime_status_for_tmux(tmux_session)
                        if self._tmux_exists(tmux_session)
                        else None
                    )
            current_thread_id = runtime_status.thread_id if runtime_status else None
            effective_thread_id = current_thread_id or thread_id
            self._set_tmux_runtime_id(tmux_session, effective_thread_id)
        else:
            raise RuntimeError(
                f"当前 `tmux {tmux_session}` 不存在。"
                "\nbridge 不会自动创建 session；请先在你自己的 shell 里启动/恢复它。"
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
        canonical_status = self._runtime_status_for_tmux(self.canonical_tmux_session)
        if canonical_status.exists:
            return canonical_status
        for status in live_statuses:
            if status.tmux_session == self.canonical_tmux_session:
                return status
        if live_statuses:
            return live_statuses[0]
        return canonical_status

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
            conflict_reason = self.runtime_conflict_reason(status)
            if conflict_reason is not None and conflict_reason != "duplicate-runtime-id":
                reason = conflict_reason
                switchable = False
            elif status.backend == "unknown":
                reason = "unrecognized-cli"
                switchable = False
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
                    label=self._resolved_live_label(existing=existing, status=status),
                    cwd=existing.cwd
                    if existing
                    else status.pane_cwd or str(self.default_cwd),
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
        if (
            not status.exists
            or not status.thread_id
            or self.runtime_conflict_reason(status) is not None
        ):
            return None
        existing = state.sessions.get(status.thread_id)
        label = self._resolved_live_label(existing=existing, status=status)
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
            backend = self._preferred_canonical_backend()
            start_hint = "启动 canonical tmux live runtime"
            if backend == CliBackend.CODEX.value:
                start_hint = (
                    "当前没有 `tmux codex`。请先启动一个固定窗口，例如：\n"
                    f"tmux new -s {self.canonical_tmux_session} "
                    f"'{self.codex_bin} resume --last -C {self.default_cwd} --no-alt-screen'"
                )
            elif backend == CliBackend.OPENCODE.value:
                start_hint = (
                    "当前没有 canonical OpenCode tmux。请先启动一个固定窗口，例如：\n"
                    f"tmux new -s {self.canonical_tmux_session} "
                    f"'{self.opencode_bin} {self.default_cwd}'"
                )
            elif backend == CliBackend.CLAUDE.value:
                start_hint = (
                    "当前没有 canonical Claude tmux。请先启动一个固定窗口，例如：\n"
                    f"tmux new -s {self.canonical_tmux_session} 'claude --resume'"
                )
            raise RuntimeError(start_hint)
        if status.backend == "unknown":
            raise RuntimeError(
                f"`tmux {status.tmux_session}` 已存在，但里面当前不是受支持的 live runtime "
                f"(pane_current_command={status.pane_command or 'unknown'})。"
                "\n请先 attach 进去并启动 Codex、OpenCode 或 Claude。"
            )
        conflict_reason = self.runtime_conflict_reason(status)
        if conflict_reason is not None:
            lines = [
                f"`tmux {status.tmux_session}` 当前处于 runtime 冲突状态。",
                f"conflict={conflict_reason}",
                f"backend={status.backend}",
            ]
            lines.append("请先恢复 shell/runtime 隔离后再继续使用 bridge。")
            raise RuntimeError("\n".join(lines))
        if not status.thread_id:
            if status.backend == CliBackend.OPENCODE.value:
                existing = self._find_existing_tmux_record(
                    state=state, tmux_session=status.tmux_session
                )
                thread_id = (
                    existing.thread_id
                    if existing
                    else self._pending_runtime_id(status.tmux_session)
                )
                self._set_tmux_runtime_id(status.tmux_session, thread_id)
                return state.touch_session(
                    thread_id,
                    label=self._resolved_live_label(existing=existing, status=status),
                    cwd=existing.cwd
                    if existing
                    else status.pane_cwd or str(self.default_cwd),
                    source=existing.source if existing else "tmux-live-provisional",
                    tmux_session=status.tmux_session,
                )
            if status.backend == CliBackend.CLAUDE.value:
                raise RuntimeError(
                    f"`tmux {status.tmux_session}` 已打开，但还没有识别到可用的 Claude session。"
                    "\n请先 attach 进去，确认 Claude Code 已经进入当前项目会话。"
                )
            raise RuntimeError(
                f"`tmux {status.tmux_session}` 已打开，但还没有进入任何 Codex thread。"
                "\n请先 attach 进去执行：\n"
                f"codex resume --last -C {self.default_cwd} --no-alt-screen"
            )
        self._set_tmux_runtime_id(status.tmux_session, status.thread_id)
        existing = state.sessions.get(status.thread_id)
        label = self._resolved_live_label(existing=existing, status=status)
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
        backend = self._preferred_canonical_backend()
        if self._tmux_exists(tmux_session):
            status = self._runtime_status_for_tmux(tmux_session)
            current_thread_id = status.thread_id
            if current_thread_id:
                self._set_tmux_runtime_id(tmux_session, current_thread_id)
                return state.touch_session(
                    current_thread_id,
                    label=label,
                    cwd=str(self.default_cwd),
                    source="bridge-canonical-existing",
                    tmux_session=tmux_session,
                )
            backend = (
                status.backend
                if status.backend != CliBackend.UNKNOWN.value
                else backend
            )
        raise RuntimeError(
            f"当前 `tmux {tmux_session}` 不存在。"
            "\nbridge 不会自动创建 session；请先在你自己的 shell 里启动 canonical live runtime。"
        )

    def submit_prompt(self, *, record: SessionRecord, prompt: str) -> SessionRecord:
        tmux_session = self._ensure_running_tmux(record)
        runtime_before = self._runtime_status_for_tmux(tmux_session)
        opencode_before = None
        if runtime_before.backend == CliBackend.OPENCODE.value:
            opencode_before = self._latest_opencode_session_info(
                pane_cwd=runtime_before.pane_cwd,
                tmux_session=tmux_session,
            )
        self._inject_prompt(tmux_session, prompt)
        runtime_after = self._runtime_status_for_tmux(tmux_session)
        thread_id = runtime_after.thread_id or record.thread_id
        if runtime_after.backend == CliBackend.OPENCODE.value:
            before_id = opencode_before[0] if opencode_before else None
            before_updated = opencode_before[1] if opencode_before else 0
            resolved = self._wait_for_opencode_session_id(
                tmux_session=tmux_session,
                pane_cwd=runtime_after.pane_cwd,
                previous_session_id=before_id,
                previous_time_updated=before_updated,
            )
            if resolved:
                thread_id = resolved
        self._set_tmux_runtime_id(tmux_session, thread_id)
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
            rollout_file.stat().st_size if rollout_file and rollout_file.exists() else 0
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
                "桌面 tmux live runtime 仍然保留完整输出；"
                "如果这次回答还在继续生成，请回到电脑侧查看。"
            )
        thread_id = (
            self._runtime_status_for_tmux(tmux_session).thread_id or record.thread_id
        )
        return LiveReply(
            thread_id=thread_id, response_text=response_text or "(无文本回复)"
        )

    def attach_hint(self, record: SessionRecord) -> str:
        tmux_session = record.tmux_session or self._tmux_name_for(record.thread_id)
        return f"tmux attach -t {tmux_session}"

    def rollout_size(self, thread_id: str) -> int:
        if not thread_id:
            return 0
        if self._is_opencode_runtime_id(thread_id):
            return self._opencode_latest_part_rowid(thread_id)
        if self._is_claude_runtime_id(thread_id):
            session_file = self._resolve_rollout_file(thread_id)
            if session_file and session_file.exists():
                return int(session_file.stat().st_size)
            return 0
        rollout_file = self._resolve_rollout_file(thread_id)
        if rollout_file is None or not rollout_file.exists():
            return 0
        return int(rollout_file.stat().st_size)

    def latest_mirror_since(
        self, *, thread_id: str, start_offset: int
    ) -> MirrorScan | None:
        if self._is_opencode_runtime_id(thread_id):
            return self._opencode_mirror_since(
                thread_id=thread_id, start_offset=start_offset
            )
        if self._is_claude_runtime_id(thread_id):
            return self._claude_mirror_since(
                thread_id=thread_id, start_offset=start_offset
            )
        rollout_file = self._resolve_rollout_file(thread_id)
        if rollout_file is None or not rollout_file.exists():
            return None
        offset = int(start_offset)
        size = rollout_file.stat().st_size
        if size < offset:
            offset = 0
        if size == offset:
            return MirrorScan(progress_texts=[], final_texts=[], end_offset=offset)
        carry = ""
        final_texts: list[str] = []
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
                final_texts.append(extracted)
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
                    final_texts.append(extracted)
        return MirrorScan(
            progress_texts=progress_texts, final_texts=final_texts, end_offset=end_offset
        )

    def latest_final_since(
        self, *, thread_id: str, start_offset: int
    ) -> FinalScan | None:
        scan = self.latest_mirror_since(thread_id=thread_id, start_offset=start_offset)
        if scan is None:
            return None
        return FinalScan(
            final_text=scan.final_texts[-1] if scan.final_texts else "",
            end_offset=scan.end_offset,
        )

    def _ensure_running_tmux(self, record: SessionRecord) -> str:
        tmux_session = record.tmux_session or self._tmux_name_for(record.thread_id)
        if not self._tmux_exists(tmux_session):
            raise RuntimeError(
                f"当前 `tmux {tmux_session}` 不存在。请先启动并在里面打开 live runtime。"
            )
        return tmux_session

    def _start_tmux_session(self, tmux_session: str, cmd: list[str]) -> None:
        shell_cmd = shlex.join(cmd)
        raise RuntimeError(
            f"当前 `tmux {tmux_session}` 不存在。"
            "\nbridge 不会自动创建 session；请先在你自己的 shell 里启动它，例如："
            f"\n{shell_cmd}"
        )

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
                visible_now = self._extract_visible_after_prompt(
                    current, submitted_prompt
                )
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
            [
                "tmux",
                "capture-pane",
                "-p",
                "-J",
                "-t",
                f"{tmux_session}:0.0",
                "-S",
                "-2000",
            ],
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

    def _extract_visible_after_prompt(
        self, full_text: str, submitted_prompt: str
    ) -> str:
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

    def _wait_for_runtime_id(self, tmux_session: str, *, backend: str) -> str | None:
        if backend == CliBackend.OPENCODE.value:
            status = self._runtime_status_for_tmux(tmux_session)
            return self._wait_for_opencode_session_id(
                tmux_session=tmux_session,
                pane_cwd=status.pane_cwd,
                previous_session_id=None,
                previous_time_updated=0,
            )
        return self._wait_for_thread_id(tmux_session)

    def _extract_thread_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()
        for match in THREAD_ID_RE.findall(text):
            if match in seen:
                continue
            seen.add(match)
            candidates.append(match)
        return candidates

    def _extract_thread_id(self, text: str) -> str | None:
        candidates = self._extract_thread_candidates(text)
        return candidates[-1] if candidates else None

    def _resolve_rollout_file(self, thread_id: str) -> Path | None:
        if self._is_claude_runtime_id(thread_id):
            session_id = thread_id[len(CLAUDE_SESSION_PREFIX) :]
            if not self.claude_projects_root.exists():
                return None
            matches = sorted(
                self.claude_projects_root.rglob(f"{session_id}.jsonl"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            return matches[0] if matches else None
        if not self.session_root.exists():
            return None
        matches = sorted(
            self.session_root.rglob(f"*{thread_id}.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return matches[0] if matches else None

    def _thread_rollout_mtime(self, thread_id: str) -> float:
        rollout = self._resolve_rollout_file(thread_id)
        if rollout is None or not rollout.exists():
            return float("-inf")
        return float(rollout.stat().st_mtime)

    def _resolve_runtime_thread_id(
        self,
        *,
        tmux_session: str,
        pane_cwd: str | None,
        screen_text: str,
        backend: str,
    ) -> str | None:
        if backend == CliBackend.OPENCODE.value:
            return self._resolve_opencode_session_id(
                tmux_session=tmux_session,
                pane_cwd=pane_cwd,
            )
        if backend == CliBackend.CLAUDE.value:
            return self._resolve_claude_session_id(tmux_session=tmux_session)
        candidates = self._extract_thread_candidates(screen_text)
        pane_candidate = candidates[-1] if candidates else None
        if backend != "codex" or not self._is_workspace_tmux(pane_cwd):
            return pane_candidate

        latest_thread = self.find_latest_thread()
        if latest_thread and latest_thread not in candidates:
            candidates.append(latest_thread)
        if not candidates:
            if tmux_session == self.canonical_tmux_session:
                return latest_thread
            return None

        rollout_backed = [
            candidate
            for candidate in candidates
            if self._thread_rollout_mtime(candidate) != float("-inf")
        ]
        if rollout_backed:
            return max(
                rollout_backed,
                key=lambda candidate: (
                    self._thread_rollout_mtime(candidate),
                    1 if latest_thread and candidate == latest_thread else 0,
                    1 if pane_candidate and candidate == pane_candidate else 0,
                ),
            )
        if tmux_session == self.canonical_tmux_session and latest_thread:
            return latest_thread
        return pane_candidate or latest_thread

    def _resolve_opencode_session_id(
        self,
        *,
        tmux_session: str,
        pane_cwd: str | None,
    ) -> str | None:
        latest = self._latest_opencode_session_info(
            pane_cwd=pane_cwd,
            tmux_session=tmux_session,
        )
        if latest:
            return latest[0]
        hinted = self._get_tmux_runtime_id(tmux_session)
        if hinted and (
            self._is_opencode_runtime_id(hinted) or self._is_pending_runtime_id(hinted)
        ):
            return hinted
        return None

    def _is_opencode_runtime_id(self, runtime_id: str | None) -> bool:
        return bool(runtime_id and runtime_id.startswith(OPENCODE_SESSION_PREFIX))

    def _is_claude_runtime_id(self, runtime_id: str | None) -> bool:
        return bool(runtime_id and runtime_id.startswith(CLAUDE_SESSION_PREFIX))

    def _is_pending_runtime_id(self, runtime_id: str | None) -> bool:
        return bool(runtime_id and runtime_id.startswith(PENDING_RUNTIME_PREFIX))

    def _pending_runtime_id(self, tmux_session: str) -> str:
        return f"{PENDING_RUNTIME_PREFIX}{tmux_session}"

    def _claude_runtime_id(self, session_id: str) -> str:
        return f"{CLAUDE_SESSION_PREFIX}{session_id}"

    def _resolve_claude_session_id(self, *, tmux_session: str) -> str | None:
        session_file = self._current_claude_session_file(tmux_session)
        if session_file is not None:
            session_id = self._extract_claude_session_id_from_path(session_file)
            if session_id:
                return self._claude_runtime_id(session_id)
        hinted = self._get_tmux_runtime_id(tmux_session)
        if hinted and self._is_claude_runtime_id(hinted):
            return hinted
        return None

    def _extract_claude_session_id_from_path(self, path: Path) -> str | None:
        match = CLAUDE_SESSION_FILE_RE.search(str(path))
        if not match:
            return None
        return str(match.group("session_id"))

    def _current_claude_session_file(self, tmux_session: str) -> Path | None:
        pane_pid = self._pane_pid(tmux_session)
        if pane_pid is not None:
            for pid in [pane_pid, *self._proc_children(pane_pid)]:
                for raw_path in self._proc_open_paths(pid):
                    match = CLAUDE_SESSION_FILE_RE.search(raw_path)
                    if match:
                        return Path(raw_path.replace(" (deleted)", ""))
        project_dir = self._claude_project_dir(tmux_session)
        if project_dir is None or not project_dir.exists():
            return None
        matches = sorted(
            project_dir.glob("*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return matches[0] if matches else None

    def _claude_project_dir(self, tmux_session: str) -> Path | None:
        pane_cwd = self._pane_current_path(tmux_session) or str(self.default_cwd)
        try:
            resolved = Path(pane_cwd).resolve(strict=False)
        except OSError:
            return None
        slug = "-" + "-".join(part for part in resolved.parts if part and part != "/")
        return self.claude_projects_root / slug

    def _proc_children(self, pid: int) -> list[int]:
        children_file = Path(f"/proc/{pid}/task/{pid}/children")
        if not children_file.exists():
            return []
        try:
            content = children_file.read_text(encoding="utf-8").strip()
        except OSError:
            return []
        if not content:
            return []
        children: list[int] = []
        for token in content.split():
            try:
                children.append(int(token))
            except ValueError:
                continue
        return children

    def _proc_open_paths(self, pid: int) -> list[str]:
        fd_dir = Path(f"/proc/{pid}/fd")
        if not fd_dir.exists():
            return []
        paths: list[str] = []
        for fd in fd_dir.iterdir():
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            paths.append(target)
        return paths

    def _opencode_candidate_directories(self, pane_cwd: str | None) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()
        for raw in (pane_cwd, str(self.default_cwd)):
            if not raw:
                continue
            try:
                value = str(Path(raw).resolve(strict=False))
            except OSError:
                value = str(raw)
            if value in seen:
                continue
            seen.add(value)
            candidates.append(value)
        return candidates

    def _latest_opencode_session_info(
        self,
        *,
        pane_cwd: str | None = None,
        tmux_session: str | None = None,
    ) -> tuple[str, int] | None:
        state_db = self.opencode_state_db
        if not state_db.exists():
            return None
        directories = self._opencode_candidate_directories(pane_cwd)
        if not directories:
            return None
        placeholders = ",".join("?" for _ in directories)
        title = str(tmux_session or "").strip()
        conn = sqlite3.connect(state_db)
        try:
            row = None
            if title:
                try:
                    row = conn.execute(
                        f"""
                        select id, time_updated
                        from session
                        where time_archived is null
                          and title = ?
                          and directory in ({placeholders})
                        order by time_updated desc, time_created desc
                        limit 1
                        """,
                        [title, *directories],
                    ).fetchone()
                except sqlite3.OperationalError:
                    row = None
            if row:
                return str(row[0]), int(row[1] or 0)
            row = conn.execute(
                f"""
                select id, time_updated
                from session
                where time_archived is null
                  and directory in ({placeholders})
                order by time_updated desc, time_created desc
                limit 1
                """,
                directories,
            ).fetchone()
            if row:
                return str(row[0]), int(row[1] or 0)
            return None
        finally:
            conn.close()

    def _wait_for_opencode_session_id(
        self,
        *,
        tmux_session: str,
        pane_cwd: str | None,
        previous_session_id: str | None,
        previous_time_updated: int,
    ) -> str | None:
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            info = self._latest_opencode_session_info(
                pane_cwd=pane_cwd,
                tmux_session=tmux_session,
            )
            if info:
                session_id, time_updated = info
                if (
                    session_id != previous_session_id
                    or time_updated > previous_time_updated
                ):
                    self._set_tmux_runtime_id(tmux_session, session_id)
                    return session_id
            time.sleep(0.25)
        return previous_session_id

    def _opencode_latest_part_rowid(self, session_id: str) -> int:
        state_db = self.opencode_state_db
        if not state_db.exists():
            return 0
        conn = sqlite3.connect(state_db)
        try:
            row = conn.execute(
                "select max(rowid) from part where session_id = ?",
                (session_id,),
            ).fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            conn.close()

    def _opencode_mirror_since(
        self, *, thread_id: str, start_offset: int
    ) -> MirrorScan | None:
        state_db = self.opencode_state_db
        if not state_db.exists():
            return None
        conn = sqlite3.connect(state_db)
        try:
            rows = conn.execute(
                """
                select p.rowid, p.message_id, p.data, m.data
                from part p
                join message m on m.id = p.message_id
                where p.session_id = ?
                  and p.rowid > ?
                order by p.rowid asc
                """,
                (thread_id, int(start_offset)),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return MirrorScan(
                progress_texts=[], final_texts=[], end_offset=int(start_offset)
            )
        message_parts: dict[str, dict[str, object]] = {}
        progress_texts: list[str] = []
        final_texts: list[str] = []
        end_offset = int(start_offset)
        for rowid, message_id, part_raw, message_raw in rows:
            end_offset = max(end_offset, int(rowid))
            try:
                part = json.loads(part_raw)
                message = json.loads(message_raw)
            except json.JSONDecodeError:
                continue
            if str(message.get("role", "")).strip() != "assistant":
                continue
            bucket = message_parts.setdefault(
                str(message_id),
                {
                    "progress_chunks": [],
                    "final_chunks": [],
                    "saw_stop": False,
                },
            )
            part_type = str(part.get("type", "")).strip()
            if part_type == "text":
                text = str(part.get("text", "")).strip()
                if not text:
                    continue
                if self._opencode_part_phase(part) == "final_answer":
                    bucket["final_chunks"].append(text)
                else:
                    bucket["progress_chunks"].append(text)
                continue
            if (
                part_type == "step-finish"
                and str(part.get("reason", "")).strip() == "stop"
            ):
                bucket["saw_stop"] = True
        for bucket in message_parts.values():
            final_chunks = [
                str(chunk).strip()
                for chunk in bucket.get("final_chunks", [])
                if str(chunk).strip()
            ]
            if final_chunks:
                final_texts.append("".join(final_chunks).strip())
                continue
            progress_chunks = [
                str(chunk).strip()
                for chunk in bucket.get("progress_chunks", [])
                if str(chunk).strip()
            ]
            if bucket.get("saw_stop") and progress_chunks:
                final_texts.append("".join(progress_chunks).strip())
                continue
            for chunk in progress_chunks:
                normalized = self._normalize_progress_text(chunk)
                if normalized:
                    progress_texts.append(normalized)
        return MirrorScan(
            progress_texts=progress_texts, final_texts=final_texts, end_offset=end_offset
        )

    def _claude_mirror_since(
        self, *, thread_id: str, start_offset: int
    ) -> MirrorScan | None:
        session_file = self._resolve_rollout_file(thread_id)
        if session_file is None or not session_file.exists():
            return None
        offset = int(start_offset)
        size = session_file.stat().st_size
        if size < offset:
            offset = 0
        if size == offset:
            return MirrorScan(progress_texts=[], final_texts=[], end_offset=offset)
        with session_file.open("r", encoding="utf-8") as fh:
            fh.seek(offset)
            chunk = fh.read()
            end_offset = fh.tell()
        final_texts: list[str] = []
        for raw in chunk.splitlines():
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            extracted = self._extract_claude_final_text(event)
            if extracted:
                final_texts.append(extracted)
        return MirrorScan(
            progress_texts=[], final_texts=final_texts, end_offset=end_offset
        )

    def _extract_claude_final_text(self, event: dict) -> str:
        if str(event.get("type", "")).strip() != "assistant":
            return ""
        message = event.get("message") or {}
        if str(message.get("role", "")).strip() != "assistant":
            return ""
        parts: list[str] = []
        has_tool_use = False
        for item in message.get("content") or []:
            item_type = str(item.get("type", "")).strip()
            if item_type == "tool_use":
                has_tool_use = True
                continue
            if item_type != "text":
                continue
            text = str(item.get("text", "")).strip()
            if text:
                parts.append(text)
        if not parts:
            return ""
        stop_reason = str(message.get("stop_reason", "")).strip()
        if has_tool_use and stop_reason not in {"end_turn", "stop_sequence"}:
            return ""
        return "\n\n".join(parts).strip()

    def _extract_opencode_final_text(self, *, part: dict, message: dict) -> str:
        if str(message.get("role", "")).strip() != "assistant":
            return ""
        if str(part.get("type", "")).strip() != "text":
            return ""
        if self._opencode_part_phase(part) != "final_answer":
            return ""
        return str(part.get("text", "")).strip()

    def _extract_opencode_progress_text(self, *, part: dict, message: dict) -> str:
        if str(message.get("role", "")).strip() != "assistant":
            return ""
        if str(part.get("type", "")).strip() != "text":
            return ""
        if self._opencode_part_phase(part) == "final_answer":
            return ""
        return self._normalize_progress_text(str(part.get("text", "")).strip())

    def _opencode_part_phase(self, part: dict) -> str:
        metadata = part.get("metadata")
        if isinstance(metadata, dict):
            direct = str(metadata.get("phase", "")).strip()
            if direct:
                return direct
            for value in metadata.values():
                if isinstance(value, dict):
                    phase = str(value.get("phase", "")).strip()
                    if phase:
                        return phase
        return ""

    def _tmux_name_for(self, thread_id: str) -> str:
        return self._tmux_name_for_backend(self._backend_for_runtime_id(thread_id))

    def _start_command(
        self, *, backend: str, thread_id: str | None = None
    ) -> list[str]:
        if backend == CliBackend.OPENCODE.value:
            cmd = [self.opencode_bin, str(self.default_cwd)]
            if thread_id and self._is_opencode_runtime_id(thread_id):
                cmd.extend(["--session", thread_id])
            return cmd
        if thread_id:
            return [
                self.codex_bin,
                "resume",
                thread_id,
                "-C",
                str(self.default_cwd),
                "--no-alt-screen",
            ]
        return [
            self.codex_bin,
            "-C",
            str(self.default_cwd),
            "--no-alt-screen",
        ]

    def _find_existing_tmux_record(
        self,
        *,
        state: BridgeState,
        tmux_session: str,
    ) -> SessionRecord | None:
        records = [
            record
            for record in state.sessions.values()
            if record.tmux_session == tmux_session
        ]
        if not records:
            return None
        return max(records, key=lambda item: item.updated_at)

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
        pane_start_command = self._pane_start_command(tmux_session)
        hinted_runtime_id = self._get_tmux_runtime_id(tmux_session)
        hinted_backend = (
            self._backend_for_runtime_id(hinted_runtime_id)
            if hinted_runtime_id
            else None
        )
        pane_pid = self._pane_pid(tmux_session)
        backend = detect_backend(
            pane_command=pane_command,
            pane_start_command=pane_start_command,
            screen_text=screen_text,
            pane_pid=pane_pid,
        )
        if backend == CliBackend.UNKNOWN:
            if hinted_backend:
                backend = CliBackend(hinted_backend)
        elif (
            pane_command == "node"
            and not (pane_start_command or "").strip()
            and hinted_backend
            and backend.value != hinted_backend
        ):
            backend = CliBackend(hinted_backend)
        thread_id = self._resolve_runtime_thread_id(
            tmux_session=tmux_session,
            pane_cwd=pane_cwd,
            screen_text=screen_text,
            backend=backend.value,
        )
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

    def _pane_pid(self, tmux_session: str) -> int | None:
        proc = subprocess.run(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                f"{tmux_session}:0.0",
                "#{pane_pid}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            return None
        raw = proc.stdout.decode(errors="replace").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _get_tmux_runtime_id(self, tmux_session: str) -> str | None:
        proc = subprocess.run(
            ["tmux", "show-options", "-v", "-t", tmux_session, TMUX_RUNTIME_ID_OPTION],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            return None
        value = proc.stdout.decode(errors="replace").strip()
        return value or None

    def _set_tmux_runtime_id(self, tmux_session: str, runtime_id: str | None) -> None:
        if not self._tmux_exists(tmux_session):
            return
        if not runtime_id:
            return
        subprocess.run(
            [
                "tmux",
                "set-option",
                "-t",
                tmux_session,
                TMUX_RUNTIME_ID_OPTION,
                runtime_id,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def _pane_current_command(self, tmux_session: str) -> str | None:
        proc = subprocess.run(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                f"{tmux_session}:0.0",
                "#{pane_current_command}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.decode(errors="replace").strip() or None

    def _pane_current_path(self, tmux_session: str) -> str | None:
        proc = subprocess.run(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                f"{tmux_session}:0.0",
                "#{pane_current_path}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.decode(errors="replace").strip() or None

    def _pane_start_command(self, tmux_session: str) -> str | None:
        proc = subprocess.run(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                f"{tmux_session}:0.0",
                "#{pane_start_command}",
            ],
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
