### Activation (A1)

Brought README.md and a handful of stale/dead files into agreement
with what 1.1.0-agentic actually shipped. README "What's running
today" status table flipped — H4/H5/H7 and all five Phase I rows
moved from "in progress" / "queued" to "shipped (1.1.0-agentic)";
H4 renamed to "Oracle Always-Free single-VM deploy runbook" to
match A4's pivot. README "The agentic patterns I built" bullets
re-tagged from `*(planned — Phase I, item Ix)*` to
`*(shipped — ...)*` with present-tense verbs and code links to
the modules that ship the behavior (tutor_orchestrator, authoring_-
orchestrator, mcp/server, learning_path, learner_traces +
agent_tracer). MCP registry badge swapped from the
`pending I1 / lightgrey` placeholder to the canonical
`io.github.ahmedeid1/lumen` blue badge pointing at the v0.1
registry slug; the badge will 404 until the operator runs
`mcp-publisher publish apps/backend/app/mcp/registry_metadata.json`
on their credentialled machine (a quiet HTML comment under the
badge calls that out). Status footer updated with the
2026-05-22 ship date, 2026-05-25 Wave-2 portfolio-activation
completion, and the operator-side remaining list (Oracle VM +
live eval + Loom + applications).

Dead-code sweep: removed the `# ----- free-tier deploy (H4) -----`
Makefile block (`deploy.fly`, `deploy.fly.api`, `deploy.fly.worker`,
`deploy.demo-seed` — all flyctl-dependent and unreachable now that
Wave-2 H4 ships on Oracle); renamed `demo-seed` target's help text
to drop the "H4 free-tier" branding; fixed `.env.example` Groq
block header to cross-reference `docs/deployment/oracle-vps.md`
Step 5 instead of the never-landed "v2 spec §8 addendum"; removed
the `infra/fly/`, `infra/supabase/`, and `infra/vercel/` trees
entirely (Fly + Supabase + Vercel were the original three-vendor
free-tier plan, all replaced by the single-VM Oracle path); and
removed `.github/workflows/deploy.yml` because it ran flyctl
against the Fly apps that no longer exist.

**Files deleted (audit trail):**
- `infra/fly/.dockerignore`
- `infra/fly/Dockerfile.fly`
- `infra/fly/fly.api.toml`
- `infra/fly/fly.worker.toml`
- `infra/supabase/README.md`
- `infra/supabase/connection-pooler-note.md`
- `infra/vercel/README.md`
- `infra/vercel/vercel.json`
- `.github/workflows/deploy.yml`

**Verified still present:** `make eval`, `make publish-rewrite`,
`make demo-seed`, the Oracle deploy workflow path (`scripts/oracle-bootstrap.sh`
+ `docs/deployment/oracle-vps.md`), the eight remaining
`.github/workflows/*.yml`, A5's `![Lumen tutor ...](docs/screenshots/hero.png)`
hero line, A4's `## Deploy it (Oracle Cloud Always Free)` section,
and A6's `publish-rewrite` Makefile target.
