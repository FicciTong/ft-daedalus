# codex-wechat-bridge

Bridge a **local Codex tmux session** into WeChat using the **official**
OpenClaw Weixin channel (`@tencent-weixin/openclaw-weixin`).

This is **not** a cloud-task wrapper. It preserves **local session continuity**
by routing WeChat messages into one canonical live tmux shell:

- tmux session name: `codex`
- live agent inside that shell: local `codex`
- WeChat acts as a remote input surface for that same local shell

Desktop and mobile intentionally have **different output semantics**:

- desktop `tmux codex` = **full live terminal stream**
- WeChat = **final reply only**

## Truthful boundaries

- This bridge does **not** modify Codex.
- This bridge does **not** live inside `ft-cosmos`.
- This bridge does **not** use Codex cloud tasks.
- This bridge does **not** multiplex multiple active live shells into one chat.
- This bridge uses the **official** `openclaw-weixin` login flow.
- This bridge keeps its own dedicated OpenClaw profile by default, so it does
  not need to fight with an existing OpenClaw gateway account already running
  on the same machine.
- This bridge treats `tmux codex` as the canonical runtime truth.

## How To Think About It

There are two distinct surfaces:

1. **Desktop live owner**
   - `tmux attach -t codex`
   - shows everything: prompt injection, live model output, tool chatter

2. **WeChat operator surface**
   - sends messages into that same local Codex session
   - receives **final reply only**
   - does **not** receive thinking / commentary / bottom status bar noise
   - after the current WeChat chat is bound, desktop-originated final replies
     from that same active session are also mirrored back to WeChat

So:

- if you want the full live stream, look at desktop tmux
- if you want remote control from your phone, use WeChat
- if you want desktop-originated final replies to come back to WeChat, first
  send any normal message or command once so the current chat context is bound
- if you manually `resume` a different thread inside `tmux codex`, the mirror
  follows that **current canonical tmux thread**, not a stale saved thread id

## Prerequisites

You need these on the machine that owns the local Codex session:

- `codex`
- `tmux`
- Python `3.13+`
- `uv`
- `openclaw`
- WeChat on your phone

This means: **yes, OpenClaw is a real prerequisite for this implementation.**
The bridge uses the official OpenClaw Weixin channel path; it does not replace
that dependency.

Quick checks:

```bash
codex --version
tmux -V
python3 --version
uv --version
openclaw --version
```

For the official Weixin channel plugin, Tencent currently documents:

```bash
npx -y @tencent-weixin/openclaw-weixin-cli install
```

and then:

```bash
openclaw channels login --channel openclaw-weixin
```

This bridge wraps that official route for you, so you usually do **not** need
to run those raw commands manually.

If your friend does not already have `openclaw`, they need to install it first
before this bridge can work.

## Install

```bash
cd ~/dev
git clone https://github.com/FicciTong/codex-wechat-bridge.git
cd codex-wechat-bridge
uv sync
```

## Fastest Friend Install

If you want to hand this to someone else, the shortest install path is:

```bash
cd ~/dev/codex-wechat-bridge
bash scripts/install-user-service.sh
```

This script does all of the following:

1. checks required commands (`codex`, `tmux`, `python3`, `uv`, `openclaw`,
   `systemctl`)
2. runs `uv sync`
3. installs the user systemd unit
4. creates `~/.config/codex-wechat-bridge.env` if missing
5. runs the official WeChat QR login flow
6. restarts the bridge
7. runs bridge doctor

If you only want the health summary later:

```bash
cd ~/dev/codex-wechat-bridge
bash scripts/doctor.sh
```

## Official WeChat Login

The canonical login path for this bridge is:

```bash
cd ~/dev/codex-wechat-bridge
uv run codex-wechat-bridge auth-openclaw
```

What this does:

1. bootstraps the official `@tencent-weixin/openclaw-weixin` plugin into the
   dedicated OpenClaw profile `codex-wechat-bridge`
2. enables the plugin for that profile
3. runs the official QR-code login flow
4. imports the resulting account into the bridge state dir

By default the bridge stores its imported account at:

```bash
~/.local/state/codex-wechat-bridge/account.json
```

If `doctor` later reports `errcode=-14` / session timeout, just run
`uv run codex-wechat-bridge auth-openclaw` again.

If you intentionally want a different OpenClaw profile:

```bash
export CODEX_WECHAT_BRIDGE_OPENCLAW_PROFILE=my-profile
```

## Security Boundary

By default, if you do nothing, the bridge allows any sender who can reach the
bot conversation.

If this machine matters, **configure an allowlist** in:

```bash
~/.config/codex-wechat-bridge.env
```

Example:

```bash
CODEX_WECHAT_BRIDGE_ALLOWED_USERS=o9cq80y6O1DAYqilESlM_NbeqtTc@im.wechat
```

You can provide multiple users, comma-separated:

```bash
CODEX_WECHAT_BRIDGE_ALLOWED_USERS=user-a@im.wechat,user-b@im.wechat
```

After changing the env file:

```bash
systemctl --user restart codex-wechat-bridge
```

## Canonical Desktop Session

The bridge expects one canonical live tmux owner:

```bash
tmux new -s codex 'codex resume --last -C /home/ft/dev/ft-cosmos --no-alt-screen'
```

If `tmux codex` already exists:

```bash
tmux attach -t codex
```

If you do **not** have a prior thread yet, start one in the same canonical tmux:

```bash
tmux new -s codex 'codex -C /home/ft/dev/ft-cosmos --no-alt-screen'
```

Important discipline:

- keep **one** canonical bridge-owned tmux live session
- do **not** keep opening random parallel `codex resume` windows if you want
  continuity to stay clean
- if you need desktop live view, always attach to `tmux codex`

## Run The Bridge

Foreground:

```bash
cd ~/dev/codex-wechat-bridge
uv run codex-wechat-bridge run
```

Health check:

```bash
cd ~/dev/codex-wechat-bridge
uv run codex-wechat-bridge doctor
```

## Install As A User Service

This repo includes a user-level systemd unit:

```bash
mkdir -p ~/.config/systemd/user
cp ops/systemd/user/codex-wechat-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now codex-wechat-bridge
```

The bridge reads:

```bash
~/.config/codex-wechat-bridge.env
```

That is the canonical place for both foreground CLI and background service:

- `CODEX_WECHAT_BRIDGE_DEFAULT_CWD`
- `CODEX_WECHAT_BRIDGE_TMUX_SESSION`
- `CODEX_WECHAT_BRIDGE_CODEX_BIN`
- `CODEX_WECHAT_BRIDGE_ALLOWED_USERS`
- optional profile overrides

Useful commands:

```bash
systemctl --user status codex-wechat-bridge
systemctl --user restart codex-wechat-bridge
journalctl --user -u codex-wechat-bridge -n 100 --no-pager
```

## WeChat Commands

The bridge accepts both `/command` and `\\command`.

Commands:

- `/help`
- `/status`
- `/health`
- `/sessions`
- `/new [label]`
- `/switch <index|thread_id-prefix|label|tmux>`
- `/attach-last`
- `/stop`

Plain text messages are sent to whatever Codex thread is **currently active
inside `tmux codex`**.

Examples:

```text
/health
/status
/sessions
/switch 1
/switch attached-last
/switch codex
帮我检查今天的 package outcome
```

Phone-friendly semantics:

- `/health` = is the bridge / tmux / thread healthy right now
- `/status` = which live session am I currently attached to
- `/sessions` = short switchable list, optimized for phone reading

## Daily Operating Guide

### Start of day

1. make sure `tmux codex` exists
2. make sure Codex is running inside it
3. make sure the bridge service is up
4. use WeChat `/status` to confirm active session

### While outside

- talk to WeChat normally
- use `/status` if you want to confirm which session is active
- use `/sessions` and `/switch` only if you intentionally manage more than one
  session

### Back at the desktop

Attach to the canonical owner:

```bash
tmux attach -t codex
```

Do **not** expect a separate desktop Codex window to live-sync if it is not the
canonical tmux owner.

## Optional Environment Variables

- `CODEX_WECHAT_BRIDGE_DEFAULT_CWD`
- `CODEX_WECHAT_BRIDGE_STATE_DIR`
- `CODEX_WECHAT_BRIDGE_ACCOUNT_FILE`
- `CODEX_WECHAT_BRIDGE_CODEX_BIN`
- `CODEX_WECHAT_BRIDGE_OPENCLAW_PROFILE`
- `CODEX_WECHAT_BRIDGE_TMUX_SESSION`

## Failure Recovery

If WeChat stops replying:

1. run:

```bash
systemctl --user status codex-wechat-bridge
```

2. run:

```bash
cd ~/dev/codex-wechat-bridge
uv run codex-wechat-bridge doctor
```

3. if login expired, run:

```bash
uv run codex-wechat-bridge auth-openclaw
```

4. if the bridge is healthy but Codex is missing, restore the canonical tmux:

```bash
tmux new -s codex 'codex resume --last -C /home/ft/dev/ft-cosmos --no-alt-screen'
```
