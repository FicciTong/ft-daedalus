import { tool } from "@opencode-ai/plugin";
import { runHarness } from "../lib/run-harness.js";

export const VerifyChangedTool = tool({
  description: "Build the repo-local verification DAG for the current changed files or explicit paths.",
  args: {
    paths: tool.schema.array(tool.schema.string()).optional().describe("Changed or target paths."),
    mode: tool.schema.enum(["quick", "standard"]).optional().describe("Verification depth. Defaults to quick."),
    format: tool.schema.enum(["text", "json"]).optional().describe("Output format. Defaults to text."),
  },
  async execute(args, context) {
    const extra = ["--mode", args.mode ?? "quick", "--format", args.format ?? "text"];
    for (const item of args.paths ?? []) {
      extra.push("--path", item);
    }
    return runHarness(context.worktree, "verify-changed", extra);
  },
});
