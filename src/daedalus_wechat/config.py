from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BridgeConfig:
    codex_bin: str
    account_file: Path
    state_dir: Path
    default_cwd: Path
    canonical_tmux_session: str
    allowed_users: frozenset[str]
    progress_updates_default: bool
    opencode_bin: str = "opencode"
    codex_state_db: Path = field(default_factory=lambda: default_codex_state_db())
    codex_state_db_source: str = "default_resolved"
    opencode_state_db: Path = field(default_factory=lambda: default_opencode_state_db())
    opencode_state_db_source: str = "default_resolved"
    poll_timeout_ms: int = 35_000
    text_chunk_limit: int = 3500
    min_send_interval_seconds: float = 0.5
    outbox_retry_interval_seconds: float = 1.0

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def event_log_file(self) -> Path:
        return self.state_dir / "events.jsonl"

    @property
    def delivery_ledger_file(self) -> Path:
        return self.state_dir / "deliveries.jsonl"

    @property
    def incoming_media_dir(self) -> Path:
        return self.state_dir / "incoming_media"

    @property
    def room_transcript_file(self) -> Path:
        return self.state_dir / "room_transcript.jsonl"

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


def _parse_bool(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_float(raw: str | None, *, default: float) -> float:
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _default_workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_codex_state_db() -> Path:
    codex_root = Path.home() / ".codex"
    canonical = codex_root / "state.sqlite"
    if canonical.exists():
        return canonical

    candidates = sorted(
        p for p in codex_root.glob("state*.sqlite") if p.is_file()
    )
    if candidates:
        return max(candidates, key=lambda p: (p.stat().st_mtime, p.name))

    return canonical


def default_opencode_state_db() -> Path:
    return Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def load_config() -> BridgeConfig:
    env_file = Path(
        os.environ.get(
            "DAEDALUS_WECHAT_ENV_FILE", "~/.config/daedalus-wechat.env"
        )
    ).expanduser()
    file_env = _load_env_file(env_file)
    default_cwd = Path(
        os.environ.get(
            "DAEDALUS_WECHAT_DEFAULT_CWD",
            file_env.get(
                "DAEDALUS_WECHAT_DEFAULT_CWD",
                str(_default_workspace_root()),
            ),
        )
    ).expanduser()
    state_dir = Path(
        os.environ.get(
            "DAEDALUS_WECHAT_STATE_DIR", "~/.local/state/daedalus-wechat"
        )
    ).expanduser()
    account_file = Path(
        os.environ.get("DAEDALUS_WECHAT_ACCOUNT_FILE", str(state_dir / "account.json"))
    ).expanduser()
    codex_bin = os.environ.get(
        "DAEDALUS_WECHAT_CODEX_BIN",
        file_env.get("DAEDALUS_WECHAT_CODEX_BIN", "codex"),
    )
    opencode_bin = os.environ.get(
        "DAEDALUS_WECHAT_OPENCODE_BIN",
        file_env.get("DAEDALUS_WECHAT_OPENCODE_BIN", "opencode"),
    )
    env_codex_state_db = os.environ.get("DAEDALUS_WECHAT_CODEX_STATE_DB")
    file_codex_state_db = file_env.get("DAEDALUS_WECHAT_CODEX_STATE_DB")
    if env_codex_state_db and env_codex_state_db.strip():
        codex_state_db_source = "env_explicit"
        raw_codex_state_db = env_codex_state_db
    elif file_codex_state_db and file_codex_state_db.strip():
        codex_state_db_source = "env_file_explicit"
        raw_codex_state_db = file_codex_state_db
    else:
        codex_state_db_source = "default_resolved"
        raw_codex_state_db = str(default_codex_state_db())
    codex_state_db = Path(raw_codex_state_db).expanduser()
    env_opencode_state_db = os.environ.get("DAEDALUS_WECHAT_OPENCODE_STATE_DB")
    file_opencode_state_db = file_env.get("DAEDALUS_WECHAT_OPENCODE_STATE_DB")
    if env_opencode_state_db and env_opencode_state_db.strip():
        opencode_state_db_source = "env_explicit"
        raw_opencode_state_db = env_opencode_state_db
    elif file_opencode_state_db and file_opencode_state_db.strip():
        opencode_state_db_source = "env_file_explicit"
        raw_opencode_state_db = file_opencode_state_db
    else:
        opencode_state_db_source = "default_resolved"
        raw_opencode_state_db = str(default_opencode_state_db())
    opencode_state_db = Path(raw_opencode_state_db).expanduser()
    canonical_tmux_session = (
        os.environ.get(
            "DAEDALUS_WECHAT_TMUX_SESSION",
            file_env.get("DAEDALUS_WECHAT_TMUX_SESSION", "codex"),
        ).strip()
        or "codex"
    )
    allowed_users = _parse_allowed_users(
        os.environ.get(
            "DAEDALUS_WECHAT_ALLOWED_USERS",
            file_env.get("DAEDALUS_WECHAT_ALLOWED_USERS", ""),
        )
    )
    progress_updates_default = _parse_bool(
        os.environ.get(
            "DAEDALUS_WECHAT_PROGRESS_UPDATES",
            file_env.get("DAEDALUS_WECHAT_PROGRESS_UPDATES"),
        ),
        default=False,
    )
    min_send_interval_seconds = _parse_float(
        os.environ.get(
            "DAEDALUS_WECHAT_MIN_SEND_INTERVAL_SECONDS",
            file_env.get("DAEDALUS_WECHAT_MIN_SEND_INTERVAL_SECONDS"),
        ),
        default=0.5,
    )
    outbox_retry_interval_seconds = _parse_float(
        os.environ.get(
            "DAEDALUS_WECHAT_OUTBOX_RETRY_INTERVAL_SECONDS",
            file_env.get("DAEDALUS_WECHAT_OUTBOX_RETRY_INTERVAL_SECONDS"),
        ),
        default=1.0,
    )
    return BridgeConfig(
        codex_bin=codex_bin,
        opencode_bin=opencode_bin,
        account_file=account_file,
        state_dir=state_dir,
        default_cwd=default_cwd,
        codex_state_db=codex_state_db,
        codex_state_db_source=codex_state_db_source,
        opencode_state_db=opencode_state_db,
        opencode_state_db_source=opencode_state_db_source,
        canonical_tmux_session=canonical_tmux_session,
        allowed_users=allowed_users,
        progress_updates_default=progress_updates_default,
        min_send_interval_seconds=min_send_interval_seconds,
        outbox_retry_interval_seconds=outbox_retry_interval_seconds,
    )
