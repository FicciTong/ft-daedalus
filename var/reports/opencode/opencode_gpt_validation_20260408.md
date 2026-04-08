# OpenCode GPT Validation 2026-04-08

Historical note:

- this validation captured the earlier installer-based validation cut
- the later canonical adoption posture is manual-only
- see `var/reports/opencode/opencode_harness_manual_adoption_posture_20260408.md`
  and `opencode-harness/MANUAL_ADOPTION.md`

## Verdict

- PASS
- The reusable OpenCode harness overlay validated cleanly in an independent fresh-target install.
- No real issue was found, so no code change was needed.

## Commands Actually Run

```bash
tmpdir=$(mktemp -d)
mkdir -p "$tmpdir/target"
git -C "$tmpdir/target" init
printf '# temp repo\n' > "$tmpdir/target/README.md"
cat > "$tmpdir/target/opencode.json" <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "instructions": ["AGENTS.md", "docs/LOCAL.md"],
  "default_agent": "build",
  "mcp": {
    "custom": {"type": "local", "enabled": true}
  }
}
EOF
mkdir -p "$tmpdir/target/.opencode"
cat > "$tmpdir/target/.opencode/package.json" <<'EOF'
{
  "dependencies": {
    "left-pad": "1.3.0"
  }
}
EOF
printf 'custom-cache/\n' > "$tmpdir/target/.opencode/.gitignore"
python3 /home/ft/dev/ft-cosmos/ft-daedalus/scripts/install_opencode_harness.py install "$tmpdir/target"

printf 'broken\n' > "$tmpdir/target/.opencode/plugins/repo_harness.js"
python3 /home/ft/dev/ft-cosmos/ft-daedalus/scripts/install_opencode_harness.py sync --skip-deps "$tmpdir/target"
python3 /home/ft/dev/ft-cosmos/ft-daedalus/scripts/install_opencode_harness.py verify "$tmpdir/target"

python3 -m json.tool "$tmpdir/target/opencode.json" >/dev/null
python3 -m py_compile "$tmpdir/target/scripts/opencode_harness.py"
node --check "$tmpdir/target/.opencode/plugins/repo_harness.js"
node --check "$tmpdir/target/.opencode/tools/verify_changed.js"
```

## What Passed

Fresh install preserved target-owned fields while adding the harness overlay:

- target `opencode.json` preserved original `default_agent = "build"`
- target `mcp.custom` remained intact
- target `instructions` gained `docs/OPENCODE_HARNESS_OVERLAY.md`
- target `.opencode/package.json` preserved `left-pad` and gained `@opencode-ai/plugin`
- target `.opencode/.gitignore` preserved `custom-cache/` and gained `.state/`
- target `default_agent` was not silently rewritten to the harness default
- expected harness files landed at the managed overlay paths

Managed-file repair also passed:

- after intentionally breaking `.opencode/plugins/repo_harness.js`
- `sync --skip-deps` restored the canonical template copy
- `verify` returned `ok: True`

Smallest truthful checks also passed:

- `python3 -m json.tool opencode.json`
- `python3 -m py_compile scripts/opencode_harness.py`
- `node --check .opencode/plugins/repo_harness.js`
- `node --check .opencode/tools/verify_changed.js`

## Failure Found / Fix Applied

- None.
- No code changes were required.

## Residual Risk

- The validation covered the installer/merge/sync/verify contract against a fresh temp git repo.
- It did not validate every possible pre-existing target repo layout or every third-party npm resolution edge case.
- The current evidence is sufficient to treat the harness installer as passing its intended bounded contract.
