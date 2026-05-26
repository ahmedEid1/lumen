---
name: ralph-iteration-style
description: "User's expected Ralph loop iteration cadence — one focused fix per iteration, regression test, commit-with-why, no batched changes"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 570ed99c-48b3-471c-a2d9-c72712d55445
---

This user runs Ralph loops with `--max-iterations 50` and expects a
specific iteration shape. Across ~98 iterations the pattern that
works for them is:

**One iteration = one focused change.** No "while I'm here" cleanup,
no batched fixes, no opportunistic refactors. If you find a second
bug while fixing the first, note it in the commit body and pick it
up in the next iteration.

**Each iteration ships**:
1. The fix or feature
2. A regression test that would have caught the bug (or a new test
   for the feature) — placed in `apps/backend/tests/test_<topic>.py`
   or `apps/frontend/tests/<topic>.test.tsx`
3. A `CHANGELOG.md` entry under `[Unreleased]` with
   `### Fixed (iteration N)` / `### Added (iteration N)` /
   `### Security (iteration N)` / `### Docs (iteration N)` /
   `### Performance (iteration N)` / `### Tests (iteration N)`
4. One commit with a Conventional-Commits subject
   (`fix(scope): ...`, `feat(scope): ...`, `sec(scope): ...`,
   `docs(adr): ...`, `perf(scope): ...`, `test(scope): ...`)
   and a body explaining the **why** not the what

**Why:** the user reads commit messages and the CHANGELOG to audit
the work. Squashing two fixes into one commit loses that audit
trail. Naming the iteration in the CHANGELOG header is how they
cross-reference between the docs, the commits, and the bug-hunt
history.

**Don't**:
- amend prior commits
- skip hooks (`--no-verify`)
- batch fixes into a single commit even if they look related
- pad iterations with cosmetic work when there's nothing real left —
  stop honestly and surface in a final summary text message instead

**How to apply**: look at iter 98's commit body (`affe07d`) for the
exact tone. Each numbered point states the symptom, the root cause,
and the fix in 3-5 lines. No emojis, no marketing language, no
"successfully resolved" — just what it was and what was done.
