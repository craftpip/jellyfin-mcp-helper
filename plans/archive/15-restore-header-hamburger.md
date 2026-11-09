# 15 — Restore the header hamburger + the work lost with it

## Background / RCA (why it disappeared)

The header hamburger (and a chunk of related mobile/UI work) was built on
2026-09-22 but never made it back onto `main`. The full RCA is below; the
short version is that the built bundle kept the hamburger while the JSX source
already reverted silently on disk (AGENTS.md "Filesystem rollback hazard"), and
the commit carrying it was then `git reset` away and re-committed without it.

### git timeline

| When | SHA | What happened |
|---|---|---|
| 2026-09-21 01:15 | `5c2bc75` | Last clean commit: "style: responsive report/history cards with touch targets" |
| 2026-09-22 13:23:03 | `02adad0` *(dangling)* | Commit with the hamburger. Built bundle `index-DH06j_NZ.js` contains `nav-burger`, `setNavMenu`, `☰`; `theme.css` has `.nav-wrap` / `.nav-burger` / `.top-nav` + the ≤730px mobile nav panel |
| 13:23:12 | `d58fb01` *(dangling, amend)* | Same content — still has the hamburger |
| 13:23:20 | — | `reset: moving to HEAD~1` — amended commit discarded |
| 13:23:24 | — | `reset: moving to 5c2bc75` — all hamburger work dropped from the branch |
| 13:24:19 | `760bab1` | Re-commit "make source path horizontally scrollable" — hoisted **only** the scroll fix; bundle rebuilt from resync source (`index-CF2QBl6V.js`) — **no hamburger** |
| (then) | `894c2ff` | current `main` HEAD; hamburger absent from source and bundle |

### Root cause

Evidence that the source had already reverted before the dangling commit was
assembled:

- `02adad0` **bundle has** hamburger markup (`nav-burger`, `setNavMenu`, `☰`).
- `02adad0` **source does not**: `git show 02adad0:.../TopBar.jsx | grep nav-burger` = 0,
  `git show 02adad0:.../AppStore.jsx | grep navMenu` = 0.

So the bundle was built while the source still contained the hamburger; the JSX
files then reverted on disk (the documented rollback hazard), and the subsequent
`reset` + re-commit finished the job by rebuilding from the reverted source.

## What was lost (all recoverable from the dangling commits)

`02adad0` vs its parent `5c2bc75` contained, none of which is on `main` now:

1. **Hamburger nav** — `TopBar.jsx` markup (`☰` button, `setNavMenu`), `AppStore.jsx`
   state (`navMenuOpen`), and CSS: `.nav-wrap`, `.top-actions .nav-burger`,
   `.top-nav` (+ `.top-nav.open` dropdown panel) — into which History/Settings/Logout
   (and the library dropdown) collapse on mobile.
2. **Mobile report bar** — `.report-bar.mobile` (`.report-counts`, `.report-search`).
3. **Transfer panel redesign** — persistent single confirm-progress box
   (`.transfer-panel`), group rows, minimize/dismiss toggles.
4. **Empty-report state** — `.empty-report` organized panel.
5. Misc: `.table-scroll`, checkbox alignment, `.admin-footer` spacing, `@media`
   breakpoint 720px→730px for **both** report and history.

## Recovery source of truth

- `02adad0` (and identical-ish `d58fb01`) — `git show 02adad0:<path>` for the
  source bundle contents.
- The compiled bundle `02adad0:app/ui/react-react-dist/assets/index-DH06j_NZ.js`
  is the only copy of the compiled hamburger markup — extract `nav-burger` /
  `setNavMenu` / `☰` behavior from it to reconstruct the JSX.

## Steps

1. **Extract the exact source diffs from `02adad0`.**
   - `git diff 5c2bc75 02adad0 -- app/ui/react/src/styles/theme.css` — hamburger +
     all companion CSS.
   - Reconstruct `TopBar.jsx` + `AppStore.jsx` hamburger markup/state from the
     bundle (`02adad0:.../index-DH06j_NZ.js`, grep `nav-burger`, `setNavMenu`,
     `navMenuOpen`, `☰`).
2. **Re-apply to source**, keeping current style conventions:
   - `app/ui/react/src/components/TopBar.jsx` — burger button + `top-nav` panel.
   - `app/ui/react/src/store/AppStore.jsx` — `navMenuOpen` state.
   - `app/ui/react/src/styles/theme.css` — `.nav-wrap` / `.nav-burger` / `.top-nav`
     + the ≤730px collapse block.
   - Include the other lost work only if it still fits `main`'s current UI
     (transfer panel, empty-report) — do **not** resurrect stale markup that
     conflicts with current components.
3. **Verify** — `npm test` in `app/ui/react`, then `npm run build`, then
   `docker restart jellysort`. Check header on desktop (burger hidden, inline
   nav) and ≤730px (burger appears, others collapse into it).
4. **Commit** to `dev` (dev → prod per release workflow).

## RCA — full root-cause chain (for a later fix, not just this plan)

### Failure chain

1. **Filesystem rollback hazard (primary cause).** Edits under `/www1/...`
   silently revert after a container restart / under load — documented in
   AGENTS.md, no error is ever reported by edit tools. This is what deleted the
   JSX (`TopBar.jsx`, `AppStore.jsx` hamburger code) out from under us.
   Evidence: `02adad0`'s built bundle still contained `nav-burger`/`setNavMenu`/`☰`
   (compiled while the source still had it), but the *same commit's* source files
   had zero matches — the source reverted before the commit was assembled.
2. **Un-committed work persisted too long.** The hamburger lived only in the
   working tree + an uncommitted build for hours. There was no `git stash` /
   `git commit` checkpoint, so when the disk reverted the source, the only
   remaining copy was the stray compiled bundle.
3. **The carrying commit was reset away instead of fixed.** `02adad0` / `d58fb01`
   (which held the bundle copy) were `git reset` to base and rewritten as
   `760bab1` from the *reverted* source — permanently dropping the work from the
   branch. The re-commit kept only the scroll-fix CSS that happened to survive
   on disk.
4. **No cross-check until a human noticed.** Nothing re-verified that the rebuild
   matched the authored UI; the hamburger was only missed visually later.

### Why the loss was invisible at each step

- Edit tools never report the rollback → no error surfaced at write time.
- The build succeeded because it ran *before* the revert; dist assets existed.
- `git reset` + re-commit is a normal-looking reflog entry, not an error.
- `grep`-grade checks (the only ones run) passed against the reverted tree.

### What "fix later" means

The rollback cause is environmental (filesystem/host), not git. Mitigations:
- Keep in-flight work **committed or stashed**, never long-lived in the worktree.
- In the pre-commit ritual (AGENTS.md: "re-verify the file content"),
  `grep` the *source* for the feature before rebuilding (e.g. `grep -c setNavMenu
  app/ui/react/src/store/AppStore.jsx`), not just the dist.
- Consider a periodic `git fsck --lost-found` sweep (see below) so stray work is
  noticed early.

## Finding MORE lost commits (audit procedure)

The dangling-commit pool is the recovery surface. Run after any suspected loss:

```
git fsck --no-reflogs | grep "dangling commit"
```

To identify which contain genuinely lost work (vs. superseded WIP):

```
git merge-base --is-ancestor <commit> HEAD && echo in-main || echo LOST
git diff --name-only <commit>^ <commit>        # files it touched
git show HEAD:<file> | diff - <(git show <commit>:<file>)  # still differs today
```

Current inventory (2026-09-22, all absent from `main`):

| Commit | Subject | Touched (differs from main today) | Verdict |
|---|---|---|---|
| `02adad0` / `d58fb01` | hamburger + scrollable source | `theme.css`, dist bundle | **lost UI work — restore (this plan)** |
| `d07c9f6` | trust folder for series | `classifier.py`, `resolver.py` | **review — may be a lost fix** |
| `4c557c5` | foreign-episode words | `jellyfin.py` | review |
| `1eb33e7` | full-folder-access jellyfin user | `classifier.py` | review |
| `4c734e0` | phantom_show_folder | `scan_manager.py`, `theme.css`, `test_ui_api.py` | review |
| `bf816e3` `74798a0` `f3f7834` | older WIP stashes | many files | likely superseded; diff per-file before touching |

For each candidate, port the specific hunk to `main` (dev first) rather than
cherry-picking wholesale, since later commits built on the reverted tree.

## Prevent-this-again checklist (rules to adopt)

1. **Never keep source work uncommitted across a restart/build.** Commit or
   `git stash` before any container restart or long build.
2. **Verify source, not just dist.** After any build, `grep` the JSX/SCSS source
   for the feature before relying on it.
3. **Never `git reset` a commit that might hold valid work.** Prefer
   amend/additive commits; if a reset is required, first `git stash` or tag the
   pre-reset state, and diff the rewritten commit against the original
   (`git diff 760bab1 02adad0`) to catch dropped changes.
4. **Add a `git fsck` sweep to the release workflow** (app/core/version.py bump /
   releasing step) so dangling work is reviewed, not forgotten.
5. **After any rollback-hazard incident**, re-inventory: `git fsck`, reflog
   review, and re-verify the affected files before continuing.

## Guardrail (commit to memory)

When a source edit "loses" itself silently, re-verify after any restart, and
never rebuild/reset from a source tree that wasn't re-read after a restart —
the AGENTS.md rollback-hazard block. Prefer `git stash`/commits for long
builds so in-flight work cannot be lost to a disk revert.