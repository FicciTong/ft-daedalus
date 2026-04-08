# OpenCode Harness Overlay

Repo-local OpenCode harness overlay for this repository.

This overlay exists to improve OpenCode behavior **without** patching OpenCode
upstream.

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

## Verification Doctrine

- the user should not need to type harness commands for normal use
- the default agent should automatically gather repo context and run the
  smallest truthful verifier path when needed
- `harness-orchestrator` is the owner-facing control seat:
  - it may implement directly when no separate worker is active
  - it may keep orchestration and use worker seats when they exist
- `harness-worker` is the implementation seat itself
- prefer targeted checks before broad checks
- do not jump to repo-wide verification if `verify_changed` returns a smaller
  truthful DAG
- treat verifier output as the fact source, not model explanation

## Boundary

This overlay does **not** add:

- a sidecar daemon
- global home-dir config dependency
- repo-external network services
