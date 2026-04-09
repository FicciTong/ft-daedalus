---
description: Build a bounded plan for the current repo slice using repo-local harness helpers
agent: planner
subtask: true
---
Plan the current task for `$ARGUMENTS`.

Use the repo-local harness helpers first:
- call `repo_profile` to understand repository shape
- call `related_context` for the named paths or the current repo slice
- call `verify_changed` if the task already has changed files

Return only:
- objective
- write scope
- verification
- done when
