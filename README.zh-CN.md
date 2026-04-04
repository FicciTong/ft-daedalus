# ft-daedalus

**英文名：** Daedalus  
**中文名：** 天工

`ft-daedalus` 是受 `ft-cosmos` 治理的 **operator / tooling 仓库**。  
它是一个公开的工具仓库，用来承载 owner/operator surface 和一些小而真
的运行工具。它**不代表以后只有这一件工具**。

当前这个仓库里已经正式落下来的 canonical 工具是：

- **`daedalus-wechat`** —— 把微信接成一个 canonical 本地 live `tmux`
  runtime 的 operator surface，并支持在多个本地 live session 之间切换

> 📱 手机微信  
> 🖥️ 本地 `tmux` 里的 live runtime（如 Codex / OpenCode / Claude）  
> 🔁 同一时刻只盯一个 active live session

[English Version](./README.md)

今天，`daedalus-wechat` 这件工具把**本地 live tmux 会话**桥接到微信，
走的是腾讯官方开放出来的 `iLink bot` 链路。

当前主线真相：

- 腾讯提供官方 `iLink bot` 上游
- `ft-daedalus` 现在直接对接这条上游
- 这台机器已经不再需要安装 OpenClaw 宿主
- bridge 仍然只是 owner-facing 的本地 operator surface

它**不是**云端任务转发器，也**不是**“换个平台聊同一个机器人”的空壳。  
它的核心目标只有一个：

> **让微信成为你本机 live session 的远程操作入口。**

默认约定：

- 默认 canonical tmux 名：`codex`
- tmux 里跑的 agent/runtime：本地 live CLI（当前支持 Codex / OpenCode / Claude）
- 微信是远程 operator surface，不是另一个独立 bot
- 如果你有意识地维护多个同 workspace 下的 live tmux session，微信可以
  list / switch，但仍然一次只对准一个 active session

这只是仓库当前已经落成的第一件工具，不是这个仓库的永久边界。以后如果
`ft-daedalus` 再长出别的工具，它们也应该作为独立 operator/tooling
surface 落在这里。

## ✨ 一眼看懂

| 表面 | 你会看到什么 | 它的用途 |
|---|---|---|
| 桌面 `tmux` live runtime | 完整 live terminal stream | 全量输出、工具过程、真正的实时工作界面 |
| 微信 | 默认只收 system / plan / final；progress 可选开启 | 外出时下任务、收结果 |

如果你想让微信也收 progress：

```text
/notify on
```

微信消息图标：

- `⚙️` = bridge / 服务 / 绑定 / 命令提示
- `📋` = plan 更新
- `⏳` = progress commentary
- `✅` = 这一轮真的结束了

当前 owner 入站支持：

- 普通文本
- 微信提供转写文本的语音
- 图片消息，支持两种最短正确路径：
  - 直接 `image_item.url`
  - `image_item.media.encrypt_query_param` + 可用 AES key 的加密图片
  - 如果只有加密 query、没有 AES key，也会先按 plain CDN 路径尝试一次
  - bridge 会把图片落到 `~/.local/state/daedalus-wechat/incoming_media/`
  - 再把绝对本地路径注入当前 active live session
  - 仍然无法被 truthfully 重建的图片继续 fail-closed

## 🧭 这套东西的真实边界

它：

- **不会**修改底层模型 CLI 本体
- **不会**放进 `ft-cosmos`
- **不会**接管 repo 治理
- **不会**把多个 live shell 同时混流到一个聊天窗口
- **会**使用腾讯官方 iLink 上游
- **不会**把 OpenClaw 继续当长期必需宿主依赖
- **会**把 workspace 下的 live tmux session 当成可切换 runtime target，
  同时保留一个 canonical default tmux
- **会**在当前微信会话绑定后，把桌面侧产生的 final reply 镜像回微信

## 🧠 正确理解方式

你需要把它理解成两层表面、同一时刻一个 active owner：

### 1. 桌面 live owner

```bash
tmux attach -t codex
```

这里看到的是完整实时流：

- prompt 注入
- 模型 live 输出
- 工具调用
- 终端噪声

### 2. 微信 operator surface

这里不是终端镜像，而是：

- 消息进同一个本地 live session
- 微信收到的是：
  - 默认 `system / plan / final`
  - `progress` 需要 `/notify on` 才开启
- 不会把工具原始日志、状态栏、底部噪声直接刷给你

所以：

- 想看完整实时流：看桌面 tmux
- 想手机远程操作：看微信
- 想让桌面侧 final 回到微信：先在微信发任意一句话或命令，把当前 chat context 绑上
- 如果你在当前 active tmux session 里手动 `resume` 到别的 thread，owner-facing 绑定仍然留在这个 **tmux session** 上，bridge 只是在内部跟随它下面当前 live 的 thread
- 如果你真的维护多个 live tmux session，可以用 `/sessions` / `/switch` 在微信里切换

## 🧰 前置依赖

装在那台拥有本地 live session 的机器上：

- `codex`、`opencode` 或 `claude`
- `tmux`
- Python `3.13+`
- `uv`
- 你手机上的微信

快速检查：

```bash
codex --version
opencode --version
tmux -V
python3 --version
uv --version
```

这里现在的真话是：

- 腾讯官方上游是 `iLink bot`
- bridge 现在直接对接这条上游
- 当前主线不再需要 OpenClaw 宿主

## 🚀 安装

```bash
cd ~/dev
git clone https://github.com/FicciTong/ft-daedalus.git
cd ft-daedalus
uv sync
```

## ⚡ 给朋友用的最快安装方式

如果你要把这套东西交给别人装，最短路径就是：

```bash
cd ~/dev/ft-cosmos/ft-daedalus
bash scripts/install-user-service.sh
```

这个脚本会自动做：

1. 检查依赖命令（`codex`、`tmux`、`python3`、`uv`、`systemctl`）
2. 执行 `uv sync`
3. 安装 user-level systemd 服务
4. 创建 `~/.config/daedalus-wechat.env`
5. 走官方微信扫码登录
6. 重启 bridge
7. 运行 doctor 自检

如果只想单独看健康状态：

```bash
cd ~/dev/ft-cosmos/ft-daedalus
bash scripts/doctor.sh
```

## 🔐 官方微信登录

canonical 登录命令现在是：

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat auth-ilink
```

它会自动：

1. 直接调用腾讯官方 iLink 二维码登录接口
2. 等待扫码确认
3. 把结果写入 bridge 的本地状态目录
4. 自动重载正在运行的 bridge service，让新 token 立刻生效

默认账号文件位置：

```bash
~/.local/state/daedalus-wechat/account.json
```

如果以后 doctor 报：

- `errcode=-14`
- 或登录超时

直接重新跑一次：

```bash
uv run daedalus-wechat auth-ilink
```

如果后面微信发不出去并出现 `ret=-2`，bridge 现在会自动再试一次：
- 第二次发送会去掉 `context_token`
- 这样旧聊天上下文过期时，消息也尽量不要直接丢
- 如果这样还是失败，bridge 会先把消息停在本地队列里，等下一条微信消息刷新绑定后再继续发，不会再后台每秒死命重试

如果你还是没看到，先发：

```bash
/status
/recent 6
```

当前主线不需要 OpenClaw profile。

## 🤖 给别的 Agent 的最短部署路径

如果是别的 coding agent 帮 owner 安装，这条最短：

```bash
cd ~/dev/ft-cosmos/ft-daedalus
bash scripts/install-user-service.sh
```

然后验证：

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat doctor
```

再在微信里发：

```text
/status
/sessions
/switch codex
```

## 🛡️ 安全边界

默认情况下，如果你不加限制，任何能触达这个 bot 会话的人都能控制它。

如果这台机器重要，请配置 allowlist：

```bash
~/.config/daedalus-wechat.env
```

示例：

```bash
DAEDALUS_WECHAT_ALLOWED_USERS=o9cq80y6O1DAYqilESlM_NbeqtTc@im.wechat
```

多个用户就逗号分隔：

```bash
DAEDALUS_WECHAT_ALLOWED_USERS=user-a@im.wechat,user-b@im.wechat
```

改完后重启：

```bash
systemctl --user restart daedalus-wechat
```

## 🛟 可靠性保障

现在这套 bridge 内置了四层保障：

1. **长轮询内部重试，不再用误杀式 watchdog**
   - 长轮询失败会记成 `poll_error` 并在进程内重试
   - 服务仍然跑在 `systemd` 下，保留 `Restart=always`
   - 但不再使用会把健康长轮询误判成卡死的 watchdog
2. **过期 context 自动重发**
   - 如果微信发送返回 `ret=-2`，bridge 会自动去掉 `context_token` 再试一次
3. **桌面镜像优先吃最新绑定 context**
   - 桌面镜像出来的 `progress / plan / final` 现在会优先使用最新绑定的入站 `context_token`
   - 如果这个 token 已经过期，微信客户端层仍会按重试逻辑继续兜底
   - 即时命令回复（例如 `/status`）也仍然优先使用当前入站 context
4. **runtime 原生 final 捕获 + pending outbox**
   - final 现在优先从 runtime 原生状态里取：
     - Codex JSONL rollout
     - OpenCode sqlite/db
     - Claude project JSONL
   - 如果这样还是发不出去，消息会先落到本地 outbox
   - 相同消息不会因为重复重试而无限堆叠进 outbox
   - 现在 backlog 会按 owner-facing 的 `tmux session` 分区，不再只是挂一个 `thread_id` 标签
   - 非当前 active tmux 的 backlog 会先停在自己的队列里，等你 `/switch` 过去后再冲洗，不会混着刷进当前会话流
   - 桌面镜像 backlog 现在按真实顺序保留，不再把同一 thread 里的旧 progress 静默折叠成只剩最新一条
   - 如果仍然是 `ret=-2`，后台重试会暂停，等下一条微信入站消息刷新 live binding 后再继续冲洗队列
   - 后续如果有新的入站消息刷新了 live binding，bridge 会优先继续冲洗 pending 队列
   - owner 侧 backlog 补发现在走后台自动冲洗，不再需要手写 `/queue` / `/catchup`
5. **prompt 异步队列 + 语音兜底**
   - 微信发来的 prompt 会进入单独 worker 队列处理，所以一条长任务不再把后面的 `/status`、`/help` 一起堵死
   - 如果微信这次只给了语音消息但没有可用转写文本，bridge 仍然会刷新绑定、补发队列，并明确告诉你“这次语音没有可用转写”，而不是静默吞掉

如果你想把发消息节奏再放慢一点，还可以在 env 里设置：

```bash
DAEDALUS_WECHAT_MIN_SEND_INTERVAL_SECONDS=0.5
```

默认就是 `0.5` 秒，所有微信出站消息都走这个节流。

最后兜底的 operator 操作还是：

```bash
/status
/recent 6
/log 10
```

## 🖥️ canonical 桌面会话

这套桥默认认一个 canonical tmux owner：

```bash
tmux new -s codex 'codex resume --last -C /home/ft/dev/ft-cosmos --no-alt-screen'
```

如果已经存在：

```bash
tmux attach -t codex
```

如果你还没有历史 thread：

```bash
tmux new -s codex 'codex -C /home/ft/dev/ft-cosmos --no-alt-screen'
```

纪律非常简单：

- 永远只维护一个 canonical bridge-owned tmux live session
- 不要到处乱开新的 `codex resume` 窗口
- 你要在电脑上看 live，就 attach `tmux codex`

## ▶️ 运行 bridge

前台跑：

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat run
```

健康检查：

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat doctor
```

## ⚙️ 安装成用户服务

仓库自带 user-level systemd unit：

```bash
mkdir -p ~/.config/systemd/user
cp ops/systemd/user/daedalus-wechat.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now daedalus-wechat
```

bridge 读取的 canonical env 文件是：

```bash
~/.config/daedalus-wechat.env
```

这里是前台 CLI 和后台 service 共用的配置入口。

常用命令：

```bash
systemctl --user status daedalus-wechat
systemctl --user restart daedalus-wechat
journalctl --user -u daedalus-wechat -n 100 --no-pager
```

## 💬 微信命令

支持 `/command` 和 `\\command` 两种前缀。

命令有：

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
- `/new [label]`（绑定 canonical live runtime；不会自动新建 tmux）
- `/switch <index|thread_id-prefix|label|tmux>`
- `/attach-last`
- `/stop`

如果是脚本、桌面侧任务、或者像我现在这种不在 bridge owner 里的直连会话，
但你仍然想把一段消息主动推到**当前已绑定**的微信聊天窗口，可以用：

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat send-bound "hello from desktop"
```

普通文本消息会送进**当前 active live tmux session** 里正在活着的受支持 runtime。

示例：

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

如果你发的是微信图片，bridge 现在会按这两个顺序尝试：

1. 直接使用 `image_item.url`
2. 如果没有直链，就走加密 CDN media 下载 + 本地解密

成功后会先把图片落到本地 state dir，再把绝对路径注入当前 active Codex
session，让 live agent 直接从磁盘读图。

手机侧语义：

- `/health` = bridge / tmux / 当前 thread 现在健不健康
- `/notify` = 切 `system+plan+progress+final` 或 `system+plan+final`
- `/recent` = 从永久 delivery ledger 里回看最近几条记录
- `/recent after <seq>` = 在当前 active tmux scope 里，从某个稳定序号之后继续看
- `/recent all` = 只有当你明确要看所有 session 混合视图时才用
- `/status` = 当前接的是哪个 live session
- `/sessions` = 手机可读的 live workspace tmux 列表，用来快速 `/switch 1`
- `send-bound` = 桌面/脚本侧显式把一段消息推到当前绑定微信会话

## 🗓️ 日常使用建议

### 每天开始前

1. 确认 `tmux codex` 在
2. 确认 Codex 在里面跑着
3. 确认 bridge service 正常
4. 微信里发 `/status` 确认当前 active session

### 你在外面的时候

- 直接在微信里正常说话
- 如果不确定接的是谁，就发 `/status`
- 如果你真的在管多个 live tmux session，再用 `/sessions` / `/switch`

### 你回到电脑前的时候

直接 attach canonical owner：

```bash
tmux attach -t codex
```

不要期待另一个独立开的桌面 Codex 窗口会自动和微信实时同步。  
只有看起来像受支持 live runtime 且 cwd 落在 configured workspace 下的 tmux session，才会出现在可切换列表里。

## 🧩 可选环境变量

- `DAEDALUS_WECHAT_DEFAULT_CWD`
- `DAEDALUS_WECHAT_STATE_DIR`
- `DAEDALUS_WECHAT_ACCOUNT_FILE`
- `DAEDALUS_WECHAT_CODEX_BIN`
- `DAEDALUS_WECHAT_OPENCODE_BIN`
- `DAEDALUS_WECHAT_OPENCODE_STATE_DB`
- `DAEDALUS_WECHAT_PROGRESS_UPDATES`
- `DAEDALUS_WECHAT_TMUX_SESSION`

## 🧯 故障恢复

如果微信不回了：

1. 看 service：

```bash
systemctl --user status daedalus-wechat
```

2. 跑 doctor：

```bash
cd ~/dev/ft-cosmos/ft-daedalus
uv run daedalus-wechat doctor
```

3. 如果登录过期：

```bash
uv run daedalus-wechat auth-ilink
```

4. 如果 bridge 健康但 Codex 不在了，重建 canonical tmux：

```bash
tmux new -s codex 'codex resume --last -C /home/ft/dev/ft-cosmos --no-alt-screen'
```
