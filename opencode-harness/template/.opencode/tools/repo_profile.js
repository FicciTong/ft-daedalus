import { tool } from "@opencode-ai/plugin";
import { runHarness } from "../lib/run-harness.js";

export const RepoProfileTool = tool({
  description: "Summarize the current repository shape and the default verification posture.",
  args: {
    format: tool.schema.enum(["text", "json"]).optional().describe("Output format. Defaults to text."),
  },
  async execute(args, context) {
    return runHarness(context.worktree, "repo-profile", ["--format", args.format ?? "text"]);
  },
});
