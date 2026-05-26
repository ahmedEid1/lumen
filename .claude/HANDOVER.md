# Handover for the next Claude Code session

Last updated: **2026-05-26** (commit `fe94ab3` on `Rewrite`).

This file is what you (the next Claude Code session, on a new device) read first. It tells you where things stand, what's already known, and what to do before you touch anything.

---

## TL;DR — where things stand right now

- **Branch**: `Rewrite` (NOT `master`; master is 358+ commits stale and explicitly off-limits).
- **CI**: all 5 workflows green on `fe94ab3` — CI / Frontend / Build container images / E2E / Accessibility / Eval smoke / Secret scan.
- **Production**: live at https://lumen.ahmedhobeishy.tech on AWS t4g.small via Terraform (commit `1dc7502`). Groq Llama 3.3 70B + Cloudflare Workers AI embeddings. Deployer IAM access key already rotated.
- **Pytest**: ~12 min on CI (was timing out at 25 min cap) — parallelized with `pytest-xdist -n 4`, see `.claude/memory-snapshot/pytest-infra.md` for the full reasoning.
- **Open tasks**: none queued. Last session finished a clean push + green CI.

---

## First-session bootstrap — Linux

You (Claude) are reading this because the user just landed on a new Linux machine and asked you to pick up where the previous session left off. **Do all of the steps below yourself, in order, without stopping to ask permission for routine setup.** Only halt if you hit a credential / secret / decision that genuinely needs the user.

### Step 1 — Import the memory snapshot into your own state

Claude Code stores project memory at `~/.claude/projects/<slug>/memory/`. The slug is the absolute repo path with `/` replaced by `-`. Don't compute it by sed — list `~/.claude/projects/` and pick the directory that matches this repo's path (it will already exist if you've written or read any memory this session). If it doesn't exist yet, create it. Then:

```bash
mkdir -p ~/.claude/projects/<slug>/memory
cp .claude/memory-snapshot/*.md ~/.claude/projects/<slug>/memory/
ls ~/.claude/projects/<slug>/memory/ | wc -l   # expect 15
```

Read `MEMORY.md` (the index) and skim each file once.

### Step 2 — Verify the clone is at the right state

```bash
git status                  # clean
git rev-parse --abbrev-ref HEAD   # Rewrite
git log --oneline -1        # 7311815 chore(handover): ...
git fetch origin && git status -uno    # up to date with origin/Rewrite
```

If the tip doesn't match, `git pull` and re-read this file.

### Step 3 — Bring up the local dev stack

```bash
docker compose up --build -d
docker compose ps        # api, web, db, redis, s3, mail, worker, beat — all running / healthy
```

If `docker` is missing, install Docker Engine + Compose plugin via the distro package manager. If `make` is missing, install build-essential.

Smoke-check:

```bash
curl -fsS http://localhost:8000/healthz       # {"status":"ok"} or similar
curl -fsS http://localhost:3000 | head -3     # any HTML
```

### Step 4 — Verify the test suite still passes

```bash
make test.api    # pytest, ~3 min wall locally with xdist
make test.web    # frontend vitest, ~10s
```

If something breaks during setup or smoke, fix it before asking the user. Common first-boot trip-ups are in `.claude/memory-snapshot/first-boot-gotchas.md` — consult that file BEFORE googling.

### Step 5 — Report back

When the stack is up and tests are green, summarize: "Bootstrap complete on Linux. Stack up, tests green, on Rewrite @ `<sha>`. Ready for the next task."

**Only stop and ask the user when:**
- A credential is needed (Anthropic / Groq / AWS / GitHub) and it's not already on the new machine
- A decision is needed that isn't already documented in the handover or memory files
- Something is genuinely broken in a way the handover didn't predict

---

## Critical rules (carried from previous sessions)

These are persistent constraints — they override default behaviour:

1. **`master` is off-limits.** All real work happens on `Rewrite`. Master is the stale merge target for the historical CS50 project. Never push to master, never branch from master.
2. **No secrets through tool params.** API keys, AWS keys, JWTs, anything sensitive — never pass them as command args. The previous IAM access key was rotated specifically because it was passed through `aws configure set` tool params.
3. **Free / free-tier first.** When picking a deploy / LLM / DB provider, lead with the free option. Current stack is intentional: Groq free tier + Cloudflare Workers AI free tier + AWS t4g.small (12-month free) + Cloudflare DNS (free) + GHCR (free).
4. **Ralph cadence is the default** (one focused fix + regression test + commit-with-why per iteration), but flip to autonomous-execution-mode when the user explicitly hands off control. See `.claude/memory-snapshot/ralph-iteration-style.md` and `.claude/memory-snapshot/autonomous-execution-mode.md`.
5. **"The app works perfectly"** means running-the-app evidence (curl, screenshots, docker compose up + smoke), not just a green test suite. See `.claude/memory-snapshot/verification-criteria.md`.

---

## Important things-to-know that aren't in the code

| Topic | File | Why it matters |
|---|---|---|
| Owner positioning | `memory-snapshot/owner-positioning.md` | Ahmed Hobeishy uses Lumen as the portfolio anchor for agentic-AI engineering roles. Production-grade hardening + MCP + multi-agent + eval-suite are the priority axes. |
| AWS prod state | `memory-snapshot/aws-deployment-state.md` | What's actually deployed, what env, what was rotated. |
| Cost preferences | `memory-snapshot/cost-preferences.md` | Why Groq + CF + AWS t4g.small was chosen over alternatives. |
| Pytest infra (just-done) | `memory-snapshot/pytest-infra.md` | Don't bump `-n 4` to `-n auto`. Why `ENV=test` is forced. Why `--max-worker-restart=0`. |
| First-boot gotchas | `memory-snapshot/first-boot-gotchas.md` | CORS_ORIGINS shape, `.test` TLD, role typing — three things that bite a fresh `docker compose up`. |
| Design pivot pattern | `memory-snapshot/design-pivot-pattern.md` | Visual tokens are disposable; primitives + i18n + server/client split are NOT. |
| Worktree gotchas | `memory-snapshot/worktree-gotchas.md` | `worktree.baseRef: head` is committed but harness caches it at session start. |
| Oracle (defunct) | `memory-snapshot/oracle-deployment-state.md` | Skim and ignore — Oracle was abandoned; current deploy is AWS. |
| Windows-only ports | `memory-snapshot/windows-reserved-ports.md` | **Probably won't apply on a Linux/macOS new device.** Read once, discard if not on Windows. |

---

## Snapshot of recent commits

```
fe94ab3 ci(build): lowercase the GHCR repository owner before tagging images
62cc5cb ci(build): use trivy-action@v0.36.0 with v-prefix
14e096c ci(build): bump trivy-action 0.28.0 -> 0.36.0
64e7aac test(backend): bump pytest-timeout to 120s + fail-fast on worker crash
9597149 test(backend): fix SIM118 + ruff format in conftest
3c428e1 test(backend): drop orphan test DB on setup failure
96b02e9 test(backend): parallelize pytest with xdist + pin ENV=test
fc2505c ci(backend): cap backend job at 25min so hung tests fail loud
d2e67a1 ci+cd: round-3 reviewer fixes
```

If `git log --oneline -10` on the new machine matches this from the top, the clone is current.

---

## Things deliberately NOT in scope

- **Backend pytest test-isolation bug** (`uq_courses_slug_live` constraint). Diagnosed as a non-issue (the postgres log entry was the savepoint-retry mechanism working correctly, not a real test bug). Don't re-investigate.
- **Mypy strict mode.** Stays at `strict = false` until the 166-error wall is paid down separately. The CI `mypy` step is `continue-on-error: true` for the same reason.
- **`-q` flag on pytest.** Always omit it. The pyproject `addopts` pins `-v --durations=10` for streaming output; `-q` would silently override and re-introduce the "hung suite" diagnostic blindspot.

---

## If something is wrong

- The previous session's full reasoning lives in the transcript at `C:\Users\ahmed\AppData\Local\Temp\claude\E--2026-building-with-AI-updating-old-projects-E-Learning-Platform--claude-worktrees-gallant-antonelli-49a336\4059c30a-7172-4501-9264-82e562516963.jsonl` — this path won't exist on the new machine, so just go from this handover + the memory snapshot.
- The repo's `CLAUDE.md` (if present) and `docs/` have the canonical project-level instructions.
- The `.claude/memory-snapshot/MEMORY.md` is the index; each entry is one line + a link to its detail file. Don't put memory content directly in `MEMORY.md`.

Good luck on the new device. Don't break master.
