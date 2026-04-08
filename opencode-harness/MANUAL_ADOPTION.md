# Manual Coding-Agent Harness Adoption

This document is the `ft-daedalus` runbook for adopting the narrow **OpenCode
adapter seed** into another repository.

Global cross-runtime harness/token governance is canonical in `ft-cosmos`, not
in this repo.

The current runbook records:

- the OpenCode adapter seed
- the final boundary between `ft-daedalus` and the target repo
- the rule that live runtime adapters stay repo-local in the target repo

## Rules

- Do not modify OpenCode upstream/core.
- Do not treat `ft-daedalus` as a live runtime dependency of the target repo.
- Do not rely on global `~/.config/opencode/` behavior for canonical repo
  behavior.
- Do not run an auto-installer against an owner repo as the default path.
- Patch the target repo by hand.
- Review every changed file before commit.

Shared cross-runtime rules:

- keep `AGENTS.md` as the shared authority where possible
- keep the live shared helper in the target repo:
  - `scripts/repo_harness.py`
- keep runtime-specific adapter files in the target repo:
  - OpenCode: `opencode.json` + `.opencode/*`
  - Claude: `CLAUDE.md` + `.claude/*`
  - Codex: `.codex/*`

## OpenCode Seed Source

For OpenCode adoption, copy or merge only from these seed template paths as
needed:

- `opencode-harness/template/opencode.json`
- `opencode-harness/template/.opencode/.gitignore`
- `opencode-harness/template/.opencode/harness.json`
- `opencode-harness/template/.opencode/package.json`
- `opencode-harness/template/.opencode/package-lock.json`
- `opencode-harness/template/.opencode/agents/harness-orchestrator.md`
- `opencode-harness/template/.opencode/agents/harness-worker.md`
- `opencode-harness/template/.opencode/agents/harness-planner.md`
- `opencode-harness/template/.opencode/agents/harness-reviewer.md`
- `opencode-harness/template/.opencode/agents/harness-verifier.md`
- `opencode-harness/template/.opencode/commands/h-plan.md`
- `opencode-harness/template/.opencode/commands/h-review.md`
- `opencode-harness/template/.opencode/commands/h-verify.md`
- `opencode-harness/template/.opencode/commands/h-repair.md`
- `opencode-harness/template/.opencode/lib/run-harness.js`
- `opencode-harness/template/.opencode/plugins/repo_harness.js`
- `opencode-harness/template/.opencode/tools/repo_profile.js`
- `opencode-harness/template/.opencode/tools/related_context.js`
- `opencode-harness/template/.opencode/tools/affected_tests.js`
- `opencode-harness/template/.opencode/tools/verify_changed.js`
- `opencode-harness/template/docs/OPENCODE_HARNESS_OVERLAY.md`
- `opencode-harness/template/scripts/opencode-local.sh`

Do **not** treat the template script path as the target repo's final live
helper contract. The target repo's live shared helper should use the final
repo-local name:

- `scripts/repo_harness.py`

## Target Repo Files

After manual adoption, the target repo should contain the runtime-specific files
it actually uses.

### Shared Target-Repo Files

- `AGENTS.md`
- `scripts/repo_harness.py`

### OpenCode

- `opencode.json`
- `.opencode/.gitignore`
- `.opencode/harness.json`
- `.opencode/package.json`
- `.opencode/package-lock.json`
- `.opencode/agents/harness-orchestrator.md`
- `.opencode/agents/harness-worker.md`
- `.opencode/agents/harness-planner.md`
- `.opencode/agents/harness-reviewer.md`
- `.opencode/agents/harness-verifier.md`
- `.opencode/commands/h-plan.md`
- `.opencode/commands/h-review.md`
- `.opencode/commands/h-verify.md`
- `.opencode/commands/h-repair.md`
- `.opencode/lib/run-harness.js`
- `.opencode/plugins/repo_harness.js`
- `.opencode/skills/README.md`
- `.opencode/skills/repo-harness/SKILL.md`
- `.opencode/tools/repo_profile.js`
- `.opencode/tools/related_context.js`
- `.opencode/tools/affected_tests.js`
- `.opencode/tools/verify_changed.js`
- `docs/OPENCODE_HARNESS_OVERLAY.md`
- `scripts/opencode-local.sh`

### Claude

- `CLAUDE.md`
- `.claude/settings.json`
- `.claude/agents/harness-orchestrator.md`
- `.claude/agents/harness-worker.md`
- `.claude/agents/harness-planner.md`
- `.claude/agents/harness-reviewer.md`
- `.claude/agents/harness-verifier.md`

### Codex

- `.codex/config.toml`
- `.codex/skills/repo-harness/SKILL.md`

## OpenCode Merge Rules

Do not blindly replace these files if the target repo already has them.

### `opencode.json`

Keep the target repo's existing:

- `instructions`
- `default_agent`
- `mcp`
- `compaction`
- `watcher`
- any other repo-owned settings

Add or merge only the harness-required pieces:

- ensure `docs/OPENCODE_HARNESS_OVERLAY.md` is included in `instructions`
- ensure `permission` allows:
  - `todowrite`
  - `lsp`
- ensure `harness-orchestrator` task permissions allow only:
  - `harness-planner`
  - `harness-reviewer`
  - `harness-verifier`
  while denying `*` by default
- ensure `harness-worker` task permission denies `*`
- ensure repo-local `lsp` points at `.opencode/node_modules/.bin/` language
  servers
- ensure watcher ignore includes:
  - `**/.git/**`
  - `**/.venv/**`
  - `**/node_modules/**`
  - `**/__pycache__/**`
  - `**/.pytest_cache/**`
  - `**/.ruff_cache/**`
  - `**/.mypy_cache/**`
  - `**/.cache/**`
  - `**/.next/**`
  - `**/.turbo/**`
  - `**/dist/**`
  - `**/build/**`
  - `**/coverage/**`
  - `**/*.pyc`

Do not silently rewrite the target repo's `default_agent`.

### `.opencode/package.json`

Keep any repo-owned dependencies.

Ensure:

- `"type": "module"`
- dependency `"@opencode-ai/plugin": "1.4.0"`
- dependency `"pyright": "^1.1.408"`
- dependency `"typescript": "^6.0.2"`
- dependency `"typescript-language-server": "^5.1.3"`

### `.opencode/.gitignore`

Keep repo-owned ignore lines.

Ensure:

- `.state/`

### `.opencode/package-lock.json`

If the target repo has no `.opencode/package-lock.json`, copy the canonical one
from the template.

If the target repo already has one, review manually before replacing it.

## Claude / Codex Merge Rules

Keep Claude/Codex adapters **thin**.

### `CLAUDE.md`

Keep it Claude-specific and thin:

- Claude-specific startup / posture notes only
- import or reference `AGENTS.md`
- do not copy the whole shared rulebook again

### `.claude/agents/*`

Keep seat semantics aligned with OpenCode when Claude supports them:

- `harness-orchestrator`
- `harness-worker`
- helper modes:
  - `harness-planner`
  - `harness-reviewer`
  - `harness-verifier`

### `.codex/*`

Keep Codex aligned in **role semantics**, but do not fake unsupported UX.

Current truthful posture:

- Codex uses shared authority + shared helper + thin local skills/config
- do not pretend Codex has the same explicit agent-selection UX if the CLI
  does not expose it

## What To Commit

Commit the runtime-specific repo-local adapter files and the shared helper that
the target repo actually uses.

Typical live commit set:

- `scripts/repo_harness.py`
- OpenCode adapter files under `.opencode/*` and `opencode.json`
- Claude adapter files under `CLAUDE.md` and `.claude/*`
- Codex adapter files under `.codex/*`

Do not commit:

- `.opencode/.state/`
- `.opencode/node_modules/`
- `.opencode/bun.lock`
- cache files
- temporary validation repos

## Manual Verification

From the target repo root, run:

```bash
python3 -m json.tool opencode.json >/dev/null
python3 -m json.tool .opencode/package.json >/dev/null
python3 -m json.tool .opencode/harness.json >/dev/null
python3 -m py_compile scripts/repo_harness.py
node --check .opencode/plugins/repo_harness.js
node --check .opencode/tools/verify_changed.js
bash -n scripts/opencode-local.sh
uv run pytest -q tests/test_repo_harness.py
```

Also manually confirm:

- `instructions` still include the target repo's prior entries
- `default_agent` was not overwritten unless you intentionally changed it
- target repo `mcp` config still exists
- target repo `.opencode/package.json` still includes any prior dependencies
- target repo `.opencode/.gitignore` still includes any prior ignore lines
- `CLAUDE.md` stays thin and points to shared repo truth instead of copying it
- `.codex/*` stays a thin adapter instead of a second rulebook

## Runtime Activation

After the target repo is patched and committed, activate the runtime from the
repo root.

### OpenCode

1. enter that repo root in the tmux session's shell
2. start or resume OpenCode from that repo root
3. confirm OpenCode is now loading the repo-local `opencode.json` and
   `.opencode/`
4. if direct experimental `lsp` tool use is desired, launch through:
   - `scripts/opencode-local.sh`

### Claude

- start Claude from the target repo root
- use the repo-local `CLAUDE.md`
- when needed, explicitly choose:
  - `harness-orchestrator`
  - `harness-worker`

### Codex

- start Codex from the target repo root
- rely on the repo-local `.codex/config.toml`
- rely on `AGENTS.md` + `scripts/repo_harness.py` + thin Codex skills/config

The harness is not active just because files exist in `ft-daedalus`.
It becomes active only when the **target repo itself** contains the repo-local
adapter files and the runtime is started from that repo.

## Review Standard

Before calling the target repo adoption complete, confirm:

- the change stayed bounded to repo-local coding-agent adapter files
- no business logic was changed by the harness patch itself
- the target repo still owns its own runtime settings
- the target repo can be cloned on a new machine and still carry this overlay
