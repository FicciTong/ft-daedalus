# Coding-Agent Harness Closeout 2026-04-08

## Final Boundary

This closeout records the final boundary for the current repo-local coding-agent
harness posture.

- `ft-daedalus` keeps:
  - runbook truth
  - OpenCode adapter seed files
  - evidence
- target repos keep:
  - live repo-local config
  - live runtime adapters
  - the live shared helper

`ft-daedalus` is therefore **not** a live runtime dependency for the target
repo.

## Shared Posture

Shared authority:

- `AGENTS.md`

Shared live helper in the target repo:

- `scripts/repo_harness.py`

Role semantics to keep aligned across runtimes when supported:

- `harness-orchestrator`
- `harness-worker`
- helper modes:
  - `harness-planner`
  - `harness-reviewer`
  - `harness-verifier`

## Runtime Adapters

OpenCode:

- repo-local `opencode.json`
- repo-local `.opencode/*`
- explicit selectable seats supported

Claude:

- repo-local `CLAUDE.md`
- repo-local `.claude/*`
- project agents supported

Codex:

- repo-local `.codex/*`
- same role semantics, but current CLI uses thin config/skill adapters instead
  of the same explicit agent-selection UX

## Adoption Rule

- patch target repos manually
- do not use auto-installer posture against owner repos
- do not let runtime adapters regrow a second rulebook
- keep runtime-specific layers thin

## Canonical References

- `opencode-harness/README.md`
- `opencode-harness/MANUAL_ADOPTION.md`
- `var/reports/opencode/opencode_harness_manual_adoption_posture_20260408.md`
