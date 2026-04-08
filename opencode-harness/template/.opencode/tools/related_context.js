import { tool } from "@opencode-ai/plugin";
import { runHarness } from "../lib/run-harness.js";

export const RelatedContextTool = tool({
  description: "Return the minimal repo-local files that should be read together for the given paths.",
  args: {
    paths: tool.schema.array(tool.schema.string()).optional().describe("Changed or target paths."),
    format: tool.schema.enum(["text", "json"]).optional().describe("Output format. Defaults to text."),
  },
  async execute(args, context) {
    const extra = ["--format", args.format ?? "text"];
    for (const item of args.paths ?? []) {
      extra.push("--path", item);
    }
    return runHarness(context.worktree, "related-context", extra);
  },
});
