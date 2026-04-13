from __future__ import annotations

from unittest.mock import patch

from daedalus_wechat.cli_backend import CliBackend, detect_backend


def test_detect_claude_by_command():
    assert detect_backend(pane_command="claude") == CliBackend.CLAUDE


def test_detect_codex_by_command():
    assert detect_backend(pane_command="codex") == CliBackend.CODEX


def test_detect_opencode_by_command():
    assert detect_backend(pane_command="opencode") == CliBackend.OPENCODE


def test_detect_node_without_hints_is_unknown():
    assert detect_backend(pane_command="node") == CliBackend.UNKNOWN


def test_detect_node_prefers_visible_runtime_over_stale_start_command():
    screen = "OpenCode\nBuild GPT-5.4 OpenAI · xhigh\nAsk anything"
    assert (
        detect_backend(
            pane_command="node",
            pane_start_command="codex resume 123 -C /tmp --no-alt-screen",
            screen_text=screen,
        )
        == CliBackend.OPENCODE
    )


def test_detect_node_prefers_opencode_start_command():
    assert (
        detect_backend(
            pane_command="node",
            pane_start_command="opencode /tmp",
        )
        == CliBackend.OPENCODE
    )


def test_detect_node_with_claude_screen():
    screen = "some output\n╭─ Claude Code\nmodel: claude-opus"
    assert detect_backend(pane_command="node", screen_text=screen) == CliBackend.CLAUDE


def test_detect_node_with_codex_screen():
    screen = "gpt-4o · abc12345-1234-5678-9abc-def012345678"
    assert detect_backend(pane_command="node", screen_text=screen) == CliBackend.CODEX


def test_detect_node_with_opencode_screen():
    screen = "OpenCode\nBuild GPT-5.4 OpenAI · xhigh\nAsk anything"
    assert (
        detect_backend(pane_command="node", screen_text=screen) == CliBackend.OPENCODE
    )


def test_detect_node_prefers_child_process_backend_over_stale_screen_hints():
    screen = "OpenCode\nBuild GPT-5.4 OpenAI · xhigh\nAsk anything"
    with patch(
        "daedalus_wechat.cli_backend._detect_backend_from_proc",
        return_value=CliBackend.CODEX,
    ):
        assert (
            detect_backend(
                pane_command="node",
                screen_text=screen,
                pane_pid=1234,
            )
            == CliBackend.CODEX
        )


def test_detect_unknown_for_bash():
    assert detect_backend(pane_command="bash") == CliBackend.UNKNOWN


def test_detect_bash_with_stale_claude_screen_is_unknown():
    screen = "Claude Code ⏵⏵ bypass permissions on"
    assert detect_backend(pane_command="bash", screen_text=screen) == CliBackend.UNKNOWN


def test_detect_bash_with_stale_opencode_screen_is_unknown():
    screen = "OpenCode\nBuild GPT-5.4 OpenAI · xhigh\nAsk anything"
    assert (
        detect_backend(pane_command="bash", screen_text=screen) == CliBackend.UNKNOWN
    )


def test_detect_bash_uses_child_process_backend_when_screen_is_empty():
    with patch(
        "daedalus_wechat.cli_backend._detect_backend_from_proc",
        return_value=CliBackend.CODEX,
    ):
        assert (
            detect_backend(pane_command="bash", pane_pid=1234) == CliBackend.CODEX
        )


def test_detect_none_command():
    assert detect_backend(pane_command=None) == CliBackend.UNKNOWN


def test_detect_empty_command():
    assert detect_backend(pane_command="") == CliBackend.UNKNOWN
