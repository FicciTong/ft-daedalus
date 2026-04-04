"""CLI backend detection for live tmux runtimes supported by the WeChat bridge."""

from __future__ import annotations

import re
from enum import Enum

# Codex shows status lines like:
#   gpt-4o · thread-id-uuid
CODEX_STATUS_RE = re.compile(r"\bgpt-[^\n]*·[^\n]*\b[0-9a-f]{8}-[0-9a-f-]{28}\b")
OPENCODE_HINT_RE = re.compile(r"\bOpenCode\b|\bAsk anything\b|\bBuild\b.*\bgpt-", re.IGNORECASE)


class CliBackend(Enum):
    CODEX = "codex"
    OPENCODE = "opencode"
    UNKNOWN = "unknown"


def detect_backend(
    *,
    pane_command: str | None,
    screen_text: str | None = None,
) -> CliBackend:
    """Detect whether the active tmux pane is a supported live runtime."""
    cmd = (pane_command or "").strip().lower()

    if cmd == "codex":
        return CliBackend.CODEX

    if cmd == "opencode":
        return CliBackend.OPENCODE

    if cmd == "node":
        if screen_text and OPENCODE_HINT_RE.search(screen_text):
            return CliBackend.OPENCODE
        if screen_text and CODEX_STATUS_RE.search(screen_text):
            return CliBackend.CODEX
        return CliBackend.CODEX  # legacy default

    if not cmd or cmd in {"bash", "zsh", "sh", "fish"}:
        if screen_text and CODEX_STATUS_RE.search(screen_text):
            return CliBackend.CODEX
        if screen_text and OPENCODE_HINT_RE.search(screen_text):
            return CliBackend.OPENCODE
        return CliBackend.UNKNOWN

    return CliBackend.UNKNOWN
