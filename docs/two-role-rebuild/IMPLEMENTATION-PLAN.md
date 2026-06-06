# Two-Role Rebuild — Master Implementation Plan (W3)

Authoritative execution plan. Reads with the design canon (ADRs 0025-0030 + design spec + DESIGN-RESOLUTIONS).

All ground truth confirmed. I have the authoritative canon: DESIGN-RESOLUTIONS (R1+R2, with the linear migration chain reconciliation in DR-21/22), the design spec §2.5 (migration chain 0030–0043), §2.6 (Phase A/B/C/D rollout), §7 (build sequence S7-pre → S1 → S2 → S3/S5 → S4 → S6 → S7-post), §8 (cross-ADR resolutions), and the 7 stream plans. I have everything needed to synthesize the master plan. Writing it now as my entire final message.

---

# Lumen Two-Role Rebuild — MASTER EXECUTION PLAN (W3)

**Delivery-lead integration of the 7 work-stream plans into one ordered, dependency-aware, gate-checkpointed build.**

**Canon authority order (highest wins on conflict):** `docs/two-role-rebuild/DESIGN-RESOLUTIONS.md` (R1+R2) ▸ `docs/two-role-rebuild/REQUIREMENTS-RESOLUTIONS.md` ▸ design spec `docs/superpowers/specs/2026-06-03-two-role-rebuild-design.md` (§2.5 chain, §2.6 rollout, §7 build order, §8 cross-ADR) ▸ ADRs `docs/adr/0025–0030*.md` ▸ `CHARTER.md`. Per-ADR migration numbers are **superseded** by the single linear chain in §2.5+DR-21 (encoded in Part 2 below).

**Ground truth re-verified at synthesis (2026-06-03):**
- Migration head = **0029** (`down_revision="0028"`); new chain begins at 0030. New migrations begin at `down_revision="0029"` for the first one (0030).
- `RequireInstructor` real count = **26** (`courses.py`=16, `ai_authoring.py`=6, `content_ingest.py`=4) — confirmed by `grep -c`. Plan against 26, not ADR-0025's stale 24.
- None of `app/services/capabilities.py`, `app/services/visibility.py`, `app/services/byok.py`, `app/core/secrets_crypto.py` exist yet — all are net-new in this build.
- `can_view_course` leak confirmed at `app/services/courses.py:432` (`if course.status == CourseStatus.published: return True`).
- `app/models/user.py:36` role default = `Role.student`; collapse is app-enum + data UPDATE (String(20), **no `ALTER TYPE`**).
- `app/workers/celery_app.py` has `beat_schedule` but **no** `worker_process_init`/`on_after_configure` signal — the BYOK worker boot-guard handler is genuinely net-new (DR-7).

---

## PART 1 — GLOBAL BUILD ORDER & CONCURRENCY MAP

### 1.1 The eight-phase build spine (from design-spec §7, made executable)

```
S7-pre (foundation)  ─────────────────────────────────────────────────────►  unblocks ALL
   │
   ├─► S1 (role collapse)  ──┐
   │                          ├─► S3 (goal→build)  ──┐
   ├─► S2 (visibility)  ──────┤                       ├─► S4 (clone)  ──► S6 (admin/moderation)
   │      │                   └─► (S2 also feeds S6)  │
   │      └─────────────────────────────────────────►┘
   │
   └─► S5 (BYOK)  ────────────────────────────────────────────────────────►  (largely independent)
                                                                              │
                                                              S7-post (cross-cutting close) ◄─ all
```

### 1.2 Hard cross-stream dependencies (what must serialize, and why)

| Dependency | Direction | Reason (cite) | Enforcement |
|---|---|---|---|
| **S7-pre → everything** | S7-pre first | `capabilities.py`, `auth.capability`, `normalize_role`, redaction filter, `secrets_crypto.py` + KEK boot guard, ORM cascade fix (DR-6-R2: `User.courses_owned` `all,delete-orphan`→`save-update`, `user.py:55-59`), migration **0030** (`users.deleted_at`) — design-spec §7 step 1 | S7-pre lands & merges before any stream opens its capability/crypto/deletion calls |
| **S1 → S3, S6** | S1 before | `can_author` default-on, studio student-redirect removed, `RequireAuthor`; S6 builds grant/revoke on S1's `{user,admin}` enum (design-spec §7; CHARTER §4 "S1 precedes most") | 0031/0032 precede S3/S6 schema work in the chain |
| **S2 → S4 (CLONE)** | S2 before S4 | `can_clone(course,viewer) := is_publicly_listed(course)` + `visibility`/`moderation_state` columns (0033) — clone reads them; design-spec §8.4, DR-3-R2. **CHARTER §4 "S2 precedes S4"** | 0033 before 0035 in chain; S4 imports `visibility.is_publicly_listed` |
| **S2 → S3** | S2 before | S3 sets `visibility=private` on build (FR-DEFINE-11) + owner self-learn `can_learn_in_course`; private drafts excluded from RAG via `retrieval_acl_clause` (FR-DEFINE-18) | 0033 before 0037 |
| **S4 → S3 (`is_self`)** | S4 owns `Enrollment.is_self` (0035); S3 consumes | design-spec §7 step 4 "`Enrollment.is_self` (needs 0035)"; R-M8′ cert suppression shared seam | **S3's self-enroll task waits on 0035**; S4 ships `enroll_self` + `_maybe_issue_certificate` guard, S3 reuses |
| **S6 → S4 (provenance anonymize)** | read-time, soft | `delete_account` provenance-anonymize step (S4 columns) is **try-guarded** (DR-19 read-time) so S6 lands before S4 | narrow `try/except ProgrammingError/UndefinedTable` |
| **S5 → S5 worker FK** | 0038 before 0040 | `tutor_turn_jobs.credential_id` FK targets `user_llm_credentials` | chain order |
| **S2 grep-guard FIRST** | before any S2 reader migration | DR-3-R2 mandate: `test_no_raw_published_checks` is the **literal first commit of S2** | S2.1 lands green (allowlist + `READERS_PENDING_MIGRATION` block) before any of the 14 readers move |

### 1.3 What can run CONCURRENTLY (in git worktrees)

**Wave 0 (serial, blocking):** **S7-pre** alone. Everything downstream imports its artifacts; parallelizing it buys nothing and risks every stream rebasing crypto/capability signatures.

**Wave 1 (parallel after S7-pre merges):** **S1**, **S2**, **S5** in three worktrees.
- S1 ⟂ S2 ⟂ S5 share no files except the chain. S1 owns deps/RBAC; S2 owns visibility/authorizer; S5 owns BYOK. **Migration-number coordination is the only contact point** — pre-assign 0031/0032 (S1), 0033 (S2), 0038/0039/0040 (S5) per Part 2; each worktree temporarily chains off 0030 and re-points `down_revision` at integration if a sibling hasn't merged (every plan documents this fallback).
- **S2's grep-guard (S2.1) must be the first S2 commit** — it gates S2 internally, not the other waves.

**Wave 2 (after S1+S2 merge):** **S3** and **S6** in two worktrees, **concurrent with the tail of S5**.
- S3 needs S1 (`can_author`) + S2 (`visibility`, `can_learn_in_course`). S6 needs S1 (`{user,admin}` enum) + S2 (authorizer, `_transition_status`, `ModerationEvent`). They touch different files (S3: `learning_brief.*`, `goal_intake.py`, `authoring_orchestrator.py`; S6: `admin.py`, `account.py`, `moderation.py`) — safe in parallel.
- **S3's self-enroll task is the one S3 task that blocks on S4's 0035** — sequence it after S4's 0035 lands, OR S3 stubs `is_self` locally and rewires. Treat 0035 as a small early-S4 deliverable to unblock S3.

**Wave 3 (after S2 + S3's `is_self` consumer):** **S4** (clone). Depends on S2 authorizer + the shared `is_self`/`enroll_self`/cert-suppression seam (S4 owns it, S3 consumes). S4 can start its 0035 migration + projection (pure, no deps) early in Wave 2 to unblock S3, then complete the clone service in Wave 3.

**Wave 4 (terminal, serial):** **S6's `delete_account` choreography** completes after S4/S5 tables exist (try-guards go live no-redeploy), then **S7-post** (contract-drift CI, eval gate, 0045 `parent_message_id`, full i18n/a11y, runbook, OpenAPI regen, ADR/CHANGELOG finalize, the consolidated chain-integrity guard). S7-post is **last by definition** — its terminal audits require every surface to exist.

**Concretely parallelizable worktrees:**
- `wt/s1-role`, `wt/s2-visibility`, `wt/s5-byok` (Wave 1)
- `wt/s3-goal-build`, `wt/s6-admin` (Wave 2), `wt/s4-clone` (0035+projection early, clone service Wave 3)

**Forced serialization points (cannot parallelize):** S7-pre→all; S2.1 grep-guard→S2 readers; 0033→0035; 0035→S3 self-enroll; all-streams→S7-post terminal audits; **Phase B (0031 irreversible backfill) is a deploy-time serialization, not a build-time one** (see Part 5).

---

## PART 2 — CONSOLIDATED ORDERED ALEMBIC MIGRATION SEQUENCE (0030–0045)

One linear chain. Each `down_revision` = the immediately prior rev. Phase tags per DR-12 / design-spec §2.6 (**A** = additive, safe any deploy; **B** = irreversible data-collapse, release-gated; **C** = metadata flip + narrowed-enum release; **D** = evidence-gated NOT-NULL tighten). **Never a blind `alembic upgrade head`** — each phase group is applied by an explicit runbook step (Part 5).

| Rev | Name | Stream | Phase | Kind | Deploy/runbook step that applies it |
|---|---|---|---|---|---|
| **0030** | `account_lifecycle_users_deleted_at` | S7-pre | **A** | add `users.deleted_at` nullable + partial idx CONCURRENTLY; backfill legacy `deleted-%@lumen.invalid` rows → `deleted_at=updated_at` | Phase A: `alembic upgrade 0030` with the foundation release; confirm API+worker boot |
| **0031** | `role_collapse_backfill` | S1 | **B** | data: `UPDATE users SET role='user' WHERE role IN ('student','instructor')` | **Phase B explicit step:** `alembic upgrade 0031` **only while fleet is in Phase A** (accepts all 4 role values); idempotent, logs rowcount. **IRREVERSIBLE — no-op downgrade (R-C4)** |
| **0032** | `role_default_user` | S1 | **C** | `ALTER COLUMN users.role SET DEFAULT 'user'` (metadata; String(20), no enum DDL) | Phase C: `alembic upgrade 0032` with the narrowed-enum + normalization release |
| **0033** | `course_visibility_moderation` | S2 | **A** | add `visibility`/`moderation_state` (nullable→batched backfill→default→NOT NULL); create `moderation_events`; synthetic `approved` events; `ix_courses_listed (visibility,moderation_state,status,subject_id,owner_id) WHERE deleted_at IS NULL` CONCURRENTLY; backfill live-published→`(public,approved)` else `(private,none)` | Phase A: `alembic upgrade 0033` with the authorizer release, **`FEATURE_PRIVATE_PUBLISH_ENABLED=false`**; verify catalog unchanged |
| **0034** | `course_reports` | S6 | **A** | create `course_reports` + partial-unique `(course_id,reporter_id) WHERE status='open'` + idx | Phase A: `alembic upgrade 0034` |
| **0035** | `clone_provenance` | S4 | **A** | add 6 provenance cols (nullable, FK SET NULL) + `enrollments.is_self` (server_default false) + `ix_courses_origin*` CONCURRENTLY | Phase A: `alembic upgrade 0035` (**lands early to unblock S3 self-enroll**) |
| **0036** | `idempotency_keys` | S4 | **A** | create `idempotency_keys` + unique `(user_id, idempotency_key)` | Phase A: `alembic upgrade 0036` |
| **0037** | `learning_briefs` | S3 | **A** | create `learning_briefs` (field-encrypted `source_goal_enc`) + Personal subject seed (idempotent `ON CONFLICT`) | Phase A: `alembic upgrade 0037`; encryption uses `secrets_crypto` (DR-22, **independent of BYOK KEK 0038**) |
| **0038** | `byok_credentials` | S5 | **A** | create `user_llm_credentials` + 2 partial-uniques + idx | Phase A: `alembic upgrade 0038`; **BYOK code flag-gated OFF** (`feature_byok_enabled=false`) until KEK confirmed fleet-wide |
| **0039** | `llm_calls_billing_mode` | S5 | **A** | add `llm_calls.billing_mode` (PG17 fast-default `'platform'`) | Phase A: `alembic upgrade 0039`; old fleet INSERTs default correctly |
| **0040** | `tutor_turn_credential_id` | S5 | **A** | add `tutor_turn_jobs.credential_id` nullable + FK→user_llm_credentials SET NULL | Phase A: `alembic upgrade 0040` (after 0038 — FK target) |
| **0041** | `lesson_chunks_embedding_model` | S2/RAG | **A** | add `embedding_model`,`embedding_dim` nullable; batched backfill to **operator-confirmed** deployed model + dim (DR-14, never assumed) | Phase A: `alembic upgrade 0041`; operator passes deployed `EMBEDDING_PROVIDER` as migration param |
| **0042** | `lesson_chunks_live_index` | RAG | **A** | `ix_lessons_module_id_live (module_id) WHERE deleted_at IS NULL` CONCURRENTLY | Phase A: `alembic upgrade 0042` |
| **0043** | `lesson_chunks_model_not_null` | RAG | **D** | `ALTER COLUMN embedding_model/dim SET NOT NULL` | **Phase D gated step:** `alembic upgrade 0043` only after the always-stamps-model ingest image is fleet-wide AND 0041 drained (R-S8′ discipline) |
| **0044** | `courses_quarantined` | S2/S6 | **A** | add `courses.quarantined` BOOLEAN NOT NULL DEFAULT false (instant on PG17); rebuild `ix_courses_listed` with `quarantined=false` in partial WHERE (CONCURRENTLY) | Phase A: `alembic upgrade 0044` (DR-18-R2) |
| **0045** | `agent_traces_parent_message_id` | S7-post | **A** | add `agent_traces.parent_message_id` nullable + FK→tutor_messages SET NULL + idx CONCURRENTLY + best-effort batched backfill via the 120s window join | Phase A: `alembic upgrade 0045` (DR-2/DR-21) |

**Forced ordering rationale (design-spec §2.5 "Why this order is forced"):** 0030 first so deletion try-guards activate as later tables land; 0031/0032 run inside Phase A acceptance window; **0033 before 0035** (clone reads visibility) and **before 0041** (ACL JOIN references visibility columns); 0038 before 0039/0040 (FK target); 0041→0043 nullable→backfill→NOT-NULL drain discipline; 0044/0045 additive tail.

**Chain-integrity guard (S7-post, `test_migration_chain.py`):** asserts head==0045, linear `down_revision` chain with no collisions, **0031 is the only irreversible migration**. This is the merge-time backstop against the historical hazard where ADR-0026/0027/0028/0030 all claimed 0030 and ADR-0028 had a bogus `down_revision="0029_visibility"`.

**Rollback playbook:** image-rollback to the last release accepting the wider sets; **never `alembic downgrade` past 0031**; `moderation_events` is never dropped even on a 0033 downgrade (R-C2); `course_reports`/`moderation_events` audit survives column rollback.

---

## PART 3 — GATE CHECKPOINTS

**Every stream's gate = (1) unit/integration green + (2) Codex review (Gate A) + (3) Claude reviewer (Gate B) + (4) LIVE browser walkthrough as the relevant persona, local (Gate C).** Then a **system-level gate** before deploy. Per the post-deploy-visual-coverage memory, Gate C **must** sign in as student/instructor→user, authoring-user, learning-user, and admin and capture every auth-gated surface — public-only captures do not gate `/studio`, `/admin/*`, `/dashboard/*`.

### Per-stream gate + exactly what to LIVE-test

**S7-pre gate** — Unit: `secrets_crypto` round-trip + tamper + KEK-version; `capabilities.py` predicates; `normalize_role` legacy→user; redaction-filter sentinel across sinks; cascade-introspection (`courses_owned` is `save-update`, no `delete-orphan`); 0030 up/down clean. Live: `make up`; confirm API **and** worker boot with the KEK boot guard (DR-7 — both `assert_production_safe` and the new Celery `worker_process_init` handler); sign in as each seeded account and confirm no regression (foundation is invisible to users). *Codex/Claude focus: the crypto module + boot guard + cascade fix are the load-bearing security primitives.*

**S1 gate** — Unit: `test_capabilities`, `test_deps_capabilities`, user-role-can-author across courses/ai_authoring, `test_suspended_user_cannot_create_course`, MCP user-can-author + ingest-closed + legacy-instructor, `test_content_ingest` closed-for-all (FR-SEC-02), `test_jwt_role_inert` (FR-MIG-04), `test_migration_role_collapse` (0031 idempotent + no-op down, 0032 default), `test_admin_stats` admins/authors, `test_set_user_role_rejects_legacy`; frontend `Role` union `"user"|"admin"`, studio/command-palette/site-header gates inverted; no test asserts removed `courses.forbidden`/`mcp.role.instructor_required`. **Live (3 personas):** (1) sign in as a **regular user** (former `student@lumen.test`, now `role=user`) → `/studio` renders (no redirect), create a course via UI → 201, command palette shows "Studio", `/dashboard` shows merged author CTA; (2) same user → content-ingest blocked (403 capability); (3) **admin** → `/admin/users` role `<Select>` offers only User/Admin, `/admin` stats shows admins/authors (no `undefined`); (4) second user **cannot** edit the first user's course (ownership preserved); (5) stale/`instructor`-claim session grants no admin power (FR-MIG-04 manifested).

**S2 gate** — Unit: `test_no_raw_published_checks` green **AND `READERS_PENDING_MIGRATION` empty**; `test_migration_0033_visibility`, `test_quarantine` (0044), `test_visibility_authorizer` (Python≡SQL parity), `test_moderation_state_machine` (every transition row), `test_publish_share_endpoints` (flag-gated), `test_rag_acl_visibility` (no cross-user private leak), `test_catalog_visibility`. **Live (user + admin + 2nd user):** (1) user builds/owns a course → `/publish` via Studio lifecycle control → confirm absent from `/catalog` (private+published); toggle Share (flag ON) → "Pending review", still absent; verify with flag OFF that Share is unavailable (R-S8′ step-4 gate); (2) **admin** → `/admin/moderation` approve → course now in `/catalog`, search, sitemap, RAG-citable; (3) **2nd user** → first user's private course invisible in catalog/search + 404 on direct URL (existence-hide), cross-course tutor never surfaces it; (4) **admin** hard-remove `csam`/`illegal` → vanishes even for a previously-enrolled learner (full quarantine R-C6′); hard-remove `severe_abuse` → owner keeps view/edit, tutor disabled. **Rollout proof:** runbook entry showing the R-S8′ 4-step with an asserted invariant that no non-default visibility is writable before step 4.

**S3 gate** — Unit: brief field-encrypts goal, never leaks in repr/serialization (FR-PRIV-01); 6-turn cap + per-user session quota (R-M10); finalize immutable (FR-DEFINE-03); `draft_course` derives difficulty from `brief.level` (no `Difficulty.beginner` hardcode at `authoring_orchestrator.py:1146`), outcomes from brief, module/lesson estimate from `time_budget_hours`, outliner/critic prompts carry constraints (DR-4); subject auto-resolves to Personal (no `subject_not_found`); built course `visibility=private,status=draft`; `build_failed` + re-runnable + idempotent; `cancel-build` (DR-1a); owner self-learn + `is_self` cert suppression (R-M8′); two beat sweeps idempotent (DR-1b); private drafts excluded from research/catalog/search (FR-DEFINE-18); 401 anon / 403 suspended on every define/build endpoint; en/ar parity + axe AA. **Live (authoring/learning user):** `/dashboard` → "Create a course to learn" → fuzzy goal → multi-turn clarification (hit turn cap deliberately) → review/tweak brief → confirm → watch trace timeline (researcher→outliner→critic→reviser→drafter→final-critic) → land on private course, study it, tutor answers, complete → **no certificate** (self-enroll); trigger a build failure → clean `build_failed` (no half-course, normalized error) → re-run recovers; cancel an in-flight build → flips to `build_failed`; confirm the private draft is invisible to a 2nd anonymous/user.

**S4 gate** — Unit: projection whitelist field-set tripwire, empty-module drop, soft-delete exclusion, `is_preview=false`, dense 0-based orders, quiz verbatim deepcopy, size ceiling; `enroll_self` bypass + cert suppression; clone create/403/404/401/idempotency/audit/rollback; quotas (429/409/413/disabled-flag); read-time anonymization + `origin_available` (DR-19); asset download→revalidate→reupload (DR-9, **not CopyObject**) + best-effort + cooperative-cancel + orphan sweep; zero-chunk + publish-schedules-index isolation; `extra="forbid"` immutability; **S2 grep-guard still green** (clone reads `is_publicly_listed`, never `status==published`); 0035/0036 up/down clean. **Live (2 users, en+ar/RTL):** user A publishes a course (quiz + cover + image lesson) to public; user B sees "Make my own copy" on the card → clicks → lands in `/studio/draft/{newId}` with modules/quiz, fresh title, `visibility=private/status=draft`, "Based on … by …" attribution + working link; media resolves to the **cloner's** namespace (re-homed `Asset` rows owned by cloner); edit clone → source unchanged; tutor returns `tutor.index_pending` until publish; self-enroll mints **no** certificate; admin delists source → attribution reads "no longer available", no link, content intact; anonymous CTA → sign-in with return path.

**S5 gate** — Unit: `repr(provider)` redaction; sentinel absent across **every enumerated sink** (structlog, exception envelope, `llm_calls`, agent_traces, Celery payload carries `credential_id` not key bytes, admin views, `/openapi.json`, `/me/export`); BYOK streamed turn records `billing_mode=byok` + user's model; validate oracle caps trip (R-S4); pre-dispatch DB COUNT quota trips on a $0 BYOK model (DR-16) + persists sentinel row + provider never hit; drift → platform + `needs_attention` (R-M11′); boot guard fires on **both** API and worker when a credential exists without a real KEK (R-S3); `decrypt_secret` called **only** inside `build_provider`; 0038/0039/0040 up/down clean. **Live (user + admin):** `/profile` model tab → pick provider → model list populates from `/llm-providers` → enter dev key → Validate → **redacted** status badge → toggle Enabled + "Use for my requests"; run an interactive tutor turn (+ streaming if flag on) → admin `/admin/llm-calls` shows `billing_mode=byok` + user's model, platform-$ excludes them; delete key → next turn falls back to platform; confirm **no key** in UI/network tab/`/me/export`/`/openapi.json`; confirm **no `api_base`/URL field** anywhere.

**S6 gate** — Unit: cascade introspection (DR-6-R2); moderation transitions (approve/reject/delist/relist/remove) write `ModerationEvent`+`AuditEvent`, `quarantined` for csam/illegal only; `course_reports` account-age gating (DR-20) + coalescing + per-course rate limit; atomic report-resolve single-audit; last-admin invariant (422 `user.last_admin`/`user.last_admin_active`); suspend/reinstate distinct codes (`auth.account_suspended` vs `auth.account_deleted`); `delete_account` choreography + try-guard tolerance + cooperative cancellation (`account.access_revoked`); `authors` stat; deleted-user read-time rendering; **admin-cannot-edit-others-course** regression (FR-MOD-05); no N+1 on queue/reports; **S2 grep-guard stays green**. **Live (admin + user + target-user):** **admin** drives `/admin/users` (grant/revoke toggle, last-admin 422 surfaced, own-row controls disabled, suspend/reinstate), `/admin/moderation` (queue approve/reject/delist/relist/remove with confirm-on-remove, report resolve), `/admin/courses` badges; **user** files a report on a public course; **target user** deletes account from `/profile` → sign-out + anonymize verified; en+ar(RTL)+keyboard/a11y on new controls; end-to-end: suspend a user mid-stream → in-flight tutor stream closes with `account.access_revoked`; delete an owner → their public course leaves catalog while another user's enrollment survives.

**S7-post gate** — Unit: `test_openapi_snapshot`, `test_learner_traces_parent_message` (0045 FK exact-path + temporal fallback), `test_eval_fixture_gate` (ε=0.30, inconclusive-on-outage R-U6), `test_migration_chain` (head=0045, linear, only 0031 irreversible), `test_migration_phase_annotations` (every ≥0030 rev declares Phase A/B/C/D), `test_adr_consistency`; frontend `i18n-parity` + `api-role-contract` + `changelog-shape`; `pnpm typecheck`; CI `contract-drift` + `eval-gate` steps; axe WCAG 2.2 AA across **every** net-new surface + Arabic/RTL pass. **Live (all personas + locale toggle):** walk author+learn under one `user` (`/studio`, define→build, `/dashboard`, clone CTA, BYOK settings), admin moderation under `/admin/*`, toggle Arabic and confirm RTL on home + one auth surface (logical-property spacing, no clipping); confirm a fresh post-0045 turn's trace timeline resolves via the exact `parent_message_id` FK (no temporal false-positives); `/eval` public page still renders.

### System-level gate (before deploy — W11/W12, design-spec Gate C + CHARTER §5)

1. **Full backend suite green** (`make test.api`, xdist `-n 4`, ~3 min local / ~12 min CI) + `make test.web` + eslint + `tsc --noEmit` + `make lint`.
2. **`test_no_raw_published_checks` green with `READERS_PENDING_MIGRATION == set()`** — the visibility leak is structurally shut (DR-3-R2 backstop).
3. **Migration chain integrity** — `alembic upgrade head` reaches 0045 on a fresh DB; `alembic downgrade -1` reverses 0045; chain test confirms only 0031 irreversible; phase-annotation test green.
4. **OpenAPI ↔ hand-written `types.ts` drift check passes** (DR-5 — never `make api-client`; diff `openapi.json` only).
5. **Security proofs (the load-bearing ADR-0027/0030 ones)**: BYOK sentinel absent across every sink + boot guard on API+worker; brief goal never leaks; `delete_account` irreversibly scrubs PII; redaction filter covers worker sinks.
6. **End-to-end user journeys (live browser, local then prod):** define→build→learn (private, no cert) ▸ publish→moderate→appears-in-catalog ▸ clone→remix→independent ▸ BYOK→tutor-uses-my-model ▸ admin moderation + suspend + account-delete ▸ all under both `en` and `ar`/RTL with axe AA clean.
7. **eval CI gate** reports pass on seeded fixtures (deterministic, ε=0.30, no live Groq).
8. **Cooperative-cancellation E2E:** suspend-mid-stream closes the stream; delete-owner delists their public course while preserving another user's enrollment.

---

## PART 4 — FULL TASK LIST, GROUPED BY STREAM, IN GLOBAL EXECUTION ORDER

Each task keeps its TDD steps + files + acceptance from the stream plans (condensed; the stream plans are the per-task source of truth). **Wave** column = concurrency assignment from Part 1.

---

### WAVE 0 — S7-pre (foundation; serial, blocks all)

> Owned across S1/S5/S6/S7 plans but **must merge first**. The integrator lands these as one foundation release before opening Wave 1 worktrees.

- **S7pre.1 — `app/core/secrets_crypto.py`** (from S5.1): AES-256-GCM envelope (DEK wrapped by versioned KEK) + `key_fingerprint`/`last4` + `rotate_secret` + dev-derived-KEK fallback + `reset_for_tests`. KEK Settings in `config.py`. TDD: `test_secrets_crypto.py` (round-trip, tamper→`InvalidTag`, multi-version decrypt, derived-KEK only when `ENV!=production`). **Acceptance:** encrypt→decrypt identical; no plaintext in repr/log; rotation re-wraps `enc_data_key` only.
- **S7pre.2 — `app/services/capabilities.py`** (from S1.2): pure predicates `can_author/can_clone/can_use_byok/can_publish_public/can_view_course_analytics/can_use_mcp_authoring/can_ingest_url` over `(User, Settings)`; `ingest_url_enabled=False`, `mcp_authoring_enabled=True` flags. **Acceptance:** suspended→all False; `can_ingest_url` admin+flag-only; no per-user override table (R-CAP).
- **S7pre.3 — `app/api/deps.py` capability deps** (from S1.3): `RequireAuthor`, `RequireIngestUrl`, `RequireCapability(fn)` factory; `auth.capability` error code (`details.capability`); 401 anon / 403 suspended. `require_role`/`RequireAdmin` unchanged.
- **S7pre.4 — `normalize_role` display helper** (from S1.9) in `security.py`: legacy/unknown→`Role.user`, `admin→admin`. Authz already re-reads DB (`deps.py:48,68`) — test documents the inert-claim invariant.
- **S7pre.5 — Value-level redaction filter + sentinel contract** (from S5.10): last-stage structlog processor (after `_redact`) + exception/envelope scrub; `install_value_redaction` exported for worker reuse. TDD: `test_byok_sink_redaction.py` enumerated-sink contract (deferred-completeness — sinks that don't exist yet are stubbed).
- **S7pre.6 — KEK boot guard** (from S5.11, DR-7): `assert_byok_kek_present(settings)` called from `assert_production_safe` **and** unconditionally-when-credentials-exist; new Celery `@worker_process_init.connect` handler in `celery_app.py` runs the guard + installs worker redaction sinks. **Extend the guard to also fire when any `learning_briefs` row exists** (design-spec §9 gap 4 — brief encryption implies a real KEK).
- **S7pre.7 — ORM cascade fix (DR-6-R2)** (from S6.0): `User.courses_owned` `all,delete-orphan`→`save-update` (the **one** load-bearing change, `user.py:55-59`); align `enrollments`/`reviews` per DR-6-R2; **keep `refresh_tokens` unchanged**. TDD: `test_account_cascade_invariant.py` introspects `__mapper__.relationships`.
- **S7pre.8 — Migration 0030** `account_lifecycle_users_deleted_at` (Phase A): `users.deleted_at` nullable + partial idx CONCURRENTLY + idempotent legacy backfill. Up/down clean.

---

### WAVE 1a — S1: Role collapse & capability RBAC (worktree `wt/s1-role`)

- **S1.1** Widen `Role` enum to `{student,instructor,user,admin}` (Phase A tolerance). TDD `test_role_enum.py`. No migration.
- **S1.4** Swap the **22** author/owner routes → `RequireAuthor` (`courses.py` 16 + `ai_authoring.py` 6). TDD: `test_user_role_can_create_course`, `..._can_call_ai_outline`, `test_suspended_user_cannot_create_course` (403 `auth.capability`). Keep course-analytics route's service re-check (S1.5).
- **S1.5** `create_course` ungate + service ownership/analytics re-checks (`services/courses.py:69` block deleted; `_owned_course` kept; `cap.can_view_course_analytics`). Remove now-unreachable `courses.forbidden`.
- **S1.6** MCP principal/enforcement reconcile (`principal.py` `can_author`, keep deprecated `is_instructor`; `server.py:_enforce_auth` instructor-branch→`can_author`, code `mcp.writes.author_required`; `tools.py:_require_instructor`→`_require_author`; `create_course_draft` ToolSpec `"instructor"→"user"`; `ingest_url_to_draft` stays admin-only). TDD: user-principal-can-author, legacy-instructor-still-authors, user-cannot-ingest-url, suspended-cannot-author.
- **S1.7** `content_ingest.py` 4 routes → `RequireIngestUrl` (stays closed, DR-M12). TDD: closed-for-user, closed-for-admin-flag-off, allowed-admin-flag-on. **Load-bearing Gate-A correction: ingest is NOT globally opened.**
- **S1.8** Role defaults → `user` (`auth.py:58`, `users.py:26`, `cli.py:151-152`, `seeds/demo.py`, `run_baseline.py:159`, `user.py:36`); `platform_stats` `instructors`→`admins`+`authors`; `set_user_role` restrict to `{user,admin}` (422 legacy). **Ships with the TS client/admin-dashboard stat change in the same PR** (OpenAPI-visible).
- **S1.9** JWT inert-claim test (`test_jwt_role_inert.py`, FR-MIG-04) + `normalize_role` display use (helper from S7pre.4).
- **S1.10** **Migration 0031** (data collapse, **IRREVERSIBLE**, Phase B) + **0032** (default flip, Phase C). TDD `test_migration_role_collapse.py` (0031 idempotent + no-op down, 0032 default). `down_revision`: 0031→0030, 0032→0031.
- **S1.11** Frontend `Role` union `"user"|"admin"` + author-gate inversions (`studio/*`, `dashboard`, `command-palette`, `site-header.tsx:86,98`) + `admin/users` union/Select + merged onboarding + `useCapabilities` helper. **Do NOT `make api-client`** (DR-5). Vitest: `studio-access`, `command-palette`, `admin-users`.
- **S1.12** Test fixtures + e2e/a11y persona shim (`conftest.py` `make_user`/`auth_headers` default→`user`; Playwright `student@`/`teacher@`→`user` shim; keep one explicit `instructor` override for the S1.6 legacy test).
- **S1.13** **Release-3 cleanup (Phase D, evidence-gated)** — narrow enum to `{user,admin}`, remove `is_instructor_or_admin`, drop deprecated `Principal.is_instructor`, remove `mcp.role.instructor_required` branch; CI grep-guard `test_no_legacy_role_refs.py`. **Merges only after the live positive-evidence gate passes in prod (Phase D).**

### WAVE 1b — S2: Visibility, moderation & central authorizer (worktree `wt/s2-visibility`)

- **S2.1** **FIRST COMMIT** — CI grep-guard `test_no_raw_published_checks.py` (DR-3-R2): matches `status == CourseStatus.published`, string form `str(...status...)=="published"`, dead `IN (none, approved)`; marker-comment allowlist for state-machine writes + seeds; `READERS_PENDING_MIGRATION` block lists the 14 readers, emptied as each migrates. Green at every commit.
- **S2.2** **Migration 0033** (Phase A) `course_visibility_moderation` (additive→batched backfill→NOT NULL; `moderation_events`; `ix_courses_listed`; CONCURRENTLY; never drop `moderation_events` on down). Model enums `Visibility`/`ModerationState` + `ModerationEvent`. TDD `test_migration_0033_visibility.py`.
- **S2.3** Central authorizer `app/services/visibility.py` — `is_publicly_listed` (R-C1′ `==approved`), `publicly_listed_sql`, `can_view_course`, `can_learn_in_course`, `can_enroll`, `can_clone(course,viewer)`, `can_publish_public`, `retrieval_acl_clause` (owner-branch defensively guards `build_failed` via getattr until S3). TDD `test_visibility_authorizer.py` (Python≡SQL parity).
- **S2.4** Migrate `can_view_course` (`courses.py:432`→re-export) + free-preview reader (`courses.py:313` string-form). Drop 2 from pending.
- **S2.5** Catalog/repo readers (`repositories/courses.py:47/:139` rename `only_published`→`publicly_listed_only`; `/mine` keeps `False`; MCP `tools.py:323`). Drop from pending.
- **S2.6** Enrollment + streaming-tutor + CLI readers (`enrollment.py:91`→`can_enroll`; `tutor_streaming.py:150`→`can_view_course`; `cli.py:351`). Drop from pending.
- **S2.7** RAG/authoring cross-course readers (`learning_path.py:551/613/933`, `researcher.py:246/290`)→`retrieval_acl_clause(user_id)`; thread `user_id` (fallback→`None`→`publicly_listed_sql` only). **Pending block now empty.**
- **S2.8** Admin published-count readers + narrow `_can_edit_course` (admin.py:375/416 are **lifecycle** counts → allowlist with marker, not migrate; add `courses_listed` stat; `_can_edit_course`→owner-only). TDD `test_admin_cannot_edit_others_course` (coordinates with S6.5).
- **S2.9** Lifecycle + moderation service fns (`_transition_status` force-private side-effects; owner `share/unshare/resubmit`; **S2 ships owner-intent fns, S6 owns admin-authority `approve/reject/delist/relist/remove`** — see Part 1 seam note) + `moderation_safety.py` advisory classifier (**fail-closed to `pending_review`, never auto-approves**, R-C1′) + cache-version bump + best-effort reindex.
- **S2.10** **Migration 0044** (Phase A) `courses.quarantined` + SQL+Python enforcement (DR-18-R2: single source of truth for csam/illegal; `severe_abuse` stays a `moderation_event.reason_code` read). TDD `test_quarantine.py`.
- **S2.11** Feature flag `feature_private_publish_enabled` (DR-13/DR-22) + endpoints `POST /courses/{id}/publish|unpublish|share|unshare|resubmit` (**remove `status` from PATCH**) + admin moderation endpoints + schemas (read-only `visibility`/`moderation_state`, non-owner redaction FR-VIS-21). Hand-edit `types.ts` (DR-5).
- **S2.12** Frontend two-control Studio + `/admin/moderation` page + i18n + sitemap (listed-only) + detail ETag (incl. visibility/moderation) + **assert `READERS_PENDING_MIGRATION` empty**.
- **S2/RAG.41-43** **Migrations 0041 (Phase A), 0042 (Phase A), 0043 (Phase D)** — lesson-chunk `embedding_model`/`embedding_dim` nullable→backfill(operator-confirmed, DR-14)→NOT-NULL-gated + live index. (RAG ACL prerequisite; design-spec §7 step 3.)

### WAVE 1c — S5: BYOK & model config (worktree `wt/s5-byok`)

- **S5.2** Allowlisted provider registry `llm_providers.py` (frozen, fixed base URLs, curated models, groq present) + `GET /llm-providers` (no base_url/keys). TDD `test_llm_providers_registry.py`.
- **S5.3** **Migration 0038** (Phase A) `user_llm_credentials` (envelope cols, partial-uniques, soft-delete; **no plaintext/api_base column**). TDD `test_user_llm_credential_model.py`.
- **S5.4** **Migration 0039** (Phase A) `llm_calls.billing_mode` + `quota_exceeded` status.
- **S5.5** **Migration 0040** (Phase A) `tutor_turn_jobs.credential_id` (FK SET NULL).
- **S5.6** Provider key `SecretStr` wrap + redacting `__repr__`/`__str__` + `build_provider_from_spec` (no `api_base` param — DR-17). TDD `test_provider_key_redaction.py`. Keep `get_provider()` zero-arg.
- **S5.7** `LLMContext` + `byok.build_provider` + `resolve_context` (**the only decrypt site**) + repo + `capabilities.can_use_byok`. TDD `test_byok_resolve.py` (decrypt-locus spy, drift→platform+`needs_attention` R-M11′, background→platform R-S1″).
- **S5.8** Pre-dispatch DB COUNT quota in `call_logged` (DR-11/16) + streaming reservation + Redis concurrency lease (fail-open). TDD `test_llm_quota_guard.py` (**BYOK $0 model still counts** — core DR-16 assertion; sentinel row; provider not invoked; Redis-down fail-open).
- **S5.9** Credential CRUD + validate API (`/me/llm-credentials`) + schemas + error codes + audit + anti-oracle caps (R-S4). TDD `test_llm_credentials_api.py` (masked reads, `byok.base_url_forbidden`, oracle caps, redacted probe, `/me/export` exclusion).
- **S5.10** (sentinel contract completion — extends S7pre.5 now that sinks exist).
- **S5.12** Thread `LLMContext` through every foreground call site (DR-8): `tutor_orchestrator`, `authoring_orchestrator` (`draft_course`), `learning_path` (`build_path`/`replan_for_user`/`_chat_with_retry`), tutor subagents, `tutor_streaming` worker (carry `credential_id`), `stream_chat(ctx)` (remove global switch). Each site defaults `ctx=PLATFORM_CONTEXT` so partial threading never regresses.
- **S5.13** Admin cost surface: `billing_mode` grouping + platform-$ excludes BYOK (`admin_llm_calls.py:170`).
- **S5.14** `rotate_byok_master_key` CLI + runbook (R-S2).
- **S5.15** Frontend BYOK settings tab `/profile/model` + i18n + hooks (no `api_base` field). Hand-edit `types.ts` (DR-5).
- **S5.16** Flag-gate `feature_byok_enabled=False` + CHANGELOG. Flip only after KEK fleet-confirmed.

### WAVE 2a — S3: Goal-intake → private course build (worktree `wt/s3-goal-build`)

- **S3.1** `LearningBrief` model + **Migration 0037** (Phase A) `learning_briefs` (field-encrypted `source_goal_enc` via `secrets_crypto`, DR-22 independent of BYOK KEK). TDD: goal never in repr/serialization (FR-PRIV-01).
- **S3.2** Brief Pydantic schemas + `BriefLevel`→`Difficulty` mapping.
- **S3.3** Elicitation service `services/learning_brief.py` (bounded 6-turn convergence, finalize→immutable, per-user session quota R-M10, `call_logged` metered). TDD `test_learning_brief_service.py`.
- **S3.4** Goal-intake endpoints (`/ai/goal/start|turn|finalize`, `RequireAuthor`, rate-limited, metered). TDD: 401 anon, 403 suspended, cross-user finalize→404.
- **S3.5** Seed reserved "Personal/Self-directed" Subject (idempotent `ON CONFLICT`, fold into 0037).
- **S3.6** Thread brief into `draft_course` (DR-4): difficulty from `brief.level` (replaces `authoring_orchestrator.py:1146`), outcomes from brief, module/lesson estimate from `time_budget_hours`, level/time/outcomes into outliner+critic prompts, subject auto-resolve (no `subject_not_found`), `visibility=private` (consumes 0033). **Update pinned `test_authoring_orchestrator.py` consciously (FR-DEFINE-18).**
- **S3.7** `build_failed` `CourseStatus` value + re-runnable + idempotent build endpoint + non-dollar concurrency/quota caps. Coordinate `retrieval_acl_clause` `status != build_failed` literal with S2 (one-line follow-up if S2 shipped first).
- **S3.8** `POST /me/courses/{id}/cancel-build` (DR-1a) + cooperative-cancel fence (R-S10).
- **S3.9** Owner self-learn on private draft + self-enroll (FR-LEARN-01, R-M8′). **Consumes S4's `Enrollment.is_self` (0035) + shared `enroll_self`/`_maybe_issue_certificate` guard** — sequence after 0035 or stub+rewire.
- **S3.10** Beat sweeps `sweep_orphaned_build_drafts` + `sweep_unfinalized_briefs` (DR-1b, idempotent).
- **S3.11** Frontend define→build→learn flow (`/dashboard` CTA, multi-turn intake, brief review, build progress via `CourseDraftTrace`, deep-link to learn). i18n en+ar + axe AA. Hand-edit `types.ts` (DR-5).

### WAVE 2b — S6: Admin, moderation actions & account lifecycle (worktree `wt/s6-admin`)

- **S6.0** (verify S7pre.7 cascade fix landed; own it if not).
- **S6.1** Reason taxonomy + report-content sanitizer `moderation_taxonomy.py` (shared by moderation + suspension; `QUARANTINE_REASONS={csam,illegal}`, `severe_abuse` hard-removal-only). TDD `test_moderation_taxonomy.py`.
- **S6.2** Admin moderation transition fns `services/moderation.py` (`approve/reject/delist/relist/remove_course`) writing `ModerationEvent`+`AuditEvent`, `quarantined` for csam/illegal, revoke-on-hard-removal. TDD `test_moderation_service.py`.
- **S6.3** **Migration 0034** (Phase A) `course_reports` + report-flow service (`report_course`, DR-20 account-age + email-verified gating, open-report coalescing, per-course rate limit). TDD `test_course_reports.py`.
- **S6.4** Admin moderation + report endpoints (`/admin/courses/moderation-queue` cursor, actions, `/admin/reports`, `/admin/reports/{id}/resolve` atomic single-audit). R-S11: approved-course report accumulation requeues to `pending_review`, never auto-delists.
- **S6.5** Narrow `_can_edit_course` admin branch (FR-MOD-05, admin views any but mutates own only / via moderation). Coordinate with S2.8.
- **S6.6** Grant/revoke-admin toggle + last-admin invariant (`PATCH /admin/users/{id}/admin`; legacy `/role` normalize→422; `count_active_admins`). TDD `test_admin_grant_revoke.py`.
- **S6.7** Suspend/reinstate sharing `is_active`, distinct from deletion via `deleted_at`; refresh-token revoke; `auth.account_suspended` vs `auth.account_deleted` codes. TDD `test_suspend_reinstate.py`, `test_auth_suspended_codes.py`.
- **S6.8** `delete_account` choreography (anonymize-in-place, 11-step, try-guarded sibling steps catching only `ProgrammingError`/`UndefinedTable`/`ImportError`) + `assert_account_active` cooperative-cancel wired at streaming heartbeat + build/clone fences (R-S10). TDD `test_delete_account.py`, `test_cooperative_cancel.py`.
- **S6.9** `authors` platform stat (replaces role-derived `instructors`; ships with TS client/`admin/page.tsx` in one PR).
- **S6.10** `DeletedUserName` read-time anonymization serialization (DR-19). TDD `test_deleted_user_rendering.py`.
- **S6.11** Admin moderation frontend + user-mgmt UI + `authors` stat + `/profile` delete wiring. Hand-edit `types.ts` (DR-5). en+ar + axe AA.

### WAVE 3 — S4: Clone / Remix (worktree `wt/s4-clone`; 0035+projection early in Wave 2 to unblock S3)

- **S4.1** Provenance + `is_self` model cols + `IdempotencyKey` model (model-only).
- **S4.2** **Migration 0035** (Phase A) `clone_provenance` (6 provenance cols + `enrollments.is_self` + concurrent indexes) + **0036** (Phase A) `idempotency_keys`. **Land 0035 early (Wave 2) to unblock S3 self-enroll.**
- **S4.3** Sanitized export projection `clone_projection.py` (frozen whitelist DTO, soft-delete exclusion, empty-module drop, `is_preview=false`, dense 0-based orders, quiz verbatim deepcopy, size ceiling). **The single most security-load-bearing test (field-set tripwire).**
- **S4.4** `enroll_self` + certificate suppression (`is_self`, R-M8′) — **shared seam, S3 consumes**.
- **S4.5** Clone schemas (`CourseOrigin`, `origin`/`is_clone`, `extra="forbid"` on `CourseCreate`/`CourseUpdate`).
- **S4.6** `clone_course` service + `POST /courses/{key}/clone` + idempotency (resolve+authorize via `is_publicly_listed`+403/404 split, project, materialize atomic with server-written immutable provenance, `enroll_self`, audit ×2 + origin notification). Flag-gate `clone_enabled=False`.
- **S4.7** Clone quotas + amplification caps (non-dollar: `clone_per_hour`, `clone_owned_cap`, `clone_max_lessons`, R-S7).
- **S4.8** Read-time provenance anonymization + `origin_available` (DR-19; deleted-owner→"a deleted user" even if snapshot scrub never ran).
- **S4.9** Lazy asset re-homing worker `media.copy_clone_asset` (**download→revalidate→reupload, DR-9, NOT CopyObject** — R-S5 re-validates bytes) + orphan sweeper + cooperative-cancel.
- **S4.10** Lazy embeddings (verify never copied; regenerate on publish via `_schedule_embedding_index`; zero-chunk clone).
- **S4.11** Frontend Clone CTA + origin attribution + query keys + i18n. Hand-edit `types.ts` (DR-5). axe AA.

### WAVE 4 — S7-post: Cross-cutting close (after all streams)

- **S7.1** CI contract-drift check (`openapi.json` vs fresh; `test_openapi_snapshot.py`; `make openapi.check`; **never `make api-client`**, DR-5).
- **S7.2** `types.ts` Role union finalize + frontend drift guard (`api-role-contract.test.ts`).
- **S7.3** **Migration 0045** (Phase A) `agent_traces.parent_message_id` self-FK + backfill + `learner_traces` FK fast-path with temporal fallback (DR-2). TDD `test_learner_traces_parent_message.py`.
- **S7.4** Eval regression gate on recorded fixtures, ε=0.30, inconclusive-on-outage (R-U6). TDD `test_eval_fixture_gate.py` + CI `eval-gate` step.
- **S7.5** i18n en+ar parity for all net-new keys + RTL logical properties + `translation_status` (FR-I18N-04, R-U8).
- **S7.6** axe WCAG 2.2 AA over every net-new surface + 3-persona shim + Arabic/RTL pass (FR-A11Y-03).
- **S7.7** Migration-application RUNBOOK encoding Phase A/B/C/D (DR-12) + phase-annotation guard `test_migration_phase_annotations.py`.
- **S7.8** OpenAPI regen + commit (`make openapi`) after all streams + manual `types.ts`/`endpoints.ts` sync.
- **S7.9** ADR finalization (fold DR-6-R2/DR-18-R2/DR-19/DR-10/DR-17/DR-22 into ADR-0026/0027/0029/0030; new eval ADR documenting ε) + `test_adr_consistency.py`.
- **S7.10** Consolidated migration-chain rev-list 0030–0045 + `test_migration_chain.py` (head=0045, linear, only 0031 irreversible, no collisions).
- **S7.11** CHANGELOG finalization (Added/Changed/Migration sections; `changelog-shape.test.ts`).
- **(S7-post deferred ADRs, design-spec §9):** ingest SSRF hardening ADR (opens `can_ingest_url` flag — out of this build's scope, keeps ingest closed); prompt-injection rail (ADR-0024) re-eval with the FR-CLONE-21 adversarial-cloned-content test.

---

## PART 5 — RISKS & SEQUENCING HAZARDS

### 5.1 Migration phasing (the irreversible step)

- **0031 is the only irreversible migration (R-C4).** It backfills `student|instructor → user` with a **no-op downgrade** — once run, `student` vs `instructor` is unrecoverable. **Hazard:** a blind `make migrate`/`alembic upgrade head` would run 0031 before the fleet is in Phase A, or before evidence supports it. **Mitigation:** the runbook (S7.7) applies 0031 as an **explicit `alembic upgrade 0031` step in Phase B only**, after the Phase-A image (accepting all 4 role values) is confirmed up; `test_migration_phase_annotations.py` forces every ≥0030 rev to declare its phase; rollback past 0031 is forbidden (image-rollback only).
- **NOT-NULL tightens (0043) are evidence-gated (Phase D, DR-14/R-S8′).** **Hazard:** an old ingest pod INSERTs a chunk missing `embedding_model` after the column is NOT NULL → INSERT failure. **Mitigation:** the 0041→0043 nullable→backfill→NOT-NULL split; 0043 runs only after the always-stamps-model ingest image is fleet-wide and 0041 drained. The backfill model value is **operator-confirmed**, never assumed.
- **0033 backfill must make `is_publicly_listed ≡ status==published` for existing rows** so old-fleet readers and the new authorizer agree (R-S8′ step 1). **Hazard:** a delisting/false-private during backfill. **Mitigation:** batched UPDATE (live-published→`public,approved`; else `private,none`); synthetic `approved` events; verify catalog unchanged in Gate C before flag flip.

### 5.2 Zero-downtime (single-host topology, DR-12)

- Prod is **single-host docker-compose (one API + one worker)** — multi-pod read-skew reduces to **JWT 15-min token-drain**. **Hazard:** over-engineering a fleet rollout; or under-accounting for the 15-min stale-token window in Phase D's positive-evidence gate (R-C5′ requires ≥15-min TTL elapsed). **Mitigation:** runbook states the topology explicitly; Phase D gate query includes the TTL-elapsed check.
- **CONCURRENTLY index builds (0033/0035/0042/0044/0045)** can leave an INVALID index if they fail mid-build. **Mitigation:** `autocommit_block()` + `DROP INDEX IF EXISTS` for re-runnability; runbook step to drop/rebuild on failure; tune batch sizes to live catalog `count(*)` before prod.
- **0044 rebuilds `ix_courses_listed`** (adds `quarantined=false` to partial WHERE) via CONCURRENTLY drop+recreate — verify EXPLAIN still uses it on the catalog hot path (DR-15). **Defer dropping the legacy `ix_courses_status_subject`** until EXPLAIN confirms the consolidated index is used.

### 5.3 Feature-flag flips (the leak-window guards)

- **`FEATURE_PRIVATE_PUBLISH_ENABLED` (S2, DR-13/R-S8′):** flip to `true` **only after** the authorizer-bearing image is fleet-confirmed and the grep-guard is green (`READERS_PENDING_MIGRATION` empty). **Hazard:** flipping early = a private-publish write before all readers route through the authorizer = leak. **Mitigation:** the 4-step rollout with an asserted invariant that no non-default visibility is writable before step 4; Gate C verifies Share is unavailable with the flag OFF.
- **`feature_byok_enabled` (S5):** flip **only after** the KEK boot guard confirms a real KEK on **every** API + worker process (R-S2/R-S3). **Hazard:** enabling BYOK with a derived/missing KEK in prod = unencryptable keys / boot loop. **Mitigation:** boot guard fires on both API (`assert_production_safe`) and worker (`worker_process_init`); the guard also fires when any `learning_briefs` row exists (brief encryption shares the KEK).
- **`clone_enabled` (S4):** keep `False` until 0035/0036 confirmed applied, so partial landings never run clone code against a missing column.

### 5.4 Cross-stream contact points (merge-time hazards)

- **Migration-number races across parallel worktrees.** S1/S2/S5 (Wave 1) and S3/S4/S6 (Wave 2) all add revisions. **Hazard:** two worktrees pick the same number or a dangling `down_revision`. **Mitigation:** Part 2 pre-assigns every number; each worktree temporarily chains off the last-landed rev and re-points at integration; `test_migration_chain.py` (S7.10) is the merge-time backstop (linear, no collisions, head=0045).
- **`Enrollment.is_self` ownership (S4 owns, S3 consumes).** **Hazard:** S3's self-enroll lands before 0035. **Mitigation:** sequence 0035 early in Wave 2; S3 stubs `is_self` + rewires; the shared `enroll_self`/`_maybe_issue_certificate` guard is S4-owned and self-contained (design-spec §8.12).
- **`_can_edit_course` narrowing touched by both S2.8 and S6.5.** **Hazard:** double-edit/merge conflict. **Mitigation:** S2 narrows it; S6.5 becomes the regression test if S2 already shipped (both plans note this).
- **Moderation service-fn ownership (S2 owner-intent fns vs S6 admin-authority fns).** **Hazard:** the design-spec lists both under different streams (line 235 vs 264). **Mitigation:** explicit split — S2 ships `share/unshare/unpublish` side-effects + predicates; S6.2 owns `approve/reject/delist/relist/remove`; S6 completes any S2 stub.
- **`platform_stats` `instructors`→`admins`/`authors` is OpenAPI-visible (S1.8 + S6.9).** **Hazard:** backend rename without the TS client/admin-dashboard change = `undefined` in the admin UI. **Mitigation:** the rename ships with the TS client + `admin/page.tsx` stat + i18n key in **one PR** (ADR-0025 open-risk #6).
- **`retrieval_acl_clause` `build_failed` literal (S2 ships clause, S3 adds the state).** **Hazard:** S2's clause references only `deleted_at`, letting an owner's failed drafts leak into their own cross-course RAG. **Mitigation:** S2's owner-branch defensively guards `build_failed` via getattr/string compare; S3 files a one-line follow-up to make it exact (R-S12).
- **`types.ts` is hand-written (DR-5) across S1/S2/S3/S4/S5/S6.** **Hazard:** someone runs `make api-client` and clobbers the curated file. **Mitigation:** every stream hand-edits `types.ts` in the same PR as its endpoints; S7.1's CI contract-drift check diffs `openapi.json` only and **never writes** the TS side; CLAUDE.md/`types.ts` header comment corrected to strike the regenerate claim.

### 5.5 Security/correctness hazards carried across the build

- **BYOK key leakage** is structurally prevented by `SecretStr`-wrapped providers (S5.6) + the only-decrypt-in-`build_provider` invariant (S5.7); the value-redaction filter (S7pre.5/S5.10) is defense-in-depth. The enumerated-sink sentinel test is the tested contract.
- **Visibility leak** is structurally prevented by routing all 14 readers through the authorizer with the grep-guard as the backstop (DR-3-R2). `READERS_PENDING_MIGRATION` empty is a hard gate.
- **GDPR/anonymization ordering** (deletion before provenance columns landed) is closed by **read-time** anonymization (DR-19) — the S6 one-time scrub is belt-and-suspenders, not the guard.
- **Quarantine two-truth-sources** risk (ADR-0026's moderation_events-lookup vs DR-18-R2's column) is resolved: `quarantined` column is the single source of truth for csam/illegal; `severe_abuse` legitimately stays a `moderation_event.reason_code` read.
- **Cooperative-cancellation completeness (R-S10):** every future foreground LLM feature must adopt `assert_account_active`; enforced by a suspend-mid-stream regression test (S6.8) + the system-gate E2E.


---

# Appendix — Per-Stream Plans


<!-- ===== S1 ===== -->

# Stream S1: Role collapse & capability RBAC

**Authoritative canon:** ADR-0025 (owns this stream) · DESIGN-RESOLUTIONS.md (R-CAP, R-C4, R-C5/C5′, DR-22) supersedes on conflict · design-spec §3.1/§3.3/§7-step-2 · REQUIREMENTS-RESOLUTIONS for FR/R traceability.

**Verified ground-truth corrections to the task brief (cite source):**
- The brief says "24 `RequireInstructor` sites." **Real count is 26** (`grep -c`): `courses.py`=16, `ai_authoring.py`=**6** (`:170/194/219/249/310` + the import-line count is 6 decorator uses), `content_ingest.py`=**4** (`:65/80/102` + one more). ADR-0025's "24" is stale; CHARTER §6a and design-spec §0 confirm 26. **Plan against 26.**
- `Role` is `String(20)`, not a PG `ENUM` (`user.py:36`) — collapse is app-enum + data `UPDATE`, **no `ALTER TYPE`**.
- Latest migration is **0029** (`down_revision="0028"`); per the §2.5 single-chain, S7-pre owns 0030 (`users.deleted_at`), so **S1 owns 0031 (data collapse) + 0032 (default flip)** with `down_revision="0030"` → `"0031"`. (Brief's "migrations 0031+0032" matches the master chain; ADR-0025's local "0030/0031" numbering is superseded by design-spec §2.5.)
- JWT `role` claim is already authz-inert: `deps.py:48,68` re-read the live DB row; `decode_token` (`security.py:64`) never inspects `role`. The S1 test only has to *prove* this invariant.
- `UserAdminOut`, `UserRoleUpdate`, `PlatformStatsOut` are defined **inline in `app/api/v1/admin.py`** (`:159/171/391`), not in `schemas/`.
- Frontend `Role` is hand-written (`types.ts:3`) — **do NOT `make api-client`** (DR-5); edit by hand + CI drift check (owned by S7).
- Extra frontend site not in CHARTER §6a inventory: `components/shared/site-header.tsx:86,98` (`navLinksFor` role union + studio link gate). Must be included.

---

## Preconditions / depends-on (other streams, by Sx)

- **S7-pre** (foundation, design-spec §7 step 1) must land first: migration **0030** (`users.deleted_at`) + the ORM cascade fix (`User.courses_owned` → `save-update`, DR-6/DR-6-R2). S1's migrations chain off 0030. *If S7-pre is not yet merged, S1 may still proceed by temporarily chaining 0031 off 0029 in the worktree, but the master chain (§2.5) requires 0030 first — coordinate at integration so `down_revision` is `"0030"`.*
- **No dependency on S2–S6.** S1 is the root; CHARTER §4: "S1 precedes most."
- The capability layer file `app/services/capabilities.py` is nominally listed in S7-pre, but **this stream owns its creation** (it is the load-bearing artifact of ADR-0025). If S7-pre already created it, S1.2 becomes an extension rather than a create.

---

## Ordered tasks

Order keeps the stream green at every step: capability layer (pure, no callers) → deps → route swaps → service ungate → MCP → migrations → JWT inert test → frontend → i18n. Each task is independently testable.

---

### S1.1 — Widen the `Role` enum to accept legacy + new (Phase A tolerance)

- **Goal:** make `Role` contain `{student, instructor, user, admin}` so no ORM row or request body crashes during the transition window (R-C5, ADR-0025 Phase A).
- **Files:** `app/models/user.py` (`Role` StrEnum at `:19-22`).
- **TDD steps:**
  1. **Failing test** `tests/test_role_enum.py::test_role_enum_accepts_user_and_legacy` — assert `Role("user")`, `Role("admin")`, `Role("student")`, `Role("instructor")` all resolve, and `Role.user.value == "user"`. Fails today (`Role("user")` → `ValueError`).
  2. **Impl:** add `user = "user"` to the `Role` StrEnum (keep `student`/`instructor` for now — they are removed in Release 3 / a later S1 sub-task gated by positive evidence; for the build/test pass we keep them so legacy rows load).
  3. **Green.**
- **Migrations:** none.
- **Acceptance:** Given the enum, When the app deserializes any of the four strings, Then no `ValueError`; `Role.user` exists.
- **Risk/notes:** `StrEnum` ordering doesn't matter for authz. Do NOT alias `student`/`instructor` away yet — anonymize/serialization paths still read legacy rows until 0031 backfills. The narrow-to-`{user,admin}` final cut is S1.13 (evidence-gated).

---

### S1.2 — Create `app/services/capabilities.py` (DR-CAP, ADR-0025 D2)

- **Goal:** the single home for pure capability predicates over `(User, Settings)`.
- **Files:** create `app/services/capabilities.py`; add the two new Settings flags to `app/core/config.py` (`ingest_url_enabled: bool = False`, `mcp_authoring_enabled: bool = True`) if absent.
- **TDD steps:**
  1. **Failing test** `tests/test_capabilities.py`:
     - `test_can_author_active_user_true` — active `user`/`instructor`/`student`/`admin` → `True`.
     - `test_can_author_suspended_false` — `is_active=False` → `False` (R-CAP: suspension is the only revocation).
     - `test_admin_passes_all_capabilities` — admin → True for author/clone/publish_public/view_analytics(own & others')/mcp_authoring; `can_ingest_url` admin+flag-on → True, admin+flag-off → False.
     - `test_can_ingest_url_non_admin_always_false` — active non-admin user, flag on or off → `False` (DR-M12: ingest stays closed).
     - `test_can_view_course_analytics_owner_only` — non-admin sees own course True, other's course False.
  2. **Impl:** exactly the signatures in ADR-0025 D2 / design-spec §3.1:
     ```python
     def _active(u): return u.is_active
     def can_author(u): return _active(u)
     def can_clone(u): return _active(u)
     def can_publish_public(u): return _active(u)
     def can_view_course_analytics(u, course): return _active(u) and (u.is_admin() or course.owner_id == u.id)
     def can_use_mcp_authoring(u, s): return _active(u) and s.mcp_authoring_enabled
     def can_ingest_url(u, s): return _active(u) and s.ingest_url_enabled and u.is_admin()
     ```
  3. **Green.**
- **Migrations:** none.
- **Acceptance:** Given an active user, When `can_author(u)`, Then True; Given a suspended user, Then False; Given a non-admin + `can_ingest_url`, Then False regardless of flag.
- **Risk/notes:** Pure functions, no DB, no `await` — fast unit tests, no fixtures beyond `make_user`. `can_ingest_url` is **global-flag + admin-only**, NOT per-user (DR-M12, charter decision 7). No `user_capability_overrides` table (R-CAP). Force-clear the Settings cache in tests that flip flags (conftest does this on env override).

---

### S1.3 — Add `RequireAuthor` / `RequireIngestUrl` deps + `auth.capability` code (ADR-0025 D3)

- **Goal:** convenience capability guards layered over `capabilities.py`.
- **Files:** `app/api/deps.py`.
- **TDD steps:**
  1. **Failing test** `tests/test_deps_capabilities.py` (via a throwaway test router or by hitting an already-`RequireAuthor`'d route in S1.4 — to keep S1.3 standalone, mount a tiny test-only app fixture):
     - `test_require_author_active_user_200`.
     - `test_require_author_suspended_403_capability` — body `error.code == "auth.capability"`, `error.details.capability == "can_author"`.
     - `test_require_author_anonymous_401` — `error.code == "auth.required"`.
     - `test_require_ingest_url_non_admin_403`.
  2. **Impl:** add `_require_author`, `RequireAuthor`, `_require_ingest_url`, `RequireIngestUrl`, and a `RequireCapability(fn)` factory (used later by S4 clone). Import `from app.services import capabilities as cap`. `ForbiddenError(..., code="auth.capability", details={"capability": "..."})`. Keep `require_role`/`RequireAdmin` unchanged.
  3. **Green.**
- **Migrations:** none.
- **Acceptance:** Given suspended user on `RequireAuthor` route → 403 `auth.capability`; Given anonymous → 401 `auth.required`; Given non-admin on `RequireIngestUrl` → 403.
- **Risk/notes:** `RequireIngestUrl` resolves `cap.can_ingest_url(user, settings)` — needs `Settings` injected (use the existing settings dependency/`get_settings`). Anonymous → 401 comes free because `RequireAuthor` builds on `CurrentUser` (`get_current_user` raises `auth.required`).

---

### S1.4 — Swap the 22 author/owner routes to `RequireAuthor` (courses + ai_authoring)

- **Goal:** ungate authoring/owner routes from instructor to any active user (FR-RBAC-02). 16 in `courses.py` + 6 in `ai_authoring.py` = 22.
- **Files:** `app/api/v1/courses.py` (import + 16 sites), `app/api/v1/ai_authoring.py` (import + 6 sites).
- **TDD steps:**
  1. **Failing tests** in `tests/test_courses.py` / `tests/test_ai_authoring.py`:
     - `test_user_role_can_create_course` — `make_user(role=Role.user)` + `auth_headers(role=Role.user)`, `POST /courses` → 201 (today 403 `courses.forbidden`).
     - `test_user_role_can_list_my_courses` — `GET /courses/mine` 200.
     - `test_user_role_can_call_ai_outline` — `POST /ai/outline` 200/accepted.
     - Keep an existing instructor/admin test green (regression).
     - `test_suspended_user_cannot_create_course` — 403 `auth.capability` (FR-DEFINE-06).
  2. **Impl:** replace `RequireInstructor` with `RequireAuthor` at all 22 sites; update the two import lines. The course-analytics route (`courses.py:344/367/374`) moves to `RequireAuthor` at the route but its service gate is `cap.can_view_course_analytics` (owner-or-admin) — added in S1.5.
  3. **Green.**
- **Migrations:** none.
- **Acceptance:** Given a `user`-role caller, When POST `/courses` / `/ai/outline`, Then 200/201; Given suspended, Then 403 `auth.capability`; Given anonymous, Then 401.
- **Risk/notes:** **Owner-vs-admin write authority must stay** — collapsing the route gate must NOT let user A edit user B's course; that protection lives in the service `_owned_course` (S1.5). Course-analytics (`courses.py:344`) is the one "author route" that is actually owner-or-admin, not all-users — do not leave it as bare `RequireAuthor` without the service re-check (S1.5).

---

### S1.5 — `create_course` ungate + service-layer capability/ownership re-checks

- **Goal:** drop the `is_instructor_or_admin` business gate (FR-RBAC-04); generalize ownership check; gate analytics by capability.
- **Files:** `app/services/courses.py` (`create_course:68-70`; `_owned_course:97,130` → keep/rename to `_can_edit_course`); analytics service path used by `courses.py:344`.
- **TDD steps:**
  1. **Failing tests** in `tests/test_courses.py`:
     - `test_create_course_no_instructor_gate` — calling `create_course(db, owner=user_role_user, payload)` returns a Course (today raises `ForbiddenError courses.forbidden`).
     - `test_user_cannot_edit_other_users_course` — user B `update_course` on user A's course → `ForbiddenError`/`NotFoundError` (ownership preserved).
     - `test_course_analytics_owner_only` — owner 200, non-owner non-admin 403, admin 200.
  2. **Impl:** delete lines 69-70 of `services/courses.py` (the `if not owner.is_instructor_or_admin()` block). Keep `_owned_course` semantics (rename to `_can_edit_course` optional — keep diff minimal, but ensure admin can edit any, owner can edit own). Add `cap.can_view_course_analytics(user, course)` check in the analytics service entry.
  3. **Green.**
- **Migrations:** none.
- **Acceptance:** Given any active user, When `create_course`, Then success; Given non-owner non-admin, When `update_course`/analytics, Then forbidden.
- **Risk/notes:** `courses.forbidden` error code becomes **unreachable** — remove it and grep that no test asserts it (the design says it's removed; a lingering test would go red). The `is_instructor_or_admin()` method itself is still referenced at `mcp/tools.py:574` (docstring only) and `models/user.py:67` — leave the *method* until S1.13 Release-3 cleanup; just stop *calling* it here.

---

### S1.6 — MCP principal & enforcement reconcile (ADR-0025 D5, FR-RBAC-07/08)

- **Goal:** replace the MCP `is_instructor` write-gate with a capability gate, keep legacy instructor principals working through the window, keep `ingest_url_to_draft` admin-only.
- **Files:** `app/mcp/principal.py` (add `can_author`, `can_use_mcp_authoring`, `can_ingest_url`; keep `is_instructor` deprecated), `app/mcp/server.py` (`_enforce_auth:109-115`), `app/mcp/tools.py` (`_require_instructor:571-577` → `_require_author`; ToolSpec `auth` for `create_course_draft` `"instructor"→"user"`; `ingest_url_to_draft` stays `"admin"`).
- **TDD steps:**
  1. **Failing tests** in `tests/test_mcp_*` (e.g. `tests/test_mcp_tools.py` / `tests/test_mcp_server.py`):
     - `test_mcp_user_principal_can_create_course_draft` — a `user`-role principal invokes `create_course_draft` → allowed (today `mcp.role.instructor_required`).
     - `test_mcp_legacy_instructor_principal_still_authors` — an `instructor`-role principal still authors (Phase A tolerance, FR-RBAC-07).
     - `test_mcp_user_principal_cannot_ingest_url` — `user` principal on `ingest_url_to_draft` → denied (admin-only).
     - `test_mcp_suspended_principal_cannot_author` — inactive user principal → denied.
     - assert new code `mcp.writes.author_required` on denial.
  2. **Impl:** `Principal.can_author = self.user is not None and self.user.is_active`; add `can_use_mcp_authoring`/`can_ingest_url` mirroring `capabilities.py`; keep `is_instructor` property (deprecated) so the legacy branch resolves. In `_enforce_auth`, redefine the `auth=="instructor"` branch as a `principal.can_author` check (or move `create_course_draft` to `auth="user"` and re-check `can_author` in the handler). `tools.py:_require_instructor` → `_require_author` (checks `can_author`, raises `mcp.writes.author_required`). `ingest_url_to_draft` handler additionally requires `can_use_mcp_authoring AND can_ingest_url`.
  3. **Green.**
- **Migrations:** none.
- **Acceptance:** Given a `user` MCP principal, When `create_course_draft`, Then allowed; Given the same on `ingest_url_to_draft`, Then denied; Given a legacy `instructor` principal, Then still authors.
- **Risk/notes:** The brief mentions "`content_ingest` stays `can_ingest_url=closed` per DR-M12" — this applies to both REST (`RequireIngestUrl` in S1.7) and MCP `ingest_url_to_draft` here. MCP role re-reads live DB `User.role` (`principal.py:113`), so a stale token for a former instructor is already `user` post-backfill — safe. Keep `mcp.role.instructor_required` code defined only while the legacy branch exists; remove in S1.13.

---

### S1.7 — `content_ingest.py` routes → `RequireIngestUrl` (stays closed, DR-M12)

- **Goal:** the 4 ingest routes move off `RequireInstructor` to `RequireIngestUrl` (admin-only + flag-off), NOT to `RequireAuthor` (FR-SEC-02).
- **Files:** `app/api/v1/content_ingest.py` (import + `:65/80/102` + the 4th site).
- **TDD steps:**
  1. **Failing tests** in `tests/test_content_ingest.py`:
     - `test_ingest_closed_for_regular_user` — active `user`-role caller → 403 `auth.capability` (capability `can_ingest_url`). This is the negative security test FR-SEC-02.
     - `test_ingest_closed_for_admin_when_flag_off` — admin + `INGEST_URL_ENABLED=false` → 403 (flag-off).
     - `test_ingest_allowed_for_admin_when_flag_on` — admin + flag on → reaches handler (200/accepted).
  2. **Impl:** swap `RequireInstructor` → `RequireIngestUrl` at all 4 sites; update import.
  3. **Green.**
- **Migrations:** none.
- **Acceptance:** Given role collapse complete, When any non-admin posts to `/content-ingest/*`, Then 403; the SSRF surface is NOT opened by S1.
- **Risk/notes:** This is the load-bearing Gate-A correction — the brief's whole point is that ingest must NOT be globally opened. The flag default is `False` (S1.2). Opening it is a future SSRF-hardening ADR (charter decision 7), out of S1 scope.

---

### S1.8 — Role defaults → `user`, admin counts, settable-role restriction (Phase C code)

- **Goal:** flip all code defaults student→user, fix `platform_stats`, restrict admin role writes to `{user,admin}` (FR-RBAC-06, FR-ADMIN-07, FR-EVAL-03).
- **Files:** `app/services/auth.py:58`, `app/repositories/users.py:26`, `app/cli.py:151-152`, `app/seeds/demo.py:544/552`, `app/evals/run_baseline.py:159`, `app/api/v1/admin.py` (`set_user_role:194-210`, `platform_stats:402-411`, `PlatformStatsOut:391`), `app/models/user.py:36` (`default=Role.student` → `Role.user`).
- **TDD steps:**
  1. **Failing tests:**
     - `tests/test_auth.py::test_signup_defaults_to_user_role` — register → new user `.role == Role.user`.
     - `tests/test_admin_stats.py::test_platform_stats_reports_admins_and_authors` — assert response has `admins` + `authors` (and `instructors` field handled per FR-API-02 transition).
     - `tests/test_admin.py::test_set_user_role_rejects_legacy_values` — `PATCH /admin/users/{id}/role {role:"instructor"}` → 422 (settable set is `{user,admin}`); `{role:"user"}` → 200.
     - `tests/test_baseline_eval.py` (or `test_cli`): seed/baseline picks a `user`-role account.
  2. **Impl:** flip every default to `Role.user`. In `admin.py`: change `platform_stats` `instructors` query to `admins` (`User.role == Role.admin`) + `authors` (= `COUNT(DISTINCT owner_id)` over live courses, or active non-admin users per ADR-0025) and rename the `PlatformStatsOut` field set per FR-ADMIN-05 (keep `instructors` through Phase C if FR-API-02 transition requires, else flip — coordinate the TS client change in S1.11 same PR). `set_user_role`: validate `payload.role in {Role.user, Role.admin}` else 422 `user.invalid_role`; add a `normalize_role`-style `field_validator` on `UserRoleUpdate` (read-tolerant, write-forbidden for legacy). `run_baseline.py:159` selects any active non-admin (`Role.user`) not hard `student`, with updated RuntimeError naming the new account.
  3. **Green.**
- **Migrations:** none in this task (the DB `server_default` flip is migration 0032, S1.10).
- **Acceptance:** Given a fresh signup, Then role is `user`; Given admin sets role `instructor`, Then 422; Given `/admin/stats`, Then `admins`/`authors` counts present.
- **Risk/notes:** `platform_stats` rename is **OpenAPI-visible** — must ship with the TS client/admin-dashboard change in the same PR (S1.11) or the admin UI renders `undefined` (ADR-0025 open-risk #6). The `set_user_role` self-demote guard (`admin.py:199`) stays. Demo seed accounts (`teacher@`, `student@`) keep their emails but get `role=Role.user` — a compatibility shim (S1.12 frontend, conftest) maps them for tests.

---

### S1.9 — JWT inert-claim test + `normalize_role` display helper (ADR-0025 D6, FR-MIG-04)

- **Goal:** prove the JWT `role` claim grants nothing once the DB row changes; add a display-only normalizer.
- **Files:** `app/core/security.py` (add `normalize_role(raw) -> Role` mapping legacy/unknown → `Role.user`); test only.
- **TDD steps:**
  1. **Failing test** `tests/test_jwt_role_inert.py::test_stale_instructor_token_grants_nothing` —
     - Create a user, demote DB row to `Role.user` (or it already is), but mint an access token with `role="instructor"` (`create_access_token(subject=user.id, role="instructor")`).
     - Hit a `RequireAdmin`-or-instructor-formerly-gated *admin* route with that token → 403 (the claim does NOT grant admin/instructor power).
     - Hit `RequireAuthor` route → 200 (because the live row is an active user, not because of the claim).
     - `test_decode_token_does_not_validate_role` — a token with `role="bogus"` still decodes and authenticates (role is never validated at decode).
     - `test_normalize_role_maps_legacy_to_user` — `normalize_role("instructor") == Role.user`, `normalize_role("admin") == Role.admin`, `normalize_role("garbage") == Role.user`.
  2. **Impl:** add `normalize_role` to `security.py`; use it only on display/materialization paths (not authz). Authz already re-reads DB (`deps.py:48,68`) — no code change needed there, the test documents the invariant.
  3. **Green.**
- **Migrations:** none.
- **Acceptance:** Given a token claiming `instructor` but a DB row that is `user`, When the user calls an admin route, Then 403; the claim is provably inert.
- **Risk/notes:** This is the explicit FR-MIG-04 testing obligation in ADR-0025 "Testing obligations." The mint side (`auth.py:195`, `security.py:53`) keeps writing `role` for back-compat; from Phase C it writes the normalized value.

---

### S1.10 — Migrations 0031 (data collapse, IRREVERSIBLE) + 0032 (default flip)

- **Goal:** backfill `student|instructor → user` and flip the column `server_default` (R-C4, DR-12 phased gating).
- **Files:** create `alembic/versions/2026_..._0031-role_collapse_backfill.py` and `..._0032-role_default_user.py`.
- **TDD steps:**
  1. **Failing test** `tests/test_migration_role_collapse.py`:
     - `test_0031_backfills_legacy_roles` — seed rows with `role IN ('student','instructor')` + an `admin`; run the 0031 `upgrade` logic (or apply via the test DB at session scope per conftest's transient DB); assert no rows remain with legacy roles, admin untouched, idempotent on re-run.
     - `test_0031_downgrade_is_noop` — `downgrade()` does not raise and does not recover legacy values (R-C4 documented no-op).
     - `test_0032_sets_default_user` — after 0032, inserting a user without a role yields `user` (verify via `information_schema` column default or an insert).
  2. **Impl:**
     - **0031** `down_revision="0030"` (S7-pre's `deleted_at`; if S7-pre not yet merged in the worktree, temporarily `"0029"` and re-point at integration):
       ```python
       def upgrade():
           res = op.get_bind().execute(sa.text(
               "UPDATE users SET role='user' WHERE role IN ('student','instructor')"))
           # log res.rowcount
       def downgrade():
           pass  # R-C4: IRREVERSIBLE — cannot recover student vs instructor
       ```
     - **0032** `down_revision="0031"`:
       ```python
       def upgrade(): op.alter_column("users","role", server_default="user")
       def downgrade(): op.alter_column("users","role", server_default="student")
       ```
  3. **Green.**
- **Migrations:** **0031** — up: data `UPDATE` (forward-only, idempotent, single txn, logs rowcount); down: **no-op** (R-C4). **0032** — up: `ALTER COLUMN ... SET DEFAULT 'user'` (metadata-only, fast on PG17); down: reverse to `'student'`. **Zero-downtime note (DR-12):** these are **release-gated**, applied via explicit `alembic upgrade 0031` / `upgrade 0032` steps in the deploy runbook (Phase B then Phase C), NOT a blind `make migrate` to head. 0031 runs while the fleet is in **Phase A** (accepts all four values). 0031 is the **only irreversible** step in the chain; rollback = image-rollback, never `downgrade` past 0031.
- **Acceptance:** Given legacy rows, When 0031 runs, Then all become `user`, admins untouched, re-running is a no-op; When 0032 runs, Then new inserts default to `user`.
- **Risk/notes:** `String(20)` ⇒ no `ALTER TYPE`, no DDL lock beyond the metadata default flip. The `UPDATE` takes brief row locks on `users`; seeded-scale prod is sub-second. Annotate each revision docstring with its release phase (A/B/C per DR-12). Conftest builds a transient DB at session scope and may apply migrations to head — ensure 0031/0032 don't break the autogen/seed path.

---

### S1.11 — Frontend `Role` union + author-gate inversions + admin/users type (FR-RBAC-09)

- **Goal:** `Role = "user" | "admin"`; remove/invert all `role==="student"` author-hides; keep admin + owner gates; fix `admin/users` union and stats consumption.
- **Files:** `src/lib/api/types.ts:3`; `src/app/studio/page.tsx:58/70/74`; `src/app/studio/new/page.tsx:45`; `src/app/studio/draft/[courseId]/page.tsx:51/57/62/77`; `src/app/studio/draft/[courseId]/replay/page.tsx:49/57/62/77`; `src/app/dashboard/page.tsx:91`; `src/components/shared/command-palette.tsx:141`; `src/components/shared/site-header.tsx:86,98`; `src/app/admin/users/page.tsx:37,158-159`; merge `src/lib/onboarding/steps.ts` (`learnerSteps`+`instructorSteps`); add `useCapabilities` helper in `src/lib/auth/`. Admin dashboard stats consumer (wherever `instructors` field is read) updated to `admins`/`authors`.
- **TDD steps:**
  1. **Failing Vitest tests** (`apps/frontend/tests/`):
     - `studio-access.test.tsx` — render `studio/page` with a `user`-role session → does NOT redirect to `/dashboard`, studio content shows (today `role==="student"` redirects).
     - `command-palette.test.tsx` (extend) — `user`-role session sees the "Studio" nav item.
     - `admin-users.test.tsx` — `AdminUser.role` union is `"user"|"admin"`; the role `<Select>` offers only User/Admin (no student/instructor options).
     - a tsc/`Role`-union compile assertion (no `"student"` literal anywhere) — add to an existing types test or rely on `tsc --noEmit` in the gate.
  2. **Impl:** change the union; replace every `user.role === "student"` redirect/hide with capability-by-default (authoring visible to all authenticated non-…—actually to all authenticated users; admins also author). Keep `role !== "admin"` admin redirects and owner gates (`learn/[slug]`, discussions) untouched. `navLinksFor` union → `"user"|"admin"|undefined`; studio link visible to any logged-in user. `admin/users` SelectItems → User/Admin only. Merge onboarding into one set for every `user`. Add `useCapabilities` (`isAdmin`, `canAuthor = !!user`, `canPublishPublic = !!user`) — no server round-trip.
  3. **Green:** `make test.web` + `tsc --noEmit` + eslint.
- **Migrations:** none.
- **Acceptance:** Given a `user`-role browser session, When visiting `/studio`, Then it renders (no redirect); Given the command palette, Then Studio appears; Given `/admin`, Then non-admins still redirect; Given `admin/users`, Then only User/Admin roles are selectable.
- **Risk/notes:** **Do NOT `make api-client`** — `types.ts` is hand-written (DR-5); the CI openapi-vs-types drift check is owned by S7. A stale cached `/me` with `instructor` is harmless because gates are inverted to capability-by-default (ADR-0025 open-risk #5) — but `normalize_role` on the display path + `roles.user` i18n fallback covers badge rendering. The `platform_stats` field rename must land in this same PR as the backend change (S1.8) to avoid `undefined` in the admin dashboard.

---

### S1.12 — Test fixtures + e2e/a11y persona shim (FR-A11Y-02/03)

- **Goal:** make the suite role-collapse-aware: conftest defaults → `user`, e2e personas backed by `{user,admin}`, legacy seed shim.
- **Files:** `apps/backend/tests/conftest.py` (`make_user` `role=Role.student` → `Role.user` at `:227`; `auth_headers` `_login(role=Role.student)` → `Role.user` at `:276`); frontend Playwright storage-state setup + any `student@`/`teacher@` → `user` shim; rename role-coded test names to capability-neutral.
- **TDD steps:**
  1. This task is itself test-infra; verification = the full suite stays green. Add `tests/test_conftest_defaults.py::test_make_user_defaults_user_role` asserting the fixture default is `Role.user`.
  2. **Impl:** flip conftest defaults; keep an explicit `role=Role.instructor` override available only for the S1.6 legacy-principal test; map `student@`/`teacher@` seeds to `user` accounts for e2e; keep 3 storage states → 3 personas (admin, authoring user, learning user).
  3. **Green:** `make test.api` + `make test.web` + Playwright.
- **Migrations:** none.
- **Acceptance:** Given the suite, When run with collapsed roles, Then green; 3 personas all `{user,admin}`-backed; no test hard-codes `student`/`instructor` except the deliberate legacy-tolerance test.
- **Risk/notes:** conftest "force-clears the Settings cache after env-var overrides" (CLAUDE.md) — preserve that. Don't break the seeded demo accounts' login (CHARTER credentials table) — they keep emails, gain `user` role.

---

### S1.13 — Release-3 cleanup: narrow enum to `{user,admin}`, remove `is_instructor_or_admin` (evidence-gated)

- **Goal:** after positive-evidence drain (R-C5′), remove the transition scaffolding (FR-RBAC-05).
- **Files:** `app/models/user.py` (drop `student`/`instructor` from `Role`; remove `is_instructor_or_admin:67-68`); `app/mcp/principal.py` (drop deprecated `is_instructor:96-97`); `app/mcp/server.py` (remove the `auth=="instructor"` legacy branch + `mcp.role.instructor_required`); `app/mcp/tools.py:574` (drop the `is_instructor_or_admin` docstring ref); tighten Pydantic `Role` accept-set; remove `normalize_role` legacy-mapping (or keep as defensive). Add CI grep-guard test `tests/test_no_legacy_role_refs.py`.
- **TDD steps:**
  1. **Failing test** `tests/test_no_legacy_role_refs.py::test_no_instructor_or_student_refs` — grep the `app/` tree for `Role.instructor`, `Role.student`, `is_instructor_or_admin`, `.is_instructor` (MCP) outside an allow-list (none after cleanup) → fail until removed (mirrors ADR-0025 open-risk #2 grep-guard).
  2. **Positive-evidence precondition** (operational, encoded as a deploy gate, not a unit test): a query proving zero `role IN ('student','instructor')` rows AND no legacy MCP principals AND ≥15-min token TTL elapsed since Phase C deploy.
  3. **Impl:** remove the legacy enum members + methods + branches; the suite (now all `{user,admin}`) stays green.
  4. **Green.**
- **Migrations:** none (Release-3 is code-only narrowing per ADR-0025 — no DB change).
- **Acceptance:** Given the evidence gate passed, When the enum narrows, Then no legacy-role reference remains in `app/`, the grep-guard test passes, and the suite is green.
- **Risk/notes:** **This task only merges after the live positive-evidence gate passes in prod (Phase D).** In local/CI it can be staged on a branch but the deploy order is Phase A (S1.1 widen) → backfill 0031 → Phase C (S1.8/S1.10–S1.12 narrow+normalize) → **Phase D (this task)**. Removing `is_instructor_or_admin` while a straggler `student` row exists would crash ORM load (open-risk #1) — the grep-guard + evidence query are the guards. Keep `Principal.is_instructor` until this task (it resolves legacy principals during A–C).

---

## Stream-level gate (done = all of these)

**Unit / integration (backend):**
- `make test.api` green, including: `test_capabilities.py`, `test_deps_capabilities.py`, the `user`-role-can-author tests across `courses`/`ai_authoring`, `test_suspended_user_cannot_create_course`, the MCP user-can-author + ingest-closed + legacy-instructor tests, `test_content_ingest` closed-for-all negative test (FR-SEC-02), `test_jwt_role_inert.py` (FR-MIG-04), `test_migration_role_collapse.py` (0031 idempotent + no-op down, 0032 default), `test_admin_stats` admins/authors, `test_set_user_role_rejects_legacy_values`, `test_no_legacy_role_refs.py` (after S1.13).
- No test asserts the removed `courses.forbidden` / `mcp.writes.instructor_required` codes.

**Unit (frontend):** `make test.web` + `tsc --noEmit` + eslint green; `Role` union is `"user"|"admin"` with no `"student"`/`"instructor"` literal in non-test source; studio/command-palette/site-header gates inverted; admin/users union + Select fixed; i18n parity test (S7 owns i18n keys but parity must hold for any S1-added keys).

**Live-as-a-user browser check (Gate C, post-`make up`) — covers all S1 surfaces, all three personas (memory: post-deploy visual must cover auth-gated paths):**
1. Sign in as a **regular `user`** (former student account, e.g. `student@lumen.test` now `role=user`): visit `/studio` → it renders (no redirect to `/dashboard`); create a course via the UI → 201; open the command palette → "Studio" is present; `/dashboard` shows the merged onboarding/author CTA. Screenshot each.
2. As the same `user`, attempt content-ingest UI/endpoint → blocked (403 capability) — ingest stays closed.
3. Sign in as **admin** (`admin@lumen.test`): `/admin/users` renders, role `<Select>` offers only User/Admin; `/admin` stats shows admins/authors (no `undefined`); admin can still edit any course.
4. Sign in as a second `user` and confirm they **cannot** edit the first user's course (ownership preserved).
5. Confirm a stale/`instructor`-claim session (or a freshly demoted account) grants no admin powers in the browser (FR-MIG-04 manifested).

Screenshots attached as evidence (local first; prod after deploy per CHARTER Gate C).

---

## Traceability

**FR:** FR-RBAC-01, -02, -03, -04, -05, -06, -07, -08, -09, -10; FR-MIG-01, -04; FR-ADMIN-05, -06, -07; FR-DEFINE-06 (capability + 401/403 portion), FR-DEFINE-09 (unblocked by studio gate removal); FR-EVAL-03; FR-SEC-02 (ingest stays closed); FR-API-01, -02 (Role-union + stats-field portions); FR-I18N-01 (role/capability keys — keys land here, parity gating in S7); FR-A11Y-02, -03; FR-DOC-01 (ADR-0025).

**Resolutions (R):** R-C4 (irreversible data collapse / no-op down), R-C5 / R-C5′ (wide → narrow+normalize → evidence-gated remove), R-CAP (suspension as the single revocation axis; no per-user capability table), R-M12 (ingest admin-only/flag-off), R-S1″ (capability re-check at *initiation*, REST or worker), R-S10 (suspension = `is_active`). Cross-refs: R-M3′/R-M13′ ORM cascade fix (owned by S7-pre / ADR-0029-account-lifecycle), R-S8′ rollout discipline (mirrored from ADR-0026).

**Design Resolutions (DR):** DR-CAP (capability layer = `app/services/capabilities.py`), DR-12 (phased release-gated migrations, not blind `upgrade head`; 0031/0032 applied per-phase), DR-22 (naming canon), DR-5 (do not `make api-client` — hand-edit `types.ts`; drift check in S7).

**ADR:** ADR-0025 (owns S1 in full — D1 enum, D2 capabilities, D3 deps, D4 create_course ungate, D5 MCP reconcile, D6 JWT inert, D7 phased migration). Cross-refs ADR-0008 (soft-delete), ADR-0026/0028/0029/0030 (downstream consumers of `capabilities.py`).

**Cited source files (ground truth):** `app/models/user.py:19-22,36,67-71`; `app/api/deps.py:66-76`; `app/services/courses.py:69,97,130,344`; `app/api/v1/courses.py` (16 sites), `ai_authoring.py` (6 sites), `content_ingest.py` (4 sites); `app/mcp/principal.py:96-97`, `mcp/server.py:109-115`, `mcp/tools.py:571-577` + ToolSpec `auth` at `:881/890`; `app/core/security.py:42-68`; `app/services/auth.py:58,195`; `app/repositories/users.py:26`; `app/cli.py:151-152`; `app/seeds/demo.py:544,552`; `app/evals/run_baseline.py:159`; `app/api/v1/admin.py:159,171,194-211,391,402-411`; `apps/backend/tests/conftest.py:227,276`; `apps/frontend/src/lib/api/types.ts:3`; studio/dashboard/command-palette/site-header/admin-users frontend sites per CHARTER §6a (+ `site-header.tsx:86,98`); `alembic/versions/...0029` (`down_revision="0028"`, new chain off 0030).


<!-- ===== S2 ===== -->

# Stream S2: Ownership, Visibility, Moderation & Central Authorizer

**Scope authority:** ADR-0026 (`docs/adr/0026-course-visibility-moderation.md`) + DR-3-R2 / DR-18-R2 / DR-10 / DR-13 / DR-15 / DR-22 in `docs/two-role-rebuild/DESIGN-RESOLUTIONS.md` (authoritative on conflict) + design spec §2.5 (migration chain) + REQUIREMENTS-RESOLUTIONS R-S8′/R-C1′/R-C2/R-C6′/R-M9.
**Verified ground truth (2026-06-03):** latest migration is `0029`; the 14-site reader inventory below was confirmed by grep against current source. S2 owns migrations **0033** (visibility/moderation/events) and **0044** (quarantined) per the global linear chain (S1 owns 0030–0032 for role collapse; the design spec resolves visibility to rev 0033).

---

## Preconditions / depends-on (other streams, by Sx)

- **S1 (role collapse & RBAC) — soft dependency, NOT a hard blocker.** S2 must not hard-code `Role.instructor`/`Role.student`. `can_publish_public(user)` (R-CAP: pure function over `User.is_active` + suspension) and the `RequireInstructor → any-authenticated-user` flip on owner endpoints land in S1. S2 writes its capability calls against `visibility.can_publish_public` and `user.is_admin()` only, so it stays green whether S1 has merged or not. **Migration ordering:** 0033 has `down_revision="0032"` (S1's last). If S1 is not yet merged when S2 builds, temporarily chain `down_revision="0029"` and rebase to 0032 before merge — note in the PR.
- **S6 (admin) — consumer, not blocker.** S2 ships the moderation **service functions + admin moderation endpoints + queue** (they are the authority half of this ADR and the only way `approved` is set, so the rollout's flag-flip step is meaningful). S6 layers the richer admin UX (reporting triage UI, badges) on top. S2 ships the minimal admin moderation API + a basic `/admin/moderation` page; S6 enriches.
- **S4 (clone) — downstream consumer.** `can_clone(course, viewer) := is_publicly_listed(course)` lives in `visibility.py` (S2) and is consumed by S4. S2 ships it; S4 imports it. Migration 0033 must precede S4's clone migration (0035) — design spec §2.5 dependency 3.
- **S7 (cross-cutting) — i18n parity, CHANGELOG, OpenAPI contract-drift check (DR-5), CDN/sitemap purge infra note.** S2 adds the i18n keys it needs and a CHANGELOG entry; S7 enforces parity + the contract-drift CI check globally.

---

## Ordered tasks

Order guarantees the stream is green between every task: the grep-guard is committed FIRST as a green no-op (its allowlist covers all 14 sites pre-migration), columns land additive + backfilled (behavior identical), then readers migrate one cluster at a time (guard tightens as each cluster moves into the authorizer), then write-endpoints land behind the OFF flag, then the rollout discipline is documented.

---

### S2.1 — CI grep-guard test `test_no_raw_published_checks` (FIRST commit, before any migration)

**Goal:** Lock the leak so no future agent (or this stream) can re-introduce a raw `status==published` access/discoverability read. This is the authoritative backstop; the hand-list is only a starting map (DR-3-R2).

**Files:**
- create `apps/backend/tests/test_no_raw_published_checks.py`
- (no app change yet — the test passes green against today's tree via the allowlist)

**TDD steps:**
1. Write the test FIRST. It walks `apps/backend/app/` (`.py` files only) and greps each line for the union of patterns:
   - `status == CourseStatus.published` / `status != CourseStatus.published` (regex tolerant of whitespace and `Course.` qualifier)
   - the **string form** `str(...status...) == "published"` (regex `str\(.*status.*\)\s*==\s*["']published["']`) — DR-3-R2's 14th site (`courses.py:313`)
   - the dead phrasings `moderation_state IN (none, approved)` and the `none, approved` / auto-approve-fast-path strings (ADR-0026 open-risk; R-C1′)
   - assert each match's `file:line` is in an explicit `ALLOWLIST` set.
2. Seed `ALLOWLIST` with exactly the **state-machine writes + seeds** (NOT access reads), verified by grep today:
   - `app/services/courses.py` lines in `_VALID_STATUS_TRANSITIONS` + `_transition_status` (`:135,:136,:148,:166`) and the new `visibility.py` predicates (added in S2.3)
   - `app/cli.py:184` (seed write)
   - `app/seeds/demo.py:451`, `app/seeds/agentic_demo.py:270`, `app/seeds/rag_from_scratch_demo.py:347`, `app/seeds/ts_variance_demo.py:367`
   - The allowlist is keyed by **file + a stable marker comment** (`# noqa: published-check — state-machine write`), NOT raw line numbers, so it survives edits. Each allowlisted line must carry that marker; the test asserts marker presence.
3. Run `make test.api -- -k no_raw_published` → **green** (all current matches are allowlisted reads/writes; this is intentional — the 14 readers are about to be migrated and removed from the allowlist as they move).

   > Important nuance: at S2.1 commit time, the 14 **reader** sites are NOT yet in the allowlist and would FAIL. Resolve by having the test, at S2.1, allowlist BOTH the writes AND a clearly-labeled `READERS_PENDING_MIGRATION` block listing the 14 reader sites with marker `# noqa: published-check — PENDING S2.x migration`. Each later reader task **removes** its site from `READERS_PENDING_MIGRATION`. The stream is done only when `READERS_PENDING_MIGRATION` is empty (asserted by S2.12). This keeps the guard green at every commit while ratcheting the leak shut.

**Acceptance criteria:**
- Given the current tree, When the guard runs, Then it passes (writes allowlisted, readers in the pending block).
- Given a developer adds a new `Course.status == CourseStatus.published` access read anywhere outside the allowlist, When CI runs, Then `test_no_raw_published_checks` fails with the offending `file:line`.
- Given the string form `str(course.status) == "published"` is added, Then it is also caught.

**Risk/notes:** Marker-comment allowlist (not line numbers) is the only maintainable approach in a churning codebase. Exclude `tests/` and `alembic/versions/` from the walk. This test must be the literal first commit of S2 (DR-3-R2 mandate).

---

### S2.2 — Migration 0033: `course_visibility_moderation` (additive, backfilled, flag-OFF behavior-identical)

**Goal:** Add `visibility` + `moderation_state` columns, the `moderation_events` table, the consolidated `ix_courses_listed` index, and a one-way backfill that makes `is_publicly_listed ≡ (status==published)` for all existing rows — so old fleet readers and the new authorizer agree (R-S8′ step 1, DR-12).

**Files:**
- create `apps/backend/alembic/versions/2026_07_29_0033-0033_course_visibility_moderation.py`
- edit `apps/backend/app/models/course.py` (add `Visibility`, `ModerationState` enums + columns + index)
- create `apps/backend/app/models/moderation.py` (`ModerationEvent`)
- edit `apps/backend/app/models/__init__.py` (export `ModerationEvent`, `Visibility`, `ModerationState`)

**TDD steps:**
1. Write `apps/backend/tests/test_migration_0033_visibility.py` FIRST:
   - assert a course seeded `status=published, deleted_at=None` backfills to `visibility=public, moderation_state=approved` AND gets exactly one synthetic `moderation_events` row `to_state='approved'`.
   - assert a `status=draft` course backfills to `visibility=private, moderation_state=none` with no synthetic event.
   - assert a soft-deleted (`deleted_at` set) published course backfills to `private/none` (not public — only live-published becomes public).
   - assert columns are NOT NULL with server defaults `private`/`none` after migration; a bare `INSERT` omitting them succeeds (old-fleet INSERT tolerance).
   - (the conftest DB is built from `Base.metadata` / migrations per session — see `tests/conftest.py:54`; this test runs the migration logic against seeded rows.)
2. Implement the model columns exactly per ADR-0026 (`String(20)`, server_default, default), the enums, `ModerationEvent` model, and `__init__.py` exports.
3. Implement the migration ops in order (DR-15 — online index):
   - `op.add_column` visibility/moderation_state as `nullable=True` (instant on PG17, no rewrite).
   - **Batched backfill** in a Python loop (`UPDATE ... WHERE id IN (SELECT id ... LIMIT 1000)`, separate transactions): live-published → `('public','approved')`; else → `('private','none')`. Insert one synthetic `moderation_events` row per backfilled-approved course (`to_state='approved'`, `actor_id=NULL`).
   - `ALTER COLUMN ... SET DEFAULT` then `SET NOT NULL`.
   - `CREATE TABLE moderation_events` + `CREATE INDEX ix_moderation_events_course_id_created_at`.
   - `ix_courses_listed` as `(visibility, moderation_state, status, subject_id, owner_id) WHERE deleted_at IS NULL` via **`CREATE INDEX CONCURRENTLY`** inside `with op.get_context().autocommit_block():` (design spec §2.5 consolidates ADR-0029's `ix_courses_acl` into this one index by appending `owner_id`).
   - **Do NOT drop `ix_courses_status_subject` yet** (DR-15: keep until an `EXPLAIN` on prod-scale data confirms `ix_courses_listed` is used; drop in a follow-on only after verification).
4. `downgrade()`: drop `visibility`, `moderation_state`, `ix_courses_listed`. **Never drop `moderation_events`** (R-C2/R-M9 — audit survives column rollback).
5. `make migrate` locally → green; `make test.api -- -k migration_0033` → green.

**Migrations touched:** `0033` up = additive columns + batched backfill + NOT-NULL + `moderation_events` + `ix_courses_listed` (CONCURRENTLY). down = drop the two columns + `ix_courses_listed` only. **Zero-downtime:** nullable-add → batched backfill (no long lock on a live `courses` table) → defaults+NOT-NULL after backfill (in-flight old-fleet INSERTs covered by default) → CONCURRENTLY index (no write lock). `down_revision="0032"` (S1) — see Preconditions for the temporary-chain fallback.

**Acceptance criteria:**
- Given a live catalog of published courses, When 0033 runs, Then every live-published course is `public+approved` and the public catalog is unchanged (no delisting).
- Given the old fleet image (no knowledge of the columns), When it INSERTs a course, Then the row defaults to `private/none` and the INSERT succeeds.
- Given `downgrade()`, Then `moderation_events` rows still exist.

**Risk/notes:** CONCURRENTLY can leave an INVALID index if it fails mid-build → runbook step to drop/rebuild (ADR-0026 open-risk). Tune the 1000-row batch to current catalog size (verify `SELECT count(*) FROM courses` before prod run). PG17 native enums are deliberately NOT used (matches existing `String(20)` pattern, `course.py:124`).

---

### S2.3 — Central authorizer module `app/services/visibility.py` (pure predicates + SQL clause)

**Goal:** Create the single home for every visibility/discoverability predicate. Nothing reads `status==published` outside this module + the lifecycle machine (DR-3-R2, ADR-0026 §3).

**Files:**
- create `apps/backend/app/services/visibility.py`
- edit `apps/backend/tests/test_no_raw_published_checks.py` (add `visibility.py` predicate lines to the write allowlist via markers)

**TDD steps:**
1. Write `apps/backend/tests/test_visibility_authorizer.py` FIRST, asserting the truth table:
   - `is_publicly_listed(course)` is `True` **iff** `visibility==public AND status==published AND moderation_state==approved AND deleted_at is None`; `none` is NOT listable; any of {private, draft, rejected, delisted, soft-deleted} → `False`.
   - `publicly_listed_sql()` returns a SQLAlchemy `and_(...)` whose result set over a seeded mixed table equals the rows where `is_publicly_listed` is True (parity test: filter in Python vs filter in SQL → identical id sets).
   - `can_view_course(db, course, viewer)`: listed→anyone (incl. anon) True; private draft → owner True, admin True, enrolled-non-owner True (grandfather, R-VIS-13), random user False, anon False.
   - `can_learn_in_course(db, course, viewer)`: owner True on private/draft (self-learn, FR-LEARN-01).
   - `can_enroll(db, course, viewer)` → `(True, None)` for listed or owner-self; `(False, "enrollment.not_available")` otherwise.
   - `can_clone(course, viewer)` == `is_publicly_listed(course)`.
   - `can_publish_public(user)` == `user.is_active and not suspended` (R-CAP).
2. Implement the module. `is_publicly_listed` is a pure function over already-loaded columns (NFR-PERF-2 — no DB, no viewer). `publicly_listed_sql()` is the **only** place the four-column AND is expressed for queries. `retrieval_acl_clause(requesting_user_id)` = `or_(publicly_listed_sql(), Course.owner_id == requesting_user_id)` with the owner branch also `AND deleted_at IS NULL AND status != build_failed` per R-S12 (note: `build_failed` is an S3 enum value — guard defensively with a `getattr`/string compare so S2 stays green if S3 hasn't merged).
3. Add the `# noqa: published-check — central authorizer` markers; update the guard's allowlist; remove `visibility.py` from any pending block (it is a write/canonical-home, not a leak).
4. `make test.api -- -k "visibility_authorizer or no_raw_published"` → green.

**Acceptance criteria:**
- Given a `public+published+approved` course, Then `is_publicly_listed` is True and `can_view_course` is True for an anonymous viewer.
- Given a `public+published+pending_review` course, Then `is_publicly_listed` is False (R-C1′ — `none`/`pending` never list).
- Given the Python predicate and the SQL clause over the same fixture set, Then they select identical course ids.

**Risk/notes:** `can_view_course` here is the *replacement* for `services/courses.py:424`; do not migrate the call sites yet (that is S2.4). The quarantine suppression (`delisted AND reason ∈ {csam,illegal}`) is wired in S2.10 once the `quarantined` column exists — stub `quarantined` defaulting False so S2.3 stays self-contained.

---

### S2.4 — Migrate `can_view_course` to re-export + the detail/lesson reader cluster

**Goal:** Replace the wrong `can_view_course` (`courses.py:432`) and the free-preview string-form reader (`courses.py:313`) with the authorizer. Removes 2 of the 14 sites from `READERS_PENDING_MIGRATION`.

**Files:**
- edit `apps/backend/app/services/courses.py` (`can_view_course` → thin re-export from `visibility.py`)
- edit `apps/backend/app/api/v1/courses.py` (`:313` free-preview gate → `visibility.is_publicly_listed(course)`)
- edit `apps/backend/tests/test_no_raw_published_checks.py` (drop these 2 from pending)

**TDD steps:**
1. Extend `apps/backend/tests/test_courses.py` / `test_archived_access.py` FIRST: a private-but-enrolled archived course is still viewable (grandfather, unchanged behavior); a private draft 404s to a stranger; a published-public course's preview lesson is readable anonymously; a private course's preview lesson is NOT readable by a stranger.
2. Implement: `can_view_course` becomes `from app.services.visibility import can_view_course` (re-export so existing callers at `courses.py:111`, `discussions.py:42`, `api/v1/discussions.py:80/:123` are untouched — ADR-0026 §3). Replace `courses.py:313` `str(course.status)=="published"` with `is_publicly_listed(course)`.
3. Drop both sites from the pending block. `make test.api -- -k "courses or archived or discussion or no_raw"` → green.

**Acceptance criteria:**
- Given an enrolled learner on an archived (now `private`) course, When they open detail, Then they still see it (R-VIS-13 grandfather).
- Given a stranger and a `private+published` course, When they GET it, Then `404 course.not_found` (existence-hiding, FR-VIS-11/R-U1).
- Given the preview-lesson endpoint on a non-listed course, Then a stranger gets 404/forbidden.

**Risk/notes:** Behavior is **identical to pre-migration** for all existing rows because 0033's backfill made every live-published course `public+approved`. This is the R-S8′ step-2 invariant.

---

### S2.5 — Migrate the catalog/repository reader cluster (subject counts, search, `/mine`, MCP search)

**Goal:** Route catalog discoverability through `publicly_listed_sql()`. Removes `repositories/courses.py:47` and `:139` (and the MCP `only_published` consumer) from pending.

**Files:**
- edit `apps/backend/app/repositories/courses.py` (`:47` subject counts; `:139` `search_courses`, rename param `only_published` → `publicly_listed_only`)
- edit `apps/backend/app/api/v1/courses.py:96` (`/mine` keep `publicly_listed_only=False` — owner sees all own)
- edit `apps/backend/app/mcp/tools.py:323` (`only_published=True` → `publicly_listed_only=True`)
- edit `apps/backend/tests/test_no_raw_published_checks.py`

**TDD steps:**
1. Extend `apps/backend/tests/test_catalog_fulltext.py` / `test_catalog_sort.py` / a new `test_catalog_visibility.py` FIRST: a `public+published+approved` course appears in `/catalog`; a `private+published` course does NOT; a `public+published+pending_review` course does NOT; subject-tile counts only count publicly-listed; `/courses/mine` returns the owner's private + pending + public courses.
2. Implement: replace the two repo `status==published` clauses with `publicly_listed_sql()`; rename the param everywhere it is called (catalog `list_courses`, `/mine`, `services/courses.py:78`, MCP). Keep `/mine` and the create-dup path on `publicly_listed_only=False`.
3. Drop the migrated sites from pending. `make test.api -- -k "catalog or mcp or no_raw"` → green.

**Acceptance criteria:**
- Given a `private+published` course, When anyone hits `/catalog`, Then it is absent.
- Given the owner hits `/courses/mine`, Then their private and pending courses are present.
- Given subject tiles, Then the count equals the number of publicly-listed courses in that subject.

**Risk/notes:** The param rename is a contract change inside the backend only (not the HTTP API). Verify `EXPLAIN` uses `ix_courses_listed` on the catalog query (DR-15) before dropping `ix_courses_status_subject` — defer that drop to a maintenance follow-on.

---

### S2.6 — Migrate the enrollment + streaming-tutor + CLI readers

**Goal:** Route enrollment gate, the streaming-tutor slug→id lookup, and the CLI listing through the authorizer. Removes `enrollment.py:91`, `tutor_streaming.py:150`, `cli.py:351` from pending.

**Files:**
- edit `apps/backend/app/services/enrollment.py:91` (`status != published` → `can_enroll(db, course, viewer)`)
- edit `apps/backend/app/api/v1/tutor_streaming.py:150` (slug-lookup gate → `is_publicly_listed`, or use `can_view_course` post-fetch for owner self-learn parity)
- edit `apps/backend/app/cli.py:351` (`status==published` → `publicly_listed_sql()`)
- edit `apps/backend/tests/test_no_raw_published_checks.py`

**TDD steps:**
1. Extend `apps/backend/tests/test_enrollments*.py` + a `test_tutor_streaming_visibility.py` FIRST: enroll on a listed course succeeds; enroll on a `private+published` course → `403 enrollment.not_available` for a stranger but the owner can self-preview-enroll; the streaming tutor 404s a non-listed course for a non-owner.
2. Implement. For `tutor_streaming.py:150`: the current query restricts the slug→id lookup to published; switch to `is_publicly_listed` columns in the WHERE (or fetch the course and call `can_view_course` to preserve owner self-learn on private — choose `can_view_course` since FR-LEARN-01 wants owners to tutor their private courses).
3. Drop the three sites from pending. `make test.api -- -k "enroll or tutor_stream or no_raw"` → green.

**Acceptance criteria:**
- Given a stranger enrolling on a non-listed course, Then `403 enrollment.not_available`.
- Given an owner opening the streaming tutor on their own `private+published` course, Then it works (self-learn, FR-LEARN-01).
- Given the CLI ingest listing, Then only publicly-listed courses are enumerated.

**Risk/notes:** `tutor_streaming.py` is flag-gated by `feature_tutor_streaming` (off by default) — tests must enable it via the Settings cache-clear pattern (`tests/conftest.py` force-clears Settings after env override).

---

### S2.7 — Migrate the RAG/authoring cross-course readers (learning_path ×3, researcher ×2)

**Goal:** Route every cross-course retrieval/planner read through `retrieval_acl_clause(requesting_user_id)` so the RAG owner-branch lets a user's own private courses into their cross-course context while never leaking others' private courses. Removes the final 5 reader sites from pending.

**Files:**
- edit `apps/backend/app/services/learning_path.py:551`, `:613`, `:933`
- edit `apps/backend/app/services/authoring_subagents/researcher.py:246`, `:290`
- edit `apps/backend/tests/test_no_raw_published_checks.py`

**TDD steps:**
1. Write `apps/backend/tests/test_rag_acl_visibility.py` FIRST: seed user A with a private course + a public course, user B with a private course. Retrieval/planner for A returns chunks from A's private + any public course but NEVER B's private course. Researcher catalog-neighbour reads respect the same clause. (These functions take a requesting user context — verify the call signatures carry `user_id`; if not, thread it as part of this task per ADR-0026 §service changes / DR-8 `LLMContext` interop — but only the `user_id` for ACL, not the full BYOK ctx which is S5.)
2. Implement: replace each `Course.status == CourseStatus.published` WHERE with `visibility.retrieval_acl_clause(requesting_user_id)`. The owner branch adds `AND deleted_at IS NULL`; quarantine `AND NOT quarantined` is added in S2.10.
3. Drop all 5 from pending → **pending block is now empty**. `make test.api -- -k "rag_acl or learning_path or researcher or no_raw"` → green.

**Acceptance criteria:**
- Given user A's cross-course planner, When it retrieves, Then A's own private course chunks are eligible and other users' private courses are never returned.
- Given the authoring researcher, Then it only surfaces publicly-listed neighbours + the requesting user's own.
- Given `test_no_raw_published_checks`, Then `READERS_PENDING_MIGRATION` is empty (assert in S2.12).

**Risk/notes:** These functions currently do not all carry a requesting user — `_fallback_recent_published` (learning_path:613, researcher:290) is a generic fallback. Thread the user_id from the caller; for the fallback when there is genuinely no user (pure system context) pass `None` → clause collapses to `publicly_listed_sql()` only. R-S12: the consolidated `ix_courses_listed` trailing `owner_id` covers the owner-branch — verify with `EXPLAIN`.

---

### S2.8 — Migrate admin published-count readers + narrow admin edit (FR-MOD-05)

**Goal:** Route admin stats/reindex counts through `publicly_listed_sql()` where they mean "publicly listed", and narrow `_can_edit_course` so admins cannot mutate non-owned courses via owner-shaped endpoints.

**Files:**
- edit `apps/backend/app/api/v1/admin.py:375` (reindex fan-out — keep as `status==published` *write-trigger* selection OR move to publicly-listed depending on intent: reindex should cover all published incl. private-published for owner RAG, so this one stays a **publish-state** read and is allowlisted, NOT migrated — document the distinction)
- edit `apps/backend/app/api/v1/admin.py:416` (platform-stats `courses_published` count → keep as lifecycle count `status==published` and allowlist it, since the stat genuinely means "published" not "listed"; add a separate `courses_listed` stat via `publicly_listed_sql()`)
- edit `apps/backend/app/services/courses.py:410` (`_can_edit_course` narrow admin branch)
- edit `apps/backend/tests/test_no_raw_published_checks.py` (move `admin.py:375/:416` from pending to allowlist with the lifecycle-stat marker)

**TDD steps:**
1. Extend `apps/backend/tests/test_admin_stats.py` + `test_admin_courses.py` FIRST: platform stats expose both `courses_published` (lifecycle) and a new `courses_listed` (publicly-listed) count; admin cannot `PATCH`/`DELETE` a non-owned course (asserts `403`/`404` — FR-MOD-05) but can still VIEW it.
2. Implement: `_can_edit_course` → `course.owner_id == user.id` only (admins act through moderation endpoints, S2.9). Resolve admin.py:375/:416 per the lifecycle-vs-listed distinction above (these two are genuinely lifecycle counts/triggers, so they are **allowlisted, not leaks** — the grep-guard must accept a `# noqa: published-check — lifecycle stat` marker; DR-3-R2 calls the grep-guard the source of truth, and a lifecycle count is not an access read).
3. `make test.api -- -k "admin_stats or admin_courses or no_raw"` → green.

**Acceptance criteria:**
- Given an admin, When they `PATCH /courses/{id}` on a course they don't own, Then `403`/`404` (FR-MOD-05) and a regression test asserts the block.
- Given platform stats, Then `courses_published` (lifecycle) and `courses_listed` (public) are both present and correct.

**Risk/notes:** This is the one place where ADR-0026's "11 readers" list and DR-3-R2's "14 sites" diverge in intent: admin.py:375/:416 are **lifecycle counts/triggers**, not access reads. Allowlist them with an explicit marker rather than forcing them through `is_publicly_listed` — the grep-guard is the source of truth (DR-3-R2). Document this decision in the ADR-0026 consequences section.

---

### S2.9 — Lifecycle + moderation service functions in `app/services/courses.py` / `visibility.py`

**Goal:** Implement the transition table (ADR-0026 §4): `publish`/`unpublish`/`archive` side-effects + `share`/`unshare`/`resubmit` (owner) + `approve`/`reject`/`delist`/`relist`/`remove` (admin), each writing an `AuditEvent` + (for moderation transitions) a `ModerationEvent`, plus catalog cache-version bump + best-effort embedding re-enqueue on transition-to-listed.

**Files:**
- edit `apps/backend/app/services/courses.py` (`_transition_status` gains atomic force-private side-effects on unpublish/archive; new `share_course`/`unshare_course`/`resubmit_course`; admin `approve_course`/`reject_course`/`delist_course`/`relist_course`/`remove_course`)
- create `apps/backend/app/services/moderation_safety.py` (advisory classifier — deterministic keyword heuristic over title+overview+outcomes, **fail-closed to `pending_review`**, never auto-approves; LLM variant off-by-default)
- edit `apps/backend/app/repositories/courses.py` (helper: `latest_moderation_event(course_id)` for re-approval / quarantine reason)

**TDD steps:**
1. Write `apps/backend/tests/test_moderation_state_machine.py` FIRST, one test per transition row:
   - `unpublish` of a public course → atomic `status=draft, visibility=private, is_featured=False`, `moderation_state` UNTOUCHED (sticky, R-C2), audit `course.unpublish` (+`course.unfeatured`).
   - `share` requires `status==published`; sets `visibility=public, moderation_state=pending_review`; emits `moderation_event(none→pending_review)`; audit `course.shared`; does NOT list (`is_publicly_listed` False).
   - `share` of a course with a prior `approved` event and NO subsequent reject/delist → re-`approved` (R-M9); with a prior reject/delist → `pending_review`.
   - `unshare` → `visibility=private`, moderation_state STICKY (NOT reset to none — corrects spec L457).
   - `approve` → `moderation_state=approved` (lists), cache bump + embedding re-enqueue; `reject` → `rejected`+`visibility=private`; `delist` → `delisted`+`is_featured=False` (not soft-deleted); `relist` only if predicate would hold else `409 course.not_listable`; `remove` (hard) → `deleted_at=now` + `moderation_event`.
   - classifier fail-closed: on classifier exception, `share` lands `pending_review` (never auto-approve).
2. Implement the service functions + the classifier. Each moderation transition: write `AuditEvent` (existing `app/models/audit.py`) + `ModerationEvent`, then `_bump_catalog_cache_version()` (O(1) Redis version key) + best-effort sitemap purge stub + `_schedule_embedding_index` on approve/relist (FR-VIS-17). No DB CHECK constraint — invariants are service+test enforced (R-C2).
3. `make test.api -- -k moderation_state` → green.

**Acceptance criteria:**
- Given a public+approved course, When the owner unshares, Then it becomes `private` and `moderation_state` is unchanged.
- Given a previously-rejected course, When re-shared, Then it returns to `pending_review` (R-M9), and an admin must approve again.
- Given the classifier raises, When a user shares, Then the course is `pending_review`, never `approved` (R-C1′).

**Risk/notes:** `_transition_status` stays the only allowlisted `status==published` *writer* besides `visibility.py`. Cache-version bump uses a Redis key (no Caddy surrogate-key support confirmed — ADR-0026 open-risk; sitemap purge is best-effort, S7 adds the infra note). Classifier is advisory only — assert in a test that it NEVER sets `approved`.

---

### S2.10 — Migration 0044 + quarantine SQL enforcement (DR-18-R2)

**Goal:** Add `courses.quarantined` (single source of truth for the csam/illegal full-quarantine path) and enforce it in BOTH the Python `can_view_course` AND the SQL `publicly_listed_sql`/`retrieval_acl_clause`, so a quarantined owner's frozen-not-deleted course cannot leak via catalog OR RAG retrieval.

**Files:**
- create `apps/backend/alembic/versions/2026_08_15_0044-0044_courses_quarantined.py`
- edit `apps/backend/app/models/course.py` (add `quarantined: bool` col, default False, NOT NULL)
- edit `apps/backend/app/services/visibility.py` (add `AND NOT quarantined` to `publicly_listed_sql`, `retrieval_acl_clause` owner-branch, and `is_publicly_listed`/`can_view_course` Python)
- edit `apps/backend/app/services/courses.py` (`remove_course` sets `quarantined=True` ONLY for `reason ∈ {csam, illegal}`, NOT `severe_abuse`; cleared only by admin)
- edit `apps/backend/app/models/course.py` `__table_args__` (add `quarantined = false` to `ix_courses_listed` partial-index WHERE)

**TDD steps:**
1. Write `apps/backend/tests/test_quarantine.py` FIRST:
   - a quarantined course is invisible in catalog, search, RAG retrieval (even to the owner via retrieval_acl owner-branch), and `can_view_course` returns False even for enrolled learners (full quarantine, R-C6′).
   - `severe_abuse` removal does NOT set `quarantined` — owner keeps view/edit (handled by `can_learn_in_course`/tutor-disable, which reads the latest `moderation_event.reason_code`, NOT the column).
   - quarantine cleared by admin → course re-enters its prior visibility computation.
2. Implement migration 0044 (additive: `ADD COLUMN quarantined BOOLEAN NOT NULL DEFAULT false` — instant on PG17 with a constant default; rebuild `ix_courses_listed` to include `quarantined=false` in the partial WHERE via CONCURRENTLY drop+recreate, or add a sibling predicate — verify EXPLAIN). down = drop column + restore index.
3. Wire `AND NOT quarantined` into all four predicate forms. Update `remove_course` write-path.
4. `make migrate` + `make test.api -- -k quarantine` → green.

**Migrations touched:** `0044` up = add `quarantined` col + index predicate. down = drop col + restore index. **Zero-downtime:** constant-default boolean add is instant on PG17; index rebuilt CONCURRENTLY. `down_revision` = S2's last migration before it (chain after 0043 per design spec §2.5, i.e. `down_revision="0043"`).

**Acceptance criteria:**
- Given a csam/illegal-removed course, Then it is invisible in catalog, search, RAG (incl. owner-branch), and `can_view_course` is False for everyone including enrolled learners (R-C6′ full quarantine).
- Given a severe_abuse-flagged course, Then `quarantined` stays False and the owner retains view/edit (the tutor disable is a separate `moderation_event.reason_code` read — do NOT conflate, DR-18-R2 scope note).
- Given Python `can_view_course` and SQL `publicly_listed_sql` over a quarantined fixture, Then both agree it is hidden (single source of truth).

**Risk/notes:** DR-18-R2 is explicit: `quarantined` is single-source-of-truth ONLY for csam/illegal full-quarantine; `severe_abuse` tutor-disable remains a `moderation_event.reason_code` read. This **supersedes ADR-0026's** `moderation_events`-lookup-in-the-listing-authorizer design (which created two truth sources). The grandfather suppression in `can_view_course` (ADR-0026 §3) keys on `quarantined`, not on a moderation_events JOIN, for the legally-sensitive case.

---

### S2.11 — Feature flag + publish/unpublish/share/unshare/resubmit endpoints + admin moderation endpoints + schemas

**Goal:** Replace PATCH-as-publish with explicit lifecycle/share endpoints (flag-gated for the sharing axis), add admin moderation endpoints, and surface read-only visibility/moderation in schemas with the non-owner redaction contract (FR-VIS-21).

**Files:**
- edit `apps/backend/app/core/config.py` (add `feature_private_publish_enabled: bool = False`, env `FEATURE_PRIVATE_PUBLISH_ENABLED` — DR-13/DR-22 naming canon; NOT runtime_flags table)
- edit `apps/backend/app/core/prod_guards.py` (no-op for S2; the BYOK KEK guard is S5 — leave alone)
- edit `apps/backend/app/api/v1/courses.py` (new `POST /{id}/publish|unpublish|share|unshare|resubmit`; **remove `status` from the PATCH path**)
- edit `apps/backend/app/schemas/course.py` (`CourseUpdate` drop `status`; `CourseListItem`/`CourseDetail` add read-only `visibility`, `moderation_state`; `CourseDetail` add derived `is_publicly_listed`, owner-only `can_publish_public`; add `ShareRequest`, `ModerationActionRequest`)
- edit `apps/backend/app/api/v1/admin.py` (new `GET /admin/courses/moderation-queue` (cursor) + `POST /admin/courses/{id}/approve|reject|delist|relist|remove`)
- edit `apps/backend/app/services/courses.py` (`update_course` no longer transitions status)
- edit `apps/backend/openapi.json` + `apps/frontend/src/lib/api/types.ts` (hand-written — DR-5; add `Visibility`/`ModerationState` unions, do NOT `make api-client`)

**TDD steps:**
1. Write `apps/backend/tests/test_publish_share_endpoints.py` + extend `test_admin_courses.py` FIRST:
   - `POST /publish` (draft→published) works for owner with title+overview+≥1 lesson; `POST /unpublish` reverts atomically.
   - With `FEATURE_PRIVATE_PUBLISH_ENABLED=False`: `POST /share` returns `404`/`403` (flag off) — assert via Settings cache-clear override.
   - With flag ON: `POST /share` on a published course → `pending_review`; non-owner → `403`; anonymous → `401 auth.required`; share without `can_publish_public` → `403 course.publish_public_forbidden`.
   - `PATCH /courses/{id}` with `status` in body → `status` is ignored/rejected (no longer publishes — FR-VIS-08).
   - Admin queue lists only `pending_review`; `approve` lists the course; non-owner non-admin cannot hit moderation endpoints.
   - Serialization: a non-owner viewing a listed course sees `visibility` but NOT internal moderation churn; a non-listed course 404s (FR-VIS-21/R-U1).
2. Implement endpoints + schemas + flag. The share/unshare/resubmit endpoints check `settings.feature_private_publish_enabled` and 404 when off (R-S8′ step 4 gate). Regenerate `openapi.json` in-container (`make openapi`) and hand-edit `types.ts`.
3. `make test.api -- -k "publish_share or admin_courses"` + `make test.web` (types compile) → green.

**Acceptance criteria:**
- Given the flag OFF, When a user calls `/share`, Then `404`/`403` and visibility stays private (no leak window — R-S8′).
- Given the flag ON and an eligible owner, When they share, Then `moderation_state=pending_review` and the course does NOT appear in the public catalog until an admin approves.
- Given `PATCH /courses/{id}` with `{status:"published"}`, Then it does not publish (lifecycle moved to `/publish`).
- Given a non-owner serializing a non-listed course, Then `404` (existence-hiding).

**Risk/notes:** `RequireInstructor` on the owner endpoints flips to any-authenticated-user in S1; S2's endpoints should use the owner check inside the service (`_owned_course`) + `can_publish_public` rather than relying on the role dep, so they are correct regardless of S1 merge order. `types.ts` is hand-written (DR-5) — never `make api-client`; the S7 contract-drift CI check covers `openapi.json` drift.

---

### S2.12 — Frontend two-control Studio + admin moderation page + i18n + catalog/sitemap/ETag + guard-empty assertion

**Goal:** Replace the legacy PATCH-publish button with the two-control model (lifecycle + share), add a minimal admin moderation page, fold visibility into the detail ETag + sitemap, add i18n keys, and assert the grep-guard pending block is empty (stream done condition).

**Files:**
- edit `apps/frontend/src/app/studio/draft/[courseId]/page.tsx` (replace `Courses.patch(courseId,{status:"published"})` at `:66` with `/publish`,`/unpublish` lifecycle control + a separate Share control calling `/share`,`/unshare`, surfacing `pending_review`/`approved`/`rejected`/`delisted` copy; remove the legacy `PublishAnywayButton` PATCH path)
- create `apps/frontend/src/app/admin/moderation/page.tsx` (queue + approve/reject/delist/relist/remove with confirm-on-remove; inert-text rendering FR-MOD-13)
- edit `apps/frontend/src/lib/query/keys.ts` (add `moderationQueue`, `courseModeration`; invalidate `catalog`/`subjects`/`course`/`myCourses` on mutations)
- edit `apps/frontend/src/app/sitemap.ts` (enumerate only publicly-listed)
- edit `apps/backend/app/api/v1/courses.py` `_course_detail_etag` (`:57-65`) to incorporate `visibility+moderation_state+status`
- edit `apps/frontend/src/lib/i18n/messages/en.ts` + `ar.ts` (keys per ADR-0026 §frontend; `ar` stubs `translation_status: mt-draft`)
- edit `apps/backend/tests/test_no_raw_published_checks.py` (assert `READERS_PENDING_MIGRATION` is empty)

**TDD steps:**
1. Backend: extend `test_course_detail_etag.py` FIRST — ETag changes when `visibility`/`moderation_state` changes; assert `test_no_raw_published_checks` `READERS_PENDING_MIGRATION == set()`.
2. Frontend: add/extend a Vitest test for the two-control Studio (lifecycle toggles call `/publish`/`/unpublish`; Share control disabled until published; share calls `/share`). i18n parity test (`en`/`ar` key sets match — S7 enforces globally, S2 adds keys).
3. Implement components, sitemap filter, ETag, query-key invalidations, i18n.
4. `make test.web` + eslint + `tsc` → green; `make test.api -- -k "etag or no_raw"` → green.

**Acceptance criteria:**
- Given a published private course in Studio, Then the owner sees a Share control (enabled) and toggling it calls `/share`, showing "Pending review".
- Given the sitemap, Then it lists only publicly-listed courses.
- Given the detail ETag, Then it changes when visibility/moderation changes (cache correctness).
- Given the grep-guard, Then `READERS_PENDING_MIGRATION` is empty — all 14 reader sites migrated or explicitly allowlisted-as-lifecycle.

**Risk/notes:** Auth-gated surfaces (Studio, /admin/moderation) must be captured signed-in per the post-deploy-visual-coverage memory. Sitemap/CDN purge at the edge is unconfirmed (ADR-0026 open-risk) — the O(1) cache-version bump from S2.9 is the fallback.

---

## Stream-level gate (done criteria)

**Unit/integration (all green via `make test.api` + `make test.web`):**
- `test_no_raw_published_checks` green AND `READERS_PENDING_MIGRATION` empty (the leak is structurally shut — DR-3-R2 backstop).
- `test_migration_0033_visibility`, `test_quarantine` (0044), `test_visibility_authorizer` (Python≡SQL parity), `test_moderation_state_machine` (every transition row), `test_publish_share_endpoints` (flag-gated), `test_rag_acl_visibility` (no cross-user private leak), `test_catalog_visibility` all green.
- Backend full suite (`make test.api`, xdist `-n 4`, ~3 min) green; `tsc` + eslint + `make test.web` green.

**Live-as-a-user browser check (Gate C, local then prod) — covering S2 surfaces signed-in:**
1. `make up`; seed; sign in as a **user**. Build/own a course → `POST /publish` via the Studio lifecycle control → confirm it does NOT appear in `/catalog` (private+published). Toggle Share → confirm "Pending review" and still absent from catalog (flag must be ON for this check; verify with flag OFF that Share is unavailable — R-S8′ step-4 gate).
2. Sign in as **admin** → `/admin/moderation` → approve the pending course → confirm it now appears in `/catalog`, in search, in the sitemap, and the RAG tutor can cite it cross-course.
3. As a **second user**: confirm the first user's still-private course is invisible in catalog/search and 404s on direct URL (existence-hiding); confirm a cross-course tutor query never surfaces the other user's private content.
4. As **admin**: hard-remove a course with reason `csam`/`illegal` → confirm it vanishes from catalog AND becomes inaccessible even to a previously-enrolled learner (full quarantine, R-C6′); hard-remove with `severe_abuse` → confirm owner keeps view/edit but tutor is disabled.
5. Screenshots of every authenticated surface (Studio two-control, /admin/moderation, catalog before/after approve) attached as Gate C evidence.

**Rollout proof (R-S8 4-step):** A documented runbook entry (in the deploy runbook + ADR-0026) showing the 4-step sequence — (1) deploy 0033 additive+backfill with authorizer, flag OFF → catalog unchanged; (2) confirm all readers on authorizer; (3) grep-guard green + pod drain; (4) flip `FEATURE_PRIVATE_PUBLISH_ENABLED=true` — with a test/asserted invariant that no non-default visibility is writable before step 4.

---

## Traceability

- **ADR:** ADR-0026 (course-visibility-moderation) primary; touches ADR-0029 (RAG-retrieval-ACL — consolidated `ix_courses_listed` index, `retrieval_acl_clause`); ADR-0025 (role-vs-capability — `can_publish_public`/R-CAP). ADR-0030 (account-lifecycle) only at the read-time-provenance / grandfather seam (S2 provides `can_view_course`; ADR-0030 consumes).
- **DR (DESIGN-RESOLUTIONS, authoritative):** DR-3-R2 (14-site reader inventory + grep-guard FIRST + both `==` and string forms + allowlist writes/seeds), DR-18-R2 (0044 `quarantined` col + SQL/Python single source of truth + index + csam/illegal scope, supersedes ADR-0026's moderation_events-lookup), DR-10 (archived semantics / unarchive→pending_review), DR-13 (`feature_private_publish_enabled` env flag, not runtime_flags), DR-15 (CONCURRENTLY indexes + EXPLAIN before dropping `ix_courses_status_subject`), DR-22 (naming canon: `feature_private_publish_enabled`).
- **Requirements (REQUIREMENTS-RESOLUTIONS):** R-S8′ (4-step flag-gated zero-downtime rollout), R-C1′ (canonical predicate ANDs `==approved`, classifier advisory-only never auto-approves), R-C2 (no DB CHECK, sticky moderation_state, append-only `moderation_events` survives down-migration), R-C6′ (grandfather + full quarantine for csam/illegal, severe_abuse edit-only), R-M9 (re-approval via moderation_events history), R-M1 (discussions inherit authorizer), R-CAP (`can_publish_public` = pure function over is_active/suspension), R-U1/R-VIS-11 (404 existence-hiding), R-VIS-13 (grandfathered enrollment access), R-S12 (RAG owner-branch + index coverage).
- **FR:** FR-VIS-01..05, 07..19, 21, 22 (visibility columns, predicate, share/unshare/publish/unpublish endpoints, catalog filtering, ETag, sitemap, redaction); FR-MOD-01..09, 14, 15 (moderation state machine, queue, approve/reject/delist/relist/remove, FR-MOD-05 narrow admin edit, FR-MOD-06 resubmit, FR-MOD-13 inert text); FR-LEARN-01 (owner self-learn on private via `can_learn_in_course`); FR-TUTOR-01/02/04 (visibility branch in tutor/streaming reads); FR-AUDIT-01/02 (publish/unpublish/share/moderation audit actions); FR-MIG (additive zero-downtime migrations 0033/0044).


<!-- ===== S3 ===== -->

# Stream S3: AI goal-intake → private course build

Canon read: CHARTER.md (v2 decisions 2,3,5,8), DESIGN-RESOLUTIONS.md (DR-1, DR-4, DR-8, DR-22 authoritative), design spec §2.1/§2.5/§4.1/§5.1, ADR-0025/0026/0027/0030, REQUIREMENTS-RESOLUTIONS (FR-DEFINE-01..18, FR-PRIV-01/02, FR-LEARN-01, R-M8′, R-M10, R-G1, R-G8, R-S1″, R-S9, R-S10). All code citations verified against source on 2026-06-03.

## Preconditions / depends-on (other streams, by Sx)

- **S7-pre (foundation) — HARD dep:**
  - `app/core/secrets_crypto.py` (envelope field-encrypt: `encrypt(bytes)->bytes`, `decrypt(bytes)->bytes`, `key_version`) + KEK Settings + boot guard. **Verified absent today** (`grep secrets_crypto` → 0 hits). S3's `learning_briefs.source_goal_enc` (R-G8/FR-PRIV-01) requires it. **DR-22 is explicit: the brief field-encryption reuses `secrets_crypto` shipped in S7-pre and does NOT depend on the BYOK KEK migration (0038).** If S7-pre's crypto is not yet merged when S3 starts, gate the encryption behind a thin `secrets_crypto` shim with the same interface so S3 stays green; do not block on S5.
  - `app/services/capabilities.py::can_author(user)` + `RequireAuthor` dep + `auth.capability` error code (FR-DEFINE-06). S3 consumes these; if S1 hasn't landed them, S3 stubs `can_author = user.is_active` locally and rewires when S1 merges.
- **S1 (role collapse) — soft dep:** `can_author` default-on for all active users; the studio student-redirect removed (FR-RBAC-09). S3's `/dashboard` entry point and `RequireAuthor` guards assume the collapse. Migrations 0030–0032 precede 0037 in the chain but are schema-orthogonal.
- **S2 (visibility) — HARD dep for two seams:**
  - `Course.visibility` column + `visibility.py` central authorizer (migration 0033). S3 sets `visibility=private` on build (FR-DEFINE-11) and owner self-learn calls `can_learn_in_course` (FR-LEARN-01). Until 0033 lands, S3 cannot set `visibility`; sequence S3 strictly after S2's 0033.
  - `is_publicly_listed`/`retrieval_acl_clause` so private build drafts are excluded from research/catalog/search (FR-DEFINE-18 regression assertions). The researcher subagent's catalog-neighbour query must already route through the authorizer (S2 migrates `researcher.py:246/290`).
- **S4 (clone) — shared column:** `Enrollment.is_self` lands in migration **0035** (S4). S3's owner self-enroll (FR-LEARN-01) and cert suppression (R-M8′) need it. **Ordering: 0035 (S4 provenance/is_self) precedes the S3 self-enroll task.** Per design-spec §7 step 4, "`can_learn_in_course` + `Enrollment.is_self` (needs 0035)". S3 may land `learning_briefs` (0037) and elicitation/build before self-enroll; the self-enroll task is the only S3 task that waits on 0035.
- **S5/DR-8 (LLMContext) — soft dep:** goal-intake is a user-initiated foreground call → BYOK per R-S1″. S3 threads a `LLMContext` (or `metered_user_id` if `LLMContext` not yet shipped) into elicitation + build metering. Land S3 on the existing zero-arg `get_provider()` + `metered_user_id` path; rewire to `ctx` when S5/DR-8 merge (FR-BYOK-02 lists goal-intake as a call site). Not a blocker.

## Ordered tasks

Order keeps the stream green: model+migration → schema → service (elicitation) → endpoints → brief→build threading → build lifecycle (failed/cancel) → self-learn → beat sweeps → frontend.

---

### S3.1 — `LearningBrief` model + `learning_briefs` migration (0037)
One-line goal: persist the server-owned, immutable-once-finalized brief with field-encrypted raw goal text.

**Files:**
- create `apps/backend/app/models/learning_brief.py`
- change `apps/backend/app/models/__init__.py` (re-export `LearningBrief`)
- create `apps/backend/alembic/versions/2026_..._0037-0037_learning_briefs.py`
- create `apps/backend/tests/test_learning_brief_model.py`

**TDD steps:**
1. FIRST write `test_learning_brief_model.py`: assert (a) a `LearningBrief` row persists with `owner_id`, `finalized_at IS NULL` on create; (b) `source_goal_enc` round-trips through `secrets_crypto.encrypt/decrypt` and the **raw goal text never appears in `repr(brief)` or `str(brief)`** (FR-PRIV-01); (c) structured fields (`goal_summary`, `level`, `prior_knowledge`, `time_budget_hours`, `sessions_per_week`, `desired_outcomes` JSONB list, `format_prefs` JSONB, `language`, `suggested_subject`) load/store; (d) index `(owner_id, created_at)` present via `inspect`.
2. Implement model per design-spec §2.1: `id` nanoid PK (IdMixin), `owner_id` FK→users `ondelete="CASCADE"`, `created_at`/`finalized_at` (`DateTime(timezone=True)`, finalized nullable), `source_goal_enc` (`LargeBinary`/BYTEA), structured columns as listed; `__repr__` that omits goal text.
3. Write migration: `create_table` + `ix_learning_briefs_owner_created`. Green: `make migrate && make test.api -k learning_brief`.

**Migrations touched:** **0037** `learning_briefs`. `down_revision` = the prior rev in the global linear chain (per design-spec §2.5: the chain is 0030→…→0037; verify the immediate predecessor at build time — chain head today is **0029**, so the S3 rev attaches after S1/S2/S6/S4 land their 0031–0036). up: `create_table` + index. down: `drop_index` + `drop_table` (clean, reversible). Zero-downtime: new table, invisible to old pods (additive). Encryption depends only on `secrets_crypto` (DR-22), not the BYOK KEK migration.

**Acceptance criteria:**
- Given a finalized brief row, When loaded, Then `finalized_at` is set and every structured field deserializes.
- Given any serialization/log of a `LearningBrief`, When inspected, Then the plaintext goal never appears (only `source_goal_enc` bytes).

**Risk/notes:** Times are `DateTime(timezone=True)` (CLAUDE.md). FK CASCADE here is correct (brief is the owner's private content, hard-cascades on physical delete — but self-serve delete is anonymize-in-place per R-M3′, so the cascade rarely fires). Keep model/schema separate (CLAUDE.md Pydantic-v2 gotcha). Do not add the brief to any cross-user RAG index (FR-PRIV-01).

---

### S3.2 — Brief Pydantic schemas + level/time enums
One-line goal: DTOs for elicitation turns and the finalized `BriefOut`, plus the `BriefLevel` enum.

**Files:**
- create `apps/backend/app/schemas/learning_brief.py`
- create `apps/backend/tests/test_learning_brief_schema.py`

**TDD steps:**
1. FIRST `test_learning_brief_schema.py`: assert `GoalStartRequest{goal: str(min_length=1,max_length=4_000)}`; `GoalTurnRequest{message}`; `GoalTurnResponse{session_id, assistant_message, accumulated_brief: BriefDraft, turns_used, turns_remaining, converged: bool}`; `BriefFinalizeRequest{edits: BriefDraft|None}`; `BriefOut` carries `id, level, time_budget_hours, prior_knowledge, desired_outcomes, finalized_at` but **NOT** the raw goal text (FR-PRIV-01). `BriefLevel` ∈ {beginner, intermediate, advanced} maps 1:1 to `Difficulty`. `model_validate`/`ConfigDict(from_attributes=True)`.
2. Implement schemas with `ConfigDict(extra="forbid")` on request bodies.
3. Green: `make test.api -k learning_brief_schema`.

**Migrations:** none.

**Acceptance criteria:**
- Given `BriefOut.model_validate(brief_row)`, When serialized with `model_dump(mode="json")`, Then no `source_goal_enc` / raw goal field is present.
- Given a `GoalStartRequest` with empty goal, Then `ValidationError`.

**Risk/notes:** `BriefLevel`→`Difficulty` mapping is the seam DR-4 needs at build time; define it here as a pure `_difficulty_from_level()` to be imported by the orchestrator (S3.6).

---

### S3.3 — Elicitation service: bounded multi-turn convergence + finalize→immutable
One-line goal: `services/learning_brief.py` orchestrates the bounded clarification conversation and the immutable finalize.

**Files:**
- create `apps/backend/app/services/learning_brief.py`
- create `apps/backend/app/repositories/learning_briefs.py`
- create `apps/backend/tests/test_learning_brief_service.py`

**TDD steps:**
1. FIRST `test_learning_brief_service.py` (against real Postgres per conftest; stub the LLM provider with a deterministic `NoopProvider`-style fake that returns canned JSON):
   - `start_session(db, user, goal)` → creates an in-progress brief row (`finalized_at IS NULL`), encrypts goal into `source_goal_enc`, returns session state.
   - `take_turn` enforces the **6-assistant-turn per-conversation cap** (R-G1/FR-DEFINE-02): the 7th turn raises `AppError(code="define.turn_cap")`.
   - convergence: when level + time_budget + prior_knowledge + ≥1 outcome are all present, `take_turn` returns `converged=True` and asks for confirmation (FR-DEFINE-02 "asks only for fields still missing").
   - `finalize(db, user, session_id, edits)` sets `finalized_at`, applies `edits` once, returns the brief; a SECOND `finalize` on the same row raises `AppError(code="define.brief_finalized")` (immutability, FR-DEFINE-03).
   - un-finalized briefs are mutable (FR-DEFINE-08): `take_turn` after start mutates accumulated fields.
   - **session cap (R-M10):** a per-user elicitation-session quota per window (default from `Settings.define_elicitation_sessions_24h`, R-G1) — creating session N+1 in-window raises `AppError(code="define.session_quota")`. Test injects N existing in-window briefs and asserts the (N+1)th `start_session` is rejected.
2. Implement: reuse the shared LLM infra — `llm_service.get_provider()` + `call_logged(...)` (verified pattern at `authoring_orchestrator.py:484-496`), `feature="goal_elicitation"`, metered with `user_id` (FR-DEFINE-02 "metered through `call_logged`"). System prompt is **learner-author voice** (FR-DEFINE-10): "help a self-directed learner define a course for themselves." Convergence is a deterministic field-completeness check in Python (not trusted to the model). Repository: `create_brief`, `get_active_session`, `count_sessions_in_window`, `finalize_brief`.
3. Green: `make test.api -k learning_brief_service`.

**Migrations:** none.

**Acceptance criteria:**
- Given a started session, When the user sends a 7th message, Then `define.turn_cap` and no LLM call is made.
- Given convergence + `finalize`, Then `finalized_at` is set and all structured fields persist (UC-3 AC).
- Given a finalized brief, When `finalize` is called again, Then `define.brief_finalized` (422) and the row is unchanged.
- Given a user at their session quota, When `start_session`, Then `define.session_quota` (429).

**Risk/notes:** Celery is best-effort in dev — but elicitation is in-request (no broker). The convergence check must be deterministic so tests are reproducible (the fake provider returns fixed JSON). Goal text enters build prompts (allowed, FR-PRIV-01) but never a cross-user index. Reuse `call_logged` exactly — do not invent a parallel metering path (R-M7′ quota guard lives there, S5/DR-11).

---

### S3.4 — Goal-intake endpoints (start / turn / finalize)
One-line goal: REST surface for the elicitation flow, `RequireAuthor`, rate-limited, metered.

**Files:**
- create `apps/backend/app/api/v1/goal_intake.py`
- change `apps/backend/app/api/router.py` (register router under `/api/v1/ai`)
- create `apps/backend/tests/test_goal_intake_api.py`

**TDD steps:**
1. FIRST `test_goal_intake_api.py` (uses `auth_headers` fixture):
   - `POST /ai/goal/start` 401 anonymous (FR-DEFINE-06/FR-ANON-01), 403 suspended (`is_active=False`), 200 for active user; returns `session_id`.
   - `POST /ai/goal/{session}/turn` advances; at cap returns 429-ish `define.turn_cap` in the `{error:{code,...}}` envelope (CLAUDE.md error contract).
   - `POST /ai/goal/{session}/finalize` returns `BriefOut` with `brief_id`; cross-user finalize of another user's session → 404 (existence-hide).
   - slowapi rate limit present on `start`/`turn` (FR-QUOTA-04 "goal-intake submit").
2. Implement thin handlers delegating to `learning_brief` service; `@limiter.limit(...)` per `ai_authoring.py:167` pattern; `user: RequireAuthor`.
3. Green: `make test.api -k goal_intake`.

**Migrations:** none.

**Acceptance criteria:**
- Given anonymous, When `POST /ai/goal/start`, Then 401, no row created (FR-ANON-01).
- Given a suspended user, When `POST /ai/goal/start`, Then 403 `auth.account_suspended`/capability, no LLM call.
- Given finalize, Then response carries `brief_id` (UC-3).

**Risk/notes:** Error envelope is `{error:{code,message,details,request_id}}` via `AppError` subclasses (CLAUDE.md). 401 anonymous vs 403 suspended distinction is testable and required (FR-DEFINE-06). Register under `/api/v1/ai` (sibling of the `/studio/ai/*` authoring routes), not `/studio` — define entry is learner-facing (FR-DEFINE-09).

---

### S3.5 — Seed reserved "Personal / Self-directed" Subject (idempotent)
One-line goal: a reserved Subject so self-serve build never hard-fails on the admin-only subject taxonomy (FR-DEFINE-12).

**Files:**
- create `apps/backend/alembic/versions/2026_..._00XX-personal_subject_seed.py` (data-only, in the S3 segment of the chain) OR fold into the 0037 migration's `op.bulk_insert`
- change `apps/backend/app/seeds/demo.py` (idempotent upsert of the Personal subject)
- change `apps/backend/app/core/config.py` (`personal_subject_slug: str = "personal-self-directed"`)
- create `apps/backend/tests/test_personal_subject_seed.py`

**TDD steps:**
1. FIRST `test_personal_subject_seed.py`: assert the migration/seed creates exactly one live Subject with slug `personal-self-directed`; running the seed twice does not create a duplicate (idempotent, NFR-MIG-3).
2. Implement idempotent insert (`INSERT … ON CONFLICT (slug) DO NOTHING` in the migration; `get_or_create` in the seed).
3. Green: `make migrate && make seed && make test.api -k personal_subject`.

**Migrations touched:** data-only insert (fold into **0037** or a small follow-on rev). up: insert-if-absent. down: `DELETE WHERE slug='personal-self-directed' AND no live courses reference it` (guarded; subject FK is RESTRICT). Zero-downtime: data-only, additive.

**Acceptance criteria:**
- Given a fresh DB after migrate, Then exactly one `personal-self-directed` Subject exists.
- Given the migration runs twice (re-run safety), Then no duplicate.

**Risk/notes:** `Subject.slug` is already `unique` (`course.py:58`), so `ON CONFLICT` is safe. This is the FR-DEFINE-12 escape from `authoring.subject_not_found`. Real taxonomy assignment happens at publish time (S2/S6 moderation), not build.

---

### S3.6 — Thread the finalized brief into `draft_course` (DR-4): difficulty, outcomes, estimate, prompts
One-line goal: replace hardcoded `Difficulty.beginner`, derive module/lesson estimate from `time_budget_hours`, feed level/time/outcomes into outliner+critic; auto-resolve subject.

**Files:**
- change `apps/backend/app/services/authoring_orchestrator.py` (`draft_course` signature, `_persist_outline`, `_call_outliner`, `_call_critic`, `_call_reviser`, `_call_final_critic`, subject resolution)
- change `apps/backend/app/services/learning_brief.py` (export `_difficulty_from_level`, `estimate_counts(time_budget_hours)`)
- change `apps/backend/tests/test_authoring_orchestrator.py` (update pinned behavior — FR-DEFINE-18)
- create `apps/backend/tests/test_authoring_brief_constraints.py`

**TDD steps:**
1. FIRST update `test_authoring_orchestrator.py` (FR-DEFINE-18 "consciously updated, not silently drifted") + new `test_authoring_brief_constraints.py`:
   - `draft_course(db, user=..., brief_id=<finalized>)` sets `Course.difficulty` from `brief.level` (e.g. `level=advanced` → `Difficulty.advanced`), **NOT** `beginner` (asserts the `authoring_orchestrator.py:1146` hardcode is gone).
   - `Course.learning_outcomes == brief.desired_outcomes` (FR-DEFINE-04b).
   - module/lesson target derives from `time_budget_hours` via `estimate_counts` (FR-DEFINE-16): assert a low budget → fewer modules, high → more (deterministic bands, e.g. ≤5h→2-3 modules, 6-20h→3-5, >20h→5-8).
   - the outliner + critic **prompts include explicit constraint lines** (level, time budget, outcomes): assert via a spy on the fake provider's received messages that the rendered prompt contains the level + budget tokens (DR-4 "the critic scores the outline against the budget").
   - subject auto-resolution: a build with a `suggested_subject` that matches no live Subject attaches to `personal-self-directed` and does **NOT** raise `authoring.subject_not_found` (FR-DEFINE-12).
   - `visibility=private` + `status=draft` on the built course (FR-DEFINE-11) — depends on S2's `visibility` column (0033).
   - `brief_id` linkage recorded on the course/draft trace (FR-DEFINE-18).
2. Implement:
   - Change `draft_course(db, *, user, brief_id: str)` (replace `brief: str` + `subject_slug: str`). Load the finalized brief; decrypt goal once into the in-request `brief_text` used for prompts; raise `define.brief_not_finalized` if `finalized_at IS NULL`.
   - `_persist_outline`: `difficulty=_difficulty_from_level(brief.level)` (replaces line 1146 `Difficulty.beginner`); `learning_outcomes=brief.desired_outcomes`; `visibility=Visibility.private` (S2).
   - Subject resolution: match `brief.suggested_subject`→live Subject by slug/title; fallback to `personal-self-directed` (never 404 for self-serve, FR-DEFINE-12).
   - Prompt builders: add constraint lines to `_call_outliner`/`_call_critic`/`_call_reviser`/`_call_final_critic` system or user message ("Target level: {level}. Time budget: {hours}h → aim for ~{n} modules. Required outcomes: …"). Rewrite "the instructor pasted a brief" → learner-author voice (FR-DEFINE-10).
3. Green: `make test.api -k "authoring_orchestrator or authoring_brief_constraints"`.

**Migrations:** none (consumes 0037 + S2's 0033 `visibility`).

**Acceptance criteria:**
- Given a finalized brief with `level=advanced, time_budget_hours=30`, When build runs, Then `course.difficulty == advanced` and module count lands in the high band (FR-DEFINE-04a/16).
- Given `suggested_subject` with no live match, When build runs, Then the course attaches to `personal-self-directed`, no 404 (FR-DEFINE-12).
- Given the built course, Then `visibility=private`, `status=draft` (FR-DEFINE-11).
- Given the outliner prompt, Then it contains the level + time-budget constraint text (DR-4).

**Risk/notes:** The orchestrator "commits its own course rows but not the outer transaction" (verified docstring `:666-670`) — keep that contract. Existing tests pin `Difficulty.beginner` and `subject_not_found` (verified at `:1146`, `:680-683`) — FR-DEFINE-18 mandates conscious update, so edit those assertions, don't delete the tests. The decrypted goal text lives only in the in-request prompt builder, never logged (FR-PRIV-01) — `_record_trace` already stores `brief[:240]` summaries; switch trace `prompt_summary` to use `goal_summary` (non-sensitive) not the raw decrypted goal.

---

### S3.7 — `build_failed` state + re-runnable + idempotent build endpoint
One-line goal: a failed build leaves a flagged `build_failed` course (never a silent half-course); re-submitting the same `brief_id` while in flight does not start a second build.

**Files:**
- change `apps/backend/app/models/course.py` (add `build_failed` to `CourseStatus` enum — String(20), no DDL)
- change `apps/backend/app/services/authoring_orchestrator.py` (wrap pipeline; on unrecoverable failure set `status=build_failed`; concurrency cap + daily quota; idempotency)
- create/extend `apps/backend/app/api/v1/goal_intake.py` (`POST /ai/courses/draft` with `Idempotency-Key`) or extend `ai_authoring.py` draft endpoint
- change `apps/backend/app/core/config.py` (`define_build_concurrency: int = 1`, `define_build_quota_24h: int`)
- create `apps/backend/tests/test_build_failed_state.py`, `apps/backend/tests/test_build_idempotency.py`

**TDD steps:**
1. FIRST tests:
   - `test_build_failed_state.py`: inject an outliner failure (fake provider returns unparseable JSON twice) → the course row ends `status=build_failed` (or is cleanly soft-deleted), the API returns a **normalized, user-safe error** (no raw model output, FR-DEFINE-15), and the course is excluded from catalog/search/research (it's `build_failed`, so `retrieval_acl_clause` excludes it per R-S12). Re-running the build for the same brief succeeds and flips the course back to `draft`/`published`-eligible (FR-DEFINE-15 re-runnable).
   - `test_build_idempotency.py`: two concurrent `POST /ai/courses/draft` with the same `brief_id` (or same `Idempotency-Key`) → only ONE build starts (`define.build_in_flight` on the second, FR-DEFINE-15); quota consumed only on successful start, not on validation rejection (FR-DEFINE-15).
   - per-user concurrency cap (default 1, FR-DEFINE-13): a second concurrent build by the same user → `define.build_in_flight`/429.
   - daily build quota (non-dollar, FR-DEFINE-13): N+1 builds in 24h → `define.build_quota`.
   - suspended user → 403, no build (FR-DEFINE-06).
2. Implement:
   - Add `CourseStatus.build_failed = "build_failed"` (enum value, String(20), no migration — design §2.2 closes ADR-0029 risk #1).
   - Wrap `draft_course` body in try/except: on `AppError(authoring.outliner_failed)` or unrecoverable mid-run failure, set the persisted course `status=build_failed` and re-raise a normalized error; the trace records the failure step.
   - Concurrency cap + quota: DB-backed COUNT of in-flight builds (courses owned by user in a transient `building` marker / or a small `build_jobs` guard) — reuse the cost-meter/quota pattern; the hard backstop is the pre-dispatch DB COUNT (aligns with DR-11). Idempotency keyed on `(user_id, brief_id)` in-flight check; accept `Idempotency-Key` header (CLAUDE.md: idempotency planned, S4 ships the `idempotency_keys` table at 0036 — S3 can use the in-flight `(user,brief)` guard if 0036 hasn't landed).
3. Green: `make test.api -k "build_failed or build_idempotency"`.

**Migrations:** none for the enum (String(20) column already holds it). If the in-flight guard needs a column, reuse status; otherwise lean on S4's `idempotency_keys` (0036).

**Acceptance criteria:**
- Given an outliner double-failure, When build runs, Then the course is `build_failed` (or soft-deleted), error is normalized (no vendor/model leakage, FR-DEFINE-15), and it's invisible to catalog/search/research.
- Given a re-submit of a failed brief, Then the build retries without manual deletion (FR-DEFINE-15).
- Given two in-flight builds for the same `brief_id`, Then exactly one runs; quota charged once on successful start only.

**Risk/notes:** `build_failed` must be added to `retrieval_acl_clause`'s owner-branch exclusion (`status != build_failed`, R-S12) — coordinate the literal with S2; if S2 already shipped the clause referencing only `deleted_at`, file a one-line follow-up so the owner's failed drafts don't leak into their own cross-course RAG. The normalized-error requirement reuses the existing `authoring.outliner_failed` 502 mapping (verified `:738-741`). Quota is non-dollar (FR-DEFINE-13) because BYOK $0 calls bypass the dollar guard — DB COUNT is the real backstop (DR-11).

---

### S3.8 — `POST /me/courses/{id}/cancel-build` (DR-1a)
One-line goal: an explicit cancel that marks an in-flight/abandoned build `build_failed` and flags it for cleanup.

**Files:**
- change `apps/backend/app/api/v1/courses.py` (or a new `/me/courses` handler) — add `cancel_build`
- change `apps/backend/app/services/courses.py` (service: owner-or-admin check, transition to `build_failed`, audit)
- create `apps/backend/tests/test_cancel_build.py`

**TDD steps:**
1. FIRST `test_cancel_build.py`:
   - owner `POST /me/courses/{id}/cancel-build` on an in-flight/own draft → 200, course `status=build_failed`, flagged for sweep (FR-DEFINE-14a).
   - non-owner → 404 (existence-hide).
   - anonymous → 401.
   - idempotent: a second cancel on an already-`build_failed` course → 200, no duplicate audit (NFR-OBS-3 idempotent).
   - an audit event is written (FR-DEFINE-14 "all cleanup is audited and observable").
   - cooperative-cancel signal: if a streaming/build worker is running, `cancel-build` sets the flag the phase-fence checks (R-S10) — assert the course is marked so a subsequent build-phase check aborts.
2. Implement: service fn re-checking ownership, transitioning to `build_failed`, writing `AuditEvent` (best-effort embedding/notification swallow per NFR-OBS-3).
3. Green: `make test.api -k cancel_build`.

**Migrations:** none.

**Acceptance criteria:**
- Given the owner of an in-flight build, When `POST /me/courses/{id}/cancel-build`, Then `status=build_failed`, flagged for cleanup, audited.
- Given a non-owner, Then 404.
- Given a re-cancel, Then idempotent (200, no duplicate audit).

**Risk/notes:** Cooperative cancellation (R-S10): the build/clone job checks `is_active`/cancel flag at phase boundaries — wire a `assert_build_not_cancelled` fence into the orchestrator's per-step loop (cheap DB re-read of `status`). This is the S3 contribution to the cross-cutting R-S10 checklist (design §9 residual gap 9). Route lives under `/me/courses` (owner-scoped), not `/admin`.

---

### S3.9 — Owner self-learn on private draft + self-enroll (FR-LEARN-01, R-M8′)
One-line goal: the owner can learn from their own private/draft course; self-enroll is marked `is_self` and suppresses certificates.

**Files:**
- change `apps/backend/app/services/enrollment.py` (`_maybe_issue_certificate`: early-return on `enrollment.is_self`; add `enroll_self` path)
- change `apps/backend/app/services/courses.py` or `enrollment.py` (owner self-learn routes through `can_learn_in_course`)
- create `apps/backend/tests/test_owner_self_learn.py`
- extend `apps/backend/tests/test_enrollment.py` (cert suppression)

**TDD steps:**
1. FIRST tests:
   - `test_owner_self_learn.py`: owner of a `visibility=private, status=draft` course can start learning (lesson progress, tutor) via `can_learn_in_course` returning True for the owner (FR-LEARN-01) — depends on S2's `can_learn_in_course`. A non-owner cannot (404).
   - cert suppression (R-M8′): an `Enrollment` with `is_self=True` that completes all lessons does **NOT** mint a certificate/badge (assert `_maybe_issue_certificate` early-returns); a normal learner enrollment (`is_self=False`) still mints.
2. Implement: `_maybe_issue_certificate` gains `if enrollment.is_self: return` at the top (verified target `enrollment.py:60`, R-M8′). `enroll_self(db, user, course)` creates an `Enrollment(is_self=True)` (the column lands in S4's 0035 — gate this task after 0035). Owner self-learn read path delegates to `visibility.can_learn_in_course`.
3. Green: `make test.api -k "owner_self_learn or enrollment"`.

**Migrations:** consumes **0035** (`Enrollment.is_self`, S4). No new migration.

**Acceptance criteria:**
- Given a private draft owner, When they open the learn surface, Then `can_learn_in_course` is True and lessons render (FR-LEARN-01).
- Given a self-enrollment completes, Then no certificate is issued (R-M8′).
- Given a real learner enrollment completes, Then a certificate is issued (regression intact).

**Risk/notes:** Hard-blocked on S4's `Enrollment.is_self` (0035). Cert suppression is the shared seam consumed by both clone self-enroll (S4) and owner self-learn (S3) — design §8 resolution 12. `can_learn_in_course` is S2-owned; if S2 hasn't shipped it, S3 stubs `viewer == course.owner_id or viewer.is_admin()` and rewires.

---

### S3.10 — Beat tasks: `sweep_orphaned_build_drafts` + `sweep_unfinalized_briefs` (DR-1b)
One-line goal: two idempotent Celery beat sweeps reaping abandoned build drafts and un-finalized briefs after a retention window.

**Files:**
- create `apps/backend/app/workers/tasks/define_sweep.py`
- change `apps/backend/app/workers/celery_app.py` (register module in `include` + two `beat_schedule` entries)
- change `apps/backend/app/core/config.py` (`orphan_build_draft_retention_days: int = 30`, `unfinalized_brief_retention_days: int = 30`)
- create `apps/backend/tests/test_define_sweep.py`

**TDD steps:**
1. FIRST `test_define_sweep.py` (drive the async `_sweep_*` helpers directly, mirroring `test` access to `tutor_sweep._sweep_async`):
   - `sweep_orphaned_build_drafts`: a `build_failed`/draft course never opened by its owner (no `LessonProgress`, no last-viewed) older than 30d → soft-deleted (`deleted_at` set); a draft opened/edited recently is left alone (FR-DEFINE-14b). Idempotent: re-running doesn't double-process (already-`deleted_at` skipped).
   - `sweep_unfinalized_briefs`: a `LearningBrief` with `finalized_at IS NULL` older than 30d → reaped (deleted/soft-deleted); a finalized brief and a recent un-finalized one are left alone (FR-DEFINE-14b, DR-1b).
   - both audit/log the cleanup count (FR-DEFINE-14 observable).
2. Implement using the verified `tutor_sweep` pattern: `@celery.task(name="define.sweep_orphaned_build_drafts.v1", bind=True, max_retries=0)` wrapping `asyncio.run(_sweep_*_async())`, `make_worker_engine()` + `async_sessionmaker`, batched `LIMIT … FOR UPDATE SKIP LOCKED`, dispose engine in `finally`.
3. Register in `celery_app.py`: add `"app.workers.tasks.define_sweep"` to `include`; two `beat_schedule` entries (`crontab(hour="4", minute="30")` daily, off-peak alongside the existing 3-4am sweeps).
4. Green: `make test.api -k define_sweep`.

**Migrations:** none.

**Acceptance criteria:**
- Given a build draft never opened by its owner >30d old, When the sweep runs, Then it's soft-deleted (`deleted_at` set), audited (FR-DEFINE-14b).
- Given an un-finalized brief >30d old, When the sweep runs, Then it's reaped; finalized briefs untouched (DR-1b).
- Given the sweep runs twice, Then idempotent (no double-action).

**Risk/notes:** Celery is best-effort in dev (CLAUDE.md) — the sweep must be idempotent against empty/no-orphan state (mirror the `tutor_sweep` comment). Background beat uses the **platform** model context (DR-8: "Background beat passes PLATFORM") — these sweeps make no LLM calls, so no BYOK concern. "Never opened by the owner" needs a definition: use absence of any `LessonProgress` for that owner+course AND `created_at` age (simplest verifiable signal). Retention configurable (R-G1: 30d default).

---

### S3.11 — Frontend: define → build → learn flow
One-line goal: the learner-author UX — `/dashboard` entry, multi-turn goal intake, brief review, build progress, then learn.

**Files:**
- create `apps/frontend/src/app/learn/define/page.tsx` (or `/dashboard/define`) — canonical define entry (FR-DEFINE-09)
- create `apps/frontend/src/components/define/{GoalIntakeChat,BriefReview,BuildProgress}.tsx`
- change `apps/frontend/src/app/dashboard/page.tsx` ("Create a course to learn" CTA)
- change `apps/frontend/src/components/shared/command-palette.tsx` (define command)
- change `apps/frontend/src/lib/api/endpoints.ts` (goal start/turn/finalize, `POST /ai/courses/draft`, cancel-build; wire dead `AI.draftCourse` `:413` to the live learner entry per FR-DEFINE-05)
- change `apps/frontend/src/lib/api/types.ts` (BriefDraft, BriefOut, GoalTurnResponse — hand-written per DR-5, NO `make api-client`)
- change `apps/frontend/src/lib/query/keys.ts` (`goalSession`, `brief`)
- change `apps/frontend/src/messages/en.ts` + `ar.ts` (all new keys, both files — FR-I18N-01)
- create `apps/frontend/tests/define-flow.test.tsx` (Vitest) + extend Playwright a11y spec

**TDD steps:**
1. FIRST Vitest `define-flow.test.tsx`: the goal-intake chat renders accumulated brief, posts turns, surfaces the turn cap, and the brief-review form requires explicit confirm before build (FR-DEFINE-07 "build starts only on explicit confirmation"). `i18n-parity.test.ts` must pass (en/ar key-set equality, FR-I18N-01).
2. Implement the three components + dashboard CTA; reuse `CourseDraftTrace` for build progress (FR-DEFINE-17); aria-live on the chat (FR-A11Y-01). Build-progress shows the estimate (module/lesson count from time budget) + "a private course will be created" note (FR-DEFINE-16). On build done → deep-link to `/learn/[slug]` (define→build→learn).
3. Green: `make test.web`; `tsc`; eslint; then `make up` + Playwright axe-core WCAG 2.2 AA on goal-intake, brief-review, build-progress (FR-A11Y-01).

**Migrations:** none.

**Acceptance criteria:**
- Given a user on `/dashboard`, When they click "Create a course to learn", Then the goal-intake flow opens without navigating to `/studio` (FR-DEFINE-09).
- Given convergence, When the user reviews and confirms the brief, Then a build starts (never auto, FR-DEFINE-07) and progress renders via the trace timeline (FR-DEFINE-17).
- Given build success, Then the user is deep-linked into the learn surface for their private course.
- Given axe-core on every new surface, Then zero WCAG 2.2 AA violations (FR-A11Y-01).

**Risk/notes:** `types.ts` is hand-written (DR-5) — do NOT `make api-client`; update it in the same PR as the endpoints and rely on the CI drift check. All instructor-framed copy rewritten to learner-author voice (FR-DEFINE-10). The dead `AI.draftCourse` binding at `endpoints.ts:413` is verified present and must be wired live (FR-DEFINE-05). Keep server/client split + primitives (memory: design pivot pattern). i18n: flat dotted keys in both `en.ts`+`ar.ts`.

---

## Stream-level gate (done = all true)

**Unit / integration (all green via `make test.api` + `make test.web`):**
- Brief model field-encrypts the goal and never leaks it in repr/serialization (S3.1, FR-PRIV-01).
- Elicitation enforces the 6-turn cap AND the per-user session quota (S3.3, R-M10); finalize is immutable (S3.3, FR-DEFINE-03).
- `draft_course` derives difficulty from `brief.level` (no `Difficulty.beginner` hardcode), outcomes from the brief, module/lesson estimate from `time_budget_hours`, and the outliner/critic prompts carry the constraints (S3.6, DR-4); subject auto-resolves to Personal (no `subject_not_found`, FR-DEFINE-12); built course is `visibility=private, status=draft` (FR-DEFINE-11).
- `build_failed` state + re-runnable + idempotent (same `brief_id` in flight → no second build) + non-dollar concurrency/quota caps (S3.7, FR-DEFINE-13/15).
- `POST /me/courses/{id}/cancel-build` transitions to `build_failed`, audited, idempotent, 404 non-owner, 401 anonymous (S3.8, DR-1a/FR-DEFINE-14a).
- Owner self-learn on a private draft works; `is_self` enrollment suppresses certs (S3.9, FR-LEARN-01/R-M8′).
- `sweep_orphaned_build_drafts` + `sweep_unfinalized_briefs` reap >30d artifacts idempotently (S3.10, DR-1b/FR-DEFINE-14b).
- Regression: private build drafts excluded from research/catalog/search (S3.6, FR-DEFINE-18); 401 anonymous / 403 suspended on every define/build endpoint (FR-DEFINE-06/FR-ANON-01).
- en/ar i18n parity passes; axe-core WCAG 2.2 AA clean on every new surface (S3.11, FR-I18N-01/FR-A11Y-01).

**Live-as-a-user browser check (`make up`, sign in as the authoring/learning persona — memory: post-deploy visual must cover auth-gated paths):**
1. Sign in as a `user`, open `/dashboard`, click "Create a course to learn."
2. Type a fuzzy goal ("I want to get good at React"), run the multi-turn clarification, watch the running brief accumulate, hit the turn cap deliberately to confirm the bounded behavior, review + tweak the brief, confirm.
3. Watch the build progress (researcher→outliner→critic→reviser→lesson-drafter→final-critic) render in the trace timeline; confirm the estimate note showed before build.
4. Land on the private course, confirm `visibility=private`, open the learn surface, confirm the owner can study their own draft and the tutor answers; complete it and confirm NO certificate is minted (self-enroll).
5. Trigger a build failure (e.g. provider down) and confirm a clean `build_failed` surface (no half-course, normalized error), then re-run and confirm recovery.
6. Cancel an in-flight build via the UI and confirm the course flips to `build_failed`.
7. Confirm the private draft does NOT appear in the public catalog/search as a different anonymous/second user.
Capture screenshots of each surface (define chat, brief review, build progress, learn, build_failed, cancel).

## Traceability

- **FR-DEFINE-01..18** — the whole define-and-build contract: 01/02 (elicitation S3.3/S3.4), 03 (immutable brief S3.1/S3.3), 04+16 (brief→build constraints + estimate S3.6, = **DR-4**), 05/09/10/17 (frontend define→build→learn S3.11), 06 (auth/suspend guards S3.4/S3.7), 07/08 (review-before-build + un-finalized mutability S3.3/S3.11), 11/12 (private-by-default + Personal subject S3.5/S3.6), 13/15 (cost-control + idempotent + re-runnable S3.7), 14 (cancel + sweeps + build_failed S3.7/S3.8/S3.10, = **DR-1**), 18 (pinned-test update + private-exclusion regression S3.6).
- **FR-LEARN-01** — owner self-learn on private draft (S3.9).
- **FR-PRIV-01/02** — brief at-rest field-encryption + no raw goal to admins/cross-user RAG (S3.1, **R-G8**).
- **FR-QUOTA-04** — slowapi on goal-intake submit (S3.4).
- **FR-I18N-01 / FR-A11Y-01** — new surfaces i18n + WCAG 2.2 AA (S3.11).
- **R-M8′** — cert suppression in `_maybe_issue_certificate` on `is_self` (S3.9).
- **R-M10** — elicitation turn cap + session cap (S3.3).
- **R-G1** — quota starting values (build concurrency 1, 6 turns, 30d retention) (S3.7/S3.10).
- **R-S1″ / DR-8** — goal-build is a user-initiated foreground call → BYOK via `LLMContext` (S3.3/S3.6 metering seam; full ctx in S5).
- **R-S10** — cooperative cancellation fence on the build job (S3.8).
- **R-S9** — brief admin-read requires an open linked report (consumed by S6; S3 keeps briefs non-admin-readable by default).
- **DR-1** (cancel-build + two beat sweeps + build_failed), **DR-4** (brief→`draft_course` constraint plumbing replacing `authoring_orchestrator.py:1146`), **DR-22** (brief encryption uses `secrets_crypto`, independent of BYOK KEK 0038).
- **ADR-0025** (capability `can_author` gate), **ADR-0026** (`visibility=private`, `can_learn_in_course`, `build_failed` not listable), **ADR-0027/DR-8** (model-selection locus), **ADR-0029** (`build_failed` in `retrieval_acl_clause`, R-S12), **ADR-0030** (brief CASCADE / anonymize-in-place interaction).
- **Migration 0037** (`learning_briefs`) + Personal-subject seed; consumes **0033** (`visibility`, S2) and **0035** (`Enrollment.is_self`, S4).

Plan file authored from source-verified ground truth; key real paths cited: `apps/backend/app/services/authoring_orchestrator.py:1146` (the `Difficulty.beginner` hardcode DR-4 replaces), `:648-654` (`draft_course` signature), `:678-683` (`subject_not_found` FR-DEFINE-12 removes), `apps/backend/app/services/enrollment.py:60` (`_maybe_issue_certificate` R-M8′ target), `apps/backend/app/workers/celery_app.py:52` (`beat_schedule`), `apps/backend/app/workers/tasks/tutor_sweep.py` (sweep task pattern to mirror), `apps/backend/app/api/v1/ai_authoring.py:413`/`endpoints.ts:413` (dead `AI.draftCourse` to wire). Latest migration head verified = **0029**.


<!-- ===== S4 ===== -->

# Stream S4: Clone / Remix

**Canon read:** CHARTER §3.4 (decision 4) + §3.4 deletion-semantics decision 10; DESIGN-RESOLUTIONS DR-9 (asset copy = download→revalidate→reupload, NOT `CopyObject`), DR-19 (read-time provenance anonymization + ordering: `DELETE /me` only after 0035), DR-6/DR-6-R2 (cascade scope, not S4's job but consumed by deletion), DR-21 (migration chain — S4 owns 0035/0036); ADR-0028 (clone-as-projection, full); design spec §2.5 (migrations 0035 `clone_provenance`, 0036 `idempotency_keys`), §5.4 (clone projection service), §3.2 (`can_clone(course,viewer) = is_publicly_listed`); REQUIREMENTS-RESOLUTIONS / spec FR-CLONE-01..25, FR-DEL-01/03.

**Naming canon note (DR-22 wins over ADR-0028 prose):** the asset worker task is **`media.copy_clone_asset`** (the orchestrating task may be `copy_clone_assets`, per-object helper is `copy_clone_asset`); the migration is **0035** (`clone_provenance`), per DR-21, NOT ADR-0028's stale `0030`. ADR-0028's `uploads.copy_object_validated` (server-side boto3 `copy_object`) is **superseded by DR-9**: use download→re-validate(MIME-sniff + size)→re-upload, because `CopyObject` never exposes bytes to re-sniff (R-S5 requires re-validating copied bytes).

## Preconditions / depends-on (other streams, by Sx)

- **S1 (role collapse)** — `can_clone` is granted to any active `user`/`admin`; `RequireCapability` factory and `capabilities.can_clone` live in **S7-pre + S1** (`app/services/capabilities.py`, `app/api/deps.py`). S4 consumes them. If S1's `RequireAuthor`/`RequireCapability` are not yet present, S4 task S4.6 stubs `RequireCapability(can_clone)` only on the clone route (must not block on S1 for unit tests of the service layer, which call `capabilities.can_clone` directly).
- **S2 (visibility) — HARD dependency.** Clonability = `visibility.is_publicly_listed(course)` and `can_view_course` rewritten to drop the `status==published` first branch (`courses.py:432`). S4 MUST NOT read `status==published`. S2 must have landed: migration **0033** (`courses.visibility`, `moderation_state`), `app/services/visibility.py` with `is_publicly_listed`/`can_view_course`/`can_clone(course,viewer)`, and the grep-guard `test_no_raw_published_checks`. The S4 clone projection materializes `visibility=private, moderation_state=none`.
- **S3 (goal intake → build)** — owns `Enrollment.is_self` *consumption* (owner self-learn) but the **column ships in S4's migration 0035** (design spec §2.5 row 0035, R-M8′). S3 depends on 0035 for its self-enroll. So S4's 0035 must land before S3's self-learn work; the `enroll_self` service helper is shared. Coordinate: **S4 owns `Enrollment.is_self` + `enroll_self` + the `_maybe_issue_certificate` suppression guard**; S3 reuses them.
- **S5 (BYOK / quotas)** — clone embedding/asset work counts against per-user non-dollar quotas. The quota module (`call_logged` COUNT guard, DR-11) is S5. S4 adds its own **clone-specific** quotas (`clone_per_hour`, `clone_owned_cap`, `clone_max_lessons`) which are self-contained Settings + DB COUNT checks — no dependency on S5's LLM quota module.
- **S6 (moderation/account-deletion)** — `delete_account` choreography (anonymize-in-place) calls the provenance-snapshot anonymize step; DR-19 makes anonymization **read-time** so S4's serializer is the real GDPR guard and S6's one-time scrub is belt-and-suspenders. DR-19 ordering: `DELETE /me` enabled **only after 0035** exists — satisfied because 0035 is in S4 and S6 follows.

## Ordered tasks

Order keeps the stream green: model+migrations → projection (pure, no DB) → enroll_self + cert suppression → clone_course service → API/schemas → lazy assets → lazy embeddings + quotas → read-time provenance → frontend. Clone endpoint is **flag-gated OFF (`clone_enabled=False`)** until 0035/0036 confirmed applied (ADR-0028), so partial landings never run clone code against a missing column.

---

### S4.1 — Provenance + `is_self` model columns + `IdempotencyKey` model (no behavior yet)
**Goal:** add the 6 provenance columns to `Course`, `is_self` to `Enrollment`, and the new `IdempotencyKey` model + clone indexes — model-only, so later tasks have schema.

**Files:**
- change `apps/backend/app/models/course.py` (add provenance cols to `Course`; `is_self` to `Enrollment`; add `ix_courses_origin_course_id`, `ix_courses_root_origin` to `Course.__table_args__`)
- create `apps/backend/app/models/idempotency.py`
- change `apps/backend/app/models/__init__.py` (re-export `IdempotencyKey`)

**TDD steps:**
1. FIRST write `apps/backend/tests/test_clone_model.py::test_course_has_provenance_columns` — import `Course`, assert `hasattr(Course, "origin_course_id")`, `origin_owner_id`, `root_origin_course_id`, `origin_title_snapshot`, `origin_owner_name_snapshot`, `cloned_at`; assert all default `None` on a freshly-constructed `Course()`. Assert `Enrollment().is_self is False`. Assert `from app.models import IdempotencyKey` works and `IdempotencyKey.__tablename__ == "idempotency_keys"`. → RED (AttributeError / ImportError).
2. Implement the columns exactly as ADR-0028 §"Data model changes" (provenance: `origin_course_id`/`root_origin_course_id` FK→courses SET NULL; `origin_owner_id` FK→users SET NULL; snapshots String(200)/String(120); `cloned_at` timestamptz; all nullable, indexed where specified). `Enrollment.is_self`: `Boolean, nullable=False, server_default="false", default=False`. `IdempotencyKey` per ADR-0028 (`uq_idem_user_key` unique on `(user_id, idempotency_key)`, `user_id` FK CASCADE, `endpoint` String(80), `response_target_id` String(64) null, `expires_at` timestamptz).
3. GREEN. No migration yet (next task); model+ORM only, this test doesn't hit the DB schema.

**Migrations:** none (model-only).

**Acceptance:** Given the models import, When I construct `Course()`/`Enrollment()`, Then provenance fields are `None` and `is_self` is `False`; `IdempotencyKey` is registered in `app.models.__init__`.

**Risk/notes:** Do NOT add `origin_*` to `CourseCreate`/`CourseUpdate` (S4.5 enforces `extra="forbid"`). Keep the cascade fix (`User.courses_owned` → `save-update`, DR-6) OUT of S4 — that is S7-pre/S6's change; do not touch `user.py:58` here.

---

### S4.2 — Migration 0035 `clone_provenance` + migration 0036 `idempotency_keys`
**Goal:** ship the two additive, zero-downtime migrations (DR-21: 0035 + 0036; down_revision chains from S6's 0034 `course_reports`).

**Files:**
- create `apps/backend/alembic/versions/2026_..._0035-0035_clone_provenance.py`
- create `apps/backend/alembic/versions/2026_..._0036-0036_idempotency_keys.py`

**TDD steps:**
1. FIRST write `apps/backend/tests/test_migration_clone_provenance.py::test_clone_columns_present` — using the session-scoped engine (conftest runs migrations to head), `SELECT column_name FROM information_schema.columns WHERE table_name='courses'` and assert the 6 provenance columns exist; assert `enrollments.is_self` exists with default `false`; assert `idempotency_keys` table exists with `uq_idem_user_key`. Assert indexes `ix_courses_origin_course_id`, `ix_courses_root_origin` exist (query `pg_indexes`). → RED (columns/table absent until migration written).
2. Write 0035: `down_revision="0034"` (S6's course_reports — confirm at implementation; if 0034 not yet merged, chain to the latest landed rev and re-point on rebase). `op.add_column` ×6 on `courses` (all nullable, no table rewrite — PG adds nullable metadata-only); `op.create_foreign_key` for the 3 FKs (`ondelete="SET NULL"`); `op.add_column("enrollments", is_self boolean NOT NULL server_default="false")` (server_default → instant, existing rows = false); indexes via `op.create_index(..., postgresql_concurrently=True)` inside `op.get_context().autocommit_block()` with `DROP INDEX IF EXISTS` for re-runnability (matches migration 0014 GIN pattern). `downgrade()` drops indexes + FKs + columns cleanly (additive ⇒ reversible; DR-21 says both additive/zero-downtime).
3. Write 0036: `down_revision="0035"`; `op.create_table("idempotency_keys", ...)` + unique constraint. `downgrade()` drops the table.
4. GREEN.

**Migrations:** **0035** (up: +6 provenance cols nullable/SET-NULL-FK + `enrollments.is_self` + 2 concurrent indexes; down: drop). **0036** (up: create `idempotency_keys`; down: drop). Zero-downtime: all metadata-only adds; old pods never read/write these (clone code flag-gated OFF). CONCURRENTLY index builds run outside the migration txn.

**Acceptance:** Given `alembic upgrade head`, When I inspect the schema, Then all 6 provenance cols + `enrollments.is_self` + `idempotency_keys` + 2 indexes exist; When I `downgrade` one step at a time, Then it reverses without error.

**Risk/notes:** `down_revision` collision risk — every concurrent stream claims revisions; S4's are **0035/0036** per the design-spec single linear chain. If S6's 0034 hasn't merged when S4 builds, temporarily chain 0035→0033 (S2's visibility) and re-point on integration; the conftest runs the full chain so a wrong link surfaces immediately. CONCURRENTLY in a test DB: SQLite isn't used (backend tests run real Postgres per conftest), so concurrent index DDL is valid.

---

### S4.3 — Sanitized export projection (`clone_projection.py`, pure, no DB/IO)
**Goal:** the security boundary — a frozen whitelist DTO that *structurally cannot* carry forbidden state (FR-CLONE-04/05/06/07).

**Files:**
- create `apps/backend/app/services/clone_projection.py`
- create `apps/backend/tests/test_clone_projection.py`

**TDD steps:**
1. FIRST write `test_clone_projection.py`:
   - `test_projection_field_whitelist` — build `CourseExport` from in-memory `Course`+modules+lessons fixtures (no DB); assert the dataclass field set equals exactly the whitelist `{title, overview, difficulty, learning_outcomes, subject_id, tag_ids, cover_url, modules}` and that `CourseExportLesson` has no `id`, `deleted_at`, `is_preview` (it's forced), no `published_at`, no `owner_id`. Assert there is **no** attribute path from the export to `reviews`/`enrollments`/`lesson_progress`/`lesson_chunks`/`origin_*`.
   - `test_drops_empty_modules` — a module whose every lesson has `deleted_at != None` is dropped (FR-CLONE-05).
   - `test_soft_deleted_lessons_excluded` — a live module's soft-deleted lesson is excluded (explicit `deleted_at IS NULL` filter, mirroring `courses.py:231`).
   - `test_is_preview_forced_false` — a source lesson with `is_preview=True` projects `is_preview=False` (R-M4 / FR-CLONE-04).
   - `test_dense_zero_based_orders` — source orders `[2, 5, 9]` project to `[0, 1, 2]` per module and per lesson, preserving display order (FR-CLONE-05 — satisfies `uq_modules_course_order`/`uq_lessons_module_order` on first INSERT).
   - `test_quiz_data_verbatim_deepcopy` — quiz `data` JSONB (`pass_score`, `questions[]`, `choices[]`, `answer_keys[]`, ids) is `copy.deepcopy`'d identically; mutating the export does not mutate the source (FR-CLONE-06, no id re-mint).
   - `test_counters` — returns `lessons_copied`, `modules_copied`, `modules_dropped` for the audit.
   - `test_size_ceiling` — >`clone_max_lessons` live lessons OR projected `data` byte sum > `clone_max_data_bytes` raises a `CloneSourceTooLargeError` (FR-CLONE-18). → all RED.
2. Implement `build_export_projection(course, modules, lessons, *, max_lessons, max_data_bytes) -> CourseExport` as frozen dataclasses (`CourseExport`, `CourseExportModule`, `CourseExportLesson`), pure, `copy.deepcopy` on lesson `data`, explicit `deleted_at is None` filter, dense re-keying, `is_preview=False`. Raise on size ceiling.
3. GREEN.

**Migrations:** none.

**Acceptance:** Given a source tree with soft-deleted lessons, preview lessons, gappy orders, and a quiz, When I project it, Then forbidden fields are structurally absent, empty modules dropped, orders dense 0-based, `is_preview=False`, quiz data verbatim, and counters correct.

**Risk/notes:** This is the single most security-load-bearing test in the stream (charter §3.4 "whitelist projection makes leakage structurally impossible"). The field-set assertion is a regression tripwire — adding any new `Course`/`Lesson` column will NOT silently leak because the test pins the export field set. Tags are platform-shared: project **tag ids only** (associate existing `Tag` rows by id at materialization, don't deep-copy Tag rows).

---

### S4.4 — `enroll_self` + certificate suppression (`is_self`)
**Goal:** owner self-enroll that bypasses the `status==published` gate, and suppress cert/badge minting on self-enrollment (FR-CLONE-16 / R-M8′).

**Files:**
- change `apps/backend/app/services/enrollment.py` (new `enroll_self`; guard `_maybe_issue_certificate`)
- create `apps/backend/tests/test_enroll_self.py`

**TDD steps:**
1. FIRST write `test_enroll_self.py`:
   - `test_enroll_self_on_private_draft` — `enroll_self(db, user=owner, course=draft_private_course)` returns an `Enrollment` with `is_self=True` despite `status != published` (the `enroll()` gate at `enrollment.py:91` rejects this — proves the bypass). No "Welcome" notification created.
   - `test_enroll_self_idempotent` — calling twice returns the same enrollment (no duplicate; `uq_enrollments_user_course`).
   - `test_self_enrollment_no_certificate` — drive `_maybe_issue_certificate` with `enrollment.is_self=True, total=N, done=N`; assert `completed_at` stays None, `certificate_id` None, `badge_credential` None, **no** `certificate_ready` notification (R-M8′). Compare against a non-self enrollment which DOES mint. → RED.
2. Implement `enroll_self(db, *, user, course) -> Enrollment` — no `status` check, `is_self=True`, idempotent on existing enrollment, skip Welcome notification. Add `if enrollment.is_self: return` at the top of `_maybe_issue_certificate` (after the existing signature).
3. GREEN.

**Migrations:** none (uses 0035's `is_self`).

**Acceptance:** Given a private draft owned by the caller, When `enroll_self` runs, Then an `is_self=True` enrollment exists and completing every lesson mints **no** certificate/badge/notification.

**Risk/notes:** Cert minting lives in `_maybe_issue_certificate` (`enrollment.py:41`), called from both `record_quiz_attempt` and `mark_lesson` — the single guard covers both paths. This helper is **shared with S3** (owner self-learn); keep it self-contained.

---

### S4.5 — Clone schemas: `CourseOrigin`, `origin`/`is_clone` on outputs, `extra="forbid"` immutability
**Goal:** serialize provenance as a structured `origin` object and block provenance smuggling (FR-CLONE-09/10, ADR-0028 §API).

**Files:**
- change `apps/backend/app/schemas/course.py` (new `CourseOrigin`, `CourseClonesItem`; add `origin: CourseOrigin | None` + `is_clone: bool` to `CourseListItem`/`CourseDetail`; `model_config = ConfigDict(extra="forbid")` on `CourseCreate` + `CourseUpdate`)
- create `apps/backend/tests/test_clone_schemas.py`

**TDD steps:**
1. FIRST write `test_clone_schemas.py`:
   - `test_course_create_forbids_provenance` — `CourseCreate.model_validate({...valid..., "origin_course_id": "x"})` raises `ValidationError` (extra forbidden) → maps to 422 at the API.
   - `test_course_update_forbids_extra` — same for `CourseUpdate`.
   - `test_origin_serialization` — given a `Course` with provenance cols set, the `origin` object exposes `{origin_course_id, origin_title, origin_owner_name, origin_owner_id, cloned_at, origin_available}` and `is_clone == (origin_course_id is not None)`.
   - `test_origin_null_when_not_cloned` — a from-scratch course serializes `origin=None`, `is_clone=False`. → RED.
2. Implement `CourseOrigin` (ADR-0028 §Schemas), the builder mapping `origin_title_snapshot→origin_title`, `origin_owner_name_snapshot→origin_owner_name`; `extra="forbid"`. Leave `origin_available` computation as a parameter the builder receives (computed in S4.8 read-time anonymization — default `False` here).
3. GREEN.

**Migrations:** none.

**Acceptance:** Given a POST/PATCH body containing `origin_course_id`, When validated, Then 422; Given a cloned course, When serialized, Then `origin` is populated and `is_clone=True`.

**Risk/notes:** `CourseUpdate` currently carries `status` (`schemas/course.py:210`); S2/FR-VIS-08 *drops* `status` from `CourseUpdate` — that is S2's change. Do not remove `status` here; only add `extra="forbid"`. If S2 already dropped it, no conflict. The `origin_owner_name` value is **snapshot-only** here; S4.8 overrides display at read-time for deleted owners (DR-19).

---

### S4.6 — `clone_course` service + `POST /courses/{key}/clone` endpoint + idempotency
**Goal:** the orchestrator — resolve+authorize (`is_publicly_listed`, 403-vs-404 existence-hide), idempotency, project, materialize atomically with server-written immutable provenance, self-enroll, audit + origin notification (FR-CLONE-01/02/03/11/14/15/19/20/22).

**Files:**
- change `apps/backend/app/services/courses.py` (new `clone_course`)
- create `apps/backend/app/services/idempotency.py` (lookup/record helper, 24h TTL)
- change `apps/backend/app/api/v1/courses.py` (new `POST /{key}/clone`, registered under existing courses router)
- change `apps/backend/app/models/notification.py` (add `course_cloned` `NotificationKind`)
- create `apps/backend/tests/test_clone.py`

**TDD steps:**
1. FIRST write `test_clone.py` (uses `client`, `make_user`, `auth_headers`, `seed_lesson`; build a published-public source via the API + a direct `visibility=public, moderation_state=approved` set, or via S2's publish flow):
   - `test_clone_public_course_creates_independent_copy` — POST `/api/v1/courses/{slug}/clone` → 201 + `Location` header; body `is_clone=True`, `origin.origin_course_id == source.id`, `origin.origin_owner_name == source.owner.full_name`; new course `owner_id=caller`, `status=draft`, `visibility=private`, `moderation_state=none`, fresh slug (not source slug), modules/lessons copied with dense orders.
   - `test_clone_private_source_403_for_viewer_who_can_see` — caller clones their own private draft → 403 `clone.source_not_clonable`.
   - `test_clone_private_source_404_for_stranger` — non-owner clones a private course → 404 `course.not_found` (no existence leak, FR-CLONE-03).
   - `test_clone_anonymous_401` — no auth → 401 `auth.required`.
   - `test_clone_never_copies_forbidden_state` — source has an enrollment, a review, lesson_progress, a soft-deleted lesson, `is_featured=True`, `published_at` set; the clone has **none** of these (new enrollments only = the cloner self-enroll), `is_featured=False`, `published_at=None`, soft-deleted lesson absent (FR-CLONE-07).
   - `test_clone_auto_enrolls_caller_is_self` — caller has an `Enrollment(is_self=True)` on the clone immediately (FR-CLONE-16).
   - `test_self_clone_allowed` — owner clones own *public* course → 201, provenance points at the original (FR-CLONE-15).
   - `test_clone_idempotency_key_returns_same_course` — two POSTs with the same `Idempotency-Key` return the same course id, only one course created (FR-CLONE-20).
   - `test_clone_writes_audit_events` — a `course.cloned` AuditEvent (actor=caller, target=new course) with `data.origin_course_id/lessons_copied/modules_copied/modules_dropped`, plus `course.cloned_by_other` targeting the origin, plus a `course_cloned` notification to the origin owner (FR-CLONE-19).
   - `test_clone_provenance_not_client_writable` — POST a clone, then PATCH the clone with `origin_owner_name_snapshot` in the body → 422 (covered by S4.5 but assert end-to-end here).
   - `test_clone_rolls_back_on_failure` — inject a materialization failure (e.g. monkeypatch `_flush_course_with_slug_retry` to raise after partial insert) → no orphan course persisted (FR-CLONE-22). → all RED.
2. Implement `clone_course(db, *, caller, source_key, ip, user_agent, source_updated_at=None, idempotency_key=None) -> Course` exactly per ADR-0028 §Decision.2: `slug_or_id(with_modules=True)` snapshot → authorize via `visibility.is_publicly_listed` + `can_view_course` for the 403/404 split + `capabilities.can_clone(caller)` → idempotency lookup → optional `source_updated_at` 409 → project (S4.3) → materialize one transaction (fresh `_unique_slug` + `_flush_course_with_slug_retry`, `Course(owner_id=caller.id, status=draft, visibility=private, moderation_state=none, ...)`, set 6 provenance cols server-side, copy tags by id, module→lesson loop with dense pre-computed orders mirroring `ai_authoring.commit_outline`) → `enroll_self` → `audit.record` ×2 + `course_cloned` notification → record idempotency key → return. Endpoint: `RequireCapability(can_clone)` (from S1; if S1 not landed, `CurrentUser` + service-level `can_clone` re-check), `Idempotency-Key` header, `?source_updated_at=`, 201 + `Location`, slowapi-limited (S4.7 wires the quota). Flag-gate behind `settings.clone_enabled` (default `False` → 404 `clone.disabled`).
3. GREEN.

**Migrations:** none (consumes 0035/0036).

**Acceptance:** Given a publicly-listed source, When an authenticated active user POSTs `/clone`, Then a fresh private draft owned by them is created with immutable server-written provenance, they are self-enrolled, audit + origin notification fire, and a same-key retry returns the same course. Given a non-visible source, Then 404; given a visible-but-not-listed source, Then 403.

**Risk/notes:** `enroll()` at `enrollment.py:91` rejects non-published — clone MUST use `enroll_self` (S4.4), never `enroll`. Materialization must NOT use the two-phase reorder dance (dense orders from the projection satisfy `uq_modules_course_order`/`uq_lessons_module_order` on first INSERT — ADR-0028 §1). Use a single transaction so rollback leaves no orphan. The 403-vs-404 split is a security requirement (no existence leak) — test both branches. Never accept `origin_*` from the client (S4.5 `extra="forbid"`).

---

### S4.7 — Clone quotas + amplification caps
**Goal:** bound clone amplification independent of dollar cost — per-user window, owned-course cap, source-size ceiling (FR-CLONE-18 / R-S7 / R-G1).

**Files:**
- change `apps/backend/app/core/config.py` (Settings: `clone_enabled=False`, `clone_per_hour=20`, `clone_per_day=100`, `clone_owned_cap=200`, `clone_max_lessons=500`, `clone_max_data_bytes`, `clone_asset_inline_max=0`)
- change `apps/backend/app/services/courses.py` (`clone_course` pre-flight quota checks)
- change `apps/backend/app/api/v1/courses.py` (slowapi limiter on the clone route)
- change `apps/backend/app/core/errors.py` if a `ClonePayloadTooLargeError`/code is needed (else reuse `ValidationAppError`/`ConflictError`)
- change `apps/backend/tests/test_clone.py` (add quota cases)

**TDD steps:**
1. FIRST add cases:
   - `test_clone_owned_cap` — with `clone_owned_cap` lowered via Settings override, a caller at the live-owned-course cap → 409 `clone.course_limit`.
   - `test_clone_source_too_large` — source exceeding `clone_max_lessons` → 413/422 `clone.source_too_large` (drives the projection ceiling from S4.3 through the endpoint).
   - `test_clone_rate_limited` — exceed `clone_per_hour` → 429 `clone.rate_limited` (DB COUNT over recent `course.cloned` audit rows, or slowapi — assert the code).
   - `test_clone_disabled_flag` — `clone_enabled=False` → 404 `clone.disabled` (no feature-probe). → RED.
2. Implement: DB COUNT guard for the per-user window (count recent `AuditEvent action='course.cloned' actor_id=caller` within the window — independent of dollars, mirrors DR-11 pattern but clone-local) → 429; live-owned-course COUNT → 409; size ceiling surfaces from the projection → 413/422; flag gate → 404. Add the Settings fields with env backing. conftest force-clears the Settings cache after env override (per CLAUDE.md testing notes) — use the existing settings-override fixture.
3. GREEN.

**Migrations:** none.

**Acceptance:** Given a caller at the owned-course cap, When they clone, Then 409; given an oversized source, Then 413/422; given >N clones in the window, Then 429; given the feature flag off, Then 404.

**Risk/notes:** Quotas are **non-dollar** by design (charter decision 5/4, R-S7) — a clone is platform compute/storage, not an LLM call, so it never rides the 24h-dollar guard. Use DB COUNT over audit rows for the window so it survives worker restarts (slowapi is in-memory/Redis and is the fast first line; the DB COUNT is the durable backstop). `clone_max_data_bytes` ceiling computed in the projection (S4.3) — wire its error to the endpoint here.

---

### S4.8 — Read-time provenance anonymization + `origin_available` (DR-19)
**Goal:** render "a deleted user" at READ time when `origin_owner` is deleted (or `origin_owner_id IS NULL`), regardless of whether the one-time snapshot scrub ran; compute `origin_available` by re-resolving `origin_course_id` through `is_publicly_listed` (FR-CLONE-10, FR-DEL-01, DR-19).

**Files:**
- change `apps/backend/app/schemas/course.py` or the response builder (`app/api/v1/_builders.py` / wherever `list_item`/`detail` is built) to compute `origin_available` + anonymized `origin_owner_name`
- change `apps/backend/app/services/courses.py` (helper `resolve_origin(db, course) -> CourseOrigin` doing the read-time resolution)
- change `apps/backend/tests/test_clone.py` (anonymization + availability cases)

**TDD steps:**
1. FIRST add cases:
   - `test_origin_available_true_when_source_listed` — clone whose source is still publicly listed serializes `origin.origin_available=True` with a link.
   - `test_origin_available_false_when_source_unlisted` — source made private/delisted/soft-deleted → `origin_available=False`, link suppressed; snapshot title/owner still render ("Based on … (no longer available)", FR-DEL-01).
   - `test_origin_owner_anonymized_when_deleted` — mark the origin owner as deleted (`User.deleted_at` set / `is_active=False` per ADR-0030 tombstone) WITHOUT running any snapshot scrub → `origin.origin_owner_name` renders the deleted-user sentinel ("a deleted user"), proving read-time anonymization (DR-19, no GDPR gap if deletion happened before 0035).
   - `test_origin_owner_anonymized_when_id_null` — `origin_owner_id IS NULL` (hard purge) → same sentinel. → RED.
2. Implement `resolve_origin` — re-resolve `origin_course_id` and apply `is_publicly_listed` for `origin_available`; if `origin_owner_id IS NULL` OR the origin owner is tombstoned/deleted, override `origin_owner_name` to the deleted-user sentinel at serialize time (the snapshot value is the fallback for live owners). Wire into the `CourseDetail`/`CourseListItem` builder.
3. GREEN.

**Migrations:** none.

**Acceptance:** Given a clone whose origin owner is deleted but the snapshot was never scrubbed, When the clone is serialized, Then `origin_owner_name` reads "a deleted user"; Given the origin course is no longer publicly listed, Then `origin_available=False` and no link.

**Risk/notes:** DR-19 is explicit that anonymization is **read-time, not one-time** — the S6 `delete_account` scrub is belt-and-suspenders, NOT the GDPR guard. The deleted-owner detection must use ADR-0030's tombstone signal (`User.deleted_at IS NOT NULL` or `is_active=False` + tombstone email); confirm with S6/S7-pre which discriminator is canonical (`deleted_at` per design spec §2.2). `origin_available` re-resolution is a single indexed lookup (`ix_courses_origin_course_id`) — acceptable on the detail path; avoid N+1 in list serialization (batch-resolve origins for a page, or accept the cost on detail-only).

---

### S4.9 — Lazy asset re-homing worker (`media.copy_clone_asset`, download→revalidate→reupload)
**Goal:** re-home lesson/cover S3 objects into the cloner's namespace via download→re-validate(MIME+size)→re-upload (DR-9, NOT `CopyObject`), best-effort per object, cooperative-cancel; orphan sweeper (FR-CLONE-12/13/22, R-S5/R-S10/R-G7).

**Files:**
- change `apps/backend/app/services/uploads.py` (new `download_revalidate_reupload(*, src_key, dst_kind, dst_owner_id) -> dict` — `get_object` bytes, re-run `ALWAYS_DENIED_TYPES`/`ALLOWED_PER_KIND`/`MAX_BYTES_PER_KIND` validation on the fetched bytes, MIME-sniff, re-upload to `{kind}/{cloner_id}/{date}/{new_id}/{filename}`, return new key + public_url)
- change `apps/backend/app/workers/tasks/media.py` (new `copy_clone_assets(new_course_id)` orchestrator task calling per-object `copy_clone_asset`; new `sweep_orphan_clone_assets()`; extend the `sweep_unclaimed_assets` stub)
- change `apps/backend/app/services/courses.py` (enqueue `copy_clone_assets.delay(new.id)` after commit; mark URLs `copying`)
- create `apps/backend/tests/test_clone_assets.py`

**TDD steps:**
1. FIRST write `test_clone_assets.py` (against MinIO via the test stack, or a stubbed `_client`):
   - `test_copy_clone_asset_revalidates_bytes` — re-home an allowed image; assert the NEW object lives under the cloner's namespace, a new `Asset(owner_id=cloner)` row exists, and validation ran on the *fetched* bytes (not the source `Asset` row's stored type) — feed a source whose stored `content_type` lies but whose bytes are a denied type → it is NOT re-homed (R-S5).
   - `test_copy_clone_asset_rewrites_lesson_refs` — after the task, the clone's lesson `data.asset_key`/`url`/`captions_url` and `cover_url` point at the new public URLs.
   - `test_copy_missing_object_best_effort` — a source object that 404s → lesson still exists, media ref stripped to a safe placeholder, failure appended to clone audit `data.asset_copy_failures[]`, task succeeds (no 500) (FR-CLONE-13).
   - `test_external_url_left_as_is` — a non-bucket video URL is referenced unchanged.
   - `test_cooperative_cancel_on_suspend` — if `caller.is_active` flips false mid-task, the task aborts at a lesson boundary (R-S10).
   - `test_sweep_orphan_clone_assets` — an Asset in a cloner namespace with no live lesson/cover ref, older than 24h, is dropped (R-G7). → RED.
2. Implement `download_revalidate_reupload` reusing `uploads._client`/`ALLOWED_PER_KIND`/`MAX_BYTES_PER_KIND`/`ALWAYS_DENIED_TYPES` (re-sniff a bounded byte-range for large media per ADR-0028 open-risk). `copy_clone_assets` Celery task on `worker_session_scope` (NullPool, mirroring `embeddings.py:23`), best-effort per object, `caller.is_active` check at each lesson boundary, rewrites refs, appends failures to audit. `sweep_orphan_clone_assets` periodic task. Enqueue from `clone_course` after commit (best-effort, swallow broker errors like `_schedule_embedding_index`).
3. GREEN.

**Migrations:** none.

**Acceptance:** Given a clone with image/file lessons + cover, When `copy_clone_assets` runs, Then each in-bucket object is downloaded, re-validated on its bytes, re-uploaded under the cloner namespace, a new owned `Asset` row created, refs rewritten; a missing object is stripped + recorded without failing the task; the orphan sweeper reclaims rollback debris.

**Risk/notes:** **DR-9 supersedes ADR-0028's `copy_object_validated`** — DO NOT use boto3 `CopyObject` (it never exposes bytes to re-sniff; R-S5 mandates re-validating the copied bytes). Use `get_object` → validate → `put_object`. Lazy by default (`clone_asset_inline_max=0` → always async). Best-effort enqueue mirrors the `_schedule_embedding_index` defensive shape (CLAUDE.md gotcha: Celery best-effort in dev). The task is the *only* place `Asset` rows are minted for clones — never reference the origin author's S3 key (FR-CLONE-12: cascades away on owner delete).

---

### S4.10 — Lazy embeddings (no copy; regenerate on publish / first tutor)
**Goal:** verify embeddings are NEVER copied and regenerate lazily — on first (re)publish via existing `_schedule_embedding_index`, and the fresh-clone-has-zero-chunks state (FR-CLONE-08).

**Files:**
- change `apps/backend/tests/test_clone.py` (embedding-isolation cases)
- (no production change if S2's publish path + ADR-0029's lazy-ingest guard already cover regeneration; S4 only asserts the contract and that clone copies zero chunks)

**TDD steps:**
1. FIRST add cases:
   - `test_clone_copies_zero_chunks` — source has `lesson_chunks`; immediately after clone, the new course has **zero** `LessonChunk` rows (FR-CLONE-08).
   - `test_clone_publish_schedules_index` — transitioning the clone to `published` calls `_schedule_embedding_index(clone.id)` (assert the enqueue, mock the task) — embeddings regenerate on the clone's own publish, against the clone's own lesson ids.
   - `test_clone_chunks_reference_only_own_lessons` — after a (mocked) ingest, chunks reference the clone's lesson ids, never the source's (FR-DEL-03 independence). → RED.
2. Implement: confirm `clone_course` never touches `lesson_chunks`; the projection (S4.3) structurally excludes them. Regeneration rides the existing `_transition_status` → `_schedule_embedding_index` (`courses.py:167`) — no new code unless ADR-0029's lazy-ingest tutor guard is needed (that guard is ADR-0029/S2-RAG, not S4; S4 only asserts the publish-time path).
3. GREEN.

**Migrations:** none.

**Acceptance:** Given a clone of a course with embeddings, When the clone is created, Then it has zero chunks; When the clone is published, Then `_schedule_embedding_index` fires for the clone's id and produces chunks bound only to the clone's own lessons.

**Risk/notes:** CLAUDE.md: the Celery reindex task rebuilds lesson-chunk embeddings on publish (not the tsvector). `LessonChunk` is CASCADE-bound to the origin's lessons (ADR-0028) — copying them would reference a foreign lesson graph and a model+dim mismatch (ADR-0029). The projection's whitelist already excludes them (S4.3 field-set test is the structural guard). Embedding work counting against the cloner's per-user quota is S5's quota module — S4 just enqueues.

---

### S4.11 — Frontend: Clone CTA + origin attribution + query keys + i18n
**Goal:** "Make my own copy" CTA on `CourseCard` + course-detail sidebar (only `viewer && can_clone && is_publicly_listed`), structured "Based on …" attribution, studio "Cloned" badge, on-success route to `/studio/draft/{newId}` (FR-CLONE-25/23/10, FR-DEL-01).

**Files:**
- create `apps/frontend/src/components/course/clone-button.tsx`
- create `apps/frontend/src/components/course/origin-attribution.tsx`
- change `apps/frontend/src/components/course/course-card.tsx` (CTA when clonable; anonymous → sign-in with return path)
- change the course-detail sidebar page (next to Enroll)
- change `apps/frontend/src/lib/query/keys.ts` (add `clone(key)`, `courseClones(key)`)
- change `apps/frontend/src/lib/api/endpoints.ts` + `types.ts` (hand-written per DR-5: add `Courses.clone()`, `CourseOrigin`/`is_clone`/`Visibility`/`ModerationState` to `CourseListItem`/`CourseDetail`) — same PR as the backend endpoint
- change `apps/frontend/src/lib/i18n/messages/en.ts` + `ar.ts` (clone.* keys per ADR-0028, both files for parity)
- create `apps/frontend/tests/clone-button.test.tsx` (Vitest + happy-dom)

**TDD steps:**
1. FIRST write `clone-button.test.tsx` / a `course-card` test:
   - CTA renders only when `viewer && course.can_clone && course.is_publicly_listed`; hidden otherwise.
   - Anonymous click routes to sign-in with `?returnTo` set.
   - On 201 success, routes to `/studio/draft/{newId}` and invalidates `qk.myCourses` + `qk.enrollments`.
   - 429/409/413 → localized error toast (`clone.error.rateLimited` etc.).
   - `origin-attribution` renders a link when `origin.origin_available`, plain "no longer available" text when not; immediate parent only.
   - `i18n-parity.test.ts` passes with the new `clone.*` keys present in both `en.ts` and `ar.ts`. → RED.
2. Implement the components, keys, endpoint client method, and i18n keys (en + ar from ADR-0028 §i18n; `translation_status: human`).
3. GREEN: `make test.web` + eslint + tsc.

**Migrations:** none.

**Acceptance:** Given a publicly-listed course and a signed-in active user, When viewing the catalog/detail, Then a "Make my own copy" CTA shows; When clicked, Then the clone is created and the user lands in `/studio/draft/{newId}` with myCourses/enrollments invalidated; anonymous users route to sign-in.

**Risk/notes:** `types.ts` is **hand-written** (DR-5) — do NOT `make api-client` to regenerate it; hand-edit in the same PR + the CI contract-drift check (S7) guards `openapi.json`. i18n keys are flat dotted in both `en.ts`/`ar.ts`; `i18n-parity.test.ts` gates key-set equality. RTL via logical properties. axe-core WCAG 2.2 AA on the new CTA/attribution surfaces.

---

## Stream-level gate (done criteria)

**Unit/integration (backend, `make test.api`):**
- All S4 tests green: projection whitelist (field-set tripwire), empty-module drop, soft-delete exclusion, `is_preview=false`, dense orders, quiz-verbatim, size ceiling; `enroll_self` bypass + cert suppression; clone create/403/404/401/idempotency/audit/rollback; quotas (429/409/413/disabled); read-time anonymization + `origin_available`; asset download-revalidate-reupload + best-effort + cooperative-cancel + orphan sweep; zero-chunk + publish-schedules-index isolation; `extra="forbid"` immutability.
- Migrations 0035/0036 up+down clean; full suite green under xdist `-n 4` (pytest-infra memory).
- The S2 grep-guard `test_no_raw_published_checks` still passes (clone reads `is_publicly_listed`, never `status==published`).

**Frontend:** `make test.web` + eslint + tsc green; `i18n-parity.test.ts` green; axe-core AA on the clone CTA + origin-attribution + studio badge.

**Live-as-a-user browser check (Gate C, `make up` + Playwright/manual, both en + ar/RTL):**
1. Sign in as an authoring `user`; create + publish a course (with a quiz lesson + a cover image + an image lesson) to public.
2. Sign in as a **second** `user`; on the catalog, see "Make my own copy" on the card; click it; land in `/studio/draft/{newId}`; confirm the clone has the modules/lessons/quiz, fresh title (no "Copy of"), `visibility=private/status=draft`, and the "Based on … by …" attribution with a working link to the source.
3. Confirm media: the clone's cover + image lesson resolve to the **cloner's** namespace URLs (re-homed), not the origin's; verify the new `Asset` rows are owned by the cloner.
4. Edit the clone (rename, add a lesson); confirm the source is unchanged; open the source as the first user and confirm it's untouched (full independence).
5. Tutor on the fresh clone returns `tutor.index_pending` (zero chunks) until publish/index; publish the clone and confirm it goes through the normal publish→pending_review moderation flow (no fork bypass) and chunks build.
6. Self-enroll: confirm the cloner sees progress tracking but completing every lesson mints **no** certificate (self-enroll suppression).
7. As an admin, soft-delete/delist the source; reload the clone detail → attribution reads "Based on … (no longer available)", no link, content intact (FR-DEL-01).
8. Anonymous: clicking the CTA routes to sign-in with return path.
9. Capture screenshots of: catalog CTA, clone-in-progress, the cloned studio draft with "Cloned" badge + attribution, and the deleted-origin "no longer available" state (post-deploy visual must cover these authoring surfaces, per memory).

## Traceability

- **FR:** FR-CLONE-01..25 (full clone surface), FR-DEL-01 (immutable provenance, origin-change resilience, suppressed link), FR-DEL-03 (independent lesson ids → cloner progress survives origin deletion). FR-DEL-02 partial (origin-author-delete delisting hooks into S6's `delete_account`; the snapshot-anonymization read path is S4.8).
- **R (resolutions):** R-M1 (never copy discussions/reviews/enrollments/progress/traces/embeddings), R-M4 (`is_preview=false`), R-M8′ (`is_self` cert suppression), R-M13′ (snapshot anonymize on deletion — implemented read-time per DR-19), R-S5 (re-validate copied bytes), R-S7 (lazy assets/embeddings + amplification quotas), R-S10 (cooperative cancellation), R-G1 (quota numbers), R-G7 (orphan-asset sweeper), R-CAP (`can_clone` = active-user, no per-user storage).
- **DR:** **DR-9** (asset copy = download→revalidate→reupload, `media.copy_clone_asset`), **DR-19** (read-time provenance anonymization + `DELETE /me` ordered after 0035), DR-21 (migrations 0035/0036 in the linear chain), DR-22 (naming canon: `media.copy_clone_asset`, migration name `clone_provenance`). Consumes S2's authorizer (DR-3-R2 leak-site discipline) and S6/S7-pre's cascade fix (DR-6/DR-6-R2 — not changed by S4).
- **ADR:** ADR-0028 (clone/remix — owns this stream); depends on ADR-0026 (`is_publicly_listed`/`can_view_course`), ADR-0025 (`can_clone` capability + `RequireCapability`), ADR-0029 (lazy-ingest tutor guard for the zero-chunk clone), ADR-0030 (account-lifecycle tombstone signal consumed by S4.8 read-time anonymization).
- **Charter:** §3.4 decision 4 (clone = sanitized export projection + immutable provenance), decision 10 (deletion semantics for clone attribution).

**Note for the integrator:** S4's revision numbers (0035/0036), the `Enrollment.is_self` ownership (S4 ships it, S3 consumes), and the `down_revision` link to S6's 0034 are the cross-stream contact points — confirm at integration time. ADR-0028's stale `copy_object_validated`/`copy_object` mechanism and its `0030`–`0032` migration numbers are **overridden** by DR-9 and DR-21 respectively; this plan follows the resolutions.


<!-- ===== S5 ===== -->

# Stream S5: BYOK & model config

Authoritative inputs read: CHARTER §3 decision 5, DESIGN-RESOLUTIONS DR-7/DR-8/DR-11/DR-16/DR-17/DR-22 (R1+R2 win on conflict), ADR-0027, REQUIREMENTS-RESOLUTIONS R-S1″/R-S2/R-S3/R-S4/R-U3/R-U4/R-M7′/R-M11′/R-CAP/R-G1/R-G4. Grounded against `app/services/llm.py:180,200,285,312,460,478`, `llm_stream.py:93,122,159,187`, `llm_call_log.py:197,227`, `models/llm_call.py:80,106`, `core/prod_guards.py:180,199`, `core/logging.py:20,31,73`, `core/badges_keys.py:67`, `core/cost_scripts.py:109,132`, `workers/celery_app.py`, `workers/tasks/learning_path.py:70,130`, `workers/tasks/tutor_streaming.py:97`, `api/v1/learning_path.py:181,271`, `services/learning_path.py:270,423,743,757`, `authoring_orchestrator.py:484,648`, `tutor_orchestrator.py:654`, `tutor_subagents/{concept_explainer.py:110,quiz_generator.py:159}`, `core/config.py:144`, `models/__init__.py`, latest revision = **0029** (so S5 takes **0030–0032** per ADR-0027 §Migrations; if S2 has already claimed 0030–0043, S5 uses the next-free additive numbers — strictly-additive, order-flexible per ADR-0027 §Migrations).

## Preconditions / depends-on (other streams, by Sx)
- **S1 (Role collapse & RBAC)** — soft dep. `can_use_byok(user)` is a pure function over `User.is_active` (R-CAP); no role storage needed, so S5 can land before S1's enum collapse. If S1 ships first, `capabilities.py` may already exist (S5 adds `can_use_byok` to it; create the file if absent — verified **no `app/services/capabilities.py` today**).
- **S7 cross-cutting** — `secrets_crypto` is also used by S3 `learning_briefs` field-encryption per DR-22 ("uses `secrets_crypto` shipped in S7-pre"). **Resolution:** S5 ships `secrets_crypto` as task **S5.1** (it is the BYOK-critical module). If S7-pre wants it earlier it imports from `app.core.secrets_crypto`; do not duplicate. S5 does **not** depend on S7.
- **No dependency on S2 (visibility) or S4 (clone).** Charter §4: "S5 is largely independent."
- **Migration numbering** depends only on the global Alembic chain head at build time (currently 0029). Coordinate the actual revision numbers at PR time; the down_revision must point at whatever head exists then.

---

## Ordered tasks
Each task is independently testable; the stream is green between tasks. Backend tests run against real Postgres+Redis via `conftest.py` (`make_user`/`auth_headers`/`db_session`/`client` fixtures; `get_settings.cache_clear()` after env overrides). Run `make test.api` (xdist `-n 4`, `ENV=test` forced) between tasks.

### S5.1 — `secrets_crypto` envelope-encryption module
Goal: AES-256-GCM envelope crypto (DEK wrapped by versioned KEK) + fingerprint/last4 + rotation primitive — the only place keys are encrypted/decrypted.

- **Files:**
  - create `apps/backend/app/core/secrets_crypto.py`
  - change `apps/backend/app/core/config.py` (add KEK settings)
  - create `apps/backend/tests/test_secrets_crypto.py`
- **TDD steps (write first, must fail):** `test_secrets_crypto.py` asserts:
  1. `encrypt_secret("sk-abc...")` → `EncryptedSecret(enc_key, enc_data_key, key_version)` with `key_version == settings.byok_master_key_version`; ciphertext != plaintext; nonce-prefixed (`len(enc_key) > 12`).
  2. round-trip: `decrypt_secret(*encrypt_secret(p)) == p`.
  3. two `encrypt_secret(p)` calls produce **different** `enc_key` and `enc_data_key` (random DEK + nonces) but `key_fingerprint(p)` is stable across both.
  4. `key_fingerprint(p)` == `hashlib.sha256(p.encode()).hexdigest()` (64 hex); `last4("...wxyz")=="wxyz"`, `last4("ab")=="****"`.
  5. tamper detection: flipping a byte of `enc_key`/`enc_data_key` → `cryptography.exceptions.InvalidTag` on decrypt.
  6. KEK source: with `byok_master_keys={1: <b64 32B>, 2: <b64 32B>}` + `byok_master_key_version=2`, encrypt stamps version 2; `decrypt_secret(..., key_version=1)` still works (uses v1 KEK) — proves multi-version decrypt for rotation.
  7. dev fallback: when no `byok_master_keys` and `ENV != production`, `_active_kek()` returns `(0, sha256(b"lumen.byok.kek.v1:"+secret_key))`, tagged derived (assert via a helper `active_kek_is_derived() is True`); under `ENV=production` with no keys → `RuntimeError`.
  8. `rotate_secret(enc_key, enc_data_key, from_version=1, to_version=2)` returns a new `enc_data_key` wrapped under v2 with **identical** `enc_key` (plaintext key blob untouched) and decrypts to the same plaintext.
- **Implementation:** mirror `badges_keys.py:67` derived-key pattern; use `cryptography.hazmat.primitives.ciphers.aead.AESGCM`. `Settings.byok_master_keys: dict[int, SecretStr]` (b64 32-byte), `byok_master_key_version: int = 0`, `byok_allow_derived_kek: bool = False`. `_kek_for_version(v)` reads the dict, b64-decodes, asserts 32 bytes. No logging anywhere in this module.
- **Migrations:** none.
- **Acceptance:** Given a plaintext key, When encrypted then decrypted, Then identical; And `repr(EncryptedSecret)` and any structlog never carries plaintext (covered fully in S5.10); And rotation re-wraps `enc_data_key` only.
- **Risk/notes:** `cryptography` is already a dependency (ADR-0027). Never reuse `badges_keys` (Ed25519, FR-BYOK-09). `EncryptedSecret` is a frozen dataclass with no plaintext field. Keep `_active_kek` cache-free or cleared like `badges_keys.reset_for_tests` so env-flip tests work — add a `reset_for_tests()`.

### S5.2 — Allowlisted provider registry + `GET /llm-providers`
Goal: frozen in-code `PROVIDER_REGISTRY` with **fixed base URLs** + curated model allowlist; read-only API.

- **Files:**
  - create `apps/backend/app/services/llm_providers.py`
  - create `apps/backend/app/schemas/llm_provider.py` (`ProviderInfo`, `ProviderRegistryOut`)
  - create `apps/backend/app/api/v1/llm_providers.py`
  - change `apps/backend/app/api/router.py` (register router, no prefix → `/api/v1/llm-providers`)
  - create `apps/backend/tests/test_llm_providers_registry.py`
- **TDD steps (fail first):**
  1. registry unit: `PROVIDER_REGISTRY["groq"].base_url == "https://api.groq.com/openai/v1"`; every spec has non-empty `base_url`, `models` tuple, `transport in {"openai","anthropic"}`; groq is present (FR-BYOK-13).
  2. immutability: `PROVIDER_REGISTRY` values are frozen dataclasses (mutating raises `FrozenInstanceError`).
  3. API: `GET /api/v1/llm-providers` with `auth_headers` → 200, body `{"providers":[{provider, display_name, models:[...]}...]}`; **no `base_url`, no key fields** in the response (assert keys absent).
  4. anonymous → 401 (FR-BYOK-22).
- **Implementation:** `ProviderSpec` dataclass per ADR-0027 §1 (verbatim registry). Handler depends on `CurrentUser`. `ProviderInfo` exposes `provider, display_name, models` only (base_url is server-internal).
- **Migrations:** none.
- **Acceptance:** Given an authenticated user, When GET /llm-providers, Then the curated model lists return and no URL/secret leaks; And the frontend never hard-codes providers (FR-BYOK-20).
- **Risk/notes:** Code constant, not DB table (R-G4). `base_url` must never appear in any DTO — it is the SSRF lockdown surface.

### S5.3 — `user_llm_credentials` model + migration 0030
Goal: encrypted credential table, partial-unique constraints, soft-delete.

- **Files:**
  - create `apps/backend/app/models/user_llm_credential.py`
  - change `apps/backend/app/models/__init__.py` (import + `__all__`)
  - create `apps/backend/alembic/versions/<date>-0030_byok_credentials.py`
  - create `apps/backend/tests/test_user_llm_credential_model.py`
- **TDD steps (fail first):**
  1. model fields exist with correct types (LargeBinary `enc_key`/`enc_data_key`, Integer `key_version`, String(64) `key_fingerprint`, String(8) `last4`, Bool `enabled`/`is_active`/`allow_platform_fallback`, String(20) `last_validation_status` default `'unvalidated'`, nullable `last_validated_at`, `deleted_at`). **Assert there is no `api_key`/`api_base`/`host`/`url`/plaintext column** (introspect `__table__.columns`).
  2. partial-unique `(user_id, provider) WHERE deleted_at IS NULL`: insert two live rows same provider → `IntegrityError`; soft-delete one then insert → OK (FR-BYOK-08).
  3. partial-unique active: two rows `is_active=True` for one user → `IntegrityError` (≤1 active).
  4. FK `user_id ON DELETE CASCADE`: delete user → rows gone.
  5. migration round-trip: `alembic upgrade 0030` then `downgrade -1` drops the table cleanly (run via a small migration test or assert table presence after the `_engine` fixture creates schema).
- **Implementation:** model per ADR-0027 §Data model. Use `IdMixin` (21-char nanoid) + `TimestampMixin`. Migration: `CREATE TABLE` + three indexes/constraints; use `postgresql_where=text("deleted_at IS NULL")` for partials; `ix_user_llm_credentials_user` on `(user_id)`. Up purely additive; down drops table.
- **Migrations:** **0030_byok_credentials** — up: create table + partial uniques + index; down: drop table. Zero-downtime: additive, no fleet coordination (apply before rolling image).
- **Acceptance:** Given the migration applied, When two enabled creds for the same provider are inserted, Then the second fails; And no column can hold a plaintext key or URL.
- **Risk/notes:** Partial unique indexes need `postgresql_where`. Confirm `down_revision` is the real chain head at PR time.

### S5.4 — `llm_calls.billing_mode` + `quota_exceeded` status (migration 0031)
Goal: per-row billing attribution + new sentinel status.

- **Files:**
  - change `apps/backend/app/models/llm_call.py` (add `billing_mode`, `STATUS_QUOTA_EXCEEDED`)
  - change `apps/backend/app/models/__init__.py` (export new status if listed)
  - create `apps/backend/alembic/versions/<date>-0031_llm_calls_billing_mode.py`
  - change `apps/backend/tests/test_llm_call_log.py`
- **TDD steps (fail first):**
  1. model: `LLMCall(...).billing_mode` defaults to `"platform"`; `STATUS_QUOTA_EXCEEDED == "quota_exceeded"` importable.
  2. persisting a row with `billing_mode="byok"` reads back correctly.
  3. migration: column exists with `server_default 'platform' NOT NULL` (introspect).
- **Implementation:** `billing_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="platform", default="platform")`; add `STATUS_QUOTA_EXCEEDED = "quota_exceeded"` to literals + `__all__`.
- **Migrations:** **0031_llm_calls_billing_mode** — up: `ADD COLUMN billing_mode VARCHAR(16) NOT NULL DEFAULT 'platform'` (Postgres 17 fast-default, no rewrite); down: drop column. Zero-downtime: old fleet writes rows without it → DB fills `'platform'` (correct, pre-deploy traffic is platform). No backfill window.
- **Acceptance:** Given old code writes a row during deploy, When read by new code, Then `billing_mode == "platform"`.
- **Risk/notes:** keep `SYSTEM_USER_ID` + both composite indexes untouched.

### S5.5 — `tutor_turn_jobs.credential_id` (migration 0032)
Goal: carry the foreground-locus token (credential id, never the key) to the streaming worker (R-S1″).

- **Files:**
  - change `apps/backend/app/models/tutor_turn_job.py`
  - create `apps/backend/alembic/versions/<date>-0032_tutor_turn_credential_id.py`
  - change `apps/backend/tests/` (add to existing tutor-turn job test or `test_user_llm_credential_model.py`)
- **TDD steps (fail first):**
  1. model: `credential_id` is nullable String(21); FK to `user_llm_credentials.id` `ON DELETE SET NULL`.
  2. set/read round-trip; deleting the credential nulls the column (SET NULL), not the turn row.
- **Implementation:** additive nullable column + FK. Migration up adds column+FK; down drops.
- **Migrations:** **0032_tutor_turn_credential_id** — up add nullable column + FK SET NULL; down drop. Additive, zero-downtime.
- **Acceptance:** Given a streaming turn references a credential, When that credential is soft-then-hard-deleted, Then the turn row survives with `credential_id IS NULL`.
- **Risk/notes:** SET NULL (not CASCADE) so a deleted key never orphans audit/turn history.

### S5.6 — Provider key safety: `SecretStr` wrap + redacting `__repr__`/`__str__`
Goal: `repr(provider)` / `str(provider)` never contain the key; locked `api_base` for BYOK (DR-17).

- **Files:**
  - change `apps/backend/app/services/llm.py` (`AnthropicProvider`/`OpenAIProvider`/`MistralProvider` at `:200,:312,:460`; add `build_provider_from_spec`)
  - create `apps/backend/tests/test_provider_key_redaction.py`
- **TDD steps (fail first):**
  1. `OpenAIProvider(api_key="sk-SENTINEL-1234").__repr__()` does **not** contain `"sk-SENTINEL"` (assert sentinel absent); same for `str()`, and for Anthropic + Mistral.
  2. the provider still works: `_get_client()` receives the real key (mock the SDK; assert `kwargs["api_key"] == "sk-SENTINEL-1234"`).
  3. `build_provider_from_spec(spec, api_key="sk-X", model="gpt-4o")` returns the right transport class with `base_url == spec.base_url` and the model set; **passing any non-registry `api_base` is impossible** (function has no such param) — assert signature.
- **Implementation:** store `self._api_key = SecretStr(api_key)`; everywhere it's used (`_get_client`, the `if not self._api_key` guards), call `.get_secret_value()`. Add `__repr__`/`__str__` returning e.g. `f"OpenAIProvider(model={self._model!r})"` (no key). `build_provider_from_spec(spec, *, api_key, model)` in `llm.py` instantiates by `spec.transport` with `api_base=spec.base_url` exactly.
- **Migrations:** none.
- **Acceptance:** Given a provider with a real key, When `repr()`/`str()` is taken, Then the key bytes are absent; And `get_provider()` (zero-arg, system/eval path) keeps working unchanged.
- **Risk/notes:** keep `get_provider()` signature stable (system/eval still use it). The `if not self._api_key:` truthiness check changes — `SecretStr("")` is truthy, so guard on `not self._api_key.get_secret_value()`.

### S5.7 — `LLMContext` + `byok.build_provider` + `resolve_context` (the only decrypt site)
Goal: initiation-locus resolution, decryption-at-dispatch-only, drift + fallback + precedence (DR-8, DR-17, R-M11′, R-S1″).

- **Files:**
  - create `apps/backend/app/services/byok.py`
  - create `apps/backend/app/repositories/user_llm_credentials.py` (async data access; no HTTP)
  - change `apps/backend/app/services/capabilities.py` (create if absent: `can_use_byok(user) = user.is_active`)
  - create `apps/backend/tests/test_byok_resolve.py`
- **TDD steps (fail first):**
  1. `PLATFORM_CONTEXT.user_id == SYSTEM_USER_ID`, `foreground is False`.
  2. `resolve_context(db, user_id=u)` with no credential → returns ctx whose resolution yields platform (`credential_id is None`).
  3. with an active/enabled/`last_validation_status!=invalid` cred → `resolve_context` sets `credential_id`; `build_provider(db, ctx)` returns `(provider, "byok")` and the provider's model == stored model, base_url == registry base, key == decrypted plaintext (mock SDK; assert via `build_provider_from_spec` call args).
  4. **decrypt locus:** patch `secrets_crypto.decrypt_secret` with a spy; assert it is called **only** inside `build_provider`, never in `resolve_context` (resolve does no decrypt).
  5. **drift (R-M11′):** stored `model` not in `spec.models` → if `allow_platform_fallback=True`: returns `(platform_provider, "platform")` AND sets cred `last_validation_status="needs_attention"` AND raises/surfaces `byok.model_unavailable` notice; if `False`: raises `AppError("tutor.byok_provider_error")`.
  6. **disabled / not-active / soft-deleted** cred → platform.
  7. **background ctx** (`foreground=False`) → platform regardless of stored creds (R-S1″).
  8. **invalid status** cred + `allow_platform_fallback=False` → hard-fail `tutor.byok_provider_error`; with True → platform + one-time notice flag.
- **Implementation:** dataclasses + functions per ADR-0027 §4. `build_provider` is the sole `decrypt_secret` caller; it calls `build_provider_from_spec(spec, api_key=decrypted, model=cred.model)`. Precedence ladder from ADR-0027 §4 (items 1–6). `capabilities.can_use_byok(user) -> bool` returns `user.is_active` (R-CAP; no storage). New error subclasses added in S5.9.
- **Migrations:** none.
- **Acceptance:** Given a foreground user with a valid BYOK cred, When `build_provider` runs, Then it decrypts exactly once and returns the user's model on the registry-fixed base; Given a background beat ctx, Then platform regardless.
- **Risk/notes:** No process-wide/Redis cache of decrypted keys (FR-BYOK-25) — request-scoped provider object only. The repo returns ORM rows; never `model_dump` an enc_* field into a DTO.

### S5.8 — Pre-dispatch DB COUNT quota in `call_logged` + streaming reservation (DR-11/DR-16, R-M7′)
Goal: non-dollar request/job ceiling enforced before provider dispatch, closing the $0 BYOK bypass; Redis concurrency lease (best-effort).

- **Files:**
  - change `apps/backend/app/services/llm_call_log.py` (`call_logged` at `:197`; add `ctx`/`billing_mode`, COUNT guard, sentinel row)
  - change `apps/backend/app/core/config.py` (`llm_user_request_quota_24h`, `llm_user_request_quota_1h`, `byok_requests_24h`, `byok_tokens_24h`, `platform_requests_24h`, `llm_max_concurrent`, `llm_max_retries`, `llm_provider_timeout_s` — defaults from R-G1)
  - change `apps/backend/app/workers/tasks/tutor_streaming.py` (reservation path counts too, around `:97`)
  - change `apps/backend/tests/test_llm_call_log.py` + create `apps/backend/tests/test_llm_quota_guard.py`
- **TDD steps (fail first):**
  1. with `llm_user_request_quota_24h=2`, three `call_logged(..., user_id=u)` → 3rd raises `RateLimitedError`/`AppError("llm.quota_exceeded")` with tripped dimension in `details`, and **persists a sentinel row** `status="quota_exceeded"` (mirrors `STATUS_BUDGET_EXCEEDED` path at `llm_call_log.py:230`).
  2. **BYOK $0 bypass closed:** a BYOK ctx call on a model absent from `MODEL_PRICING` (cost_usd=0) **still** counts toward the request quota and trips (this is the core DR-16 assertion).
  3. quota is **pre-dispatch**: provider is **not** invoked when over-limit (spy on `_invoke_provider`, assert not called).
  4. `SYSTEM_USER_ID` calls bypass the quota (operator paths), matching the existing dollar-guard carve-out at `:227`.
  5. `billing_mode` persisted = ctx-derived (`"byok"` vs `"platform"`).
  6. concurrency: with Redis up and `llm_max_concurrent=1`, a second concurrent reservation is rejected; **Redis-down → fail-open** (DB backstop still hard) — simulate by pointing the client at a dead socket, assert call proceeds + a warning logged.
- **Implementation:** add `ctx: LLMContext = PLATFORM_CONTEXT` param to `call_logged`; before the provider call, `SELECT COUNT(*) FROM llm_calls WHERE user_id=? AND created_at > now()-window` for the 24h and 1h windows (reuse `ix_llm_calls_user_created`); BYOK vs platform window/limit chosen from settings via `ctx`/`billing_mode`. Over-limit → persist sentinel `quota_exceeded` row + raise. Concurrency lease via `cost_scripts.check_concurrency`/`release_concurrency` with `ttl = llm_provider_timeout_s + buffer`; wrap in try/except → fail-open. Streaming reservation path mirrors the COUNT before reserving.
- **Migrations:** none (uses 0031 status literal + existing index).
- **Acceptance:** Given a BYOK user on a free-priced model, When they exceed `byok_requests_24h`, Then the call short-circuits with `llm.quota_exceeded`, a sentinel row is written, and the provider is never hit; Given Redis is down, Then the call still proceeds (DB is the hard guard).
- **Risk/notes:** keep the existing dollar guard for platform users (run both). Token-per-window is post-dispatch (only known after the call) — out of scope for the pre-dispatch guard; note it. COUNT hotspot risk noted in ADR-0027 §Open risks — index-covered; revisit with Redis token-bucket if p95 regresses.

### S5.9 — Credential CRUD + validate API (`/me/llm-credentials`) + schemas + error codes + audit
Goal: upsert/list/patch/delete/validate with write-only keys, masked reads, redacted probe, oracle caps (FR-BYOK-16..21, R-S4), audit events.

- **Files:**
  - create `apps/backend/app/schemas/llm_credential.py` (`LLMCredentialUpsert`, `LLMCredentialPublic`, validate-out)
  - create `apps/backend/app/api/v1/llm_credentials.py`
  - create `apps/backend/app/services/llm_credentials.py` (service: upsert/patch/delete/validate; the only validate-probe caller)
  - change `apps/backend/app/api/router.py` (register under `/me`)
  - change `apps/backend/app/core/errors.py` (new `AppError` subclasses)
  - change `apps/backend/app/core/ratelimit.py` usage / apply slowapi limits on create/update/validate (FR-QUOTA-04, keyed by `_identity_key`)
  - create `apps/backend/tests/test_llm_credentials_api.py`
- **TDD steps (fail first):**
  1. `PUT /me/llm-credentials/openai {model:"gpt-4o-mini", api_key:"sk-SENTINEL"}` → 201/200; `GET /me/llm-credentials` returns **masked** DTO with `last4`, `last_validation_status`, **no `api_key`/`enc_*`/`key_version`** field present.
  2. `LLMCredentialUpsert` 422s on **any** `base_url|api_base|host|url` key → error code `byok.base_url_forbidden` (FR-BYOK-14); model_config rejects extras.
  3. model not in registry → 422 `byok.model_not_allowed`; provider not in registry → 422 `byok.provider_not_allowed`.
  4. idempotency on `(provider, model, key_fingerprint)`: PUT same payload twice → one live row (FR-BYOK-08).
  5. `PATCH` toggles `enabled`/`is_active`/`allow_platform_fallback`; setting active demotes any prior active (≤1).
  6. `DELETE` soft-deletes + clears active; subsequent resolution → platform.
  7. validate **anti-oracle (R-S4):** `POST .../validate` before storing → 412 `byok.must_store_before_validate`; >5 validations / 10 min → 429 `byok.validate_rate_limited`; >10 **distinct** `key_fingerprint`s validated per user/day → 429 (counts distinct fingerprints in `byok.credential_validated` audit window).
  8. validate response is **redacted**: feed a fake provider raising an error containing a vendor request-id/header; assert the returned `{status,message}` contains none of those tokens (no key echo, no `x-request-id`, no raw body).
  9. `can_use_byok` gate: suspended user (`is_active=False`) → 403 `byok.capability_revoked` on every endpoint.
  10. audit: create/update/delete/validate emit `byok.credential_created/_updated/_deleted/_validated` (status only).
  11. anonymous → 401 (FR-BYOK-22).
- **Implementation:** schemas per ADR-0027 §API (`SecretStr` write-only key; `field_validator` raising `ValidationAppError(code="byok.base_url_forbidden")` on URL-ish keys). Service encrypts via `secrets_crypto`, stores fingerprint+last4, `last_validation_status="unvalidated"`, auto-validates **once** on create. Validate uses `build_provider_from_spec` against the **registry-fixed base** with `chat_min` (`max_tokens=1`) and a normalized/redacted error mapper. Audit via the existing audit-event mechanism. The store-validate refuses a real key under a derived KEK unless `byok_allow_derived_kek=true` (dev only).
- **Migrations:** none.
- **Acceptance:** Given a stored key, When listed/exported/viewed by admin, Then only masked metadata appears; Given rapid distinct-key validation, Then the oracle cap trips with a redacted 429; Given any URL field, Then 422.
- **Risk/notes:** New error codes: `byok.base_url_forbidden`, `byok.model_not_allowed`, `byok.provider_not_allowed`, `byok.credential_not_found`, `byok.validate_rate_limited`, `byok.must_store_before_validate`, `byok.capability_revoked`, `byok.model_unavailable`, `tutor.byok_provider_error`, `llm.quota_exceeded`. BYOK key material excluded from `GET /me/export` (FR-BYOK-21) — wire that exclusion here and assert it.

### S5.10 — Value-level redaction filter over all sinks + sentinel tests (R-U3, FR-BYOK-24)
Goal: a last-stage structlog processor + exception/trace scrub that prevents any decrypted key from landing in any sink; enumerated-sink sentinel coverage. Removes the runtime leak-canary (R-U4).

- **Files:**
  - change `apps/backend/app/core/logging.py` (add value-level processor as the **last** processor after `_redact` at `:73`; export for worker reuse)
  - change `apps/backend/app/core/errors.py` (scrub `details` in the envelope)
  - create `apps/backend/tests/test_byok_sink_redaction.py` (the enumerated-sink contract)
- **TDD steps (fail first):** a fixture stores a credential with sentinel key `"sk-SENTINEL-DO-NOT-LEAK-0000"`, drives each named path, and asserts the sentinel is **absent** across:
  - structlog JSON output (capture stdout),
  - exception messages/tracebacks rendered to the client (`{error:{...}}` envelope — `details` scrubbed),
  - `llm_calls` rows (provider/model/error_kind columns),
  - `agent_traces` / `retrieval_audits` / `tutor_turn_jobs` payloads,
  - sub-agent trace payloads,
  - Celery task payloads/args (assert the streaming task arg carries `credential_id`, **not** the key bytes — FR-BYOK-26),
  - admin views (`admin_llm_calls`, admin user view),
  - OpenAPI schema (`/openapi.json` has no `api_key`/`enc_*` field on credential DTOs),
  - `/me/export`.
  - plus a unit test of the processor: `redact_values({"k": "sk-SENTINEL-..."})` → masked; recurses into nested dict/list/str; preserves non-key values.
- **Implementation:** a processor that walks `event_dict` values (recursing dict/list/str) and masks substrings matching known key prefixes (`sk-`, `sk-ant-`, `gsk_`, `...`) plus the test-injected sentinel. Register **after** `_redact` (so it sees post-key-redaction values). Export `redact_values`/`install_value_redaction` so `workers/celery_app.py` can install the same on worker structlog/exception/trace sinks (R-S1′f, wired in S5.11). Scrub the error envelope `details`.
- **Migrations:** none.
- **Acceptance:** Given a sentinel key flows through every named sink, When the tests run, Then the sentinel appears in none; And the self-defeating leak-canary metric is not introduced (R-U4).
- **Risk/notes:** heuristic by prefix+sentinel (ADR-0027 §Open risks) — the structural guarantee (keys only ever live inside a `SecretStr`-wrapped provider, S5.6) is the primary defense; this filter is defense-in-depth. The enumerated-sink test is the tested contract, not the regex.

### S5.11 — Boot guard on API and worker (`assert_byok_kek_present`) — DR-7, R-S3
Goal: refuse to boot without a real KEK once credentials exist (or in prod); same guard on API lifespan and Celery worker.

- **Files:**
  - change `apps/backend/app/core/prod_guards.py` (add `assert_byok_kek_present(settings)`; **call it from `assert_production_safe`** per DR-7 — the API path already runs `assert_production_safe` at `main.py:268`)
  - change `apps/backend/app/workers/celery_app.py` (add a `worker_process_init` signal handler running the guard + installing the worker redaction sinks from S5.10)
  - change `apps/backend/tests/test_prod_guards.py` + create `apps/backend/tests/test_worker_boot_guard.py`
- **TDD steps (fail first):**
  1. `assert_byok_kek_present` raises when **any `user_llm_credentials` row exists** AND the KEK is empty/derived/`<32` bytes — in **any env**, not just prod (R-S3). Note: the existing `collect_problems` early-returns when not production (`prod_guards.py:187`); `assert_byok_kek_present` must run **independently of `_is_production`** when credentials exist (it cannot live behind that early return).
  2. with `ENV=production` and no real KEK → raises even with zero credentials.
  3. with a real 32-byte versioned KEK → passes; with `byok_allow_derived_kek=true` (dev only, never prod) → derived KEK allowed only when not production.
  4. worker: the `worker_process_init` handler calls the same guard and aborts boot on failure (test the handler function directly; assert it raises/`sys.exit`).
- **Implementation:** `assert_byok_kek_present(settings)` checks `secrets_crypto.active_kek_is_derived()` / key length / version presence; runs a lightweight existence check (`SELECT 1 FROM user_llm_credentials LIMIT 1` — guard a sync engine in the worker path / accept a "credentials_exist" callable to keep prod_guards import-light). Call it inside `assert_production_safe` (DR-7) **and** unconditionally-when-credentials-exist regardless of env. Worker: register `@worker_process_init.connect` in `celery_app.py` (genuinely absent today) that runs the guard and installs the value-redaction sinks (S5.10).
- **Migrations:** none (depends on 0030 table existing).
- **Acceptance:** Given a real KEK absent and a credential row present, When either the API lifespan or the worker process inits, Then boot hard-fails with a clear message; Given a real KEK, Then both boot.
- **Risk/notes:** DR-7 corrected the citation — the extension point is `assert_production_safe` (called at `main.py:268`), not a non-existent `check_byok_master_key` at `:268`. Worker-boot-loop risk on misconfigured deploy is documented (ADR-0027 §Open risks); `BYOK_ALLOW_DERIVED_KEK` escape is dev-only.

### S5.12 — Thread `LLMContext` through every foreground LLM call site (DR-8, R-S1″)
Goal: every user-initiated feature uses BYOK; background/beat uses platform; streaming worker carries `credential_id`.

- **Files:**
  - change `apps/backend/app/services/tutor_orchestrator.py:654`
  - change `apps/backend/app/services/authoring_orchestrator.py:484` (+ `draft_course` at `:648` accepts/threads ctx) and `_chat_with_retry` at `:462`
  - change `apps/backend/app/services/learning_path.py` (`build_path:270`, `replan_for_user:423` add `ctx: LLMContext = PLATFORM_CONTEXT`; `_chat_with_retry:743`; provider build at `:757`)
  - change `apps/backend/app/services/tutor_subagents/concept_explainer.py:110`, `quiz_generator.py:159` (inherit parent ctx)
  - change `apps/backend/app/api/v1/learning_path.py:181,271` (resolve foreground ctx), `app/api/v1/ai_authoring.py:328`, `app/api/v1/tutor.py` (interactive tutor handler)
  - change `apps/backend/app/services/tutor_orchestrator_stream.py` + `apps/backend/app/workers/tasks/tutor_streaming.py:97` (carry `turn.credential_id` → rebuild ctx in worker)
  - change `apps/backend/app/services/llm_stream.py:93` (`stream_chat(messages, *, ctx)` replaces global switch; dispatch by `spec.transport` with registry base + decrypted key)
  - change `apps/backend/app/workers/tasks/learning_path.py:70` (beat passes default `PLATFORM_CONTEXT`)
  - create/extend `apps/backend/tests/test_byok_threading.py`, change `tests/test_llm_stream.py`
- **TDD steps (fail first):**
  1. interactive tutor: a foreground user with a valid cred records an `llm_calls` row with `billing_mode="byok"` and the user's model; without a cred → `platform`.
  2. authoring/goal-build (`draft_course`) foreground → BYOK.
  3. learning-path **build** + **manual replan** (API handlers) → BYOK; **monthly beat** `replan_paths_monthly` → platform (same `replan_for_user`, ctx decided by caller — R-S1″).
  4. tutor subagents inherit the parent ctx (concept_explainer/quiz_generator).
  5. **streaming:** enqueue a turn for a BYOK user → task args carry `credential_id` (not the key — assert payload bytes, ties to S5.10); the worker rebuilds ctx, `stream_chat` dispatches to the registry base with the decrypted user model; the recorded turn shows `billing_mode="byok"`.
  6. `stream_chat` no longer reads `settings.llm_provider` global switch (assert it routes by `ctx`/registry, e.g. monkeypatch `settings.llm_provider="noop"` but a BYOK ctx still dispatches the user's provider).
  7. embeddings + eval/judge paths remain platform-pinned (regression: unchanged).
- **Implementation:** per ADR-0027 §4 classification table + DR-8. API handlers build ctx via `byok.resolve_context(db, user_id=user.id)`; pass through services. Streaming: persist `credential_id` on the turn job at enqueue (foreground resolve), worker reads `turn.credential_id`, builds `LLMContext(user_id=turn.user_id, credential_id=..., foreground=True)`, passes to `orchestrate_stream`→`stream_chat`→`build_provider`. `call_logged` already gets `ctx` from S5.8.
- **Migrations:** none (uses 0032 column).
- **Acceptance:** Given each foreground feature, When invoked by a BYOK user, Then it dispatches the user's model on the registry base and logs `billing_mode=byok`; Given the monthly beat, Then platform; And no Celery payload carries key bytes.
- **Risk/notes:** This is the largest task — split per-call-site commits if needed but keep green between each (each call site defaults `ctx=PLATFORM_CONTEXT`, so partial threading never regresses behavior). `get_provider()` stays zero-arg for system/eval. The streaming global-switch removal (`llm_stream.py:93`) is the highest-risk edit — gate behind `feature_byok_enabled` if shipping inert.

### S5.13 — Admin cost surface: `billing_mode` grouping + platform-$ excludes BYOK
Goal: correct cost rollups + BYOK adoption/non-dollar usage visibility (FR-BYOK-27/28).

- **Files:**
  - change `apps/backend/app/api/v1/admin_llm_calls.py:170` (platform-$ total excludes `billing_mode='byok'`; group/filter by `billing_mode`)
  - change `apps/backend/tests/test_llm_cost_admin_api.py`
- **TDD steps (fail first):**
  1. seed mixed platform + byok rows; admin total-$ **excludes** byok rows.
  2. response exposes BYOK adoption count + non-dollar (request) consumption per group.
  3. byok rows never leak key material (covered by S5.10 sink test; add an admin-view assertion here).
- **Implementation:** add `WHERE billing_mode != 'byok'` to the dollar sum; add a grouped count by `billing_mode`.
- **Migrations:** none.
- **Acceptance:** Given byok+platform rows, When admin views cost, Then platform-$ is correct and BYOK adoption is shown.
- **Risk/notes:** admin route must keep filtering `SYSTEM_USER_ID` out of per-user views.

### S5.14 — `rotate_byok_master_key` CLI + runbook
Goal: operational KEK rotation re-wrapping `enc_data_key` only (FR-BYOK-12, R-S2).

- **Files:**
  - change `apps/backend/app/cli.py` (add `rotate_byok_master_key` command)
  - create `apps/backend/docs/runbooks/byok-key-rotation.md` (or `docs/runbooks/...`)
  - create `apps/backend/tests/test_byok_rotation.py`
- **TDD steps (fail first):**
  1. seed N creds at version 1; run rotate v1→v2; every row now `key_version=2`, `enc_data_key` re-wrapped, `enc_key` **unchanged**, all decrypt to original plaintext (uses `secrets_crypto.rotate_secret`).
  2. rotation never logs/emits plaintext or DEK; emits `byok.master_key_rotated` (counts only).
  3. precondition guard: refuses if target version KEK is absent from `byok_master_keys` (R-S2: all versions deployed before rotation).
- **Implementation:** batched transactions over creds, `rotate_secret` per row; CLI mirrors existing `cli.py` command style.
- **Migrations:** none.
- **Acceptance:** Given creds at vN, When rotation to vN+1 completes, Then all rows re-wrapped, plaintext untouched, audit emitted.
- **Risk/notes:** retain vN until rotation completes (long-running streamed turn risk — ADR-0027 §Open risks). Runbook documents the fleet precondition.

### S5.15 — Frontend BYOK settings tab + i18n + hooks
Goal: `/profile/model` (or a BYOK tab under `/profile`) — provider/model select, write-only key, validate, toggles; masked read; no `api_base` anywhere.

- **Files:**
  - create `apps/frontend/src/app/profile/model/page.tsx` (client component)
  - create `apps/frontend/src/components/byok/{CredentialForm,ProviderSelect,CredentialList,ValidateButton,NeedsAttentionBanner}.tsx`
  - change `apps/frontend/src/lib/query/keys.ts` (add `llmProviders`, `llmCredentials` keys)
  - change `apps/frontend/src/lib/api/endpoints.ts` + `types.ts` (hand-written per DR-5 — do **not** `make api-client`; add `LLMProvider`, `LLMCredentialPublic` types + endpoint fns)
  - change `apps/frontend/src/lib/i18n/messages/en.ts` + `ar.ts` (the `byok.*` keys from ADR-0027 §Frontend, parity-enforced)
  - create `apps/frontend/tests/byok-credential-form.test.tsx` (Vitest + happy-dom) + extend the i18n parity test
- **TDD steps (fail first):**
  1. Vitest: `CredentialForm` renders providers from `GET /llm-providers` (mocked), model select scoped to chosen provider, write-only key input (type=password, never pre-filled), validate button, enabled/active/`allow_platform_fallback` toggles; **no `api_base`/url field exists** (assert query returns nothing).
  2. masked read: `CredentialList` shows `last4` + status badge, never a full key.
  3. `NeedsAttentionBanner` shows on `last_validation_status="needs_attention"`/`invalid`.
  4. i18n parity test: every `byok.*` key present in both `en.ts` and `ar.ts`.
  5. mutations use the new query keys + invalidate on success.
- **Implementation:** TanStack Query mutations for upsert/patch/delete/validate. Provider→model cascade from the registry endpoint. Consent copy for `allow_platform_fallback` (data-handling notice — ADR-0027 §Open risks). RTL-safe for `ar`.
- **Migrations:** none.
- **Acceptance:** Given a user opens the model tab, When they pick provider+model, enter a key, validate, and enable, Then the key is stored encrypted (never re-rendered) and used for their requests; And no URL field is ever presented.
- **Risk/notes:** `types.ts` is hand-written (DR-5) — add types manually, add the CI contract-drift check (openapi.json vs generated) in S7, not here. i18n parity test must pass.

### S5.16 — Flag-gate `feature_byok_enabled` + CHANGELOG
Goal: ship inert until KEK confirmed fleet-wide (ADR-0027 §Migrations deploy ordering).

- **Files:**
  - change `apps/backend/app/core/config.py` (`feature_byok_enabled: bool = False`)
  - gate the write/resolve paths (CRUD endpoints + `resolve_context` returns platform when flag off)
  - change `CHANGELOG.md`
  - create `apps/backend/tests/test_byok_feature_flag.py`
- **TDD steps (fail first):** flag off → `PUT /me/llm-credentials/...` → 404/403 (route inert) and `resolve_context` → platform; flag on → full behavior. Toggle via env + `get_settings.cache_clear()`.
- **Implementation:** `Settings.feature_byok_enabled` (env-backed, default false), checked at the credential service + `resolve_context` entry.
- **Acceptance:** Given the flag is off, When BYOK endpoints are called, Then they are inert and resolution is platform; Given on (after KEK confirmed), Then full BYOK.
- **Risk/notes:** Settings env (deploy-gated), mirroring `feature_tutor_streaming` (`config.py:202`). Flip only after fleet roll + boot guard confirms KEK on every API+worker process (R-S2/R-S3).

---

## Stream-level gate (done = all true)
1. **Unit/integration green:** `make test.api` passes including all new `test_secrets_crypto`, `test_byok_*`, `test_llm_quota_guard`, `test_byok_sink_redaction`, `test_worker_boot_guard`, `test_byok_rotation`, `test_llm_credentials_api`, `test_provider_key_redaction`; `make test.web` passes including the BYOK Vitest + i18n parity test; `make lint` + `tsc` clean.
2. **Security proofs (the load-bearing ones from ADR-0027 §Consequences):** `repr(provider)` redaction; sentinel absent across every enumerated sink; Celery payload has `credential_id` and no key bytes; a BYOK streamed turn records `billing_mode=byok` + the user's model in `llm_calls`; validate oracle caps trip; quota trip persists a sentinel row and blocks (no platform fallback for quota-exhausted); drift → platform + `needs_attention`; boot guard fires on **both** API and worker when a credential exists without a real KEK; `decrypt_secret` is called only inside `build_provider`.
3. **Migrations applied + reversible:** 0030/0031/0032 up+down verified locally; `make up` boots API+worker; `make migrate` clean.
4. **Live-as-a-user browser check (Gate C) on S5 surfaces** — drive the real app locally (`make up`), signed in as a normal `user` per the post-deploy-visual-coverage memory:
   - open `/profile` → model tab: pick provider (e.g. OpenAI) → model list populates from `/llm-providers`; enter a (dev) key, Validate → status badge updates with a **redacted** message; toggle Enabled + "Use for my requests".
   - run an interactive tutor turn and (if `feature_tutor_streaming` on) a streaming turn → confirm via admin `/admin/llm-calls` the rows show `billing_mode=byok` + the user's model; platform-$ total excludes them.
   - delete the key → next tutor turn falls back to platform; confirm no key ever appears in the UI, network tab, `/me/export`, or `/openapi.json`.
   - confirm **no `api_base`/URL field** anywhere in the BYOK UI.
   - capture screenshots of the model tab (valid + needs-attention states) — auth-gated surface, per memory.

## Traceability
- **ADR:** ADR-0027 (entire). Aligns with ADR-0024 (off-default adversarial rail — cloned/user content is untrusted to the tutor) and FR-EMBED-03 (embeddings platform-pinned).
- **Charter:** decision 5 (BYOK allowlisted providers, no user api_base, envelope encryption, non-dollar quotas) + decision 9 (audit events for BYOK create/update/delete/validate).
- **Design Resolutions:** DR-7 (`assert_byok_kek_present` in `assert_production_safe` + Celery `worker_process_init`), DR-8 (`LLMContext` threaded across get_provider/build_path/replan_for_user/_chat_with_retry/tutor/authoring + worker credential_id), DR-11 + DR-16 (pre-dispatch DB COUNT quota in `call_logged`, closes $0 BYOK bypass), DR-17 (provider `api_base` locked to registry), DR-22 (naming canon: `byok.build_provider`, `Settings` env flag).
- **Requirements:** FR-BYOK-01…28; FR-QUOTA-01, -02, -03, -04. Resolutions: R-S1, R-S1′, **R-S1″** (initiation locus), R-S2 (rotation atomicity), R-S3 (dev/test KEK bypass + boot guard), R-S4 (validate-as-oracle caps), R-U3 (redaction filter all sinks + sentinel tests), R-U4 (remove leak canary), R-M7 + R-M7′ (concurrency lease + DB backstop quota), R-M11 + R-M11′ (model-allowlist drift + fallback consent), R-CAP (suspension-only `can_use_byok`), R-G1 (quota defaults), R-G4 (code-constant registry).


<!-- ===== S6 ===== -->

# Stream S6: Admin, moderation actions & account lifecycle

## Preconditions / depends-on (other streams, by Sx)

- **S7-pre (foundation) — HARD DEP.** Provides: migration **0030** (`users.deleted_at` + `ix_users_deleted_at` partial, concurrent), the **ORM cascade fix** on `User.courses_owned` (and `enrollments`/`reviews`) — but **DR-6-R2 narrows this**: S6 verifies/owns the *one* load-bearing change (`User.courses_owned: "all, delete-orphan" → "save-update"`, `apps/backend/app/models/user.py:55-59`). `capabilities.py`, `auth.capability` code, redaction filter. If S7-pre has not landed the cascade fix when S6 starts, **S6.0 lands it** (it is the precondition for any deletion path being trusted, ADR-0030 §D1).
- **S1 (role collapse) — HARD DEP.** Provides `Role = {user, admin}` + normalize-legacy layer, `RequireAuthor`, the reshaped role surface direction (grant/revoke), `User.is_admin()` retained. S6 builds the grant/revoke-**admin** toggle + last-admin invariant on top of S1's `Role` enum and the legacy `/role` normalizer.
- **S2 (visibility) — HARD DEP.** Provides `app/services/visibility.py` (`is_publicly_listed`, `publicly_listed_sql`, `can_view_course`, `can_clone`, `can_publish_public`, `removal_reason`), the `Course.visibility`/`moderation_state` columns + `Course.quarantined` (DR-18-R2, migration 0044), `ModerationEvent` model + table (migration 0033), the owner-side `_transition_status` side-effects, and the catalog cache-version + sitemap-purge hooks. **Open seam to resolve at S6 kickoff:** design-spec line 235 lists the moderation **service functions** (`approve/reject/delist/relist/remove_course`, `share/unshare/resubmit`) under S2's service layer, while line 264 puts the **admin endpoints + state machine + report flow** under S6. **Resolution for this plan:** S2 ships the owner-intent fns (`share/unshare/unpublish` side-effects) + the predicates; **S6 owns the admin-authority transition functions** (`approve/reject/delist/relist/remove_course`) because they are the moderation-action core of this stream. S6.2 builds them; if S2 already shipped a stub, S6.2 completes it.
- **S4 (clone) / S5 (BYOK) — SOFT DEP.** `delete_account`'s provenance-anonymization step (S4 columns: `origin_owner_id`, `origin_owner_name_snapshot`) and BYOK-credential-purge step (S5 table: `user_llm_credentials`) are **try-guarded** (catch only `ProgrammingError`/`UndefinedTable`/`ImportError`) so S6 can land and pass its core tests before S4/S5 exist; those steps become live no-redeploy once the sibling tables land (ADR-0030 §D2, open-risk 1). S6 ships tests that mock the missing table → core PII scrub still succeeds.

---

## Ordered tasks

> Test runner: `make test.api` (pytest, xdist `-n 4`, `--timeout=120`, forced `ENV=test`, real Postgres+Redis). Backend tests live in `apps/backend/tests/`. Frontend: `make test.web` (Vitest + happy-dom). Each task leaves the suite green.

---

### S6.0 — Verify/land the ORM cascade fix (DR-6-R2) and the `users.deleted_at` column

One-line goal: guarantee the headline ORM-vs-DB contradiction is gone and the tombstone marker exists before any deletion/suspension logic touches it.

- **Files:**
  - `apps/backend/app/models/user.py` (the `courses_owned` relationship, `:55-59`)
  - `apps/backend/alembic/versions/2026_..._0030-account_lifecycle_users_deleted_at.py` (verify present from S7-pre; create if absent)
  - `apps/backend/tests/test_account_cascade_invariant.py` (new)
- **TDD steps:**
  1. **FIRST write** `test_account_cascade_invariant.py::test_courses_owned_cascade_is_save_update` — introspect `User.__mapper__.relationships["courses_owned"].cascade` and assert `"delete-orphan" not in cascade` and `"save-update" in cascade`. Assert (`enrollments`, `reviews`) likewise have no `delete-orphan` (per DR-6-R2 they are also `save-update`), and `refresh_tokens` **still** has `delete-orphan` (unchanged). Currently RED (`courses_owned` is `all, delete-orphan`).
  2. **FIRST write** `test_courses_owned_relationship_does_not_orphan_delete` — create user with a course, `db.expunge` and remove the course from `user.courses_owned` collection, flush, assert the `courses` row still exists (save-update doesn't orphan-delete).
  3. Implement: change cascade to `"save-update"` on the three relationships per ADR-0030 §D1 / DR-6-R2 (`courses_owned` is the load-bearing one; the other two are internally consistent already but the ADR aligns them — keep `refresh_tokens` untouched).
  4. Confirm migration 0030 (`add_column users.deleted_at` nullable + `ix_users_deleted_at` partial CONCURRENTLY + the one-shot backfill `UPDATE users SET deleted_at = updated_at WHERE email LIKE 'deleted-%@lumen.invalid' AND is_active = false`) is present and `make migrate` + downgrade both clean. Green.
- **Migrations:** **0030** (owned by S7-pre; S6 verifies). Up: additive nullable column + partial concurrent index + idempotent historical backfill. Down: drop index (concurrently) then column — reversible, no PII destroyed. Zero-downtime: old pods never write the column; the column defaults null → reads as "suspended" until a new-pod deletion sets it (the backfill reclassifies legacy `deleted-*` rows as tombstones).
- **Acceptance criteria:** Given the ORM models, When the mapper is introspected, Then `courses_owned` cascade is `save-update` with no `delete-orphan`; Given a migrated DB, When `users.deleted_at` is queried, Then the column + partial index exist and legacy `deleted-*@lumen.invalid` inactive rows have `deleted_at` set.
- **Risk/notes:** Relationship cascade is Python-side (no DDL) — must ship in the same release as the model file. `RESTRICT` on `Course.owner_id` (`course.py:103`) stays as a DB backstop; never weaken it. CONCURRENTLY index requires `op.get_context().autocommit_block()`.

---

### S6.1 — Reason taxonomy + report-content sanitizer (shared primitive)

One-line goal: one source of truth for the moderation/suspension reason taxonomy and the inert-text sanitizer used by reports, suspensions, and moderation actions.

- **Files:**
  - `apps/backend/app/services/moderation_taxonomy.py` (new) — `ReasonCode(StrEnum)` = `{spam, abuse, fraud, tos_violation, copyright, security, illegal, csam, severe_abuse, other}` (FR-SUSP-03 set ∪ hard-removal set), `HARD_REMOVAL_REASONS = {csam, illegal, severe_abuse}`, `QUARANTINE_REASONS = {csam, illegal}` (DR-18-R2), `sanitize_note(text: str|None, *, max_len=1000) -> str|None` (strip control chars, no markup, length-cap — FR-MOD-13/FR-SUSP-03).
  - `apps/backend/tests/test_moderation_taxonomy.py` (new)
- **TDD steps:**
  1. **FIRST write** `test_sanitize_note_strips_markup_and_caps` — assert `<script>` / HTML / control chars are inertly escaped or stripped and a 5000-char note is truncated to ≤1000.
  2. `test_reason_taxonomy_membership` — assert `csam` and `illegal` are in `QUARANTINE_REASONS`, `severe_abuse` is in `HARD_REMOVAL_REASONS` but **not** `QUARANTINE_REASONS` (DR-18-R2 scope split), and `spam` is in neither.
  3. Implement the module. Green.
- **Migrations:** none.
- **Acceptance criteria:** Given untrusted note text with HTML/control chars, When `sanitize_note` runs, Then output is inert plain text ≤1000 chars; Given a reason code, When classified, Then `csam/illegal`→quarantine, `severe_abuse`→hard-removal-only.
- **Risk/notes:** This is the **single** place the taxonomy lives — shared by course moderation AND user suspension (FR-SUSP-03). `quarantined` (DR-18-R2) is set **only** by hard-remove for `reason ∈ {csam, illegal}`, never `severe_abuse`.

---

### S6.2 — Admin moderation transition service functions (writes `ModerationEvent` + `quarantined`)

One-line goal: the admin-authority state transitions `approve/reject/delist/relist/remove_course`, each writing an `AuditEvent` + `ModerationEvent`, setting `quarantined` for csam/illegal, and revoking enrolled access on hard-removal.

- **Files:**
  - `apps/backend/app/services/moderation.py` (new) — `approve/reject/delist/relist`, `remove_course`, `resubmit` already owned by S2 (owner action) but verify; consumes S2's `visibility.is_publicly_listed` + `_transition_status` invariants.
  - `apps/backend/app/repositories/moderation.py` (new) — `record_event(db, *, course_id, actor_id, from_state, to_state, reason_code, note, classifier_signal)`, `latest_event(db, course_id)`.
  - `apps/backend/tests/test_moderation_service.py` (new)
- **TDD steps:**
  1. **FIRST write** `test_approve_lists_and_writes_event` — pending_review course → `approve` → `moderation_state == approved`, `is_publicly_listed(course)` True, a `ModerationEvent(to_state=approved)` + `AuditEvent(action="admin.course.approve")` exist; embedding reindex enqueued (best-effort, mocked).
  2. `test_reject_forces_private` — pending→`reject` → `moderation_state == rejected`, `visibility == private`, `admin.course.reject` audit (FR-MOD-07).
  3. `test_delist_not_soft_deleted_and_defeatures` — approved→`delist(reason=spam)` → `moderation_state == delisted`, `is_featured == False`, `deleted_at IS NULL` (owner keeps content), idempotent (second delist → no new event) (FR-MOD-03).
  4. `test_relist_409_when_not_listable` — delisted+now-private course → `relist` raises `ConflictError(code="course.not_listable")` (FR-MOD-04); a delisted-but-still-public-published course relists to `approved`.
  5. `test_remove_csam_sets_quarantined_and_revokes_all` — `remove_course(reason=csam)` → `deleted_at` set, `quarantined == True`, enrolled learners' access revoked incl. owner (DR-18-R2 / R-C6′); `remove_course(reason=severe_abuse)` → `deleted_at` set, `quarantined == False`, other learners revoked but **owner keeps view/edit** (FR-MOD-08).
  6. `test_moderation_state_sticky_on_owner_actions` — delisted course then owner `unshare` → `moderation_state` stays `delisted` (R-C2 sticky; cross-check S2's `_transition_status`).
  7. Implement the service + repo. Each transition: validate legal source state else `ValidationAppError(code="course.invalid_transition")`; write event + audit (ip/ua threaded from endpoint); bump catalog cache-version + best-effort sitemap purge + reindex via S2 hooks. Green.
- **Migrations:** none new (consumes S2's 0033 `moderation_events` + DR-18-R2's 0044 `courses.quarantined`).
- **Acceptance criteria:** Given a `pending_review` course, When admin approves, Then it becomes publicly listed with an immutable `ModerationEvent` + audit; Given `remove(reason=csam)`, When applied, Then `quarantined=true` and even the owner loses view (full quarantine); Given `remove(reason=severe_abuse)`, Then owner keeps edit access and `quarantined=false`.
- **Risk/notes:** `quarantined` is the **single source of truth** for the csam/illegal full-quarantine path (DR-18-R2) — the SQL ACL (S2) reads the column, not a `moderation_events` JOIN; `severe_abuse` legitimately stays a `moderation_events.reason_code` read in `can_learn_in_course`. Do NOT add a DB CHECK coupling moderation_state↔visibility (R-C2). Reindex/cache calls are best-effort (swallow broker errors, CLAUDE.md).

---

### S6.3 — `course_reports` table + report-flow service (DR-20 account-age gating)

One-line goal: a `CourseReport` entity + `POST /courses/{id}/report` with reportable-only-when-publicly-listed, self-report forbidden, open-report coalescing, per-user + per-course rate limits, and DR-20 reporter eligibility (email-verified AND account-age ≥ threshold).

- **Files:**
  - `apps/backend/app/models/moderation.py` — add `CourseReport` (alongside `ModerationEvent`); export in `apps/backend/app/models/__init__.py`.
  - `apps/backend/alembic/versions/2026_..._0034-course_reports.py` (new)
  - `apps/backend/app/repositories/moderation.py` — `create_or_coalesce_report`, `list_reports`, `count_reports_in_window`, `get_open_report`.
  - `apps/backend/app/services/moderation.py` — `report_course(db, *, course, reporter, reason, note, ip, user_agent)`.
  - `apps/backend/app/schemas/course.py` — `ReportRequest{reason: ReasonCode, note: str|None}`.
  - `apps/backend/app/api/v1/courses.py` — `POST /courses/{id}/report` (`@limiter.limit("10/hour")`, `RequireAuthor`-or-auth).
  - `apps/backend/app/core/config.py` (Settings) — `report_min_account_age_days` (default 3), `report_per_course_window_max` (default e.g. 5/24h).
  - `apps/backend/tests/test_course_reports.py` (new)
- **TDD steps:**
  1. **FIRST write** `test_report_requires_publicly_listed` — report a private/own/nonexistent course → **404** (existence-hide, FR-MOD-11).
  2. `test_report_self_forbidden` — owner reports own listed course → **422** `report.own_course`.
  3. `test_report_account_age_gate` (DR-20) — reporter with `created_at` < threshold OR `email_verified_at IS NULL` → **403** `report.ineligible`; an eligible reporter (verified + ≥3d old) → 201.
  4. `test_report_coalesces_open` — same user reports same course twice → one `open` row, second updates the note (partial-unique `(course_id, reporter_id) WHERE status='open'`).
  5. `test_report_rate_limited_per_course` — N reports on one course past `report_per_course_window_max` → **429** `course.report_rate_limited` (per-course brigading cap, DR-20, on top of the `@limiter` ≤10/h per-user).
  6. `test_report_writes_audit` — successful report writes `course.report` audit (actor=reporter, ip/ua).
  7. Implement model → migration → repo → service → schema → endpoint → Settings. Green.
- **Migrations:** **0034 — `course_reports`.** Up: `CREATE TABLE course_reports` (`id`, `course_id` FK→courses CASCADE, `reporter_id` FK→users CASCADE, `reason` String(40), `note` Text, `status` String(16) default `'open'`, `created_at`, `resolved_at`, `resolved_by` FK→users SET NULL), partial-unique `uq_course_reports_open (course_id, reporter_id) WHERE status='open'`, `ix_course_reports_status_created (status, created_at)`. Down: drop table. Zero-downtime: net-new table, invisible to old pods.
- **Acceptance criteria:** Given an eligible verified reporter and a publicly-listed course, When they report, Then one `open` report row + `course.report` audit; Given an account younger than `report_min_account_age_days`, When they try to report, Then **403** `report.ineligible` (DR-20); Given a private/own course, Then **404**/**422** with no row written.
- **Risk/notes:** Account-age + email-verified is the brigading control (DR-20) layered over the per-user ≤10/h (`@limiter`) AND a new per-course cap. `note` runs through `sanitize_note` (S6.1) before persist (FR-MOD-13). Reportability routes through S2's `is_publicly_listed` — never a raw `status==published` check (grep-guard backstop).

---

### S6.4 — Admin moderation + report endpoints

One-line goal: expose the queue, the moderation actions, and report resolution; resolving a report performs the linked moderation action in the same transaction with a single audit trail.

- **Files:**
  - `apps/backend/app/api/v1/admin.py` — `GET /admin/courses/moderation-queue` (cursor; `moderation_state==pending_review`; no N+1 via `selectinload(owner, subject)`), `POST /admin/courses/{id}/approve|reject|delist|relist|remove` (body `ModerationActionRequest{reason, note}`), `GET /admin/reports` (filters status/reason/course_id, cursor), `POST /admin/reports/{id}/resolve` (body `{action: dismiss|delist|remove, reason?, note?}`).
  - `apps/backend/app/schemas/course.py` / `apps/backend/app/api/v1/admin.py` — `ModerationActionRequest`, `ModerationQueueItem`, `ReportOut`, `ReportResolveRequest`, `CourseAdminOut`.
  - `apps/backend/tests/test_admin_moderation.py` (new)
- **TDD steps:**
  1. **FIRST write** `test_moderation_queue_lists_pending_only` — seed approved + pending + rejected courses → queue returns only `pending_review`, with owner/subject loaded (assert no extra queries via query-count or eager-load shape).
  2. `test_admin_actions_require_admin` — non-admin user hits `/admin/courses/{id}/approve` → **403**; anonymous → **401**.
  3. `test_resolve_delist_is_atomic_single_audit` — `POST /admin/reports/{id}/resolve {action: delist}` → report `status==actioned`, `resolved_by`/`resolved_at` set, course delisted, **one** linked `admin.course.report_resolved` audit + the `admin.course.delist` audit in the same transaction (FR-MOD-12).
  4. `test_resolve_remove_revokes` — resolve with `action: remove, reason: severe_abuse` → course soft-deleted, learners revoked (delegates to S6.2 `remove_course`).
  5. `test_auto_action_never_delists_approved` (R-S11) — N reports accumulate on an **approved** course → it moves to `pending_review` for admin confirmation, **never** auto-delisted; a never-approved course MAY auto-requeue.
  6. `test_report_content_rendered_inert` — assert the queue/report DTOs return the sanitized note verbatim (no HTML), reporter PII present only on the admin endpoint (FR-MOD-13).
  7. Implement endpoints wiring S6.2/S6.3 services; thread ip/ua via `client_ip(request)`/`user_agent(request)`. Green.
- **Migrations:** none.
- **Acceptance criteria:** Given an admin, When they GET the moderation queue, Then only `pending_review` courses with owner/subject (no N+1); Given an open report, When admin resolves with `delist`, Then report+course transition atomically with a single linked audit trail; Given an **approved** course accumulating reports, When threshold hit, Then it requeues to `pending_review`, never auto-delisting (R-S11).
- **Risk/notes:** Cursor pagination (CLAUDE.md: cursor for moderation/audit-style reads). Admin sees reporter PII (FR-MOD-12) — keep it out of any non-admin DTO. `set_course_featured` (`admin.py:268-283`) must require `is_publicly_listed` (S2 already narrows; verify in a regression test here).

---

### S6.5 — Narrow `_can_edit_course` admin branch (FR-MOD-05)

One-line goal: admin can VIEW any course but can only mutate another user's course through the `/admin/courses/*` moderation endpoints — never via owner-shaped `PATCH`/`DELETE /courses/{id}`.

- **Files:**
  - `apps/backend/app/services/courses.py` — `_can_edit_course` (`:410-411`) and its callers `_owned_course`/`_owned_module`/`_owned_lesson` (`:374-407`).
  - `apps/backend/tests/test_admin_cannot_edit_others_course.py` (new)
- **TDD steps:**
  1. **FIRST write** `test_admin_cannot_patch_non_owned_course` — admin (not owner) `PATCH /courses/{id}` (e.g. title) → **403** `course.forbidden` (RED today: `_can_edit_course` returns True for any admin).
  2. `test_admin_cannot_delete_non_owned_course` — admin `DELETE /courses/{id}` on another's course → **403**.
  3. `test_admin_can_still_view_and_moderate` — admin GET detail of any course → 200 (view via `can_view_course`); admin `/admin/courses/{id}/delist` → 200 (moderation path unaffected).
  4. `test_owner_still_edits_own_course` — owner PATCH own course → 200 (no regression).
  5. Implement: `_can_edit_course(user, course)` → `course.owner_id == user.id` (drop the `user.is_admin()` OR-branch for edit). Keep admin view via the separate `can_view_course` authorizer (S2). Green.
- **Migrations:** none.
- **Acceptance criteria:** Given an admin who is not the owner, When they call an owner-shaped mutate endpoint, Then **403** `course.forbidden`; When they call a moderation endpoint, Then it succeeds; Given the owner, Then own-course edits still succeed.
- **Risk/notes:** This intentionally **removes** the implicit "admin edits any course" power (ADR-0026 §3, FR-MOD-05). Audit all owner-shaped routes that use `_owned_*` — they all funnel through `_can_edit_course`, so one change covers them. Coordinate with S2 (which also touches `_can_edit_course`); if S2 already narrowed it, S6.5 is just the regression test.

---

### S6.6 — Grant/revoke-admin toggle + last-admin invariant (FR-ADMIN-01/02/03)

One-line goal: replace the role `<Select>` write path with a `{is_admin}` toggle, enforce "always ≥1 active admin," and 422 legacy role values after the migration window.

- **Files:**
  - `apps/backend/app/api/v1/admin.py` — new `PATCH /admin/users/{id}/admin` (`AdminToggleUpdate{is_admin: bool}`); keep legacy `PATCH /admin/users/{id}/role` (`:194-210`) normalizing `student/instructor → user`, 422 `user.invalid_role` for removed values after Phase D; `UserAdminOut` already exposes `role`+`is_active`.
  - `apps/backend/app/services/admin_users.py` (new) — `set_admin(db, *, target, is_admin, actor, ip, ua)`, `assert_active_admin_invariant(db, *, excluding_user_id, becoming_inactive_or_user)`.
  - `apps/backend/app/repositories/users.py` — `count_active_admins(db, *, excluding=None)`.
  - `apps/backend/tests/test_admin_grant_revoke.py` (new)
- **TDD steps:**
  1. **FIRST write** `test_grant_admin` — `PATCH …/admin {is_admin: true}` on a user → `role==admin`, audit `admin.user.grant_admin` (ip/ua) (FR-AUDIT-02).
  2. `test_revoke_admin` — two admins, revoke one → `role==user`, audit `admin.user.revoke_admin`.
  3. `test_last_admin_revoke_blocked` (FR-ADMIN-03) — exactly one active admin, revoke them (or self) → **422** `user.last_admin`, no change.
  4. `test_last_active_admin_suspend_blocked` — exactly one active admin, suspend them → **422** `user.last_admin_active` (the suspend path in S6.7 calls the same invariant).
  5. `test_legacy_role_endpoint_normalizes_then_422` — `PATCH …/role {role:"instructor"}` during window → applied as `user`, audit `{requested:'instructor', applied:'user'}`; after Phase D (or with strict flag) → **422** `user.invalid_role` (FR-ADMIN-02).
  6. Implement service + repo `count_active_admins` + endpoints. The invariant is computed in the service layer (NFR-SEC-3), counting `role==admin AND is_active==true` excluding the target's prospective new state. Green.
- **Migrations:** none.
- **Acceptance criteria:** Given two active admins, When one is revoked, Then role→user with `admin.user.revoke_admin` audit; Given exactly one active admin, When revoke or suspend targets them, Then **422** `user.last_admin`/`user.last_admin_active` with no change; Given a legacy `instructor` role write post-Phase-D, Then **422** `user.invalid_role`.
- **Risk/notes:** The last-admin invariant **subsumes** the existing self-demote (`admin.py:199`) / self-deactivate (`admin.py:218`) guards — keep those as defense-in-depth but the invariant is authoritative and covers "demote the only *other* admin" too. The `authors` stat (S6.9) and this toggle both touch `admin.py` user section — sequence them to avoid merge churn.

---

### S6.7 — Suspend / reinstate (FR-SUSP-01/02/04) sharing `is_active`, distinct from deletion

One-line goal: first-class suspend/reinstate distinct from `locked_until`, sharing `is_active`, with `deleted_at` as the suspend-vs-delete discriminator, refresh-token revocation, notification, and distinct auth codes.

- **Files:**
  - `apps/backend/app/api/v1/admin.py` — `PATCH /admin/users/{id}/suspend {reason: ReasonCode, note?}`, `PATCH /admin/users/{id}/reinstate`. (Replaces the generic `/active` toggle direction; keep `/active` deprecated or fold into these.)
  - `apps/backend/app/services/admin_users.py` — `suspend(db, *, target, reason, note, actor, ip, ua)`, `reinstate(db, *, target, actor, ip, ua)`.
  - `apps/backend/app/services/auth.py` — `authenticate` (`:72-99`) + `rotate_refresh` (`:170-179`): branch `is_active==False` → `auth.account_deleted` if `deleted_at` else `auth.account_suspended` (replaces generic `auth.inactive` at `:175`).
  - `apps/backend/app/core/errors.py` — register `auth.account_suspended`, `auth.account_deleted`, `user.deleted_irreversible`, `account.access_revoked`.
  - `apps/backend/tests/test_suspend_reinstate.py`, `apps/backend/tests/test_auth_suspended_codes.py` (new)
- **TDD steps:**
  1. **FIRST write** `test_suspend_revokes_and_audits` — suspend a user → `is_active==False`, all refresh tokens revoked (`revoke_all_refresh_tokens`), `deleted_at IS NULL`, `admin.user.suspend` audit (reason/note/ip/ua), notification queued with taxonomy **label** (not free-text note) (FR-SUSP-04).
  2. `test_suspended_login_returns_suspended_code` — suspended user authenticates → `auth.account_suspended` (not `auth.inactive`); refresh → same.
  3. `test_reinstate_restores_active_not_tokens` — reinstate → `is_active==True`, no refresh tokens restored, `admin.user.reinstate` audit; idempotent (no duplicate audit on no-op) (FR-SUSP-02).
  4. `test_reinstate_refused_on_tombstone` — target with `deleted_at IS NOT NULL` → **422** `user.deleted_irreversible` (ADR-0030 §D3).
  5. `test_deleted_login_returns_deleted_code` — tombstoned user authenticates → `auth.account_deleted`.
  6. `test_suspend_last_active_admin_blocked` — reuse S6.6 invariant → **422** `user.last_admin_active`.
  7. Implement service + auth branching + error codes + notification. Green.
- **Migrations:** none (uses `users.deleted_at` from 0030 + `is_active`).
- **Acceptance criteria:** Given an active user, When suspended, Then `is_active=false`, refresh tokens revoked, `deleted_at` null, audit+notification (label only); Given a suspended user, When they log in, Then `auth.account_suspended`; Given a tombstoned user, When admin reinstates, Then **422** `user.deleted_irreversible`; Given a tombstoned user, When they log in, Then `auth.account_deleted`.
- **Risk/notes:** Suspension shares the `is_active` mechanism (already re-checked at `deps.py:49`, `auth.py:80`, `auth.py:174`); the **only** discriminator is `deleted_at IS NULL`. Notify with the taxonomy **label**, never the admin's raw note (FR-SUSP-04). Keep the dummy-hash timing-flatten in `authenticate` for the no-such-user case (`auth.py:85`).

---

### S6.8 — `delete_account` choreography + cooperative cancellation (ADR-0030 §D2/§D4, R-S10)

One-line goal: move `DELETE /me` into an atomic `account.delete_account` service implementing the full R-M3′ anonymize-in-place choreography with try-guarded sibling steps, plus the `assert_account_active` cooperative-cancellation helper wired at the streaming heartbeat and build/clone fences.

- **Files:**
  - `apps/backend/app/services/account.py` (new) — `delete_account(db, *, user, password, ip, user_agent)`, `assert_account_active(db, user_id)`.
  - `apps/backend/app/repositories/users.py` — `purge_refresh_tokens(db, user_id)` (hard delete after revoke), `mark_deleted(db, user)`.
  - `apps/backend/app/api/v1/users.py` — `delete_me` (`:194-216`) slimmed to call the service + clear `__Host-access`/`__Host-refresh` cookies.
  - `apps/backend/app/workers/tasks/tutor_streaming.py` — wire `assert_account_active` at the heartbeat near `:86`.
  - `apps/backend/app/services/authoring_orchestrator.py` (+ S4 clone service when present) — `assert_account_active` at phase fences.
  - `apps/backend/tests/test_delete_account.py`, `apps/backend/tests/test_cooperative_cancel.py` (new)
- **TDD steps:**
  1. **FIRST write** `test_delete_account_scrubs_core_pii` — delete with correct password → `email == f"deleted-{id}@lumen.invalid"`, `full_name==""`, `avatar_url/bio==None`, `password_hash` unusable, `email_verified_at==None`, `is_active==False`, `deleted_at` set, `user.deleted` audit written **before** scrub (actor=self, ip/ua).
  2. `test_delete_account_wrong_password_401` — wrong password → **401** `auth.invalid_credentials`, nothing scrubbed (transaction rolls back).
  3. `test_delete_account_purges_sessions` — refresh tokens revoked **and** hard-deleted (`purge_refresh_tokens`) — assert zero rows remain.
  4. `test_delete_account_delists_owned_courses` — owner with a public course → course `visibility==private`, soft-deleted (`deleted_at`), `moderation_state` **unchanged-but-delisted/sticky** (R-C2); other users' enrollments/certs on that course preserved (FR-DEL-02).
  5. `test_delete_account_tolerant_of_missing_sibling_tables` — mock `user_llm_credentials` / provenance columns absent (raise `ProgrammingError`/`UndefinedTable`) → core scrub still succeeds, optional steps no-op (ADR-0030 open-risk 1: guards catch only `ProgrammingError`/`UndefinedTable`/`ImportError`, never blanket `Exception`).
  6. `test_delete_account_soft_deletes_authored_discussions_reviews` — user's discussions/replies/reviews get `deleted_at`, author pointer kept at the tombstone.
  7. **FIRST write** `test_cooperative_cancel_streaming` — suspend a user mid-stream → next heartbeat `assert_account_active` raises `ForbiddenError(code="account.access_revoked")` and the SSE stream closes; `test_cooperative_cancel_build_fence` — flip `is_active` between authoring phases → the orchestrator aborts the phase, no partial course persists.
  8. Implement service (the 11-step D2 order: authn → audit-first → scrub PII + `deleted_at` → deactivate → purge sessions → [guarded] BYOK purge → MCP revoke → owned-course delist+soft-delete → provenance anonymize → discussion/review soft-delete), the helper, the endpoint slim-down + cookie clear, the worker/orchestrator wiring. Green.
- **Migrations:** none (uses 0030).
- **Acceptance criteria:** Given a user with correct password, When they `DELETE /me`, Then PII is irreversibly scrubbed, `deleted_at` set, sessions purged, owned public courses delisted+soft-deleted, other users' enrollments preserved, auth cookies cleared, all in one transaction; Given missing sibling tables, Then core scrub still succeeds; Given a suspended user mid-stream/mid-build, Then the in-flight job aborts with `account.access_revoked`.
- **Risk/notes:** Core PII scrub + deactivate is **un-guarded** (must succeed or the whole transaction rolls back — no half-tombstone); only the sibling-table steps are try-guarded with **narrow** exception types. Provenance anonymization is **read-time** too (DR-19) — even if the one-time snapshot scrub didn't run, the serializer renders "a deleted user" when `origin_owner.deleted_at IS NOT NULL` (covered in S6.10). `assert_account_active` is the R-S10 checklist primitive — every future foreground LLM feature must adopt it (CHARTER risk).

---

### S6.9 — `authors` platform stat (FR-ADMIN-05)

One-line goal: replace the role-derived `instructors` count with `admins` (`role==admin`) + `authors` (`COUNT(DISTINCT owner_id)` over non-deleted courses).

- **Files:**
  - `apps/backend/app/api/v1/admin.py` — `PlatformStatsOut` (`:391-401`) + `platform_stats` (`:402-411`): drop the `instructors` query (`role IN (instructor, admin)`), add `admins` (`role==admin`) and `authors` (`COUNT(DISTINCT Course.owner_id) WHERE deleted_at IS NULL`).
  - `apps/backend/tests/test_admin_stats.py` (extend existing).
- **TDD steps:**
  1. **FIRST update** `test_admin_stats.py` — seed an admin + several users owning courses (some soft-deleted) → assert `admins == 1`, `authors == COUNT(DISTINCT owner_id over live courses)`, and the response **no longer contains** `instructors` keyed on `role IN (instructor, admin)`.
  2. Implement the query change. Green.
- **Migrations:** none.
- **Acceptance criteria:** Given seeded users/courses, When GET `/admin/stats`, Then `admins` = active+inactive `role==admin` count and `authors` = distinct owners of non-deleted courses (not role-derived); `instructors` field is gone/renamed.
- **Risk/notes:** OpenAPI-visible field change — must ship with the TS client/`admin/page.tsx` stat + i18n key (`admin.stat.instructors → admin.stat.authors`) in the **same PR** or the dashboard renders `undefined` (FR-ADMIN-05, ADR-0025 risk 6). Pairs with S6.11 frontend.

---

### S6.10 — `DeletedUserName` serialization (DR-19 read-time anonymization)

One-line goal: any author/owner-bearing DTO renders the localized "a deleted user" label at read time when the underlying row is tombstoned, robust to migration ordering.

- **Files:**
  - `apps/backend/app/schemas/user.py` (`UserOut`) and author-bearing DTOs (`ReviewOut`, `DiscussionOut`, course-provenance "Based on …") — serializer rule: tombstoned (`deleted_at IS NOT NULL`) or sentinel snapshot → emit `common.deletedUser` key / `""` + frontend resolves.
  - `apps/backend/tests/test_deleted_user_rendering.py` (new)
- **TDD steps:**
  1. **FIRST write** `test_review_of_deleted_author_renders_label` — tombstoned author's review DTO → name resolves to the deleted-user label, email never exposed beyond the masked tombstone.
  2. `test_provenance_of_deleted_origin_owner` (DR-19) — clone whose `origin_owner.deleted_at IS NOT NULL` → "Based on … a deleted user" **even if** the one-time snapshot scrub didn't run (read-time, not one-time).
  3. Implement serializer branches. Green.
- **Migrations:** none.
- **Acceptance criteria:** Given a tombstoned author, When any author-bearing DTO serializes, Then the name renders as the localized deleted-user label and PII is not exposed; Given a clone whose origin owner is deleted (snapshot scrub absent), Then provenance still reads "a deleted user" (read-time guarantee).
- **Risk/notes:** Read-time rendering (DR-19) closes the GDPR-ordering gap (deletion before provenance columns landed). Single-sourced via the `common.deletedUser` i18n key (ADR-0030 §D5). Coordinate with S4's provenance serializer.

---

### S6.11 — Admin moderation frontend + user-mgmt UI + `authors` stat (FR-MOD-15, FR-ADMIN-01/04/08)

One-line goal: ship `/admin/moderation` (queue + reports + actions), reshape `/admin/users` to grant/revoke-admin toggle + suspend/reinstate with `{user, admin}` role, the moderation badges on `/admin/courses`, the `authors` stat, and wire `/profile` delete to `DELETE /me`.

- **Files:**
  - `apps/frontend/src/app/admin/moderation/page.tsx` (new) — queue + reports tabs, approve/reject/delist/relist/remove + resolve actions, confirmation on remove (FR-MOD-15).
  - `apps/frontend/src/app/admin/users/page.tsx` — `AdminUser` role union → `"user" | "admin"`; replace role `<Select>` (currently `student|instructor|admin`) with grant/revoke-admin toggle (confirmation) + suspend/reinstate; **disable self-row** grant/revoke/suspend controls (FR-ADMIN-01); handle mid-session **403** gracefully (FR-ADMIN-08).
  - `apps/frontend/src/app/admin/page.tsx` — add `/admin/moderation` tile; change `admin.stat.instructors` → `admin.stat.authors`.
  - `apps/frontend/src/app/admin/courses/page.tsx` — visibility/moderation/removed badges + row actions delist/relist/remove (FR-MOD-15).
  - `apps/frontend/src/app/profile/page.tsx` — wire existing delete section to `DELETE /api/v1/me`; on success `queryClient.clear()` + hard-redirect to `/`; revise copy to anonymize-in-place (ADR-0030 frontend).
  - `apps/frontend/src/lib/query/keys.ts` — add `moderationQueue: ["admin","moderation","queue"]`, `reports: ["admin","reports"]`, `courseModeration: (id) => ["course", id, "moderation"]`.
  - `apps/frontend/src/lib/api/types.ts` (hand-written — **do NOT regenerate**, DR-5) — add `Visibility`/`ModerationState` unions, `ModerationQueueItem`, `ReportOut`, `CourseAdminOut`, `PlatformStats.authors`.
  - `apps/frontend/src/lib/i18n/messages/en.ts` + `ar.ts` (parity-enforced) — `admin.moderation.*`, `admin.tile.moderation.*`, `admin.user.grantAdmin/revokeAdmin/suspend/reinstate/confirm*`, `admin.stat.authors`, `common.deletedUser`, error-code copy (`user.lastAdmin`, `course.notListable`, `report.*`, `auth.accountSuspended/Deleted`), and revised `profile.delete.*` (ADR-0030 §i18n).
  - `apps/frontend/tests/admin-moderation.test.tsx`, `apps/frontend/tests/admin-users-toggle.test.tsx` (new, Vitest).
- **TDD steps:**
  1. **FIRST write** `admin-users-toggle.test.tsx` — render `/admin/users`; assert role options are exactly `{user, admin}`; assert the current admin's **own row** grant/revoke + suspend controls are disabled; assert grant shows a confirmation step.
  2. `admin-moderation.test.tsx` — render `/admin/moderation`; assert pending queue renders, remove action requires confirmation, resolve actions present; reported note rendered as inert text (no `dangerouslySetInnerHTML`).
  3. i18n parity test (existing harness) stays green after adding the keys to both `en.ts` and `ar.ts`.
  4. Implement pages/components/keys/types; verify `tsc` + eslint clean. Green.
  5. **Live-as-a-user browser check** (Gate C, Playwright + manual): sign in as **admin**, drive `/admin/users` (grant/revoke toggle, last-admin block surfaced, suspend/reinstate), `/admin/moderation` (queue → approve/reject/delist/relist/remove with confirm; reports → resolve), `/admin/courses` (badges); sign in as a **user**, file a report on a public course; sign in as the **target user**, confirm `DELETE /me` from `/profile` signs out and anonymizes. Capture authenticated screenshots per the post-deploy-visual-coverage memory (admin + user surfaces, not public-only).
- **Migrations:** none.
- **Acceptance criteria:** Given an admin in the browser, When they open `/admin/moderation`, Then the pending queue + reports render and each action (incl. confirm-on-remove) drives the backend and optimistically reflects state; Given the admin's own row in `/admin/users`, Then grant/revoke/suspend controls are disabled; Given a user, When they delete their account from `/profile`, Then they are signed out and their public courses leave the catalog; en and ar both render the new surfaces with RTL + AA (focus trap, keyboard, `aria-live` for "submitted for review").
- **Risk/notes:** `types.ts` is **hand-written** — never `make api-client` (DR-5); update it in the same PR + rely on the CI openapi-vs-types drift check. All net-new controls meet AA (FR-A11Y-05): destructive confirmations keyboard-reachable, focus-trapped, `useReturnFocus`, `aria-live`. Reported content rendered inert (FR-MOD-13). Admin gate is defense-in-depth (FR-ADMIN-08) but the authoritative gate is backend `RequireAdmin`.

---

## Stream-level gate (done = all true)

1. **Unit/integration green:** `make test.api` and `make test.web` pass, including every FIRST-written test above (cascade introspection, moderation transitions, quarantine, report account-age gating + coalescing + rate limits, atomic report-resolve, last-admin invariant, suspend/reinstate codes, `delete_account` choreography + try-guard tolerance + cooperative cancellation, `authors` stat, deleted-user read-time rendering, admin-cannot-edit-others regression).
2. **CI grep-guard (S2's `test_no_raw_published_checks`) stays green** — every S6 reportability/listing decision routes through `visibility.is_publicly_listed`/`publicly_listed_sql`, no raw `status==published`.
3. **No N+1** on `/admin/courses/moderation-queue` and `/admin/reports` (eager-load owner/subject; query-count assertion).
4. **OpenAPI ↔ hand-written `types.ts` drift check passes** (DR-5) — endpoints + schemas added, `types.ts` updated in lockstep, `tsc`+eslint clean.
5. **Live-as-a-user browser evidence (Gate C):** with `make up`, signed in as **admin** drive the full moderation + user-mgmt surface (grant/revoke toggle, last-admin 422 surfaced, suspend/reinstate, queue approve/reject/delist/relist/remove with confirm, report resolve, course badges); signed in as a **user** file a report and delete the account from `/profile` (sign-out + anonymize verified); en + ar (RTL) + keyboard/a11y pass on the new controls. Screenshots captured for the authenticated admin + user surfaces (post-deploy-visual-coverage memory).
6. **Account-lifecycle invariants demonstrated end-to-end:** suspend a user mid-stream → in-flight tutor stream closes with `account.access_revoked`; delete an owner → their public course leaves the catalog while another user's enrollment on it survives.

---

## Traceability

- **FR (requirements spec):** FR-MOD-01..15 (state machine, queue, delist/relist/reject/remove, resubmit, safety-check selection via S2, `CourseReport`+report flow, report-resolve atomicity, inert content, admin UI); FR-ADMIN-01..08 (grant/revoke toggle, legacy `/role` normalize+422, last-admin invariant, `UserAdminOut` `{user,admin}`, `authors` stat, MCP gate adjacency, observability retained, defense-in-depth gate); FR-SUSP-01..04 (suspend/reinstate, refresh revoke, audit, distinct `auth.account_suspended` code); FR-DEL-01..03 (provenance/clone survival, owned-course delist, independent lesson ids preserved by anonymize-in-place + cascade fix); FR-AUDIT-01/02/03 (`admin.user.grant_admin/revoke_admin/suspend/reinstate`, `admin.course.*`, `course.report`, `course.report_resolved`, `user.deleted`); FR-A11Y-05 / FR-I18N-01 (net-new controls AA + en/ar parity); FR-MIG (additive 0034); FR-VIS-13 (grandfather + hard-removal revoke).
- **R / DR (resolutions — authoritative):** R-M3′/R-M13/R-M13′ (anonymize-in-place + provenance erasure), R-CAP (revocation = suspension only, no capability-override table), R-S10 (cooperative cancellation), R-S11 (auto-action never delists approved), R-C2 (sticky moderation_state), R-C6′ (quarantine vs severe_abuse access split), R-U5 (fail-closed classifier selection — built in S2, consumed here), **DR-6/DR-6-R2** (ORM cascade fix scope = `courses_owned` only), **DR-18-R2** (`courses.quarantined` single-source-of-truth for csam/illegal), **DR-19** (read-time provenance anonymization), **DR-20** (report brigading: account-age + email-verified gating + per-course rate limit), **DR-5** (hand-written `types.ts`, no `make api-client`).
- **ADR:** ADR-0025 (role↔capability — last-admin/grant-revoke, `authors` stat, `_can_edit_course` narrowing direction), ADR-0026 (visibility/moderation state machine + central authorizer — moderation transitions, queue, `set_course_featured` gate), ADR-0030 (account lifecycle — anonymize-in-place choreography, ORM cascade fix, suspend/reinstate discriminator, cooperative cancellation, auth codes).
- **CHARTER:** §3 decisions 6 (admin scope: user mgmt + catalog moderation state machine + report flow + immutable audit), 8 (phased zero-downtime — additive 0034 + 0030 tolerance), 10 (account/course deletion semantics).
- **Migrations owned/verified by S6:** **0034** (`course_reports`, additive). Verified-from-S7-pre: **0030** (`users.deleted_at` + cascade fix). Consumed-from-S2: **0033** (`moderation_events`), **0044** (`courses.quarantined`).


<!-- ===== S7 ===== -->

# Stream S7: Cross-cutting — contract, i18n/a11y, eval, traces, runbook, docs

## Preconditions / depends-on (other streams, by Sx)

- **S7-pre is owned partly here but precedes everything**: the design's build order (`design §6` step 1) puts migration **0030** (`account_lifecycle_users_deleted_at`), the redaction filter, `secrets_crypto.py`, KEK boot guard, and the ORM cascade fix in "S7-pre". Those are tracked in S1/S5/S6 plans (cascade → S6 deletion, crypto → S5). **This S7 plan owns only the genuinely cross-cutting, end-of-build close-out work** (`design §6` step 8 "S7-post"): contract-drift CI (DR-5), `parent_message_id` migration 0045 + backfill (DR-2), full i18n/a11y parity pass, eval CI gate (R-U6), the phased-migration RUNBOOK (DR-12), CHANGELOG/ADR finalization, OpenAPI regen, and the consolidated 0030–0045 rev-list.
- **S1 (role collapse)** must be merged before S7's i18n role-key pass and a11y persona shim: the frontend `Role` union becomes `"user" | "admin"` and the a11y spec's `teacher@`/`student@` logins must be reconciled to the `user` persona (FR-A11Y-03). S7's `types.ts` `Role` change (DR-5) is *coordinated with* S1's enum change but the contract-drift **check** can land independently.
- **S2 (visibility), S3 (goal intake), S4 (clone), S5 (BYOK), S6 (admin)** must all be merged before S7's terminal passes (eval gate baseline capture, full en/ar parity audit, axe over every net-new surface, OpenAPI regen, CHANGELOG/ADR finalize) — these are by definition "all new surfaces exist now" gates. Individual S7 tasks below are ordered so the *infrastructure* (drift check, fixture-replay harness, runbook skeleton) lands early and the *terminal audits* land last.
- **Migration-chain dependency**: S7's migration **0045** has `down_revision="0044"` (`courses.quarantined`, S2/S6 per DR-18-R2). If 0044 has not landed when S7 builds, 0045 chains off whatever the current head is — the rev-list consolidation task (S7.10) is the authority that reconciles the final linear chain.

---

## Ordered tasks

### S7.1 — CI contract-drift check: committed `openapi.json` vs freshly generated (DR-5)

One-line goal: fail CI when the backend OpenAPI schema drifts from the committed snapshot, so hand-written `types.ts` stays a deliberate same-PR edit (never auto-regenerated).

**Files**
- create `apps/backend/openapi.json` (commit the canonical snapshot; does not exist today — verified via `find`)
- change `.github/workflows/ci.yml` — add a `contract-drift` step inside the existing `backend` job (it already has Postgres/Redis/uv set up)
- create `apps/backend/tests/test_openapi_snapshot.py` (local mirror so devs catch drift before CI)
- change `Makefile` — add `make openapi.check` (diff committed vs freshly exported)
- change `apps/frontend/src/lib/api/types.ts` line 1 comment: strike the `regenerate via pnpm openapi:generate` claim → "hand-written; keep in sync with the backend enum in the same PR; CI `contract-drift` guards `openapi.json`."

**TDD steps**
1. FIRST write `apps/backend/tests/test_openapi_snapshot.py::test_committed_openapi_matches_app` — imports `app.main.app`, calls `app.openapi()`, normalizes (sort keys, drop volatile `servers`/version-stamp fields), reads `apps/backend/openapi.json`, asserts deep-equal. Assert it **fails** before the snapshot exists / when stale.
2. Implement: run `make openapi.local` (or the in-container `make openapi`) to mint `apps/backend/openapi.json`; commit it. Add `make openapi.check` = export to a temp path + `diff` (non-zero exit on drift).
3. Green: `uv run pytest tests/test_openapi_snapshot.py` passes; `make openapi.check` exits 0.
4. Add the CI step to `ci.yml` `backend` job after Pytest: `- name: OpenAPI contract drift` → `uv run python -m scripts.export_openapi --out /tmp/openapi.fresh.json --pretty && diff <(jq -S . openapi.json) <(jq -S . /tmp/openapi.fresh.json)`. Failing diff → red.

**Migrations**: none.

**Acceptance criteria**
- *Given* a PR that changes an endpoint's response model but not `openapi.json`, *When* CI runs the `backend` job, *Then* the `OpenAPI contract drift` step fails with a unified diff naming the drifted path.
- *Given* `types.ts`'s `Role` is `"student"|"instructor"|"admin"` while the backend enum is `user|admin` (post-S1), *When* a reviewer reads the same PR, *Then* both files changed together (the check guards the schema; the test in S1 guards the union — see S7.2).

**Risk/notes**
- **Do NOT add `make api-client` to CI** — DR-5 is explicit: `types.ts` is hand-written and `pnpm openapi:generate` would clobber the curated file. The check *diffs*, it never *writes*.
- `app.openapi()` may embed a build-time version; normalize it out so the snapshot is stable across releases.
- `export_openapi.py` sets harmless dev env defaults at import (`ENV=development`, dummy secrets) so it runs without a DB — confirmed lines 27-30.

---

### S7.2 — `types.ts` Role union + frontend drift guard (DR-5, coordinates with S1)

One-line goal: bring the hand-written TS contract in line with the two-role enum and pin it with a unit test so a future edit can't silently desync.

**Files**
- change `apps/frontend/src/lib/api/types.ts:3` — `export type Role = "user" | "admin";`
- change consumers of `Role` (grep `"student"|"instructor"` in `src/`): `admin/users/page.tsx:37` union (per CHARTER §6a) and any narrowing
- create `apps/frontend/tests/api-role-contract.test.ts`

**TDD steps**
1. FIRST write `apps/frontend/tests/api-role-contract.test.ts` — a `tsd`-style/type-level assertion that `Role` extends `"user" | "admin"` exactly (no `"student"`/`"instructor"`), plus a runtime list assertion `expect(ALL_ROLES).toEqual(["user","admin"])` against an exported const. Fails against today's union.
2. Implement: edit `types.ts:3`; introduce/align `ALL_ROLES`; fix consumers until `pnpm typecheck` is clean.
3. Green: `pnpm exec vitest run api-role-contract` + `pnpm typecheck`.

**Migrations**: none.

**Acceptance criteria**
- *Given* the two-role enum, *When* `pnpm typecheck` runs, *Then* no file references `"student"`/`"instructor"` as a `Role` member.
- *Given* someone re-adds `"instructor"` to `Role`, *When* vitest runs, *Then* `api-role-contract.test.ts` fails.

**Risk/notes**
- Must land in lockstep with S1's backend enum + S1's `i18n role keys` change. If S1 ships a transition shim accepting legacy values at the wire (Phase A), the *type* can narrow to `user|admin` immediately (frontend never authored legacy roles) — verify against S1's `normalize_role`.

---

### S7.3 — `agent_traces.parent_message_id` self-FK migration 0045 (DR-2 / DR-21)

One-line goal: add the additive nullable FK that lets `learner_traces` swap its 120s temporal window for an exact lookup, per the documented TODO at `services/learner_traces.py:39`.

**Files**
- change `apps/backend/app/models/agent_trace.py` — add `parent_message_id: Mapped[str | None]` FK → `tutor_messages.id` `ondelete="SET NULL"`, nullable; add `Index("ix_agent_traces_parent_message_id", "parent_message_id")`
- create `apps/backend/alembic/versions/2026_07_..._0045-0045_agent_traces_parent_message_id.py`
- update `apps/backend/app/models/__init__.py` re-export only if needed (model already exported)
- change `apps/backend/app/services/learner_traces.py` — add an exact-FK fast path (`AgentTrace.parent_message_id == message_id`) that falls back to the temporal window when the column is NULL on legacy rows (do NOT rip out the window — backfill is best-effort)

**TDD steps**
1. FIRST write `apps/backend/tests/test_learner_traces_parent_message.py`:
   - `test_exact_fk_path_used_when_set` — insert a `TutorMessage` (assistant) + `AgentTrace` rows with `parent_message_id` set; assert `build_learner_trace_timeline` (or the existing service entry) returns exactly those rows and *ignores* a decoy sibling trace inside the 120s window but with a different `parent_message_id`.
   - `test_temporal_fallback_when_null` — legacy traces (`parent_message_id IS NULL`) still resolve via the window.
   - `test_parent_message_id_nullable_and_set_null_on_message_delete` — deleting the message nulls the FK (no cascade of the trace).
2. Implement migration `0045` (`down_revision` = current head, expected `0044`): `op.add_column("agent_traces", sa.Column("parent_message_id", sa.String(21), nullable=True))`; `op.create_foreign_key(..., "tutor_messages", ["parent_message_id"], ["id"], ondelete="SET NULL")`; `op.create_index("ix_agent_traces_parent_message_id", ...)` via `CREATE INDEX CONCURRENTLY` in an `autocommit_block()` with `IF NOT EXISTS` (re-runnable per §2.5 convention). **Backfill (best-effort, same migration, batched):** for each assistant `tutor_message`, `UPDATE agent_traces SET parent_message_id = m.id WHERE agent_traces.user_id = (conversation.user_id) AND feature LIKE 'tutor%' AND created_at BETWEEN m.created_at - interval '120 seconds' AND m.created_at AND parent_message_id IS NULL` — i.e. exactly the window join from `learner_traces._TRACE_WINDOW_SECONDS`. Where the window matches >1 message, leave NULL (ambiguous → temporal fallback stays correct).
3. Then update `learner_traces.py` to prefer the FK; run the test green.

**Migrations**: **0045** (`agent_traces_parent_message_id`).
- up: add nullable column + FK (`SET NULL`) + concurrent index + best-effort batched backfill.
- down: drop index (`IF EXISTS`), drop FK, drop column. **Clean/reversible.**
- Zero-downtime: additive nullable column; old pods never write it; backfill is non-blocking (batched, no long lock); `SET NULL` FK means a `tutor_messages` delete can't break inserts. Safe on any deploy (DR-12 "additive ⇒ safe").

**Acceptance criteria**
- *Given* a turn where traces carry `parent_message_id`, *When* the H7 admin/learner trace timeline renders, *Then* it shows exactly that turn's traces with no temporal-window false-positives.
- *Given* pre-0045 legacy traces, *When* the timeline renders, *Then* the 120s window still resolves them (no regression).
- *Given* `alembic downgrade -1` from 0045, *Then* the column/FK/index are gone and the service silently uses the window again.

**Risk/notes**
- DR-2 phrasing says "tutor message/trace row"; the verified target is `agent_traces` (the model with the TODO + the existing `parent_trace_id` self-FK). The new column links a trace to its owning `tutor_messages` row — distinct from the existing `parent_trace_id` (trace→trace tree) and `parent_call_id` (trace→llm_call). Name it `parent_message_id` to match the TODO verbatim.
- IDs are 21-char nanoid → `sa.String(21)` (CLAUDE.md convention), matching `tutor_messages.id`.
- This is additive; it does **not** require any API-surface change (the docstring promised "no API surface change") — keep response DTOs identical.

---

### S7.4 — Eval regression gate on recorded fixtures, epsilon 0.30 (R-U6)

One-line goal: a deterministic CI eval gate that replays **recorded** judge fixtures (no live Groq) and fails only on a real regression beyond ε=0.30 on the 1–5 axis-mean scale.

**Files**
- create `apps/backend/evals/fixtures/<suite>/recorded.jsonl` (one per suite: tutor/authoring/ingest) — frozen `(question, primary_answer, judge_scores)` triples captured from a known-good run
- create `apps/backend/app/evals/fixture_gate.py` — loads recorded fixtures, recomputes axis means via the existing `compute_summary` (`reports.py:97`), compares against a committed baseline summary, fails if any axis-mean OR `mean_overall` drops by `> EVAL_EPSILON` (0.30); Groq-unavailable path is irrelevant here (no live calls) but a `--mode live` escape hatch marks **inconclusive** on outage (R-U6)
- create `apps/backend/evals/fixtures/baseline-summary.json` (committed per-suite expected means)
- create `apps/backend/tests/test_eval_fixture_gate.py`
- change `.github/workflows/ci.yml` — add an `eval-gate` step in the `backend` job (deterministic, no external keys), OR a tiny standalone job; document ε in ADR (S7.9)
- reuse `apps/backend/app/evals/reports.py::compute_summary` and `judge.py::JudgeScore` shapes (do not duplicate the rollup math)

**TDD steps**
1. FIRST write `apps/backend/tests/test_eval_fixture_gate.py`:
   - `test_passes_within_epsilon` — recorded scores equal to baseline → exit 0.
   - `test_fails_on_regression_beyond_epsilon` — synthetic fixture with one axis 0.31 below baseline → raises/exits non-zero with the offending axis named.
   - `test_passes_within_epsilon_boundary` — exactly 0.30 below → still pass (ε inclusive).
   - `test_live_outage_marks_inconclusive` — when invoked with a stubbed provider that raises Groq-unavailable, gate returns `inconclusive`, not `fail` (R-U6).
2. Implement `fixture_gate.py` using `compute_summary` + `EVAL_EPSILON = 0.30` (sourced from a `Settings` field `eval_regression_epsilon` defaulting 0.30 so it's documented and tunable).
3. Capture recorded fixtures: run the existing `run_baseline` once against the seeded dataset with the noop/deterministic provider (or a one-time real run), freeze the judge outputs into `recorded.jsonl`, and snapshot the summary into `baseline-summary.json`.
4. Green: `uv run pytest tests/test_eval_fixture_gate.py`; wire the CI step (`python -m app.evals.fixture_gate --suite tutor authoring ingest`).

**Migrations**: none.

**Acceptance criteria**
- *Given* recorded fixtures matching the committed baseline, *When* CI runs the eval gate, *Then* it passes with zero external API calls (deterministic).
- *Given* a code change that drops tutor `groundedness` mean by 0.4 (re-recorded fixtures), *When* the gate runs, *Then* it fails naming `tutor.groundedness Δ=-0.40 > ε=0.30`.
- *Given* the live (nightly) variant and a Groq 503, *When* the live eval runs, *Then* it reports **inconclusive** and does not fail the gate (R-U6).

**Risk/notes**
- The existing `eval-baseline.yml` is a **live, operator-driven, prod-SSH** workflow — leave it as the separate nightly/manual live path (R-U6 explicitly separates the two). S7.4 adds the *deterministic CI fixtures* path; do not entangle them.
- ε is on the **1–5 judge scale** (R-U6); `JudgeScore.overall` averages axes (`judge.py:104-112`), `compute_summary` rounds to 4dp — compare with a tolerance-aware `<= -epsilon` test, not float equality.
- Document ε=0.30 in the eval ADR (R-U6 + R-G2 require it documented) — see S7.9.

---

### S7.5 — i18n en+ar key parity for all net-new keys + RTL via logical properties (FR-I18N-04, R-U8)

One-line goal: every key added by S2–S6 exists in both `en.ts` and `ar.ts`, the parity test gates equality, RTL renders correctly with logical properties, and a `translation_status` tracks quality without asserting it.

**Files**
- change `apps/frontend/src/lib/i18n/messages/en.ts` + `ar.ts` — add every net-new key (visibility, clone/remix, goal-intake/define-build, BYOK, moderation, account-lifecycle, two-role labels) in both locales; flip legacy `student`/`instructor` copy to the two-role wording
- change `apps/frontend/tests/i18n-parity.test.ts` — extend with: no-key-echo (already present), non-empty (present), and add an RTL-marker assertion + a `translation_status` presence check (R-U8)
- create/extend `apps/frontend/src/lib/i18n/locales.ts` — add `translation_status: "human" | "mt-draft"` metadata per locale (R-U8)
- audit `apps/frontend/src/components/**` for any physical CSS (`ml-`, `mr-`, `left-`, `right-`, `pl-`, `pr-`) on new surfaces → swap to logical (`ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-`) for RTL (FR-I18N-04)

**TDD steps**
1. FIRST extend `i18n-parity.test.ts`:
   - the existing `arKeys ≡ enKeys` assertion now fails the moment S2–S6 add EN-only keys.
   - add `test("no physical-direction utility classes leak into RTL-critical new components")` — a static scan over the new component dirs asserting no `\b(ml|mr|pl|pr|left|right)-` on flagged files (allowlist exceptions).
   - add `test("each locale declares a translation_status")`.
2. Implement: add the Arabic translations, set `translation_status: "mt-draft"` where not human-reviewed; fix logical-property violations.
3. Green: `pnpm exec vitest run i18n-parity` + the RTL Playwright check in S7.6.

**Migrations**: none.

**Acceptance criteria**
- *Given* any net-new EN key from S2–S6, *When* vitest runs, *Then* it fails until the AR key exists, is non-empty, and isn't a key-echo.
- *Given* `dir="rtl"` (Arabic), *When* a new surface renders, *Then* spacing/alignment mirror correctly (logical properties; verified visually in S7.6).
- *Given* an MT-only Arabic string, *When* a reviewer reads `locales.ts`, *Then* `translation_status: "mt-draft"` flags it for sign-off (quality not auto-asserted, R-U8).

**Risk/notes**
- `en.ts` is 1073 lines of flat dotted keys (verified) and `ar.ts` mirrors it; the `Record<MessageKey, string>` type already gives compile-time parity — the runtime test is belt-and-suspenders (file comment says so).
- Don't assert Arabic *quality* in CI (R-U8) — only key-set equality, non-empty, no-echo, RTL-render, and the status field.

---

### S7.6 — axe WCAG 2.2 AA over every net-new surface + persona shim (FR-A11Y-03)

One-line goal: extend the existing axe gate to cover every surface S2–S6 added, run it under the three personas (admin + authoring user + learning user), and reconcile the legacy `teacher@`/`student@` logins to the `user` role during the transition.

**Files**
- change `apps/frontend/tests/e2e/accessibility.spec.ts` — add route blocks for: visibility/publish controls (S2 studio two-control), goal-intake → build flow (S3), clone/remix CTA + origin attribution (S4), BYOK settings (S5), admin moderation queue (S6); add an Arabic (`dir=rtl`) pass over the home + one authenticated surface (ties FR-I18N-04 → S7.5)
- change the `signIn` helper personas: `student@`/`teacher@` → the `user` persona shim (FR-A11Y-03) once S1 collapses roles; keep `admin@`
- coordinate with `.github/workflows/ci.yml` `accessibility` job (no workflow change needed — it runs the whole spec)

**TDD steps**
1. FIRST add the new `test.describe` blocks asserting `expect(violations).toEqual([])` on each net-new route under the right persona. These **fail** until each surface is reachable/clean.
2. Implement/triage: fix AA violations on the new surfaces (contrast, labels, focus order, tap targets — WCAG 2.2 AA new SCs like 2.5.8 target size). Prefer per-test `disableRules` with a `// TODO(a11y):` over a global ignore (spec comment mandates this).
3. Green: `pnpm exec playwright test tests/e2e/accessibility.spec.ts --project=chromium` locally then in CI.

**Migrations**: none.

**Acceptance criteria**
- *Given* every net-new surface (visibility, define-build, clone, BYOK, moderation), *When* the axe suite runs at `wcag22aa` + lower bars, *Then* zero AA violations.
- *Given* the three personas, *When* the suite signs in, *Then* the `user` persona reaches `/studio` and `/dashboard` (authoring + learning collapsed onto one role) and `admin@` reaches `/admin` (per post-deploy auth-gated coverage memory).
- *Given* the Arabic pass, *When* axe runs on `dir=rtl`, *Then* zero AA violations (no clipped/overlapping RTL text).

**Risk/notes**
- Memory [post-deploy-visual-coverage]: public-only captures do NOT gate `/studio`, `/admin/*`, `/dashboard/*` — must sign in per persona. This is the live-as-a-user half of the stream gate.
- The a11y job uses chromium-only by design (axe is browser-agnostic); keep it that way to avoid doubling wallclock.
- WCAG 2.2 AA effective date (2026-04-24) already locked in the spec header — keep `wcag22aa` in `WCAG_TAGS`.

---

### S7.7 — Migration-application RUNBOOK encoding the phased order (DR-12)

One-line goal: a deploy runbook that makes the phased, release-gated migration order explicit so an operator never blindly `make migrate` to head through the irreversible role-collapse.

**Files**
- create `docs/runbooks/two-role-migration.md` (alongside existing `incident-response.md`, `upgrade.md`)
- cross-link from `docs/runbooks/upgrade.md`

**TDD steps** (docs — verification is a reviewable checklist + a guard test)
1. FIRST write `apps/backend/tests/test_migration_phase_annotations.py` — parses every `alembic/versions/*.py` ≥ 0030, asserts each module docstring/marker declares its release phase (`Phase: A|B|C|D`) and that the irreversible 0031 has a documented no-op `downgrade` with a `# IRREVERSIBLE` marker (DR-12 / R-C4). Fails until annotations + runbook exist.
2. Implement the runbook with the exact phased sequence from `design §2.6` + `DR-12`:
   - **Phase A (Release 1):** deploy image accepting `{student,instructor,user,admin}`; apply **additive** migrations (0030, 0033 columns nullable-first, 0034, 0035, 0036, 0037, 0038, 0039, 0040, 0041 nullable, 0042, 0044, 0045) via explicit `alembic upgrade <rev>` per group; confirm API+worker boot (KEK guard, DR-7).
   - **Phase B:** `alembic upgrade 0031` (role data-collapse, **IRREVERSIBLE**, idempotent, logs count).
   - **Phase C (Release 2):** `alembic upgrade 0032` (default flip); deploy narrowed-enum image + normalization layer; flip `FEATURE_PRIVATE_PUBLISH_ENABLED` only **after** the authorizer image is confirmed up (DR-13 / R-S8′ step 4).
   - **Phase D (Release 3):** positive-evidence gate (R-C5′: zero legacy-role rows + no legacy MCP principals + ≥15-min token TTL elapsed) → `alembic upgrade 0043` (chunk model NOT NULL, DR-14 operator-confirmed model) + remove normalization layer.
   - Index builds note: `CREATE INDEX CONCURRENTLY` (DR-15), keep old `ix_courses_acl` until `EXPLAIN` confirms `ix_courses_listed`.
   - Rollback playbook: image-rollback only; **never `alembic downgrade` past 0031**; `moderation_events` never dropped (R-C2).
3. Green: the phase-annotation test passes; runbook reviewed against the consolidated rev-list (S7.10).

**Migrations**: documents 0030–0045; touches none directly (the annotation test forces each migration module to carry its phase marker — coordinate with the owning stream).

**Acceptance criteria**
- *Given* the runbook, *When* an operator follows it for a release, *Then* additive migrations apply in Phase A, role-collapse waits for Phase B, and the private-publish flag flips only post-authorizer-confirm.
- *Given* `test_migration_phase_annotations.py`, *When* a new ≥0030 migration lands without a `Phase:` marker, *Then* CI fails.
- *Given* a botched release, *Then* the runbook's rollback section forbids `downgrade` past 0031 and prescribes image-rollback.

**Risk/notes**
- DR-12 topology note: prod is **single-host docker-compose** (one API + one worker), so multi-pod read-skew reduces to JWT 15-min token drain — the runbook must say this so an operator doesn't over-engineer a fleet rollout.
- Memory [deploy-approval-reflex REMOVED]: prod env has no required reviewers; CI green ⇒ auto-deploy. The runbook covers the *migration phasing*, not an approval click.

---

### S7.8 — OpenAPI regen + commit (`make openapi`) after all streams land (DR-5)

One-line goal: regenerate and commit the canonical `openapi.json` so the contract-drift check (S7.1) is green against the final, all-streams API surface.

**Files**
- change `apps/backend/openapi.json` (regenerate)
- change `apps/frontend/src/lib/api/types.ts` (manual sync of any new DTOs S2–S6 introduced — hand-written, DR-5)
- change `apps/frontend/src/lib/api/endpoints.ts` if new endpoints were added (hand-written client surface)

**TDD steps**
1. FIRST confirm `tests/test_openapi_snapshot.py` (S7.1) **fails** because new endpoints (visibility, clone, BYOK, moderation, goal-intake, cancel-build) aren't in the committed snapshot.
2. Implement: `make openapi` (in-container) → commit `apps/backend/openapi.json`; hand-edit `types.ts`/`endpoints.ts` for any DTO/route the frontend consumes.
3. Green: `tests/test_openapi_snapshot.py` + `make openapi.check` + `pnpm typecheck` + S7.1 CI drift step all pass.

**Migrations**: none.

**Acceptance criteria**
- *Given* the merged S1–S6 API, *When* `make openapi.check` runs, *Then* zero drift.
- *Given* a frontend call to a new endpoint, *When* `pnpm typecheck` runs, *Then* it resolves against the hand-written `endpoints.ts`/`types.ts`.

**Risk/notes**
- Again: **never `make api-client`** (clobbers hand-written `types.ts`, DR-5). Regenerate only `openapi.json`; the TS side is curated by hand.
- This is a terminal task — run it after S1–S6 merge so the snapshot reflects the final surface.

---

### S7.9 — ADR finalization (0025–0030 cross-cut updates + eval ε) and DR/ADR reconciliation

One-line goal: fold the DESIGN-RESOLUTIONS corrections into the ADRs they supersede so the ADRs aren't left contradicting the authoritative resolutions, and document ε=0.30.

**Files**
- change `docs/adr/0026-course-visibility-moderation.md` — record DR-10 (archived semantics: frozen visibility, unarchive→`pending_review`), DR-18-R2 (`quarantined` column is single source of truth for csam/illegal; `moderation_events` audit-only for listing), DR-22 (flag = `feature_private_publish_enabled`)
- change `docs/adr/0027-byok-model-config.md` — DR-17 (`api_base` locked to registry), DR-22 (`byok.build_provider` naming)
- change `docs/adr/0030-account-lifecycle.md` — DR-6/DR-6-R2 (cascade fix is `User.courses_owned` ONLY → `save-update`; the "change all three" wording is superseded), DR-19 (read-time provenance anonymization)
- change `docs/adr/0029-rag-retrieval-acl.md` — DR-15 (online index builds + EXPLAIN gate), DR-18 (owner-branch `AND NOT quarantined`)
- create or extend the **eval ADR** (the eval gate's home — likely a new `docs/adr/0031-eval-regression-gate.md` from the template) documenting ε=0.30, fixtures-vs-live split, inconclusive-on-outage (R-U6 / R-G2)
- add the new ADR number to relevant PR descriptions per CLAUDE.md

**TDD steps** (docs)
1. FIRST add `apps/backend/tests/test_adr_consistency.py` (or a `docs`-lint) asserting: no ADR still says "change all three relationships" for the cascade (DR-6-R2); the eval ADR mentions `0.30`; `feature_private_publish_enabled` (not `feature_private_publish`) appears. Cheap grep-based test.
2. Implement the ADR edits + the eval ADR.
3. Green: the consistency test passes.

**Migrations**: none.

**Acceptance criteria**
- *Given* the ADRs post-finalization, *When* a future implementer reads ADR-0030, *Then* it matches DR-6-R2 (one relationship), not the over-corrected "all three".
- *Given* the eval ADR, *When* read, *Then* ε=0.30, fixtures-deterministic, live-separate, inconclusive-on-outage are all documented.

**Risk/notes**
- DESIGN-RESOLUTIONS stays authoritative on conflict (its header says so); finalizing the ADRs just removes the contradiction so they don't mislead. Add a one-line "Superseded-by: DR-x" pointer rather than rewriting wholesale where risky.

---

### S7.10 — Consolidated migration-chain rev-list 0030–0045 + chain-integrity guard

One-line goal: produce the single authoritative linear rev-list and a test that proves the `down_revision` chain is unbroken and collision-free from 0030 to head (0045).

**Files**
- change `docs/runbooks/two-role-migration.md` (append the canonical rev table) and/or create `docs/two-role-rebuild/MIGRATION-CHAIN.md`
- create `apps/backend/tests/test_migration_chain.py`

**TDD steps**
1. FIRST write `apps/backend/tests/test_migration_chain.py`:
   - `test_chain_is_linear_no_collisions` — load all `alembic/versions/*.py`, assert each `revision` is unique, each `down_revision` (≥0031) points at the immediately prior rev, exactly one head, and head == `0045`.
   - `test_irreversible_only_0031` — assert 0031 is the only migration with a no-op/raising `downgrade` (DR-12).
   - `test_no_duplicate_numbers` — guards against the historical ADR collisions (every ADR claimed 0030).
2. Implement: reconcile the actual versions dir to the spec §2.5 chain extended by DR-21 (0044 quarantined, 0045 parent_message_id); fix any `down_revision` drift left by parallel-stream merges.
3. Green: the chain test passes; the consolidated rev-list table matches.

**Migrations**: audits/locks 0030–0045; creates none.

The consolidated chain (authority = design §2.5 + DR-21):

| Rev | Name | Stream | Phase | Type |
|---|---|---|---|---|
| 0030 | account_lifecycle_users_deleted_at | S7-pre | A | additive |
| 0031 | role_collapse_backfill | S1 | B | **IRREVERSIBLE** data |
| 0032 | role_default_user | S1 | C | metadata |
| 0033 | course_visibility_moderation | S2 | A | additive (flag OFF) |
| 0034 | course_reports | S6 | A | new table |
| 0035 | clone_provenance | S4 | A | additive |
| 0036 | idempotency_keys | S4 | A | new table |
| 0037 | learning_briefs | S3 | A | new table |
| 0038 | byok_credentials | S5 | A | new table |
| 0039 | llm_calls_billing_mode | S5 | A | additive (PG17 fast-default) |
| 0040 | tutor_turn_credential_id | S5 | A | additive |
| 0041 | lesson_chunks_embedding_model | S2/RAG | A | additive (nullable) |
| 0042 | lesson_chunks_live_index | RAG | A | concurrent index |
| 0043 | lesson_chunks_model_not_null | RAG | D | gated tighten |
| 0044 | courses_quarantined | S2/S6 | A | additive (DR-18-R2) |
| 0045 | agent_traces_parent_message_id | **S7** | A | additive (DR-2/DR-21) |

**Acceptance criteria**
- *Given* the versions dir, *When* `test_migration_chain.py` runs, *Then* head==0045, chain is linear, no collisions, only 0031 irreversible.
- *Given* a stream merges out of order and leaves a dangling `down_revision`, *Then* the chain test fails in CI.

**Risk/notes**
- Historical hazard: ADR-0026/0027/0028/0030 ALL claimed 0030; ADR-0028 had a bogus `down_revision="0029_visibility"`. The single linear chain (§2.5) supersedes every per-ADR number — this test is the enforcement.
- Parallel-stream builds will race on `down_revision`; this test is the merge-time backstop. Run it on every PR (add to the `backend` job, cheap).

---

### S7.11 — CHANGELOG finalization (Unreleased → versioned two-role release)

One-line goal: a single Keep-a-Changelog entry covering all user-visible two-role changes, cut as the release version.

**Files**
- change `CHANGELOG.md` — under `[Unreleased]`, add `### Added` (two-role authoring for all users, course visibility public/private, clone/remix, goal-intake→build, BYOK, admin moderation), `### Changed` (role model student/instructor→user, frontend `Role` union), `### Migration` (phased order pointer to the runbook); then promote to a versioned heading with date

**TDD steps**
1. FIRST add `apps/frontend/tests/changelog-shape.test.ts` (or backend equivalent) asserting the CHANGELOG has a versioned heading above `[Unreleased]` with the expected sections and references the migration runbook path. Fails until written.
2. Implement the entry.
3. Green: the shape test passes.

**Migrations**: none.

**Acceptance criteria**
- *Given* the release, *When* CHANGELOG is read, *Then* every user-visible two-role change is listed with Added/Changed/Migration sections (CLAUDE.md "CHANGELOG entry for user-visible changes").

**Risk/notes**
- Keep the existing QA-loop "Fixed" entries; append, don't overwrite.

---

## Stream-level gate (what must be true to call S7 done)

**Unit / CI green:**
- `uv run pytest tests/test_openapi_snapshot.py tests/test_learner_traces_parent_message.py tests/test_eval_fixture_gate.py tests/test_migration_chain.py tests/test_migration_phase_annotations.py tests/test_adr_consistency.py` all pass.
- `pnpm exec vitest run i18n-parity api-role-contract ci-workflow-shape changelog-shape` all pass; `pnpm typecheck` clean.
- CI `backend` job's new `OpenAPI contract drift` + `eval-gate` steps pass; `make openapi.check` exits 0.
- `alembic upgrade head` reaches **0045**; `alembic downgrade -1` cleanly reverses 0045; chain test confirms linear 0030–0045, only 0031 irreversible.
- axe WCAG 2.2 AA suite green across all net-new surfaces + the Arabic/RTL pass.

**Live-as-a-user browser check (Gate C, per memory [verification-criteria] + [post-deploy-visual-coverage]):**
- Bring up `make up`. Sign in as **each persona** — admin (`admin@`), and the collapsed `user` (formerly `teacher@`/`student@`) — and walk:
  - Author+learn surfaces under one `user`: `/studio`, define→build flow, `/dashboard`, a clone CTA, BYOK settings — capture screenshots.
  - Admin moderation queue under `/admin/*`.
  - Toggle locale to **Arabic** and confirm RTL layout on home + one authenticated surface (no clipped/overlapping text, logical-property spacing correct).
- Confirm the trace timeline (H7) renders a turn's traces via the exact `parent_message_id` FK (S7.3) with no temporal false-positives, by inspecting a fresh post-0045 turn.
- Confirm `/eval` public page still renders (live eval path untouched) and the deterministic CI eval gate reports pass on the seeded fixtures.

---

## Traceability: FR/R/DR/ADR ids this stream satisfies

- **DR-2 / DR-21** — `agent_traces.parent_message_id` self-FK migration **0045** + best-effort temporal-window backfill; `learner_traces` swaps window→FK with fallback (S7.3).
- **DR-5 / FR-API-01** — CI contract-drift check (`openapi.json` vs fresh), hand-written `types.ts`/`endpoints.ts` kept in-PR, **no `make api-client`**, Role union narrowed (S7.1, S7.2, S7.8).
- **DR-12** — phased migration-application RUNBOOK (Phase A/B/C/D, never `downgrade` past 0031, single-host topology note) + phase-annotation guard (S7.7).
- **DR-13 / R-S8′** — runbook flips `FEATURE_PRIVATE_PUBLISH_ENABLED` only post-authorizer-confirm (S7.7).
- **DR-14 / DR-15 / R-C2 / R-C5′** — operator-confirmed model NOT-NULL gate, online `CONCURRENTLY` index + EXPLAIN gate, `moderation_events` never dropped, positive-evidence Phase D gate — all encoded in the runbook (S7.7).
- **DR-18-R2 / DR-22 / DR-6-R2 / DR-10 / DR-17 / DR-19** — ADR finalization reconciling the resolutions into ADR-0026/0027/0029/0030 (S7.9).
- **R-U6 / R-G2** — deterministic eval CI gate on recorded fixtures, ε=0.30 on 1–5 scale, live separate + inconclusive-on-outage, ε documented in the eval ADR (S7.4, S7.9).
- **FR-I18N-04 / R-U8** — en+ar key parity test (equality, non-empty, no-echo), RTL via logical properties, `translation_status` field tracking quality (S7.5).
- **FR-A11Y-03** — axe WCAG 2.2 AA over every net-new surface under 3 personas with the `student@`/`teacher@`→`user` shim (S7.6).
- **CLAUDE.md / CHARTER §7** — CHANGELOG for user-visible changes; ADR for architectural seams; OpenAPI-is-the-contract (regen `openapi.json`, hand-curate the TS client) (S7.8, S7.11).
- **ADRs touched/finalized:** 0025 (role↔capability — cross-ref only), 0026, 0027, 0029, 0030; new eval-gate ADR (0031).

**Files of record cited (ground truth):** `apps/backend/app/models/agent_trace.py`, `apps/backend/app/services/learner_traces.py:39`, `apps/backend/app/models/tutor_conversation.py` (TutorMessage), `apps/frontend/src/lib/api/types.ts:3`, `apps/frontend/tests/i18n-parity.test.ts`, `apps/frontend/src/lib/i18n/messages/{en,ar}.ts`, `apps/frontend/tests/e2e/accessibility.spec.ts`, `apps/backend/app/evals/{reports.py:97,judge.py:104,runner.py,run_baseline.py}`, `apps/backend/evals/{tutor,authoring,ingest}/dataset.jsonl`, `.github/workflows/{ci.yml,eval-baseline.yml}`, `apps/frontend/tests/ci-workflow-shape.test.ts`, `Makefile:171-181`, `apps/backend/scripts/export_openapi.py`, `apps/backend/alembic/versions/` (head=0029 today), `docs/runbooks/{incident-response,upgrade}.md`, `CHANGELOG.md`, `docs/adr/0000-template.md`.
