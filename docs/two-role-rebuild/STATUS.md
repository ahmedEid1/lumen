# Two-Role Rebuild — Status Board

> Compact, current-state view. History + decisions live in [CHARTER.md](CHARTER.md) §6 (ledger).
> Updated by the orchestrator as work lands. Last update: **2026-06-03**.

## Where we are

**Wave 1 integration** on branch `two-role-rebuild` (never auto-deployed; main merges at W12 only).

| Stream | Build | Merge | Gate A (Codex) | Gate B (Claude) | Gate C (live) |
|---|---|---|---|---|---|
| S7-pre foundation | ✅ | ✅ 913b978 | ✅ | ✅ | ✅ |
| S1 role collapse | ✅ | ✅ 506e1f5+acf390e | ✅ | ✅ | ✅ |
| S5 BYOK | ✅ | ✅ 89fea7a + merge-gate fixes | ⏳ next | ⏳ next | ⏳ next |
| S2 visibility/authorizer | ✅ (worktree `agent-a719f9a8a9f298534`, 16 commits) | ⬜ after S5 gates | ⬜ | ⬜ | ⬜ |
| S3 goal intake→build | ⬜ Wave 2 (needs S1+S2) | | | | |
| S4 clone/remix | ⬜ Wave 2 (needs S2) | | | | |
| S6 admin/moderation | ⬜ Wave 2 | | | | |
| S7 cross-cutting | ⬜ W10 | | | | |

## Migration chain (single head required)

`… → 0030 (foundation) → 0031 (S1, IRREVERSIBLE) → 0032 (S1) → 0038 → 0039 → 0040 (S5, head)`

S2 carries `0033 → 0041 → 0042 → 0043 (NOT-NULL boundary) → 0044`; integrator re-points
`0033.down_revision → 0040` at merge. `make migrate` = phase-safe; boundaries need
`make migrate.phase` + `ALLOW_PHASE_MIGRATION=1` (one boundary per run).

## Carry-forwards (owed, not lost)

- PR-19 live no-KEK-with-credential boot check — verify at S5 Gate-C.
- Suspended-user 401-vs-403 contract — S7 contract pass.
- Ingest "Import from URL" button visible to non-admin (API refuses; UI polish) — S2/S6.
- `feature_byok_enabled` default OFF — flip decision belongs to W12 release planning.

## Standing process rules

- Gates A+B+C green before a stream advances (charter §5).
- Gate-C auth = scripted Playwright storageState (`--project=setup`), never interactive
  multi-account credential fills (post-mortem in ledger 2026-06-03; memory
  `aup-block-multi-account-logins`).
- Local-first: full backend+frontend suites + lint before any push; CI gates prod.
