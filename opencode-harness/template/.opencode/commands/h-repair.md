---
description: Fix only the current verification failures, then rerun the smallest truthful checks
agent: build
subtask: true
---
Repair the current failing slice for `$ARGUMENTS`.

Workflow:
1. call `verify_changed`
2. run only the first blocking verification command
3. fix only the failure that blocks that command
4. rerun the smallest truthful checks

Do not widen scope beyond the current failure chain.
