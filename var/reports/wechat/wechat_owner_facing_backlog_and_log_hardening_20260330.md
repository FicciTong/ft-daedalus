# WeChat owner-facing backlog/log hardening — 2026-03-30

## Problem

The owner-facing bridge commands had diverged into three inconsistent views:

- `/queue` only reported `pending_outbox`
- `/recent` replayed raw delivery ledger entries, including repeated `queued`
  retry noise
- `/catchup` only trimmed pending backlog and returned `empty` when no visible
  pending items existed, even if recent effective messages did exist

This created a misleading live operator experience:

- the bridge could say `queue=0` / `catchup=empty`
- but sending a new inbound WeChat message could still flush an old pending
  mirror item
- `/recent` could replay retry noise instead of the newest effective chat

## Live truth at inspection

- state: `/home/ft/.local/state/daedalus-wechat/state.json`
- ledger: `/home/ft/.local/state/daedalus-wechat/deliveries.jsonl`
- events: `/home/ft/.local/state/daedalus-wechat/events.jsonl`

Observed before the fix:

- `pending_outbox = 0`
- `/queue` therefore rendered `queue=0 / status=empty`
- `/recent 6` still surfaced repeated historical `queued` / `final` noise
- `/catchup` returned `catchup=empty`

This proved the bug was not a single bad command; the owner-facing backlog,
history, and error surfaces were semantically inconsistent.

## Landed changes

1. `/recent` now reads **effective delivery history** only.
   - It filters out raw `queued` retry noise.
   - It replays `sent` / `flushed` events as the effective owner-facing history.

2. `/catchup` now becomes a real owner-facing catchup command.
   - It still trims current-scope backlog.
   - It now also replays recent/incremental **effective** delivery history.
   - It persists a per-scope recent-delivery cursor so repeated catchup calls
     move forward instead of re-dumping the same history forever.
   - When nothing new exists it returns `catchup=up_to_date`, not a misleading
     raw `empty`.

3. `/queue` now stays honest even when `pending_outbox = 0`.
   - It reports the latest effective delivery summary for the active scope.
   - The operator can now distinguish:
     - no pending backlog
     - but recent effective messages do exist

4. Stale failed backlog no longer auto-surprises on the next inbound message.
   - Only pending items that are both:
     - previously failed / retried
     - and stale
     are blocked from automatic flush.
   - This prevents old retry backlog from resurfacing just because a new
     inbound message refreshed the chat context.

5. Added `/log`.
   - This exposes recent bridge events and errors from `events.jsonl`.
   - It gives the owner a direct view of backlog/error behavior without shell
     access.

## Not landed

- no command alias expansion
  - owner explicitly said `/queue` and `/catchup` are always handwritten
- no broader multi-CLI / multi-tmux bridge expansion
- no change to the underlying OpenClaw / WeChat vendor transport

## Verification

- `cd ft-daedalus && uv run pytest -q`
  - `82 passed`
- `cd ft-daedalus && uv run ruff check src/daedalus_wechat/daemon.py src/daedalus_wechat/state.py src/daedalus_wechat/delivery_ledger.py tests/test_daemon.py`
  - passed
- `cd ft-daedalus && git diff --check`
  - passed
- user service restarted:
  - `systemctl --user restart daedalus-wechat.service`
  - status = `active (running)`

## Current operator semantics

- `/queue`
  - current backlog posture
  - plus latest effective delivery summary
- `/recent`
  - stable effective delivery history
- `/catchup`
  - trim current backlog if needed
  - then move the per-scope catchup cursor forward over effective history
- `/log`
  - recent bridge events / errors
