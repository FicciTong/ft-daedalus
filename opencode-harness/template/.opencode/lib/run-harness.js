import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";

const execFileAsync = promisify(execFile);

function scriptPath(worktree) {
  return path.join(worktree, "scripts", "repo_harness.py");
}

export async function runHarness(worktree, subcommand, args = []) {
  const script = scriptPath(worktree);
  const { stdout } = await execFileAsync("python3", [script, subcommand, ...args], {
    cwd: worktree,
    maxBuffer: 1024 * 1024,
  });
  return stdout.trim();
}
