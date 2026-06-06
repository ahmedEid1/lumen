# Implementation-Plan Resolutions (W3 plan-critic remediation)

**Authoritative.** Supersedes `IMPLEMENTATION-PLAN.md` on conflict. Closes the plan-critic's 25 findings
(verdict: needs-work). The W4+ build reads the plan **and** this file; on conflict this wins.

## New tasks (uncovered design elements)
- **PR-1 — S6.break-glass (FR-PRIV-03 / R-S9 / D-20).** Add task: `GET /admin/briefs/{id}` decrypt path
  **gated on an OPEN report linked to that brief/course** (precondition, not audit-after), each read writing an
  immutable `moderation_event` (action=`brief_inspected`). TDD: test that the read 404s/403s without a linked
  open report, succeeds with one, and always writes the audit event. Live gate: admin opens a flagged brief via
  the report-linked path → audit row present.
- **PR-2 — S2.enforce_acl grep-guard (ADR-0029 D8).** Add a SECOND CI guard `test_no_unallowlisted_enforce_acl_false`
  forbidding new `enforce_acl=False` sites outside an allowlist (the inline-index fallback is the only legit
  user). Lands with S2.1 alongside `test_no_raw_published_checks`.
- **PR-3 — S4.fence (R-S6) is IN-SCOPE, not deferred.** Add task: a **random per-request delimiter nonce** +
  strip/escape of nonce occurrences in untrusted (cloned/user) content + structural role separation, applied
  wherever cloned lesson/quiz text enters tutor/authoring prompts. Only the broader prompt-injection *ADR
  re-eval* is deferred; the fence itself ships in S4. TDD: a lesson body containing a forged delimiter/`system:`
  boundary cannot break the fence.
- **PR-4 — S7.hnsw-recall (ADR-0029 risk #2 / R-U7).** Add task: set `rag_hnsw_ef_search_catalog=100` and a
  filtered-recall benchmark gate asserting cross-course HNSW recall doesn't starve top_k when a user's catalog
  is mostly private. Part of the perf harness (PR-7).
- **PR-5 — S2.discussions-private-gate (R-M1).** Add explicit task + test: discussion CREATE is disabled on
  `visibility=private` courses (distinct from the read authorizer); existing discussions on now-private courses
  serve only owner+enrolled.
- **PR-6 — S3.brief-rag-exclusion (FR-PRIV-01).** Add a guard test proving `learning_briefs` rows never enter
  the researcher/cross-course retrieval bundle (retrieval is over `courses`/`lesson_chunks` only, never briefs).
- **PR-7 — S0.perf-baseline (R-U7) — EARLIEST task.** Add pytest-benchmark to deps; add a baseline-capture task
  that records tutor p95 / clone-path / retrieval metrics on the seeded demo dataset **before** S2/S3/S4 land.
  The +15% / <2s gates reference this baseline. Without it the perf gates are unanchored.

## Ordering fixes
- **PR-8 — S7-pre is a STUB gate for the redaction sentinel.** The real cross-sink sentinel proof CANNOT run at
  Wave-0 (BYOK sinks are net-new in S5). S7-pre asserts only the filter wiring on existing sinks; **S5.10 is the
  real owning task** (see PR-13). Mark the S7-pre sentinel acceptance as "wiring + existing sinks only."
- **PR-9 — build_failed cross-wave (R-S12).** S2's `retrieval_acl_clause` defensively guards `build_failed` via
  string/getattr compare (enum value absent until S3). Add an S3 task with a TEST asserting the clause excludes
  `status=build_failed` once the enum value lands — closes the owner-only leak window.
- **PR-10 — carve 0035 + `Enrollment.is_self` as an EARLY Wave-2 deliverable.** Extract migration 0035
  (provenance + `is_self`) + `enroll_self` + cert-suppression as a standalone S4 sub-deliverable that lands
  BEFORE S3 consumes `is_self` for owner self-learn. Do not schedule it inside the Wave-3 clone-service unit.
- **PR-11 — guard `make migrate` against the phased foot-gun.** Add a task: the `make migrate` target (currently
  `alembic upgrade head`) must NOT blindly cross a release-phase boundary. Either split into
  `make migrate.safe` (additive, up to the phase rev) vs an explicit `make migrate.phase` with a confirmation,
  or add a migration pre-hook that refuses to apply an IRREVERSIBLE/phase-gated rev (0031, NOT-NULL tightenings)
  unless `ALLOW_PHASE_MIGRATION=1`. Encode in the runbook + Makefile.
- **PR-12 — 0044 index rebuild is CREATE-new-then-DROP-old.** Rebuilding `ix_courses_listed` (add
  `quarantined=false` to the partial WHERE) MUST `CREATE INDEX CONCURRENTLY ix_courses_listed_v2 ...` then
  `DROP INDEX CONCURRENTLY ix_courses_listed` (never DROP-then-CREATE — that leaves a no-index window on the
  catalog hot path). Same pattern for the RAG ACL index.
- **PR-13 — mid-wave migration chain-lint + ADR-number correction FIRST.** (a) Run `test_migration_chain`
  (dangling/duplicate `down_revision`) as a REQUIRED check at EACH wave-merge, not only terminal S7.10.
  (b) Move the ADR cross-numbering correction (ADR-0029/0030 cite stale 0031-0035 RAG/clone numbers; canonical
  chain is in DESIGN-RESOLUTIONS/§2.5) to an EARLY task **before** build streams open, since CLAUDE.md tells
  executors to "read the relevant ADR first."

## Untestable-task fixes
- **PR-14 — S5.10 is the concrete sentinel-proof task.** Give it real TDD: a sentinel BYOK key flows through an
  LLM call; assert the sentinel is ABSENT from each ENUMERATED sink now that they exist — `llm_calls` row,
  `agent_traces`, celery task payload, admin serializers, `/openapi.json`, `/me/export`, structlog capture,
  exception traceback. Files + assertions listed, not "extends S7pre.5."
- **PR-15 — S6.0 cascade check is a concrete test.** Replace "verify/own it" with
  `test_user_courses_owned_cascade_is_save_update` asserting only `courses_owned` changed (enrollments/reviews
  unchanged), independent of who lands it.
- **PR-16 — eval fixtures have a recording task.** Add S7 task `record_eval_fixtures` (deterministic tutor/
  authoring/ingest fixtures, no live Groq) that MUST precede the ε=0.30 eval gate (S7.4).
- **PR-17 — FR-CLONE-21 adversarial test has a home.** Concrete task in S4: malicious cloned content (injection
  in lesson body + quiz prompt) cannot exfiltrate/escape via tutor/authoring; uses the PR-3 fence; named
  fixtures + pass criteria.

## Gate strengthening
- **PR-18 — S5 gate MANDATES a live streamed BYOK turn.** Not "if flag on." The persona walkthrough MUST
  exercise the worker re-resolve/decrypt path (highest-blast-radius BYOK seam) end-to-end as a real user.
- **PR-19 — late live boot-guard check.** Add to the S5 (or pre-deploy) gate: a LIVE check that the worker
  REFUSES to boot without the KEK when a real `user_llm_credentials` row exists (the S7-pre boot check can't
  reach this branch — no credentials table yet).
- **PR-20 — Phase-D live persona gate.** After the enum-narrow (S1.13 / 0043 NOT-NULL) lands in prod, a LIVE
  persona walkthrough MUST run to catch any straggler legacy-role surface — bind it to Gate C, not just the
  runbook.
- **PR-21 — system gate enforces the FULL visual-coverage matrix** (per the post-deploy-visual-coverage standard):
  sign in as EACH persona — migrated-user (ex-student), authoring-user (ex-instructor), a learner, and admin —
  and capture EVERY auth-gated surface (`/studio*`, `/admin/*`, `/dashboard/*`, `/learn/*`, settings/BYOK,
  catalog+clone), under both `en` and `ar`/RTL, locally then on prod after deploy. No piecemeal substitute.

---

# Round-2 Plan Corrections (after confirmation gate)

Gate B (confirmation) caught that several Round-1 PRs *described* fixes that "float" — they need concrete
numbered task homes — and that one whole subsystem (the tutor's per-course RAG ACL) was never tasked. (Codex
Gate A said proceed; on divergence I side with the specific, source-verified finding.) These corrections add
the missing tasks and fix two in-plan contradictions. Authoritative over the plan body + Round-1.

- **PR-22 — NEW TASK S2.RAG-ACL (the untasked leak surface).** Verified `find_relevant_chunks(db, course_id,
  query, top_k)` (`embeddings_retrieval.py:47`, called `tutor.py:276,392`) is ACL-blind. Add task **S2.8a**:
  - **Files:** `app/services/embeddings_retrieval.py`, `app/services/tutor.py`, `app/core/config.py`.
  - **TDD (test-first):** `test_retrieval_acl.py` — (1) a private non-owner course's chunks are NEVER returned;
    (2) owner gets their own private course's chunks; (3) `build_failed`/soft-deleted owner drafts excluded
    (R-S12); (4) `enforce_acl=False` (inline-index fallback ONLY) is the single allowlisted bypass (ties PR-2).
  - **Impl:** add `viewer`/`enforce_acl` params to `find_relevant_chunks`; apply the central retrieval predicate
    (`is_publicly_listed OR (owner_id==viewer AND deleted_at IS NULL AND status!=build_failed AND NOT quarantined)`);
    per-course tutor calls pass the viewer (the endpoint already gates `can_view_course`, but the param makes the
    ACL explicit + testable and powers cross-course/inline paths).
  - **Inline-index fallback (R-U2′):** when a viewable course has live lessons but zero chunks, trigger inline
    top-N indexing within `INDEX_MAX_STALENESS_S` so the tutor never permanently refuses; this is the ONLY
    `enforce_acl=False` site. Acceptance: no-worker test → inline path fires; private course never leaks.
  - **HNSW recall (PR-4):** set `rag_hnsw_ef_search_catalog=100`; add the filtered-recall benchmark to PR-7's harness.
- **PR-23 — FIX S5 migration-number collision.** The S5.3/S5.4/S5.5 task HEADERS say "migration 0030/0031/0032"
  (stale ADR-0027 numbers — collide with S7-pre 0030 + S1 0031/0032). **Authoritative:** S5 owns **0038
  (user_llm_credentials), 0039, 0040** per the consolidated chain. Builders use those numbers; ignore the stale
  headers.
- **PR-24 — FIX S6.0 cascade scope.** The plan body S6.0 (and ADR-0030 lines 51-53) say change THREE
  relationships to `save-update`. **DR-6-R2/PR-15 win: change ONLY `User.courses_owned`.** Leave
  `User.enrollments`/`User.reviews` as `all, delete-orphan` (consistent with their CASCADE FKs; never fire under
  anonymize-in-place). S6.0's test asserts exactly one relationship changed.
- **PR-25 — concrete homes for the floating PRs (each becomes a numbered task with files+test):**
  - **S6.7 break-glass (PR-1):** `app/api/v1/admin.py` (`GET /admin/briefs/{id}`), `app/services/moderation.py`;
    test: 403 without an open linked report, 200 + `moderation_event(action=brief_inspected)` with one.
  - **S4.7 clone fence (PR-3/R-S6 + PR-17 adversarial):** `app/services/tutor_orchestrator*.py` /
    authoring prompt builders — random per-request delimiter nonce + escape; `test_clone_injection.py` with a
    malicious cloned lesson/quiz body that cannot break the fence or exfiltrate.
  - **S2.9 discussions-private gate (PR-5):** `app/services/discussions.py` `create_discussion` rejects on
    `visibility=private`; test asserts create-403 on private, read still owner+enrolled only.
  - **S3.10 brief-RAG-exclusion (PR-6):** `test_brief_not_in_rag.py` proving `learning_briefs` rows never enter
    the researcher/cross-course bundle.
  - **S7pre.8 make-migrate guard (PR-11):** edit `Makefile` — `migrate.safe` (additive up to phase rev) +
    `migrate.phase` (requires `ALLOW_PHASE_MIGRATION=1`); migration pre-hook refuses IRREVERSIBLE/phase-gated
    revs (0031, NOT-NULL tightenings) without the flag.
  - **S0.2 chain-lint + ADR-number fix EARLY (PR-13):** land `test_migration_chain` in S0 (runs at every
    wave-merge, not terminal S7.10); apply the ADR-0029/0030 stale-migration-number in-place edits in S0 BEFORE
    streams open (executors read ADRs first).
  - **S7.4a eval-fixture recording (PR-16):** a documented `make eval.record` step that captures deterministic
    triples from ONE known-good live-Groq run into `recorded.jsonl`; precedes the ε=0.30 gate.
  - **Task-ID disambiguation (Gate-B note):** the new tasks above are NET-NEW SIBLINGS, suffixed `-b` to avoid
    colliding with existing same-numbered tasks: **S6.7b** (break-glass), **S4.7b** (clone fence/adversarial),
    **S2.9b** (discussions-private), **S3.10b** (brief-RAG-exclusion), **S7pre.9** (make-migrate guard). `S0.2`,
    `S2.8a`, and `S7.4a` do not collide. Each retains its own commit + files + failing-test-first.

## Net-new tasks added to the build backlog
S0 perf baseline (PR-7) · early ADR-number fix + chain-lint discipline (PR-13) · S2 enforce_acl guard (PR-2) +
discussions-private gate (PR-5) · S3 build_failed exclusion test (PR-9) + brief-RAG-exclusion test (PR-6) ·
S4 fence nonce (PR-3) + clone adversarial test (PR-17) + early 0035/is_self carve (PR-10) ·
S5 real sentinel proof (PR-14) + live streamed BYOK + boot-guard live (PR-18/19) ·
S6 break-glass (PR-1) + concrete cascade test (PR-15) · S7 hnsw recall (PR-4) + eval fixtures (PR-16) +
make-migrate guard (PR-11) + 0044 create-then-drop (PR-12) · system gate full visual matrix (PR-21) + Phase-D
live gate (PR-20).
