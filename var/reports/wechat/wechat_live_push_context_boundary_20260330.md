# WeChat Live Push Context Boundary

Date: 2026-03-30
Repo: `ft-daedalus`

## Summary

The bridge itself is back to a healthy local state:

- service is running
- inbound command/reply path is alive
- active tmux/thread resolution is truthful again

The remaining constraint is now the WeChat channel's live chat context, not a
local daemon failure.

## What Was Fixed

1. `security_drill` no longer mutates the live bridge state file.
2. Invalid/stale `get_updates_buf` is cleared on `ret=-1` / `ret=-14`.
3. systemd status returns to `bridge polling` after poll recovery.
4. `desktop-mirror` traffic now uses context-free sends instead of preferring a
   stale bound `context_token`.
5. `ret=-2` retry now uses a fresh `client_id`.
6. `wait_for_bind` no longer blocks a visible-scope backlog when the backlog is
   entirely `desktop-mirror`.

## Current Truth

Local daemon/service state is healthy, but once the WeChat channel stops
accepting the existing live chat context, desktop-originated mirror pushes can
still queue until the next real inbound WeChat message refreshes binding.

This means:

- `desktop-mirror` delivery is durable via pending outbox
- command replies still work on a fresh inbound context
- a fresh inbound message remains the truthful recovery path when the channel
  starts rejecting outbound live push with `ret=-2`

## Operator Recovery

If live push appears stalled again:

1. send `/status` or any normal text from WeChat
2. let the bridge refresh binding
3. pending `desktop-mirror` backlog should flush on the refreshed context lane

This should be read as a channel boundary, not as proof that the local bridge
is down.
