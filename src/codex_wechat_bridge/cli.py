from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import subprocess
import shutil
import sys
from pathlib import Path

from .config import load_config
from .daemon import BridgeDaemon
from .live_session import LiveCodexSessionManager
from .state import BridgeState
from .wechat_api import WeChatAccount, WeChatClient


OPENCLAW_WEIXIN_PLUGIN_SPEC = "@tencent-weixin/openclaw-weixin"


def _chunk_text(text: str, limit: int) -> list[str]:
    body = text.strip()
    if not body:
        return []
    if len(body) <= limit:
        return [body]
    chunks: list[str] = []
    current = body
    while current:
        chunks.append(current[:limit])
        current = current[limit:]
    return chunks


def _send_bound_text(
    config,
    state: BridgeState,
    text: str,
    *,
    client: WeChatClient | None = None,
) -> int:
    if not state.bound_user_id or not state.bound_context_token:
        raise RuntimeError("No bound WeChat chat context. Send /status from WeChat first.")
    chunks = _chunk_text(text, config.text_chunk_limit)
    if not chunks:
        raise RuntimeError("No text to send.")
    wechat = client or WeChatClient(
        WeChatAccount.load(config.account_file),
        min_send_interval_seconds=config.min_send_interval_seconds,
    )
    for chunk in chunks:
        try:
            wechat.send_text(
                to_user_id=state.bound_user_id,
                context_token=None,
                text=chunk,
            )
            event_kind = "relay_outgoing"
        except Exception as exc:  # noqa: BLE001
            state.enqueue_pending(to_user_id=state.bound_user_id, text=chunk)
            state.save(config.state_file)
            event_kind = "relay_queued"
            chunk = f"{chunk[:400]} [queued: {str(exc)[:160]}]"
        config.state_dir.mkdir(parents=True, exist_ok=True)
        with config.event_log_file.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "ts": datetime.now(UTC).isoformat(),
                        "kind": event_kind,
                        "payload": {
                            "to": state.bound_user_id,
                            "text": chunk[:400],
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-wechat-bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Run the WeChat bridge daemon")
    sub.add_parser("status", help="Print current bridge state")
    sub.add_parser("doctor", help="Check bridge prerequisites and current auth health")
    send_bound = sub.add_parser(
        "send-bound",
        help="Send text to the currently bound WeChat chat context",
    )
    send_bound.add_argument("text", nargs="?", help="Text to send")
    send_bound.add_argument(
        "--stdin",
        action="store_true",
        help="Read text from stdin",
    )
    sub.add_parser(
        "auth-openclaw",
        help="Run official openclaw-weixin login under the dedicated bridge profile, then import the account",
    )
    sub.add_parser(
        "import-openclaw-account",
        help="Import the newest official OpenClaw Weixin account into the bridge state dir",
    )
    return parser


def _import_latest_openclaw_account(config, state: BridgeState) -> int:
    root = config.openclaw_accounts_dir
    candidates = sorted(
        (
            p
            for p in root.glob("*.json")
            if not p.name.endswith(".sync.json")
            and not p.name.endswith(".context-tokens.json")
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
        )
    if not candidates:
        raise RuntimeError(
            "No OpenClaw Weixin account found. Run `codex-wechat-bridge auth-openclaw` first."
        )
    account_src = candidates[0]
    sync_src = root / f"{account_src.stem}.sync.json"
    config.state_dir.mkdir(parents=True, exist_ok=True)
    account_obj = json.loads(account_src.read_text())
    if not account_obj.get("accountId"):
        account_obj["accountId"] = account_src.stem
    config.account_file.write_text(
        json.dumps(account_obj, ensure_ascii=False, indent=2) + "\n"
    )
    if sync_src.exists():
        sync_obj = json.loads(sync_src.read_text())
        state.get_updates_buf = str(sync_obj.get("get_updates_buf", "") or "")
        state.save(config.state_file)
    print(f"imported_account={account_src}")
    print(f"bridge_account_file={config.account_file}")
    print(f"openclaw_profile={config.openclaw_profile}")
    if sync_src.exists():
        print(f"seeded_get_updates_buf_from={sync_src}")
    return 0


def _resolve_openclaw_module_dir() -> Path:
    openclaw_bin = shutil.which("openclaw")
    if not openclaw_bin:
        raise RuntimeError("openclaw CLI not found in PATH")
    candidate = Path(openclaw_bin).resolve().parent.parent / "lib" / "node_modules" / "openclaw"
    if not candidate.exists():
        raise RuntimeError(f"Cannot resolve global openclaw module dir from {openclaw_bin}")
    return candidate


def _ensure_openclaw_profile_bootstrap(config) -> None:
    profile_args = ["openclaw", "--profile", config.openclaw_profile]
    plugin_root = config.openclaw_state_dir / "extensions" / "openclaw-weixin"
    if not plugin_root.exists():
        subprocess.run(
            profile_args + ["plugins", "install", OPENCLAW_WEIXIN_PLUGIN_SPEC],
            check=True,
        )
    plugin_node_modules = (
        plugin_root / "node_modules"
    )
    plugin_node_modules.mkdir(parents=True, exist_ok=True)
    openclaw_link = plugin_node_modules / "openclaw"
    if not openclaw_link.exists():
        openclaw_link.symlink_to(_resolve_openclaw_module_dir())
    subprocess.run(
        profile_args
        + [
            "config",
            "set",
            "plugins.entries.openclaw-weixin.enabled",
            "true",
            "--strict-json",
        ],
        check=True,
    )
    subprocess.run(
        profile_args
        + [
            "config",
            "set",
            "plugins.allow",
            '["openclaw-weixin"]',
            "--strict-json",
        ],
        check=True,
    )


def _auth_openclaw(config, state: BridgeState) -> int:
    _ensure_openclaw_profile_bootstrap(config)
    cmd = [
        "openclaw",
        "--profile",
        config.openclaw_profile,
        "channels",
        "login",
        "--channel",
        "openclaw-weixin",
    ]
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        return completed.returncode
    return _import_latest_openclaw_account(config, state)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config = load_config()
    state = BridgeState.load(config.state_file)

    if args.command == "status":
        print(f"state_file={config.state_file}")
        print(f"account_file={config.account_file}")
        print(f"openclaw_profile={config.openclaw_profile}")
        print(f"active_session_id={state.active_session_id}")
        print(f"sessions={len(state.sessions)}")
        return 0

    if args.command == "auth-openclaw":
        return _auth_openclaw(config, state)

    if args.command == "import-openclaw-account":
        return _import_latest_openclaw_account(config, state)

    if args.command == "doctor":
        print(
            "allowed_users="
            + (
                ",".join(sorted(config.allowed_users))
                if config.allowed_users
                else "ALL (no allowlist configured)"
            )
        )
        print(f"codex_bin={config.codex_bin}")
        print(f"account_file={config.account_file}")
        print(f"openclaw_profile={config.openclaw_profile}")
        print(f"default_cwd={config.default_cwd}")
        print(f"state_file={config.state_file}")
        print(f"active_session_id={state.active_session_id}")
        print(f"known_sessions={len(state.sessions)}")
        account = WeChatAccount.load(config.account_file)
        print(f"wechat_account_id={account.account_id}")
        print(f"wechat_user_id={account.user_id}")
        client = WeChatClient(
            account,
            min_send_interval_seconds=config.min_send_interval_seconds,
        )
        response = client.get_updates(state.get_updates_buf)
        print(
            "wechat_probe="
            + str(
                {
                    "ret": response.get("ret"),
                    "errcode": response.get("errcode"),
                    "errmsg": response.get("errmsg"),
                    "has_get_updates_buf": bool(response.get("get_updates_buf")),
                    "message_count": len(response.get("msgs") or []),
                }
            )
        )
        runner = LiveCodexSessionManager(
            codex_bin=config.codex_bin,
            default_cwd=config.default_cwd,
            canonical_tmux_session=config.canonical_tmux_session,
        )
        print(f"latest_codex_thread={runner.find_latest_thread()}")
        print(f"canonical_tmux_session={config.canonical_tmux_session}")
        return 0

    if args.command == "send-bound":
        text = sys.stdin.read() if args.stdin else (args.text or "")
        return _send_bound_text(config, state, text)

    account = WeChatAccount.load(config.account_file)
    daemon = BridgeDaemon(
        config=config,
        wechat=WeChatClient(
            account,
            min_send_interval_seconds=config.min_send_interval_seconds,
        ),
        runner=LiveCodexSessionManager(
            codex_bin=config.codex_bin,
            default_cwd=config.default_cwd,
            canonical_tmux_session=config.canonical_tmux_session,
        ),
        state=state,
    )
    daemon.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
