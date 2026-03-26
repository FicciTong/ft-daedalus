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

So:

- if you want the full live stream, look at desktop tmux
- if you want remote control from your phone, use WeChat

## Prerequisites

You need these on the machine that owns the local Codex session:

- `codex`
- `tmux`
- Python `3.13+`
- `uv`
- `openclaw`
- WeChat on your phone

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

## Install

```bash
cd ~/dev
git clone https://github.com/FicciTong/codex-wechat-bridge.git
cd codex-wechat-bridge
uv sync
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
- `/sessions`
- `/new [label]`
- `/switch <index|thread_id-prefix|label|tmux>`
- `/attach-last`
- `/stop`

Plain text messages are sent to whatever Codex thread is **currently active
inside `tmux codex`**.

Examples:

```text
/status
/sessions
/switch 1
/switch attached-last
/switch codex
帮我检查今天的 package outcome
```

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
