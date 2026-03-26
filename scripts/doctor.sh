#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"
uv run codex-wechat-bridge doctor
echo
systemctl --user status codex-wechat-bridge --no-pager | sed -n '1,18p'
