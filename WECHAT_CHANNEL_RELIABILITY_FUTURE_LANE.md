# WeChat Channel Reliability Future Lane

Canonical record of the next bounded improvement lane for `daedalus-wechat`.

This is a **future lane**, not an active implementation lane.

The purpose of this document is to preserve:

- what the current bridge already does
- what the remaining pain point actually is
- why the next step should stay in `ft-daedalus`
- what the shortest correct upgrade path is
- what this lane must **not** become

## Current truth

As of `2026-03-28`, the current `daedalus-wechat` bridge already has:

- one canonical local `tmux codex` runtime
- WeChat inbound polling through the official OpenClaw Weixin route
- prompt injection into the live Codex terminal
- desktop mirror of `progress / plan / final`
- a persisted `pending_outbox`
- a `delivery_ledger`
- a background outbox retry loop
- bounded reliability features such as:
  - `ret=-2` retry without `context_token`
  - pending flush on the next inbound message
  - final fallback from visible live `tmux` text

This means the current bridge is already beyond a toy transport script.

## Current pain point

The remaining real pain point is:

- outbound delivery can still feel **sticky**
- old queued messages may appear to flush only after a new inbound message or
  later bridge activity
- the owner experiences this as:
  - message backlog
  - delayed progress/final delivery
  - WeChat not yet feeling like a fully reliable primary operator surface

This is not the same problem as:

- Codex model latency
- tmux runtime correctness
- OpenClaw login/bootstrap

It is specifically a **channel delivery and drain semantics** problem.

## Why this lane should exist

The owner wants WeChat to become the practical primary operator entry surface
for daily use, with terminal dependence reduced as much as truthfully possible.

Therefore, this lane has real value because it improves:

- operator trust
- queue visibility
- progress/final delivery reliability
- practical phone-first usability

This lane is not cosmetic.

## Why this lane should stay in `ft-daedalus`

The correct host for this work is `ft-daedalus`, not Codex itself.

This lane must remain:

- outside official Codex
- outside `ft-kairos`
- outside the battlefield/runtime truth stack

Correct boundary:

- official `codex` remains unchanged
- `ft-daedalus` owns:
  - bridge behavior
  - message lifecycle
  - channel adaptation
  - operator-facing delivery semantics

This means:

- no Codex fork
- no Codex patching
- no attempt to inject custom channel logic into the model runtime itself

## Current diagnosis

The bridge already has part of a message system, but not a complete one.

Current pieces that exist:

- queue:
  - `pending_outbox`
- append-only evidence:
  - `deliveries.jsonl`
- retry worker:
  - `_outbox_retry_loop`
- desktop mirror worker:
  - `_mirror_loop`

Current pieces that are still too thin:

- delivery state is too coarse
  - mainly `sent / queued / flushed`
- retry metadata is too thin
  - no explicit retry count / next retry / stuck age contract
- stuck-message visibility is too weak
- backlog/drain visibility is too weak
- queue semantics are still closer to a bridge than to a real channel adapter

## Shortest correct next step

Do **not** build a generic plugin ecosystem.

Do **not** build a marketplace.

Do **not** redesign the whole bridge around abstract framework theater.

The shortest correct bounded next step is:

### 1. explicit delivery state

Upgrade queue items from a simple pending list to an explicit message lifecycle
such as:

- `queued`
- `sending`
- `sent`
- `retrying`
- `stuck`

### 2. explicit retry metadata

Each pending item should carry:

- `attempt_count`
- `last_error`
- `created_at`
- `last_attempt_at`
- `next_retry_at`

### 3. explicit queue observability

Add operator-facing queue inspection such as:

- `/queue`
- `pending_count`
- `oldest_pending_age`
- `stuck_count`

### 4. explicit stuck handling

Do not allow old queued items to remain silently pending forever.

The bridge should be able to distinguish:

- still retrying
- temporarily blocked
- genuinely stuck

## Done when

This lane should be considered successfully opened later only if:

1. queued outbound messages no longer rely on incidental later traffic to feel
   drained
2. the owner can inspect queue age/count/stuck state directly from WeChat
3. outbound failures become explicitly classifiable rather than merely
   "pending"
4. the implementation still does **not** require any Codex modification
5. the implementation remains small, bounded, and specific to
   `daedalus-wechat`

## What this lane must not become

This future lane must not be used as an excuse to:

- modify official Codex
- invent a universal internal plugin framework
- build a full multi-channel platform before it is needed
- turn `ft-daedalus` into a general-purpose orchestration engine
- interrupt higher-priority current work in data bedrock and mainline closure

## Current decision

Current canonical decision:

- this lane is worth doing
- it is not a current `P0`
- it should be opened after the current higher-priority mainline/data closure
  work is more settled
- when opened, it should be implemented as a bounded `ft-daedalus` upgrade only

## Adjacent but separate future lane

The owner has also requested a later **multi-CLI / multi-tmux** operator lane,
for example:

- `tmux codex`
- `tmux claude`
- `tmux kimi`

That is a real future lane, but it is **not** the same problem as this
reliability lane.

Keep the separation explicit:

- this document = current WeChat channel reliability / drain semantics
- later multi-CLI lane = target identity, per-CLI binding, routing, and queue
  isolation across multiple live operator runtimes

Do **not** use this reliability lane as an excuse to silently expand into a
generic multi-agent bridge framework.
