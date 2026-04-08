# OpenCode Harness Overlay

Repo-local OpenCode harness overlay for this repository.

This overlay exists to improve OpenCode behavior **without** patching OpenCode
upstream.

`docs/AGENT_TOOL_RUNTIME_NOTES.md` remains an on-demand reference note, not a
default startup payload.

This file is meant to be adopted into a target repo by manual review and manual
patching. `ft-daedalus` keeps the canonical source, but the target repo owns
its final merged copy.

## Design Rules

- Do **not** modify OpenCode core.
- Keep durable overlay source repo-local:
  - `opencode.json`
  - `.opencode/`
  - `docs/OPENCODE_HARNESS_OVERLAY.md`
  - `scripts/repo_harness.py`
- Keep machine-local scratch only in `.opencode/.state/`.
- If a new machine pulls this repo and launches `opencode` from the repo root,
  the overlay should work without hand-editing `~/.config/opencode/`.

## Harness Surface

The harness uses namespaced agent and command names so it does not silently
take over common repo-local names such as `planner` or `/verify`.

It adds:

- one default automatic harness seat:
  - `harness-orchestrator`
- one additional selectable implementation seat:
  - `harness-worker`
- repo-local subagents:
  - `harness-planner`
  - `harness-reviewer`
  - `harness-verifier`
- repo-local commands:
  - `/h-plan`
  - `/h-review`
  - `/h-verify`
  - `/h-repair`
- repo-local custom tools:
  - `repo_profile`
  - `related_context`
  - `affected_tests`
  - `verify_changed`
- shared helper:
  - `scripts/repo_harness.py`
- one repo-local plugin:
  - `repo_harness`
  - tracks changed files + verifier runs for compaction
- one repo-local launcher for experimental direct LSP use:
  - `scripts/opencode-local.sh`

## Verification Doctrine

- the user should not need to type harness commands for normal use
- the default agent should automatically gather repo context and run the
  smallest truthful verifier path when needed
- routine answers should stay concise by default; expand only when the owner
  explicitly asks for depth
- multi-step work should maintain a live todo list:
  - `harness-orchestrator` owns the todo list by default
  - `harness-worker` should also keep todo current when it is opened as a
    primary implementation seat
- `related_context` is a first-hop seed, not a hard boundary:
  - if seed reading reveals a new authority doc, work plan, import neighbor,
    runtime dependency, or cross-repo runbook, rerun it with that path before
    continuing
  - do not treat authority candidates as mandatory reads for every bounded task
- `harness-orchestrator` is the owner-facing control seat:
  - it defaults to completing the bounded task locally
  - it may implement directly when no separate worker is active
  - it may use local helper subagents for plan/review/verify assists
  - it may keep orchestration and use worker seats only when the owner
    explicitly asks for extra delegated execution
- `harness-worker` is the implementation seat itself
- repo-local LSP posture:
  - `opencode.json` points OpenCode at repo-local `pyright` and
    `typescript-language-server` binaries under `.opencode/node_modules/`
  - normal `opencode` startup should now get repo-local LSP diagnostics without
    editing home-dir config
  - direct experimental `lsp` tool usage remains opt-in through
    `scripts/opencode-local.sh`, which sets
    `OPENCODE_EXPERIMENTAL_LSP_TOOL=true` before launch
- prefer targeted checks before broad checks
- do not jump to repo-wide verification if `verify_changed` returns a smaller
  truthful DAG
- treat verifier output as the fact source, not model explanation
- token-budget governance is continuous:
  - periodically re-audit startup payload, context breadth, watcher noise, and
    compaction summaries

## Boundary

This overlay does **not** add:

- a sidecar daemon
- global home-dir config dependency
- repo-external network services
