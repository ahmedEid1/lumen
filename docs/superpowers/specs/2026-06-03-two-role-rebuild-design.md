All claims verified. The ORM cascade contradiction is confirmed: `User.courses_owned` cascade `all, delete-orphan` (user.py:58) vs `Course.owner_id ondelete="RESTRICT"` (course.py:103). FK ondeletes into users all confirmed matching ADR-0030's table. Migration chain 0028→0029 confirmed, so new migrations start at **0030** with `down_revision="0029"`.

One important note: the Celery app uses `celery.conf.beat_schedule` and has NO `worker_init`/`on_after_configure` signal handler — ADR-0027/0030 propose adding one, accurate. Discussions route through `can_view_course` confirmed.

I have full ground truth. Now I'll write the integrated design spec as my final message.

---

# Lumen Two-Role Rebuild — Integrated System Design Specification (W2)

**Status:** W2 design synthesis · **Date:** 2026-06-03 · **Canon:** `docs/two-role-rebuild/CHARTER.md` (v2 decisions) + `REQUIREMENTS-RESOLUTIONS.md` (R1+R2+R3 — **authoritative on conflict**) + the W1 spec. Integrates ADR-0025 (role↔capability), ADR-0026 (visibility/moderation/central authorizer), ADR-0027 (BYOK), ADR-0028 (clone/remix), ADR-0029 (RAG ACL + index plan), ADR-0030 (account lifecycle). All citations re-verified against source at synthesis time; corrections to ADR claims are flagged inline with **[VERIFIED]**.

**Verification corrections folded into this spec (do not trust the ADRs blindly on these):**
- `RequireInstructor` site count is **26**, not 24: `courses.py`=16, `ai_authoring.py`=**6** (not 5), `content_ingest.py`=**4** (not 3). ADR-0025's "24" is wrong; the CHARTER's "26" is correct. **[VERIFIED via grep]**
- Latest migration is **0029** (`2026_07_28_0029-0029_seed_free_preview_lessons.py`, `down_revision="0028"`). New migrations begin at **0030**. **[VERIFIED]**
- `can_view_course` lives at `services/courses.py` ~`:424-439` and its first branch is `if course.status == CourseStatus.published: return True` — the published==public leak. **[VERIFIED]**
- ADR-0028 cites its own first migration's `down_revision` as "0029_visibility" — that is the **ADR-0026** migration name, not a real revision. The true predecessor revision id is whatever ADR-0026's last migration lands as. The linear chain below resolves this authoritatively.
- ADR-0027 numbers its migrations 0030–0032 **and** ADR-0028 numbers its migrations 0030–0032 **and** ADR-0026 numbers its as 0030 **and** ADR-0029 as 0033–0035 **and** ADR-0030 as 0030. These collide. §2 imposes one global linear ordering that supersedes every per-ADR number.

---

## 1. Architecture Overview & New Domain Model

### 1.1 The one-paragraph shape

Lumen collapses `{student, instructor, admin}` → `{user, admin}` but authorization becomes **capability-based, evaluated in the service layer**, never a blunt role swap. A course grows from one lifecycle axis (`status`) to **three orthogonal axes** — `status` (lifecycle, owner), `visibility` (sharing, owner), `moderation_state` (authority, admin/system) — and a **single central authorizer module** (`app/services/visibility.py`) becomes the only place those axes are combined into access/discoverability decisions, eliminating the 11 `status==published` leak sites. Every user can **define → build → learn** a private course, **publish/share** it through a moderated catalog, and **clone** any publicly-listed course into an independent deep copy with immutable provenance. Users may **bring their own model** (allowlisted providers, envelope-encrypted keys, no user-supplied base URL), with model selection decided by **initiation locus** (foreground user-initiated → BYOK; background/system → platform). Account deletion is **anonymize-in-place**, fixing a latent ORM-vs-DB cascade contradiction.

### 1.2 The five cross-cutting seams (and which ADR owns each)

| Seam | Owner ADR | Consumed by |
|---|---|---|
| **Capability layer** (`app/services/capabilities.py`) — pure fns over `(User, Settings)` | 0025 | visibility (`can_publish_public`), clone (`can_clone`), ingest (`can_ingest_url`), BYOK (`can_use_byok`), tutor/authoring (`can_author`), MCP, deps |
| **Central authorizer** (`app/services/visibility.py`) — `is_publicly_listed`, `can_view_course`, `can_enroll`, `can_learn_in_course`, `can_clone(course,viewer)`, `retrieval_acl_clause`, `publicly_listed_sql` | 0026 (+ SQL-clause variant added by 0029) | tutor (REST+stream+MCP), catalog, search, clone, discussions, RAG, enrollment, sitemap, ETag, CLI |
| **BYOK dispatch** (`app/services/byok.py` + `app/core/secrets_crypto.py`) — `LLMContext`, `resolve_context`, `build_provider` (the only decrypt site) | 0027 | tutor (interactive + streaming worker), authoring/goal-build, learning-path build/manual-replan |
| **Migration ordering** — one linear Alembic chain ≥0030 | this synthesis (§2.5) | every ADR's schema delta |
| **Suspension as the single revocation axis** (`is_active`) | 0030 / R-CAP | every capability check, BYOK reachability, cooperative cancellation |

### 1.3 New domain entities

- **`LearningBrief`** (S3, FR-DEFINE-03) — server-owned, immutable-once-finalized goal artifact; raw goal text field-encrypted reusing the BYOK envelope module (R-G8).
- **`Course` extensions** — `visibility`, `moderation_state` (0026); 6 provenance columns + `cloned_at` (0028).
- **`ModerationEvent`** (0026) — append-only moderation history, survives visibility column rollback (R-C2/R-M9).
- **`CourseReport`** (S6, FR-MOD-11) — report entity with `{open, actioned, dismissed}` lifecycle.
- **`UserLLMCredential`** (0027) — one row per `(user, provider)`, envelope-encrypted, no plaintext column ever.
- **`IdempotencyKey`** (0028) — first consumer is clone; seeds the platform-wide idempotency infra.
- **`Enrollment.is_self`** (0028/R-M8′) — distinguishes owner self-learn from real learners (suppresses certs/analytics).
- **`User.deleted_at`** (0030) — tombstone marker distinguishing deletion from suspension on a shared `is_active`.
- **`LessonChunk.embedding_model/embedding_dim`** (0029) — per-chunk model record for reindex-on-drift without mass invalidation.
- **`llm_calls.billing_mode`** + **`tutor_turn_jobs.credential_id`** (0027) — cost attribution + foreground-locus token to the streaming worker.

---

## 2. Data Model & the Single Ordered Alembic Migration Plan

### 2.1 New tables

**`learning_briefs`** (S3) — `id` nanoid PK; `owner_id` FK→users CASCADE; `created_at`, `finalized_at` (null until finalize ⇒ immutable); `source_goal_enc` (BYTEA, field-encrypted via secrets_crypto, R-G8/FR-PRIV-01); `goal_summary`, `level` (String(20)), `prior_knowledge` (Text), `time_budget_hours` (Int null), `sessions_per_week` (Int null), `desired_outcomes` (JSONB list), `format_prefs` (JSONB), `language` (String(8)), `suggested_subject` (String(120)). Index `(owner_id, created_at)`.

**`moderation_events`** (0026) — `id`; `course_id` FK→courses CASCADE; `actor_id` FK→users SET NULL; `from_state`/`to_state` (String(20)); `reason_code` (String(40), shared taxonomy); `note` (Text, capped/inert); `classifier_signal` (JSONB); `created_at`. Index `(course_id, created_at)`. **Never dropped by a visibility down-migration** (R-C2).

**`course_reports`** (S6, FR-MOD-11) — `id`; `course_id` FK→courses CASCADE; `reporter_id` FK→users CASCADE; `reason` (String(40)); `note` (Text capped/sanitized); `status` (String(16) default `open`); `created_at`, `resolved_at`, `resolved_by` (FK→users SET NULL). Partial-unique `(course_id, reporter_id) WHERE status='open'` (one open report per user/course, FR-MOD-11 coalesce). Index `(status, created_at)`.

**`user_llm_credentials`** (0027) — `id`; `user_id` FK→users CASCADE indexed; `provider` (String(32)); `model` (String(128)); `enc_key` (BYTEA); `enc_data_key` (BYTEA); `key_version` (Int); `key_fingerprint` (String(64)); `last4` (String(8)); `enabled` (Bool default true); `is_active` (Bool default false); `last_validated_at`; `last_validation_status` (String(20) default `unvalidated` ∈ `{unvalidated,valid,invalid,error,needs_attention}`); `allow_platform_fallback` (Bool default true); `created_at/updated_at`; `deleted_at`. **No plaintext key column, no api_base column, ever.** Constraints: partial-unique `(user_id,provider) WHERE deleted_at IS NULL`; partial-unique `(user_id) WHERE is_active AND deleted_at IS NULL`; index `(user_id)`.

**`idempotency_keys`** (0028) — `id`; `user_id` FK→users CASCADE; `idempotency_key` (String(200)); `endpoint` (String(80)); `response_target_id` (String(64) null); `expires_at`; unique `(user_id, idempotency_key)`.

### 2.2 Changed columns

**`courses`** — add `visibility` (String(20) NOT NULL server_default `'private'`); `moderation_state` (String(20) NOT NULL server_default `'none'`, indexed); 6 provenance cols (`origin_course_id` FK→courses SET NULL, `origin_owner_id` FK→users SET NULL, `root_origin_course_id` FK→courses SET NULL, `origin_title_snapshot` String(200), `origin_owner_name_snapshot` String(120), `cloned_at` timestamptz). **No `build_failed` column conflict** — FR-DEFINE-14 introduces a `build_failed` state; **decision: add it as a `CourseStatus` enum value** (String(20) column, no DDL), so ADR-0029's `retrieval_acl_clause` references `CourseStatus.build_failed` directly (closes ADR-0029 open-risk #1).

**`enrollments`** — add `is_self` (Bool NOT NULL server_default `false`) (0028/R-M8′).

**`lesson_chunks`** — add `embedding_model` (String(128)), `embedding_dim` (SmallInt); both nullable→backfill→NOT NULL (0029).

**`llm_calls`** — add `billing_mode` (String(16) NOT NULL server_default `'platform'`); add status literals `quota_exceeded` (code-level, not a column).

**`tutor_turn_jobs`** — add `credential_id` (String(21) null) FK→user_llm_credentials SET NULL.

**`users`** — add `deleted_at` (timestamptz null); partial index `WHERE deleted_at IS NOT NULL`.

### 2.3 New indexes

- `ix_courses_listed` partial composite `(visibility, moderation_state, status, subject_id) WHERE deleted_at IS NULL` (catalog predicate; 0026).
- `ix_courses_acl` partial `(visibility, status, moderation_state, owner_id) WHERE deleted_at IS NULL` (RAG ACL JOIN; 0029) — **note: this overlaps `ix_courses_listed`; keep both only if the planner needs the `owner_id` trailing column for the RAG owner branch; otherwise extend `ix_courses_listed` with `owner_id` and drop `ix_courses_acl` to avoid index bloat on a hot table.** Final call: **extend `ix_courses_listed` to `(visibility, moderation_state, status, subject_id, owner_id)` and do not create a separate `ix_courses_acl`** — one partial index serves both catalog and ACL JOIN. (Resolution of an inter-ADR redundancy.)
- `ix_lessons_module_id_live` partial `(module_id) WHERE deleted_at IS NULL` (0029).
- `ix_courses_origin_course_id`, `ix_courses_root_origin` (0028).
- `ix_moderation_events_course_id_created_at`, `ix_course_reports_status_created`, `ix_users_deleted_at` (partial).

### 2.4 ORM cascade fix (no DDL — ship with model change)

`User.courses_owned` cascade `all, delete-orphan` → **`save-update`** (resolves the verified contradiction with `Course.owner_id ondelete="RESTRICT"`). Symmetrically `User.enrollments` and `User.reviews` → `save-update` (they are anonymize-in-place content, not orphan-deletable). `User.refresh_tokens` stays `all, delete-orphan` (ephemeral, FK is CASCADE). **[VERIFIED contradiction is real: user.py:55-65 vs course.py:103.]**

### 2.5 THE single ordered migration plan (supersedes all per-ADR numbering)

One linear chain, each `down_revision` = the prior. Grouped by work-stream but **globally ordered** so `alembic upgrade head` is deterministic on the live fleet. All are additive or data-only; the **only irreversible** step is the role data collapse (0031, R-C4 documented no-op down). `CONCURRENTLY` index builds use `op.get_context().autocommit_block()` and `DROP INDEX IF EXISTS` for re-runnability.

| Rev | Name | Stream | Kind | Zero-downtime property |
|---|---|---|---|---|
| **0030** | `account_lifecycle_users_deleted_at` | S7→0030 | add `users.deleted_at` (nullable) + partial index CONCURRENTLY; backfill old `deleted-%@lumen.invalid` rows → `deleted_at=updated_at` | metadata-only add; old pods never write it; reversible |
| **0031** | `role_collapse_backfill` | S1 | data: `UPDATE users SET role='user' WHERE role IN ('student','instructor')` | **IRREVERSIBLE** (R-C4 no-op down); run while fleet accepts both (Phase A precondition); idempotent; logs count |
| **0032** | `role_default_user` | S1 | `ALTER COLUMN users.role SET DEFAULT 'user'` | metadata-only; reversible; no enum DDL (String(20)) |
| **0033** | `course_visibility_moderation` | S2 | add `courses.visibility`,`moderation_state` (nullable→batched backfill→default→NOT NULL); create `moderation_events`; backfill synthetic `approved` events; `ix_courses_listed` (extended w/ owner_id) CONCURRENTLY; backfill published+live → `(public,approved)`, else `(private,none)` | batched backfill avoids long lock; old pods ignore cols; **authorizer ships in the same release but private-publish writes flag-gated OFF** (R-S8′ step 1) |
| **0034** | `course_reports` | S6 | create `course_reports` + partial-unique + index | new table; invisible to old pods |
| **0035** | `clone_provenance` | S4 | add 6 provenance cols (nullable/FK SET NULL) + `is_self` on enrollments + `ix_courses_origin*` CONCURRENTLY | metadata-only adds; old pods ignore; reversible |
| **0036** | `idempotency_keys` | S4 | create `idempotency_keys` | new table |
| **0037** | `learning_briefs` | S3 | create `learning_briefs` (encrypted goal field) | new table; depends on secrets_crypto (0038 KEK) being deployable — table add is independent |
| **0038** | `byok_credentials` | S5 | create `user_llm_credentials` + partial-uniques + index | new table; BYOK code flag-gated OFF until KEK confirmed fleet-wide |
| **0039** | `llm_calls_billing_mode` | S5 | add `llm_calls.billing_mode` (PG17 fast-default `'platform'`) | old fleet INSERTs get default = correct (pre-deploy traffic is platform) |
| **0040** | `tutor_turn_credential_id` | S5 | add `tutor_turn_jobs.credential_id` (null) + FK | additive nullable |
| **0041** | `lesson_chunks_embedding_model` | S2/RAG | add `embedding_model`,`embedding_dim` (nullable); batched backfill to current platform model + dim 384 | nullable-first so old ingest still INSERTs; batched off-peak |
| **0042** | `lesson_chunks_live_index` | RAG | `ix_lessons_module_id_live` CONCURRENTLY | concurrent; no lock |
| **0043** | `lesson_chunks_model_not_null` | RAG | `ALTER COLUMN embedding_model/dim SET NOT NULL` | **gated**: only after new ingest image (always stamps model) is fleet-wide and 0041 drained (R-S8′ step 3 discipline) |

**Why this order is forced:**
1. **0030 before 0031**: account-lifecycle's `deleted_at` is additive and orthogonal; placing it first means `delete_account`'s try-guarded BYOK/provenance steps activate automatically as later tables land (no redeploy of the deletion path).
2. **0031/0032 (role)** must run while the fleet is in **Phase A** (accepts `{student,instructor,user,admin}` at every boundary). The data collapse (0031) precedes the default flip (0032).
3. **0033 (visibility) before 0035 (clone)**: clone reads `visibility`/`moderation_state` to compute `is_publicly_listed`; **before 0041 (chunk model)** is irrelevant (independent). The **authorizer is deployed with 0033** so it is in effect before any non-default visibility is writable — the leak-free invariant (R-S8′).
4. **0033 before 0041**: `ix_courses_listed`/ACL JOIN references `visibility`/`moderation_state`, so those columns must exist before the chunk-model work that consumes the ACL clause deploys.
5. **0038 (BYOK table) before 0039/0040**: `tutor_turn_jobs.credential_id` FK targets `user_llm_credentials`.
6. **0041 → 0043 split** (nullable → backfill → NOT NULL) is the R-S8′ drain discipline so a still-old ingest pod never INSERTs a chunk missing the new columns mid-window.

**Rollback playbook:** image-rollback to the last release that accepts the wider sets; never `alembic downgrade` past **0031** (irreversible data). Every other rev has a clean `downgrade()` (drop column/table/index). `moderation_events` is **never** dropped even on 0033 downgrade (R-C2).

### 2.6 Phased role rollout mapped onto the chain (R-C5/C5′)

- **Phase A (Release 1):** deploy code accepting `{student,instructor,user,admin}` everywhere (Pydantic `Role` validators, JWT `normalize_role`, MCP `Principal.role`). Defaults still `student`.
- **Phase B:** run **0031** backfill.
- **Phase C (Release 2):** run **0032**; deploy narrowed enum `{user,admin}` + normalization layer (legacy→`user` at every boundary); flip all code defaults to `user`; update admin counts, frontend `Role` union, i18n.
- **Phase D (Release 3):** **positive-evidence gate** (R-C5′) — query proving zero `role IN ('student','instructor')` rows **AND** no legacy MCP principals **AND** ≥15-min token TTL elapsed since Phase C — then remove the normalization layer, remove `is_instructor_or_admin()`, drop deprecated `Principal.is_instructor`, tighten accept-set to strictly `{user,admin}`.

---

## 3. The Single Central Authorizer & Capability Layer

### 3.1 `app/services/capabilities.py` (0025) — pure fns over `(User, Settings)`

```python
def _active(u): return u.is_active                 # suspension/deletion = is_active=False (R-CAP)
def can_author(u) -> bool:                 return _active(u)            # default-granted
def can_clone(u) -> bool:                  return _active(u)            # default-granted
def can_use_byok(u) -> bool:               return _active(u)            # default-granted (R-CAP: no per-user revoke)
def can_publish_public(u) -> bool:         return _active(u)            # + quota at call site
def can_view_course_analytics(u, course):  return _active(u) and (u.is_admin() or course.owner_id == u.id)
def can_use_mcp_authoring(u, s):           return _active(u) and s.mcp_authoring_enabled   # global flag default ON
def can_ingest_url(u, s):                  return _active(u) and s.ingest_url_enabled and u.is_admin()  # CLOSED until SSRF ADR (R-M12)
```

Invariants: **admin always passes** (admins are active; guarded fns treat `is_admin()` as pass). **Suspension/deletion (`is_active=False`) is the single per-user revocation axis** — no `user_capability_overrides` table, no per-user `can_use_byok` storage (R-CAP; supersedes FR-BYOK-22's per-user revoke and the `byok.capability_*` audit names). `can_ingest_url` is **global-flag + admin-only**, not per-user, until the SSRF ADR (charter decision 7).

### 3.2 `app/services/visibility.py` (0026, extended by 0029) — the only home for the multi-axis combine

```python
def is_publicly_listed(course) -> bool:                       # pure, no DB/viewer (R-C1′ canonical)
    return (course.visibility == Visibility.public
            and course.status == CourseStatus.published
            and course.moderation_state == ModerationState.approved
            and course.deleted_at is None)
def publicly_listed_sql():                                     # the ONLY query-side 4-col AND
async def can_view_course(db, course, viewer) -> bool          # listed OR owner OR admin OR grandfathered-enrollment
async def can_learn_in_course(db, course, viewer) -> bool      # owner self-learn on private/draft (FR-LEARN-01)
async def can_enroll(db, course, viewer) -> tuple[bool,str|None]
def can_clone(course, viewer) -> bool                          # = is_publicly_listed(course)  [consumed by 0028]
def can_publish_public(user) -> bool                           # delegates to capabilities.can_publish_public
def retrieval_acl_clause(viewer) -> ColumnElement[bool]        # SQL: listed OR (owner AND deleted_at IS NULL AND status != build_failed) [0029, R-S12]
```

**R-C1′ supersedes the spec's `moderation_state IN (none, approved)`** everywhere — the canonical predicate ANDs `== approved`. `none` is NOT listable. A CI grep-guard (`test_no_raw_published_checks`) blocks `status == published`, `str(...status)=="published"`, and the dead `IN (none, approved)` / auto-approve-fast-path phrasings (R3 cleanup sweep), allow-listing only `visibility.py` + `_transition_status` + seeds.

**Quarantine override (R-C6′):** when `moderation_state==delisted AND latest moderation_event.reason_code ∈ {csam, illegal}`, the grandfathered-enrollment branch of `can_view_course` is suppressed (full quarantine incl. owner). For `severe_abuse`, owner keeps view/edit but `can_learn_in_course`→tutor disabled.

### 3.3 `app/api/deps.py` — capability dependencies (0025)

Add `RequireAuthor` (= any active user via `can_author`), `RequireIngestUrl` (= `can_ingest_url`, admin-only/flag-off), and `RequireCapability(fn)` factory (used by clone). `require_role`/`RequireAdmin` unchanged; admin-always-passes shortcut preserved. New error code `auth.capability` with `details.capability=<name>`; 401 for anonymous, 403 for suspended.

### 3.4 EVERY call site that must adopt the authorizer/capabilities (the migration list)

**Route-guard swaps (26 RequireInstructor sites + MCP):**
- `courses.py` (16) → `RequireAuthor`; `ai_authoring.py` (6) → `RequireAuthor`; `content_ingest.py` (4) → `RequireIngestUrl`. **[VERIFIED counts: 16/6/4=26]**
- `mcp/server.py:_enforce_auth` `auth=="instructor"` branch → capability `principal.can_author`, code `mcp.writes.author_required`; `create_course_draft` ToolSpec `auth "instructor"→"user"`; `ingest_url_to_draft` stays `"admin"` + `can_use_mcp_authoring AND can_ingest_url`. `tools.py:_require_instructor`→`_require_author`. `Principal.is_instructor` kept deprecated through Phase A–C only.

**Service-layer capability re-checks:** `create_course` (drop `is_instructor_or_admin` gate at `courses.py:69`); `draft_course` orchestrator entry; clone service; share/publish; ingest service; every BYOK endpoint; goal-build endpoints.

**`status==published` → authorizer (the 11 FR-VIS-04 leak sites, all [VERIFIED] present):** `enrollment.py:91` (`enroll`→`can_enroll`); `courses.py:313` (free-preview→`is_publicly_listed`); `repositories/courses.py:47` & `:138-139` (subject counts + `search_courses` only_published→`publicly_listed_only`); `learning_path.py:551/613/933` + `researcher.py:246/290` (cross-course RAG→`retrieval_acl_clause`); `tutor_streaming.py:150`; `mcp/tools.py:323`; `admin.py:375/416`; `cli.py:351`; **plus** `can_view_course` at `courses.py:424` itself rewritten (drop the `status==published` first branch). MCP `ask_tutor` keeps its **stricter** enrolled-or-owner floor (R-M2) — only REST/streaming adopt `can_view_course`; the SQL `retrieval_acl_clause` is added as defense-in-depth even there.

---

## 4. API Surface (by capability)

**Error-envelope contract for all new codes:** `{error:{code,message,details,request_id}}` via `AppError` subclasses; `details` scrubbed by the redaction filter (§5). 401 anonymous on mutate; 404 existence-hiding for non-listed to non-owner; 403 capability/suspension.

### 4.1 Authoring / goal-build (S3)
- `POST /ai/goal/start`, `POST /ai/goal/{session}/turn` (multi-turn elicitation, bounded 6 assistant turns, `RequireAuthor`, metered via `call_logged` with foreground `LLMContext`); `POST /ai/goal/{session}/finalize` → `BriefOut` (immutable). Codes: `define.turn_cap`, `define.brief_finalized`.
- `POST /ai/courses/draft` (`RequireAuthor`, in-request, `Idempotency-Key`) → builds `visibility=private,status=draft`; subject auto-resolved to seeded "Personal/Self-directed" (no `authoring.subject_not_found`); difficulty/outcomes from brief. Codes: `define.build_in_flight`, `authoring.build_failed`.
- Guards/edits: existing `courses.py` author routes keep owner-or-admin service checks via `_can_edit_course`. Removed code: `courses.forbidden`.

### 4.2 Visibility / lifecycle / moderation (S2/S6)
- Owner: `POST /courses/{id}/publish|unpublish|share|unshare|resubmit`, `POST /courses/{id}/report`. `PATCH /courses/{id}` **drops `status`** from `CourseUpdate` (FR-VIS-08).
- Admin: `GET /admin/courses/moderation-queue`; `POST /admin/courses/{id}/approve|reject|delist|relist|remove`; `GET /admin/reports`; `POST /admin/reports/{id}/resolve`.
- Schemas: `CourseListItem`/`CourseDetail` gain read-only `visibility`,`moderation_state`; `CourseDetail` adds `is_publicly_listed`, owner-only `can_publish_public`, and (0028) `origin: CourseOrigin|null`, `is_clone`. **Non-owner serialization MUST NOT expose moderation internals** (FR-VIS-21). New: `ShareRequest`, `ModerationActionRequest{reason,note}`, `ReportRequest`.
- Codes: `course.invalid_transition`, `course.publish_public_forbidden` (403), `course.not_listable` (409), `course.not_found` (404 existence-hide), `report.own_course` (422), `course.report_rate_limited` (429).

### 4.3 Clone (S4)
- `POST /courses/{key}/clone` (`RequireCapability(can_clone)`, `Idempotency-Key`, slowapi) → 201 + `Location`, body `CourseListItem` w/ `origin`. `GET /courses/{key}/clones` (origin-owner/admin, 404 for others).
- `CourseCreate`/`CourseUpdate` gain `model_config=ConfigDict(extra="forbid")` so provenance can't be smuggled.
- Codes: `clone.source_not_clonable` (403), `clone.source_changed` (409), `clone.rate_limited` (429), `clone.course_limit` (409), `clone.source_too_large` (413/422), `clone.disabled` (404 flag-off mirror).

### 4.4 BYOK (S5)
- `GET /llm-providers` (registry, no keys); `GET /me/llm-credentials` (masked, **no `api_key` field in schema**); `PUT /me/llm-credentials/{provider}` (upsert write-only key); `PATCH …` (toggle enabled/active/fallback); `DELETE …` (soft-delete); `POST /me/llm-credentials/{provider}/validate` (redacted probe).
- Codes: `byok.base_url_forbidden` (422 — field_validator rejects any url/host/api_base), `byok.model_not_allowed`, `byok.provider_not_allowed`, `byok.credential_not_found`, `byok.validate_rate_limited` (429), `byok.must_store_before_validate` (412, anti-oracle R-S4), `byok.model_unavailable`, `tutor.byok_provider_error`, `llm.quota_exceeded`.

### 4.5 Admin user mgmt / account (S6/S7)
- `PATCH /admin/users/{id}/admin {is_admin}` (grant/revoke, last-admin invariant), `PATCH …/suspend`, `PATCH …/reinstate` (422 `user.deleted_irreversible` if tombstoned). Legacy `PATCH …/role` normalizes legacy→user during window, then 422 `user.invalid_role`.
- `DELETE /me` (anonymize-in-place, clears auth cookies). Codes: `auth.account_suspended`, `auth.account_deleted`, `account.access_revoked` (403 cooperative-cancel), `user.last_admin`/`user.last_admin_active`.
- `/admin/stats`: `instructors` count → `admins` + `authors` (=`COUNT(DISTINCT owner_id)` over live courses); rename ships with TS client in one PR (FR-ADMIN-05).

**Contract:** every new/changed endpoint regenerates `openapi.json` (`make openapi`) and the TS client (`make api-client`); hand-written `types.ts` `Role` union changed in the same PR as the backend enum with a CI drift check (FR-API-01).

---

## 5. Service / Worker Layer

### 5.1 Authoring / goal-build
New `services/learning_brief.py` (elicitation orchestration, convergence, finalize→immutable, field-encrypt goal). `authoring_orchestrator.draft_course` consumes `brief_id`: difficulty from `brief.level` (not hardcoded beginner at `authoring_orchestrator.py:1146`), `learning_outcomes` from `brief.desired_outcomes`, level/time/outcomes into outliner+critic prompts. Build cost-controlled: per-user concurrency cap (default 1) + daily build-job quota (non-dollar) + idempotency. `build_failed` is a `CourseStatus` value (no half-courses). Capability re-check (`can_author`) at **initiation** before any work; suspended→403, anonymous→401 (FR-DEFINE-06).

### 5.2 Tutor (worker streaming + BYOK via credential_id)
`services/tutor.py::ask`: call `can_view_course` (→404 on deny) **before** retrieval; thread `viewer` into `find_relevant_chunks` (now required kwarg + `retrieval_acl_clause`). Index-state computation (R-U2′/0029 D8): pending → enqueue `index_course_embeddings`, bounded wait `INDEX_MAX_STALENESS_S=60`, inline top-N fallback (`enforce_acl=False` permitted, ownership already proven) capped by `index_inline_timeout_s=8` + per-user embedding quota + concurrency lease → else `tutor.index_pending` (never permanent refusal, distinct from empty-retrieval). Streaming worker (`tutor_streaming.run_turn`→`orchestrate_stream`→`stream_chat`) carries `turn.credential_id`; `stream_chat(messages,*,ctx)` calls `byok.build_provider` and dispatches by `spec.transport`. **R-M5**: re-run `can_view_course` per send → 403 `course.access_revoked` on loss.

### 5.3 BYOK dispatch + encryption + quotas + redaction (R-S1″)
`secrets_crypto.py`: AES-256-GCM DEK per credential, DEK wrapped by versioned KEK; `encrypt/decrypt/fingerprint/last4/rotate`; dev fallback derives ephemeral KEK from `secret_key` (forbidden in prod). `byok.py`: `LLMContext{user_id,credential_id,foreground}`, `resolve_context` (API-side, picks active credential, no decrypt), `build_provider` (**the only decrypt site**; drift→platform+needs_attention R-M11′; auth-error→fallback iff `allow_platform_fallback` else hard-fail; transient→no fallback; quota-exhausted→blocked not platform). **Classification by initiation (R-S1″):** interactive+streaming tutor, authoring/goal-build, learning-path **build + manual replan** → BYOK; **monthly beat replan** + embeddings + eval → platform. `replan_for_user(db,user_id,*,ctx=PLATFORM_CONTEXT)`: API passes resolved ctx, beat passes default. **Celery payloads carry `credential_id` only, never the key** (FR-BYOK-26); worker re-resolves+decrypts. Boot guard (`prod_guards.check_byok_master_key`) wired into **both** API lifespan (`main.py:268`) **and a new Celery `worker_init` signal** (none exists today — `celery_app.py` only has `beat_schedule` **[VERIFIED]**) (R-S3/R-S1′e/f). Provider classes get `SecretStr` wrap + redacting `__repr__/__str__` (closes the `self._api_key` raw-storage leak at `llm.py:200,312` **[VERIFIED]**). Quotas (R-M7′): pre-dispatch DB request/job COUNT backstop in `call_logged` (independent of `cost_usd=0` BYOK bypass **[VERIFIED]**) + best-effort Redis concurrency lease (TTL, fail-open). Value-level redaction processor registered last in structlog + exception/trace serializers, wrapping worker sinks too; enumerated-sink sentinel tests replace the self-defeating canary (R-U3/R-U4).

### 5.4 Clone projection
`clone_projection.py::build_export_projection` — pure whitelist DTO (title/overview/difficulty/outcomes/subject/tags/cover; modules w/ ≥1 live lesson; lessons live-only, `is_preview=false` R-M4, quiz `data` verbatim R-CLONE-06). `courses.py::clone_course` — resolve+authorize (`can_clone(course,viewer)`; 403 vs 404 existence-hide), idempotency, project, materialize atomically (fresh slug, dense orders, server-written immutable provenance), `enroll_self(is_self=True)`, audit + origin notification, commit. Assets lazy (`workers/tasks/media.py::copy_clone_assets`, `copy_object_validated` re-runs MIME/size validation R-S5, best-effort per object, cooperative-cancel R-S10). Embeddings never copied (lazy on publish/first-tutor). `_maybe_issue_certificate` gains `if enrollment.is_self: return` (R-M8′, **[VERIFIED]** cert minting lives at `enrollment.py:_maybe_issue_certificate`).

### 5.5 Moderation
`moderation_safety.py` advisory classifier (deterministic keyword over title/overview/outcomes; fail-closed→`pending_review` R-U5; never auto-approves R-C1′). Service fns `share/unshare/resubmit/approve/reject/delist/relist/remove_course` each write `AuditEvent` + `ModerationEvent`, bump catalog cache-version + sitemap purge (R-M14). `_can_edit_course` admin branch **narrowed** (FR-MOD-05): admin views any course but mutates non-owned only via moderation endpoints. Report flow: coalesce open reports, rate-limit ≤10/h, brigading guard (auto-action never delists approved, R-S11). `_schedule_embedding_index` also fires on approve/relist (FR-VIS-17).

### 5.6 Account lifecycle
`services/account.py::delete_account` (atomic single transaction): authn re-check → audit first → scrub PII + set `users.deleted_at` → `is_active=False` → purge refresh tokens → **try-guarded** (catch only `ProgrammingError/UndefinedTable/ImportError`, never blanket) BYOK hard-delete, MCP revoke, owned-courses delist+soft-delete (sticky moderation_state R-C2), provenance snapshot anonymize (R-M13′), discussion/review soft-delete. Core scrub is **un-guarded** (must succeed or rollback). `assert_account_active` cooperative-cancel helper wired at streaming heartbeat (`tutor_streaming.py:86`) + build/clone phase fences (R-S10). Suspension shares `is_active`; `deleted_at IS NULL` discriminates suspend vs delete; auth surfaces distinct codes.

---

## 6. Frontend

**Routes:** `/dashboard` gains "Create a course to learn" entry (canonical define entry, FR-DEFINE-09); goal-elicitation flow + brief review; `/studio/draft/[courseId]` two-control model (lifecycle Draft/Published + Share Private/Public w/ pending_review/approved/rejected/delisted copy, replacing PATCH-status); `/admin/moderation` (queue + approve/reject/delist/relist/remove w/ confirm); `/profile/model` (BYOK tab); `/profile` delete section wired to `DELETE /me`.

**Components:** goal-intake multi-turn UI (aria-live), brief review/edit form, build-progress trace (reuse `CourseDraftTrace`), `course-card` "Make my own copy" CTA (only `viewer && can_clone && is_publicly_listed`), `clone-button`, `origin-attribution` ("Based on …", link iff `origin_available`, immediate-parent only), `byok/{CredentialForm,ProviderSelect,CredentialList,ValidateButton,NeedsAttentionBanner}`, `DeletedUserName` (renders `common.deletedUser`), tutor index-pending state, moderation badges.

**Types/keys:** `Role = "user"|"admin"`; add `Visibility`/`ModerationState`/`CourseOrigin` unions; remove/invert all `role==="student"` author-hide gates (studio/dashboard/command-palette **[CHARTER inventory verified]**), keep admin + owner gates, merge onboarding steps. New query keys: `moderationQueue`, `courseModeration(id)`, `llmProviders`, `llmCredentials`, `clone(key)`, `courseClones(key)`; invalidate `catalog/subjects/course/myCourses/enrollments` on share/moderation/clone.

**i18n/a11y:** all new keys in **both** `en.ts`+`ar.ts` (flat dotted keys **[VERIFIED structure]**), `i18n-parity.test.ts` gates key-set equality; `translation_status` tracks quality (R-U8); RTL via logical properties (FR-I18N-04). axe-core WCAG 2.2 AA on every net-new surface; 3 storage states→3 personas (admin + authoring user + learning user), `student@`/`teacher@`→`user` shim during transition (FR-A11Y-03).

---

## 7. Build Sequence (dependency-aware, mapped to S1–S7 — feeds W3)

Dependencies (CHARTER §4): **S1 precedes most; S2 precedes S4; S3 depends on S1+S2; S5 largely independent; S6 depends on S1+S2.** Migration chain (§2.5) imposes the schema order.

1. **S7-pre (foundation):** capability layer (`capabilities.py`), `auth.capability` code, JWT `normalize_role`, redaction filter + sentinel tests, `secrets_crypto.py` + KEK Settings + boot guard (API+worker signal), `account.deleted_at` migration **0030**, ORM cascade fix. *(Unblocks everything; BYOK crypto needed before S5; cascade fix needed before S6 deletion.)*
2. **S1 (role collapse):** migrations **0031/0032**, Phase A→D rollout, deps `RequireAuthor`/`RequireIngestUrl`, 26 route swaps, MCP RBAC reconcile, `create_course` ungate, frontend `Role` union + gate inversions, eval `run_baseline` user-select, i18n role keys.
3. **S2 (visibility):** migration **0033** + authorizer `visibility.py` (all predicates incl. `retrieval_acl_clause`), migrate the 11 readers, `_transition_status` side-effects, two-control studio, grep-guard, catalog cache/sitemap/ETag, lesson-chunk model migrations **0041–0043** (RAG ACL prerequisite). *(Authorizer ships with 0033; private-publish flag OFF.)*
4. **S3 (goal intake→build):** migration **0037** (`learning_briefs`), elicitation endpoints + brief service, `draft_course` brief-driven, subject auto-resolve + seeded Personal subject, `can_learn_in_course` + `Enrollment.is_self` (needs **0035**) owner self-learn, build quotas/idempotency/`build_failed`, dashboard entry. *(Depends S1+S2.)*
5. **S4 (clone):** migrations **0035/0036**, `clone_projection.py` + `clone_course` + `enroll_self`, `copy_clone_assets` + orphan sweeper, idempotency infra, provenance serialization, CTA/origin-attribution. *(Depends S2 authorizer + S3 `is_self`.)*
6. **S5 (BYOK):** migrations **0038/0039/0040**, `llm_providers.py` registry, `byok.py` dispatch, `stream_chat(ctx)` refactor, call-site `ctx` threading (tutor/authoring/learning-path), non-dollar quotas, validate anti-oracle, admin cost split, settings UI, flip flag after KEK fleet-confirmed. *(Largely independent; crypto from S7-pre.)*
7. **S6 (admin/moderation):** migration **0034** (`course_reports`), moderation state-machine services + admin endpoints + queue UI, `_can_edit_course` narrowing, suspend/reinstate + last-admin invariant, `delete_account` choreography (try-guards activate as S4/S5 tables exist), audit ip/ua backfill. *(Depends S1+S2.)*
8. **S7-post (cross-cutting close):** ingest SSRF hardening (opens `can_ingest_url` flag), prompt-injection rail re-eval (ADR-0024), eval CI gate (epsilon 0.30, fixtures), OpenAPI/TS drift check, full en/ar parity + RTL a11y pass, docs/ADRs/CHANGELOG/CLAUDE.md.

---

## 8. Cross-ADR Resolutions

1. **Migration number collisions** — ADR-0026/0027/0028/0030 all claimed 0030; ADR-0029 claimed 0033–0035. **Resolved by §2.5's single linear chain 0030–0043.** No two migrations share a number; `down_revision` chains deterministically. ADR-0028's bogus `down_revision="0029_visibility"` is corrected (visibility is rev **0033**, not a name).
2. **Index redundancy** — ADR-0026's `ix_courses_listed` and ADR-0029's `ix_courses_acl` overlap. **Resolved:** one extended partial index `ix_courses_listed (visibility, moderation_state, status, subject_id, owner_id) WHERE deleted_at IS NULL` serves catalog + ACL JOIN; no separate `ix_courses_acl`.
3. **`build_failed` column ambiguity** — ADR-0029 left it as either a `CourseStatus` value or a separate `build_state`. **Resolved:** it is a `CourseStatus` enum value (String(20), no DDL), set by S3 build pipeline; `retrieval_acl_clause` references `CourseStatus.build_failed` (closes ADR-0029 risk #1, FR-DEFINE-14).
4. **Capability layer ↔ authorizer ownership** — `can_publish_public`/`can_clone(user)`/`can_use_byok` live in `capabilities.py` (0025); `is_publicly_listed`/`can_view_course`/`can_clone(course,viewer)`/`retrieval_acl_clause` live in `visibility.py` (0026/0029). Both are pure; visibility's `can_clone(course,viewer)` = `is_publicly_listed(course)`, while the *capability* `can_clone(user)` gates the route — both must pass.
5. **BYOK locus across tutor/authoring/learning-path** — single `LLMContext` + `byok.build_provider`; classification by **initiation** (R-S1″) not execution. Worker holds KEK (API+worker co-located, documented R-S1′); streaming worker re-resolves from `tutor_turn_jobs.credential_id`.
6. **Per-user BYOK revocation** — ADR-0027 and FR-BYOK-22 specified a per-user `can_use_byok` revoke + `byok.capability_*` audits; **R-CAP drops these** (suspension is the only revocation). Synthesis adopts R-CAP; the stale FRs/audit names are purged (R3 cleanup).
7. **`moderation_state IN (none, approved)`** — spec (~6 sites) and ADR-0026's "spec is dead" note both reference it; **R-C1′ canonical predicate (`== approved`) governs**; grep-guard blocks reintroduction.
8. **ORM cascade fix ownership** — ADR-0025 references it as a cross-cut owned by ADR-0030; **ADR-0030 owns the change** (`save-update`), shipped in S7-pre before any deletion path.
9. **`R-S8` atomic vs `R-S8′` flagged 4-step** — synthesis adopts R-S8′; the authorizer deploys with migration **0033**, private-publish writes flag-gated OFF until the fleet drains.
10. **Account-deletion forward-compat** — `delete_account`'s BYOK/provenance/visibility steps are try-guarded (narrow exception types) so 0030 (deletion) can ship before 0035/0038 (clone/BYOK tables) land.
11. **MCP divergence** — REST/streaming tutor adopt `can_view_course`; MCP `ask_tutor` keeps the stricter enrolled-or-owner floor (R-M2); the SQL ACL is added everywhere as defense-in-depth (R-U4).
12. **Certificate suppression** — lives in `_maybe_issue_certificate` (R-M8′), gated on `Enrollment.is_self` (0028 column), consumed by both clone self-enroll and owner self-learn (S3).

---

## 9. Residual Gaps

1. **CDN/edge cache purge mechanism (R-G6)** — Caddy surrogate-key support unconfirmed; fallback is the O(1) cache-version bump. Needs an infra note before S2 ships to prod; non-blocking (the version bump works).
2. **HNSW filtered-recall under ACL (0029 risk #2)** — if a user's catalog is mostly private, cross-course HNSW may starve `top_k`; mitigated by `ef_search=100` + the R-U7 +15% benchmark gate; escalation = denormalized ACL escape hatch (D7, specified-not-built).
3. **0041 backfill model attribution** — the backfilled `embedding_model` must match the model that actually produced existing prod chunks; operator confirms deployed `EMBEDDING_PROVIDER` at backfill; self-healing (drift only triggers reindex, never refuses/leaks).
4. **Brief at-rest encryption (R-G8)** — reuses BYOK envelope module; the KEK boot guard must cover the brief path too (a brief row implies a real KEK), not only credential rows — extend `check_byok_master_key` to also fire when any `learning_briefs` row exists.
5. **Ingest SSRF hardening (charter decision 7 / FR-SEC-01)** — its own future ADR; `can_ingest_url` stays admin-only/flag-off until it lands. URL ingest is **not** opened by the role collapse.
6. **Prompt-injection rail (ADR-0024) re-evaluation** — FR-SEC-03 requires an explicit recorded decision on the off-default adversarial rail for cloned/user content; deferred to S7-post with the clone-specific adversarial test mandated by FR-CLONE-21.
7. **`source_updated_at` clone precondition** — best-effort only (`Course.updated_at` doesn't bump on module/lesson edits); snapshot atomicity (single read txn) is the real race guard (FR-CLONE-14 "optional").
8. **Tombstone email reuse** — `deleted-*@lumen.invalid` blocks re-registration with the original address; intentional, needs an operator runbook if product later wants reuse (offline purge frees it).
9. **Cooperative-cancellation completeness (R-S10)** — every future foreground LLM feature must adopt `assert_account_active`; enforce via a W3 build-plan checklist + a suspend-mid-stream regression test.
10. **`make api-client` drift on hand-written `types.ts`** — `Role` union + new endpoint shapes are hand-edited; CI contract-drift check (FR-API-01) is the guard; must run in the same PR as each backend enum/endpoint change.