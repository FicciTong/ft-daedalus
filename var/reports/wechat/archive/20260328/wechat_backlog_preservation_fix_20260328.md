# 2026-03-28 WeChat backlog preservation fix

## Problem

The bridge could report a very small `/queue` backlog while the delivery ledger
already showed many recent `queued` desktop-mirror entries.

Observed runtime truth before the fix:

- runtime state:
  - `~/.local/state/daedalus-wechat/state.json`
  - `pending_outbox = 2`
- command reply seen by the user:
  - `/queue -> queue=2`
- but the recent delivery ledger already contained many undelivered entries in
  the same incident window:
  - examples: `seq=26885..26917`
  - kind: `progress`
  - origin: `desktop-mirror`

This matched the user-visible symptom:

- `\\Q` only reported two or three queued messages
- older queued progress updates disappeared instead of flushing later

## Root cause

Two local queue semantics were wrong for this use case:

1. `BridgeState.enqueue_pending_with_meta(...)` explicitly removed older
   `desktop-mirror progress` entries for the same thread before appending the
   newest one.
2. The persisted pending queue kept only the last `100` items and did not
   expose overflow as a first-class signal.

The first issue caused real backlog loss.
The second issue made future loss silent if the queue ever grew further.

## Landed fix

Changed files:

- `src/daedalus_wechat/state.py`
- `src/daedalus_wechat/daemon.py`
- `tests/test_daemon.py`
- `README.md`
- `README.zh-CN.md`

Contract after the fix:

- desktop-mirror backlog is preserved in queue order
- old progress items are no longer silently folded away just because a newer
  progress item for the same thread arrives
- `/queue` now shows:
  - current queue size
  - oldest age
  - stuck count
  - head preview
  - tail preview
  - `overflow_dropped` if a hard cap was ever exceeded
- queue cap remains bounded, but overflow is now explicit instead of silent

## Verification

- `PYTHONPATH=/home/ft/dev/ft-cosmos/ft-daedalus/src uv run pytest -q tests/test_daemon.py tests/test_wechat_api.py`
  - `31 passed`
- `python -m compileall src/daedalus_wechat tests/test_daemon.py tests/test_wechat_api.py`
  - passed

Key regression checks now covered:

- duplicate message identity still dedupes correctly
- pending flush still preserves remainder after mid-flush failure
- desktop-mirror backlog now preserves multiple progress entries for one thread
- overflow tracking is explicit
- `/queue` includes tail preview

## Boundary

This fix preserves future backlog truthfully.

It does **not** auto-replay historical already-lost queued messages from the
delivery ledger back into the active chat, because that would be an
irreversible owner-facing action and should remain deliberate.
