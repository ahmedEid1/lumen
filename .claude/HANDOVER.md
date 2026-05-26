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

## First-session bootstrap

Run this **once** from the repo root to import the saved memories into your local Claude Code state:

```bash
# 1. Find your Claude project memory directory. Claude Code derives it from
#    the absolute repo path by replacing `/` and `\` with `-` and prefixing
#    with `~/.claude/projects/`. Adjust if your repo lives elsewhere.

# macOS / Linux:
PROJECT_SLUG=$(pwd | sed 's|^/|-|; s|/|-|g')
MEM_DIR="$HOME/.claude/projects/${PROJECT_SLUG}/memory"

# Windows PowerShell equivalent:
#   $slug = (Get-Location).Path -replace '\\','-' -replace '^([A-Z]):','-$1-'
#   $memDir = "$env:USERPROFILE\.claude\projects\$slug\memory"

# 2. Copy the snapshot in
mkdir -p "$MEM_DIR"
cp .claude/memory-snapshot/*.md "$MEM_DIR/"

# 3. Verify
ls "$MEM_DIR" | wc -l   # should print 15
```

Then tell Claude in the first message:

> "I'm continuing the previous session on a new device. Read `.claude/HANDOVER.md` for the state snapshot, and the memory files at `.claude/memory-snapshot/` (also copied into the standard Claude memory dir). Branch is `Rewrite`. Don't touch master."

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
