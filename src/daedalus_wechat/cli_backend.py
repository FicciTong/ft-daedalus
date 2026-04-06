"""CLI backend detection for live tmux runtimes supported by the WeChat bridge."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

# Codex shows status lines like:
#   gpt-4o · thread-id-uuid
CODEX_STATUS_RE = re.compile(
    r"\bgpt-[^\n]*·\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
OPENCODE_HINT_RE = re.compile(
    r"\bOpenCode\b|\bAsk anything\b|\bBuild\b.*\bgpt-", re.IGNORECASE
)
CLAUDE_HINT_RE = re.compile(r"\bClaude Code\b|\bclaude-(opus|sonnet)\b", re.IGNORECASE)

# /proc/*/comm values that identify each backend.
_COMM_TO_BACKEND: dict[str, "CliBackend"] = {}  # populated after CliBackend defined


class CliBackend(Enum):
    CODEX = "codex"
    OPENCODE = "opencode"
    CLAUDE = "claude"
    UNKNOWN = "unknown"


_COMM_TO_BACKEND.update({
    "opencode": CliBackend.OPENCODE,
    ".opencode": CliBackend.OPENCODE,
    "codex": CliBackend.CODEX,
    "claude": CliBackend.CLAUDE,
})


def _detect_backend_from_proc(pane_pid: int | None) -> CliBackend:
    """Walk /proc process tree to detect backend from child process names."""
    if not pane_pid:
        return CliBackend.UNKNOWN
    proc_root = Path("/proc")
    to_visit = [pane_pid]
    visited: set[int] = set()
    while to_visit:
        pid = to_visit.pop()
        if pid in visited:
            continue
        visited.add(pid)
        try:
            comm = (proc_root / str(pid) / "comm").read_text().strip().lower()
        except OSError:
            continue
        backend = _COMM_TO_BACKEND.get(comm)
        if backend is not None:
            return backend
        # Enqueue children via /proc/<pid>/task/<tid>/children.
        task_dir = proc_root / str(pid) / "task"
        try:
            for tid_entry in task_dir.iterdir():
                children_file = tid_entry / "children"
                try:
                    for child in children_file.read_text().split():
                        child_pid = int(child)
                        if child_pid not in visited:
                            to_visit.append(child_pid)
                except (OSError, ValueError):
                    pass
        except OSError:
            pass
    return CliBackend.UNKNOWN


def detect_backend(
    *,
    pane_command: str | None,
    pane_start_command: str | None = None,
    screen_text: str | None = None,
    pane_pid: int | None = None,
) -> CliBackend:
    """Detect whether the active tmux pane is a supported live runtime."""
    cmd = (pane_command or "").strip().lower()
    start_cmd = (pane_start_command or "").strip().lower()

    if cmd == "codex":
        return CliBackend.CODEX

    if cmd == "opencode":
        return CliBackend.OPENCODE

    if cmd == "claude":
        return CliBackend.CLAUDE

    if cmd == "node":
        if screen_text and OPENCODE_HINT_RE.search(screen_text):
            return CliBackend.OPENCODE
        if screen_text and CODEX_STATUS_RE.search(screen_text):
            return CliBackend.CODEX
        if screen_text and CLAUDE_HINT_RE.search(screen_text):
            return CliBackend.CLAUDE
        if "opencode" in start_cmd:
            return CliBackend.OPENCODE
        if "codex" in start_cmd:
            return CliBackend.CODEX
        if "claude" in start_cmd:
            return CliBackend.CLAUDE
        # Fallback: inspect child process tree via /proc (robust after
        # tmux-resurrect where start_command and screen text may be lost).
        child_backend = _detect_backend_from_proc(pane_pid)
        if child_backend != CliBackend.UNKNOWN:
            return child_backend
        return CliBackend.UNKNOWN

    if not cmd or cmd in {"bash", "zsh", "sh", "fish"}:
        if screen_text and CODEX_STATUS_RE.search(screen_text):
            return CliBackend.CODEX
        if screen_text and OPENCODE_HINT_RE.search(screen_text):
            return CliBackend.OPENCODE
        if screen_text and CLAUDE_HINT_RE.search(screen_text):
            return CliBackend.CLAUDE
        if "opencode" in start_cmd:
            return CliBackend.OPENCODE
        if "codex" in start_cmd:
            return CliBackend.CODEX
        if "claude" in start_cmd:
            return CliBackend.CLAUDE
        return CliBackend.UNKNOWN

    return CliBackend.UNKNOWN
