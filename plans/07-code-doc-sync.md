# 07 — Code ↔ Doc Sync (recursive)

> **Status: ACTIVE — run repeatedly, never deleted.** This is a perpetual
> maintenance plan that keeps `README.md`, `docs/`, and `AGENTS.md` accurate
> against the code.

## Purpose

The repo docs describe the code at a specific commit. After every feature or
fix, review what changed and fold it into the docs instead of letting the docs
drift.

## Sync procedure

1. Review the commits since the last synced commit
   (`git log --oneline <last-synced>..HEAD`).
2. For each commit, update the closest existing doc section (AGENTS.md pattern
   blocks, `docs/backend/*`, `docs/services/*`, `docs/web-ui/*`,
   getting-started/configuration.md) — never create a new standalone block for
   something that extends an existing topic.
3. When a plan in `plans/` is fully implemented: absorb its durable knowledge
   into `docs/` (mark it COMPLETE in a status header with the implemented
   deviations, then delete the plan file). Done plans 03–06 live in
   `docs/backend/auth.md`, `docs/services/*`, and `docs/web-ui/*`; do not
   recreate them.
4. Update README.md's **Last synced commit** line.

## Checks before finishing

- `grep -rn "plan 0" README.md AGENTS.md docs/` → no references to deleted
  plan files.
- `grep -rn "TODO\|FIXME" docs/` → none.
- Plan references in docs (`docs/backend/auth.md`, `docs/services/*`,
  `docs/web-ui/*`) point at real files (relative links resolve).
- If the code changed behavior or env vars, verify
  `docs/getting-started/configuration.md` matches `.env.example` and
  `app/services/env_manager.py` `ENV_SPEC`.