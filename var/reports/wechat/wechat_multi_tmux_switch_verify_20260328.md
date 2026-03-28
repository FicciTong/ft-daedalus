# WeChat Multi-Tmux Switch Verify — 2026-03-28

- package: /home/ft/dev/ft-cosmos/ft-daedalus/src/daedalus_wechat/__init__.py
- daemon: /home/ft/dev/ft-cosmos/ft-daedalus/src/daedalus_wechat/daemon.py
- live_session: /home/ft/dev/ft-cosmos/ft-daedalus/src/daedalus_wechat/live_session.py
- default_cwd: /home/ft/dev/ft-cosmos
- canonical_tmux_session: codex
- discovered_live_session_count: 1

## Discovered live sessions
- 1. tmux=codex pane=node cwd=/home/ft/dev/ft-cosmos thread=019cdfe5-fa14-74a3-aa31-5451128ea58d

## /sessions output
```text
sessions=1
*1 attached-last | 019cdfe5 | codex live
use=/switch 1
```

## /status output
```text
status=ok
thread=019cdfe5
label=attached-last
tmux=codex
cwd=~/dev/ft-cosmos
notify=progress+final
attach=tmux attach -t codex
```

## Notes
- live discovery only includes tmux sessions that look like a live Codex runtime and whose pane cwd is inside the configured workspace
- this excludes unrelated tmux sessions such as deleted/openclaw workspaces from the switchable surface
