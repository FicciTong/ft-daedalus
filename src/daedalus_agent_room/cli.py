from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adm import AdmWorker
from .core import AgentRoom, TmuxRoster, default_room_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daedalus-agent-room")
    parser.add_argument(
        "--room-dir",
        type=Path,
        default=default_room_dir(),
        help="Local agent-room state directory.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    agents = sub.add_parser("agents", help="Owner-friendly alias for roster")
    agents.add_argument("--json", action="store_true")

    broadcast = sub.add_parser(
        "broadcast", help="Broadcast an announcement to all agents"
    )
    broadcast.add_argument("text", nargs="*")
    broadcast.add_argument("--stdin", action="store_true")
    broadcast.add_argument("--from", dest="from_actor", default="owner")
    broadcast.add_argument("--topic-id", default=None)
    broadcast.add_argument("--json", action="store_true")

    ask = sub.add_parser("ask", help="Ask one agent session to handle a task")
    ask.add_argument("agent")
    ask.add_argument("text", nargs="*")
    ask.add_argument("--stdin", action="store_true")
    ask.add_argument("--from", dest="from_actor", default="owner")
    ask.add_argument("--topic-id", default=None)
    ask.add_argument("--write-allowed", action="store_true")
    ask.add_argument("--json", action="store_true")

    debate = sub.add_parser("debate", help="Start a bounded debate between agents")
    debate.add_argument("agents", nargs="+")
    debate.add_argument("--rounds", type=int, required=True)
    debate.add_argument("--starter", default=None)
    debate.add_argument("--from", dest="from_actor", default="owner")
    debate.add_argument("--topic-id", default=None)
    debate.add_argument("--stdin", action="store_true")
    debate.add_argument("text", nargs="*")
    debate.add_argument("--json", action="store_true")

    review = sub.add_parser(
        "review", help="Ask one agent to review an artifact or statement"
    )
    review.add_argument("agent")
    review.add_argument("text", nargs="*")
    review.add_argument("--stdin", action="store_true")
    review.add_argument("--from", dest="from_actor", default="owner")
    review.add_argument("--topic-id", default=None)
    review.add_argument("--artifact", action="append", default=[])
    review.add_argument("--json", action="store_true")

    send = sub.add_parser("send", help="Append an owner/agent message to the room bus")
    send.add_argument("text", nargs="*", help="Message text")
    send.add_argument(
        "--stdin", action="store_true", help="Read message text from stdin"
    )
    send.add_argument("--from", dest="from_actor", default="owner")
    send.add_argument("--to", action="append", default=[])
    send.add_argument(
        "--mode",
        default="message",
        choices=[
            "announce",
            "message",
            "task",
            "panel",
            "debate",
            "review_request",
            "agent_reply",
        ],
    )
    send.add_argument("--topic-id", default=None)
    send.add_argument("--round-limit", type=int, default=None)
    send.add_argument("--write-allowed", action="store_true")
    send.add_argument("--json", action="store_true", help="Print raw JSON payload")

    artifact = sub.add_parser("artifact", help="Append an artifact reference")
    artifact.add_argument("path")
    artifact.add_argument("--by", required=True)
    artifact.add_argument("--topic-id", default=None)
    artifact.add_argument("--kind", default="artifact")
    artifact.add_argument("--note", default="")
    artifact.add_argument("--json", action="store_true")

    status = sub.add_parser("status", help="Print room status and tmux roster")
    status.add_argument("--json", action="store_true")

    roster = sub.add_parser("roster", help="Print current tmux session roster")
    roster.add_argument("--json", action="store_true")

    next_msg = sub.add_parser("next", help="Print pending messages for one agent")
    next_msg.add_argument("agent")
    next_msg.add_argument("--limit", type=int, default=10)
    next_msg.add_argument("--ack", action="store_true")
    next_msg.add_argument("--json", action="store_true")

    watch = sub.add_parser("watch", help="Watch pending messages for one agent")
    watch.add_argument("agent")
    watch.add_argument("--interval", type=float, default=2.0)
    watch.add_argument("--limit", type=int, default=10)
    watch.add_argument("--once", action="store_true")
    watch.add_argument("--from-end", action="store_true")
    watch.add_argument("--json", action="store_true")

    cursor = sub.add_parser("cursor-end", help="Move one agent cursor to the end")
    cursor.add_argument("agent")
    cursor.add_argument("--json", action="store_true")

    adm = sub.add_parser("adm", help="Run an ADM intent dispatcher for one agent")
    adm.add_argument("--agent", default="adm")
    adm.add_argument("--backend", choices=["claude", "codex"], default="claude")
    adm.add_argument("--cwd", type=Path, default=Path.cwd())
    adm.add_argument("--send-wechat", action="store_true")
    adm.add_argument("--once", action="store_true")
    adm.add_argument("--interval", type=float, default=2.0)
    adm.add_argument("--limit", type=int, default=1)
    adm.add_argument("--from-end", action="store_true")
    adm.add_argument("--json", action="store_true")

    pause = sub.add_parser("pause", help="Set room pause flag")
    pause.add_argument("--by", default="owner")
    pause.add_argument("--reason", default="")
    pause.add_argument("--json", action="store_true")

    resume = sub.add_parser("resume", help="Clear room pause flag")
    resume.add_argument("--by", default="owner")
    resume.add_argument("--reason", default="")
    resume.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    room = AgentRoom(args.room_dir)

    if args.command == "broadcast":
        text = sys.stdin.read() if args.stdin else " ".join(args.text)
        payload = room.send_message(
            from_actor=args.from_actor,
            text=text,
            mode="announce",
            topic_id=args.topic_id,
        )
        _print_payload(payload, as_json=args.json)
        return 0

    if args.command == "ask":
        text = sys.stdin.read() if args.stdin else " ".join(args.text)
        payload = room.send_message(
            from_actor=args.from_actor,
            to=[args.agent],
            text=text,
            mode="task",
            topic_id=args.topic_id,
            write_allowed=args.write_allowed,
        )
        _print_payload(payload, as_json=args.json)
        return 0

    if args.command == "debate":
        text = sys.stdin.read() if args.stdin else " ".join(args.text)
        metadata = {"starter": args.starter} if args.starter else {}
        payload = room.send_message(
            from_actor=args.from_actor,
            to=args.agents,
            text=text,
            mode="debate",
            topic_id=args.topic_id,
            round_limit=args.rounds,
            metadata=metadata,
        )
        _print_payload(payload, as_json=args.json)
        return 0

    if args.command == "review":
        text = sys.stdin.read() if args.stdin else " ".join(args.text)
        metadata = {"artifacts": args.artifact} if args.artifact else {}
        payload = room.send_message(
            from_actor=args.from_actor,
            to=[args.agent],
            text=text,
            mode="review_request",
            topic_id=args.topic_id,
            metadata=metadata,
        )
        _print_payload(payload, as_json=args.json)
        return 0

    if args.command == "send":
        text = sys.stdin.read() if args.stdin else " ".join(args.text)
        payload = room.send_message(
            from_actor=args.from_actor,
            to=args.to,
            text=text,
            mode=args.mode,
            topic_id=args.topic_id,
            round_limit=args.round_limit,
            write_allowed=args.write_allowed,
        )
        _print_payload(payload, as_json=args.json)
        return 0

    if args.command == "artifact":
        payload = room.record_artifact(
            path=args.path,
            by=args.by,
            topic_id=args.topic_id,
            kind=args.kind,
            note=args.note,
        )
        _print_payload(payload, as_json=args.json)
        return 0

    if args.command == "status":
        sessions = TmuxRoster().list_sessions()
        payload = room.status(sessions=sessions)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            _print_status(payload)
        return 0

    if args.command in {"agents", "roster"}:
        sessions = TmuxRoster().list_sessions()
        payload = [session.__dict__ for session in sessions]
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            if not sessions:
                print("sessions=0")
            for session in sessions:
                print(
                    f"{session.agent_id}\talive={str(session.alive).lower()}"
                    f"\tattached={session.attached}\twindows={session.windows}"
                )
        return 0

    if args.command == "next":
        messages = room.pending_for_agent(
            agent_id=args.agent,
            limit=args.limit,
            ack=args.ack,
        )
        if args.json:
            print(json.dumps(messages, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            _print_messages(messages)
        return 0

    if args.command == "watch":
        for message in room.run_watch(
            agent_id=args.agent,
            interval_seconds=args.interval,
            limit=args.limit,
            once=args.once,
            from_end=args.from_end,
        ):
            if args.json:
                print(
                    json.dumps(message, ensure_ascii=False, sort_keys=True), flush=True
                )
            else:
                _print_messages([message])
        return 0

    if args.command == "cursor-end":
        payload = room.set_cursor_to_end(agent_id=args.agent)
        _print_payload(payload, as_json=args.json)
        return 0

    if args.command == "adm":
        if args.from_end:
            room.set_cursor_to_end(agent_id=args.agent)
        worker = AdmWorker(
            room=room,
            agent_id=args.agent,
            backend=args.backend,
            cwd=args.cwd,
            send_wechat=args.send_wechat,
        )
        if args.once:
            results = worker.handle_pending_once(limit=args.limit)
            if args.json:
                print(
                    json.dumps(
                        [result.__dict__ for result in results],
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                _print_adm_results(results)
            return 0
        print(
            f"adm_agent={args.agent} backend={args.backend} "
            f"send_wechat={str(args.send_wechat).lower()}"
        )
        worker.run_forever(interval_seconds=args.interval, limit=args.limit)
        return 0

    if args.command == "pause":
        payload = room.set_paused(paused=True, by=args.by, reason=args.reason)
        _print_payload(payload, as_json=args.json)
        return 0

    if args.command == "resume":
        payload = room.set_paused(paused=False, by=args.by, reason=args.reason)
        _print_payload(payload, as_json=args.json)
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def _print_payload(payload: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for key in ("id", "kind", "mode", "topic_id", "path", "paused", "updated_at"):
        if key in payload:
            print(f"{key}={payload[key]}")


def _print_status(payload: dict) -> None:
    print(f"room_dir={payload['room_dir']}")
    print(f"paused={str(payload['paused']).lower()}")
    if payload["pause_reason"]:
        print(f"pause_reason={payload['pause_reason']}")
    print(f"messages={payload['message_count']}")
    print(f"artifacts={payload['artifact_count']}")
    print(f"sessions={payload['session_count']}")
    for session in payload["sessions"]:
        print(
            f"- {session['agent_id']} "
            f"alive={str(session['alive']).lower()} "
            f"attached={session['attached']} "
            f"windows={session['windows']}"
        )


def _print_messages(messages: list[dict]) -> None:
    if not messages:
        print("messages=0")
        return
    for message in messages:
        recipients = ",".join(str(value) for value in message.get("to", [])) or "all"
        print(
            f"[{message.get('mode', 'message')}] "
            f"{message.get('from')} -> {recipients} "
            f"topic={message.get('topic_id')}\n{message.get('text', '')}"
        )


def _print_adm_results(results: list) -> None:
    if not results:
        print("adm_results=0")
        return
    for result in results:
        print(
            f"source_message_id={result.source_message_id} "
            f"topic_id={result.topic_id} "
            f"sent_to_wechat={str(result.sent_to_wechat).lower()}\n{result.reply}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
