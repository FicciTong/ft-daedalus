# WeChat tmux-scoped queue and recent closeout — 2026-03-28

## Objective
Make owner-facing backlog/history semantics truthful after tmux-scoped outbox delivery:

- `/queue` should not imply that a waiting message from another tmux session belongs to the current active session
- `/recent` should default to the current active tmux session instead of silently mixing all delivered history

## Changes landed
- delivery ledger now persists `tmux_session`
- `/recent` now defaults to the current `active_tmux_session`
- `/recent all` explicitly requests the mixed global history view
- `/queue` now distinguishes:
  - `head=` for currently visible backlog
  - `head_waiting_session=` + `head_waiting=` when the only pending backlog belongs to another tmux session

## Validation
- Targeted tests:
  - `cd /home/ft/dev/ft-cosmos/ft-daedalus && PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_daemon -q`
  - result: `Ran 45 tests ... OK`
- Bytecode:
  - `cd /home/ft/dev/ft-cosmos/ft-daedalus && ./.venv/bin/python -m compileall src`
  - result: success
- User service:
  - `systemctl --user restart daedalus-wechat.service`
  - result: `active`

## Live render snapshot
- active tmux:
  - `daedalus`
- pending backlog:
  - `1`
- `/queue` render:

```text
queue=1
oldest_age_s=288
stuck_ge_120s=1
active_tmux=daedalus
visible_now=0
waiting_other_sessions=1
progress=1
sessions=1
session[1]=codex|count=1|threads=1
head_waiting_session=codex
head_waiting=⏳ 我不打算空等那个重的 backfill 了。按第一性原则，当前更快的主线动作是：停掉它，改跑一个“只复用现有 account evidence、不补历史 selection”的 bounded refresh，先把第一批 stamped
```

- `/recent 2` render:

```text
recent:
scope=daedalus
[27325][sent][progress][15:52:28] ⏳ 测试环境这边有个小偏差：`ft-daedalus` 的 `.venv` 里没有 `pytest` 模块。我不需要你介入，我会用 repo 的正常运行方式把验证补齐，再一起重启和提交。

[27326][sent][progress][15:53:08] ⏳ 我已经把渲染 contract 改完了。现在做最后一轮 live closeout：重启服务、用真实 state 渲染 `/queue` 和 `/recent` 看输出，再把证据文件落下，然后一次性 commit/push。

next=/recent after 27326
```

## Result
The current owner-facing behavior is now truthful:

- a waiting `codex` backlog stays queued while `daedalus` is active
- `/queue` explicitly marks that backlog as waiting for another session
- `/recent` for `daedalus` shows delivered `daedalus` history instead of mixed-session history by default
