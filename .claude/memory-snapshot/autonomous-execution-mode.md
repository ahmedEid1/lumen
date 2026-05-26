---
name: autonomous-execution-mode
description: "When the user explicitly hands off control (\"team should work on it, you decide\", \"won't review, keep going until the end\"), set aside the one-fix-per-iteration ralph style and drive end-to-end with MAXIMUM-parallelism worktree agents + frequent commits"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fc8f1217-97de-4904-9a5f-4e226102a445
---

When this user says some variant of "the team should work on it, you decide how, I won't review, keep going until the end" — that is an explicit toggle out of [[ralph-iteration-style]] into autonomous-execution mode for the duration of that task.

**Why:** the user deliberately operates in two modes: Ralph-cadence (one focused fix + regression test + commit + their review) when they want to audit each step, and autonomous (parallel waves, I design the execution model, I integrate, no check-ins) when they want the work driven to completion. Conflating the two — e.g. asking for approval after every change in autonomous mode, or batching commits in Ralph mode — gets it wrong both directions.

**How to apply when in autonomous mode:**
- Design the execution plan myself (phases, parallel vs. sequential, verification gates)
- **Default to maximum parallelism, not a single sequential executor.** The user explicitly pushed back on a single-worker dispatch with "why one worker? why are you not using a full team? and all the resources you need?" — confirmed that "team as big as need + unlimited budget" should be taken literally. Dispatch one agent per independent unit of work.
- **Worktree isolation is unreliable on this codebase.** Tried it twice during the rebuild; both rounds had the same failure: agents wrote to the parent repo via absolute paths despite the prompt saying "RELATIVE paths only", AND the dev Postgres is shared across worktrees so parallel `alembic`/`pytest` collided on `alembic_version`. See [[worktree-gotchas]] for the full pattern.
- **Working approach (proven across Phases C2-wave-2, D, E):** dispatch parallel agents WITHOUT `isolation: "worktree"`. They write directly to the parent. Give each agent a disjoint file scope (own a feature directory) and tell them explicitly NOT to touch the other agents' files. Each agent commits on `main` directly. The risks: (a) parallel agents touching the same shared file (CHANGELOG.md, router.py, i18n files, models/__init__.py) will race on the index lock or overwrite each other's edits — agents call this "auto-formatter reverting my changes" but it's actually parallel-agent contention; (b) one agent's commit may sweep in another agent's uncommitted work. Both are tolerable: the work still lands, just on slightly muddled commits.
- **For the 3 truly shared files** (CHANGELOG.md, i18n en/ar, router.py) **dispatch sequentially or accept jumbled commits.** This session's compromise was: accept jumbled commits, let the marker commit (e.g. E3's `ecacffe`) note where the actual code landed, move on.
- Each completed change still gets a commit with a "why" body and a CHANGELOG entry — the audit trail still matters even without per-iteration review
- Commit frequently (every change), not in batches at the end — that preserves progress across any session restart
- Verify by driving the running stack at phase boundaries (docker compose + Playwright + tests)
- Push to completion or to honest token-budget exhaustion; report a clean handoff at the stop point
- Don't seek check-ins along the way; surface only blockers that genuinely require a decision the user delegated to me to make

**How to apply when in Ralph mode:**
- Revert to [[ralph-iteration-style]]: one focused change per iteration, regression test, CHANGELOG entry under `### Fixed (iteration N)` / etc., one commit with conventional-commits subject + why body, stop and let the user review

**Signal that triggers autonomous mode:** the user explicitly says they won't review, gives complete freedom, tells me to design the execution model, or both.
