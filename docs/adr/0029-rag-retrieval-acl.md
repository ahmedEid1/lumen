# ADR 0029: RAG Retrieval ACL + pgvector Index Plan

## Status — Proposed

## Context (forces + current code reality)

The two-role rebuild makes every `user` an author who builds **private-by-default** courses and learns from them with the RAG tutor (CHARTER §1). This collides head-on with the current retrieval layer, which has **no ACL at all** — it scopes by `course_id` and live-lesson only, trusting the caller to authorize. Two distinct retrieval shapes exist:

1. **Per-course retrieval** — `find_relevant_chunks(db, course_id, query, top_k, ...)` in `app/services/embeddings_retrieval.py:47-136`. It JOINs `LessonChunk → Lesson → Module` and filters `Module.course_id == course_id` + `Lesson.deleted_at IS NULL` (`:99-104`, `:123-134`). **No course-level visibility/ownership/`deleted_at`/`status` check.** Its own docstring (`:62-64`) explicitly says "The caller is responsible for any further authz check." Callers: REST tutor (`services/tutor.py:276,392`), retriever sub-agent (`services/tutor_subagents/retriever.py:85`), MCP `search_lesson_content` (`mcp/tools.py:394`), and a second hand-rolled scored query in the same MCP tool (`mcp/tools.py:404-422`).

2. **Cross-catalog retrieval** — `_condense_catalog()` in `app/services/learning_path.py:512-557`. It drops the `course_id` filter and instead filters `Course.status == CourseStatus.published AND Course.deleted_at IS NULL AND Lesson.deleted_at IS NULL` (`:550-554`). Crucially, **`build_path`/`replan_for_user` already thread `user_id`** (`learning_path.py:273,300,423,436`) but `_condense_catalog` ignores it (`:306` calls it without `user_id`) — so the OR-owner branch has the user available but unused.

The caller-side gates today are the three divergent ones FR-TUTOR-01 calls out: REST tutor has **no** course gate before retrieval; streaming reserves the turn only for `Course.status == published` (`api/v1/tutor_streaming.py:150`); MCP `ask_tutor` floors on enrolled-or-owner. Once `visibility` lands (ADR 0027 course-visibility), `status == published` is no longer a safe proxy for "anyone may see this." A **published-private** course (status=published, visibility=private) would be retrievable by anyone under the cross-catalog branch, and a private draft's chunks would be reachable by any caller who can guess/learn the `course_id` under the per-course branch. This is the R-S12 / FR-VIS-05 / FR-VIS-07 leak.

**Schema reality.** `LessonChunk` (`models/lesson_chunk.py:35-60`) has `lesson_id`, `chunk_index`, `text`, `embedding vector(384)`, `token_count`, `created_at` — **no embedding model/dim record** (R-C3/FR-EMBED-03 gap). `EMBEDDING_DIM = 384` is a module constant (`:32`). The pgvector index is `ix_lesson_chunks_embedding_hnsw` (HNSW, `vector_cosine_ops`, m=16/ef_construction=64) created in migration `0018` (`alembic/versions/2026_07_07_0018-0018_lesson_chunks.py:82-85`). There is **one** secondary B-tree, `ix_lesson_chunks_lesson_id` (`:75-79`). There is **no** index supporting the new visibility JOIN's filter columns (`courses.visibility/status/moderation_state/deleted_at`, `lessons.deleted_at`, `modules.course_id`). The HNSW index has no partial predicate — it ranks across **all** chunks of **all** courses including private/deleted, then the JOIN filters post-hoc.

**Indexing reality.** Embeddings are built by `ingest_course`/`ingest_lesson` (`services/embeddings_ingest.py:136-210`), enqueued **publish-only** via `_schedule_embedding_index` (`services/courses.py:166-190`, best-effort `.delay()` that swallows broker errors `:189-190`) and by the admin bulk reindex (`api/v1/admin.py:368-380`). `delete_course` (`services/courses.py:129`) is soft-delete and enqueues nothing (per CLAUDE.md gotcha). The model/provider is platform-pinned via `get_provider()` reading `Settings.embedding_provider` (`services/embeddings.py:207-234`; `config.py:124-126`) and **ignores `user_id`** — already FR-EMBED-03-compliant for the *act* of embedding, but the indexed model is **not recorded**, so reindex-on-drift (FR-EMBED-04) and the R-C3 "stay queryable under recorded model" rule are unimplementable today.

**The empty-retrieval refusal is currently the privacy + the index-pending mechanism**, conflated. `tutor.ask` (`services/tutor.py:276-283`) returns the generic refusal when retrieval is empty — indistinguishable from "no chunks because never indexed" (R-C3/R-U2/FR-EMBED-02 gap), and in no-worker dev the publish enqueue silently no-ops so this is permanent.

**Forces:**
- **F1 — no ACL drift.** A denormalized owner/visibility column on `lesson_chunks` would have to be kept in sync with `courses` on every share/unshare/delist/soft-delete/clone, across millions of rows, for a value that already lives one JOIN away (R-M6′). Drift = silent leak.
- **F2 — R-U7 perf budget.** Tutor p95 must stay within **+15%** of the pre-change pytest-benchmark baseline on the seeded demo dataset (R-U7). Adding three JOINs + four filter predicates after an HNSW scan must not blow that.
- **F3 — HNSW recall vs. filtering.** pgvector HNSW does ANN ranking first, then post-filters; an aggressive ACL predicate that eliminates most candidates can starve `top_k` (the "filtered-out" recall problem). Must hold recall under the predicate.
- **F4 — zero-downtime against a LIVE prod fleet** (R-S8′): old readers judge `status==published`; the ACL + visibility columns + authorizer must roll out without a leak window and without a window where a published-private course is judged by the legacy rule.
- **F5 — index never permanently pending** (R-C3/R-U2′): no worker (dev) or model drift must never become a silent permanent refusal.

## Decision (the concrete chosen design)

### D1 — JOIN-based ACL, no denormalized column (R-M6′)

Retrieval applies the central predicate via the existing `LessonChunk → Lesson → Module → Course` JOIN. **No `owner_id`/`visibility` column is denormalized onto `lesson_chunks`.** The denormalized ACL column is the documented **escape hatch** (D7), reached only if measured retrieval p95 regresses past the R-U7 budget after D5's index lands.

### D2 — The retrieval predicate is pure SQL, built from one helper

Add `app/services/visibility.py::retrieval_acl_clause(viewer: User | None) -> ColumnElement[bool]` — a pure function returning a SQLAlchemy boolean over the **already-joined `Course`** alias. It is the SQL embodiment of `is_publicly_listed OR (owner)`:

```python
# is_publicly_listed (R-C1′ canonical, AND deleted_at IS NULL):
listed = and_(
    Course.visibility == Visibility.public,
    Course.status == CourseStatus.published,
    Course.moderation_state == ModerationState.approved,
    Course.deleted_at.is_(None),
)
if viewer is None:
    return listed
# owner branch, hardened per R-S12: exclude own soft-deleted / failed drafts
owner = and_(
    Course.owner_id == viewer.id,
    Course.deleted_at.is_(None),
    Course.status != CourseStatus.build_failed,
)
if viewer.is_admin():
    return or_(listed, Course.owner_id == viewer.id, Course.deleted_at.is_(None))  # admin sees own + listed; see D2a
return or_(listed, owner)
```

**D2a — admin scope in cross-course RAG.** Admins do **not** get every private course in their *learning-path/researcher* RAG — that would pull every user's private drafts into an admin's planner prompt (amplification + PII). The admin branch in the **cross-course** clause is identical to a normal user (listed OR own). Admin's elevated read is for moderation/observability surfaces, not RAG grounding. (Per-course tutor on a specific course already gates through `can_view_course`, where admin passes — D3.)

`build_failed` is a new `CourseStatus` member introduced by the goal-build/clone work (ADR-0028 clone, build pipeline); this ADR depends on it existing. If the build-pipeline ADR lands `build_failed` as a separate `build_state` column instead of a `CourseStatus` value, `retrieval_acl_clause` references that column — the predicate's **intent** (exclude the owner's failed drafts) is the contract; the column is wired at implementation against whatever the build ADR ships. Until then the clause references `CourseStatus.build_failed` and the migration that adds the enum value (owned by the build ADR) is a hard dependency recorded in this ADR's risks.

### D3 — Two distinct enforcement layers (defense in depth)

1. **Course-level authorizer (caller side, the primary gate).** Every per-course tutor entrypoint calls `can_view_course(db, course, viewer)` (`services/courses.py:424`, rewritten by ADR-0027 to use `is_publicly_listed`) **before** retrieval, returning **404 `course.not_found`** on denial (FR-TUTOR-01/03). This is unchanged scope from the visibility ADR; this ADR consumes it.
2. **Data-level ACL (SQL side, defense in depth + the only gate for cross-course).** `find_relevant_chunks` and `_condense_catalog` apply `retrieval_acl_clause(viewer)` in their WHERE. For per-course retrieval this is **redundant with #1 by design** (R-U4 leak test pins it): even if a caller forgets the authorizer, the SQL cannot return another user's private chunk. For cross-course retrieval there is no per-course authorizer, so the SQL clause **is** the boundary.

### D4 — `find_relevant_chunks` gains a required `viewer` + `course_acl` posture

New signature:

```python
async def find_relevant_chunks(
    db, *, course_id: str, query: str, top_k: int = 5,
    viewer: User | None,                # NEW — required keyword
    enforce_acl: bool = True,           # NEW — defense-in-depth toggle
    provider=None, audit=False, audit_user_id=None, audit_feature="tutor",
) -> list[LessonChunk]:
```

When `enforce_acl=True` (default) the per-course query additionally JOINs `Course` (already reachable via `Module.course_id`) and ANDs `retrieval_acl_clause(viewer)`. The course-scoped path already filters `Module.course_id == course_id`, so the ACL clause is a cheap extra predicate on the single target course's row. `enforce_acl=False` is reserved for **owner-scoped private indexing/preview internal paths that have already proven ownership** (e.g. the lazy-index inline fallback running as the owner) and for the eval harness; every production caller passes the real `viewer`. A CI grep-guard (extending R-C1′'s discipline) forbids new `enforce_acl=False` call sites outside an allowlist.

`_condense_catalog` gains a required `viewer: User` param; `build_path`/`replan_for_user` pass their existing `user_id`-resolved `User` through (the user is already loaded for `_load_constraints`, `learning_path.py:326`). Its WHERE swaps `Course.status == published` (`learning_path.py:551`) for `retrieval_acl_clause(viewer)` (FR-VIS-05). The authoring **researcher** sub-agent's cross-catalog path takes the same treatment.

### D5 — pgvector index plan to hold the R-U7 budget (R-M6′)

The risk is HNSW ranking across **all** chunks (including private/deleted) then the JOIN discarding most. Plan, in priority order:

1. **`ix_chunks_acl` composite B-tree on the JOIN spine** — `modules(course_id)`, plus a **covering composite on `courses` for the ACL predicate**: `CREATE INDEX ix_courses_acl ON courses (visibility, status, moderation_state, owner_id) WHERE deleted_at IS NULL;` (partial, live-only). This lets the planner resolve the ACL JOIN with index-only scans on the small `courses` table rather than re-reading heap rows for every HNSW candidate. `lessons.deleted_at` is already cheap via the existing `ix_lessons_module_id_order`; add `ix_lessons_module_id_live` partial `(module_id) WHERE deleted_at IS NULL` to keep the live-lesson filter index-backed.
2. **Raise HNSW `ef_search` on the cross-course path only.** For per-course retrieval the candidate pool is already tiny (one course), so default `ef_search=40` is fine. For cross-catalog retrieval, set `SET LOCAL hnsw.ef_search = 100` inside the `_condense_catalog` transaction (via `db.execute(text("SET LOCAL hnsw.ef_search = 100"))` before the SELECT) so post-filter recall holds when the ACL clause discards private candidates. Tunable via `Settings.rag_hnsw_ef_search_catalog` (default 100).
3. **Keep the single global HNSW index** (`ix_lesson_chunks_embedding_hnsw`). A **partial** HNSW index `WHERE` the chunk's course is public is rejected (D-alt below): partial pgvector indexes can't reference a joined table's column, and a denormalized flag to make it indexable reintroduces F1's drift.
4. **R-U7 gate.** Capture the pytest-benchmark baseline for `find_relevant_chunks` (per-course) and `_condense_catalog` (cross-course) on the seeded demo dataset **before** D4 lands. After: per-course p95 ≤ baseline+15%; cross-course p95 ≤ baseline+15%. If cross-course regresses past budget after D5.1–D5.2, escalate to the **denormalized ACL escape hatch** (D7).

### D6 — per-chunk embedding model+dim record (R-C3 / FR-EMBED-03 / FR-EMBED-04)

`lesson_chunks` gains `embedding_model VARCHAR(128) NOT NULL` and `embedding_dim SMALLINT NOT NULL`. `ingest_lesson` stamps them from the resolving provider (`provider.dim` + a new `provider.model_id` property added to the `EmbeddingProvider` Protocol and all three concrete providers in `services/embeddings.py`). Semantics (R-C3): a platform embedding-model change **does not mass-invalidate**; existing chunks stay queryable under their recorded model; the tutor uses whatever chunks exist. Drift detection (FR-EMBED-04, `should`): a course is **stale** iff it has live lessons and **all** its chunks' `(embedding_model, embedding_dim)` differ from the current platform `get_provider()` identity — staleness triggers a background reindex and surfaces `tutor.index_pending`, but **never refuses** while old chunks exist. Mixed-model within one course (mid-reindex) is allowed transiently; retrieval simply ranks whatever's present (cosine space is column-shared at dim 384). `embedding_dim` exists to fail-fast if a future provider emits a non-384 vector into the shared column.

### D7 — denormalized ACL escape hatch (specified, NOT built)

If and only if D5 fails the R-U7 cross-course budget: add `lesson_chunks.course_acl_listed BOOLEAN NOT NULL DEFAULT false` + `lesson_chunks.course_owner_id VARCHAR(64)`, maintained by (a) the ingest path (set at write time) and (b) a trigger/after-commit hook on `courses` visibility/status/moderation/soft-delete transitions that bulk-updates the owning course's chunks, plus a nightly reconciliation sweep (R-G7 pattern). Retrieval then filters `(course_acl_listed OR course_owner_id = :viewer)` with a partial HNSW index `WHERE course_acl_listed`. This is the explicit fallback the gates asked us to name; it is **not** the default because of F1.

### D8 — `index_pending` bounded by `INDEX_MAX_STALENESS_S` + inline top-N fallback (R-U2′ / FR-EMBED-01/02)

Introduce a **course index state**, derived (not stored as denormalized truth) at tutor time:
- **indexed** — live lessons exist and ≥1 chunk exists for the course.
- **pending** — live lessons exist and **zero** chunks exist (R-C3 scope: `index_pending` applies only here).
- **empty** — no live lessons (genuine "nothing to teach").

On a per-course tutor turn, after `can_view_course` passes and **before** the empty-retrieval refusal, compute state with one cheap `EXISTS` (covered by `ix_lesson_chunks_lesson_id` via the lesson JOIN). When **pending**:
1. Enqueue `index_course_embeddings.delay(course_id)` (idempotent; FR-EMBED-01 lazy trigger, now also for private/draft owner courses, not publish-only).
2. Wait for async completion up to **`INDEX_MAX_STALENESS_S`** (new `Settings.index_max_staleness_s`, **default 60**), polling the chunk-EXISTS at short intervals (lease-aware, R-S10 cancellation honored).
3. If no chunk appears within the SLA (no worker in dev, or slow), run an **inline best-effort index of the top-N lessons** (`Settings.index_inline_top_n`, default 5 — the N most-recently-updated live lessons) **as the owner** (`enforce_acl=False` permitted here because ownership is already proven by `can_view_course`), strictly bounded by a **hard per-request timeout** (`Settings.index_inline_timeout_s`, default 8s) and counting against the **per-user embedding-job quota** + the Redis concurrency lease (R-U2′/R-S7). Then retrieve over whatever now exists.
4. If still nothing (timeout/quota-exhausted), return the localized **`tutor.index_pending`** signal with an actionable hint — **never** the generic refusal, **never** a permanent silent refusal (FR-EMBED-02). This signal is distinct from the empty-retrieval refusal (which now means only "indexed, but no material on this topic").

`tutor.index_pending` is a structured outcome on `TutorAnswer` (`refused=True, reason="index_pending"`), surfaced over REST + streaming + MCP.

### D9 — owner-scoped private indexing + leak tests (FR-EMBED-01 / R-U4)

Private content is indexed (lazily, owner-triggered) but indexing **never** makes private chunks retrievable by another user's tutor or the researcher — guaranteed by D2's `retrieval_acl_clause`, not by withholding the index. The **runtime leak-canary metric is removed** (R-U4: self-defeating — it must run the leaky query). It is replaced by direct unit/integration tests (D11).

## Data model changes

### Model: `LessonChunk` (`app/models/lesson_chunk.py`)
Add two non-null columns:
- `embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)`
- `embedding_dim: Mapped[int] = mapped_column(SmallInteger, nullable=False)`

No change to `embedding`, `lesson_id`, uniqueness. The escape-hatch columns (D7) are **not** added now.

### Index changes
- New `ix_courses_acl` (partial composite on `courses`, live-only) — supports the ACL JOIN.
- New `ix_lessons_module_id_live` (partial on `lessons`, live-only) — supports the live-lesson filter.
- Existing `ix_lesson_chunks_embedding_hnsw` and `ix_lesson_chunks_lesson_id` unchanged.

### Migrations (numbered, ordered, zero-downtime against LIVE prod + running fleet)

This ADR's migrations must interleave correctly with ADR-0027's visibility columns. **Ordering contract:** the `visibility`/`status`/`moderation_state` columns + backfill ship in ADR-0027's migration **0030** (additive, flag-gated writes; R-S8′ step 1). This ADR's migrations are **0033–0035**, after 0030 so `ix_courses_acl` can reference `visibility`/`moderation_state`. (0031/0032 are reserved for the clone-provenance and account-lifecycle ADRs per their R-G10/FR-CLONE-09 additive migrations.)

- **Migration 0033 — `lesson_chunks` embedding-model record (additive, backfilled).**
  - `ALTER TABLE lesson_chunks ADD COLUMN embedding_model VARCHAR(128); ADD COLUMN embedding_dim SMALLINT;` (nullable first — **no table rewrite**, instant on PG17 with NULL default).
  - Backfill in batches: `UPDATE lesson_chunks SET embedding_model = :platform_model, embedding_dim = 384 WHERE embedding_model IS NULL` chunked by PK range (e.g. 5k rows/batch, brief autocommit per batch) to avoid a long lock on the live table. `:platform_model` = the model that *actually* produced existing prod chunks (Groq/local per `Settings.embedding_provider` at deploy time — operator confirms; documented in the migration docstring).
  - After backfill drains, a **follow-up migration 0035** (below) sets `NOT NULL`. Do **not** set NOT NULL in 0033 — a running old fleet still INSERTs chunks without these columns until the new image is everywhere.
  - `downgrade()`: drop both columns (additive, fully reversible).
- **Migration 0034 — ACL JOIN indexes (concurrent, additive).**
  - `CREATE INDEX CONCURRENTLY ix_courses_acl ON courses (visibility, status, moderation_state, owner_id) WHERE deleted_at IS NULL;`
  - `CREATE INDEX CONCURRENTLY ix_lessons_module_id_live ON lessons (module_id) WHERE deleted_at IS NULL;`
  - **`CONCURRENTLY` requires non-transactional migration**: set `# revision ... ` with Alembic's `op.execute` wrapped so autocommit is on — implement via `with op.get_context().autocommit_block():` around both `CREATE INDEX CONCURRENTLY`. No table lock; safe on the live fleet mid-traffic. If a `CONCURRENTLY` build fails it leaves an INVALID index — the migration first `DROP INDEX IF EXISTS` each name to be re-runnable.
  - `downgrade()`: `DROP INDEX CONCURRENTLY IF EXISTS` both.
- **Migration 0035 — `lesson_chunks` model columns NOT NULL (after fleet drain).**
  - Precondition (documented operational gate, mirrors R-S8′ step 3): the new image (new `ingest_lesson` that always stamps `embedding_model`/`embedding_dim`) is deployed to **all** workers/API and 0033's backfill has drained. Then `ALTER TABLE lesson_chunks ALTER COLUMN embedding_model SET NOT NULL; ALTER COLUMN embedding_dim SET NOT NULL;` (PG17 validates against the now-fully-populated column; brief `ACCESS EXCLUSIVE` but instant since no rewrite).
  - `downgrade()`: drop the NOT NULL constraints.

**Rollout interleave (R-S8′-aligned):** 0030 (visibility, ADR-0027) → deploy authorizer-aware readers (incl. this ADR's `retrieval_acl_clause` behind the same code release; behavior identical post-backfill because everything is public/approved) → 0033 + 0034 → deploy new ingest image that stamps model columns → drain old pods → 0035. The ACL clause is in effect the moment readers deploy; since the 0030 backfill sets existing published → `visibility=public, moderation_state=approved`, the clause returns the same set as `status==published` did, so **no leak window and no behavior change** until non-default visibility is writable (gated by ADR-0027's flag).

## API changes

No new endpoints. Behavioral/contract changes:

- **All tutor entrypoints** (REST `POST /tutor/conversations`, `POST /tutor/conversations/{id}/messages`, streaming `POST /tutor/turns`, MCP `ask_tutor`/`search_lesson_content`) now thread the authenticated `viewer` into retrieval. `search_lesson_content`'s second hand-rolled scored query (`mcp/tools.py:404-422`) is refactored to call `find_relevant_chunks(..., viewer=principal_user, audit=...)` (or, if the score must be returned on the wire, the same `retrieval_acl_clause` is ANDed into that local SELECT — no raw `Module.course_id`-only filter survives).
- **New tutor outcome `tutor.index_pending`.** `TutorAnswer` schema (Pydantic v2, `app/schemas/tutor.py`) gains `reason: Literal["refused", "index_pending"] | None = None`. Streaming SSE emits a terminal `index_pending` event; the turn `status` poll (`GET /tutor/turns/{id}/status`) can return a new terminal `index_pending` value alongside the existing set.
- **Error codes / outcome codes:**
  - `course.not_found` (404) — denied tutor access (FR-TUTOR-03), already the convention.
  - `tutor.index_pending` — **not** an HTTP error; it is a 200 `TutorAnswer` body with `reason="index_pending"` + localized hint (a refusal is a normal answer shape, per `services/tutor.py:271`). Envelope unchanged.
  - `auth.required` (401) — anonymous tutor (FR-TUTOR-05), unchanged.
- OpenAPI regen + `make api-client` after the `TutorAnswer.reason` field lands (CLAUDE.md contract rule).

## Service / worker changes

- **`app/services/embeddings_retrieval.py::find_relevant_chunks`** — add required `viewer` + `enforce_acl` kwargs; JOIN `Course` and AND `retrieval_acl_clause(viewer)` in both the audit and non-audit SELECTs (`:97-108`, `:123-134`).
- **`app/services/visibility.py`** (new module, or extend `services/courses.py` per FR-VIS-03) — `retrieval_acl_clause(viewer)`, `is_publicly_listed(course)` (pure), reused by D2. This is the **same** authorizer module ADR-0027 introduces; this ADR adds the SQL-clause variant.
- **`app/services/learning_path.py::_condense_catalog`** — add required `viewer`; swap `Course.status == published` (`:551`) for `retrieval_acl_clause(viewer)`; `SET LOCAL hnsw.ef_search` before the SELECT (D5.2). Callers `build_path`/`replan_for_user` pass the loaded `User`.
- **`app/services/embeddings.py`** — add `model_id: str` to the `EmbeddingProvider` Protocol and to `LocalEmbeddingProvider`/`OpenAIEmbeddingProvider`/`NoopEmbeddingProvider`; `get_provider()` unchanged (still platform-pinned, `user_id`-ignorant — FR-EMBED-03).
- **`app/services/embeddings_ingest.py::ingest_lesson`** — stamp `embedding_model=prov.model_id`, `embedding_dim=prov.dim` on each `LessonChunk` (`:163-172`).
- **`app/services/tutor.py::ask`/`ask_with_trace`** — before the empty-retrieval refusal (`:276-283`, `:392-404`): compute index state (D8), enqueue + bounded-wait + inline top-N fallback, return `tutor.index_pending` when pending-and-unbuildable-in-SLA. Thread `viewer` into `find_relevant_chunks`.
- **`app/services/tutor_subagents/retriever.py::dispatch`** — thread `viewer` into `find_relevant_chunks` (`:85`).
- **`app/workers/tasks/embeddings.py::index_course_embeddings`** — unchanged signature; now also fired by the lazy-index path for private/owner courses. `ingest_course` (`embeddings_ingest.py:184`) is platform-pinned (worker uses platform key, never BYOK — R-S1″ embeddings exclusion), so no worker KEK needed.
- **New: inline index helper** `services/embeddings_ingest.py::ingest_course_inline(db, course_id, *, top_n, timeout_s)` — owner-scoped, bounded best-effort for D8.3, reusing `ingest_lesson` over the N most-recently-updated live lessons; honors the concurrency lease + per-user embedding-job quota; cooperative-cancel at lesson boundaries (R-S10).
- **Authorizer/capability/dispatch:** no new capability. Tutor capability is `can_view_course` (consumed). Cross-course RAG carries no capability beyond authentication; the SQL ACL is the boundary.

## Frontend changes

- **App Router:** no new routes. The learner tutor panel lives under the lesson/learn route (`learn/[slug]`); the studio owner tutor under `studio/draft/[courseId]`.
- **Components:** the tutor panel component (`src/lib/tutor/use-tutor-stream.ts` consumer + the chat panel) renders a distinct **index-pending state** when `reason === "index_pending"` — a non-error "we're indexing your course, ask again in a moment" affordance with a retry button, visually distinct from the "no material found" refusal. The SSE stream hook (`use-tutor-stream.ts`) handles the new terminal `index_pending` event.
- **TanStack query keys** (`src/lib/query/keys.ts`): no new keys; the existing tutor conversation/turn keys carry the new `reason`. The turn-status poll key may surface `index_pending` as a terminal status (no key shape change).
- **i18n (flat dotted keys in `src/lib/i18n/messages/{en,ar}.ts`):** add
  - `en.ts`: `"tutor.indexPending.title": "Indexing your course…"`, `"tutor.indexPending.body": "We're preparing this course for the tutor. Try your question again in a moment."`, `"tutor.indexPending.retry": "Try again"`.
  - `ar.ts`: `"tutor.indexPending.title": "جارٍ فهرسة دورتك…"`, `"tutor.indexPending.body": "نقوم بتجهيز هذه الدورة للمعلّم الذكي. حاول طرح سؤالك مرة أخرى بعد لحظات."`, `"tutor.indexPending.retry": "حاول مرة أخرى"`.
  - i18n-parity test (key-set equality + non-empty + RTL render) per R-U8; `translation_status` = `human` for these three.

## Alternatives considered

- **Denormalize `owner_id`/`visibility`/`acl_listed` onto `lesson_chunks` (chosen as escape hatch only)** → rejected as default: drift surface (F1) across share/unshare/delist/soft-delete/clone, requiring a trigger + reconciliation sweep, for a value one indexed JOIN away. R-M6′ mandates JOIN-first; denorm only if measured p95 regresses (D7).
- **Partial HNSW index `WHERE course is public`** → rejected: pgvector partial indexes can't predicate on a *joined* table's column; making it indexable requires the denormalized flag (reintroduces F1), and it wouldn't cover the owner-private branch anyway (the owner must still retrieve their own private chunks, which a public-only partial index excludes).
- **One HNSW index per course / per tenant** → rejected: thousands of tiny indexes, unbounded as users grow, terrible build/maintenance amplification; pgvector recall benefits from a single well-populated graph.
- **Caller-side authorization only (no SQL ACL)** → rejected: R-U4 + NFR-SEC-5 require defense-in-depth; cross-course RAG has *no* per-course caller gate, so the SQL clause is mandatory there regardless. A forgotten authorizer at one of four+ tutor entrypoints would silently leak.
- **Invalidate all chunks on platform embedding-model change** → rejected by R-C3: with no worker (dev) or a large catalog this strands every course in permanent `index_pending`. Per-chunk model record + "queryable under recorded model until reindexed" is the resolution.
- **`index_pending` = the existing empty-retrieval refusal** → rejected: conflates "not indexed" with "no material" (FR-EMBED-02), and in no-worker dev becomes a permanent silent refusal (R-U2). Bounded SLA + inline fallback fixes it.
- **Runtime leak-canary metric (FR-VIS-05/FR-OBS-01 "SHOULD be 0")** → rejected per R-U4: the metric must run the leaky (old-predicate) query to count leaks, which is self-defeating. Replaced by direct exclusion tests (D11).

## Consequences

**Positive:** Single source of truth for ACL (no chunk-level drift). Defense-in-depth: SQL cannot return another user's private chunk even if a caller forgets the authorizer. Cross-course RAG closes the published-private exfiltration leak (FR-VIS-05/R-S12), including the owner's own soft-deleted/failed drafts. Per-chunk model record unblocks reindex-on-drift without mass invalidation. `index_pending` is observable, bounded, and never permanent. Zero-downtime rollout against the live fleet via additive→backfill→NOT-NULL ordering and `CONCURRENTLY` index builds.

**Negative / costs:** Every per-course retrieval now JOINs `Course` (one extra small-table lookup, mitigated by `ix_courses_acl`). Cross-course retrieval raises `ef_search` (more graph hops; bounded by D5.4 R-U7 gate). Two new `lesson_chunks` columns (~3 bytes/row + a 128-char model string — negligible vs the 384-float vector). The 0033 backfill touches every existing chunk row (batched, off-peak). The inline-index fallback can make a tutor turn briefly slower (hard-capped at `index_inline_timeout_s`) when an owner first tutors an unindexed private course in a no-worker environment. `find_relevant_chunks`' new required `viewer` is a breaking internal signature change — all four+ call sites updated in the same release.

**Operational:** New `Settings`: `index_max_staleness_s` (60), `index_inline_top_n` (5), `index_inline_timeout_s` (8), `rag_hnsw_ef_search_catalog` (100). Migration 0035 has a human operational precondition (fleet fully on new ingest image) — documented, gated, mirrors R-S8′ step 3.

## Requirements satisfied

R-M6′ (JOIN vs denormalized ACL + named escape hatch), R-S12 (owner-branch `deleted_at IS NULL AND status != build_failed`), R-C3 (per-chunk model+dim record; no mass invalidation), R-U2′ (`INDEX_MAX_STALENESS_S` + inline top-N fallback + per-request timeout + quota/lease), R-U4 (leak-canary removed; direct exclusion tests), R-U7 (pgvector index plan + benchmark gate ≤ baseline+15%), R-S8′ (zero-downtime interleaved rollout, no leak window), R-M2 (MCP keeps its stricter floor; only REST/streaming adopt `can_view_course` — this ADR does not relax MCP's enrolled-or-owner gate, it only adds the SQL ACL as defense-in-depth). FR-VIS-05, FR-VIS-07, FR-EMBED-01, FR-EMBED-02, FR-EMBED-03, FR-EMBED-04, FR-TUTOR-01, FR-TUTOR-02, FR-TUTOR-03, FR-OBS-01 (index-pending + lazy-index metrics; leak-canary explicitly dropped per R-U4), NFR-SEC-5, NFR-PERF-2, NFR-PERF-3.

## Open risks

1. **`build_failed` dependency.** The owner branch references `status != build_failed`. If the goal-build/clone ADR ships `build_failed` as a separate `build_state` column rather than a `CourseStatus` member, `retrieval_acl_clause` must reference that column. **Mitigation:** the predicate's *intent* (exclude owner's failed drafts) is the contract; wire the exact column at implementation against whatever the build ADR lands. Cross-ADR sequencing note recorded.
2. **HNSW filtered-recall under the ACL clause.** If a user's catalog is mostly private, the cross-course HNSW scan may discard most candidates before reaching `top_k`. **Mitigation:** D5.2 `ef_search=100` (tunable) + the D5.4 benchmark gate; escalation path is the D7 partial-index escape hatch.
3. **Migration 0034 `CONCURRENTLY` on a busy prod table.** Index build on a large `lesson_chunks`/`courses` under load can be slow and, on failure, leave an INVALID index. **Mitigation:** `DROP INDEX IF EXISTS` + `autocommit_block`; run off-peak; monitor.
4. **Inline-index fallback amplification.** A burst of owners first-tutoring large unindexed private courses in a no-worker window could spike DB/embedding load. **Mitigation:** per-user embedding-job quota + concurrency lease + `top_n`/timeout caps (R-S7).
5. **0033 backfill model attribution.** The backfilled `embedding_model` must match the model that actually produced existing prod chunks; a wrong value would falsely mark current chunks stale and trigger needless reindex. **Mitigation:** operator confirms the deployed `EMBEDDING_PROVIDER`/model at backfill time; documented in the migration; FR-EMBED-04 only *triggers reindex + index_pending*, never refuses, so a misattribution is self-healing, not a leak.
6. **`enforce_acl=False` misuse.** The escape toggle for owner-proven paths could be copied into a leaky call site. **Mitigation:** CI grep-guard with an allowlist + the R-U4 exclusion tests that assert private non-owner chunks never surface even when the authorizer is bypassed.