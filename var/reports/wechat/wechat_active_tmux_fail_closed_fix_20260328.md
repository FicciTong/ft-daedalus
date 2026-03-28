# WeChat active tmux fail-closed fix — 2026-03-28

## Symptom

Owner switched the WeChat bridge to `daedalus`, but a later plain WeChat
message was submitted into `codex`.

## Runtime evidence

Observed in the live event log:

- `2026-03-28T07:20:54Z` incoming `/switch daedalus`
- immediate owner-facing reply confirmed:
  - `tmux=daedalus`
  - `thread=019cdfe5-fa14-74a3-aa31-5451128ea58d`
- `2026-03-28T07:21:51Z` later incoming plain message was recorded as:
  - `prompt_submitted`
  - `thread=019d332d-1bc8-7151-a874-ab0fbc493747`
  - which is the `codex` tmux thread

So the owner-facing switch reply succeeded, but the later prompt still routed to
the canonical `codex` runtime.

## Root cause

Two behaviors together made this possible:

1. `current_runtime_status(...)` preferred only the list of **switchable live**
   sessions.
2. If the selected active tmux was temporarily not switchable, runtime selection
   silently fell back to canonical `codex`.
3. Mirror resolution also fell back to the old `active_session_id`, which could
   keep reinforcing the wrong thread.

That made the system ambiguous:

- owner-facing active identity said `daedalus`
- runtime fallback could still route work to `codex`

## Fix

### tmux-bound runtime selection

If `active_tmux_session` is set, runtime selection now resolves via the raw tmux
status for that exact tmux, not only through the switchable-live shortlist.

This means:

- the selected tmux keeps its owner-facing identity
- if it is degraded, the bridge now reports that degradation truthfully
- it does **not** silently jump back to `codex`

### fail-closed mirror resolution

If the selected active tmux exists but currently has no live thread, mirror
resolution now returns `None` instead of falling back to the old thread.

This avoids routing/mirroring old-thread output under the wrong active tmux.

## Added tests

- plain message follows selected active tmux
- status fails closed on selected tmux with no thread
- mirror thread lookup does not fall back to the old thread when selected tmux
  has no thread

## Verification

- `PYTHONPATH=src uv run pytest -q tests/test_daemon.py tests/test_live_session.py tests/test_wechat_api.py`
  - result: `51 passed`
- `uv run --with ruff ruff check src tests`
  - result: passed

## Boundary after fix

- This does **not** create separate physical queues per tmux session.
- Shared pending outbox semantics remain unchanged.
- The fix only ensures:
  - owner-facing active binding is tmux-bound
  - prompt routing does not silently revert to `codex`
  - degraded selected tmux states fail closed instead of falling back
