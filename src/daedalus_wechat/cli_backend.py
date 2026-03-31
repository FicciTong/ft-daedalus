"""CLI backend detection for the current Codex-only WeChat bridge."""

from __future__ import annotations

import re
from enum import Enum

# Codex shows status lines like:
#   gpt-4o · thread-id-uuid
CODEX_STATUS_RE = re.compile(r"\bgpt-[^\n]*·[^\n]*\b[0-9a-f]{8}-[0-9a-f-]{28}\b")


class CliBackend(Enum):
    CODEX = "codex"
    UNKNOWN = "unknown"


def detect_backend(
    *,
    pane_command: str | None,
    screen_text: str | None = None,
) -> CliBackend:
    """Detect whether the active tmux pane is a supported Codex runtime."""
    cmd = (pane_command or "").strip().lower()

    if cmd == "codex":
        return CliBackend.CODEX

    if cmd == "node":
        return CliBackend.CODEX  # legacy default

    if not cmd or cmd in {"bash", "zsh", "sh", "fish"}:
        if screen_text and CODEX_STATUS_RE.search(screen_text):
            return CliBackend.CODEX
        return CliBackend.UNKNOWN

    return CliBackend.UNKNOWN
