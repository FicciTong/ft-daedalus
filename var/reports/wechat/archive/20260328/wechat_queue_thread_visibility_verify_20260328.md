# WeChat Queue Thread Visibility Verify — 2026-03-28

- verified_at: 2026-03-28 14:58:05 CST
- scope: `/queue` should make cross-session/thread backlog visible instead of looking like an undifferentiated global pile

## Current live runtime

```text
queue=0
status=empty
```

## Synthetic multi-thread sample

```text
queue=2
oldest_age_s=25085
stuck_ge_120s=2
final=1
plan=1
threads=2
thread[1]=kairos|019cdfe5|count=1
thread[2]=*codex|019d332d|count=1
head=OLD FINAL
tail=NEW PLAN
```

## Result

- queue storage is still one owner-facing outbox per WeChat binding
- each pending item keeps its `thread_id`
- `/queue` now surfaces:
  - total queue size
  - kind counts
  - `threads=<n>`
  - per-thread counts with active-thread marker
- implication:
  - backlog from different live sessions is not silently hidden anymore
  - if mixed backlog exists, the operator can see it before switching or flushing
