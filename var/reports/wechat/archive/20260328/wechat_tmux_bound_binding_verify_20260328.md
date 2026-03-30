# WeChat tmux-bound binding verification — 2026-03-28

## Scope

Verify that the WeChat bridge is now owner-facing **tmux-bound, thread-aware**
instead of purely thread-bound.

## Code surface

- `src/daedalus_wechat/daemon.py`
- `src/daedalus_wechat/live_session.py`
- `src/daedalus_wechat/state.py`
- `tests/test_daemon.py`

## What changed

1. `BridgeState` now persists `active_tmux_session`.
2. Runtime selection prefers `active_tmux_session`, then falls back to
   `active_session_id`.
3. `/switch` now updates both:
   - `active_session_id`
   - `active_tmux_session`
4. `/status`, `/sessions`, `/health`, mirror resolution, and `/queue` now read
   the active binding through tmux-first semantics.
5. Queue visibility remains one shared owner-facing outbox, but active markers
   now reflect the active tmux binding.

## Verification

### Automated

- `PYTHONPATH=src uv run pytest -q tests/test_daemon.py tests/test_live_session.py tests/test_wechat_api.py`
  - result: `48 passed`
- `uv run --with ruff ruff check src tests`
  - result: `All checks passed!`
- `python -m compileall src`
  - result: success

### Runtime

- `systemctl --user restart daedalus-wechat.service`
- `systemctl --user is-active daedalus-wechat.service`
  - result: `active`

### Live runtime inventory

Observed from the real workspace runtime:

- state active thread: `019d332d-1bc8-7151-a874-ab0fbc493747`
- state active tmux: `codex`
- current runtime tmux: `codex`
- current runtime thread: `019d332d-1bc8-7151-a874-ab0fbc493747`

Inventory:

- `codex` | `switchable=True` | `reason=live`
- `wechat` | `switchable=True` | `reason=live`
- `openclaw` | `switchable=False` | `reason=outside-workspace`

### Live owner-facing output

`/sessions` equivalent:

```text
sessions=2
*1 codex | 019d332d | codex live
 2 attached-last | 019cdfe5 | wechat live
excluded=1
x openclaw | outside-workspace
use=/switch 1
```

Current `/queue` equivalent:

```text
queue=61
oldest_age_s=461
stuck_ge_120s=13
wait=next-wechat-message
active_tmux=codex
final=2
plan=8
progress=51
threads=2
thread[1]=*codex|019d332d|count=20
thread[2]=attached-last|019cdfe5|count=41
```

## Interpretation

- Owner-facing active binding now stays on the chosen tmux session.
- If the live thread under that tmux changes, the bridge follows it internally
  without changing the owner-facing live session identity.
- Excluded tmux sessions are still shown honestly as excluded, not silently
  hidden.
- Shared outbox backlog is now visibly broken out by thread/session, so cross-
  session pending messages are observable instead of silently blending together.

## Boundary

- This does **not** create per-session physical outboxes.
- The bridge still has one shared owner-facing outbox per WeChat binding.
- The fix is about:
  - active binding identity
  - session switching semantics
  - queue observability
  - mirror/runtime selection
