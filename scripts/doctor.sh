#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"
uv run daedalus-wechat doctor
echo
systemctl --user status daedalus-wechat --no-pager | sed -n '1,18p'
