import fs from "node:fs/promises";
import path from "node:path";
import { RepoProfileTool } from "../tools/repo_profile.js";
import { RelatedContextTool } from "../tools/related_context.js";
import { AffectedTestsTool } from "../tools/affected_tests.js";
import { VerifyChangedTool } from "../tools/verify_changed.js";

const EDIT_TOOL_NAMES = new Set(["edit", "write", "patch", "multiedit"]);
const STATE_DIR_PARTS = [".opencode", ".state", "sessions"];

function stateFile(worktree, sessionID) {
  return path.join(worktree, ...STATE_DIR_PARTS, `${sessionID}.json`);
}

async function loadState(worktree, sessionID) {
  try {
    const raw = await fs.readFile(stateFile(worktree, sessionID), "utf-8");
    return JSON.parse(raw);
  } catch {
    return {
      changed_files: [],
      verifier_runs: [],
    };
  }
}

async function saveState(worktree, sessionID, state) {
  const target = stateFile(worktree, sessionID);
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.writeFile(target, `${JSON.stringify(state, null, 2)}\n`, "utf-8");
}

function uniqueStrings(items) {
  return [...new Set(items.filter(Boolean).map((item) => String(item)))];
}

function collectFileArgs(args) {
  if (!args || typeof args !== "object") {
    return [];
  }
  const found = [];
  for (const key of ["filePath", "path", "newPath", "oldPath"]) {
    if (typeof args[key] === "string") {
      found.push(args[key]);
    }
  }
  for (const key of ["filePaths", "paths"]) {
    if (Array.isArray(args[key])) {
      for (const item of args[key]) {
        if (typeof item === "string") {
          found.push(item);
        }
      }
    }
  }
  return uniqueStrings(found);
}

function looksLikeVerifierCommand(command) {
  return [
    "uv run pytest ",
    "uv run ruff check ",
    "node --check ",
    "python3 -m json.tool ",
  ].some((prefix) => command.startsWith(prefix));
}

function summarizeOutput(text) {
  return String(text || "")
    .split("\n")
    .slice(0, 4)
    .join("\n")
    .trim();
}

function summarizeStateForCompaction(state) {
  const lines = [];
  if (state.changed_files.length) {
    const visibleFiles = state.changed_files.slice(-12);
    lines.push(
      `changed_files(${visibleFiles.length}/${state.changed_files.length} shown): ${visibleFiles.join(", ")}`,
    );
  }
  if (state.verifier_runs.length) {
    lines.push("recent_verifiers:");
    for (const run of state.verifier_runs.slice(-4)) {
      const summary = String(run.summary || "").replace(/\s+/g, " ").trim();
      lines.push(`- ${run.command}`);
      if (summary) {
        lines.push(`  ${summary.slice(0, 180)}`);
      }
    }
  }
  return lines;
}

export const RepoHarnessPlugin = async ({ worktree }) => {
  return {
    tool: {
      repo_profile: RepoProfileTool,
      related_context: RelatedContextTool,
      affected_tests: AffectedTestsTool,
      verify_changed: VerifyChangedTool,
    },
    "tool.execute.after": async (input, output) => {
      const state = await loadState(worktree, input.sessionID);

      if (EDIT_TOOL_NAMES.has(input.tool)) {
        state.changed_files = uniqueStrings([
          ...state.changed_files,
          ...collectFileArgs(input.args),
        ]).slice(-24);
      }

      if (input.tool === "bash") {
        const command = String(input.args?.command || "").trim();
        if (looksLikeVerifierCommand(command)) {
          state.verifier_runs = [
            ...state.verifier_runs,
            {
              command,
              title: output.title || "",
              summary: summarizeOutput(output.output),
            },
          ].slice(-4);
        }
      }

      await saveState(worktree, input.sessionID, state);
    },
    "experimental.session.compacting": async (input, output) => {
      const state = await loadState(worktree, input.sessionID);
      if (!state.changed_files.length && !state.verifier_runs.length) {
        return;
      }
      const stateSummary = summarizeStateForCompaction(state);
      output.context.push(
        [
          "Repo-local harness state:",
          ...stateSummary,
          "Keep compaction output explicit about goal, accepted plan, changed files, verifier status, and next step.",
        ].join("\n"),
      );
    },
  };
};
