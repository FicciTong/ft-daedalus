# WeChat Sessions / Switch Verify — 2026-03-28

- verified_at: 2026-03-28 14:50:27 CST
- scope: `/sessions` truthful inventory + `/switch codex` live exact-match resolution

## Runtime truth

- tmux sessions observed: `codex`, `kairos`, `openclaw`
- switchable live sessions: `codex`, `kairos`
- excluded tmux session: `openclaw`
- excluded reason: `outside-workspace`

## Owner-facing `/sessions`

```text
sessions=2
*1 codex | 019d332d | codex live
 2 attached-last | 019cdfe5 | kairos live
excluded=1
x openclaw | outside-workspace
use=/switch 1
```

## Owner-facing `/switch codex`

```text
已切换到 session:
019d332d-1bc8-7151-a874-ab0fbc493747
label=codex
tmux=codex
attach=tmux attach -t codex
```

## Result

- `/switch <tmux>` now prefers current live tmux matches over stale historical registry duplicates
- `/sessions` no longer hides excluded tmux inventory without explanation
- the third tmux session was not missing; it was intentionally excluded from the switchable set
