#!/usr/bin/env python3
"""Repo-local OpenCode harness helpers."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENCODE_CONTEXT_ROOTS = (
    ".opencode/",
    "opencode.json",
    "docs/OPENCODE_HARNESS_OVERLAY.md",
    "AGENTS.md",
    "README.md",
)


def _run_git(args: list[str], worktree: Path) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def tracked_files(worktree: Path) -> set[str]:
    return set(_run_git(["ls-files"], worktree))


def modified_files(worktree: Path) -> list[str]:
    lines = _run_git(["status", "--short"], worktree)
    found: list[str] = []
    for line in lines:
        candidate = line[3:]
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1]
        if candidate:
            found.append(candidate)
    return found


def _normalize_paths(paths: Iterable[str], worktree: Path) -> list[str]:
    normalized: list[str] = []
    for raw in paths:
        value = raw.strip()
        if not value:
            continue
        candidate = Path(value)
        if candidate.is_absolute():
            rel = candidate.resolve().relative_to(worktree.resolve())
            normalized.append(rel.as_posix())
            continue
        normalized.append(candidate.as_posix())
    return sorted(dict.fromkeys(normalized))


def collect_changed_paths(paths: list[str], worktree: Path) -> list[str]:
    return _normalize_paths(paths or modified_files(worktree), worktree)


def repo_profile_payload(tracked: set[str]) -> dict[str, object]:
    has_python = any(path.endswith(".py") for path in tracked)
    has_node = any(
        path.endswith((".js", ".ts", ".tsx", ".jsx", "package.json")) for path in tracked
    )
    file_count = len(tracked)
    if file_count > 40000:
        size_mode = "large"
    elif file_count > 10000:
        size_mode = "medium"
    else:
        size_mode = "standard"
    default_verifiers: list[str] = []
    if "opencode.json" in tracked:
        default_verifiers.append("python3 -m json.tool opencode.json > /dev/null")
    if "scripts/repo_harness.py" in tracked:
        default_verifiers.append("python3 -m py_compile scripts/repo_harness.py")
    if ".opencode/plugins/repo_harness.js" in tracked:
        default_verifiers.append("node --check .opencode/plugins/repo_harness.js")
    return {
        "worktree": REPO_ROOT.as_posix(),
        "file_count": file_count,
        "size_mode": size_mode,
        "has_python": has_python,
        "has_node": has_node,
        "has_repo_local_opencode_overlay": "opencode.json" in tracked and any(
            path.startswith(".opencode/") for path in tracked
        ),
        "default_verifiers": default_verifiers,
    }


def candidate_tests_for_path(rel_path: str, tracked: set[str]) -> list[str]:
    candidates: list[str] = []
    if rel_path == "scripts/repo_harness.py":
        for item in (
            "scripts/repo_harness.py",
            "opencode.json",
            ".opencode/plugins/repo_harness.js",
        ):
            if item in tracked and item not in candidates:
                candidates.append(item)
    if rel_path.endswith(".js") and rel_path.startswith(".opencode/") and rel_path in tracked:
        candidates.append(rel_path)
    return sorted(dict.fromkeys(candidates))


def affected_tests_payload(paths: list[str], tracked: set[str]) -> dict[str, object]:
    mapping = {path: candidate_tests_for_path(path, tracked) for path in paths}
    tests = sorted({test for items in mapping.values() for test in items})
    return {
        "paths": paths,
        "mapping": mapping,
        "tests": tests,
    }


def related_context_payload(paths: list[str], tracked: set[str]) -> dict[str, object]:
    context: list[str] = []
    for item in OPENCODE_CONTEXT_ROOTS:
        if item in tracked or any(path.startswith(item) for path in tracked):
            if item.endswith("/"):
                continue
            context.append(item)
    for rel_path in paths:
        if rel_path in tracked:
            context.append(rel_path)
        context.extend(candidate_tests_for_path(rel_path, tracked))
        if rel_path.startswith(".opencode/"):
            context.extend(
                [
                    "opencode.json",
                    "docs/OPENCODE_HARNESS_OVERLAY.md",
                    "scripts/repo_harness.py",
                ]
            )
    return {
        "paths": paths,
        "context_files": sorted(dict.fromkeys(item for item in context if item in tracked)),
    }


def verify_changed_payload(paths: list[str], tracked: set[str], mode: str) -> dict[str, object]:
    checks: list[dict[str, str]] = []
    js_targets = [
        path
        for path in paths
        if path.startswith(".opencode/") and path.endswith(".js")
    ]
    if js_targets:
        checks.append(
            {
                "kind": "syntax",
                "reason": "OpenCode repo-local tool/plugin JavaScript changed.",
                "command": f"node --check {' '.join(js_targets)}",
            }
        )
    if "opencode.json" in paths:
        checks.append(
            {
                "kind": "config",
                "reason": "OpenCode project config changed.",
                "command": "python3 -m json.tool opencode.json > /dev/null",
            }
        )
    if "scripts/repo_harness.py" in paths:
        checks.append(
            {
                "kind": "compile",
                "reason": "Local harness helper changed.",
                "command": "python3 -m py_compile scripts/repo_harness.py",
            }
        )
    if mode == "standard" and any(path.endswith(".md") for path in paths):
        checks.append(
            {
                "kind": "context",
                "reason": "Standard mode surfaces the key overlay context files for manual readback.",
                "command": "python3 scripts/repo_harness.py related-context --format text"
                + "".join(f" --path {path}" for path in paths),
            }
        )
    return {
        "mode": mode,
        "paths": paths,
        "checks": checks,
    }


def render_text(kind: str, payload: dict[str, object]) -> str:
    if kind == "repo-profile":
        lines = [
            f"worktree: {payload['worktree']}",
            f"file_count: {payload['file_count']}",
            f"size_mode: {payload['size_mode']}",
            f"has_python: {payload['has_python']}",
            f"has_node: {payload['has_node']}",
            f"has_repo_local_opencode_overlay: {payload['has_repo_local_opencode_overlay']}",
        ]
        defaults = payload.get("default_verifiers", [])
        if defaults:
            lines.append("default_verifiers:")
            lines.extend(f"- {item}" for item in defaults)
        return "\n".join(lines)

    if kind == "affected-tests":
        lines = ["affected_tests:"]
        for path, tests in payload["mapping"].items():
            lines.append(f"- {path}")
            if tests:
                lines.extend(f"  - {item}" for item in tests)
            else:
                lines.append("  - none")
        return "\n".join(lines)

    if kind == "related-context":
        lines = ["context_files:"]
        lines.extend(f"- {item}" for item in payload["context_files"])
        return "\n".join(lines)

    if kind == "verify-changed":
        lines = ["verification_dag:"]
        if not payload["checks"]:
            lines.append("- no repo-local checks matched this path set")
            return "\n".join(lines)
        for index, check in enumerate(payload["checks"], start=1):
            lines.append(f"{index}. {check['kind']}")
            lines.append(f"   reason: {check['reason']}")
            lines.append(f"   command: {check['command']}")
        return "\n".join(lines)

    raise ValueError(f"Unknown render kind: {kind}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--path",
            dest="paths",
            action="append",
            default=[],
            help="Path to evaluate. Can be repeated. Defaults to the current git changes.",
        )
        subparser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Output format.",
        )

    add_common(subparsers.add_parser("affected-tests"))
    add_common(subparsers.add_parser("related-context"))
    add_common(subparsers.add_parser("verify-changed"))
    repo_profile = subparsers.add_parser("repo-profile")
    repo_profile.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    subparsers.choices["verify-changed"].add_argument(
        "--mode",
        choices=("quick", "standard"),
        default="quick",
        help="Verification depth.",
    )
    return parser


def emit_payload(kind: str, payload: dict[str, object], *, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(render_text(kind, payload))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    tracked = tracked_files(REPO_ROOT)

    if args.command == "repo-profile":
        emit_payload("repo-profile", repo_profile_payload(tracked), fmt=args.format)
        return

    paths = collect_changed_paths(args.paths, REPO_ROOT)
    if args.command == "affected-tests":
        emit_payload("affected-tests", affected_tests_payload(paths, tracked), fmt=args.format)
        return
    if args.command == "related-context":
        emit_payload("related-context", related_context_payload(paths, tracked), fmt=args.format)
        return
    if args.command == "verify-changed":
        emit_payload(
            "verify-changed",
            verify_changed_payload(paths, tracked, mode=args.mode),
            fmt=args.format,
        )
        return
    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
