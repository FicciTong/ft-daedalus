# WeChat tmux-scoped outbox verify — 2026-03-28

## Objective
Make pending WeChat backlog owner-facing `tmux session` scoped instead of globally flushed across sessions.

## Changes landed
- pending outbox items now persist `tmux_session`
- flush only releases items for the current active tmux scope plus unscoped system items
- `/queue` now reports:
  - `visible_now`
  - `waiting_other_sessions`
  - per-session counts instead of only per-thread counts
- help/readme updated to describe tmux-scoped queue semantics

## Verification
- Targeted tests:
  - `PYTHONPATH=src uv run pytest -q tests/test_daemon.py tests/test_cli.py tests/test_live_session.py`
  - result: `54 passed`
- Bytecode:
  - `PYTHONPATH=src python -m compileall src`
  - result: success
- User service:
  - `systemctl --user restart daedalus-wechat.service`
  - `systemctl --user is-active daedalus-wechat.service`
  - result: `active`
- Live state snapshot after restart:
  - `active_tmux = daedalus`
  - `pending = 1`
  - `tmux_counts = {'daedalus': 1}`
  - `thread_counts = {'019cdfe5-fa14-74a3-aa31-5451128ea58d': 1}`
- Sample queue rendering after restart:
  - `queue=1`
  - `wait=next-wechat-message`
  - `active_tmux=daedalus`
  - `visible_now=1`
  - `waiting_other_sessions=0`
  - `sessions=1`
  - `session[1]=*daedalus|count=1|threads=1`

## Boundary
This change does not create a fully separate physical transport per tmux session.
It keeps a shared WeChat bridge process, but backlog delivery is now scoped by active tmux so inactive-session backlog waits until `/switch` targets that tmux.
