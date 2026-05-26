# Handover for the next Claude Code session

Last updated: **2026-05-26** (commit `fe94ab3` on the branch then named `Rewrite`; that branch was renamed to `main` later the same day — see the iteration-3 CHANGELOG entry).

This file is what you (the next Claude Code session, on a new device) read first. It tells you where things stand, what's already known, and what to do before you touch anything.

---

## TL;DR — where things stand right now

- **Branch**: `main` (renamed from `Rewrite` on 2026-05-26). `legacy` (renamed from `master`) is the frozen 358+-commit CS50 Django prototype — read-only history, never push or branch from it.
- **CI**: all 5 workflows green on `fe94ab3` — CI / Frontend / Build container images / E2E / Accessibility / Eval smoke / Secret scan.
- **Production**: live at https://lumen.ahmedhobeishy.tech on AWS t4g.small via Terraform (commit `1dc7502`). Groq Llama 3.3 70B + Cloudflare Workers AI embeddings. Deployer IAM access key already rotated.
- **Pytest**: ~12 min on CI (was timing out at 25 min cap) — parallelized with `pytest-xdist -n 4`, see `.claude/memory-snapshot/pytest-infra.md` for the full reasoning.
- **Open tasks**: none queued. Last session finished a clean push + green CI.

---

## Read this first — the previous box was Windows + Docker Desktop + WSL2

You are on a **clean Linux server**. Many of the gotchas in the memory snapshot were Windows-host quirks that **probably don't apply to you**. Don't waste cycles chasing them.

### Memory files that are Windows-specific — skim, don't act

| File | Why it doesn't apply on clean Linux |
|---|---|
| `windows-reserved-ports.md` | Reservations are set by Hyper-V on every Windows boot. A Linux server has no equivalent. Ignore the port-7700 advice; bind whatever you want. |
| `worktree-gotchas.md` §1 "settings cache" | Was observed on the Windows harness. The fix (`worktree.baseRef: head`) is already committed in `.claude/settings.json` and a *fresh* session picks it up at start — that's you. The §2 (relative paths only) and §3 (shared Postgres) advice **still applies universally** though. |
| `worktree-gotchas.md` §6 "Windows leaves an empty dir" | Linux's `rm -rf` cleans up properly. Step is a no-op for you. |

### Setting differences likely to surface

| What | Windows dev box | Clean Linux server |
|---|---|---|
| Docker | Docker Desktop, integrated | Probably **not installed** — install Engine + Compose plugin via the distro package manager (`apt install docker.io docker-compose-plugin` / `dnf install moby-engine docker-compose-plugin` / whatever the distro uses). User needs to be in the `docker` group: `sudo usermod -aG docker $USER` then re-login. |
| `make` | Usually pre-installed via Git Bash | **May be missing** — `apt install build-essential` or `dnf install make`. |
| Python deps | uv was installed | **May be missing** — `curl -LsSf https://astral.sh/uv/install.sh \| sh` (or however the distro packages uv). |
| Node + pnpm | Globally installed at v22 / 9.15.0 | Install Node 22 (nvm or distro), then `npm install -g pnpm@9.15.0`. |
| Filesystem perf | Windows host mounts were slow | Linux native FS is fast; backend pytest local could be **faster** than the 2:42 measured on Windows. |
| `-n 4` pytest workers | Pinned because a 12-core Windows host saw `KeyError: <WorkerController gw11>` (postgres serializes 12 concurrent CREATE DATABASE) | Linux server may have a different CPU count and different postgres throughput. **Try `-n 4` first** (matches CI), and only revisit if local time is far off from the 2-3 min target. Don't pre-emptively bump to `-n auto` — the per-worker CREATE DATABASE bottleneck is a postgres property, not a Windows quirk. |
| CRLF line ending warnings | Constant in `git status` | Won't appear on Linux. |

### Things that ARE portable (don't re-investigate)

- `ENV=development` baked into `docker-compose.yml`'s api container — this is project config, applies on Linux too. The conftest forces `ENV=test` to compensate. Already fixed; just letting you know it's intentional.
- Groq API key, Cloudflare DNS, AWS prod state — these are *production* state, machine-independent.
- pnpm `-q` / `pnpm test -- --run` flag-parsing flakiness — was real, the fix (`pnpm exec vitest run`) is committed; don't re-investigate.
- All `[tool.pytest.ini_options]` addopts in pyproject — chosen to work on both this Windows box and the CI ubuntu-24.04 runner. Should work fine on your server.

### Likely first-boot timing on a clean Linux server

- Initial `docker compose up --build -d`: **~10-20 min** for first builds (uv + pip wheels + pnpm install + Next.js build). Subsequent boots: ~30s.
- Backend pytest: **~2-3 min** wall (same target as Windows; Linux native FS might even shave it).
- Frontend vitest: ~10s after `pnpm install` (~3m20s the first time).

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
git rev-parse --abbrev-ref HEAD   # main
git log --oneline -1        # latest commit on main
git fetch origin && git status -uno    # up to date with origin/main
```

If the tip doesn't match, `git pull` and re-read this file.

### Step 3 — Bring up the local dev stack

`.env` is gitignored, but `docker-compose.yml` references variables
that have no inline default (e.g. `S3_FORCE_PATH_STYLE`, `SMTP_PORT`).
Without a `.env` file these are passed in as empty strings and
api/worker/beat crashloop with pydantic `bool_parsing` / `int_parsing`
errors. Copy the example first:

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps        # api, web, db, redis, s3, mail, worker, beat — all running / healthy
```

If `docker` is missing, install Docker Engine + Compose plugin via the distro package manager. If `make` is missing, install build-essential.

Smoke-check:

```bash
curl -fsS http://localhost:8000/api/v1/health/live   # {"status":"ok"}
curl -fsS http://localhost:8000/api/v1/health/ready  # {"status":"ok","checks":{"db":"ok","redis":"ok"}}
curl -fsS http://localhost:3000 | head -3            # any HTML
```

### Step 4 — Verify the test suite still passes

```bash
make test.api    # pytest, ~3 min wall locally with xdist
make test.web    # frontend vitest, ~10s
```

If something breaks during setup or smoke, fix it before asking the user. Common first-boot trip-ups are in `.claude/memory-snapshot/first-boot-gotchas.md` — consult that file BEFORE googling.

### Step 5 — Report back

When the stack is up and tests are green, summarize: "Bootstrap complete on Linux. Stack up, tests green, on main @ `<sha>`. Ready for the next task."

**Only stop and ask the user when:**
- A credential is needed (Anthropic / Groq / AWS / GitHub) and it's not already on the new machine
- A decision is needed that isn't already documented in the handover or memory files
- Something is genuinely broken in a way the handover didn't predict

---

## Pre-answered questions (so you don't need to ask)

### Is there an implicit backlog?

**No.** Phase H + Phase I shipped on 2026-05-22 as `1.1.0-agentic` — see the post-execution note at the top of `docs/superpowers/specs/2026-05-22-lumen-v2-agentic-positioning.md` and the `[1.1.0-agentic]` section in `CHANGELOG.md`. The `[Unreleased]` cleanup-loop work (Codex+Claude reviewer rounds, deploy hardening, CI green) also landed. There is no queued task. Wait for the user to set the next one — don't invent work from the spec.

### Ralph or autonomous mode?

**Ralph by default.** One focused fix + regression test + a commit-with-why per iteration; never batch. Flip to autonomous-execution-mode only when the user explicitly hands off control ("you decide, I won't review, keep going until the end" or similar). See `.claude/memory-snapshot/ralph-iteration-style.md` and `.claude/memory-snapshot/autonomous-execution-mode.md`.

### Subagent isolation — fresh worktree or in-process?

The `.claude/settings.json` config (`worktree.baseRef: head`) is already committed and is what your fresh session will pick up at start — the "harness caches at session start" warning in `worktree-gotchas.md` only matters if *you* edit settings mid-session, which you won't. So:

- **Read-only reviewers** (`codex-reviewer`, `pr-review-toolkit:code-reviewer`, `Explore`, `general-purpose` for searches): no worktree, in-process is fine.
- **Implementation agents that edit files**: use `isolation: "worktree"` if the work is parallel or speculative — they get a clean tree branched off `HEAD`, the user can compare, and an unchanged worktree auto-cleans.
- **The first task on the new device**: in-process is fine — user is actively driving and reviewing.

---

## Critical rules (carried from previous sessions)

These are persistent constraints — they override default behaviour:

1. **`legacy` is off-limits.** All real work happens on `main`. `legacy` is the frozen historical CS50 Django prototype (formerly `master`, renamed 2026-05-26 when `Rewrite` became `main`). Never push to legacy, never branch from legacy.
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

Good luck on the new device. Don't break legacy (it's frozen historical state, but still — don't touch it).
