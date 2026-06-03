# Design Resolutions (W2 design-critic remediation)

**Authoritative.** These resolutions supersede the design spec (`docs/superpowers/specs/2026-06-03-two-role-rebuild-design.md`)
and ADRs 0025–0030 on conflict. They close the design-critic findings (verdict: needs-work). The W3
implementation plan and W4+ build MUST read the ADRs + design spec **and** this file; on conflict, this wins.
All load-bearing critic claims were verified against source before resolving.

## Stale finding
- **DR-0 — "the 6 ADRs don't exist."** Resolved: ADRs 0025–0030 are now written to `docs/adr/`. The critic ran
  against the in-flight design string before extraction; the cross-ADR citations now resolve to real files.

## Unsatisfied requirements
- **DR-1 — FR-DEFINE-14 cancel + cleanup (was: only `build_failed` done).** Add all three: (a) `POST
  /me/courses/{id}/cancel-build` → marks an in-flight/abandoned build `build_failed` and flags for cleanup;
  (b) two Celery beat tasks — `sweep_orphaned_build_drafts` (soft-delete build drafts never opened by owner
  after 30d) and `sweep_unfinalized_briefs` (reap `learning_briefs` with `finalized_at IS NULL` after 30d);
  (c) `build_failed` state already designed. Lands in S3/S7.
- **DR-2 — R-G10 parent_message_id FK (was: dropped).** Verified absent (only a TODO comment at
  `services/learner_traces.py:39`). Add an additive nullable self-FK migration (>=0030) on the tutor
  message/trace row + best-effort backfill via the existing course-scoped window join. Lands in S7.
- **DR-3 — FR-VIS-04 leak-site inventory correction.** The authoritative `status==published` reader inventory
  to migrate to the central authorizer is the VERIFIED set: `services/enrollment.py:91`,
  `repositories/courses.py:47` & `:138`, `mcp/tools.py` search (`only_published=True`), `admin.py:375` & `:416`,
  `services/courses.py:432` (`can_view_course`). DROP the wrong cites `courses.py:313` (an `add(lesson)` line)
  and `tutor_streaming.py:150` (no status check — the streaming tutor's access decision is upstream in
  `api/v1/tutor.py`; migrate that). The CI grep-guard for `status == published` / `CourseStatus.published`
  reads is the backstop that catches any missed site — it is the source of truth, not the hand-list.
- **DR-4 — FR-DEFINE-04(a)/(c) constraint plumbing.** Specify: the finalized brief object (level,
  time_budget_hours, prior_knowledge, outcomes) is passed into `authoring_orchestrator.draft_course`; the
  outliner + critic prompt builders gain explicit constraint lines — difficulty from `brief.level` (replacing
  the hardcoded `Difficulty.beginner` at `authoring_orchestrator.py:1146`), module/lesson count estimate from
  `time_budget_hours` (FR-DEFINE-16), and the critic scores the outline against the budget. Change surface =
  the outliner/critic prompt builders in `authoring_orchestrator.py` + `authoring_subagents/`.

## Contradictions
- **DR-5 — FR-API-01 (types.ts).** `types.ts` is **hand-written**; do NOT `make api-client` to regenerate it
  (it would clobber the curated file). Strike the §4 "regenerate the TS client" line. Add a CI contract-drift
  check that diffs the committed `openapi.json` against a freshly generated one and fails on drift; the
  hand-written `types.ts` is updated in the same PR as the endpoint.
- **DR-6 — ORM cascade fix scope.** ONLY `User.courses_owned` (`all, delete-orphan` at `user.py:58`) vs
  `Course.owner_id` RESTRICT (`course.py:103`) is the real bug → change to `save-update`. `User.enrollments`
  / `User.reviews` are `ondelete="CASCADE"` (`course.py:209/257`) and never fire under anonymize-in-place;
  **leave them unchanged** (the design over-stated the scope).
- **DR-7 — boot-guard location (citation fixed + real extension point).** The API lifespan is at
  `main.py:261` calling `assert_production_safe(settings)` (imported `main.py:30`); there is NO
  `check_byok_master_key` and `:268` is mid-comment. Resolution: add `assert_byok_kek_present(settings)` to
  `core/prod_guards.py` and CALL it from `assert_production_safe`. For the worker: add a Celery
  `worker_process_init` (or `on_after_configure`) signal handler in `workers/celery_app.py` (genuinely absent
  today) that runs the same guard. Both API and worker refuse to boot in prod without a real KEK when
  credentials exist (R-S3).

## Unspecified seams
- **DR-8 — BYOK ctx threading.** Verified `get_provider()` is zero-arg (`llm.py:478`) and `replan_for_user`
  has no ctx (`learning_path.py:423`). Introduce `LLMContext` (carries `mode: platform|byok`, `credential_id`,
  `user_id`). Thread it end-to-end: `get_provider(ctx: LLMContext = PLATFORM)` builds the provider from the
  registry entry + decrypted key when `ctx.mode==byok`; add `ctx` param to `build_path`, `replan_for_user`,
  `_chat_with_retry` (`learning_path.py:743`), the tutor orchestrator, and authoring. Endpoints construct ctx
  from the caller; the streaming-tutor Celery task receives `credential_id` in task args and rebuilds ctx in
  the worker (never the raw key). Background beat passes `PLATFORM`.
- **DR-9 — clone asset copy mechanism.** Verified `media.py` has only `probe_asset`/`sweep_unclaimed_assets`.
  Use **download → re-validate (MIME-sniff + size) → re-upload** (NOT server-side S3 `CopyObject`, which never
  exposes bytes to re-sniff — R-S5 requires re-validating the copied bytes). New
  `workers/tasks/media.py::copy_clone_asset(src_key, dst_owner_id)` downloads, re-runs upload-time validation,
  re-uploads to the cloner's namespace, writes a new `Asset` row. Lazy (on the clone's first publish).
- **DR-10 — archived semantics.** `archived` keeps its visibility/moderation_state frozen and is never
  `is_publicly_listed` (predicate is `status==published` only). Unarchiving a course that was public →
  `moderation_state=pending_review` (re-review). Grandfathered enrollments on archived courses retain access
  via `can_view_course` (unchanged). State this in ADR-0026.
- **DR-11 — quota count-guard (concrete).** Add a pre-dispatch, DB-backed COUNT guard in the metered path:
  `COUNT(*) FROM llm_calls WHERE user_id=? AND created_at > now() - <window>` vs new settings
  `llm_user_request_quota_24h` (+ a short burst window `llm_user_request_quota_1h`). Independent of dollars;
  applies to ALL calls incl. BYOK `cost_usd=0`. Runs before provider dispatch in `call_logged`; over-limit →
  `status="rate_quota_exceeded"` row + `RateLimitError`. This is the real backstop (R-M7′).

## Migration safety
- **DR-12 — phased migrations are NOT a blind `upgrade head`.** The role data-collapse (0031) and the
  NOT-NULL-tightening migrations are **release-gated** and applied via explicit `alembic upgrade <rev>` steps
  in the deploy runbook, not one `make migrate` to head. Additive schema migrations (columns/tables) are safe
  on any deploy. **Topology note:** prod is a SINGLE-HOST docker-compose (one API + one worker), so the
  multi-pod read-skew concern reduces mostly to **JWT 15-min token drain**; still, sequence = additive
  migrations → deploy new image → confirm up → apply data-collapse → after token TTL, Release-3 narrow. The
  design's migration chain MUST annotate each revision with its release phase (A/B/C/D) and the runbook
  applies them per phase.
- **DR-13 — visibility flag-gate (named).** Add `Settings.feature_private_publish_enabled` (env-backed,
  default `false`). The central authorizer + new columns ship first (backfilled → behavior identical); the
  visibility-write endpoints are gated by this flag; flip to `true` only after the authorizer-bearing image is
  confirmed up (R-S8′ step 4). Use Settings env (deploy-gated), not the runtime_flags table.
- **DR-14 — embedding NOT-NULL backfill is operator-confirmed, not assumed.** Migration that backfills
  `embedding_model` uses the **operator-supplied currently-deployed** model value (a required migration
  parameter / env), NOT an assumption. If the deployed model is unconfirmed, the column STAYS nullable (do not
  force NOT NULL). Removes the circular self-healing argument (R-C3).
- **DR-15 — index builds are online + EXPLAIN-verified.** Build new indexes with `CREATE INDEX CONCURRENTLY`
  (Alembic op in autocommit/no-transaction block). Keep the old `ix_courses_acl` until an `EXPLAIN` on
  prod-scale data confirms the consolidated `ix_courses_listed` (incl. trailing `owner_id`) is used by the RAG
  ACL JOIN owner-branch (R-S12); only then drop the old index. No seq-scan regression under load.

## Security holes
- **DR-16 — count-guard closes the BYOK $0 bypass.** Same as DR-11; this is the enforced ceiling on
  per-request platform work (DB/embeddings) for BYOK users, independent of provider dollars.
- **DR-17 — lock the provider `api_base`.** Verified the provider constructor accepts `api_base` and sets
  `base_url` from it (`llm.py:197,202,211-212`). Resolution: the BYOK provider path
  (`build_provider_for_credential`) sets `base_url` **exclusively from the allowlisted registry entry** — user
  input never reaches `api_base`. Add an assertion that, for `mode==byok`, `api_base` is None/registry-fixed;
  the only caller permitted to pass a custom base is the platform/admin global config. SSRF/exfil vector
  (charter decision 5) structurally closed.
- **DR-18 — quarantine enforced in SQL, not just Python.** Add a `quarantined` boolean column on `courses`
  (set true by hard-removal csam/illegal; default false), so the SQL ACL clauses can enforce it without a
  `moderation_events` JOIN. Both `can_view_course` (Python) AND `publicly_listed_sql` /
  `retrieval_acl_clause` (SQL) gain `AND NOT quarantined` — including the RAG owner-branch (R-S12), so a
  quarantined owner's frozen-not-deleted course cannot leak via retrieval. Python + SQL now agree on the
  legally-sensitive case.
- **DR-19 — provenance anonymization is read-time, not one-time.** Render origin attribution at READ time:
  if `origin_owner` is marked deleted (or `origin_owner_id IS NULL`), display "a deleted user" regardless of
  whether the one-time snapshot scrub ran. This makes PII-erasure robust to migration ordering (0035 vs the
  deletion endpoint) — no silent GDPR gap if a deletion happened before the provenance columns landed. Also
  order: enable `DELETE /me` only after provenance columns (0035) exist.
- **DR-20 — report brigading: account-age gating.** Add reporter eligibility (email-verified AND account age
  ≥ threshold, e.g. 3 days) to file a report, plus a per-course report rate limit, on top of the ≤10/h
  per-user cap. Auto-action still never delists an approved course (R-S11).

---

# Round-2 Design Corrections (after Gate B re-review)

Gate B re-review (verdict: needs-work) caught three errors **in this resolutions doc**. Verified against
source; these corrections supersede the Round-1 entries above where they conflict.

- **DR-3-R2 — corrected leak-site inventory (DR-3 was factually wrong).** I propagated the in-workflow
  critic's error. Verified by grep: `api/v1/tutor_streaming.py:150` **DOES** gate on
  `Course.status == CourseStatus.published` (in the slug→id lookup) — do NOT drop it. The authoritative set of
  **access/discoverability READER sites** that must adopt the central authorizer is (13 sites / 8 files):
  `cli.py:351`, `repositories/courses.py:47`, `repositories/courses.py:139`, `api/v1/tutor_streaming.py:150`,
  `services/enrollment.py:91`, `api/v1/admin.py:375`, `api/v1/admin.py:416`,
  `services/authoring_subagents/researcher.py:246`, `services/authoring_subagents/researcher.py:290`,
  `services/learning_path.py:551`, `services/learning_path.py:613`, `services/learning_path.py:933`,
  `services/courses.py:432`, and **`api/v1/courses.py:313`** (free-preview gate, written as the **string
  form** `str(course.status) == "published"`). That string form is the 14th reader and is why the grep-guard
  pattern MUST match BOTH `status == CourseStatus.published` AND `str(...status...) == "published"`.
  The `status==published` occurrences at `services/courses.py:135,136,148,166` and
  `cli.py:184` are the **publish state-machine / seed writes**, NOT access reads — leave them and **allowlist
  them** in the grep-guard. **The CI grep-guard test (`test_no_raw_published_checks`) MUST be the FIRST commit
  of S2** (before any reader is migrated); it is the authoritative backstop, the hand-list is only a starting
  map.
- **DR-18-R2 — fully specify `courses.quarantined` (DR-18 had no migration/write-path/index).** Add column
  `quarantined: bool` (default `false`, NOT NULL) on `courses` via migration **0044** (additive, safe).
  **Write-path:** set `true` ONLY by the admin hard-removal moderation action for `reason ∈ {csam, illegal}`
  (NOT `severe_abuse`); cleared only by admin. **Single source of truth:** the `quarantined` column is
  authoritative for BOTH the Python `can_view_course` AND the SQL `publicly_listed_sql`/`retrieval_acl_clause`
  (owner-branch gains `AND NOT quarantined`). For **listing/visibility** authz `moderation_events` is
  audit-only — this **supersedes ADR-0026's** `moderation_events`-lookup-in-the-listing-authorizer design
  (which created two truth sources). **Scope clarification (Gate-B note):** `quarantined` is single-source-of-
  truth ONLY for the csam/illegal **full-quarantine** path. The separate **`severe_abuse`** tutor-disable
  signal (owner keeps view/edit) legitimately REMAINS a `can_learn_in_course`/`can_use_tutor` read of the
  latest `moderation_event.reason_code` per ADR-0026 — do not conflate the two. **Index:** add
  `quarantined = false` to the partial-index `WHERE` of `ix_courses_listed` and the RAG ACL index so the
  predicate stays index-covered on the hot path.
- **DR-6-R2 — cascade scope reconciled (DR-6 stands; ADR-0030/spec over-corrected).** DR-6 is correct: change
  ONLY `User.courses_owned` (`all, delete-orphan` → `save-update`) — it alone contradicts `Course.owner_id`
  RESTRICT (`course.py:103`). `User.enrollments`/`User.reviews` are `all, delete-orphan` over `CASCADE` FKs
  (`course.py:209/257`), internally consistent, and never fire under anonymize-in-place → **leave unchanged**.
  ADR-0030 D1 and design-spec §2.4 (which say "change all three") are an over-correction and are **superseded
  by DR-6/DR-6-R2** — the implementer changes exactly one relationship.
- **DR-21 — migration chain completeness.** The authoritative design-spec §2.5 chain (0030–0043) MUST be
  extended with the two mandated-but-missing migrations: **`parent_message_id` self-FK (DR-2) = 0045** and
  **`courses.quarantined` (DR-18-R2) = 0044**, both additive/zero-downtime.
- **DR-22 — naming canon (DESIGN-RESOLUTIONS wins).** Feature flag = `Settings.feature_private_publish_enabled`
  / env `FEATURE_PRIVATE_PUBLISH_ENABLED` (fix ADR-0026's `feature_private_publish`). BYOK provider builder =
  `byok.build_provider(spec, credential)` (fix DR-17's `build_provider_for_credential`). Clone asset task =
  `media.copy_clone_asset`. Spec §2.5 row 0037 dependency note is wrong: `learning_briefs` field-encryption
  uses `secrets_crypto` shipped in S7-pre and does NOT depend on the BYOK KEK migration (0038).

## Net-new scope added by design remediation (for W3 plan)
1. `cancel-build` endpoint + `sweep_orphaned_build_drafts` + `sweep_unfinalized_briefs` beat tasks (DR-1).
2. `parent_message_id` self-FK migration + backfill (DR-2).
3. `LLMContext` + ctx threading across tutor/authoring/learning-path/worker (DR-8).
4. `copy_clone_asset` download-revalidate-reupload worker task (DR-9).
5. Pre-dispatch DB COUNT quota guard in `call_logged` (DR-11/16).
6. `assert_byok_kek_present` in prod_guards + Celery `worker_process_init` guard (DR-7).
7. `courses.quarantined` column + SQL-ACL enforcement (DR-18).
8. Read-time provenance anonymization + reporter account-age gating (DR-19/20).
9. CI contract-drift check for openapi.json vs hand-written types.ts (DR-5).
