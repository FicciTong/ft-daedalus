# OpenCode Todo And LSP Pilot — 2026-04-08

## Scope

Bounded follow-up on the repo-local OpenCode harness:

- make todo discipline explicit in the primary OpenCode seats
- add repo-local LSP diagnostics without patching OpenCode core
- keep direct experimental `lsp` tool use repo-local and opt-in

## Landed Shape

- `opencode.json`
  - allows `todowrite`
  - allows `lsp`
  - keeps `harness-orchestrator` task use bounded to:
    - `harness-planner`
    - `harness-reviewer`
    - `harness-verifier`
  - keeps `harness-worker` task use denied by default
  - points `pyright` and `typescript` LSP entries at repo-local binaries under
    `.opencode/node_modules/`
- `.opencode/agents/harness-orchestrator.md`
  - now requires todo discipline for multi-step work
  - keeps local-complete-first posture
  - uses helper subagents only as narrow local assists
- `.opencode/agents/harness-worker.md`
  - now requires todo discipline for multi-step work when opened as the active
    primary seat
- `.opencode/package.json`
  - now carries repo-local LSP dependencies:
    - `pyright`
    - `typescript`
    - `typescript-language-server`
- `scripts/opencode-local.sh`
  - repo-local launcher that sets:
    - `OPENCODE_EXPERIMENTAL_LSP_TOOL=true`
  - keeps the experimental direct `lsp` tool opt-in instead of hidden global
    shell state

## Boundary

- no OpenCode upstream/core patch
- no dependence on `~/.config/opencode/`
- no sidecar daemon
- no requirement that ordinary `opencode` startup be replaced; plain startup
  should still get repo-local diagnostics from project config

## Validation

- `python3 -m json.tool opencode.json > /dev/null`
- `python3 -m json.tool .opencode/package.json > /dev/null`
- `python3 -m json.tool .opencode/harness.json > /dev/null`
- `bash -n scripts/opencode-local.sh`
- `python3 -m py_compile scripts/repo_harness.py scripts/opencode_harness.py`
- `node --check .opencode/plugins/repo_harness.js`
- `node --check .opencode/tools/verify_changed.js`
- `node --check .opencode/lib/run-harness.js`
- `uv run pytest -q tests/test_repo_harness.py`
- `npm install --prefix .opencode`
- `./scripts/opencode-local.sh agent list`
  - confirmed `harness-orchestrator` now exposes:
    - `todowrite: allow`
    - `lsp: allow`
    - `task *: deny`
    - helper allowlist for `harness-planner` / `harness-reviewer` /
      `harness-verifier`
- `./scripts/opencode-local.sh run --agent harness-orchestrator --format json ...`
  - confirmed the agent created and closed a todo list with `todowrite`
  - confirmed it used `repo_profile`
  - confirmed `has_repo_local_opencode_overlay: true`

## Official References

- OpenCode tools:
  - https://opencode.ai/docs/tools
- OpenCode agents:
  - https://opencode.ai/docs/agents/
- OpenCode LSP:
  - https://opencode.ai/docs/lsp/
- OpenCode plugins:
  - https://opencode.ai/docs/plugins/
