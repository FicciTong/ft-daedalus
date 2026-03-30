# WeChat `/recent` and `/catchup` live correction — 2026-03-30

## Why this slice landed

Owner-facing live behavior was still wrong after the first command-surface
hardening pass:

- `/catchup` could still replay old `codex` history from an earlier day
- `/recent` could still surface `kind=command` echo messages that recursively
  embedded old transcript text
- the stored catchup cursor could become stale after delivery-seq resets

Current live truth before this correction:

- `state.json` had `recent_delivery_cursors["<bound_user>|codex"] = 27384`
- current live effective deliveries were in the `9239+` range
- `/catchup` therefore anchored to the wrong historical point and replayed the
  old `2733x` block

## Landed correction

- `/recent` now treats owner-facing history as:
  - effective deliveries only
  - excluding `kind=command` echo payloads
  - bounded to the latest recent message cluster instead of crossing a long
    historical gap
- `/catchup` now:
  - excludes command echo history the same way
  - detects a stale per-scope cursor when stored seq is ahead of the current
    live tail
  - resets stale cursor and re-anchors to the current recent cluster
- `/queue` keeps using the same owner-facing recent-effective read path

## Verification

- targeted bridge tests:
  - `cd ft-daedalus && uv run pytest -q tests/test_daemon.py -k 'recent or catchup or queue'`
  - `19 passed`
- full repo tests:
  - `cd ft-daedalus && uv run pytest -q`
  - `85 passed`
- lint:
  - `cd ft-daedalus && uv run ruff check src/daedalus_wechat/daemon.py src/daedalus_wechat/delivery_ledger.py src/daedalus_wechat/state.py tests/test_daemon.py`
  - passed
- diff hygiene:
  - `cd ft-daedalus && git diff --check`
  - passed
- user service:
  - `systemctl --user restart daedalus-wechat.service`
  - `active (running)`

## Live smoke after landing

Local smoke with real `state.json + deliveries.jsonl` now shows:

- `/queue`
  - `queue=0`
  - latest effective summary stays on the current live `codex` cluster
- `/recent 6`
  - current `9253+` / `9294+` cluster only
  - no `2733x` historical spill
  - no recursive command-echo history
- `/catchup`
  - current cluster only
  - no old `2733x` block

## Boundary

This correction does **not** claim:

- vendor transport redesign
- elimination of all `ret=-2` retries
- multi-CLI / multi-tmux bridge expansion
- a new operator layer beyond the existing commands
