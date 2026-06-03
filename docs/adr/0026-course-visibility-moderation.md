# ADR 0026: Course Visibility, Moderation State Machine, and the Single Central Authorizer

## Status — Proposed

## Context (forces + current code reality with file:line)

The two-role rebuild (CHARTER §3 decision 3, REQUIREMENTS-RESOLUTIONS R-C1′/R-C2/R-S8′) requires that "published" stop meaning "publicly discoverable." Today the two concepts are fused, and **eleven** code paths read `status == published` directly as an access/discoverability proxy. That fusion is the load-bearing leak: the moment we let a user publish a *private* draft (so they can self-learn with the tutor and feed their own cross-course RAG), every one of those readers would expose it to the public catalog.

Verified current code reality:

- **`Course` model** (`app/models/course.py:79-155`): `status: CourseStatus` = `draft|published|archived` (`:34-37`, `:124-126`, `String(20)`, no native PG enum, default `draft`, indexed). There is **no** `visibility` column and **no** `moderation_state` column. `is_featured` (`:128`), `deleted_at` (`:129`, soft-delete), `published_at` (`:127`). Existing indexes: `ix_courses_status_subject` on `(status, subject_id)` (`:87`), `ix_courses_published_at` (`:88`), partial-unique `uq_courses_slug_live WHERE deleted_at IS NULL` (`:89-94`), GIN `ix_courses_search_vector` (`:95-99`).
- **The single authorizer already exists but is wrong**: `can_view_course(db, course, viewer)` (`app/services/courses.py:424-439`) returns `True` for **any** `course.status == CourseStatus.published` (`:432`) — i.e. published == public. Owner/admin/enrolled branches follow. This is the leak vector R-S8′ names.
- **Status readers that bypass the authorizer** (the FR-VIS-04 migration list, verified):
  - `app/services/enrollment.py:91` — `if course.status != CourseStatus.published:` gate on `enroll`.
  - `app/api/v1/courses.py:313` — free-preview lesson read `if lesson.is_preview and str(course.status) == "published":`.
  - `app/repositories/courses.py:47` — subject-tile counts `Course.status == CourseStatus.published`.
  - `app/repositories/courses.py:138-139` — `search_courses(only_published=True)` → `Course.status == CourseStatus.published`.
  - `app/services/learning_path.py:551, :613, :933` — cross-course RAG / planner reads.
  - `app/services/authoring_subagents/researcher.py:246, :290` — authoring researcher RAG reads.
  - `app/api/v1/tutor_streaming.py:150` — streaming tutor demo/visibility gate.
  - `app/api/v1/admin.py:375, :416` — platform-stat published counts.
  - `app/cli.py:351` — CLI published listing.
- **Lifecycle state machine** is `_transition_status` (`app/services/courses.py:134-167`): legal transitions `draft↔published`, `*→archived`, `archived→draft` (`:135-137`); publish requires title+overview (`:148-152`) and ≥1 live lesson (`:158-163`), sets `published_at` (`:164`), and best-effort enqueues embeddings (`:166-167`, `_schedule_embedding_index` `:170-190`, swallows broker errors).
- **PATCH is currently the publish lever**: `Courses.patch(courseId, { status: "published" })` (`apps/frontend/src/app/studio/draft/[courseId]/page.tsx:66`), via `PATCH /courses/{course_id}` (`app/api/v1/courses.py:177`).
- **Admin "edit any course" branch**: `_can_edit_course` returns `user.is_admin() or course.owner_id == user.id` (`app/services/courses.py:410-411`) — admin can currently mutate *any* course through owner-shaped endpoints. FR-MOD-05 narrows this.
- **`is_featured`** is admin-toggled with no listing precondition (`app/api/v1/admin.py:268-283`, audit `admin.course.featured`).
- **Audit infra exists and is reusable**: `AuditEvent` (`app/models/audit.py:17-31`) — append-only, `actor_id` (FK `SET NULL`), `action String(80)` indexed, `target_type/target_id`, `ip_address`, `user_agent`, `data JSONB`. No dedicated moderation table.
- **Detail ETag/cache**: `_course_detail_etag` (`app/api/v1/courses.py:57-65`), `_CACHE_PUBLIC_60 = "public, max-age=60, must-revalidate"` (`:44`), `Vary: Authorization`, conditional 304 (`:138-165`). There is **no** catalog cache-version key today.
- **Discussions** already route through `can_view_course` (`app/services/discussions.py:42`, `app/api/v1/discussions.py:80, :123`) — they inherit whatever the authorizer decides (R-M1).
- **Latest migration is 0029** (`alembic/versions/2026_07_28_0029-…`); new migrations are ≥0030.
- **Running prod fleet** (AWS, ENV=production) runs old readers that judge `status==published` — so an "atomic release" is impossible (R-S8′). The migration must be additive-then-flag-gated.

Forces: (1) zero-downtime against a live fleet + live prod catalog (must not delist production); (2) a real published-private state must exist so owners learn/RAG privately without public exposure; (3) the classifier must **not** be the security boundary (R-C1′ — a weak heuristic must never be an auto-publish gate); (4) moderation history must survive visibility down-migrations and unpublish (R-C2/R-M9); (5) every discoverability/access decision must funnel through one predicate so the leak cannot be re-derived (FR-VIS-04 CI grep-guard); (6) grandfathered learners vs hard-removal (R-C6′).

## Decision (the concrete chosen design)

**Three orthogonal columns, one central authorizer module, one canonical predicate, a feature-flagged 4-step rollout, an append-only moderation audit table, and a CI grep-guard.**

### 1. Three columns (never folded)

- `Course.status` (`draft|published|archived`) — **lifecycle**, owner-controlled, unchanged.
- `Course.visibility` (`private|public`) — **sharing intent**, owner-controlled, net-new, default `private`. (`unlisted` deferred — FR-VIS-20.)
- `Course.moderation_state` (`none|pending_review|approved|rejected|delisted`) — **admin/system authority**, net-new, default `none`. Never a value of `status` or `visibility`. **Sticky**: never reset to `none` on unpublish/archive (R-C2). Only the explicit unshare/reject path may set it, per the table below.

### 2. The canonical predicate (R-C1′ — supersedes the spec's `IN (none, approved)`)

```python
def is_publicly_listed(course: Course) -> bool:
    return (
        course.visibility == Visibility.public
        and course.status == CourseStatus.published
        and course.moderation_state == ModerationState.approved
        and course.deleted_at is None
    )
```

This is a **pure function over already-loaded columns** (no DB, no viewer — NFR-PERF-2). `none` is **NOT listable** (R-C1, R-C1′). A public share defaults to `pending_review`; `approved` requires an explicit admin action (or an off-by-default admin auto-approve fast-path). The classifier is **advisory triage only** — it sets queue priority, never auto-approves.

> **The spec's `moderation_state IN (none, approved)` is dead.** R-C1′ purges it; the SQL equivalent of the predicate ANDs `moderation_state == 'approved'`. The CI grep-guard (below) blocks re-introduction of `IN (none, approved)` and the auto-approve fast-path phrasing.

### 3. The single central authorizer — `app/services/visibility.py` (new module)

All predicates live here (extracted so the CI grep-guard has one allow-listed home plus the lifecycle machine):

- `is_publicly_listed(course) -> bool` — pure, above.
- `publicly_listed_sql()` — the equivalent SQLAlchemy `and_(...)` clause builder, the **only** place the four-column AND is expressed for queries (catalog, search, subject counts, sitemap, MCP catalog, admin stats).
- `async can_view_course(db, course, viewer) -> bool` — `True` iff: `is_publicly_listed(course)` **OR** viewer is owner **OR** viewer is admin **OR** viewer holds an Enrollment (grandfather, R-VIS-13) — **except** when `moderation_state == delisted AND removal_reason ∈ {csam, illegal}` the enrollment branch is suppressed (full quarantine, R-C6′). For `severe_abuse`, owner keeps **edit-only** access (handled in `can_learn_in_course`, tutor disabled).
- `async can_learn_in_course(db, course, viewer) -> bool` — owner-bypass for self-learn on private/draft (FR-LEARN-01); for `severe_abuse`-flagged courses the owner passes view/edit but `can_use_tutor` returns False.
- `async can_enroll(db, course, viewer) -> tuple[bool, str|None]` — `(True, None)` iff `is_publicly_listed` OR viewer is owner (self-preview); else `(False, "enrollment.not_available")`. Anonymous → caller raises `auth.required` (401).
- `can_clone(course, viewer) -> bool` — `is_publicly_listed(course)` only (consumed by ADR-0027 clone).
- `can_publish_public(user) -> bool` — capability check (ADR role-vs-capability); v1 = `user.is_active and not suspended`.
- `removal_reason` helper reads the latest `moderation_event` for quarantine classification.

`can_view_course` in `services/courses.py:424` is **replaced** by a thin re-export from `visibility.py`; all current callers (`courses.py:111`, `discussions.py:42`, `api/v1/discussions.py:80/123`) keep their call sites.

### 4. Legal (status × visibility × moderation) matrix + transitions

Allowed `(status, visibility)`: `{draft, private}`, `{published, private}`, `{published, public}`, `{archived, private}`. **Forbidden**: `{draft, public}`, `{archived, public}` — making public **requires** `status == published`.

Transition table (service-enforced, audited):

| Action | Guard | Effect |
|---|---|---|
| `publish` (draft→published) | owner; title+overview+≥1 live lesson | `status=published`; `published_at=now`; visibility unchanged (stays private); embeddings enqueued; audit `course.publish` |
| `unpublish` (published→draft) | owner | atomic: `status=draft`, `visibility=private`, `is_featured=false`; **moderation_state untouched** (sticky); audit `course.unpublish` (+`course.unfeatured` if was featured) |
| `archive` (→archived) | owner | atomic: `status=archived`, `visibility=private`, `is_featured=false`; moderation_state untouched; audit `course.archive` |
| `share` (private→public) | `can_publish_public` + quota; **requires** `status==published` | `visibility=public`; `moderation_state: → pending_review` (unless prior `approved` with no reject/delist event → re-`approved`, R-M9); run advisory classifier; emit `moderation_event(none→pending_review)`; audit `course.shared`; **does NOT list** |
| `unshare` (public→private) | owner | `visibility=private`; `is_featured=false`; **moderation_state stays sticky** (NOT reset to none — corrects spec L457; an unshared-then-reshared course re-enters `pending_review` via share, but prior reject/delist history governs re-approval per R-M9); audit `course.unshared` |
| `resubmit` (rejected/delisted→pending) | owner | `moderation_state=pending_review`; re-run classifier; `moderation_event`; audit; admins notified |
| `approve` | admin (or off-by-default auto fast-path) | `moderation_state=approved`; lists; cache bump + sitemap purge + public reindex; `moderation_event` |
| `reject` (pending→rejected) | admin | `moderation_state=rejected`; `visibility=private`; `moderation_event`; audit `admin.course.reject` |
| `delist` (approved→delisted) | admin or report-resolve | `moderation_state=delisted`; `is_featured=false`; NOT soft-deleted; cache bump + sitemap purge + de-feature + RAG drop; `moderation_event`; audit `admin.course.delist` |
| `relist` (delisted→approved) | admin; only if predicate would hold | `moderation_state=approved`; re-enqueue reindex; else **409** `course.not_listable` |
| `remove` (hard) | admin; reason ∈ taxonomy | `deleted_at=now`; `moderation_event`; if reason ∈ `{csam, illegal, severe_abuse}` → revoke enrolled access (R-C6′) |

Coupling invariant: **no DB CHECK constraint** (R-C2 — a CHECK manufactures contradictions during the sticky-history window). Enforced in `visibility.py` service invariants + tests + the authorizer.

### 5. R-S8′ feature-flagged 4-step zero-downtime rollout

- **Step 1 — additive migration (0030)**: add `visibility` (nullable→default `private`→NOT NULL) + `moderation_state` (nullable→default `none`→NOT NULL) + `moderation_event` table + composite index. **One-way backfill**: `status==published AND deleted_at IS NULL` → `visibility=public, moderation_state=approved` (preserve live catalog); everything else → `private/none`. Non-default-visibility **writes flag-gated OFF** (`FEATURE_PRIVATE_PUBLISH=false`). Old fleet keeps reading `status==published` — behavior identical post-backfill (every published course is now `public+approved`).
- **Step 2 — deploy authorizer**: ship `visibility.py` + migrate all 11 readers to it. Behavior identical to old rule because backfill made `is_publicly_listed ≡ (status==published)` for all existing rows.
- **Step 3 — grep-guard + drain**: CI `test_no_raw_published_checks` is green; drain old pods (15-min token TTL window irrelevant here — this is reader-code, gated by deploy).
- **Step 4 — flip flag**: `FEATURE_PRIVATE_PUBLISH=true`. Now `share`/`unshare`/private-publish writes are honored. The authorizer was already in effect before any non-default visibility could be written → **no leak window**.

The flag is a `Settings.feature_private_publish` boolean (safe default `false`); the share/unshare endpoints 404/403 while off.

## Data model changes

### `app/models/course.py`

New enums:
```python
class Visibility(StrEnum):
    private = "private"
    public = "public"

class ModerationState(StrEnum):
    none = "none"
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    delisted = "delisted"
```

New columns on `Course` (matching the existing no-TypeDecorator `String(20)` pattern):
```python
visibility: Mapped[Visibility] = mapped_column(
    String(20), nullable=False, server_default="private", default=Visibility.private)
moderation_state: Mapped[ModerationState] = mapped_column(
    String(20), nullable=False, server_default="none", default=ModerationState.none, index=True)
```

New `__table_args__` index (replaces the listing-relevant role of `ix_courses_status_subject` for catalog filtering):
```python
Index("ix_courses_listed", "visibility", "moderation_state", "status", "subject_id",
      postgresql_where=text("deleted_at IS NULL")),
```

New append-only model `app/models/moderation.py` (added to `app/models/__init__.py`):
```python
class ModerationEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "moderation_events"
    __table_args__ = (Index("ix_moderation_events_course_id_created_at", "course_id", "created_at"),)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"),
                                           nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                  nullable=True)
    from_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)  # taxonomy
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # length-capped, inert text
    classifier_signal: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
```

`moderation_events` is **separate from any visibility column** and is **never dropped by the visibility down-migration** (R-C2/R-M9) — it survives a column rollback so re-up backfill can ask "did this course ever have a reject/delist event?"

### Numbered migrations (≥0030, explicit ordering)

- **0030 — `add_course_visibility_moderation_and_events`** (Step 1). Ordering, each as a discrete op, against the LIVE prod DB:
  1. `ADD COLUMN visibility VARCHAR(20) NULL` (nullable, no default rewrite — instant on PG17).
  2. `ADD COLUMN moderation_state VARCHAR(20) NULL`.
  3. **Batched backfill** (`UPDATE … WHERE id IN (… LIMIT 1000)` loop, separate transactions, to avoid a long table lock against a running fleet): published+live → `('public','approved')`; else → `('private','none')`.
  4. `ALTER COLUMN … SET DEFAULT 'private' / 'none'`; `ALTER COLUMN … SET NOT NULL` (PG17 validates fast after backfill).
  5. `CREATE INDEX CONCURRENTLY ix_courses_listed …` (concurrent → no write lock; run outside the migration's transaction via `op.get_bind()` autocommit block or a follow-on `0030b` non-transactional migration). `CREATE INDEX ix_moderation_events_course_id_created_at`.
  6. `CREATE TABLE moderation_events`.
  7. **Backfill `moderation_events`**: one synthetic `to_state='approved'` row per backfilled-approved course so R-M9's "no prior reject/delist" query is well-defined.
  - **Downgrade**: drops `visibility`, `moderation_state`, `ix_courses_listed`. **Does NOT drop `moderation_events`** (audit survives, R-C2). Reversible/zero-downtime; old fleet tolerates the extra columns (it never reads them).
- **0031 — `narrow_admin_edit` is not a migration** (service-layer only) — noted to avoid confusion; no schema change for FR-MOD-05.

Zero-downtime notes: Step-1 migration ships in a release whose **code does not yet read** the new columns (old readers ignore them); CONCURRENTLY index avoids the fleet's writes blocking; batched backfill avoids a long lock on the prod `courses` table; the NOT-NULL + default is set only after backfill so no in-flight INSERT from the old fleet (which omits the column) fails — the column defaults cover it.

## API changes

New owner endpoints in `app/api/v1/courses.py` (replace PATCH-as-publish, FR-VIS-08):

- `POST /courses/{id}/publish` → `CourseDetail` (lifecycle draft→published)
- `POST /courses/{id}/unpublish` → `CourseDetail`
- `POST /courses/{id}/share` → `CourseDetail` (private→public; flag-gated; `can_publish_public`)
- `POST /courses/{id}/unshare` → `CourseDetail`
- `POST /courses/{id}/resubmit` → `CourseDetail` (FR-MOD-06)
- `POST /courses/{id}/report` → `OkResponse` (FR-MOD-11; not in this ADR's core but routes through `is_publicly_listed`)

`PATCH /courses/{id}` (`courses.py:177`): **remove** `status` from `CourseUpdate` (FR-VIS-08); it no longer publishes.

New admin endpoints in `app/api/v1/admin.py`:

- `GET /admin/courses/moderation-queue` → `list[ModerationQueueItem]` (cursor; `moderation_state==pending_review`)
- `POST /admin/courses/{id}/approve|reject|delist|relist|remove` → `CourseAdminOut`

Schemas (`app/schemas/course.py`):
- `CourseListItem` / `CourseDetail` add read-only `visibility: Visibility`, `moderation_state: ModerationState`. `CourseDetail` adds derived `is_publicly_listed: bool` and owner-only `can_publish_public: bool`. **Non-owner/non-admin serialization MUST NOT expose `moderation_state` internals** — a listed course shows nothing internal; a non-listed course 404s (FR-VIS-21).
- New `ShareRequest`/`ModerationActionRequest {reason: ReasonCode, note: str|None}`.

Error codes: `course.invalid_transition` (existing, reused), `course.publish_public_forbidden` (403, share without capability), `course.not_listable` (409, relist on non-eligible), `course.not_found` (404 — non-listed to non-owner, the existence-hiding contract FR-VIS-11/R-U1), `enrollment.not_available` (existing), `auth.required` (401, anonymous mutate). Envelope `{error:{code,message,details,request_id}}` via `AppError` subclasses.

OpenAPI regenerated (`make api-client`); `lib/api/types.ts` gains `Visibility`/`ModerationState` unions.

## Service / worker changes

- **`app/services/visibility.py` (new)** — all predicates above; the **only** non-lifecycle home for the four-column AND.
- **`app/services/courses.py`**: `can_view_course` (`:424-439`) → re-export from `visibility.py` (new rule). `_can_edit_course` (`:410-411`) → **narrow** the admin branch (FR-MOD-05): admin keeps VIEW but is blocked from mutating non-owned courses via owner-shaped PATCH/DELETE; admin course-state changes go only through the moderation endpoints. `_transition_status` (`:134-167`) gains the atomic-force-private side-effects on unpublish/archive of a public course, and stays the **only** allow-listed `status==published` writer besides `visibility.py`. New `share_course`/`unshare_course`/`resubmit_course` service fns; new `approve`/`reject`/`delist`/`relist`/`remove_course` (admin). Each writes an `AuditEvent` + (for moderation transitions) a `ModerationEvent`, then bumps the catalog cache-version + best-effort sitemap purge.
- **`app/services/enrollment.py`**: `enroll` (`:91`) `status != published` → `can_enroll(db, course, viewer)`. `_maybe_issue_certificate` unaffected by this ADR (R-M8 lives in the account ADR).
- **`app/repositories/courses.py`**: `list_subjects` count (`:47`) and `search_courses` (`:138-139`, rename `only_published`→`publicly_listed_only`) → `publicly_listed_sql()`. `/courses/mine` keeps owner-scoped `publicly_listed_only=False`.
- **`app/services/learning_path.py`** (`:551/:613/:933`), **`authoring_subagents/researcher.py`** (`:246/:290`): cross-course RAG predicate → `publicly_listed_sql() OR owner_id == requesting_user.id` (R-S12 adds `AND deleted_at IS NULL AND status != 'build_failed'` to the owner branch).
- **`app/api/v1/tutor_streaming.py:150`**, **`app/mcp/tools.py:323`**: → `is_publicly_listed`. MCP `ask_tutor` keeps its stricter enrolled-or-owner floor (R-M2).
- **`app/api/v1/admin.py:375/:416`**: published counts → `publicly_listed_sql()`. `set_course_featured` (`:268-283`): require `is_publicly_listed` else `course.not_listed`; de-feature side-effects on any de-list transition.
- **`app/cli.py:351`**: → `publicly_listed_sql()`.
- **Worker**: `_schedule_embedding_index` (`courses.py:170`) is now also enqueued on transition-to-publicly-listed (approve/relist) in addition to publish, so public RAG is fresh (FR-VIS-17); best-effort, swallows broker errors.
- **Classifier (advisory)**: new `app/services/moderation_safety.py` — deterministic keyword/heuristic over title+overview+learning_outcomes against a configurable blocklist; **fail-closed-to-`pending_review`** on error (R-U5); LLM variant off-by-default. Returns a signal stored in `ModerationEvent.classifier_signal`; **never auto-approves**.
- **CI grep-guard**: `app/tests/test_no_raw_published_checks.py` — greps `app/` for `status == CourseStatus.published`, `str(...status) == "published"`, and the dead `moderation_state IN (none, approved)` / auto-approve-fast-path phrasings; allow-list = `visibility.py`, `_transition_status`, seeds/fixtures.

## Frontend changes

- **Studio** (`apps/frontend/src/app/studio/draft/[courseId]/page.tsx:66`): replace `Courses.patch(courseId,{status:"published"})` with a two-control model (FR-VIS-23): a lifecycle control (Draft/Published → `/publish`,`/unpublish`) and a separate Share control (Private/Public, enabled only when published → `/share`,`/unshare`), surfacing `pending_review`/`approved`/`rejected`/`delisted` copy. Remove the legacy `PublishAnywayButton` PATCH path.
- **Admin**: new route `src/app/admin/moderation/page.tsx` (queue + approve/reject/delist/relist/remove with confirmation on remove); admin courses page gains visibility/moderation badges. Reported/queue content rendered as inert text (FR-MOD-13).
- **Catalog/detail/sitemap**: already consume `Catalog.courses`, which becomes visibility-filtered server-side; `sitemap.ts` enumerates only publicly-listed; detail ETag (`courses.py:57-65`) incorporates `visibility+moderation_state+status`.
- **TanStack query keys** (`src/lib/query/keys.ts`): add `moderationQueue: ["admin","moderation","queue"]`, `courseModeration: (id) => ["course", id, "moderation"]`. Invalidate `qk.catalog`, `qk.subjects`, `qk.course(key)`, `qk.myCourses` on share/unshare/moderation mutations.
- **i18n** (`src/lib/i18n/messages/en.ts` + `ar.ts`, parity-enforced): `studio.lifecycle.draft/published`, `studio.share.private/public/pendingReview/approved/rejected/delisted`, `studio.share.disabledHint`, `admin.moderation.queue/approve/reject/delist/relist/remove/confirmRemove`, `course.notListable`, `course.publishPublicForbidden`, error-code copy for `course.not_listable`/`course.publish_public_forbidden`. Arabic stubs `translation_status: mt-draft` (R-U8); RTL verified.

## Alternatives considered

- **Single column / overloaded state** (`published_public` enum value) → rejected: collapses three orthogonal axes (lifecycle vs sharing vs authority), re-creates the published==public leak, and makes "published-private self-learn" inexpressible. (D-21/D-61.)
- **DB CHECK constraint coupling moderation_state to visibility** → rejected: manufactures contradictions during the sticky-history window (a delisted-then-unshared course is legitimately `private+delisted`); R-C2 mandates service-enforced invariants + tests instead.
- **Classifier auto-approve as the publish gate** → rejected: a weak heuristic must never be a security boundary (R-C1′). Default is admin-gated `pending_review`; auto-approve is an explicit off-by-default admin fast-path.
- **Atomic single-release rollout** (spec R-S8 original) → rejected: impossible against a running fleet of old `status==published` readers (R-S8′). Feature-flagged 4-step is the only leak-free path.
- **Resetting `moderation_state=none` on unshare** (spec L457) → rejected: erases reject/delist history needed for R-M9 re-approval. moderation_state is sticky.
- **Denormalizing visibility/owner onto `lesson_chunks`** for RAG → deferred (R-M6′): JOIN + predicate first; denormalized ACL column only if measured retrieval p95 regresses past the R-U7 budget.

## Consequences

- One predicate, one module, one grep-guard: the leak cannot be re-derived by a future agent reading a stale spec.
- Published-private becomes a first-class state — owners self-learn and feed their own cross-course RAG without any public exposure.
- Moderation history is durable across column rollbacks and lifecycle churn (append-only `moderation_events`).
- The rollout is leak-free by construction: the authorizer is in effect before any non-default visibility is writable.
- Cost: 11 reader migrations + a CI guard + a two-control Studio UX + an admin moderation surface; a new index on a hot table (added CONCURRENTLY). Cache/sitemap must invalidate on every transition (O(1) version bump).
- Admins lose the implicit "edit any course" power (FR-MOD-05) — intentional; they act through moderation endpoints, with a regression test asserting the block.

## Requirements satisfied

R-C1, R-C1′, R-C2, R-C6′, R-M1, R-M9, R-S8′, R-U1, R-U5; FR-VIS-01..05, 07..19, 21, 22; FR-MOD-01..09, 14, 15; FR-TUTOR-01, 02, 04 (visibility branch); FR-LEARN-01 (authorizer surface); FR-ANON-01 (404 existence-hiding); FR-AUDIT-01/02 (moderation/visibility action names); FR-MIG (additive zero-downtime); FR-DOC-01 ADR (2); D-21, D-24 (corrected to `==approved`), D-25, D-30, D-33, D-61.

## Open risks

- **R-C1′ vs stale spec**: the spec still says `IN (none, approved)` in ~6 places (L38/166/245/441/658) and ships an auto-approve fast-path (FR-VIS-09/FR-MOD-09). The grep-guard must cover these phrasings or a downstream agent re-derives the wrong rule. Mitigation: extend `test_no_raw_published_checks` to the dead phrases (R-3 cleanup sweep).
- **`CREATE INDEX CONCURRENTLY` cannot run inside Alembic's transaction** — needs a non-transactional migration block (`with op.get_context().autocommit_block()`); if it fails mid-build it leaves an INVALID index that must be dropped/rebuilt. Documented runbook step.
- **Backfill batch size vs prod table lock**: 1000-row batches assumed safe for the current catalog size; verify row count before running and tune.
- **Sitemap/CDN purge mechanism** (R-G6) is not yet confirmed at the edge (Caddy surrogate-key support unknown); fallback is the O(1) cache-version bump — needs an infra note/ADR.
- **`severe_abuse` owner edit-only access** requires `can_use_tutor`/`can_learn_in_course` to read the latest `moderation_event.reason_code` — an extra query on the learn path for flagged courses only; acceptable but must be measured against R-U7.