## OpenCode Harness

This directory is the canonical `ft-daedalus` home for the **repo-local
coding-agent harness runbook** and the **OpenCode adapter seed**.

Current final boundary:

- `ft-daedalus` keeps:
  - manual adoption truth
  - adapter seed files
  - evidence
- the **target repo** keeps:
  - live repo-local config
  - live runtime adapters
  - the live shared helper

So `ft-daedalus` is **not** a runtime dependency for target repos.

## Current Posture

The canonical adoption path is **manual**, not script-driven.

- target repos are patched by hand, file by file, after review
- no installer script is the default or trusted path for changing an owner repo
- no target repo should depend on `ft-daedalus` at runtime

This keeps control in the reviewer/orchestrator seat and avoids script-shaped
risk against owner repos.

## Runtime Boundary

The current organism posture is:

- `AGENTS.md` = shared authority across coding agents
- target repo live helper = `scripts/repo_harness.py`
- OpenCode adapter = `opencode.json` + `.opencode/*`
- Claude adapter = `CLAUDE.md` + `.claude/*`
- Codex adapter = `.codex/*`

Seat semantics should stay aligned across runtimes when the runtime supports
them:

- `harness-orchestrator`
- `harness-worker`
- helper modes:
  - `harness-planner`
  - `harness-reviewer`
  - `harness-verifier`

Current capability note:

- OpenCode supports selectable repo-local agents directly
- Claude Code supports project agents directly
- Codex currently uses profiles/skills instead of the same explicit agent menu
- OpenCode seed now also carries:
  - default todo discipline for multi-step work
  - repo-local LSP diagnostics
  - an opt-in repo launcher for the experimental direct `lsp` tool

## What Lives Here

OpenCode adapter seed files live under:

- `opencode-harness/template/opencode.json`
- `opencode-harness/template/.opencode/`
- `opencode-harness/template/docs/OPENCODE_HARNESS_OVERLAY.md`
- `opencode-harness/template/scripts/opencode-local.sh`
- `opencode-harness/template/scripts/opencode_harness.py`

These seed files are for **manual reference and bounded reuse**, not for
declaring `ft-daedalus` as the live source of a target repo's merged copy.

Detailed adoption truth lives in:

- `opencode-harness/MANUAL_ADOPTION.md`

Historical and closeout evidence lives under:

- `var/reports/opencode/`
