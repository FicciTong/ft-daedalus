# WeChat catchup command verify — 2026-03-28

## Objective
Add an owner-facing command to skip large pending backlog without replaying every historical item by hand.

Canonical command:

- `/catchup [n]`

Semantics:

- only affects the current `active_tmux_session`
- trims the currently visible pending backlog to the newest `n` items
- leaves other tmux-session backlog untouched
- after trimming, the normal flush path continues sending the retained newest items

## Validation
- Targeted tests:
  - `cd /home/ft/dev/ft-cosmos/ft-daedalus && PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_daemon -q`
  - result: `Ran 47 tests ... OK`
- Bytecode:
  - `cd /home/ft/dev/ft-cosmos/ft-daedalus && ./.venv/bin/python -m compileall src`
  - result: success

## Dry-run against current live state
The following was evaluated against a deep copy of the current bridge state, so no live backlog was modified during verification.

### Before

```text
queue=10
oldest_age_s=19015
stuck_ge_120s=7
wait=next-wechat-message
active_tmux=codex
visible_now=9
waiting_other_sessions=1
final=1
plan=1
progress=8
sessions=2
session[1]=daedalus|count=1|threads=1
session[2]=*codex|count=9|threads=1
head=⏳ 我把这件事收成一个完整 lane 来做：先不回主线研究，先把 `agent-agnostic harness / control / resume / eval` 这套基础设施收成一个可执行闭环。第一步我先核对当前落地状态和未收口点，然
tail=⏳ 我继续往 control 层补，不停在 blueprint。下一步把已有 `change-budget` 和刚收紧的 `claim class / authority boundary` 接起来，让 agent 知道不同 slice 默
```

### `/catchup 5`

```text
catchup=ok
scope=codex
dropped=4
kept=5
next=bridge 会继续发送这几条保留下来的最新消息
```

### After

```text
queue=6
oldest_age_s=19015
stuck_ge_120s=3
wait=next-wechat-message
active_tmux=codex
visible_now=5
waiting_other_sessions=1
final=1
progress=5
sessions=2
session[1]=daedalus|count=1|threads=1
session[2]=*codex|count=5|threads=1
head=⏳ 我继续往下推，不碰主线研究。下一步我收的是 `eval/closeout discipline`，因为现在 blueprint 和 resume 有了，最值钱的就是把“什么算完成、什么证据才算过关”再压硬一层。
tail=⏳ 我继续往 control 层补，不停在 blueprint。下一步把已有 `change-budget` 和刚收紧的 `claim class / authority boundary` 接起来，让 agent 知道不同 slice 默
```

## Result
`/catchup 5` gives the intended shortest-path behavior:

- old visible backlog can be discarded in one step
- only the newest retained items remain to be flushed
- other tmux-session backlog is preserved
