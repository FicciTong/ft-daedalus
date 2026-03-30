# WeChat recent tmux-scope verify — 2026-03-28

## Objective
Make `/recent` owner-facing session aware so it no longer silently mixes all live sessions by default.

## Changes landed
- delivery ledger now persists `tmux_session`
- `/recent` defaults to the current `active_tmux_session`
- `/recent all` explicitly requests the mixed global view
- backward-compatible fallback:
  - if the current ledger slice has only older unscoped records, `/recent` falls back to `scope=all-fallback`
  - this avoids a false empty view during migration from old ledger rows

## Verification
- Targeted tests:
  - `PYTHONPATH=src uv run pytest -q tests/test_daemon.py tests/test_cli.py tests/test_live_session.py`
  - result: `56 passed`
- Bytecode:
  - `PYTHONPATH=src python -m compileall src`
  - result: success
- User service:
  - `systemctl --user restart daedalus-wechat.service`
  - result: `active`
- Live state snapshot:
  - `active_tmux = daedalus`
  - `pending = 1`
- Live queue rendering:
  - `visible_now=0`
  - `waiting_other_sessions=1`
  - `session[1]=codex|count=1|threads=1`
- Live `/recent` rendering at capture time:
  - `scope=all-fallback`
  - meaning: current ledger rows for that view were still older unscoped records, so the bridge truthfully exposed fallback instead of returning a misleading empty result

## Boundary
This does not create separate delivery ledgers per tmux session.
It keeps one ledger, but owner-facing reads are now session-aware by default and only mix globally when explicitly requested or when old unscoped rows force truthful fallback.
