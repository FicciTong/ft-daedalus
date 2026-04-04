## 2026-04-04 — OpenCode reply scope recovery

### Scope

Bounded follow-up slice after the initial Codex/OpenCode runtime isolation repair.

This slice stayed inside:

- `daedalus-wechat` service restoration
- `desktop-mirror` session scoping
- stale final behavior after `/switch`
- OpenCode-side owner-facing reply delivery

This slice did **not** widen into:

- full OpenCode orchestrator cutover
- Claude runtime adaptation
- governance/model changes

### Exact live symptom driving this slice

Key live ledger truth from `/home/ft/.local/state/daedalus-wechat/deliveries.jsonl`:

- `seq 50475` at `03:14:22Z`
  - `origin=wechat-command`
  - `thread=ses_2a9b...`
  - `tmux_session=opencode`
  - owner had switched to OpenCode
- `seq 50476` at `03:14:40Z`
  - `origin=wechat-prompt-submitted`
  - `thread=ses_2a9b...`
  - `tmux_session=opencode`
  - OpenCode prompt injection ack
- `seq 50485` at `03:30:59Z`
  - `origin=wechat-command`
  - `thread=ses_2a9b...`
  - `tmux_session=opencode`
  - owner had switched to OpenCode again
- `seq 50486` at `03:31:05Z`
  - `origin=desktop-mirror`
  - `thread=019d332d...`
  - `tmux_session=codex`
  - text began `我看过了，结论是...`

Interpretation:

- owner-facing `switch -> reply` experience was misleading
- the reply delivered after `/switch opencode` was a delayed Codex final
- OpenCode-side replies were still not truthfully mirrored back

So the problem was two-layered:

1. OpenCode final mirror was still missing
2. stale Codex desktop-mirror final could still surface after owner switched to OpenCode

### Root-cause read

The stale cross-session leak was not a runtime-detection problem anymore.
It was a mirror delivery scoping problem.

Two concrete gaps were fixed in code:

1. `desktop-mirror` delivery did not re-check active thread/tmux scope after scan
   collection, so a Codex final that completed just after `/switch opencode`
   could still be sent to WeChat as if it belonged to the new OpenCode context.
2. `_bind_peer()` reset the active mirror cursor too aggressively on same-user
   rebinding, which risks discarding not-yet-mirrored output when the owner sends
   follow-up messages/images in the same chat.

### Landed code changes

- `src/daedalus_wechat/daemon.py`
  - `desktop-mirror` now re-validates active thread/tmux scope before advancing
    mirror offsets and before emitting progress/final delivery
  - same-user rebinding no longer resets the active mirror cursor just because
    the context token refreshed

### Added tests

- `test_bind_peer_same_user_rebind_preserves_cursor`
- `test_mirror_does_not_leak_stale_final_after_switch`

### Verification

Focused daemon tests:

- `cd ft-daedalus && uv run pytest -q tests/test_daemon.py`
- result: `77 passed`

Full test suite:

- `cd ft-daedalus && uv run pytest -q`
- result: `133 passed`

Lint:

- `cd ft-daedalus && uv run ruff check src tests`
- result: pass

Live service restore:

- `systemctl --user is-active daedalus-wechat.service`
- result: `active`
- `systemctl --user status daedalus-wechat.service --no-pager`
- result: service running with `Status: "bridge polling"`

Live runtime inventory after restore:

- `codex`
  - `backend=codex`
  - `thread=019d332d-1bc8-7151-a874-ab0fbc493747`
  - `switchable=true`
  - `reason=live`
- `opencode`
  - `backend=opencode`
  - `thread=ses_2a9b9b59cffeTTpVS0iNdPRuoB`
  - `switchable=true`
  - `reason=live`

### Current truthful verdict

This slice is **partially successful**.

Succeeded:

- `daedalus-wechat.service` is restored and running again
- Codex remains restored
- Codex/OpenCode runtime isolation remains live-correct
- stale Codex final leak after `/switch opencode` is now covered by a direct unit
  test and patched in the mirror path

Still not cleanly proven in live owner-facing evidence:

- OpenCode-side `desktop-mirror final -> WeChat` is still not independently
  signed off by a clean live proof packet

## Follow-up narrowing — owner final skip and false success

Additional live findings after the initial note:

- real owner prompts still showed this pattern:
  - `prompt_submitted` for real owner on `thread=ses_2a9b...`
  - immediate `⚙️ 已注入 terminal。`
  - no matching real-owner `desktop-mirror final`
- OpenCode still generated the final answer in `opencode.db`
  - example owner prompt row: `1366`
  - example final row: `1368`
  - content: `text | final_answer | OK`
- one `✅ OK` was a false positive and must not count as success
  - `deliveries seq 50498`
  - `to=user@im.wechat`
  - this came from a local replay script artifact, not the real owner WeChat ID

### Narrowed root-cause read

Two more concrete truths emerged:

1. The OpenCode text extraction path itself was already good enough.
   - `latest_mirror_since(thread_id='ses_2a9b...', start_offset=1127)` returned
     `final='OK'` on the real missed owner prompts.
   - so the bridge knew how to extract the final from `opencode.db`.

2. The daemon still had a real cursor-loss hazard.
   - `_mirror_desktop_final_if_any()` advanced `mirror_offsets[thread_id]` before
     the owner-facing final send had actually succeeded.
   - in a shared OpenCode session with later local commentary/tool rows,
     advancing early makes it possible to move the cursor beyond the owner final
     without a durable owner delivery proof.

This is the exact failure class the follow-up fix closes:

- owner final exists in OpenCode
- local/shared session traffic continues
- bridge cursor must not commit past the owner final until final delivery succeeds

### Additional landed fix

- `src/daedalus_wechat/daemon.py`
  - `_reply(...)` now returns whether the reply was fully sent vs queued
  - `desktop-mirror` no longer commits the mirror cursor past a final until the
    final send succeeds
  - progress-only scans can still advance normally

### Additional regression coverage

- `test_mirror_keeps_cursor_when_final_send_is_queued`
  - exact guarantee: if the owner-facing final cannot be sent, the mirror cursor
    does not skip past it
- `test_latest_mirror_since_keeps_opencode_final_with_later_commentary`
  - exact guarantee: in a mixed OpenCode session, a later commentary text does
    not erase an earlier `final_answer` extracted from the same scan window

### Additional verification

- `cd ft-daedalus && uv run pytest -q tests/test_daemon.py tests/test_live_session.py`
- result: `99 passed`

- `cd ft-daedalus && uv run pytest -q`
- result: `135 passed`

- `cd ft-daedalus && uv run ruff check src tests`
- result: pass

- `systemctl --user restart daedalus-wechat.service`
- result: service active again on the cursor-safe build

### Current bounded read after follow-up fix

- service: restored and active
- Codex/OpenCode runtime isolation: still preserved
- false local replay success: explicitly excluded from acceptance
- OpenCode extractor: understood and regression-covered
- mirror cursor loss hazard: fixed

Still pending for full sign-off:

- one fresh real-owner OpenCode round-trip on the live service after this latest
  cursor-safe build

Current residual blocker:

- the owner-facing OpenCode tmux is also the current GPT OpenCode working seat,
  so bounded smoke prompts entered the same long-running live conversation
  rather than yielding a clean isolated one-shot mirror proof
- in live evidence after this patch, only OpenCode prompt injection acks were
  observed (`seq 50488`, `seq 50489`), not a new clean `desktop-mirror` final
  for `ses_2a9b...`

So the remaining truth is:

- service restored
- isolation preserved
- stale cross-session final leak patched
- OpenCode final owner-facing live proof still pending / blocked
