# ADR 0028: Clone/Remix via Sanitized Export Projection + Immutable Provenance

## Status — Proposed

W2 design artifact for the two-role rebuild. Sibling to ADR-0025 (role vs capability), ADR-0026 (visibility + moderation), ADR-0027 (BYOK), ADR-0029 (RAG ACL + index plan), ADR-0030 (account lifecycle). Canon: `docs/two-role-rebuild/CHARTER.md` §3.4 + REQUIREMENTS-RESOLUTIONS.md (R1/R2/R3 amendments authoritative) + spec §3.18/§3.19 (FR-CLONE-01..25, FR-DEL-01..03). Numbering: highest existing ADR on disk is `0024-adversarial-probes-off-default-tutor-rail.md` (`docs/adr/`); 0025–0027/0029–0030 are the concurrent W2 batch, so clone takes **0028**.

## Context (forces + current code reality)

The charter's central pivot: any user can **clone a publicly-listed course into a private deep copy with immutable provenance**, then learn from and edit it independently (CHARTER §1, §3.4). Gate A rejected "blind deep copy": clone is a **sanitized export projection of a published-public snapshot**, never an ORM walk that drags hidden/private/soft-deleted state across an ownership boundary.

Verified code reality this ADR builds on and must not break:

- **No clone path exists.** `app/services/courses.py` has create/update/delete/reorder + `_unique_slug` (`courses.py:193`), `_flush_course_with_slug_retry` (`courses.py:208`), `slug_or_id` (`courses.py:414`). There is no `clone_course`.
- **`Course` has no provenance, no visibility, no moderation.** `app/models/course.py:79-155`: columns are `owner_id` (FK `ondelete="RESTRICT"`, `course.py:103`), `subject_id`, `title`, `slug`, `overview`, `learning_outcomes` JSONB, `cover_url`, `difficulty` (String(20)), `status` (String(20)), `published_at`, `is_featured`, `deleted_at`, `search_vector` (GENERATED tsvector). The slug uniqueness is a **partial** unique index `uq_courses_slug_live` over live rows only (`course.py:90-94`).
- **Tree constraints** that the clone must satisfy without the two-phase dance: `uq_modules_course_order` (`course.py:161`), `uq_lessons_module_order` (`course.py:181`). `Lesson` carries `deleted_at` (`course.py:194`); `Module` does **not** (a module is "empty" iff all its lessons are soft-deleted). `Lesson.data` is JSONB (`course.py:193`); quiz payloads live there verbatim.
- **Clonability gate must be the central authorizer, not `status==published`.** Today `can_view_course` (`courses.py:424-439`) returns `True` for any `status==published` course — this is the legacy rule ADR-0026 replaces with `is_publicly_listed`. Clone (FR-CLONE-03) MUST call the new `is_publicly_listed`/`can_view_course`, never read `status`.
- **Auto-enroll target.** `enrollment.enroll` (`enrollment.py:90-107`) hard-rejects non-published (`status != CourseStatus.published` → `enrollment.not_available`, `enrollment.py:91`). A fresh clone is `draft`+`private`, so the cloner cannot self-enroll through `enroll()`. We need a dedicated owner-self-enroll that bypasses that gate (the clone owns the course; ADR-0026's `can_learn_in_course` owner-branch authorizes it). `Enrollment` has no `is_self` column (`course.py:202-226`); R-M8′ requires one so `_maybe_issue_certificate` (`enrollment.py:41-87`) suppresses certs/badges on self-enrollment.
- **Embeddings are never copyable.** `LessonChunk` (`models/lesson_chunk.py`) is per-lesson with `ondelete="CASCADE"` to `lessons`; chunks are rebuilt by `ingest_course` (`workers/tasks/embeddings.py:38`, `index_course_embeddings.delay(course_id)`) on publish via `_schedule_embedding_index` (`courses.py:170-190`, best-effort, swallows broker errors). A fresh clone has zero chunks.
- **Assets are owner-namespaced + CASCADE-on-owner-delete.** `Asset.owner_id ondelete="CASCADE"` (`models/asset.py:20-22`), `key` globally unique (`asset.py:26`). Upload keys are `{kind}/{user.id}/{YYYY/MM/DD}/{new_id}/{filename}` (`uploads.py:148`); public URL is `{s3_public_base_url}/{s3_bucket}/{key}` (`uploads.py:171`). **If a clone referenced the origin author's S3 key and the origin author is later deleted, the object cascades away and the clone's media 404s.** Re-homing is mandatory (FR-CLONE-12). `ALWAYS_DENIED_TYPES` + `ALLOWED_PER_KIND` + `MAX_BYTES_PER_KIND` (`uploads.py:26-95`) are the re-validation surface for R-S5. boto3 `copy_object` is **not yet used anywhere** — net-new.
- **Audit + slug helpers exist and are reusable.** `audit.record(...)` (`repositories/audit.py:10`); `client_ip`/`user_agent` deps (`deps.py:97-110`). `NotificationKind` (`models/notification.py:19-26`) has no `course_cloned` kind — net-new.
- **Authoring already materializes a tree** (`ai_authoring.commit_outline`, `ai_authoring.py:348-391`): the per-module `db.add` + `db.flush` then per-lesson `db.add` loop is the exact materialization shape clone reuses (single transaction, dense order).
- **The fleet is live in prod** (AWS, `main` canonical) with API+worker co-located on one docker-compose host; migrations run against the LIVE DB with old pods still serving. R-S8′ / R-C4 govern rollout.

Decisions are bound by REQUIREMENTS-RESOLUTIONS: **R-M1** (never copy discussions/reviews/enrollments/progress/traces/embeddings), **R-M4** (`is_preview=false` on clone), **R-M13′** (anonymize `origin_owner_name_snapshot` to "a deleted user" on account deletion; lineage survives), **R-S5** (re-validate copied bytes), **R-S7** (lazy assets/embeddings + amplification quotas), **R-S10** (cooperative cancellation), **R-G7** (orphan-asset sweeper), **R-G1** (quota numbers), **FR-DEL-01/03** (fork independence; origin delete never destroys cloner progress).

## Decision

Introduce a **clone-as-projection** pipeline: read a stable single-transaction snapshot of an `is_publicly_listed` source, build an in-memory **sanitized export projection** (an explicit whitelist DTO, not an ORM detach), then **materialize** a new `owner=caller, status=draft, visibility=private, moderation_state=none` course tree. The DB tree (modules, lessons, provenance, owner self-enrollment, audit) is **synchronous and atomic in one transaction**; S3 object copy and embeddings are **lazy/async** (R-S7). The whitelist projection is the security boundary — anything not on it cannot cross.

### 1. Projection (the export DTO — the whitelist boundary)

A pure builder `app/services/clone_projection.py::build_export_projection(course, modules, lessons) -> CourseExport` produces frozen dataclasses copying **only**:

- Course: `title`, `overview`, `difficulty`, `learning_outcomes` (list copy), `subject_id`, tag ids, `cover_url` (re-homed later).
- Modules: `title`, `description`, source display `order` — **dropped entirely if zero live lessons** (FR-CLONE-05).
- Lessons (live only, `deleted_at IS NULL`): `title`, `type`, `duration_seconds`, `is_preview` → **forced to `false`** (R-M4 / FR-CLONE-04), source `order`, and `data` JSONB **deep-copied** (`copy.deepcopy`). Quiz `data` is copied **verbatim** — `pass_score`, `questions[]`, `choices[]`, `answer_keys[]`, all ids preserved, no re-mint, no AI regen (FR-CLONE-06).

The projection is built from rows already loaded in the snapshot transaction (`get_course(with_modules=True)` + an explicit `deleted_at IS NULL` lesson filter — the relationship loader returns soft-deleted lessons, so we filter in the projection, mirroring `update_module`'s `if lesson.deleted_at is None` at `courses.py:231`). Modules are re-keyed to a **dense gap-free 0-based** sequence in source display order; lessons likewise per module — satisfying `uq_modules_course_order`/`uq_lessons_module_order` on first INSERT, no two-phase reorder (FR-CLONE-05).

The DTO **structurally cannot carry**: reviews, enrollments, lesson_progress, certificates/badges, quiz_attempts, AI authoring traces, tutor traces, course_draft_traces, llm_calls, lesson_chunks, retrieval_audits, discussions, `is_featured`, `published_at`, `deleted_at`, source slug, source `owner_id`, moderation/report state, `origin_*` of the source (R-M1, FR-CLONE-07). There is no code path from those tables into `CourseExport`; a test asserts the dataclass field set.

### 2. Materialization + provenance (synchronous, atomic)

`clone_course(db, *, caller, source_key, ip, user_agent, source_updated_at=None, idempotency_key=None) -> Course` (new, in `app/services/courses.py`):

1. **Resolve + authorize.** `source = slug_or_id(db, source_key, with_modules=True)`. If `not is_publicly_listed(source)` (ADR-0026 pure predicate): if `can_view_course(db, source, caller)` is true (e.g. caller's own private draft) → `403 clone.source_not_clonable`; else `404 course.not_found` (no existence leak — FR-CLONE-03). `can_clone(source, caller)` (ADR-0025; suspended/inactive → blocked, anonymous → 401 at route).
2. **Idempotency** (FR-CLONE-20): if `Idempotency-Key` present, look up `(caller_id, idempotency_key)` in a new `idempotency_keys` table; on hit return the prior course (200/201 with same body). 24h TTL.
3. **Preconditions.** Optional `source_updated_at` mismatch vs `source.updated_at` → `409 clone.source_changed` (FR-CLONE-14). Quotas (§ Service): rate window, owned-course cap, source-size ceiling.
4. **Project** → `CourseExport` (§1).
5. **Materialize in one transaction:** mint fresh slug via `_unique_slug(db, export.title)` + insert via `_flush_course_with_slug_retry` (FR-CLONE-11, no "Copy of" prefix); create `Course(owner_id=caller.id, status=draft, visibility=private, moderation_state=none, is_featured=False, published_at=None, ...)`; set provenance (below); copy tags (associate existing `Tag` rows by id — tags are platform-shared, not owned); loop modules→lessons exactly like `commit_outline` (`ai_authoring.py:369-390`) but with dense pre-computed orders.
6. **Provenance (server-written, immutable):**
   - `origin_course_id = source.id` (immediate parent)
   - `origin_owner_id = source.owner_id`
   - `root_origin_course_id = source.root_origin_course_id or source.id` (lineage root, anti-loop, single SELECT off the already-loaded source)
   - `origin_title_snapshot = source.title`
   - `origin_owner_name_snapshot = source.owner.full_name` (display name only)
   - `cloned_at = now()`

   These are set **once**, never accepted from any client payload (CourseCreate/CourseUpdate have no such fields — § API enforces this).
7. **Auto-enroll cloner** (FR-CLONE-16): `Enrollment(user_id=caller.id, course_id=new.id, is_self=True)` — a dedicated `enroll_self(db, user, course)` that bypasses the `status==published` gate (the new course is owned by caller; ADR-0026 `can_learn_in_course` owner-branch authorizes learning). `is_self=True` → `_maybe_issue_certificate` suppresses cert/badge issuance (R-M8′).
8. **Asset re-homing** is **lazy / non-blocking** (R-S7): the synchronous tree keeps origin URLs flagged `copying`; an async Celery task `copy_clone_assets(new_course_id)` re-homes objects after commit. (Small courses MAY copy inline within a request budget — config `CLONE_ASSET_INLINE_MAX`, default 0 = always async.) See § Service.
9. **Audit, atomic with the tree** (FR-CLONE-19): `audit.record(action="course.cloned", actor_id=caller.id, target_type="course", target_id=new.id, ip, user_agent, data={origin_course_id, origin_owner_id, root_origin_course_id, lessons_copied, modules_copied, modules_dropped, asset_count, asset_copy_failures: [], ip, user_agent})` + a second `course.cloned_by_other` event targeting the **origin** course + an in-app notification to the origin owner (display-name only, gated by `notification_prefs`).
10. **Commit.** Endpoint returns as soon as the tree commits. On any failure the whole transaction rolls back → no orphan course (FR-CLONE-22).

**Self-clone** (FR-CLONE-15): identical path, no special-casing; provenance points at the original. **Re-publish a fork** (FR-CLONE-17): goes through the standard ADR-0026 state machine; provenance is immutable through draft→publish→moderation→delist.

### 3. Lazy embeddings + tutor

Embeddings are **never copied** (FR-CLONE-08). They regenerate (a) on the clone's first (re)publish via the existing `_schedule_embedding_index` (`courses.py:167`); (b) on first tutor invocation if chunks are missing, via the lazy-ingest guard ADR-0029 adds before `find_relevant_chunks` (`tutor.py:276`) — enqueues `ingest_course`, returns `tutor.index_pending` until built, with the R-U2′ inline fallback. Embedding jobs count against the cloner's per-user embedding-job quota (R-S7, ADR-0027 quota module).

### 4. Fork independence (FR-DEL-01/03)

Because clone deep-copies into **independent module/lesson/quiz ids**, `review_cards.lesson_id` (ON DELETE CASCADE) and mastery rows on the clone reference only the clone's own lessons. Deleting the origin course/lessons can never cascade into a cloner's progress. Provenance `origin_*_id` are `ondelete="SET NULL"` so a hard-deleted origin nulls the pointer while the snapshot text persists; `origin_available` is computed at serialize time.

## Data model changes

### Model: `Course` (`app/models/course.py`) — add 6 provenance columns

```python
origin_course_id: Mapped[str | None] = mapped_column(
    ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
origin_owner_id: Mapped[str | None] = mapped_column(
    ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
root_origin_course_id: Mapped[str | None] = mapped_column(
    ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
origin_title_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
origin_owner_name_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
cloned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Reconciliation note: spec FR-CLONE-09 says `ondelete=SET NULL`; R-M13′ requires snapshot anonymization on **self-serve account deletion**, which (per ADR-0030) is *anonymize-in-place* (no physical `users` row delete) — so in normal operation `origin_owner_id` stays valid pointing at the tombstoned user and `origin_owner_name_snapshot` is rewritten to "a deleted user". `SET NULL` is the safety net for the offline-admin *physical* purge only. Both are honored.

### Model: `Enrollment` (`app/models/course.py:202`) — add `is_self`

```python
is_self: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
```

(R-M8′ / FR-CLONE-16; also consumed by ADR-0026 self-preview enroll.)

### New model: `IdempotencyKey` (`app/models/idempotency.py`, add to `models/__init__.py`)

```python
class IdempotencyKey(IdMixin, TimestampMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_idem_user_key"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(80), nullable=False)        # "course.clone"
    response_target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

Index `(user_id, idempotency_key)` via the unique constraint; partial cleanup by `expires_at` sweep.

### Index for clone read + lineage

```python
Index("ix_courses_origin_course_id", "origin_course_id"),   # FR-CLONE-24 "who cloned this"
Index("ix_courses_root_origin", "root_origin_course_id"),
```

### Migrations (numbered, explicit ordering, zero-downtime vs LIVE prod + running fleet)

All are **schema-additive** with proper `downgrade()` (data is not collapsed here, so R-C4's no-op rule does not apply — these reverse cleanly). They land in the `>=0030` band, ordered **after** the ADR-0026 visibility migration (clone reads `visibility`/`moderation_state`) and before any flag flip. Each runs while old pods still serve, then new pods deploy.

- **0030_clone_provenance_columns** (down-rev = ADR-0026's `0029_visibility` — confirm `down_revision` at implementation): `ALTER TABLE courses ADD COLUMN origin_course_id varchar NULL …` ×6, all **NULL/defaulted, no table rewrite** (Postgres adds nullable columns metadata-only). Add the 2 indexes `CREATE INDEX CONCURRENTLY` (run outside the migration's implicit txn — use `op.create_index(..., postgresql_concurrently=True)` with autocommit block, matching the GIN-index migration 0014 pattern). FKs are `NOT VALID`-able but small enough to add validated; if the live table is large, add `ADD CONSTRAINT … NOT VALID` then `VALIDATE CONSTRAINT` in a follow-up step. Safe with old pods: they never read/write these columns. **Down:** drop columns + indexes.
- **0031_enrollment_is_self**: `ALTER TABLE enrollments ADD COLUMN is_self boolean NOT NULL DEFAULT false` (server_default makes it instant; existing rows = false, correct — no historical enrollment was a clone self-enroll). Old pods ignore the column. **Down:** drop column.
- **0032_idempotency_keys**: `CREATE TABLE idempotency_keys (...)` + unique constraint. New table, invisible to old pods. **Down:** drop table.

Ordering rationale: 0030→0031→0032 have no inter-dependency but a single linear chain keeps `alembic upgrade head` deterministic on the fleet. The **clone endpoint is itself flag-gated OFF** (`CLONE_ENABLED`, default off) until all three migrations are confirmed applied and new pods are fully rolled — there is no window where clone code runs against a schema missing a column.

## API changes

### New endpoints (registered in `app/api/router.py` under the existing `courses` router, prefix `/api/v1/courses`)

| Method | Path | Auth | Notes |
|---|---|---|---|
| `POST` | `/courses/{key}/clone` | `CurrentUser` + `RequireCapability(can_clone)` | 201 + `Location: /api/v1/courses/{newId}`; body = `CourseListItem` w/ `origin`. Honors `Idempotency-Key`. slowapi-limited (FR-QUOTA-04). |
| `GET` | `/courses/{key}/clones` | origin owner or admin | `could` (FR-CLONE-24); offset+page; 404 for non-owners (no leak). |

`POST /clone` query: optional `?source_updated_at=<iso8601>`.

### Schemas (`app/schemas/course.py`)

- New `CourseOrigin`:
```python
class CourseOrigin(BaseModel):
    origin_course_id: str | None = None
    origin_title: str | None = None        # from origin_title_snapshot
    origin_owner_name: str | None = None   # from origin_owner_name_snapshot
    origin_owner_id: str | None = None
    cloned_at: datetime | None = None
    origin_available: bool = False         # computed: origin live + publicly listed
```
- `CourseListItem` + `CourseDetail` gain `origin: CourseOrigin | None = None`, populated by `_builders.list_item`/`detail` from the snapshot columns. `origin_available` computed by re-resolving `origin_course_id` and applying `is_publicly_listed` (single indexed lookup; suppressed link when false → FR-DEL-01). `CourseDetail` also exposes `is_clone: bool` (= `origin_course_id is not None`) for the studio "Cloned" badge (FR-CLONE-23).
- `CourseClonesItem` for FR-CLONE-24: `{id, title, owner_name, cloned_at}`.
- **Immutability enforcement:** `CourseCreate`/`CourseUpdate` already lack all `origin_*` fields (`schemas/course.py:185-216`); add `model_config = ConfigDict(extra="forbid")` to both so a client cannot smuggle provenance through extra keys. A test posts `origin_course_id` in the body and asserts 422.

### Error codes

| Code | HTTP | Trigger |
|---|---|---|
| `auth.required` | 401 | anonymous clone (FR-CLONE-02) |
| `course.not_found` | 404 | source not visible to caller (no existence leak, FR-CLONE-03) |
| `clone.source_not_clonable` | 403 | caller can see source but it's not `is_publicly_listed` |
| `clone.source_changed` | 409 | `source_updated_at` precondition mismatch (FR-CLONE-14) |
| `clone.rate_limited` | 429 | per-user window 20/h, 100/d (FR-CLONE-18) |
| `clone.course_limit` | 409 | live-owned-course cap (200) reached (FR-CLONE-18) |
| `clone.source_too_large` | 413/422 | >500 live lessons or projected-`data` byte ceiling (FR-CLONE-18) |
| `clone.disabled` | 404 | `CLONE_ENABLED` flag off (mirror not-found, no feature-probe) |

All in the standard `{error:{code,message,details,request_id}}` envelope via `AppError` subclasses (`ForbiddenError`, `NotFoundError`, `ConflictError`, `ValidationAppError`; new `ClonePayloadTooLargeError`/use `ValidationAppError` w/ 422 for byte ceiling).

## Service / worker changes

### `app/services/courses.py`
- **New** `clone_course(...)` (§Decision.2) — the orchestrator; calls the projection builder, materializer, provenance writer, `enroll_self`, audit, notification.
- **New** `can_clone(course, viewer) -> bool` is owned by ADR-0026's authorizer module (`app/services/visibility.py`); clone imports it. **Reuse** `slug_or_id`, `_unique_slug`, `_flush_course_with_slug_retry`. **Reuse** `_schedule_embedding_index` for lazy publish-time indexing (unchanged).
- `can_view_course` (`courses.py:424`) is being rewritten by ADR-0026 to drop `status==published`; clone depends on that rewrite landing first.

### `app/services/clone_projection.py` (new)
- `build_export_projection(...) -> CourseExport` — pure, no DB, no I/O. Computes `lessons_copied/modules_copied/modules_dropped` counters for the audit. Enforces the source-size ceiling (lesson count + serialized `data` byte sum) and the `is_preview=false` / quiz-verbatim rules.

### `app/services/enrollment.py`
- **New** `enroll_self(db, *, user, course) -> Enrollment` — bypasses the `status != published` gate (`enrollment.py:91`), sets `is_self=True`, idempotent on `uq_enrollments_user_course`. Skips the "Welcome" notification (cloner already knows).
- `_maybe_issue_certificate` (`enrollment.py:41`) gains a guard: `if enrollment.is_self: return` (R-M8′) — suppresses cert + badge + `certificate_ready` notification for self-enrollments regardless of status/visibility.

### `app/services/uploads.py`
- **New** `copy_object_validated(*, src_key, dst_kind, dst_owner_id, content_type, size_bytes) -> dict` — boto3 `copy_object` into `{kind}/{cloner_id}/{YYYY/MM/DD}/{new_id}/{filename}` (FR-CLONE-12), then **re-runs upload-time validation on the copied bytes** (`head_object` for size; MIME sniff of a byte-range read against `ALLOWED_PER_KIND`/`ALWAYS_DENIED_TYPES`) — never trusts the source `Asset` row's stored type/size (R-S5). Returns new `key` + `public_url`.

### Worker: `app/workers/tasks/media.py`
- **New** `copy_clone_assets(new_course_id)` Celery task (autoretry, NullPool engine per `worker_session_scope`, mirroring `embeddings.py:23-43`): walks the clone's lessons + `cover_url`, for each in-bucket asset reference calls `copy_object_validated`, creates a new `Asset(owner_id=cloner)` per object, rewrites `lesson.data.asset_key`/`url`/`captions_url` + `cover_url` to new public URLs. **Best-effort per object** (FR-CLONE-13): a missing/410/denied object → strip the media ref to a safe placeholder, append to clone audit `data.asset_copy_failures[]`, continue; overall task succeeds. **External (non-bucket) video URLs referenced as-is.** Signed/private URLs and `ALWAYS_DENIED` types never copied. **Cooperative cancellation** (R-S10): checks `caller.is_active` at each lesson boundary, aborts if suspended.
- **New** `sweep_orphan_clone_assets()` periodic task (R-G7): reconciles `Asset` rows in cloner namespaces with no live lesson/cover reference (created-before-rollback orphans), drops objects older than 24h. Extends the existing `sweep_unclaimed_assets` stub (`media.py:17`).

### Capability / dispatch
- `can_clone` is a pure function over `(User + global config)` per R-CAP: granted to any active (`is_active`, non-suspended) `user`/`admin`; no per-user storage. Route uses `RequireCapability(can_clone)` (ADR-0025 dep), service re-checks (FR-CLONE-02 — enforcement in the service, not only the route). Suspended user mid-clone: `enroll_self`/asset task abort on `is_active` re-check (R-S10).
- **Quotas** (non-dollar, ADR-0027 quota module): clone-window (20/h, 100/d → 429), owned-course cap (200 → 409), source-size (500 lessons / byte ceiling → 413/422). Settings: `clone_per_hour`, `clone_per_day`, `clone_owned_cap`, `clone_max_lessons`, `clone_max_data_bytes`, `clone_asset_inline_max`, `clone_enabled` (R-G1).
- **Prompt-injection (FR-CLONE-21):** cloned content is untrusted to the cloner's tutor/authoring; no behavior change here — it rides ADR-0029's retrieval ACL + ADR-0024's off-default rail + the per-request delimiter nonce (R-S6). A clone-specific adversarial test (malicious lesson body / quiz prompt injection) is mandated.

### New `NotificationKind`
- Add `course_cloned = "course_cloned"` (`models/notification.py:19`) for the origin-owner notification (display-name only).

## Frontend changes

### App Router routes
- **No new page route** for the clone action itself; on 201 the client routes to the existing `apps/frontend/src/app/studio/draft/[courseId]/page.tsx` with the new course id (FR-CLONE-25).
- **`could`** `app/courses/[slug]/clones/page.tsx` (origin-owner view, FR-CLONE-24) — deferred.

### Components
- `components/course/course-card.tsx` (`apps/frontend/src/components/course/course-card.tsx`): add a "Make my own copy" action, rendered **only** when `viewer && can_clone && course.is_publicly_listed` (FR-CLONE-25). Anonymous click → sign-in with return path.
- Course-detail sidebar (next to Enroll): same CTA with progress state; on success toast + route to `/studio/draft/{newId}`.
- New `components/course/clone-button.tsx` — calls generated `Courses.clone({ key })` (after `make api-client`); handles 429/409/413 → localized error toasts.
- New `components/course/origin-attribution.tsx` — renders the **structured "Based on …" block** from `course.origin`, separate from editable title/overview (no spoofing, FR-CLONE-10/23): a link to the source when `origin.origin_available`, plain text "Based on … (no longer available)" when not (FR-DEL-01). Shows immediate parent only (D-35/D-40; `root_origin_course_id` is not rendered).
- Studio my-courses list: a "Cloned" badge when `is_clone` (FR-CLONE-23).

### TanStack query keys (`apps/frontend/src/lib/query/keys.ts`)
```ts
clone: (key: string) => ["course", key, "clone"] as const,
courseClones: (key: string) => ["course", key, "clones"] as const,
```
On clone success: invalidate `qk.myCourses` and `qk.enrollments` (cloner is auto-enrolled).

### i18n keys (add to both `messages/en.ts` and `messages/ar.ts`; `i18n-parity.test.ts` enforces parity)

en:
```
"clone.cta": "Make my own copy",
"clone.inProgress": "Creating your copy…",
"clone.success": "Your copy is ready — opening the editor",
"clone.basedOn": "Based on {title} by {author}",
"clone.basedOnUnavailable": "Based on a course that is no longer available",
"clone.viewSource": "View original",
"clone.badge": "Cloned",
"clone.signInToClone": "Sign in to make your own copy",
"clone.error.rateLimited": "You're cloning too fast — try again shortly.",
"clone.error.courseLimit": "You've reached your course limit.",
"clone.error.tooLarge": "This course is too large to clone.",
"clone.error.generic": "Couldn't create your copy. Please try again."
```
ar:
```
"clone.cta": "أنشئ نسختي الخاصة",
"clone.inProgress": "جارٍ إنشاء نسختك…",
"clone.success": "نسختك جاهزة — يتم فتح المحرر",
"clone.basedOn": "مبني على {title} بواسطة {author}",
"clone.basedOnUnavailable": "مبني على دورة لم تعد متاحة",
"clone.viewSource": "عرض الأصل",
"clone.badge": "منسوخة",
"clone.signInToClone": "سجّل الدخول لإنشاء نسختك الخاصة",
"clone.error.rateLimited": "أنت تنسخ بسرعة كبيرة — حاول مرة أخرى بعد قليل.",
"clone.error.courseLimit": "لقد وصلت إلى الحد الأقصى لعدد الدورات.",
"clone.error.tooLarge": "هذه الدورة كبيرة جدًا بحيث لا يمكن نسخها.",
"clone.error.generic": "تعذّر إنشاء نسختك. يرجى المحاولة مرة أخرى."
```
`translation_status` on the ar block = `human` (these are short, reviewer-signoff per R-U8).

## Alternatives considered

- **Blind ORM deep-copy (detach + re-add the loaded graph).** Rejected (Gate A): drags soft-deleted lessons, traces, embeddings, and origin owner refs across the ownership boundary; a single new relationship or column silently leaks. The whitelist projection makes leakage structurally impossible and is the explicit charter §3.4 decision.
- **Eager asset copy + eager embedding rebuild inside the request.** Rejected (R-S7 clone amplification): a 500-lesson clone with large media would blow the request budget and let one user multiply platform storage/compute N× per click. Lazy/on-publish assets + lazy-on-first-tutor embeddings + per-user quotas bound the amplification.
- **Copy embeddings (`lesson_chunks`) directly.** Rejected (FR-CLONE-08): chunks are model+dim-specific (ADR-0029 / R-C3), CASCADE-bound to origin lessons, and would reference a foreign lesson id graph. Rebuilding lazily is correct and cheap.
- **Reference origin S3 objects (no re-homing).** Rejected (FR-CLONE-12): `Asset.owner_id ondelete=CASCADE` (`asset.py:20`) means an origin-author deletion 404s every clone's media. Server-side copy into the cloner namespace decouples lifetimes.
- **Single merged column for visibility/status/moderation.** Out of scope here (ADR-0026 owns it) but clone depends on the 3-column topology to compute `is_publicly_listed`.
- **`origin_owner_id ondelete=RESTRICT`.** Rejected: would block the offline-admin physical purge of an origin author and couple unrelated lifecycles; `SET NULL` + persisted snapshots (R-M13′) preserve lineage display while allowing erasure.
- **Provenance writable via API (client supplies `origin_*`).** Rejected: attribution spoofing. Server-only writes + `extra="forbid"` on Create/Update.
- **Clone available from any course the caller can view (incl. own private draft).** Rejected (FR-CLONE-03): clonability is strictly `is_publicly_listed`; an owner wanting a private variant uses normal duplicate-on-edit, not the public clone surface (keeps the export-sanitization invariant that clone only ever reads a public snapshot).

## Consequences

- **Positive:** clone is a hard ownership/security boundary by construction; cloners get fully independent courses (FR-DEL-03 protects their progress from origin deletion); provenance is tamper-proof and survives source deletion; amplification is quota-bounded; rollout is additive + flag-gated (zero-downtime). Clone becomes the **first endpoint to honor `Idempotency-Key`**, seeding that infrastructure for the rest of v1.
- **Negative / cost:** a fresh clone has zero chunks → tutor returns `tutor.index_pending` until first index (mitigated by R-U2′ inline fallback). Media re-homing is eventually-consistent (lessons briefly show `copying` placeholders) and can partially fail per object (recorded, never 500). A new `idempotency_keys` table + a periodic orphan-asset sweep add operational surface. `copy_object` is net-new boto3 usage to test against MinIO + S3. Three new migrations on the live DB (all additive/instant).
- **Operational:** clone work counts against per-user clone + embedding + storage quotas (ADR-0027). The orphan-asset sweeper (R-G7) must run on the Celery beat. `CLONE_ENABLED` stays off until 0030–0032 are confirmed applied fleet-wide.

## Requirements satisfied

FR-CLONE-01..25; FR-DEL-01, FR-DEL-03 (and FR-DEL-02 via ADR-0030 hook); FR-CLONE provenance ties FR-VIS-03 (`is_publicly_listed`), FR-RBAC-02 (`can_clone`), FR-QUOTA-01/04, FR-API contract (TS client regen). Resolutions: R-M1, R-M4, R-M8′, R-M13′, R-S5, R-S7, R-S10, R-G1, R-G7; charter §3.4, §3 decision 10; design decisions D-3, D-30, D-34, D-35, D-40, D-61.

## Open risks

- **`make api-client` contract drift:** the new `origin` object + `clone()` method must regenerate cleanly; `Visibility`/`ModerationState`/`CourseOrigin` unions land in `lib/api/types.ts`. CI must run the OpenAPI→TS regen check.
- **MIME re-sniff on copied bytes (R-S5):** a streamed byte-range sniff vs full download trade-off for large video — needs a bounded read (first N KB) that's still reliable for the allowlisted types; verify against MinIO + S3 `copy_object` semantics (server-side copy doesn't expose bytes to the API, so the sniff is a follow-up `get_object` range read).
- **Idempotency replay vs partial async:** a retried clone after the tree committed but before assets finished must return the same course id (tree is the durable unit) while the asset task is still in flight — the `IdempotencyKey.response_target_id` points at the committed course; confirm the replay path doesn't re-enqueue `copy_clone_assets`.
- **`source_updated_at` precision:** `Course.updated_at` only changes on a course-row write; a module/lesson edit may not bump it, so the 409 precondition is best-effort (documented as such per FR-CLONE-14 "optional client use"). Snapshot atomicity (single read transaction) is the real race guard.
- **Lineage depth / loop:** `root_origin_course_id` prevents lineage loops in analytics, but a deep clone-of-clone chain is unbounded; the owned-course cap (200) and clone-window quotas are the practical bound. No max-depth enforced in v1.
- **Tag sharing semantics:** clone associates existing platform `Tag` rows by id (tags are shared, not owned); if a future change makes tags owner-scoped, the projection must re-home them.