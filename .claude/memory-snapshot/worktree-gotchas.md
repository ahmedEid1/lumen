---
name: worktree-gotchas
description: Two things that broke parallel-worktree agent dispatch on the first try and how to prevent them
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fc8f1217-97de-4904-9a5f-4e226102a445
---

When dispatching parallel `Agent({ isolation: "worktree" })` agents on this repo, two things bite hard if not pre-empted:

### 1. The default worktree base is `origin/master`, which is the LEGACY Django prototype

`origin/HEAD` on this repo points to `master`. The Lumen rewrite lives on the `Rewrite` branch. `worktree.baseRef: "fresh"` (the harness default) branches new worktrees from `origin/<default-branch>` — so every worktree was stranded on commit `a9bfdd4 fixing the readme`, where only legacy Django code exists (`manage.py`, `chat/`, `courses/`, no `apps/backend/` at all).

**Fix (long-term):** add `"worktree": { "baseRef": "head" }` to `.claude/settings.json`. That makes new worktrees branch from the current local HEAD (typically `Rewrite`). **Status as of 2026-05-25:** applied and committed on `Rewrite` as `b8e1d07`. The file was previously 0 bytes — the fix had been documented in this memory but never written to disk before that commit.

**Critical caveat — settings cache:** The harness reads `worktree.baseRef` at *session start* and caches it. Changing settings.json mid-session does **not** affect `Agent({ isolation: "worktree" })` calls in the current session, even if the file change is verified on disk. Verified by 3 failed test spawns in this session after writing the fix: every spawn still landed on master. The setting only takes effect for sessions that start with the file already containing the value. So if you find this memory mid-session and need worktrees to work now, restart Claude Code first or rely on defense-in-depth below.

**Defense in depth (works regardless of cache state):** every agent prompt should include a first-step sanity check — `pwd && ls apps/backend apps/frontend` — and a recovery if the worktree is stranded (`git fetch origin && git reset --hard Rewrite`). Verified working 2026-05-25: the same session whose harness-cache spawned 3 stranded worktrees recovered the 4th to `b8e1d07` (Rewrite HEAD) with apps/backend present. Some agents will self-recover; others will write to the parent repo via absolute paths and contaminate the main worktree if you don't enforce relative paths (see #2 below).

### 2. Agents will use absolute paths if the prompt contains them

If a prompt says `E:\2026\building with AI\updating old projects\E-Learning-Platform\apps\backend\...`, agents will pass that absolute path to Edit/Write — which lands in the **parent** repo, not their worktree. Multiple agents writing to the parent simultaneously jumbles their changes together and is irrecoverable in practice.

**Fix:** every agent prompt must use **relative paths only** (`apps/backend/...`). Mention this rule explicitly. Don't include the project root anywhere in the prompt.

### 3. The dev Postgres is shared across all worktrees

`docker compose up` exposes one Postgres on the host. If multiple agent worktrees run backend migrations / pytest concurrently, they collide on `alembic_version` and pollute each other's test data. (Saw `alembic_version` at 0009 with conflicting 0008 heads after a botched parallel run.)

**Fix:** tell agents to NOT run backend pytest in their worktree during parallel dispatch. The orchestrator runs the full backend suite ONCE after merging all branches. Frontend vitest is fine in parallel — it's per-worktree `node_modules`, no shared state.

### 4. `pnpm` may not be on PATH per-worktree

`pnpm` was missing on the host the first time. Once installed globally (`npm install -g pnpm@9.15.0`), subsequent worktrees see it on PATH. But each worktree still needs its own `node_modules` (~3m20s install). Budget this in time estimates.

### Operating recipe for parallel worktree dispatch on this repo

1. Confirm `.claude/settings.json` has `"worktree": { "baseRef": "head" }`.
2. Confirm parent worktree is on `Rewrite` (or the branch you want as the integration target).
3. Every agent prompt:
   - Relative paths only
   - First-step sanity check + auto-recovery to `Rewrite` HEAD
   - "Do NOT run backend pytest" — frontend vitest only
   - "Commit on your worktree branch, don't push, don't amend"
4. After all agents return: orchestrator merges each branch into the integration target sequentially, resolving conflicts on the shared files (`CHANGELOG.md`, `models/__init__.py`, `api/router.py`, `i18n/messages/en.ts` and `ar.ts`).
5. After all merged: run the full backend pytest + frontend vitest once on the integration branch.
6. `git worktree remove -f -f <path>` then `rm -rf` the dir (Windows leaves an empty dir), then `git branch -D` the worktree branch.
