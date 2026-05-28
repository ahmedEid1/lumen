# Lumen QA + Improvement Loop continuing

Run a continuous loop on Lumen live at lumen.ahmedhobeishy.tech.
Each iteration walks the app as student, instructor and admin and
in the same pass fixes what's broken and improves what's weak.
Capture findings from each persona's perspective.

Parity rule: every feature is both buildable and reachable from
the UI. Backend without a consumer — build the UI or delete the
endpoint. UI placeholder without a backend — finish the backend.
Neither direction is allowed to drift.

Codex is the working partner — brainstorm uncertain calls, run
codex review --base origin/main after every batch.

Orient before iter 1 of this run: read CLAUDE.md,
~/.claude/projects/-home-ubuntu-projects-E-Learning-Platform/memory/MEMORY.md,
and docs/qa-loop/STATUS.md as the append-only iteration log and
your running ledger.

Per iteration:

1. Walk every reachable surface across all three personas. Golden
   path, edge cases, mobile, keyboard and axe on each. For each
   persona, capture two streams — fixes meaning broken or off or
   confusing or stale or inaccessible, and improvements meaning
   what this persona would want next.
2. Run a backend / UI parity sweep alongside the walk. Dump the
   OpenAPI spec, cross-reference against frontend usage, and for
   every gap force a decision — build, wire, or delete.
3. Address everything in the same iteration. Ship the
   improvements that survive codex critique. Record the rejected
   ones in STATUS.md with the reason so they don't get
   re-proposed.
4. After every change, sweep the repo for contradictions in
   README, CHANGELOG, docs, ADRs, OpenAPI client, screenshots,
   .env.example, docker-compose files, and comments.
5. Verify locally — lint, fmt, test.api, test.web, tsc,
   Playwright on changed surfaces, axe on changed routes. Use
   prod-parity locally where it matters with EMBEDDING_PROVIDER
   noop to match CI's e2e env. Skip the verify only when local
   is hardware-bound — CI is the judge.
6. Commit per change with why and how verified.
7. Push in batches when a coherent slice is ready. Deploy is
   automatic on CI green — gh run watch returning means deploy
   ran. No manual approval click needed.

An iteration is done when the walk's fixes have landed, surviving
improvements have shipped, the FE / BE gap log in STATUS.md is
up to date, and codex's last review came back clean. Then start
the next iteration.

Guardrails:

- Zero-dollar stack — if anything needs a new paid service, stop
  and ask.
- Pause and ask before touching auth, RBAC or billing semantics,
  renaming a public route, or anything that looks like secrets
  or PII.
- Propose, don't implement for product-direction changes — new
  top-level feature, positioning shift, or course-content
  rewrite.
- Stop and surface if a test breaks in a way you can't isolate,
  or the same shortcoming returns across iterations because
  that's structural — propose an ADR.
