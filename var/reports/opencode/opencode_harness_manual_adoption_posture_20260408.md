# OpenCode Harness Manual Adoption Posture

Date: 2026-04-08

## Decision

The canonical adoption path for the reusable OpenCode harness is now manual
review and manual patching of the target repository.

## What Changed

- `ft-daedalus` continues to own the canonical harness source under
  `opencode-harness/template/`
- `ft-daedalus` now documents manual adoption in
  `opencode-harness/MANUAL_ADOPTION.md`
- the earlier installer script path was removed from the active implementation
- future target repo adoption should happen by bounded manual review, merge, and
  verification

## Why

- the owner does not want a script to touch target repos by default
- repo adoption must stay reviewable and judgment-driven
- the trusted path is explicit manual change, not automatic file injection

## Canonical Surfaces

- `opencode-harness/README.md`
- `opencode-harness/MANUAL_ADOPTION.md`
- `opencode-harness/template/`

## Result

`ft-daedalus` remains the canonical home for the OpenCode harness, but it now
acts as:

- template source
- manual runbook
- evidence home

It is no longer positioned as an auto-installer against owner repos.
