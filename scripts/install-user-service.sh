#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_SRC="$ROOT_DIR/ops/systemd/user/codex-wechat-bridge.service"
SERVICE_DST="$HOME/.config/systemd/user/codex-wechat-bridge.service"
ENV_FILE="$HOME/.config/codex-wechat-bridge.env"
DEFAULT_CWD="${CODEX_WECHAT_BRIDGE_DEFAULT_CWD:-$HOME/dev/ft-cosmos}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

require_cmd python3
require_cmd uv
require_cmd tmux
require_cmd openclaw
require_cmd systemctl
require_cmd codex

mkdir -p "$HOME/.config/systemd/user"

cd "$ROOT_DIR"
uv sync

if [[ ! -f "$ENV_FILE" ]]; then
  cat >"$ENV_FILE" <<EOF
# Canonical desktop working directory for the bridge-owned Codex session.
CODEX_WECHAT_BRIDGE_DEFAULT_CWD=$DEFAULT_CWD

# Canonical tmux owner for the live desktop shell.
CODEX_WECHAT_BRIDGE_TMUX_SESSION=codex

# Optional: set an explicit codex binary path if plain \`codex\` is not on PATH.
# CODEX_WECHAT_BRIDGE_CODEX_BIN=$HOME/.local/bin/codex

# Optional: lock the bridge to a specific WeChat sender or senders.
# Comma-separated values, for example:
# CODEX_WECHAT_BRIDGE_ALLOWED_USERS=o9cq80y6O1DAYqilESlM_NbeqtTc@im.wechat
EOF
fi

install -m 0644 "$SERVICE_SRC" "$SERVICE_DST"
systemctl --user daemon-reload
systemctl --user enable codex-wechat-bridge

echo "==> official WeChat login"
uv run codex-wechat-bridge auth-openclaw

echo "==> restart bridge service"
systemctl --user restart codex-wechat-bridge

echo "==> bridge doctor"
uv run codex-wechat-bridge doctor

echo
echo "installed successfully"
echo "env file: $ENV_FILE"
echo "service:  $SERVICE_DST"
echo
echo "desktop live owner:"
echo "  tmux new -s codex 'codex resume --last -C $DEFAULT_CWD --no-alt-screen'"
echo "or"
echo "  tmux attach -t codex"
