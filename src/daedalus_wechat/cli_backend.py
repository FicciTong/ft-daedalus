"""CLI backend detection and abstraction.

The bridge supports multiple AI CLI tools running in tmux sessions.
Currently supported backends:

- **codex**: OpenAI Codex CLI (pane_command: node, codex)
- **claude**: Claude Code CLI (pane_command: claude)
- **unknown**: Unrecognized CLI or bare shell

Detection is automatic: when switching to a tmux session, the bridge
inspects `pane_current_command` and tmux screen content to determine
which backend is active, then adapts its session management and event
parsing accordingly.
"""

from __future__ import annotations

import re
from enum import Enum

# Claude Code shows a status line like:
#   ╭─ (model-name)  session-name
# or spinner lines with specific unicode characters
CLAUDE_STATUS_RE = re.compile(
    r"(?:"
    r"\u256d\u2500|"           # ╭─  (Claude Code box-drawing header)
    r"Claude Code|"            # literal "Claude Code"
    r"\u25b8\u25b8|"           # ⏵⏵  (bypass permissions indicator)
    r"\u2588|"                 # █   (cursor block)
    r"claude-opus|claude-sonnet|claude-haiku"  # model names in status
    r")"
)

# Codex shows status lines like:
#   gpt-4o · thread-id-uuid
CODEX_STATUS_RE = re.compile(r"\bgpt-[^\n]*·[^\n]*\b[0-9a-f]{8}-[0-9a-f-]{28}\b")


class CliBackend(Enum):
    CODEX = "codex"
    CLAUDE = "claude"
    UNKNOWN = "unknown"


def detect_backend(
    *,
    pane_command: str | None,
    screen_text: str | None = None,
) -> CliBackend:
    """Detect which CLI backend is running from tmux pane info.

    Priority:
    1. pane_command == "claude" → CLAUDE
    2. pane_command in {"node", "codex"} → check screen for Claude/Codex hints
    3. Screen content heuristics
    """
    cmd = (pane_command or "").strip().lower()

    # Direct binary match
    if cmd == "claude":
        return CliBackend.CLAUDE
    if cmd == "codex":
        return CliBackend.CODEX

    # "node" could be either Codex or Claude Code — check screen content
    if cmd == "node" and screen_text:
        if CLAUDE_STATUS_RE.search(screen_text):
            return CliBackend.CLAUDE
        if CODEX_STATUS_RE.search(screen_text):
            return CliBackend.CODEX
        # node but no recognizable status — default to codex (legacy)
        return CliBackend.CODEX

    if cmd == "node":
        return CliBackend.CODEX  # legacy default

    # Not a recognized CLI process
    if not cmd or cmd in {"bash", "zsh", "sh", "fish"}:
        # Check screen for hints in case CLI is running as a subprocess
        if screen_text:
            if CLAUDE_STATUS_RE.search(screen_text):
                return CliBackend.CLAUDE
            if CODEX_STATUS_RE.search(screen_text):
                return CliBackend.CODEX
        return CliBackend.UNKNOWN

    return CliBackend.UNKNOWN


# Claude Code session ID pattern — shorter numeric-ish IDs
CLAUDE_SESSION_ID_RE = re.compile(r"\b\d{5,8}\b")


def extract_claude_session_id(screen_text: str) -> str | None:
    """Try to extract a Claude Code session ID from tmux screen content."""
    # Claude Code shows session name in the status area
    # It could be a numeric ID or a user-given name
    matches = CLAUDE_SESSION_ID_RE.findall(screen_text)
    return matches[-1] if matches else None
