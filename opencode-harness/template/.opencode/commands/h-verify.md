---
description: Run the repo-local verifier DAG for current changes
agent: harness-verifier
subtask: true
---
Verify the current changes for `$ARGUMENTS`.

Use `verify_changed` first. If `$ARGUMENTS` is empty, infer from the current git
working tree.

Run the returned commands in order, stopping at the first real blocker.

Report:
- changed paths
- commands run
- pass/fail
- first blocking failure
- shortest repair cut
