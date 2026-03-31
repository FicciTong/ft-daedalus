from __future__ import annotations

from daedalus_wechat.cli_backend import CliBackend, detect_backend


def test_detect_claude_by_command():
    assert detect_backend(pane_command="claude") == CliBackend.UNKNOWN


def test_detect_codex_by_command():
    assert detect_backend(pane_command="codex") == CliBackend.CODEX


def test_detect_node_defaults_to_codex():
    assert detect_backend(pane_command="node") == CliBackend.CODEX


def test_detect_node_with_claude_screen():
    screen = "some output\n╭─ Claude Code\nmodel: claude-opus"
    assert detect_backend(pane_command="node", screen_text=screen) == CliBackend.CODEX


def test_detect_node_with_codex_screen():
    screen = "gpt-4o · abc12345-1234-5678-9abc-def012345678"
    assert detect_backend(pane_command="node", screen_text=screen) == CliBackend.CODEX


def test_detect_unknown_for_bash():
    assert detect_backend(pane_command="bash") == CliBackend.UNKNOWN


def test_detect_bash_with_claude_screen():
    screen = "Claude Code ⏵⏵ bypass permissions on"
    assert detect_backend(pane_command="bash", screen_text=screen) == CliBackend.UNKNOWN


def test_detect_none_command():
    assert detect_backend(pane_command=None) == CliBackend.UNKNOWN


def test_detect_empty_command():
    assert detect_backend(pane_command="") == CliBackend.UNKNOWN
