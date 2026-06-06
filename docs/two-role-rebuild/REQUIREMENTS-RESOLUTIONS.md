# Requirements Resolutions (W1 Gate-B remediation)

**Authoritative.** These resolutions, decided by the orchestrator (head), **supersede any conflicting
requirement** in `docs/superpowers/specs/2026-06-03-two-role-rebuild-requirements.md`. They close the
40 findings raised by the W1 completeness critic (verdict: needs-work). Every downstream workflow
(W2 design onward) MUST read the spec **and** this file; on conflict, this file wins.

Legend: R-C* contradictions · R-M* missing · R-U* untestable→measurable · R-S* security · R-G* residual gaps.

---

## Contradictions

- **R-C1 — `moderation_state=none` overload / listing leak.** `is_publicly_listed` :=
  `visibility==public AND status==published AND moderation_state==approved`. **`none` is NOT listable.**
  `none` means "never submitted to public review" (covers private and published-private). Share
  transition (`private→public`) runs the lightweight safety check: pass → `approved` (auto, fast path);
  fail/uncertain/error → `pending_review`. A course lists **only** when `approved`. No `{public,none}`
  leak window.
- **R-C2 — CHECK constraint vs reset-to-none erasing history.** Drop the DB CHECK coupling
  moderation_state to visibility (it manufactures contradictions). Enforce coupling in the single
  central authorizer + service invariants + tests. **moderation_state is sticky — never reset to
  `none`** on unpublish/archive (those change `status`, not moderation_state). Full history lives in an
  append-only `moderation_event` audit table.
- **R-C3 — fleet reindex + no-worker = permanent `index_pending`.** A platform embedding-model change
  does **not** mass-invalidate. Each chunk records its embedding model+dim; existing chunks stay
  queryable under their recorded model until a background re-index replaces them; the tutor uses
  whatever chunks exist (never refuses on model drift). `index_pending` applies **only** to a course
  with live lessons and **zero** chunks, and is bounded by R-U2 (max-staleness SLA + inline fallback).
- **R-C4 — lossy down-migration writes removed value.** The **role data collapse is irreversible**; its
  Alembic `downgrade()` is a documented **no-op** (cannot recover student vs instructor). Rollback =
  image rollback to a pre-Phase-D build, never a down-migration that writes `student`. Schema-additive
  migrations keep proper downs; the data collapse does not.
- **R-C5 — enum membership vs accept-set are the same object.** Stage the enum explicitly:
  **Release 1** `Role={student,instructor,user,admin}` (wide; new signups write `user`) → **data
  backfill** student/instructor→user → **Release 2** `Role={user,admin}` + a normalization layer that
  maps any legacy string→`user` at every deserialization boundary (request bodies via `field_validator`,
  JWT `role` claim, straggler ORM rows via load-normalization) → **Release 3** (after token TTL drains)
  removes the normalization layer. Enum is genuinely wide during R1; narrow + normalize during R2.
- **R-C6 — grandfather + is_self + hard-removal locks owner out.** Revocation distinguishes
  owner/`is_self`/cloner enrollments from learner enrollments. `severe_abuse` removal: revoke other
  learners, **owner keeps access to remediate.** `csam`/`illegal` removal: full quarantine **including
  owner** (legal), content frozen (not deleted), admin-only. Ordinary delist/unshare/archive
  grandfathers all existing enrollments (mirrors archived-but-enrolled).

## Missing

- **R-M1 — discussions.** Discussions are **disabled on private courses** (no other participants) and
  enabled on public courses. They already gate through `can_view_course`, so they inherit the new
  authorizer — document this in the authorizer route list. **Clone never copies discussions** (other
  users' content). Existing discussions on now-private courses are served only to owner+enrolled.
- **R-M2 — MCP `ask_tutor` floor.** MCP **keeps its stricter enrolled-or-owner floor**; only REST tutor
  adopts `can_view_course`. The divergence is intentional (programmatic clients enroll explicitly) and
  documented. MCP authoring tools follow R-RBAC capability gates (R-M12 for ingest).
- **R-M3 — account deletion surface (build it).** Add `DELETE /me` (S7). It: purges BYOK credentials,
  anonymizes provenance name snapshots (R-M13), **delists** the user's public courses (content frozen,
  existing independent clones unaffected), hard-deletes ephemeral/session data, soft-deletes owned
  courses. Add FR-DEL-* for this surface; the spec's deletion obligations now have a real target.
- **R-M4 — `is_preview` on clone.** Clone resets `is_preview=false` on all lessons (preview is a
  public-marketing flag; a fresh private draft has none). Cloner re-chooses previews on publish.
- **R-M5 — tutor conversation grandfather.** On every tutor send, re-run `can_view_course` on the
  conversation's course; on access loss return `403 course.access_revoked`, no new messages; history is
  retained server-side but not served to a non-viewer. Existing migration 0028/0029 context unaffected.
- **R-M6 — RAG retrieval visibility join.** Retrieval **JOINs `lesson_chunks→lessons→modules→courses`**
  and applies the central predicate (R-S12), rather than denormalizing owner/visibility onto chunks
  (avoids drift). Add an FR mandating the JOIN + predicate; revisit denormalization only if measured
  retrieval p95 regresses past the R-U7 budget.
- **R-M7 — quota concurrency slot leak.** Redis concurrency slots are **leases with TTL** (max call
  duration + buffer); a crashed process's slot auto-expires. Redis-down → **fail-open** for concurrency
  (log+metric); the Postgres-backed job/token/dollar quotas are the hard backstop.
- **R-M8 — self-cert on published-private.** **Suppress certificate + badge issuance whenever
  `enrollment.is_self` is true**, independent of status/visibility. Closes the published-private +
  owner-self-enrolled gap against the existing completion path.
- **R-M9 — down/up moderation re-approval.** The `moderation_event` audit table (R-C2) is **separate
  and append-only** (not dropped by a visibility-column down-migration). Re-up backfill sets `approved`
  only for published courses with **no** prior reject/delist event in the audit table.
- **R-M10 — elicitation conversation cap.** Add a per-user **elicitation-session quota** per window
  (wired to the non-dollar job quota), in addition to the 6-assistant-turn per-conversation cap, so
  aggregate elicitation cost is bounded.
- **R-M11 — model-allowlist drift.** At resolution, if a stored credential's model is no longer
  allowlisted: **fall back to the platform model**, mark the credential `needs_attention`, and surface
  `byok.model_unavailable` to the user. Never silently use a disallowed model; never hard-fail the call.
- **R-M12 — ingest route-swap window.** The S1 role-collapse change set must **not** open ingest.
  `content_ingest` routes move to `RequireCapability(can_ingest_url)`, which **resolves admin-only /
  flag-off until the SSRF hardening (R-S*, charter decision 7) lands.** Ordering applies to the route
  decorator, not just the capability.
- **R-M13 — provenance PII vs erasure.** Provenance keeps `origin_course_id`, `origin_owner_id`
  (FK, nullable on delete), `origin_owner_name_snapshot`. **On account deletion the name snapshot is
  anonymized to "a deleted user"** across all clones; lineage survives, PII is erased.
- **R-M14 — sitemap cache invalidation.** Visibility/moderation transitions bump the catalog
  cache-version **and** trigger sitemap regeneration / cache purge (not only the detail ETag). Add an FR.

## Untestable → measurable

- **R-U1 — 404 timing oracle.** Drop the absolute "indistinguishable timing" claim. Requirement:
  exists-but-private and nonexistent both return **404 with identical status + body**; timing-oracle
  mitigation is best-effort, **not** a gated criterion.
- **R-U2 — `index_pending` never permanent.** Define `INDEX_MAX_STALENESS_S` (default 60s). If a course
  with live lessons + zero chunks is tutored and no async index completes within the SLA, the request
  performs an **inline best-effort index of top-N lessons** so the tutor answers (degraded, never a
  permanent refusal). Testable: inject no-worker → assert inline path fires.
- **R-U3 — no decrypted key in sinks.** Reframe: a **redaction filter wraps all structlog processors +
  exception/trace serializers**; tests assert a known sentinel key is redacted across the enumerated
  sinks (structlog, exception, trace, celery payload, admin serializer, llm_calls row). Positive
  filter-presence + enumerated-path coverage, not a negative-universal.
- **R-U4 — leak canary.** **Remove** the runtime leak-canary metric (self-defeating: it must run the
  leaky query). Replace with a direct unit/integration test asserting the retrieval predicate excludes
  private non-owner courses.
- **R-U5 — safety classifier.** Ship a small labeled corpus (≥20 cases). Gate: the deterministic
  keyword/heuristic classifier scores **100% on explicit blocklist terms**; LLM classifier is advisory
  (untested for quality); **fail-closed-to-`pending_review` on classifier error** is the tested behavior.
- **R-U6 — eval epsilon.** **epsilon = 0.30** on the 1–5 judge scale (documented in the eval ADR). The
  CI eval gate runs against **recorded fixtures** (deterministic); live eval is a separate nightly/manual
  job. Groq-unavailable mid-live-eval → mark **inconclusive**, do not fail the gate.
- **R-U7 — perf bars.** Named harness: pytest-benchmark over the seeded demo dataset on the CI runner.
  **Tutor p95 within +15%** of the same-harness pre-change baseline; **clone p95 < 2s** for a ≤100-lesson
  course on the CI runner, excluding async asset copy. Baseline captured before S-changes.
- **R-U8 — "human-quality Arabic".** Replace with a `translation_status` field (`human` |
  `mt-draft`). The i18n-parity test checks key-set equality + non-empty + no-key-echo + RTL render;
  translation **quality** is tracked via the field + reviewer sign-off, not asserted by automated test.

## Security

- **R-S1 — worker KEK blast radius.** **BYOK decryption happens only in the API/dispatch path, never in
  Celery workers.** Workers' only LLM calls are platform-pinned embeddings (R-C3/FR-EMBED-03) using the
  platform key. Therefore **the worker does not hold the BYOK KEK** — blast radius shrinks to the API.
- **R-S2 — KEK rotation atomicity.** Rotation precondition: all KEK versions deployed to all API
  processes **before** rotation starts; old version retained until rotation completes; re-wrap runs in
  batches; documented operational invariant. (Fleet is API-only per R-S1.)
- **R-S3 — dev/test KEK bypass.** Boot guard fires **whenever any `user_llm_credentials` row exists and
  no real KEK is configured, in ANY env** (not just prod). Dev derives a clearly-ephemeral KEK and the
  validate/store endpoint refuses to persist real keys under the derived KEK unless explicitly opted in.
  Forbid real BYOK keys in non-prod by policy.
- **R-S4 — validate-as-key-oracle.** Cap **distinct keys validated per user/day** (default 10); a key
  must be **stored (encrypted) before/at validation** (no validate-without-store oracle); flag rapid
  key-rotation+validate patterns for review.
- **R-S5 — clone asset laundering.** On asset re-homing, **re-run upload-time validation (MIME sniff +
  size)** on the copied bytes; never trust the source Asset row's stored type/size.
- **R-S6 — fence escape.** Use a **random per-request delimiter nonce**, strip/escape any occurrence of
  the delimiter in untrusted content, and prefer **structural role separation** over in-band delimiters
  where the provider supports it.
- **R-S7 — clone amplification.** Clones **do not eagerly copy assets or build embeddings** — asset
  re-homing is lazy/on-publish, embeddings lazy on first-tutor. Add per-user **embedding-job quota** +
  **storage quota**; clone-count caps + lazy materialization bound the amplification.
- **R-S8 — published-private leak during rollout.** The `visibility` column, the backfill (existing
  published → `visibility=public`), and the **new central authorizer ship in one atomic release**; the
  authorizer is in effect before any non-default visibility is writable. No window where a
  published-private course is judged by the legacy `status==published` rule.
- **R-S9 — admin break-glass.** Brief read requires an **open report linked to that brief/course**
  (authorization precondition), not audit-after-the-fact alone.
- **R-S10 — suspension in-flight.** Beyond refresh-token revoke + per-request `is_active` re-check, add
  **cooperative cancellation**: streaming tutor heartbeats check `is_active`; build/clone jobs check
  `is_active` at phase boundaries and abort.
- **R-S11 — report brigading.** **Auto-action never delists an already-approved course.** Reports on
  approved courses queue for **admin confirmation**. Auto-requeue is permitted only for never-approved
  courses. Add reporter account-age gating + per-course report rate limiting.
- **R-S12 — RAG owner-branch leak.** The owner branch of the retrieval predicate gains
  `AND deleted_at IS NULL AND status != 'build_failed'` so a user's own soft-deleted / failed drafts
  are excluded from their cross-course RAG.

## Residual gaps (dispositions)

- **R-G1 — quota numbers.** Adopt the proposed starting values (build concurrency 1; clone 20/h, 100/d;
  200 owned-course cap; 500-lesson clone ceiling; validate ≤5/10min & ≤10 distinct keys/day; report
  ≤10/h; orphan-draft retention 30d; 6 assistant turns; elicitation sessions per R-M10). Tunable in W2
  via config; not blocking.
- **R-G2 — eval epsilon + CI behavior.** Fixed by R-U6 (epsilon 0.30, fixtures, inconclusive-on-outage).
- **R-G3 — report auto-action policy.** Fixed by R-S11 (admin-confirm for approved; auto-requeue only
  for never-approved); threshold configurable, default off for approved courses.
- **R-G4 — BYOK launch model list.** Pin an initial curated list per provider in the registry
  (OpenAI: gpt-4o-mini, gpt-4o; Anthropic: claude-sonnet-4-x, claude-haiku-4-x; Groq:
  llama-3.3-70b-versatile; Mistral: mistral-small-latest). Registry maintenance is an admin task; W2
  designs the registry source-of-truth (config vs DB table).
- **R-G5 — safety blocklist contents.** Author a starter content-policy artifact (blocklist terms +
  thresholds) before S6 build; fixed structure by R-U5.
- **R-G6 — CDN/cache purge mechanism.** W2 to confirm whether Caddy/edge supports surrogate-key purge;
  fallback is the O(1) cache-version bump already specified. Needs an infra note/ADR.
- **R-G7 — clone asset-copy sweeper.** Since asset re-homing is lazy/on-publish (R-S7), the rollback
  orphan surface shrinks; W2 designs a periodic orphan-asset reconciliation sweep.
- **R-G8 — brief at-rest encryption.** Use **application-level field encryption for the brief's raw
  goal text, reusing the BYOK envelope module** (do not rely on unverified DB/disk encryption).
- **R-G9 — break-glass trigger.** Fixed by R-S9 (open linked report is the trigger).
- **R-G10 — `parent_message_id` linkage.** Ship the FK migration within this rebuild (additive, >=0030);
  historical traces backfilled best-effort via the existing course-scoped window join.

---

---

# Round-2 Amendments (after Gate A + Gate B re-gate)

Both gates returned **not-sound-to-proceed**, converging on the same load-bearing flaws. These
amendments **supersede the round-1 resolutions above** where they conflict. Verified against source.

- **R-S1′ — BYOK execution locus (REWRITE; R-S1 was factually wrong).** Verified worker LLM paths:
  streaming tutor (`workers/tasks/tutor_streaming.py`) and learning-path replan
  (`workers/tasks/learning_path.py`); authoring/goal-build is **in-request** (`api/v1/ai_authoring.py:328`
  awaits `draft_course`, no `.delay()`). The streaming tutor IS the primary tutor UX, so BYOK MUST
  reach a worker. Decision: (a) BYOK applies to **interactive + streaming tutor** and **in-API
  authoring/goal-build**; (b) BYOK does **not** apply to **learning-path replan** (background planning
  aid → platform model) or **embeddings** (platform-pinned). (c) A single `byok.dispatch()` helper
  decrypts the key **inside the call only**; usable from API and worker. (d) **Celery tasks carry the
  `credential_id`, never the key**; the worker re-resolves + decrypts from DB. (e) **Both API and worker**
  enforce the prod boot guard (refuse to boot without a real KEK when credentials exist). (f) The R-U3
  redaction filter wraps worker structlog/exception/trace sinks too. API + worker are co-located on one
  host (docker-compose), so the KEK lives in one trust boundary — documented, not hidden.
- **R-S8′ — rollout (REWRITE; "atomic release" is impossible with a running fleet).** Verified old
  readers judge `status==published` (`services/courses.py:432`, `repositories/courses.py:138`,
  `api/v1/tutor_streaming.py:146`). Feature-flagged 4-step zero-downtime rollout: **(1)** additive
  migration adds `visibility`/`moderation_state` (+ `moderation_event` table) and backfills existing
  published → `visibility=public, moderation_state=approved`; non-default-visibility **writes are
  flag-gated OFF**. **(2)** Deploy all readers switched to the central authorizer (behavior identical
  post-backfill). **(3)** Confirm no reader still keys on `status==published` (CI grep-guard) and drain
  old pods. **(4)** Enable the private-publish flag. The authorizer lands before any delist/private write
  is honored.
- **R-C1′ — public-listing gate (HARDEN; classifier must not be the security boundary).** Public share
  defaults to **`pending_review`** (admin moderation required before listing). The lightweight classifier
  is **advisory triage only** (priority/queue hint), **never** an auto-approve gate. `approved` requires
  an admin action; auto-approve is an explicit admin-config fast-path, **OFF by default**. Canonical
  predicate (purge every `IN (none, approved)` occurrence; add a CI grep-guard):
  `is_publicly_listed := visibility=='public' AND status=='published' AND moderation_state=='approved' AND deleted_at IS NULL`.
- **R-M3′/R-M13′ — account deletion data model (RESOLVE the ORM-vs-DB contradiction).** Verified
  `User.courses_owned` is `cascade="all, delete-orphan"` (`models/user.py:58`) while `Course.owner_id` is
  `ondelete="RESTRICT"` (`models/course.py:103`) — a physical user delete is both attempted (ORM) and
  refused (DB). Decision: self-serve `DELETE /me` = **anonymize-in-place** (no physical `users` row
  delete): set `deleted`, scrub PII (email→opaque tombstone, name→"a deleted user"), purge
  sessions/refresh/BYOK credentials, `is_active=false`; owned public courses delisted, all owned courses
  soft-deleted; provenance name snapshots anonymized across clones. **Fix the ORM inconsistency:** change
  `User.courses_owned` cascade `all, delete-orphan` → `save-update` (never orphan-delete courses; RESTRICT
  stands). True legal erasure (physical purge) is an offline admin procedure, out of self-serve scope.
- **R-CAP — per-user capability revocation storage (RESOLVE).** v1 capabilities are **pure functions over
  (User + global config)**. Per-user revocation = **suspension only** (`is_active`). **Drop** FR-BYOK-22's
  per-user `can_use_byok` revocation (no storage for it; suspension covers abuse). `can_ingest_url` is a
  **global admin-config flag** (off until SSRF hardening), not per-user. A `user_capability_overrides`
  table is deferred until granular control is actually needed.
- **Refinements folded:**
  - **R-M6′** — W2 design specifies the pgvector index plan for the visibility JOIN, with a denormalized
    ACL-column escape hatch if measured retrieval p95 regresses past the R-U7 budget.
  - **R-M7′** — the hard quota backstop is a **pre-dispatch, DB-backed request/job quota** (token/dollar
    quotas are post-dispatch and BYOK-dollar is $0); the Redis concurrency lease is best-effort only.
  - **R-M11′** — platform fallback on a now-disallowed stored model is gated by the same
    `allow_platform_fallback` consent flag as auth-error fallback, with a visible `needs_attention` notice
    (never silently route BYOK-intended content through the platform model).
  - **R-U2′** — inline index fallback: strict top-N, hard per-request timeout, counts against the
    per-user embedding-job quota, uses the concurrency lease.
  - **R-M8′** — certificate suppression lives in `_maybe_issue_certificate` (`services/enrollment.py:60`),
    not only at enrollment creation; requires adding `Enrollment.is_self`.
  - **R-C5′** — Release-3 exit criterion is **positive evidence**, not TTL alone: a query proving zero
    legacy-role rows + no legacy MCP principals + access-token TTL elapsed.
  - **R-C6′** — "owner keeps access to remediate" (severe_abuse) = **edit/remediate only**; tutor,
    public listing, and LLM amplification of the flagged material are disabled while flagged.

# Round-3 Amendment (after confirmation re-gate)

Gate B round-3 confirmed A/C/D closed but caught R-S1′ repeating its own failure mode: it labeled
learning-path "background → platform" reasoning only from the monthly beat, but `POST /me/learning-path`
(build handler `api/v1/learning_path.py:181`) and `POST /me/learning-path/replan` (`:271`) are
**in-request, user-triggered** LLM calls invoking the same planner service (`build_path`/`replan_for_user`).
Verified. Fix is a general rule, not another per-feature label:

- **R-S1″ — model-selection locus is decided by INITIATION, not execution.** **BYOK applies to every
  user-initiated, owner-scoped, foreground LLM call** — regardless of whether it executes in-API or in a
  Celery worker (worker paths receive the `credential_id` and re-resolve/decrypt via `byok.dispatch()`,
  never the raw key). **Background / scheduled / system jobs use the platform model** (no user in the
  loop to attribute a key to). Concretely: interactive + streaming tutor → BYOK; authoring/goal-build →
  BYOK; learning-path **build + manual replan** (foreground) → BYOK; **monthly beat replan** → platform;
  embeddings → platform-pinned. This rule classifies any future feature correctly without re-litigation.
- **W2 ADR-3 (BYOK) scope widened** to adjudicate the model-selection locus of **every user-initiated
  LLM feature** (tutor, authoring, goal-build, learning-path build/replan), so none is left unclassified.
- **W2 cleanup sweep (non-blocking, tracked):** purge the superseded-spec copies that precedence already
  overrides — `moderation_state IN (none, approved)` (spec ~L38/166/245/441/658), the auto-approve
  fast-path (FR-VIS-09/FR-MOD-09), and per-user `can_use_byok` revocation (FR-BYOK-22, D-59, FR-AUDIT-02
  byok.capability_*). Extend R-C1′'s CI grep-guard discipline to these phrases so the wrong rule cannot
  be re-derived by a downstream agent reading a stale spec section.

## Mandatory W2 design ADRs (gates flagged these as design-level)

1. **ADR — role vs capability** (capability layer shape; charter §1).
2. **ADR — course visibility + moderation state machine** (single authorizer; canonical
   `is_publicly_listed`; the R-S8′ rollout).
3. **ADR — BYOK** (allowlisted provider registry; envelope encryption + rotation; **R-S1″
   model-selection locus for every user-initiated LLM feature** — tutor, authoring, goal-build,
   learning-path build/replan; quotas; redaction).
4. **ADR — clone/remix** (sanitized export projection; immutable provenance; lazy assets/embeddings).
5. **ADR — RAG retrieval ACL + index plan** (R-M6′ JOIN vs denormalized ACL).
6. **ADR — account lifecycle** (anonymize-in-place; ORM cascade fix; provenance erasure).

---

## Net new scope introduced by remediation (for W3 plan)

1. `moderation_event` append-only audit table (R-C2/R-M9).
2. `DELETE /me` account-deletion surface + provenance anonymization (R-M3/R-M13).
3. Inline embedding fallback path + per-chunk embedding-model record (R-C3/R-U2).
4. Redaction filter wrapping all log/trace/serialize sinks + sentinel tests (R-U3).
5. Capability layer (`can_*`) with `can_ingest_url` closed-by-default (R-M12, charter §1).
6. Per-user embedding-job + storage quotas; Redis lease-with-TTL concurrency (R-S7/R-M7).
7. Cooperative-cancellation hooks on streaming + build/clone jobs (R-S10).
8. eval CI gate on recorded fixtures, epsilon 0.30 (R-U6).
