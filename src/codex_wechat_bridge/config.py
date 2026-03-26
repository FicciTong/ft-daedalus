from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class BridgeConfig:
    codex_bin: str
    account_file: Path
    state_dir: Path
    default_cwd: Path
    openclaw_profile: str
    canonical_tmux_session: str
    allowed_users: frozenset[str]
    poll_timeout_ms: int = 35_000
    text_chunk_limit: int = 3500

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def event_log_file(self) -> Path:
        return self.state_dir / "events.jsonl"

    @property
    def openclaw_state_dir(self) -> Path:
        if self.openclaw_profile == "default":
            return Path.home() / ".openclaw"
        return Path.home() / f".openclaw-{self.openclaw_profile}"

    @property
    def openclaw_accounts_dir(self) -> Path:
        return self.openclaw_state_dir / "openclaw-weixin" / "accounts"


def _parse_allowed_users(raw: str) -> frozenset[str]:
    entries = []
    normalized = raw.replace("\n", ",")
    for item in normalized.split(","):
        value = item.strip()
        if value:
            entries.append(value)
    return frozenset(entries)


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_config() -> BridgeConfig:
    env_file = Path(
        os.environ.get(
            "CODEX_WECHAT_BRIDGE_ENV_FILE", "~/.config/codex-wechat-bridge.env"
        )
    ).expanduser()
    file_env = _load_env_file(env_file)
    default_cwd = Path(
        os.environ.get(
            "CODEX_WECHAT_BRIDGE_DEFAULT_CWD",
            file_env.get("CODEX_WECHAT_BRIDGE_DEFAULT_CWD", "/home/ft/dev/ft-cosmos"),
        )
    ).expanduser()
    state_dir = Path(
        os.environ.get(
            "CODEX_WECHAT_BRIDGE_STATE_DIR", "~/.local/state/codex-wechat-bridge"
        )
    ).expanduser()
    account_file = Path(
        os.environ.get("CODEX_WECHAT_BRIDGE_ACCOUNT_FILE", str(state_dir / "account.json"))
    ).expanduser()
    codex_bin = os.environ.get(
        "CODEX_WECHAT_BRIDGE_CODEX_BIN",
        file_env.get("CODEX_WECHAT_BRIDGE_CODEX_BIN", "codex"),
    )
    openclaw_profile = os.environ.get(
        "CODEX_WECHAT_BRIDGE_OPENCLAW_PROFILE",
        file_env.get("CODEX_WECHAT_BRIDGE_OPENCLAW_PROFILE", "codex-wechat-bridge"),
    ).strip() or "codex-wechat-bridge"
    canonical_tmux_session = (
        os.environ.get(
            "CODEX_WECHAT_BRIDGE_TMUX_SESSION",
            file_env.get("CODEX_WECHAT_BRIDGE_TMUX_SESSION", "codex"),
        ).strip()
        or "codex"
    )
    allowed_users = _parse_allowed_users(
        os.environ.get(
            "CODEX_WECHAT_BRIDGE_ALLOWED_USERS",
            file_env.get("CODEX_WECHAT_BRIDGE_ALLOWED_USERS", ""),
        )
    )
    return BridgeConfig(
        codex_bin=codex_bin,
        account_file=account_file,
        state_dir=state_dir,
        default_cwd=default_cwd,
        openclaw_profile=openclaw_profile,
        canonical_tmux_session=canonical_tmux_session,
        allowed_users=allowed_users,
    )
