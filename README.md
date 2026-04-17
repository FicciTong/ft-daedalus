# ft-daedalus

**English name:** Daedalus  
**Chinese name:** 天工

`ft-daedalus` is the **operator / tooling repo** under `ft-cosmos` governance.
It is a public tools repo for owner/operator surfaces and small practical
runtime utilities. It is **not** limited to one tool forever.

The current canonical tool in this repo is:

- **`daedalus-wechat`** — a WeChat operator surface for one canonical local
  live `tmux` runtime, with optional switching across multiple local live
  sessions

> 📱 WeChat on your phone  
> 🖥️ Codex in your local `tmux`  
> 🔁 One active live session at a time

[中文说明 / Chinese Guide](./README.zh-CN.md)

Today, `daedalus-wechat` bridges a **local live tmux session** into WeChat
using the official Tencent Weixin `iLink bot` route.

Current mainline truth:

- Tencent hosts the upstream `iLink bot` service
- `ft-daedalus` now talks to that upstream directly
- the bridge remains owner-facing and repo-native

This is **not** a cloud-task wrapper. It preserves **local session continuity**
by routing WeChat messages into one active local live tmux shell:

- default canonical tmux session name: `codex`
- live agent inside that shell: local `codex`
- WeChat acts as a remote operator surface for that same local shell
- if you intentionally manage more than one live tmux session under the same
  workspace, WeChat can list and switch them, but still targets only **one
  active session at a time**

That is the **current** shape of the repo, not the permanent limit of the repo.
If `ft-daedalus` grows more tools later, they should live here as separate
operator/tooling surfaces with the same governance posture.

## ✨ At A Glance

| Surface | What You See | What It Is For |
|---|---|---|
| Desktop `tmux codex` | Full live terminal stream | Real-time work, full context, tool chatter |
| WeChat | System / plan / final by default; progress optional | Remote operation from your phone |

If you want mobile progress too:

```text
/notify on
```

WeChat message icons:

- `⚙️` = bridge / service / binding / command notices
- `📋` = plan updates
- `⏳` = progress commentary
- `✅` = the round is actually done

Inbound owner input currently supports:

- plain text
- voice messages when WeChat provides transcript text
- image messages with either:
  - direct `image_item.url`
  - encrypted `image_item.media.encrypt_query_param` plus usable AES key fields
  - or a plain CDN fallback attempt when the encrypted query is present but no
    AES key is provided
  - the bridge saves them under `~/.local/state/daedalus-wechat/incoming_media/`
  - then injects the absolute local file path into the active Codex session
  - image payloads that still cannot be reconstructed truthfully continue to
    fail closed

## 🧭 Truthful Boundaries

This bridge:

- does **not** modify Codex
- does **not** live inside `ft-cosmos`
- does **not** use Codex cloud tasks
- does **not** stream many live shells into one WeChat chat at once (unless
  group mode is explicitly enabled)
- **does** use the official Tencent Weixin iLink upstream
- **does** treat workspace live tmux sessions as switchable runtime targets,
  with `tmux codex` as the canonical default
- **does** mirror desktop-originated final replies back to WeChat once the chat
  context is bound

Future lane for later reliability hardening:

- [WECHAT_CHANNEL_RELIABILITY_FUTURE_LANE.md](./WECHAT_CHANNEL_RELIABILITY_FUTURE_LANE.md)

## 🧠 Mental Model

There are two surfaces, but only **one active live owner at a time**:

1. **Desktop live owner**
   - usually `tmux attach -t codex`
   - or attach to whichever live tmux session you intentionally switched to
   - shows everything: prompt injection, live model output, tool chatter

2. **WeChat operator surface**
   - sends messages into that same local Codex session
   - receives **system / plan / final by default**
   - progress is opt-in via `/notify on`
   - does **not** receive raw tool logs, bottom status bar noise, or terminal
     junk

So:

- if you want the full live stream, look at desktop tmux
- if you want remote control from your phone, use WeChat
- if you want desktop-originated final replies to come back to WeChat, first
  send any normal message or command once so the current chat context is bound
- if you manually `resume` a different thread inside the currently active tmux
  session, the owner-facing binding still stays on that **tmux session**, while
  the bridge follows the current live thread under it
- if you intentionally run multiple live tmux sessions under the workspace,
  `/sessions` and `/switch` let WeChat bind to a different one

## 🧰 Prerequisites

You need these on the machine that owns the local Codex session:

- `codex`
- `tmux`
- Python `3.13+`
- `uv`
- WeChat on your phone

Quick checks:

```bash
codex --version
tmux -V
python3 --version
uv --version
```

Current truthful read:

- Tencent's official upstream is the `iLink bot` route
- `daedalus-wechat` now bootstraps directly against that route

## 🚀 Install

```bash
cd ~/dev
git clone https://github.com/FicciTong/ft-daedalus.git
cd ft-daedalus
uv sync
```

## ⚡ Fastest Install For A Friend

If you want to hand this to someone else, the shortest install path is:

```bash
cd ~/dev/ft-cosmos/ft-daedalus
bash scripts/install-user-service.sh
```

This script:

1. checks required commands (`codex`, `tmux`, `python3`, `uv`,
   `systemctl`)
2. runs `uv sync`
3. installs the user systemd unit
4. creates `~/.config/daedalus-wechat.env` if missing
5. runs the official WeChat QR login flow
6. restarts the bridge
7. runs bridge doctor

If you only want the health summary later:

```bash
cd ~/dev/ft-cosmos/ft-daedalus
bash scripts/doctor.sh
```

## 🔐 Official WeChat Login

The canonical login path for this bridge is now:

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat auth-ilink
```

What this does:

1. calls Tencent's official iLink QR login endpoints directly
2. waits for scan confirmation
3. writes the resulting account into the bridge state dir
4. reloads the running bridge service so the new token takes effect immediately

By default the bridge stores its imported account at:

```bash
~/.local/state/daedalus-wechat/account.json
```

If `doctor` later reports `errcode=-14` / session timeout, rerun:

```bash
uv run daedalus-wechat auth-ilink
```

If outbound sends later fail with `ret=-2`, the bridge now automatically retries
once **without** `context_token`. This keeps delivery alive even when the old
chat context expires. If that still fails, the bridge now parks the pending
message instead of hammering the queue every second, and waits for the next
inbound WeChat message to refresh binding. If you still do not see a message,
send:

```bash
/status
/recent 6
```

## 🛡️ Security Boundary

By default, if you do nothing, the bridge allows **no sender** to control the
bot conversation.

If this machine matters, configure an allowlist in:

```bash
~/.config/daedalus-wechat.env
```

Example:

```bash
DAEDALUS_WECHAT_ALLOWED_USERS=o9cq80y6O1DAYqilESlM_NbeqtTc@im.wechat
```

You can provide multiple users, comma-separated:

```bash
DAEDALUS_WECHAT_ALLOWED_USERS=user-a@im.wechat,user-b@im.wechat
```

After changing the env file:

```bash
systemctl --user restart daedalus-wechat
```

Without `DAEDALUS_WECHAT_ALLOWED_USERS`, inbound control is fail-closed and the
bridge only rejects commands.

You can verify the current local control posture with:

```bash
uv run daedalus-wechat security-drill
```

That drill emits a machine-readable report under `var/reports/bridge/` and
verifies that an unauthorized sender is rejected before bind/prompt injection.

## 🛟 Reliability Guardrails

The bridge now has four built-in reliability layers:

1. **poll-loop retry instead of false watchdog kills**
   - long-poll failures are logged as `poll_error` and retried in-process
   - the service still runs under `systemd` with `Restart=always`, but we no
     longer use a watchdog that can misread healthy long-polls as hangs
2. **stale context retry**
   - if WeChat rejects a send with `ret=-2`, the bridge retries once without
     `context_token`
3. **bound-context-first mirroring**
   - mirrored desktop `progress / plan / final` now prefer the latest bound
     inbound `context_token` first
   - the WeChat client still falls back through its retry logic when the token
     has gone stale
   - immediate command replies (for example `/status`) still use the live
     inbound context when available
4. **runtime-native final capture + pending outbox**
   - final replies are captured from runtime-native state sources:
     - Codex JSONL rollout
     - OpenCode sqlite/db
     - Claude project JSONL
   - if delivery still fails, the message is queued locally
   - queue entries are deduplicated by message identity instead of multiplying
     on repeated retry failures
   - queued backlog is now partitioned by owner-facing `tmux` session, not
     only tagged by thread id
   - inactive-session backlog stays parked until you `/switch` to that tmux,
     instead of being flushed into the currently active session chat flow
   - mirrored desktop backlog is preserved in queue order; it is no longer
     collapsed down to only the newest progress item for a thread
   - if WeChat still rejects the send with `ret=-2`, background retry pauses
     and waits for the next inbound WeChat message instead of retry-thrashing
   - the bridge still flushes pending messages aggressively when later inbound
     traffic refreshes the live chat binding
   - owner-side backlog recovery is now automatic; no manual `/queue` /
     `/catchup` trigger is required
5. **asynchronous prompt lane + voice fallback**
   - WeChat prompts are queued and processed by a dedicated worker, so a long
     running prompt no longer blocks later `/status` or `/help`
   - if WeChat delivers a voice message without usable transcript text, the
     bridge still refreshes binding/flushes pending messages and replies with a
     truthful hint instead of silently dropping the event

You can also pace outbound delivery more conservatively with:

```bash
DAEDALUS_WECHAT_MIN_SEND_INTERVAL_SECONDS=0.5
```

That value defaults to `0.5` seconds and applies to all WeChat sends.

Last-resort operator recovery is still:

```bash
/status
/recent 6
/log 10
```

## 🤖 Agent-Friendly Deploy Path

If another coding agent is setting this up for the owner, the shortest truthful path is:

```bash
cd ~/dev/ft-cosmos/ft-daedalus
bash scripts/install-user-service.sh
```

Then verify:

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat doctor
```

Then from WeChat:

```text
/status
/sessions
/switch codex
```

## 🖥️ Canonical Desktop Session

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

## ▶️ Run The Bridge

Foreground:

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat run
```

Health check:

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat doctor
```

## ⚙️ Install As A User Service

This repo includes a user-level systemd unit:

```bash
mkdir -p ~/.config/systemd/user
cp ops/systemd/user/daedalus-wechat.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now daedalus-wechat
```

The bridge reads:

```bash
~/.config/daedalus-wechat.env
```

That is the canonical place for both foreground CLI and background service:

- `DAEDALUS_WECHAT_DEFAULT_CWD`
- `DAEDALUS_WECHAT_TMUX_SESSION`
- `DAEDALUS_WECHAT_CODEX_BIN`
- `DAEDALUS_WECHAT_CODEX_STATE_DB`
- `DAEDALUS_WECHAT_OPENCODE_BIN`
- `DAEDALUS_WECHAT_OPENCODE_STATE_DB`
- `DAEDALUS_WECHAT_ALLOWED_USERS`
- `DAEDALUS_WECHAT_PROGRESS_UPDATES`
- `DAEDALUS_WECHAT_TMUX_SESSION`

Useful commands:

```bash
systemctl --user status daedalus-wechat
systemctl --user restart daedalus-wechat
journalctl --user -u daedalus-wechat -n 100 --no-pager
```

## 💬 WeChat Commands

The bridge accepts both `/command` and `\\command`.

Commands:

- `/help`
- `/menu`
- `/status`
- `/health`
- `/notify on|off|status`
- `/recent [n]`
- `/recent after <seq>`
- `/recent all [n]`
- `/recent all after <seq>`
- `/sessions`
- `/new [label]`  (bind canonical live runtime; does not create tmux)
- `/switch <index|thread_id-prefix|label|tmux>`
- `/switch group`  (enter group mode — see below)
- `/members`  (list live participants in group mode)
- `/attach-last`
- `/stop`

For scripts or non-bridge sessions that still need to push a message into the
currently bound WeChat chat, use:

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat send-bound "hello from desktop"
```

Plain text messages are sent to whatever supported live runtime is **currently active
inside the active live tmux session**.

### Reverse-pushing files, images, or videos

`send-bound` can also push a binary attachment to the currently bound WeChat
chat. Flags are mutually exclusive (pick one at a time):

```bash
# file (any mime type): ~/report.pdf delivered as a WeChat file message
uv run daedalus-wechat send-bound --file ~/report.pdf

# image: ~/chart.png delivered as an inline image
uv run daedalus-wechat send-bound --image ~/chart.png

# video: ~/demo.mp4 delivered as an inline video (requires ffmpeg + ffprobe)
uv run daedalus-wechat send-bound --video ~/demo.mp4
```

Preconditions:

- The chat must have been bound at least once — owner has sent ≥1 inbound to
  the bot so `bound_user_id` is persisted in `state.json`.
- `--video` needs `ffmpeg` and `ffprobe` on `PATH` (used to extract the first
  frame as thumbnail and read the duration in milliseconds).

Pipeline (iLink bot `openclaw-weixin` CDN flow):

1. Read bytes, compute raw MD5, generate a random 16-byte AES-128 key.
2. AES-128-ECB encrypt locally (via `openssl enc`) with PKCS7 padding.
3. `POST /ilink/bot/getuploadurl` → presigned `upload_param`.
4. `POST {cdn}/upload?encrypted_query_param=<upload_param>&filekey=<filekey>`
   with the ciphertext. WeChat returns the `x-encrypted-param` header.
5. `POST /ilink/bot/sendmessage` with the corresponding `image_item`,
   `file_item`, or `video_item` entry.

Observability:

- Every send writes a `relay_outgoing` (or `relay_failed`) entry to
  `events.jsonl` with `trace_id`, `media_kind`, `path`, `file_name`,
  `size_bytes`, `md5`, `content_type`, and `latency_ms`. On failure the entry
  also carries `stage` (one of `local_encrypt`, `getuploadurl`, `cdn_upload`,
  `sendmessage`, `video_probe`, `unknown`) and the raw `error` string so
  agents can grep for which pipeline step broke.
- The delivery ledger (`deliveries.jsonl`) records a human-readable line per
  send, e.g. `[image] chart.png`.

If you send a WeChat image, the bridge now tries the shortest truthful path in
this order:

1. use direct `image_item.url` when present
2. otherwise use encrypted CDN media (`encrypt_query_param` + AES key) and
   decrypt it locally

When successful, the bridge saves the image into the local state dir and
injects the absolute file path into the active Codex session so the live agent
can inspect the image from disk.

Examples:

```text
/health
/notify on
/recent
/status
/sessions
/switch 1
/switch attached-last
/switch codex
/switch 123
帮我检查今天的 package outcome
```

Phone-friendly semantics:

- `/health` = is the bridge / tmux / thread healthy right now
- `/notify` = choose `system+plan+progress+final` or `system+plan+final`
- `/recent` = replay from the permanent delivery ledger
- `/recent after <seq>` = continue from a known ledger position within the current active tmux scope
- `/recent all` = read across all session scopes when you explicitly want the mixed global view
- `/status` = which live session am I currently attached to
- `/sessions` = short switchable list of currently live workspace tmux sessions
- `send-bound` = explicit desktop/session-side push into the current bound
  WeChat chat

## 👥 Group Mode (Virtual Room Chat)

Group mode turns a single WeChat private chat into a virtual multi-agent room.
It is **additive** — personal `/switch <tmux>` mode stays intact and is not
replaced.

### Enter group mode

```text
/switch group
```

This enables room mode. Your current personal active session is preserved.

### List participants

```text
/members
```

Shows all currently live tmux sessions with supported runtimes.

### Send to a specific agent

```text
@claude help me review this code
@kimi0 算一下 1+5
```

Messages without `@agent` are **not delivered** in group mode. The bridge
prompts you to specify a target.

### Voice routing

In group mode, voice messages are automatically matched to agents. Say the
tmux session name at the beginning of your voice message:

- "claude 帮我看看" → routes to `claude`
- "kimi 零 算一下" → routes to `kimi0`
- "kimi 二 做个任务" → routes to `kimi2`

The matching is **fully dynamic** — it scans the actual live tmux session
names, normalizes spaces and Chinese/English digit words, and applies
common voice transcription corrections (e.g. "cloud" → "claude").

Tips for better voice matching:
- Use Chinese digits (零一二三) instead of English (zero one two three)
- Say the full session name when possible
- If matching fails, use `@agent` text input as fallback

### Images in group mode

Send images first, then tell an agent to look at them:

```text
(send photo)
@kimi2 看一下最近的照片
```

Images are saved with timestamp prefixes for chronological ordering. When
routing a message to an agent, the 5 most recent images are automatically
attached to the prompt with their file paths.

### Tagged replies

All agent replies in group mode are tagged with the speaker name:

```
[claude] ✅ The code looks good.
[kimi0] ✅ 1+5=6
```

### Exit group mode

```text
/switch <tmux>   (switch to personal mode with a specific session)
/stop            (clear everything)
```

## 🗓️ Daily Operating Guide

### Start of day

1. make sure `tmux codex` exists
2. make sure Codex is running inside it
3. make sure the bridge service is up
4. use WeChat `/status` to confirm active session

### While outside

- talk to WeChat normally
- use `/status` if you want to confirm which session is active
- use `/sessions` and `/switch` only if you intentionally manage more than one
  live tmux session under the same workspace

### Back at the desktop

Attach to the canonical owner:

```bash
tmux attach -t codex
```

Do **not** expect an arbitrary unrelated shell to live-sync into the bridge.

Only tmux sessions that look like live supported runtimes **and** belong to the
configured workspace are listed as switchable targets.

## 🧩 Optional Environment Variables

- `DAEDALUS_WECHAT_DEFAULT_CWD`
- `DAEDALUS_WECHAT_STATE_DIR`
- `DAEDALUS_WECHAT_ACCOUNT_FILE`
- `DAEDALUS_WECHAT_CODEX_BIN`
- `DAEDALUS_WECHAT_OPENCODE_BIN`
- `DAEDALUS_WECHAT_CODEX_STATE_DB`
- `DAEDALUS_WECHAT_OPENCODE_STATE_DB`
- `DAEDALUS_WECHAT_PROGRESS_UPDATES`
- `DAEDALUS_WECHAT_TMUX_SESSION`

If `DAEDALUS_WECHAT_CODEX_STATE_DB` is not set, the bridge now resolves the
Codex state DB by:

1. preferring `~/.codex/state.sqlite` when present
2. otherwise picking the newest matching `~/.codex/state*.sqlite`

This avoids baking `state_5.sqlite` in as the only default truth.

## 🧯 Failure Recovery

If WeChat stops replying:

1. check the service:

```bash
systemctl --user status daedalus-wechat
```

2. run doctor:

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat doctor
```

3. if login expired:

```bash
uv run daedalus-wechat auth-ilink
```

4. if the bridge is healthy but Codex is missing, restore the canonical tmux:

```bash
tmux new -s codex 'codex resume --last -C /home/ft/dev/ft-cosmos --no-alt-screen'
```
