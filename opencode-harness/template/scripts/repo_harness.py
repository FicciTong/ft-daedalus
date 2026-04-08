#!/usr/bin/env python3
"""Repo-local coding-agent harness helpers for the adopting repository."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
CRITICAL_TEST_MAP = {
    "scripts/agent_control_runtime.py": "tests/test_agent_control_runtime.py",
    "scripts/opencode-local.sh": "tests/test_repo_harness.py",
    "scripts/repo_harness.py": "tests/test_repo_harness.py",
    "scripts/opencode_harness.py": "tests/test_repo_harness.py",
    "scripts/tmux-worker-deliver.py": "tests/test_tmux_worker_deliver.py",
    "scripts/worker-claim-queue.py": "tests/test_worker_claim_queue.py",
}
HARNESS_CONTEXT_ROOTS = (
    ".claude/",
    ".codex/",
    ".opencode/",
    "AGENTS.md",
    "CLAUDE.md",
    "opencode.json",
    "docs/AGENT_TOOL_RUNTIME_NOTES.md",
    "docs/OPENCODE_HARNESS_OVERLAY.md",
    "docs/control/STATUS.md",
    "docs/control/WORK.md",
    "docs/control/DECISIONS.md",
)
HARNESS_TEST_TARGET = "tests/test_repo_harness.py"
CONTROL_AUTHORITY_FILES = (
    "docs/control/STATUS.md",
    "docs/control/WORK.md",
    "docs/control/DECISIONS.md",
    "docs/control/IDEAS.md",
    "docs/REVIEW_LOG.md",
    "docs/consultants/ADOPTION_LOG.md",
)
HARNESS_AUTHORITY_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "opencode.json",
    "scripts/repo_harness.py",
    "docs/AGENT_TOOL_RUNTIME_NOTES.md",
    "docs/OPENCODE_HARNESS_OVERLAY.md",
    "docs/MULTI_AGENT_ORCHESTRATION_POLICY.md",
    *CONTROL_AUTHORITY_FILES,
)
DISCOVERABLE_TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".mjs",
    ".cjs",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".txt",
    ".sh",
}
PATH_REFERENCE_RE = re.compile(
    r"(?<!://)(?P<path>(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:md|py|js|ts|tsx|jsx|mjs|cjs|json|toml|yaml|yml|txt|sh))"
)
WORK_LANE_RE = re.compile(r"\bW-(\d{3})\b")
JS_RELATIVE_IMPORT_RE = re.compile(r"['\"](\.{1,2}/[^'\"\n]+)['\"]")
PY_RELATIVE_IMPORT_RE = re.compile(r"^\s*from\s+(\.+[A-Za-z0-9_\.]*)\s+import\b", re.MULTILINE)


def _path_available(rel_path: str, tracked: set[str]) -> bool:
    return rel_path in tracked or (REPO_ROOT / rel_path).exists()


def _available_paths(paths: Iterable[str], tracked: set[str]) -> list[str]:
    return sorted(dict.fromkeys(item for item in paths if _path_available(item, tracked)))


def _is_control_related(rel_path: str) -> bool:
    return (
        rel_path.startswith("docs/control/")
        or rel_path.startswith("docs/consultants/")
        or rel_path.startswith("var/reports/organism/")
        or rel_path in CONTROL_AUTHORITY_FILES
    )


def _is_harness_related(rel_path: str) -> bool:
    return (
        rel_path.startswith(".opencode/")
        or rel_path.startswith(".claude/")
        or rel_path.startswith(".codex/")
        or rel_path
        in {
            "AGENTS.md",
            "CLAUDE.md",
            "opencode.json",
            "scripts/repo_harness.py",
            "scripts/opencode_harness.py",
            "scripts/opencode-local.sh",
            "docs/AGENT_TOOL_RUNTIME_NOTES.md",
            "docs/OPENCODE_HARNESS_OVERLAY.md",
            "docs/MULTI_AGENT_ORCHESTRATION_POLICY.md",
        }
    )


def _allow_generic_discovery(source_rel_path: str, candidate: str) -> bool:
    if _is_control_related(source_rel_path):
        return (
            candidate.startswith("docs/control/")
            or candidate.startswith("docs/consultants/")
            or candidate in {"docs/REVIEW_LOG.md", "docs/MULTI_AGENT_ORCHESTRATION_POLICY.md"}
            or candidate.startswith("ft-daedalus/opencode-harness/")
        )
    if _is_harness_related(source_rel_path):
        return (
            _is_harness_related(candidate)
            or candidate.startswith("docs/control/")
            or candidate.startswith("docs/consultants/")
            or candidate in {"docs/REVIEW_LOG.md", "docs/MULTI_AGENT_ORCHESTRATION_POLICY.md"}
            or candidate.startswith("ft-daedalus/opencode-harness/")
        )
    parent = Path(source_rel_path).parent.as_posix()
    return candidate.startswith(parent + "/") or candidate.startswith("tests/")


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
    return set(_run_git(["ls-files"], worktree)) | set(
        _run_git(["ls-files", "--others", "--exclude-standard"], worktree)
    )


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
    return {
        "worktree": REPO_ROOT.as_posix(),
        "file_count": file_count,
        "size_mode": size_mode,
        "has_python": has_python,
        "has_node": has_node,
        "uses_uv": "pyproject.toml" in tracked or "uv.lock" in tracked,
        "has_tests": any(path.startswith("tests/") for path in tracked),
        "has_claude_project_overlay": "CLAUDE.md" in tracked and any(
            path.startswith(".claude/") for path in tracked
        ),
        "has_codex_project_overlay": ".codex/config.toml" in tracked,
        "has_repo_local_opencode_overlay": "opencode.json" in tracked and any(
            path.startswith(".opencode/") for path in tracked
        ),
        "default_verifiers": [
            command
            for command in (
                "uv run pytest -q",
                "uv run ruff check .",
                "node --check .opencode/plugins/repo_harness.js",
            )
            if (
                command.startswith("uv run pytest")
                and "tests/test_repo_harness.py" in tracked
            )
            or (command.startswith("uv run ruff") and has_python)
            or (
                command.startswith("node --check")
                and ".opencode/plugins/repo_harness.js" in tracked
            )
        ],
    }


def candidate_tests_for_path(rel_path: str, tracked: set[str]) -> list[str]:
    candidates: list[str] = []
    path_obj = Path(rel_path)
    if rel_path in CRITICAL_TEST_MAP and CRITICAL_TEST_MAP[rel_path] in tracked:
        candidates.append(CRITICAL_TEST_MAP[rel_path])
    if (
        HARNESS_TEST_TARGET in tracked
        and (
            rel_path == "CLAUDE.md"
            or rel_path == "opencode.json"
            or rel_path == "scripts/opencode-local.sh"
            or rel_path == ".codex/config.toml"
            or rel_path.startswith(".claude/")
            or rel_path.startswith(".codex/")
            or rel_path.startswith(".opencode/")
            or rel_path == "docs/OPENCODE_HARNESS_OVERLAY.md"
        )
    ):
        candidates.append(HARNESS_TEST_TARGET)
    if rel_path.startswith("tests/") and rel_path in tracked:
        candidates.append(rel_path)
    if path_obj.suffix == ".py":
        stem = path_obj.stem
        direct_test = f"tests/test_{stem}.py"
        if direct_test in tracked:
            candidates.append(direct_test)
    return sorted(dict.fromkeys(candidates))


def affected_tests_payload(paths: list[str], tracked: set[str]) -> dict[str, object]:
    mapping = {path: candidate_tests_for_path(path, tracked) for path in paths}
    tests = sorted({test for items in mapping.values() for test in items})
    return {
        "paths": paths,
        "mapping": mapping,
        "tests": tests,
    }


def authority_candidates_for_paths(paths: list[str], tracked: set[str]) -> list[str]:
    candidates: list[str] = []
    if any(_is_control_related(path) for path in paths):
        candidates.extend(CONTROL_AUTHORITY_FILES)
    if any(_is_harness_related(path) for path in paths):
        candidates.extend(HARNESS_AUTHORITY_FILES)
    return _available_paths(candidates, tracked)


def _read_text(rel_path: str) -> str:
    target = REPO_ROOT / rel_path
    if not target.is_file() or target.suffix not in DISCOVERABLE_TEXT_SUFFIXES:
        return ""
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def _resolve_relative_path(source_rel_path: str, ref: str, tracked: set[str]) -> list[str]:
    source_dir = Path(source_rel_path).parent
    target = (REPO_ROOT / source_dir / ref).resolve(strict=False).relative_to(
        REPO_ROOT.resolve()
    )
    candidates: list[Path] = []
    if target.suffix:
        candidates.append(target)
    else:
        candidates.extend(
            [
                target.with_suffix(".py"),
                target.with_suffix(".js"),
                target.with_suffix(".ts"),
                target / "__init__.py",
                target / "index.js",
                target / "index.ts",
            ]
        )
    return _available_paths((candidate.as_posix() for candidate in candidates), tracked)


def _resolve_python_relative_import(
    source_rel_path: str, dotted_ref: str, tracked: set[str]
) -> list[str]:
    source_dir = Path(source_rel_path).parent
    dot_count = len(dotted_ref) - len(dotted_ref.lstrip("."))
    if dot_count == 0:
        return []
    parents = source_dir.parents
    base = source_dir
    if dot_count > 1:
        index = dot_count - 2
        if index >= len(parents):
            return []
        base = parents[index]
    module_ref = dotted_ref.lstrip(".").replace(".", "/")
    target = (
        (REPO_ROOT / (base / module_ref if module_ref else base))
        .resolve(strict=False)
        .relative_to(REPO_ROOT.resolve())
    )
    candidates = [
        target.with_suffix(".py"),
        target / "__init__.py",
    ]
    return _available_paths((candidate.as_posix() for candidate in candidates), tracked)


def discovered_candidates_for_paths(
    paths: list[str], seed_context: list[str], tracked: set[str]
) -> list[str]:
    discovered: list[str] = []
    for rel_path in dict.fromkeys([*paths, *seed_context]):
        text = _read_text(rel_path)
        if not text:
            continue
        for match in PATH_REFERENCE_RE.finditer(text):
            candidate = match.group("path").rstrip("`.,:;)]}")
            if _path_available(candidate, tracked) and _allow_generic_discovery(
                rel_path, candidate
            ):
                discovered.append(candidate)
        for lane_id in dict.fromkeys(WORK_LANE_RE.findall(text)):
            for plan in (REPO_ROOT / "docs/control/work").glob(f"W-{lane_id}-*.md"):
                discovered.append(plan.relative_to(REPO_ROOT).as_posix())
        if rel_path.endswith((".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs")):
            for ref in JS_RELATIVE_IMPORT_RE.findall(text):
                if ref.startswith(("./", "../")):
                    discovered.extend(_resolve_relative_path(rel_path, ref, tracked))
        if rel_path.endswith(".py"):
            for dotted_ref in PY_RELATIVE_IMPORT_RE.findall(text):
                discovered.extend(_resolve_python_relative_import(rel_path, dotted_ref, tracked))
    return list(
        dict.fromkeys(
            candidate
            for candidate in discovered
            if candidate not in paths and candidate not in seed_context
        )
    )[:24]


def related_context_payload(paths: list[str], tracked: set[str]) -> dict[str, object]:
    seed_context: list[str] = []
    for item in HARNESS_CONTEXT_ROOTS:
        if item in tracked or any(path.startswith(item) for path in tracked):
            if item.endswith("/"):
                continue
            seed_context.append(item)
    for rel_path in paths:
        if _path_available(rel_path, tracked):
            seed_context.append(rel_path)
        seed_context.extend(candidate_tests_for_path(rel_path, tracked))
        if rel_path.startswith(".opencode/"):
            seed_context.extend(
                [
                    "opencode.json",
                    ".opencode/package.json",
                    ".opencode/agents/harness-orchestrator.md",
                    "docs/OPENCODE_HARNESS_OVERLAY.md",
                    "docs/AGENT_TOOL_RUNTIME_NOTES.md",
                    "scripts/opencode-local.sh",
                ]
            )
        if rel_path.startswith(".claude/") or rel_path == "CLAUDE.md":
            seed_context.extend(
                [
                    "CLAUDE.md",
                    ".claude/agents/harness-worker.md",
                    "docs/AGENT_TOOL_RUNTIME_NOTES.md",
                ]
            )
        if rel_path.startswith(".codex/"):
            seed_context.extend(
                [
                    ".codex/config.toml",
                    ".codex/skills/repo-harness/SKILL.md",
                    "docs/AGENT_TOOL_RUNTIME_NOTES.md",
                ]
            )
    seed_context_files = _available_paths(seed_context, tracked)
    authority_candidates = [
        item
        for item in authority_candidates_for_paths(paths, tracked)
        if item not in seed_context_files and item not in paths
    ]
    discovered_candidates = [
        item
        for item in discovered_candidates_for_paths(paths, seed_context_files, tracked)
        if item not in authority_candidates
    ]
    context_files = sorted(dict.fromkeys([*seed_context_files, *authority_candidates]))
    return {
        "paths": paths,
        "context_files": context_files,
        "seed_context_files": seed_context_files,
        "authority_candidates": authority_candidates,
        "discovered_candidates": discovered_candidates,
        "expansion_guidance": [
            "Treat `context_files` as the first-hop seed, not a hard boundary.",
            "If reading these files reveals a new authority file, work plan, import neighbor, or runtime dependency, rerun `related-context` with that path included before continuing broad work.",
        ],
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
    json_targets = [
        path
        for path in paths
        if path in {".opencode/harness.json", ".opencode/package.json", ".opencode/package-lock.json"}
    ]
    for target in json_targets:
        checks.append(
            {
                "kind": "config",
                "reason": "Repo-local OpenCode overlay JSON changed.",
                "command": f"python3 -m json.tool {target} > /dev/null",
            }
        )
    if "scripts/opencode-local.sh" in paths:
        checks.append(
            {
                "kind": "syntax",
                "reason": "Repo-local OpenCode launcher changed.",
                "command": "bash -n scripts/opencode-local.sh",
            }
        )
    affected = affected_tests_payload(paths, tracked)
    if affected["tests"]:
        checks.append(
            {
                "kind": "tests",
                "reason": "Repo-local coding-agent harness logic or critical scripts changed.",
                "command": "uv run pytest -q " + " ".join(affected["tests"]),
            }
        )
    if mode == "standard" and any(path.endswith(".py") for path in paths):
        checks.append(
            {
                "kind": "lint",
                "reason": "Standard mode adds Python lint for changed Python files.",
                "command": "uv run ruff check "
                + " ".join(sorted(path for path in paths if path.endswith(".py"))),
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
            f"uses_uv: {payload['uses_uv']}",
            f"has_claude_project_overlay: {payload['has_claude_project_overlay']}",
            f"has_codex_project_overlay: {payload['has_codex_project_overlay']}",
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
        if payload["context_files"]:
            lines.extend(f"- {item}" for item in payload["context_files"])
        else:
            lines.append("- none")
        lines.append("seed_context_files:")
        if payload["seed_context_files"]:
            lines.extend(f"- {item}" for item in payload["seed_context_files"])
        else:
            lines.append("- none")
        lines.append("authority_candidates:")
        if payload["authority_candidates"]:
            lines.extend(f"- {item}" for item in payload["authority_candidates"])
        else:
            lines.append("- none")
        lines.append("discovered_candidates:")
        if payload["discovered_candidates"]:
            lines.extend(f"- {item}" for item in payload["discovered_candidates"])
        else:
            lines.append("- none")
        lines.append("expansion_guidance:")
        lines.extend(f"- {item}" for item in payload["expansion_guidance"])
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
