# ADR 0030: Account lifecycle — anonymize-in-place deletion + ORM cascade fix

## Status — Proposed

## Context (forces + current code reality with file:line)

The two-role rebuild (CHARTER §3 decision 10; REQUIREMENTS-RESOLUTIONS R-M3′/R-M13′) requires a self-serve account-deletion surface whose semantics are coherent with the rest of the rebuild (clone provenance, BYOK credentials, suspension). Today's implementation is incoherent at two levels — the ORM and the live endpoint — and the spec's own deletion FRs (FR-DEL-02, FR-BYOK-18, FR-DEL-01) point at obligations that have no correct target. This ADR fixes that.

**1. Verified ORM-vs-DB contradiction (the headline bug).**
- `User.courses_owned` declares `cascade="all, delete-orphan"` (`apps/backend/app/models/user.py:55-59`).
- `Course.owner_id` declares `ForeignKey("users.id", ondelete="RESTRICT")` (`apps/backend/app/models/course.py:102-104`).

A physical `DELETE FROM users WHERE id=…` is therefore **both attempted and refused**: SQLAlchemy's `delete-orphan` would try to delete the owner's `courses`, while the DB-level `RESTRICT` on `owner_id` forbids deleting a user that still owns any course. If the ORM cascade ran first it would silently destroy course rows (and, via their own `CASCADE` FKs, modules/lessons/enrollments/reviews/discussions of *other* users); if the FK fired it would raise `IntegrityError`. The relationship cascade and the FK policy encode **opposite intents**. This is unsafe and must be reconciled before any deletion path is trusted.

**2. The existing `DELETE /me` already does anonymize-in-place — but partially and unaudited-for-the-rebuild-surface.**
`delete_me` (`apps/backend/app/api/v1/users.py:194-216`) already: verifies password, scrubs `email`/`full_name`/`avatar_url`/`bio`, rotates `password_hash` to an unusable value, sets `is_active=False`, revokes refresh tokens (`users_repo.revoke_all_refresh_tokens`, `apps/backend/app/repositories/users.py:84`), and writes a `user.deleted` audit row. It does **not** ever call `session.delete(user)` — so the `courses_owned` cascade never fires *today* and the bug is latent. It also does **not**: purge BYOK credentials (the table doesn't exist yet — sibling ADR-0029 BYOK), anonymize provenance snapshots (columns don't exist yet — sibling ADR-0028 clone), delist/soft-delete owned courses, or scrub authored discussions. The endpoint email tombstone `deleted-{id}@lumen.invalid` (`users.py:210`) collides with no live address (`.invalid` is reserved per RFC 6761) and survives the `CITEXT unique` constraint (`user.py:28`).

**3. Every FK into `users` — verified ondelete behavior (drives what anonymize-in-place must touch).** Because we never physically delete the row, all of these keep pointing at the (now-anonymized) tombstone row, which is exactly what we want for lineage/audit/cost integrity:

| Referencing table | Column | ondelete | Disposition under anonymize-in-place |
|---|---|---|---|
| `courses` | `owner_id` | `RESTRICT` (`course.py:103`) | row kept → soft-delete + delist owned; RESTRICT now never triggers |
| `auth_refresh_tokens` | `user_id` | `CASCADE` (`user.py:78`) | hard-deleted (revoke-all already; see below) |
| `enrollments` | `user_id` | `CASCADE` (`course.py:209`) | **kept** (the user's own learning rows; severed on real purge only) |
| `reviews` | `author_id` | `CASCADE` (`course.py:258`) | soft-delete the deleter's reviews (`reviews.deleted_at`, `course.py:265`) |
| `discussions` / `discussion_replies` | `author_id` | `SET NULL` (`discussion.py:43,68`) | author already nullable → soft-delete deleter's posts (`deleted_at`, `discussion.py:47,71`) |
| `audit_events` | `actor_id` | `SET NULL` (`audit.py:21-23`) | row kept (append-only; FR-AUDIT-03) |
| `assets` | `owner_id` | `CASCADE` (`asset.py:20-22`) | kept (asset bytes orphan-swept offline) |
| `mcp_clients` | `owner_user_id` | `CASCADE` (`mcp_client.py:108-110`) | revoke (`revoked_at`) |
| `tutor_conversations` | `user_id` | `CASCADE` (`tutor_conversation.py:86`) | kept |
| `review_cards` | `user_id` | `CASCADE` (`review_card.py:79`) | kept |
| `learning_paths` | `user_id` | `CASCADE` (`learning_path.py:92`) | kept |
| `course_draft_traces` | `user_id` | `CASCADE` (`course_draft_trace.py:155`) | kept (forensic) |
| `tutor_turn_jobs` | `user_id` | `CASCADE` (`tutor_turn_job.py:65`) | kept |
| `notifications` | `user_id` | `CASCADE` (`notification.py:33`) | kept |
| `llm_calls` | `user_id` (plain `String(64)`, **no FK**, `llm_call.py:106`) | n/a | kept (cost history; FR-BYOK-18, D-58) |

The plain-string `user_id` on `llm_calls`/`agent_traces`/`retrieval_audits` (sentinel-tolerant, `llm_call.py:73,106`) means cost/observability history is structurally immune to the deletion path — no FK to honor.

**4. Suspension is a distinct, already-wired lifecycle state.** `get_current_user_optional` re-checks `is_active` on every request (`apps/backend/app/api/deps.py:49`); `authenticate` blocks inactive users (`apps/backend/app/services/auth.py:80`); `rotate_refresh` raises `auth.inactive` for inactive users (`apps/backend/app/services/auth.py:174-175`). The rebuild needs suspension (FR-SUSP-01/02, R-CAP) to share the `is_active` flag with deletion but remain reversible, plus a distinct `auth.account_suspended` code (FR-SUSP-04) and **cooperative cancellation** (R-S10) at streaming heartbeats and build/clone phase boundaries. There is exactly one cancellation comment but no `is_active` check in `tutor_streaming.py:86`.

**5. R-CAP collapses per-user capability storage into `is_active`.** v1 capabilities are pure functions over `(User + global config)`; the only per-user revocation lever is suspension. No `user_capability_overrides` table; no per-user `can_use_byok`. Deletion and suspension therefore both route through `is_active` + refresh-token revocation, with deletion adding the irreversible PII scrub.

**6. Legal erasure is explicitly out of self-serve scope** (R-M3′ last clause; CHARTER §3.10). Physical row purge is an offline admin procedure because (a) `owner_id RESTRICT` makes it a multi-table choreography, and (b) GDPR Art. 17 erasure must be auditable and reversible-until-committed by an operator, not a self-serve button.

## Decision (the concrete chosen design)

**Self-serve `DELETE /me` = anonymize-in-place. We never call `session.delete(user)` for a self-serve deletion. The `users` row persists forever as an anonymized tombstone; all FK graphs stay intact; PII is irreversibly scrubbed.**

### D1 — Fix the ORM cascade (the bug)

> **Scope narrowed by DR-6-R2 (supersedes this D1 over-correction).** The
> implemented change is **exactly one** relationship: `User.courses_owned`
> `"all, delete-orphan"` → `"save-update"`. `User.enrollments` and
> `User.reviews` stay `all, delete-orphan` — they are internally consistent
> with their `CASCADE` FKs (`course.py:209/257`) and never fire under
> anonymize-in-place (we never `session.delete(user)`), so re-cascading them
> buys nothing and risks behavior drift. `User.refresh_tokens` is unchanged.
> See DESIGN-RESOLUTIONS DR-6/DR-6-R2 + PLAN-RESOLUTIONS PR-15/PR-24 and the
> introspection test `test_account_cascade_invariant.py` (asserts ONLY
> `courses_owned` lost `delete-orphan`).

Change `User.courses_owned` cascade from `"all, delete-orphan"` → `"save-update"` (`user.py:58`). Rationale: courses are user-visible content with their own soft-delete (`course.py:129`) and a deliberate `RESTRICT` FK (`course.py:103`); they must **never** be orphan-deleted by a parent-collection mutation. `save-update` keeps relationship convenience (assigning a course to `user.courses_owned` persists `owner_id`) without authorizing deletion. `RESTRICT` stands as a DB-level backstop: any future code path that tries to physically delete a course-owning user gets an `IntegrityError` rather than silent data loss. The Round-1 plan to *also* re-cascade `User.enrollments` and `User.reviews` is **superseded by DR-6-R2** (see the admonition above) — leave them as `all, delete-orphan`:
- `User.enrollments` (`user.py`, cascade `all, delete-orphan`) → **unchanged** (consistent with its CASCADE FK; never fires under anonymize-in-place).
- `User.reviews` (`user.py`, cascade `all, delete-orphan`) → **unchanged** (the deletion service soft-deletes reviews explicitly; the ORM cascade never runs).
- `User.refresh_tokens` (`user.py`, cascade `all, delete-orphan`) → **keep as-is**. Refresh tokens are ephemeral hard-delete data (CLAUDE.md soft-delete policy); orphan-delete is correct here, and the FK is `CASCADE` (`user.py:78`).

Each relationship is internally consistent with its FK ondelete policy; only the `courses_owned`↔`RESTRICT` contradiction is corrected (DR-6-R2).

### D2 — `delete_me` becomes a service function with the full R-M3′ choreography
Extract the logic from the route into `app/services/account.py::delete_account(db, *, user, password, ip, user_agent)`, run inside the request's single transaction, in this order (so a failure rolls everything back, no orphan/partial tombstone):

1. **Authn re-check** — `verify_password(password, user.password_hash)` (`security.py`); fail → `401 auth.invalid_credentials` (unchanged from `users.py:198`). This is the destructive-action confirmation.
2. **Audit first** — write `user.deleted` (actor=self) with `ip`/`user_agent` (FR-AUDIT-01) **before** scrubbing, so the audit row's `actor_id` (`SET NULL` on real purge, kept here) is written while the row is still identifiable in-transaction.
3. **Scrub PII on the `users` row:** `email = f"deleted-{user.id}@lumen.invalid"`, `full_name = ""` (the rendered display name comes from a constant — see D5), `avatar_url = None`, `bio = None`, `password_hash = hash_password("!disabled!" + user.id)` (unusable; DUMMY-hash-equivalent), `email_verified_at = None`. Set a new `deleted_at` column on `users` (D-model) = `now(UTC)` to mark the tombstone explicitly (distinct from `is_active=False`, which suspension also uses).
4. **Deactivate:** `is_active = False` → next request 401s via `deps.py:49`; login/refresh blocked via `auth.py:80,174`.
5. **Purge sessions:** `users_repo.revoke_all_refresh_tokens(db, user.id)` then hard-delete them (`DELETE FROM auth_refresh_tokens WHERE user_id=…`) — revocation alone leaves hashed rows; deletion removes the residue. (Behavior superset of current `users.py:215`.)
6. **Purge BYOK credentials (FR-BYOK-18, D-58):** hard-delete `user_llm_credentials WHERE user_id=…` so no `enc_key`/`enc_data_key` ciphertext survives. This is a **hard delete of key material**, not the soft-delete used by `DELETE /me/llm-credentials/{provider}` — account deletion is terminal. `llm_calls` rows (no key, plain-string `user_id`) are kept. Guarded by `try/except` + import-tolerance so this is a no-op before ADR-0029 BYOK lands (charter decision 8 / NFR-MIG-3 "tolerant of a missing column/table during rollout").
7. **Revoke MCP clients:** set `mcp_clients.revoked_at = now()` for the user's clients (kills programmatic access immediately).
8. **Owned courses:** for every live course where `owner_id = user.id AND deleted_at IS NULL`: set `visibility = private` + `moderation_state` unchanged-but-delisted (so `is_publicly_listed` → false; **delist, do not reset moderation_state** per R-C2 sticky rule), then `deleted_at = now()` (soft-delete). Existing clones are **unaffected** (FR-DEL-01); other users' enrollments/certs on those courses are **preserved** (FR-DEL-02). Tolerant of missing `visibility`/`moderation_state` columns pre-ADR-0028 (falls back to soft-delete only).
9. **Anonymize provenance snapshots (R-M13/FR-DEL-01):** `UPDATE courses SET origin_owner_name_snapshot = '\x00deleted_user' WHERE origin_owner_id = user.id` — a sentinel that the API layer renders as the localized "a deleted user" (D5). `origin_owner_id` stays pointing at the tombstone row (the FK is `SET NULL`-on-hard-delete per FR-CLONE-09, but we don't hard-delete, so it remains a valid pointer; `origin_available` is computed from the *course's* listability, not the owner's liveness). Lineage survives; PII erased. Tolerant of missing provenance columns pre-ADR-0028.
10. **Scrub authored discussion content:** soft-delete the user's `discussions`/`discussion_replies` (`deleted_at = now()`) so their authored Q&A text isn't served. `author_id` is already nullable `SET NULL` (`discussion.py:43,68`); we leave it pointing at the tombstone (consistent with anonymize-in-place) but hide the body.
11. **Soft-delete authored reviews:** `reviews.deleted_at = now()` for `author_id = user.id`.

Steps 6–11 are each independently `try`-guarded so an unrelated missing sibling table never blocks the core deletion (PII scrub + deactivate + sessions), matching the best-effort swallow-broker-errors pattern (CLAUDE.md gotchas; NFR-OBS-3).

### D3 — Suspension shares `is_active`, stays reversible (FR-SUSP-01/02, R-CAP)
Suspension (`PATCH /admin/users/{id}/suspend`, admin scope, designed in the role/admin ADRs) sets `is_active=False` + `revoke_all_refresh_tokens` but **does not scrub PII and does not set `users.deleted_at`**. The single discriminator between "suspended" and "deleted" is `deleted_at IS NULL` on the `users` row. Reinstate (`PATCH …/reinstate`) sets `is_active=True` and is **refused if `deleted_at IS NOT NULL`** (`422 user.deleted_irreversible`) — a tombstoned account can never be reactivated through the suspension surface (legal erasure / restoration is offline-admin only). Auth surfaces a distinct code: suspended (`is_active=False AND deleted_at IS NULL`) → `auth.account_suspended`; deleted (`deleted_at IS NOT NULL`) → `auth.account_deleted`. Both are returned by `authenticate`/`rotate_refresh` instead of the generic `auth.inactive`/`auth.invalid_credentials`.

### D4 — Cooperative cancellation (R-S10)
A shared helper `app/services/account.py::assert_account_active(db, user_id)` re-loads `is_active` and raises `ForbiddenError(code="account.access_revoked")`. Wired at:
- **Streaming tutor heartbeat** (`workers/tasks/tutor_streaming.py` near the cancellation comment at `:86`): on each heartbeat tick, check `is_active`; on loss, stop emitting and close the stream (`course.access_revoked`-style 403 → SSE close).
- **Build / clone job phase boundaries:** the authoring orchestrator and clone service check at each phase fence; on loss they abort the phase and roll back (no partial course persists). This complements (does not replace) the 15-min access-token TTL bound (NFR-SEC-11).

### D5 — Rendered display name for tombstones
Anonymized display name is **not** stored on the row (we store `full_name=""` + the `\x00deleted_user` snapshot sentinel). Rendering is at the API/serializer edge: any DTO that would surface `full_name`/author name for a row with `users.deleted_at IS NOT NULL` (or a provenance snapshot equal to the sentinel) emits the i18n key `common.deletedUser` → "a deleted user" / "مستخدم محذوف". This keeps the anonymized label localizable and single-sourced.

## Data model changes

### New / changed columns
1. **`users.deleted_at`** — `DateTime(timezone=True)`, **nullable**, no default. The tombstone marker that distinguishes deletion (set) from suspension (null) while both share `is_active=False`. Indexed via partial index for the admin "deleted accounts" view.
2. **ORM-only (no DDL):** `User.courses_owned`, `User.enrollments`, `User.reviews` cascade `all, delete-orphan` → `save-update` (`user.py:58,61,64`). No migration needed (relationship cascade is Python-side); ship in the same release as the model change so the latent bug can never fire.

### Constraints / indexes
- `ix_users_deleted_at` — partial index `WHERE deleted_at IS NOT NULL` (small, supports the admin tombstone list without bloating the hot path).
- No new CHECK constraint coupling `deleted_at`/`is_active` (mirrors R-C2's "enforce in service + tests, not DB CHECK"): a tombstone implies `is_active=False`, but we enforce that invariant in `delete_account` + a regression test, not a DB constraint that would manufacture migration friction.

### Numbered Alembic migrations (>=0030), explicit ordering, zero-downtime
This ADR owns exactly **one** migration; it is purely additive and orders **before** the BYOK (ADR-0029) and clone (ADR-0028) migrations because those add the tables/columns that `delete_account`'s try-guarded steps will later touch — but it must not depend on them.

- **0030 — `account_lifecycle_users_deleted_at`** (this ADR).
  - `op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))` — additive, nullable, no backfill, instant on Postgres 17 (metadata-only; no table rewrite, no default).
  - `op.create_index("ix_users_deleted_at", "users", ["deleted_at"], postgresql_where=sa.text("deleted_at IS NOT NULL"), postgresql_concurrently=True)` — built `CONCURRENTLY` so it never takes an `ACCESS EXCLUSIVE` lock against the **live prod `users` table** while the fleet serves traffic. (Requires the migration to run outside a transaction block — `op.get_context().autocommit_block()` or a dedicated `with op.get_context().autocommit_block():` per the Alembic concurrent-index pattern.)
  - `downgrade()`: drop the index (concurrently) then drop the column. **Reversible** (additive schema, unlike the irreversible role data-collapse of R-C4). No data is destroyed on downgrade because `deleted_at` is metadata about a state, not the PII scrub itself (the scrub lives in already-deployed columns).

**Ordering / zero-downtime against the running fleet (charter decision 8, NFR-MIG-3):**
1. Deploy **0030** + the model with `deleted_at` mapped and the cascade fix. Old pods don't know the column but never write it; new pods can. No reader keys on it. No window of inconsistency: the column is null everywhere until a new-pod deletion sets it. The `is_active` re-check (`deps.py:49`) already exists, so a tombstoned user is blocked on every pod regardless of version.
2. The `delete_account` service ships in the same image; its sibling-table steps (BYOK purge, provenance anonymize, visibility delist) are try-guarded and become live automatically once ADR-0028/0029 migrations land — no separate re-deploy of the deletion path needed.
3. No backfill: existing `deleted-*@lumen.invalid` rows created by the **old** `delete_me` (`users.py:210`) have `is_active=False` but `deleted_at IS NULL` — i.e. they read as "suspended" under the new discriminator. A **one-shot data migration step inside 0030** backfills `UPDATE users SET deleted_at = updated_at WHERE email LIKE 'deleted-%@lumen.invalid' AND is_active = false` so historically-deleted accounts correctly read as tombstones, not as reinstateable suspensions. This runs in the same migration after the column add; it touches only already-anonymized rows and is idempotent.

## API changes

### Endpoints
- **`DELETE /api/v1/me`** — *behavior change, same signature.* Request body `DeleteAccountRequest { password: str }` (unchanged, `users.py:38-39`). Now delegates to `account_service.delete_account(...)`. Response `200 OkResponse` (unchanged). The endpoint clears the auth cookies in the response (`Set-Cookie` expiring `__Host-access`/`__Host-refresh`) so the browser is signed out immediately, not just on next request.
- **No new self-serve endpoint** is introduced (R-M3′: deletion is the existing surface, hardened). Suspend/reinstate are admin endpoints owned by the role/admin ADR; this ADR only specifies their shared `is_active`/`deleted_at` discriminator and the auth error codes.

### Pydantic schemas
- `DeleteAccountRequest` — unchanged (`users.py:38`).
- `UserOut` (read DTO, `schemas/user.py`) — add a computed/serializer rule: when the underlying row has `deleted_at IS NOT NULL`, `full_name` serializes as the localized deleted-user label at the edge (or the raw `""` + frontend resolves via `common.deletedUser`); `email` is never exposed for a tombstone beyond the masked `deleted-*@lumen.invalid`.
- Any author-bearing DTO (`ReviewOut`, `DiscussionOut`, course-provenance "Based on …") resolves a tombstoned author/`\x00deleted_user` snapshot to `common.deletedUser`.

### Error codes (new + reused)
- `auth.account_deleted` — **new.** Login/refresh on a tombstoned account (`deleted_at IS NOT NULL`). Distinct from `auth.account_suspended` (FR-SUSP-04) and `auth.account_locked` (`locked_until`).
- `auth.account_suspended` — **new** (shared with FR-SUSP-04; this ADR pins it as the value `authenticate`/`rotate_refresh` return for `is_active=False AND deleted_at IS NULL`, replacing the generic `auth.inactive` at `auth.py:175`).
- `user.deleted_irreversible` — **new**, `422`. Returned by admin reinstate when target `deleted_at IS NOT NULL`.
- `account.access_revoked` — **new**, `403`. Cooperative-cancellation signal (D4) for in-flight streaming/build/clone when `is_active` flips.
- `auth.invalid_credentials` — reused for the password re-check (`users.py:199`).

All errors use the `{error:{code,message,details,request_id}}` envelope via `AppError` subclasses (CLAUDE.md; `app.core.errors`).

## Service / worker changes

### Existing functions that change
- **`app/api/v1/users.py::delete_me`** (`users.py:194-216`) — slimmed to: re-check password, call `account_service.delete_account(db, user=user, ip=client_ip(request), user_agent=user_agent(request))`, clear cookies, return `OkResponse`.
- **`app/services/auth.py::authenticate`** (`auth.py:72-99`) — branch on `not user.is_active`: emit `auth.account_deleted` if `user.deleted_at` else `auth.account_suspended` (still run the dummy-hash timing-flatten at `auth.py:85` for the no-such-user case only).
- **`app/services/auth.py::rotate_refresh`** (`auth.py:170-179`) — replace `auth.inactive` (`auth.py:175`) with the deleted/suspended split.
- **`app/models/user.py`** (`user.py:58,61,64`) — cascade fix on `courses_owned`/`enrollments`/`reviews`.
- **`app/repositories/users.py`** — add `purge_refresh_tokens(db, user_id)` (hard delete after revoke) and `mark_deleted(db, user)` helpers; reuse `revoke_all_refresh_tokens` (`users.py:84`).

### New
- **`app/services/account.py`** — `delete_account(...)` (the D2 choreography), `assert_account_active(...)` (D4 helper). This is the single place the deletion invariants live (CLAUDE.md service-layer rule).
- **`app/models/__init__.py`** — no new model export (only a column on existing `User`).

### Worker / dispatch
- **`app/workers/tasks/tutor_streaming.py`** (heartbeat near `:86`) — call `assert_account_active`; on revoke, close the SSE stream.
- Authoring orchestrator (`app/services/authoring_orchestrator.py`) and the (net-new, ADR-0028) clone service — `assert_account_active` at phase fences.
- **Authorizer/capability:** no per-user capability storage (R-CAP). The capability layer (role/capability ADR) treats `is_active=False` (suspended **or** deleted) as failing **every** `can_*` check via the existing `is_active` gate (`deps.py:49`), so a tombstoned/suspended user is uniformly denied author/clone/publish/BYOK without per-capability code.

## Frontend changes

### App Router routes / components
- **`src/app/profile/page.tsx`** — the "Delete account" section already exists (i18n keys `profile.section.delete`, `profile.delete.*`, `profile.toast.deleted*` at `messages/en.ts:682-694`). Wire the existing password-confirm delete control to `DELETE /api/v1/me`; on success, clear TanStack `me` cache, hard-redirect to `/` (signed out). Update copy from "permanently deactivates" to reflect anonymize-in-place: data is anonymized and owned courses are removed from the public catalog.
- **`src/app/profile/layout.tsx`** — unchanged.
- A new shared helper/component `DeletedUserName` (or an inline fallback) renders `common.deletedUser` wherever an author/owner display name is null/tombstoned — used by review lists, discussion threads, and the clone "Based on …" provenance line (ADR-0028 surface).

### TanStack query keys (`src/lib/query/keys.ts`)
- Reuse `me: ["me"]` (`keys.ts:2`). On successful delete: `queryClient.clear()` (full reset — the session is gone). No new key needed; deletion invalidates `me`, `enrollments` (`keys.ts:8`), `myCourses` (`keys.ts:9`), `notifications` (`keys.ts:10`).

### i18n keys (add to BOTH `messages/en.ts` and `messages/ar.ts`; FR-I18N-01, parity test)
| Key | en | ar |
|---|---|---|
| `common.deletedUser` | "a deleted user" | "مستخدم محذوف" |
| `profile.section.deleteDesc` (revise existing `:683`) | "This anonymizes your account, removes your public courses from the catalog, and deletes your saved API keys. It can't be undone." | "يؤدي هذا إلى إخفاء هوية حسابك وإزالة دوراتك العامة من الكتالوج وحذف مفاتيح الـ API المحفوظة. لا يمكن التراجع عن ذلك." |
| `profile.delete.warning` | "Existing copies others made of your courses will remain available." | "ستظل النسخ التي أنشأها الآخرون من دوراتك متاحة." |
| `auth.error.accountSuspended` | "Your account has been suspended." | "تم تعليق حسابك." |
| `auth.error.accountDeleted` | "This account has been deleted." | "تم حذف هذا الحساب." |

Existing reused keys: `profile.delete.button` (`:684`), `profile.delete.confirmPlaceholder` (`:685`), `profile.delete.confirm` (`:686`), `profile.toast.deleted` (`:693`), `profile.toast.deleteError` (`:694`). All net-new surfaces meet WCAG 2.2 AA (FR-A11Y-05): the destructive delete confirmation is keyboard-reachable, focus-trapped, `useReturnFocus`'d (ADR-0022), with the password input error programmatically associated.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **Physical row delete + make `owner_id` `SET NULL`** | Would orphan public courses from their author (breaks `RESTRICT` intent at `course.py:103`, breaks provenance, and cascades into other users' enrollments/reviews on those courses). Contradicts FR-DEL-02's explicit "RESTRICT preserved." |
| **Keep `cascade="all, delete-orphan"` and make `owner_id` `CASCADE`** | A self-delete would silently destroy the user's courses *and* every enrolled learner's progress/certs/discussions on them — catastrophic and contradicts FR-DEL-03 (a learner's clone progress must survive origin deletion). |
| **Physical delete after transferring ownership to a system user** | Requires a privileged "orphaned content" account, complicates moderation/audit (a system user "owns" abandoned courses), and provenance snapshots still need anonymizing — strictly more moving parts than anonymize-in-place for zero added benefit. Deferred to the offline legal-erasure procedure if ever needed. |
| **Hard-delete the `users` row but keep a separate `deleted_users` tombstone table** | Doubles the storage of the FK problem: every `SET NULL`/`RESTRICT` FK still has to be reconciled, and joins for "who authored this" now span two tables. Anonymize-in-place keeps one row and all joins valid. |
| **DB CHECK constraint `is_active=false WHERE deleted_at IS NOT NULL`** | Manufactures migration friction on the live table and duplicates a service invariant; rejected for the same reason R-C2 dropped the moderation CHECK. |
| **Soft-delete owned courses but leave them `public`** | A delisted-but-public course would still satisfy a stale `status==published` reader during the rebuild rollout (R-S8′). We force `visibility=private` + soft-delete so `is_publicly_listed` is unambiguously false. |
| **Reset `moderation_state` to `none` on owner deletion** | Violates R-C2 (moderation_state is sticky, never reset); would erase the moderation history of a course that was once public. We delist via `visibility`/soft-delete only. |

## Consequences

**Positive**
- The verified ORM-vs-DB contradiction is eliminated: no code path can silently orphan-delete a user's courses; `RESTRICT` is a true backstop.
- Deletion is coherent with the whole rebuild: provenance lineage survives (FR-DEL-01), other users' clones/enrollments/certs survive (FR-DEL-02/03), cost/audit history survives (D-58, FR-AUDIT-03), PII is irreversibly scrubbed (R-M3′/R-M13).
- Suspension and deletion share one mechanism (`is_active`) yet are cleanly distinguished by `deleted_at`, with distinct stable auth codes (FR-SUSP-04).
- The migration is purely additive, concurrently-indexed, reversible, and safe against the live prod DB + a mixed-version fleet.
- The deletion service is forward-compatible: BYOK/clone/visibility steps are try-guarded no-ops until their sibling ADRs land, then activate without redeploying the deletion path.

**Negative / costs**
- `users` grows monotonically (tombstones never physically removed) — acceptable at this scale; the offline legal-erasure procedure handles true purge if storage or compliance ever demands it.
- Anonymized rows still satisfy unique constraints (`email` CITEXT unique) via the `deleted-{id}@lumen.invalid` tombstone — a freed email is **not** reusable for re-registration unless the offline purge runs. This is intentional (re-registration with a deleted account's email could resurrect dangling references) and documented.
- Every author-bearing DTO must handle the tombstone label, adding a small rendering branch in several serializers.
- The historical-data backfill in 0030 reclassifies old `deleted-*` accounts as tombstones; an operator must be aware those rows are now non-reinstateable.

## Requirements satisfied

R-M3′ (anonymize-in-place self-serve deletion), R-M13/R-M13′ (provenance name-snapshot anonymization), R-S1″ adjacency (no key material survives — feeds FR-BYOK-18), R-CAP (per-user revocation = suspension only; no capability-override storage), R-S10 (cooperative cancellation on streaming + build/clone), R-C2 (moderation_state stays sticky on owner-deletion delist). Spec FRs: **FR-DEL-01, FR-DEL-02, FR-DEL-03** (independent lesson ids preserved by anonymize-in-place + cascade fix), **FR-BYOK-18** (account deletion purges key material; `llm_calls` retained), **FR-SUSP-01/02/04** (shared `is_active`, distinct codes), **FR-AUDIT-01/03** (`user.deleted` audit, append-only, no secrets), **FR-ANON-01** (anonymous/role behavior unchanged), **NFR-MIG-3** (additive, nullable, reversible, rollout-tolerant), **NFR-SEC-11** (suspension revokes refresh + 15-min TTL bound), **NFR-REL-3** (clone progress survives origin deletion), **FR-I18N-01 / FR-A11Y-05** (deletion + suspended/deleted surfaces localized + AA). Charter decisions **8** (phased zero-downtime) and **10** (deletion semantics). Mandatory W2 ADR #6 (account lifecycle).

## Open risks

1. **Cross-ADR sequencing.** `delete_account`'s BYOK/provenance/visibility steps reference columns/tables owned by ADR-0028 (clone) and ADR-0029 (BYOK). If those land *after* this ADR's build, the try-guards must be proven no-ops by tests (mock missing table → deletion still scrubs core PII). Risk: a guard too broad swallows a real error and leaves un-scrubbed data. Mitigation: guards catch only `ProgrammingError`/`UndefinedTable`/`ImportError`, never blanket `Exception`, around the optional steps; the core PII scrub + deactivate is **un-guarded** and must succeed or the transaction rolls back.
2. **Tombstone email reuse policy.** Keeping `deleted-*@lumen.invalid` blocks re-registration with the original address. If product later wants re-registration, the offline purge must free the email — needs a documented operator runbook.
3. **Cooperative-cancellation completeness.** R-S10 requires checks at *every* in-flight LLM phase boundary. New foreground features (learning-path build/replan per R-S1″) must each adopt `assert_account_active` or a suspended user's in-flight job runs to completion (bounded only by the 15-min token TTL). Risk of omission as features are added; mitigate with a checklist in the build plan + a test that suspends mid-stream and asserts `account.access_revoked`.
4. **Backfill correctness.** The 0030 data step keys on `email LIKE 'deleted-%@lumen.invalid'`. If any *real* user ever had that literal email (impossible via signup — `.invalid` can't receive mail and the pattern is reserved by the old `delete_me`), it would be mis-tombstoned. Verified the only writer of that pattern is `users.py:210`; low risk, but the migration logs the affected row count for operator review.
5. **`updated_at` as deletion timestamp in backfill.** Using `updated_at` as the historical `deleted_at` is approximate (a profile edit could have touched it post-deletion). Acceptable because these are already-anonymized rows where the exact deletion instant has no downstream consumer; flagged so no one later treats backfilled `deleted_at` as forensically precise.