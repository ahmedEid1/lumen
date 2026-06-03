# ADR 0025: Role collapse to `{user, admin}` with capability-based authorization

## Status — Proposed

W2 design artifact for the two-role rebuild (charter §3 decision 1; mandatory ADR #1 per `REQUIREMENTS-RESOLUTIONS.md` §"Mandatory W2 design ADRs"). Supersedes the role-half of the original three-role RBAC design. Cross-references ADR-0008 (soft-delete) and the W2 visibility/BYOK/clone/account-lifecycle ADRs (0026–0029, drafted in parallel). On any conflict with the requirements spec, `REQUIREMENTS-RESOLUTIONS.md` (R1+R2+R3) governs and is reflected here.

---

## Context (forces + current code reality)

**Goal (charter §1):** collapse `student | instructor | admin` to a learner-owned `user | admin` model where every `user` can author, learn, publish, and clone — but do this **capability-first, not role-blunt**. Gate A (Codex) rejected a global `RequireInstructor → any-user` swap as unsound because three "instructor" gates protect genuinely dangerous powers (URL ingest = SSRF, public publish = catalog pollution, MCP authoring = programmatic write amplification) that must keep their own guards.

**Current code reality (verified against source):**

- `Role(StrEnum)` = `student | instructor | admin` at `apps/backend/app/models/user.py:19-22`. The DB column is `role: Mapped[Role] = mapped_column(String(20), nullable=False, default=Role.student, index=True)` at `:36` — **a plain `String(20)`, not a native Postgres `ENUM`** (confirmed: only migration `0001_initial.py` defines it). This is load-bearing: collapsing the enum is an **app-enum + data UPDATE**, with **no `ALTER TYPE`** and no Postgres enum-value drop. FR-RBAC-01.
- `User.is_instructor_or_admin()` at `user.py:67-68`; `User.is_admin()` at `:70-71`.
- `require_role(*roles)` at `deps.py:66-72` — admin always passes via `not user.is_admin()` short-circuit at `:68`. Aliases `RequireInstructor = require_role(Role.instructor, Role.admin)` at `:75`, `RequireAdmin = require_role(Role.admin)` at `:76`.
- **`RequireInstructor` decorator applications (verified count = 24):** `api/v1/courses.py` (16 — every author/owner write: create, my_courses, update, delete, module/lesson CRUD, reorder, course-analytics at `:344`), `api/v1/ai_authoring.py` (5 — `:170/194/219/249/310`, covering `/ai/outline`, `/ai/lesson-body`, `/ai/quiz`, `/ai/draft-course` at the handler awaiting `draft_course` at `ai_authoring.py:328` **in-request, no `.delay()`**, and `/ai/draft-traces`), `api/v1/content_ingest.py` (3 — `:65/80/102`). The charter's "26 sites" counts a couple of nested/aliased uses; the authoritative gate inventory is these three modules. FR-RBAC-02.
- `create_course` business gate: `if not owner.is_instructor_or_admin(): raise ForbiddenError(..., code="courses.forbidden")` at `services/courses.py:69`. FR-RBAC-04.
- **JWT `role` claim is inert for authz.** It is minted at `core/security.py:53` (`create_access_token` writes `"role": role`) and `auth.py:195` (`create_access_token(subject=user.id, role=str(user.role))`). It is **never read for authorization**: `get_current_user_optional` (`deps.py:48`) loads the live `User` by `sub` and `require_role` (`deps.py:68`) reads `user.role` from that fresh DB row. `decode_token` (`security.py:64-68`) does not validate or constrain `role`. So a stale `role='instructor'` token grants nothing once the DB row is `user`. FR-MIG-04.
- **MCP parallel RBAC** (separate from REST `deps.py`): `Principal.is_instructor` at `mcp/principal.py:96-97` (`self.role in (Role.instructor, Role.admin)`); `_enforce_auth` at `mcp/server.py:109-115` raises `mcp.role.instructor_required` for `auth=="instructor"` tools; `tools.py:_require_instructor` at `:571-577` raises `mcp.writes.instructor_required`. **Two** ToolSpecs carry `auth="instructor"`: `create_course_draft` (`tools.py:~881`) and `ingest_url_to_draft` (`tools.py:~890`). (Note: the spec's "`create_course_outline`" name is stale — the actual tool is `create_course_draft`.) `Principal.role` is populated from the live `User.role` in `_principal_from_client_row` (`principal.py`), and `resolve_from_jwt` carries `lumen-mcp` issuer tokens that **do not carry a role claim** — role is re-read from the DB user row.
- Role assignment/default sites: `services/auth.py:58` (signup `role=Role.student`), `repositories/users.py:26` (`role: Role = Role.student` default), `cli.py:94/104/163`, `seeds/demo.py:544/552`, `evals/run_baseline.py:159`. FR-RBAC-06, FR-EVAL-03.
- Admin role surface: `api/v1/admin.py:194-211` (`set_user_role`, audit `admin.user.role`); `platform_stats` at `:402` counts instructors via `User.role.in_([Role.instructor, Role.admin])` at `:411`. `notifications.py:60` selects admins (`User.role == Role.admin`) — unaffected. FR-RBAC, FR-ADMIN-07.
- Frontend: `Role = "student" | "instructor" | "admin"` at `apps/frontend/src/lib/api/types.ts:3`; i18n catalogs at `apps/frontend/src/lib/i18n/messages/{en,ar}.ts`. FR-RBAC-09, FR-I18N-01.
- Latest migration is `0029`; new migrations start at **`0030`** per R-G10/charter. Live prod DB on AWS with a running fleet (single-host docker-compose, so API + worker co-located).

**Tension to resolve:** the role enum collapse cannot be atomic against a live fleet holding 15-min access tokens and un-backfilled rows. Old readers must not crash on `user`; new readers must not crash on `student`/`instructor`. The accept-set, the enum membership, and the JWT-claim policy must be staged. R-C4 (irreversible data collapse), R-C5/R-C5′ (wide→narrow+normalize→remove with positive-evidence exit) govern the staging.

---

## Decision

### D1 — Final role model: `Role = {user, admin}`

`Role(StrEnum)` ends as exactly `user="user"`, `admin="admin"` (FR-RBAC-01). The `role` column stays `String(20)` (no PG type to migrate). `student`/`instructor` are removed from the enum **only in Release 3**, after positive-evidence drain (R-C5′). `User.is_admin()` is retained unchanged; `User.is_instructor_or_admin()` is **removed** in Release 3 (not aliased-to-True), with all call sites rewritten by semantic (FR-RBAC-05).

### D2 — Authorization is capability-based, in the service layer

Introduce a new module `app/services/capabilities.py` exposing **pure functions over the loaded `User` + global `Settings`** (no permission table — R-CAP defers `user_capability_overrides`):

```python
# app/services/capabilities.py
from app.core.config import Settings
from app.models.user import User

def _active(u: User) -> bool:
    return u.is_active  # suspension is the ONLY per-user revocation (R-CAP)

# Default-granted to every active user (and admin):
def can_author(u: User) -> bool:            return _active(u)
def can_clone(u: User) -> bool:             return _active(u)

# Guarded — own checks/quotas, NOT auto-opened by the collapse:
def can_publish_public(u: User) -> bool:    return _active(u)                 # + quota at call site
def can_view_course_analytics(u: User, course) -> bool:                       # owner-or-admin
    return _active(u) and (u.is_admin() or course.owner_id == u.id)
def can_use_mcp_authoring(u: User, s: Settings) -> bool:
    return _active(u) and s.mcp_authoring_enabled                              # global flag, default ON
def can_ingest_url(u: User, s: Settings) -> bool:
    return _active(u) and s.ingest_url_enabled and u.is_admin()               # CLOSED until SSRF ADR
```

Rules that make this unambiguous and final:

1. **`admin` always passes** every capability (each function treats `u.is_admin()` as a pass for guarded ones, and admins are active). The `is_admin()` short-circuit in `require_role` (`deps.py:68`) is preserved (FR-RBAC-03).
2. **Suspension = `is_active=False` is the single per-user revocation axis** (R-CAP, R-S10). There is **no** per-user `can_use_byok` storage or revocation: FR-BYOK-22's per-user revoke and the `byok.capability_*` audit names are **dropped** per R-CAP / R3 cleanup sweep. BYOK reachability is governed by suspension + the global allowlist (deferred to ADR-0028). When the spec says "default-granted `can_use_byok`," read it as "available to every active user; revoked only by suspension."
3. **`can_ingest_url` is a global admin-config flag (`Settings.ingest_url_enabled`, default `False`) AND admin-only** until the SSRF-hardening ADR lands (R-M12, FR-SEC-02, charter decision 7). It is **not** per-user and **not** auto-opened by S1. The route decorator itself resolves admin-only/flag-off (see D5).
4. **`can_use_mcp_authoring` is a global flag (`Settings.mcp_authoring_enabled`, default `True`)** applied to all active users — it replaces the `is_instructor` MCP gate so authoring neither silently opens to nobody nor breaks for former instructors (FR-RBAC-08, FR-ADMIN-06).
5. Capabilities live in the **service layer**, not just routes — every author/owner/admin service entry re-checks. The deps in D5 are convenience guards over the same predicates.

### D3 — `deps.py` capability dependencies

Add to `app/api/deps.py`:

```python
from app.services import capabilities as cap

async def _require_author(user: CurrentUser) -> User:
    if not cap.can_author(user):
        raise ForbiddenError("Author capability required", code="auth.capability",
                             details={"capability": "can_author"})
    return user
RequireAuthor = Annotated[User, Depends(_require_author)]
```

- **`RequireAuthor`** = any authenticated **active** user (since `can_author` is default-granted). It replaces `RequireInstructor` on the **24 author/owner routes** in `courses.py`, `ai_authoring.py`. Owner-vs-admin write authority is **unchanged** — it stays in the service layer (`_owned_course` at `services/courses.py:97/130`, generalized to `_can_edit_course(user, course)` per FR-RBAC-03/05), so collapsing the route gate does not let user A edit user B's course.
- **`RequireAdmin`** is unchanged (FR-ADMIN-07): all `admin_*.py` modules keep it.
- **`content_ingest.py`** routes (`:65/80/102`) do **not** move to `RequireAuthor`. They move to a dedicated `RequireIngestUrl` dep that resolves `cap.can_ingest_url(user, settings)` → admin-only + flag-off by default (R-M12). The route-decorator swap is part of S1; the SSRF hardening that opens the flag is a later stream.
- `require_role` stays for admin-only routes (FR-RBAC-03). The error envelope for capability denial is the standard `{error:{code,message,details,request_id}}` with `code="auth.capability"` and `details.capability=<name>` (per-CLAUDE.md envelope). `courses.forbidden` (the old `create_course` 403) becomes **unreachable and is removed** (FR-RBAC-04).

### D4 — `create_course` ungated

`services/courses.py:68-70` drops the `is_instructor_or_admin()` precondition entirely; any authenticated active user creates courses. Subject + unique-slug logic unchanged (FR-RBAC-04). Authoring orchestrator entry (`ai_authoring.py:328 draft_course`) inherits `RequireAuthor` + a service-layer `cap.can_author(user)` re-check, and rejects anonymous with **401** and suspended with **403** (FR-DEFINE-06).

### D5 — MCP RBAC reconciliation (same change set, FR-RBAC-07/08)

- Add `Principal.can_author` (property: `self.user is not None and self.user.is_active`) and `Principal.can_use_mcp_authoring` / `can_ingest_url` mirroring `capabilities.py` over `self.user` + settings. **Remove reliance on `Principal.is_instructor`** for write gating; keep `is_instructor` as a deprecated property during R1–R2 only so the `auth=="instructor"` branch still resolves **legacy `instructor` principals** without rejecting `user` principals (FR-RBAC-07).
- `mcp/server.py:_enforce_auth`: the `auth=="instructor"` branch (`:109`) is **redefined as a capability check** — for `create_course_draft` it requires `principal.can_author` (True for `user`+`admin`); the denial code becomes **`mcp.writes.author_required`**. The `ToolSpec` `auth` field for `create_course_draft` changes `"instructor" → "user"` (so `_enforce_auth` falls into the `auth=="user"` branch which already permits any authenticated principal, then the service re-checks `can_author`).
- `tools.py:_require_instructor` (`:571-577`) is renamed `_require_author` and checks `principal.can_author`; error code `mcp.writes.author_required`.
- `ingest_url_to_draft` ToolSpec **keeps a stricter posture**: `auth` stays a guarded form (kept as `"admin"` until the SSRF ADR introduces a finer MCP capability posture), and its handler additionally requires `can_use_mcp_authoring AND can_ingest_url` — i.e. admin-only/flag-off until hardening (R-M12). It is **not** opened by S1.
- During **Phase A**, the `auth=="instructor"` branch MUST continue to resolve legacy principals (a still-`instructor` DB user) and MUST NOT reject `user` principals on authoring tools (FR-RBAC-07).

### D6 — JWT claim policy: inert, tolerant, display-only (FR-MIG-04)

- `decode_token` / the `deps.py` auth path **tolerate any of `{student, instructor, user, admin}`** in the `role` claim during phases A–C and **never raise** on an unknown/legacy claim (it already never inspects `role`; we add a normalization-on-read helper `normalize_role(raw) -> Role` that maps any legacy/unknown string → `Role.user`, used only where the claim or a straggler ORM string is materialized for **display**).
- **Authorization never trusts the claim.** `require_role` and every capability function re-read the live `user.role` from the DB per request (already true at `deps.py:48,68`). The MCP path re-reads `User.role` from the DB (`principal.py` / `resolve_from_jwt`), never a token role.
- The mint side (`auth.py:195`, `security.py:53`) keeps writing `role` for backward compatibility; from Phase C it writes the normalized `user`/`admin`.

### D7 — Phased, zero-downtime, irreversible-data migration (R-C4, R-C5/C5′, FR-MIG-01)

Three Alembic **Releases** (additive-then-data-then-narrow), each shipped as a deploy, gated by token drain and positive evidence between Release 2 and Release 3.

---

## Data model changes

No new tables and **no new columns** for the role collapse (this is the deliberately small seam — visibility/moderation/BYOK tables belong to ADRs 0026/0028). The only schema touch is the `users.role` `server_default` and the eventual app-enum narrowing. The `role` column stays `String(20)`.

Note the **ORM cascade fix from R-M3′/R-M13′** belongs to the account-lifecycle ADR (0029) but is recorded here as a cross-cutting dependency: `User.courses_owned` cascade `all, delete-orphan` (`models/user.py:58`) → `save-update` to reconcile with `Course.owner_id ondelete="RESTRICT"` (`course.py:103`). **This ADR does not own that change.**

### Migrations (numbered, ordered, zero-downtime against the LIVE prod DB + running fleet)

**Migration 0030 — `role_collapse_backfill` (Release 1 → Release 2 data step).**
Forward-only, idempotent, single transaction:

```python
def upgrade():
    op.execute("UPDATE users SET role='user' WHERE role IN ('student','instructor')")
    # logged changed-row count via op.get_bind().execute(...).rowcount
def downgrade():
    pass  # R-C4: IRREVERSIBLE. Cannot recover student vs instructor. No-op by design.
```

The `downgrade()` is a **documented no-op** (R-C4) — rollback is image rollback to a pre-Release-2 build, never a down-migration that re-writes `student`. `admin` rows are untouched.

**Migration 0031 — `role_default_user` (Release 2 schema step).**
Changes the column `server_default` only (additive, reversible):

```python
def upgrade():
    op.alter_column("users", "role", server_default="user")
def downgrade():
    op.alter_column("users", "role", server_default="student")
```

This migration **does not** drop enum members at the DB level (there are none — `String(20)`), so old pods that still expect to read `student`/`instructor` strings keep working; the app-enum narrowing is a code change (Release 3), not a DB change.

**Ordering & zero-downtime sequencing (against the live fleet):**

| Phase | Deploy | Migration | App-enum accept-set | Default | Notes |
|---|---|---|---|---|---|
| **A (Release 1)** | code that **accepts `{student, instructor, user, admin}`** at every deserialization boundary (Pydantic `Role` on `UserPublic/UserOut/UserAdminOut/UserRoleUpdate`, JWT `role` decode via `normalize_role`, MCP `Principal.role`); new signups still write `user` is **not yet** forced — defaults stay `student` until Phase C | none | `student` | wide enum genuinely live; no row/token can crash serialization (FR-MIG-01) |
| **B** | (no new code) run **0030** backfill `student/instructor → user` | `{student,instructor,user,admin}` | `student` | forward-only, single txn, logged count |
| **C (Release 2)** | run **0031** (`server_default='user'`); deploy code: all defaults → `user` (`auth.py:58`, `repositories/users.py:26`, `cli.py`, `seeds/demo.py`, `evals/run_baseline.py:159`); admin counts & frontend role union & i18n updated; **enum narrowed to `{user, admin}` PLUS a normalization layer** that maps any legacy string → `user` at every boundary (request bodies via Pydantic `field_validator`, JWT claim, straggler ORM rows via a load-normalization hook) | `{user,admin}` + normalize-legacy | `user` | enum is narrow but tolerant (R-C5) |
| **D (Release 3)** | only after **positive evidence** (R-C5′): a query proving **zero** `role IN ('student','instructor')` rows **AND** no legacy MCP principals **AND** access-token TTL (≥15 min) elapsed since the Phase C deploy → remove the normalization layer, remove `is_instructor_or_admin()`, drop the deprecated `Principal.is_instructor`, tighten accept-set to strictly `{user, admin}` | strictly `{user,admin}` | `user` | Release-3 exit is evidence, not TTL alone (R-C5′) |

**Why no `ALTER TYPE`:** the column is `String(20)` — there is no Postgres enum object to add/remove values from, so there is no DDL lock risk on `users` beyond the metadata-only `ALTER COLUMN ... SET DEFAULT` (0031), which is fast and non-blocking on Postgres 17. The `UPDATE users` (0030) takes row locks on `users` for its duration; on the seeded-scale prod table this is sub-second, but it is run as its own deploy step with the fleet already accepting both old and new values (Phase A precondition), so no request fails mid-backfill.

**Irreversibility containment:** only 0030 is irreversible (R-C4). 0031 has a proper `downgrade`. The Release-3 code-only narrowing has no migration. Rollback playbook: image-rollback to the last Release-1/2 build (which still accepts `user`), never `alembic downgrade` past 0030.

---

## API changes

This ADR introduces **no new endpoints** (goal-intake/clone/BYOK/visibility endpoints belong to their own ADRs). It changes guards, schemas, and error codes:

**Changed guards (route decorators):**
- `courses.py` (16 routes) and `ai_authoring.py` (5 routes): `RequireInstructor` → `RequireAuthor`.
- `content_ingest.py` (3 routes, `:65/80/102`): `RequireInstructor` → `RequireIngestUrl` (admin-only + flag-off, R-M12).
- All `admin_*.py`: `RequireAdmin` unchanged.

**Changed Pydantic schemas:**
- `schemas/user.py` — `Role` field on `UserPublic`, `UserOut`, `UserAdminOut`, `UserRoleUpdate` (`schemas/user.py:20 role: Role`). During Phase A–C these accept `{student,instructor,user,admin}` (wide); a `field_validator` normalizes legacy → `user` for `UserRoleUpdate` inbound (admins cannot **set** `student`/`instructor` even in Phase A — only `user`/`admin` are settable; legacy values are read-tolerant but write-forbidden). From Phase C the schema enum is `{user, admin}`.
- `admin.py PlatformStatsOut` — the `instructors` count field is **renamed/repurposed**: keep the field name for OpenAPI stability through Phase C but change its query from `User.role.in_([instructor, admin])` to `User.role == Role.admin` for admins, plus an `authors` count = active non-admin users (`platform_stats` at `:402-411`). Final field set: `users`, `active_users`, `admins`, `authors` (replacing `instructors`), course/enrollment counts unchanged.

**Error codes:**
- New: `auth.capability` (capability denial; `details.capability=<name>`).
- Removed (unreachable): `courses.forbidden` (old non-instructor create gate).
- MCP: `mcp.writes.instructor_required` → `mcp.writes.author_required`; `mcp.role.instructor_required` retained only while the legacy `auth=="instructor"` branch exists (Phase A–C), removed in Release 3.
- 401 vs 403 contract: anonymous on author/define/clone routes → **401 `auth.required`**; authenticated-but-suspended → **403 `auth.capability`** (FR-DEFINE-06, FR-CLONE-02).

**OpenAPI/TS contract (FR-API-01/02):** the OpenAPI `Role` enum is the source of truth; regenerate `openapi.json` (`make openapi`) when the enum narrows (Phase C); the hand-written `types.ts` Role union is changed in the **same PR** as the backend enum, with a CI contract-drift check (FR-API-01).

---

## Service / worker changes

- **New module `app/services/capabilities.py`** (D2) — pure capability functions; the single home for the capability predicates. Imported by `deps.py`, `services/courses.py`, `mcp/server.py`, `mcp/tools.py`.
- **`services/courses.py`:**
  - `create_course` (`:68`) — drop the `is_instructor_or_admin()` gate (FR-RBAC-04).
  - `_owned_course` (`:97`, `:130`) — generalize/rename to `_can_edit_course(user, course)` returning the course or raising `course.forbidden`/`course.not_found`; owner-or-admin authority preserved (FR-RBAC-03/05).
  - Course-analytics route service (`courses.py:344` handler) — gate via `cap.can_view_course_analytics(user, course)` (owner-or-admin), not `RequireInstructor`.
- **`services/auth.py`** — `register` default `Role.student → Role.user` (Phase C; `:58`).
- **`repositories/users.py`** — `create()` default `role: Role = Role.user` (Phase C; `:26`).
- **`core/security.py` / `services/auth.py`** — add `normalize_role()`; `create_access_token` writes normalized role from Phase C (`security.py:53`, `auth.py:195`); the claim remains authz-inert (D6).
- **`mcp/principal.py`** — add `Principal.can_author` / `can_use_mcp_authoring` / `can_ingest_url`; keep `is_instructor` deprecated through R1–R2 (`:96-97`).
- **`mcp/server.py`** — `_enforce_auth` (`:109-122`) author-capability gate + `mcp.writes.author_required`.
- **`mcp/tools.py`** — `_require_instructor` → `_require_author` (`:571-577`); `create_course_draft` ToolSpec `auth "instructor"→"user"`; `ingest_url_to_draft` stays guarded.
- **`api/v1/admin.py`** — `platform_stats` (`:402-411`) admin/author counts; `set_user_role` (`:196`) restricts settable roles to `{user, admin}` from Phase A.
- **Workers:** no role logic. Per **R-S1″**, model-selection locus is decided by *initiation*, not execution; that classification is owned by ADR-0028 (BYOK), referenced here only so the capability layer's `can_author` re-check is the same function whether the LLM call dispatches in-API (`ai_authoring.py:328`) or in a worker (`workers/tasks/tutor_streaming.py`, `learning_path.py`). The capability check happens at **initiation** (request handler), before any `.delay()`; workers carry IDs, never re-derive capability from a token.
- **`cli.py`** (`:94/104/163`), **`seeds/demo.py`** (`:544/552`), **`evals/run_baseline.py`** (`:159`) — role defaults → `user`; `run_baseline.py` stops hard-selecting `role==student`, selects any active non-admin (`Role.user`) with a fallback to the learning-persona seed and an updated RuntimeError naming the new account (FR-EVAL-03).

---

## Frontend changes

**Types (`apps/frontend/src/lib/api/types.ts`):** `type Role = "student" | "instructor" | "admin"` (`:3`) → `type Role = "user" | "admin"` (FR-RBAC-09, FR-API-01), same PR as the backend enum narrowing.

**Routes/components — remove/invert author-gate-out-students; keep admin + owner gates** (charter §6a inventory, FR-RBAC-09):
- Invert/remove `role==="student"` author hides: `studio/page.tsx:58/70/74`, `studio/new/page.tsx:45`, `studio/draft/[courseId]/page.tsx:51/57/62/77`, `studio/draft/[courseId]/replay/page.tsx:49/57/62/77`, `dashboard/page.tsx:91`, `components/shared/command-palette.tsx:141` → authoring surfaces visible to all authenticated users.
- **Keep** all `app/admin/*` `user.role !== "admin"` redirects; `admin/users/page.tsx:37` role union `"student"|"instructor"|"admin"` → `"user"|"admin"`.
- **Keep** owner/admin gates: `learn/[slug]/page.tsx:104/167`, `courses/[slug]/discussions/[id]/page.tsx:141/256`.
- Merge onboarding step builders `lib/onboarding/steps.ts:34 learnerSteps` + `:52 instructorSteps` into one set for every `Role.user`; remove the student-only onboarding gate at `dashboard/page.tsx:91` (FR-RBAC-10).
- A "Create a course to learn" entry point belongs to `/dashboard` (S3/ADR-0027) — out of this ADR's scope but unblocked by removing the studio student-redirect here (FR-DEFINE-09).

**TanStack query keys:** no new keys for the role collapse. The role value flows through the existing `me`/session query (`lib/query/keys.ts` `auth`/`me` key); a stale `instructor` role from a cached `/me` is harmless because the UI gates are inverted to capability-by-default (authoring visible to any non-admin user). The `useCapabilities` helper (a thin client wrapper: `isAdmin`, `canAuthor = !!user`, `canPublishPublic = !!user`) is added to `lib/auth/` for the inverted gates; no server round-trip.

**a11y/e2e (FR-A11Y-02/03):** rename role-coded test names/route comments to capability-neutral ("author studio", "learner dashboard"); switch authenticated specs to a `user@lumen.test` seed (admin keeps `admin@`); a compatibility shim resolves `student@`/`teacher@` → a `user` account during transition so CI stays green; keep 3 storage states mapped to 3 personas (admin, authoring user, learning user) all backed by `{user,admin}` accounts.

**i18n keys (BOTH `lib/i18n/messages/en.ts` + `ar.ts`; FR-I18N-01, parity-tested):**

| Key | en | ar |
|---|---|---|
| `roles.user` | "User" | "مستخدم" |
| `roles.admin` | "Admin" | "مشرف" |
| `auth.capability.denied.title` | "Action not available" | "الإجراء غير متاح" |
| `auth.capability.denied.suspended` | "Your account is suspended. Contact an admin to restore access." | "حسابك موقوف. تواصل مع المشرف لاستعادة الوصول." |
| `auth.capability.denied.ingest_closed` | "URL import isn't available yet." | "استيراد الروابط غير متاح بعد." |
| `onboarding.author.cta` | "Create a course to learn" | "أنشئ دورة لتتعلّمها" |

Existing keys referencing "student"/"instructor"/"teacher" are remapped to neutral wording; the `i18n-parity.test.ts` (key-set equality, no-empty, no-key-echo, RTL render) gates the change; quality tracked via the `translation_status` field (R-U8), not asserted by test.

---

## Alternatives considered

- **Blunt role swap (`RequireInstructor → CurrentUser` everywhere).** Rejected (Gate A, charter §3.1): opens URL ingest (SSRF), public publish (catalog pollution), and MCP authoring to every user with no guard. Capability layer is mandatory.
- **`is_instructor_or_admin()` aliased to `True`.** Rejected (FR-RBAC-05): leaves a dead, misleading predicate that hides the capability intent and would silently re-grant if a future caller used it for a guarded action.
- **Native Postgres `ENUM` for `role` + `ALTER TYPE ... DROP VALUE`.** Rejected: the column is already `String(20)`; introducing a PG enum now adds DDL-lock risk and an irreversible `DROP VALUE` for zero benefit. App-enum + data UPDATE is simpler and lock-light.
- **Single atomic role migration (one deploy + one migration).** Rejected (R-C5/S8′): impossible against a running fleet with 15-min tokens and un-backfilled rows; a pod on old code would crash on `user` or a pod on new strict code would crash on `student`. Wide→narrow+normalize→remove with positive-evidence exit is the only safe path.
- **Per-user capability table (`user_capability_overrides`) in v1.** Rejected/deferred (R-CAP): no current need for granular per-user revocation; suspension (`is_active`) covers abuse. Pure functions over `User`+`Settings` are testable and zero-migration. Table is added only when granular control is genuinely required.
- **Per-user `can_use_byok` revocation (FR-BYOK-22 as written).** Rejected (R-CAP, R3 cleanup): no storage for it; the `byok.capability_*` audit names and FR-BYOK-22/D-59 are superseded. Suspension is the revocation path.
- **Trusting the JWT `role` claim for authz (skip the DB re-read).** Rejected (FR-MIG-04): a stale `instructor` token would grant powers after demotion/collapse; the existing per-request DB re-read (`deps.py:48,68`) is the security property and is preserved.
- **`can_ingest_url` as a per-user grant.** Rejected (R-M12): the danger is SSRF, not identity; until the SSRF ADR hardens the fetcher, ingest must be globally closed (admin-only + flag-off), not selectively per-user.

---

## Consequences

**Positive:** every active user can author/clone/publish-private by default; dangerous powers retain explicit guards; the JWT claim is provably inert (one test asserts an `instructor` token grants nothing once the row is `user`, FR-MIG-04); the migration is zero-downtime and reversible up to the irreversible data step, with a clear image-rollback playbook; capability logic is one small, unit-testable module; the MCP and REST RBAC are reconciled in one change set so they cannot drift.

**Negative / cost:** three-deploy rollout with a manual positive-evidence gate before Release 3 (operational discipline required); the role data collapse is irreversible (student/instructor distinction is lost forever — R-C4, accepted); a transition window (Phase A–C) where the enum is tolerant of legacy values adds normalization code that must be removed in Release 3 (tracked by the positive-evidence query); `types.ts` is hand-edited (not regenerated) so a CI drift check is required.

**Testing obligations:** suspended-user-cannot-author (FR-DEFINE-06); stale-`instructor`-token-grants-nothing (FR-MIG-04); admin-always-passes every capability; `content_ingest` stays closed post-collapse (FR-SEC-02 negative test); MCP `user` principal can author but cannot ingest; backfill idempotency + row-count log (0030); `set_user_role` rejects `student`/`instructor` writes.

---

## Requirements satisfied

FR-RBAC-01, -02, -03, -04, -05, -06, -07, -08, -09, -10; FR-MIG-01, -04; FR-ADMIN-06, -07; FR-DEFINE-06 (capability+401 portion), FR-DEFINE-09 (unblock); FR-EVAL-03; FR-API-01, -02 (Role-union portion); FR-I18N-01 (role/capability keys), FR-A11Y-02, -03; FR-DOC-01 (this ADR #1). Resolutions: R-C4, R-C5, R-C5′, R-CAP, R-M12, R-S1″ (capability re-check at initiation, cross-ref), R-S10 (suspension as revocation axis). Cross-references: R-M3′/R-M13′ ORM cascade fix (owned by ADR-0029), R-S8′ rollout discipline (mirrored in ADR-0026).

---

## Open risks

1. **Positive-evidence gate skipped under deploy pressure** → Release 3 narrows the enum while a straggler `student` row exists → ORM load crash. Mitigation: the Release-3 query is a hard CI/deploy precondition (R-C5′); the load-normalization hook stays until the query passes.
2. **A reader still keys on `Role.instructor` after Phase C** (e.g., a missed grep). Mitigation: CI grep-guard for `Role.instructor`/`Role.student`/`is_instructor_or_admin`/`is_instructor` outside the deprecation shim (extends R-C1′'s grep-guard discipline).
3. **MCP legacy principal handling** — a long-lived MCP OAuth token minted for a former instructor must keep working through R1–R2 (it re-reads DB role, which is now `user`); risk is only if a tool's posture is narrowed before R3. Mitigation: `create_course_draft` opens to `user` (widening, safe); `ingest_url_to_draft` stays admin-only (no regression for non-admins who never had it).
4. **Spec drift on `can_use_byok`/MCP tool name (`create_course_outline` vs `create_course_draft`)** could lead an implementer astray. Mitigation: this ADR records the verified names and the R-CAP supersession explicitly; the R3 cleanup sweep purges the stale spec phrases.
5. **Frontend cached `/me` with stale `instructor` role** post-collapse — harmless for authoring (gates inverted) but could mis-render a role badge. Mitigation: `normalize_role` on the display path + `roles.user` i18n fallback for any unknown value.
6. **`platform_stats` field rename (`instructors`→`authors`)** is an OpenAPI-visible change consumed by `admin/users` — must ship with the TS client update in the same PR or the admin dashboard renders `undefined`. Mitigation: keep the field through Phase C, flip in Phase C PR with `tsc` gate (FR-API-02).