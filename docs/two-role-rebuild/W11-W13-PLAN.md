# W11–W13 execution plan (drafted during S7 build, 2026-06-06)

> Head-authored plan; gates/evidence land in CHARTER.md ledger as each step closes.

## W11 — full local system test (after S7 gates green)

**Real-LLM decision (made 2026-06-06):** the dev box has no Groq key (`LLM_PROVIDER=noop`);
prod has the real key. W11 therefore tests the complete MACHINERY with the noop provider
(deterministic shells, honest statuses, quotas, privacy); GENERATION QUALITY is verified on
prod during the W12 live walk (one real define→build→learn journey). Rationale: the noop
path exercises every seam the rewrite added (brief encryption, shell-first commits,
completion marker, poll endpoint, ACLs); model output quality is orthogonal and already
covered by the eval harness against the prod-configured model.

**Journeys (scripted Playwright storageState auth — NEVER interactive multi-account fills):**

1. **New user story** — signup (fresh user, not seeded) → define (6-turn intake → brief
   review → finalize) → build (noop shell; poll → completed) → learn (self-enroll, cert
   suppressed) → tutor turn on own course.
2. **Share story** — publish request → visibility stays unlisted → admin approves →
   publicly listed → anonymous catalog sees it → second user enrolls + learns.
3. **Remix story** — second user clones the listed course (idempotency replay check via
   double-submit) → edits their copy → learns it; origin attribution renders; source
   private→404 honored.
4. **BYOK story** — user stores a credential (validate fails honest w/ noop upstream —
   assert redaction), flag-gated UI visible only when `FEATURE_BYOK_ENABLED=true`
   (flip in dev .env for this journey, restore after).
5. **Moderation story** — report listed course → admin resolves (dismiss + actioned
   variants) → sticky moderation_state honored; suspend a user → 401 code on next login;
   delete account → tombstone renders as deleted-user everywhere S7-B fixed.
6. **Admin story** — users page toggle/grant-admin (last-admin invariant refusal),
   moderation queue tabs, platform stats.

**Pass bar:** every journey green in the browser + zero 5xx in API logs during the walk +
backend/frontend suites green at the same SHA + `make a11y` gate green.

## W12 — merge → deploy → prod verification

1. Pre-merge: rebase-check `two-role-rebuild` vs `main` (expect no drift — main frozen),
   final full suites, CHANGELOG truth-up, OpenAPI client regen check.
2. Merge to `main` (squash per house rules? NO — this branch is ~100 topical commits;
   merge commit preserves the ledger trail. Decide at merge: user gave full autonomy →
   merge commit, not squash, to keep stream archaeology).
3. CI green ⇒ auto-deploy (approval gate REMOVED 2026-05-28 — do not poll for waiting).
4. Prod migrations: `make migrate` applies Phase-A chain …0044→0052 automatically;
   the 0043 NOT-NULL boundary (Phase D) needs the explicit
   `ALLOW_PHASE_MIGRATION=1` one-boundary-per-run path — run it ONLY after the new
   image is serving and stable (it's deferrable by design).
5. Flag sequence on prod (.env.production): set `BYOK_MASTER_KEYS` (real 32B KEK)
   **before** `FEATURE_BYOK_ENABLED=true` (boot guard refuses otherwise);
   `FEATURE_PRIVATE_PUBLISH_ENABLED=true`; `CLONE_ENABLED=true`.
6. Prod live walk: scripted-persona spot version of journeys 1–3 + 5 (real Groq LLM —
   this is where generation quality is judged); zero-5xx check; rollback plan =
   re-deploy previous image tag (Phase-A migrations are additive/reversible; 0043
   boundary not yet crossed at first deploy).

## W13 — docs & maintenance truth-up

- CHANGELOG: user-visible two-role story (define/build/learn, share, clone, BYOK,
  moderation, account deletion).
- CLAUDE.md: roles line (`student | instructor | admin` → `user | admin`), seeded
  accounts table, new gotchas (0052 backfill invariant, shell-first build, phase-gated
  boundary workflow), commands if changed.
- README/docs: PRD + architecture deltas, ADR index (0026–0029), runbooks
  (rotate_byok_master_key already has one).
- Memory truth-up: session-handoff, active-redesign supersession check.
