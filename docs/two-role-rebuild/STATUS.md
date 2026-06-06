# Two-Role Rebuild — Status Board

> Compact, current-state view. History + decisions live in [CHARTER.md](CHARTER.md) §6 (ledger).
> Updated by the orchestrator as work lands. Last update: **2026-06-06** (post-W11).

## Where we are

**W11 closed** on branch `two-role-rebuild` — full local system test green (6 live journeys; 7 product
findings F1-F7 + 3 test-infra classes found AND fixed). Next: W12 merge→main → CI auto-deploy →
prod migrations/flags → prod live walk → W13 docs.

| Stream | Build | Merge | Gate A (Codex) | Gate B (Claude) | Gate C (live) |
|---|---|---|---|---|---|
| S7-pre foundation | ✅ | ✅ 913b978 | ✅ | ✅ | ✅ |
| S1 role collapse | ✅ | ✅ 506e1f5+acf390e | ✅ | ✅ | ✅ |
| S5 BYOK | ✅ | ✅ 89fea7a + fixes →2ca6d33 | ✅ (rounds 4→4→3→1→0) | ✅ | ✅ live-proven |
| S2 visibility/authorizer | ✅ | ✅ 8860c7e + fixes →121bad9 | ✅ (117→10→1→0) | ✅ | ✅ live-proven |
| S3 goal intake→build | ✅ wave2-s3-build | ✅ (in-tree) | ✅ (4→2→0; final 2 P1s adjudicated, pinned in 0052) | ✅ | ✅ live-proven incl. encrypted-brief privacy |
| S4 clone/remix | ✅ wave2-s4-build | ✅ (in-tree) | ✅ (5→3→2→2→0) | ✅ | ✅ live-proven incl. UI remix |
| S6 admin/moderation | ✅ wave2-s6-build | ✅ (in-tree) | ✅ (4→1→1 adjudicated) | ✅ | ✅ live-proven incl. UI approve |
| S7 cross-cutting | ✅ s7-cross-cutting | ✅ (in-tree) | ✅ (clean; confirm 1→1→0) | ✅ (1 P1 fixed) | ✅ live-proven (tombstone walk, 401 brake, admin gating) |

## Migration chain (single head required)

`… → 0030 → 0031 (S1, IRREVERSIBLE) → 0032 → 0038 → 0039 → 0040 (S5) → 0033 → 0041 → 0042
→ 0044 → 0045 → 0046 → 0047 → 0048 → 0049 → 0050 → 0051 → 0052 → 0043 (NOT-NULL boundary LAST, Phase D, head)`

Confirm-fix reorder: 0044 (Phase-A `courses.quarantined`, referenced by visibility SQL) now
precedes the deferrable 0043 boundary; 0045 adds the moderation_events timestamp defaults
0033 omitted. `make migrate` = phase-safe; boundaries need `make migrate.phase` +
`ALLOW_PHASE_MIGRATION=1` (one boundary per run). Dev DB re-stamped through the reorder.

## Carry-forwards (owed, not lost)

- ~~PR-19 live no-KEK-with-credential boot check~~ — CLOSED at S5 Gate-C (prod+empty-KEK+credential
  rows → boot-guard refusal, live-verified 2026-06-03).
- ~~Suspended-user 401-vs-403 contract~~ — CLOSED at S6.7. `authenticate`/`rotate_refresh` now return
  **401** with distinct codes (`auth.account_suspended` for `is_active=False AND deleted_at IS NULL`;
  `auth.account_deleted` for the tombstone), replacing the generic `auth.inactive`; the
  suspended/deleted disclosure happens ONLY after a correct password (no enumeration oracle). The
  **403** half of the contract is the cooperative-cancel signal `account.access_revoked` raised by
  `account.assert_account_active` at streaming heartbeats + build/clone fences (S6.8). Tests:
  `test_auth_suspended_codes.py`, `test_cooperative_cancel.py`.
- ~~Ingest "Import from URL" button visible to non-admin~~ — CLOSED at S7 (8e5abbe): gated to admins,
  matching can_ingest_url; admin-with-flag-off residual 403 accepted (server is the authority).
- `feature_byok_enabled` default OFF — flip decision belongs to W12 release planning. Prod flip
  REQUIRES setting `BYOK_MASTER_KEYS={"1":"<b64 32B>"}` in .env.production first (boot guard).
- ~~Streamed-turn `llm_calls` rows persist tokens=0~~ — CLOSED at S7 (c26379c + e61492d + b864d47):
  real usage persisted on success; yielded turn_failed routes to the failure path incl. BYOK credential
  invalidation; streaming quota stays COUNT-based (tripwire-pinned). Real-token live check = W12 prod walk.

## Standing process rules

- Gates A+B+C green before a stream advances (charter §5).
- Gate-C auth = scripted Playwright storageState (`--project=setup`), never interactive
  multi-account credential fills (post-mortem in ledger 2026-06-03; memory
  `aup-block-multi-account-logins`).
- Local-first: full backend+frontend suites + lint before any push; CI gates prod.
