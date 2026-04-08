# OpenCode GPT Handover — Harness Validation

Date: 2026-04-08
Owner: Codex
Target runtime: existing tmux OpenCode GPT session

Historical note:

- this handover reflects the validation posture at the moment it was issued
- the later canonical adoption posture is manual-only
- see `var/reports/opencode/opencode_harness_manual_adoption_posture_20260408.md`
  and `opencode-harness/MANUAL_ADOPTION.md`

## Objective

Validate the new reusable OpenCode harness framework that now lives in
`ft-daedalus`, without modifying OpenCode upstream and without moving the
canonical source back into `ft-cosmos`.

## Canonical Source

Work from these files:

- `/home/ft/dev/ft-cosmos/ft-daedalus/opencode-harness/README.md`
- `/home/ft/dev/ft-cosmos/ft-daedalus/opencode-harness/template/opencode.json`
- `/home/ft/dev/ft-cosmos/ft-daedalus/opencode-harness/template/.opencode/harness.json`
- `/home/ft/dev/ft-cosmos/ft-daedalus/opencode-harness/template/scripts/opencode_harness.py`
- `/home/ft/dev/ft-cosmos/ft-daedalus/opencode-harness/template/.opencode/plugins/repo_harness.js`
- `/home/ft/dev/ft-cosmos/ft-daedalus/scripts/install_opencode_harness.py`
- `/home/ft/dev/ft-cosmos/ft-daedalus/tests/test_install_opencode_harness.py`

## Boundary

- Do not modify OpenCode upstream/core.
- Do not move canonical harness source out of `ft-daedalus`.
- Do not open a new tmux session.
- Keep work bounded to validation, small fixes if needed, and evidence.
- Prefer the shortest truthful fix if validation reveals a real issue.

## What Codex Already Did

Codex has already:

- created the canonical reusable harness template under
  `ft-daedalus/opencode-harness/template/`
- added installer / sync / verify flow in
  `ft-daedalus/scripts/install_opencode_harness.py`
- made the installer merge target repo `opencode.json`,
  `.opencode/package.json`, and `.opencode/.gitignore` instead of clobbering
  them
- namespaced harness agents / commands to avoid collisions:
  - agents: `harness-orchestrator`, `harness-planner`, `harness-reviewer`,
    `harness-verifier`
  - commands: `/h-plan`, `/h-review`, `/h-verify`, `/h-repair`
- locally verified:
  - `uv run pytest -q tests/test_install_opencode_harness.py`
  - `python3 -m py_compile scripts/install_opencode_harness.py opencode-harness/template/scripts/opencode_harness.py`
  - `node --check ...`
  - one fresh-target install
  - one broken-file then `sync` recovery
  - target-side `verify`

## Your Task

Run an independent OpenCode-side validation in the existing session.

### Step 1

Read the canonical files listed above.

### Step 2

Create a fresh temp git repo and install the harness into it:

```bash
tmpdir=$(mktemp -d)
mkdir -p "$tmpdir/target"
cd "$tmpdir/target"
git init
printf '# temp repo\n' > README.md
cat > opencode.json <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "instructions": ["AGENTS.md", "docs/LOCAL.md"],
  "default_agent": "build",
  "mcp": {
    "custom": {"type": "local", "enabled": true}
  }
}
EOF
mkdir -p .opencode
cat > .opencode/package.json <<'EOF'
{
  "dependencies": {
    "left-pad": "1.3.0"
  }
}
EOF
printf 'custom-cache/\n' > .opencode/.gitignore
python3 /home/ft/dev/ft-cosmos/ft-daedalus/scripts/install_opencode_harness.py install "$tmpdir/target"
```

### Step 3

Validate these properties:

- target `opencode.json` preserved its original `default_agent`
- target `mcp.custom` remained intact
- target `instructions` gained `docs/OPENCODE_HARNESS_OVERLAY.md`
- target `.opencode/package.json` preserved `left-pad` and gained
  `@opencode-ai/plugin`
- target `.opencode/.gitignore` preserved `custom-cache/` and gained `.state/`
- target `default_agent` was not silently rewritten to the harness default
- harness files landed at the expected paths

### Step 4

Break one managed file and verify `sync` repairs it:

```bash
printf 'broken\n' > "$tmpdir/target/.opencode/plugins/repo_harness.js"
python3 /home/ft/dev/ft-cosmos/ft-daedalus/scripts/install_opencode_harness.py sync --skip-deps "$tmpdir/target"
python3 /home/ft/dev/ft-cosmos/ft-daedalus/scripts/install_opencode_harness.py verify "$tmpdir/target"
```

### Step 5

If you find a real issue, fix it in `ft-daedalus` directly, run the smallest
truthful checks again, then continue the validation.

## Deliverable

Write a concise validation report to:

- `/home/ft/dev/ft-cosmos/ft-daedalus/var/reports/opencode/opencode_gpt_validation_20260408.md`

The report must include:

- verdict
- commands actually run
- what passed
- any failure found and fix applied
- residual risk, if any

## Done When

Done only when one of these is true:

1. validation fully passes and the report is written
2. a real blocker is found, evidence is written, and the blocker is explicit
