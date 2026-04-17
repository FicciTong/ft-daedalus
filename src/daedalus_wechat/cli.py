from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from .config import load_config
from .daemon import BridgeDaemon
from .delivery_ledger import append_delivery
from .ilink_auth import poll_ilink_login, start_ilink_login, write_bridge_account
from .live_session import LiveCodexSessionManager
from .security_drill import run_security_drill
from .state import BridgeState
from .wechat_api import WeChatAccount, WeChatClient


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
        raise RuntimeError(
            "No bound WeChat chat context. Send /status from WeChat first."
        )
    chunks = _chunk_text(text, config.text_chunk_limit)
    if not chunks:
        raise RuntimeError("No text to send.")
    wechat = client or WeChatClient(
        WeChatAccount.load(config.account_file),
        min_send_interval_seconds=config.min_send_interval_seconds,
    )
    for chunk in chunks:
        ledger_text = chunk
        try:
            wechat.send_text(
                to_user_id=state.bound_user_id,
                context_token=state.bound_context_token,
                text=chunk,
            )
            event_kind = "relay_outgoing"
            status = "sent"
        except Exception as exc:  # noqa: BLE001
            # Do NOT enqueue via the shared state file — the daemon holds
            # state in memory and its next _save_state() would overwrite
            # whatever the CLI wrote, losing daemon-side changes.
            # Report the failure; the operator can retry or let the daemon
            # handle the next delivery attempt.
            event_kind = "relay_failed"
            chunk = f"{chunk[:400]} [failed: {str(exc)[:160]}]"
            status = "failed"
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
        append_delivery(
            state=state,
            ledger_file=config.delivery_ledger_file,
            to_user_id=state.bound_user_id,
            text=ledger_text,
            status=status,
            kind="relay",
            origin="desktop-direct",
            thread_id=state.active_session_id,
            tmux_session=state.active_tmux_session,
        )
    return 0


def _stream_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classify_media_send_stage(error_text: str) -> str:
    text = str(error_text or "").strip()
    if text.startswith("WeChat getuploadurl failed"):
        return "getuploadurl"
    if text.startswith("CDN upload"):
        return "cdn_upload"
    if text.startswith("WeChat media send failed"):
        return "sendmessage"
    if text.startswith("openssl encrypt failed"):
        return "local_encrypt"
    if text.startswith("ffprobe ") or text.startswith("ffmpeg "):
        return "video_probe"
    return "unknown"


def _send_bound_media(
    config,
    state: BridgeState,
    *,
    media_path: Path,
    kind: str,
    client: WeChatClient | None = None,
) -> int:
    if not state.bound_user_id:
        raise RuntimeError(
            "No bound WeChat chat context. Send /status from WeChat first."
        )
    path = Path(media_path)
    if not path.is_file():
        raise RuntimeError(f"media path does not exist or is not a file: {path}")

    size_bytes = path.stat().st_size
    content_md5 = _stream_md5(path)
    content_type, _ = mimetypes.guess_type(path.name)
    trace_id = secrets.token_hex(8)

    wechat = client or WeChatClient(
        WeChatAccount.load(config.account_file),
        min_send_interval_seconds=config.min_send_interval_seconds,
    )
    started_at = time.monotonic()
    error: str | None = None
    stage: str | None = None
    try:
        if kind == "image":
            wechat.send_image(
                to_user_id=state.bound_user_id,
                context_token=state.bound_context_token,
                image_path=path,
            )
        elif kind == "video":
            wechat.send_video(
                to_user_id=state.bound_user_id,
                context_token=state.bound_context_token,
                video_path=path,
            )
        else:
            wechat.send_file(
                to_user_id=state.bound_user_id,
                context_token=state.bound_context_token,
                file_path=path,
            )
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        stage = _classify_media_send_stage(error)
    latency_ms = int((time.monotonic() - started_at) * 1000)

    event_kind = "relay_outgoing" if error is None else "relay_failed"
    status = "sent" if error is None else "failed"
    payload: dict[str, object] = {
        "to": state.bound_user_id,
        "trace_id": trace_id,
        "media_kind": kind,
        "path": str(path),
        "file_name": path.name,
        "size_bytes": size_bytes,
        "md5": content_md5,
        "content_type": content_type,
        "latency_ms": latency_ms,
    }
    if error:
        payload["error"] = error
        payload["stage"] = stage

    config.state_dir.mkdir(parents=True, exist_ok=True)
    with config.event_log_file.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "kind": event_kind,
                    "payload": payload,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    append_delivery(
        state=state,
        ledger_file=config.delivery_ledger_file,
        to_user_id=state.bound_user_id,
        text=f"[{kind}] {path.name} md5={content_md5[:12]} size={size_bytes}",
        status=status,
        kind="relay",
        origin="desktop-direct",
        thread_id=state.active_session_id,
        tmux_session=state.active_tmux_session,
        error=f"[{stage}] {error}" if error else None,
    )
    if error:
        raise RuntimeError(f"[{stage}] {error}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daedalus-wechat")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Run the WeChat bridge daemon")
    sub.add_parser("status", help="Print current bridge state")
    sub.add_parser("doctor", help="Check bridge prerequisites and current auth health")
    security_drill = sub.add_parser(
        "security-drill",
        help="Run a local fail-closed security drill and emit a machine-readable report",
    )
    security_drill.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="Optional output path for the drill report",
    )
    send_bound = sub.add_parser(
        "send-bound",
        help="Send text / image / file / video to the currently bound WeChat chat",
    )
    send_bound.add_argument("text", nargs="?", help="Text to send")
    send_bound.add_argument(
        "--stdin",
        action="store_true",
        help="Read text from stdin",
    )
    send_bound.add_argument(
        "--image",
        type=Path,
        default=None,
        help="Path to an image file to send as WeChat image.",
    )
    send_bound.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to any file to send as WeChat file attachment.",
    )
    send_bound.add_argument(
        "--video",
        type=Path,
        default=None,
        help="Path to a video file to send (requires ffmpeg/ffprobe on PATH).",
    )
    sub.add_parser(
        "auth-ilink",
        help="Run direct official iLink QR login, then write bridge account.json",
    )
    return parser


def _maybe_restart_bridge_service() -> bool:
    try:
        active = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "daedalus-wechat.service"],
            check=False,
        )
    except OSError:
        return False
    if active.returncode != 0:
        return False
    restarted = subprocess.run(
        ["systemctl", "--user", "restart", "daedalus-wechat.service"],
        check=False,
    )
    return restarted.returncode == 0


def _auth_ilink(config, state: BridgeState) -> int:
    qr = start_ilink_login()
    print("使用微信扫描以下二维码链接完成授权：")
    print(qr.qrcode_url)
    result = poll_ilink_login(qrcode=qr.qrcode)
    write_bridge_account(account_file=config.account_file, result=result)
    state.get_updates_buf = ""
    state.bound_user_id = None
    state.bound_context_token = None
    state.outbox_waiting_for_bind = False
    state.outbox_waiting_for_bind_since = ""
    state.pending_outbox = []
    state.save(config.state_file)
    print(f"bridge_account_file={config.account_file}")
    print(f"account_id={result.account_id}")
    print(f"base_url={result.base_url}")
    if result.user_id:
        print(f"user_id={result.user_id}")
    if _maybe_restart_bridge_service():
        print("bridge_service_restarted=daedalus-wechat.service")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config = load_config()
    state = BridgeState.load(config.state_file)

    if args.command == "status":
        print(f"state_file={config.state_file}")
        print(f"account_file={config.account_file}")
        print(f"active_session_id={state.active_session_id}")
        print(f"sessions={len(state.sessions)}")
        return 0

    if args.command == "auth-ilink":
        return _auth_ilink(config, state)

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
        print(f"opencode_bin={config.opencode_bin}")
        print(f"account_file={config.account_file}")
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
            opencode_bin=config.opencode_bin,
            default_cwd=config.default_cwd,
            canonical_tmux_session=config.canonical_tmux_session,
            codex_state_db=config.codex_state_db,
            opencode_state_db=config.opencode_state_db,
        )
        print(f"latest_codex_thread={runner.find_latest_thread()}")
        print(
            "latest_opencode_session="
            + str(runner.find_latest_opencode_session(pane_cwd=str(config.default_cwd)))
        )
        print(f"canonical_tmux_session={config.canonical_tmux_session}")
        return 0

    if args.command == "security-drill":
        result = run_security_drill(config=config, report_path=args.report_path)
        print(
            json.dumps(
                {
                    "status": result.status,
                    "report_path": str(result.report_path),
                    "allowlist_configured": result.payload.get("allowlist_configured"),
                    "allowed_user_count": result.payload.get("allowed_user_count"),
                    "codex_state_db": result.payload.get("codex_state_db"),
                    "codex_state_db_resolution": result.payload.get(
                        "codex_state_db_resolution"
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 0 if result.status in {"SUCCESS", "WARN"} else 2

    if args.command == "send-bound":
        media_args = [args.image, args.file, args.video]
        chosen_media = [m for m in media_args if m is not None]
        if len(chosen_media) > 1:
            raise SystemExit("send-bound: --image / --file / --video are mutually exclusive")
        if chosen_media:
            media_path = chosen_media[0]
            kind = (
                "image" if args.image is not None
                else "video" if args.video is not None
                else "file"
            )
            return _send_bound_media(config, state, media_path=media_path, kind=kind)
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
            opencode_bin=config.opencode_bin,
            default_cwd=config.default_cwd,
            canonical_tmux_session=config.canonical_tmux_session,
            codex_state_db=config.codex_state_db,
            opencode_state_db=config.opencode_state_db,
        ),
        state=state,
    )
    daemon.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
