## WeChat delivery wait-for-bind verification — 2026-03-28

- Service restart:
  - `daedalus-wechat.service`
  - restarted at `2026-03-28 10:11:40 CST`
- Problem before fix:
  - repeated `queued` ledger lines for the same mirrored `final`
  - error string: `WeChat send failed: ret=-2 errcode=None errmsg=None`
  - behavior looked like backlog only flushed after a later user message
- Fix now landed:
  - when outbound send still fails with `ret=-2`, bridge marks outbox as
    `wait-for-bind`
  - background retry stops hammering the same pending message
  - next inbound WeChat message clears the hold and triggers flush
- Live evidence from `~/.local/state/daedalus-wechat/deliveries.jsonl`:
  - queued while waiting:
    - `26440` `2026-03-28T02:11:42.000167+00:00` `queued final`
    - `26441` `2026-03-28T02:11:42.489373+00:00` `queued progress`
  - later inbound refresh + flush:
    - `26442` `2026-03-28T02:11:47.240628+00:00` `sent command wechat-command`
    - `26443` `2026-03-28T02:11:47.694712+00:00` `flushed final`
    - `26444` `2026-03-28T02:11:48.215666+00:00` `flushed plan`
    - `26445` `2026-03-28T02:11:48.712165+00:00` `flushed progress`
- Current state after flush:
  - `pending_outbox = 0`
  - `outbox_waiting_for_bind = false`

Conclusion:

- no full reconnect is needed
- the practical recovery action is just one fresh inbound WeChat message
- bridge no longer retry-thrashes the same stale-context delivery in the background
