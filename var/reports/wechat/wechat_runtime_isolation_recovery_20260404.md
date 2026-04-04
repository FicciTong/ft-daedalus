## 2026-04-04 — WeChat bridge runtime isolation recovery

### Scope

Bounded recovery slice for `ft-daedalus` after the bridge mixed `codex` and
`opencode` shell identities and stopped replying cleanly.

Required boundary for this slice:

- preserve existing Codex bridge capability
- preserve OpenCode support
- restore strict shell/runtime isolation
- do not widen into full OpenCode orchestrator cutover

### Root cause

Two real issues combined into the failure:

1. backend detection was too willing to trust pane transcript text for `node`
   panes, so a real Codex `node` process could be misread as `opencode` when the
   resumed conversation itself mentioned OpenCode
2. tmux/session resolution still had stale fallback paths that could reuse
   historical `label` / `tmux_session` mappings and cross-bind a live OpenCode
   session back onto the canonical `codex` tmux identity

Observed live failure before recovery:

- `daedalus-wechat.service` was stopped
- bridge state had:
  - `active_session_id = ses_2a9b9b59cffeTTpVS0iNdPRuoB`
  - `active_tmux_session = codex`
- live inventory showed:
  - `codex backend=opencode switchable=false reason=backend-mismatch`
  - `opencode backend=opencode switchable=false reason=duplicate-runtime-id`

### Landed code changes

- `src/daedalus_wechat/cli_backend.py`
  - prefer `pane_start_command` over pane transcript when classifying supported
    runtimes
  - stop treating shell panes with stale OpenCode screen text as a live
    OpenCode runtime by default
- `src/daedalus_wechat/live_session.py`
  - add explicit tmux-session backend expectations
  - add fail-closed runtime conflict detection:
    - `backend-mismatch`
    - `duplicate-runtime-id`
  - route runtime IDs back to the truthful backend tmux name instead of always
    falling back to canonical `codex`
  - exclude conflicted sessions from the live inventory / switchable set
  - refuse `require_live_session()` when shell isolation is broken
- `src/daedalus_wechat/daemon.py`
  - stop `/switch` from rebinding stale historical tmux-name matches when no
    live match exists
  - surface runtime conflicts explicitly in `/status` / `/health`
  - stop mirror tracking from accepting conflicted active runtime state
- tests updated and expanded for:
  - backend detection with `pane_start_command`
  - stale `/switch` fallback rejection
  - runtime conflict reporting
  - opencode thread routing back to `tmux opencode`

### Live recovery actions

1. preserved the misbound `codex` session long enough to free the canonical name
2. recreated `tmux codex` as a real Codex runtime with:
   - `codex resume 019d332d-1bc8-7151-a874-ab0fbc493747 -C /home/ft/dev/ft-cosmos --no-alt-screen`
3. rechecked runtime inventory after detector/routing fixes
4. restarted `daedalus-wechat.service`
5. confirmed bridge state re-aligned to the real Codex session

Steady-state operator rule after this recovery:

- owner-supported bridge shells are currently:
  - `tmux codex`
  - `tmux opencode`
- each shell/runtime must stay isolated
- if a future adapter is added (for example Claude), it must get its own
  distinct shell/runtime identity too
- bridge conflict posture is now fail-closed, not silent fallback

### Verification

Focused tests:

- `cd ft-daedalus && uv run pytest -q tests/test_cli_backend.py tests/test_live_session.py tests/test_daemon.py`
- result: `109 passed`

Full tests:

- `cd ft-daedalus && uv run pytest -q`
- result: `131 passed`

Lint:

- `cd ft-daedalus && uv run ruff check src/daedalus_wechat tests`
- result: pass

Live service:

- `systemctl --user is-active daedalus-wechat.service`
- result: `active`

Live inventory after recovery:

- `codex`
  - `backend=codex`
  - `thread=019d332d-1bc8-7151-a874-ab0fbc493747`
  - `switchable=true`
  - `reason=live`
- `opencode`
  - `backend=opencode`
  - `thread=ses_2a9b9b59cffeTTpVS0iNdPRuoB`
  - `switchable=true`
  - `reason=live`

Bridge state after restart:

- `active_session_id = 019d332d-1bc8-7151-a874-ab0fbc493747`
- `active_tmux_session = codex`

Owner switching acceptance path:

- repeated command-path verification was run against the real live runner with an
  in-memory state copy, so the actual `/sessions` / `/switch` / `/status`
  handlers were exercised without perturbing the running daemon state
- initial `/sessions` view:
  - `1 codex | 019d332d | codex live`
  - `2 opencode | ses_2a9b | opencode live`
- `/switch codex`:
  - active state became:
    - `active_tmux_session = codex`
    - `active_session_id = 019d332d-1bc8-7151-a874-ab0fbc493747`
  - mirror target stayed:
    - `MIRROR_THREAD = 019d332d-1bc8-7151-a874-ab0fbc493747`
    - `MIRROR_TMUX = codex`
  - `/status` stayed coherent:
    - `backend=codex`
    - `tmux=codex`
    - `label=codex`
- `/switch opencode`:
  - active state became:
    - `active_tmux_session = opencode`
    - `active_session_id = ses_2a9b9b59cffeTTpVS0iNdPRuoB`
  - mirror target stayed:
    - `MIRROR_THREAD = ses_2a9b9b59cffeTTpVS0iNdPRuoB`
    - `MIRROR_TMUX = opencode`
  - `/status` stayed coherent:
    - `backend=opencode`
    - `tmux=opencode`
    - `label=opencode`
- `/switch codex` again:
  - active state returned cleanly to Codex
  - `/sessions` marked only `codex` as active and kept `opencode` listed as the
    other live session

Acceptance read for repeated switching:

- switching between `codex` and `opencode` no longer cross-binds runtime identity
- active session state follows the switch truthfully
- the mirror target follows the active session truthfully
- owner-facing `/status` / `/sessions` / `/switch` remain coherent through
  repeated switching

Owner-facing live screenshot evidence:

- screenshot path:
  - `/home/ft/.local/state/daedalus-wechat/incoming_media/7446032554913270408_1.jpg`
- visible owner path in that screenshot:
  - `/switch opencode`
  - bridge reply:
    - `label=opencode`
    - `tmux=opencode`
    - `attach=tmux attach -t opencode`
  - next owner message:
    - `Hi owner sending msg from wechat`
  - bridge reply:
    - `已注入 terminal。`
- current read:
  - after an explicit switch to `opencode`, the next ordinary WeChat message was
    handled as input for the active `opencode` session rather than silently
    surfacing through `codex`

### Current truthful read

This recovery slice is materially successful.

- Codex support remains intact
- OpenCode support remains intact
- `codex` and `opencode` are live-separated again
- bridge/runtime state no longer maps the same OpenCode session across both tmux
  names
- `daedalus-wechat.service` is running again

What this slice did **not** do:

- no Claude bridge adapter
- no owner-facing governance change
- no OpenCode orchestrator cutover
