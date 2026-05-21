# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed (iteration 45)
- **Cert PDF download survives course soft-delete.**
  `download_certificate` loaded the course via
  `courses_repo.get_course`, which filters `deleted_at IS NULL`. So
  once an instructor (or admin) soft-deleted the course, every
  learner who'd earned the cert got a 404 trying to download their
  PDF — a permanent achievement record held hostage by an unrelated
  content-curation decision. The public `verify_certificate`
  endpoint already takes the right posture (no `deleted_at` filter
  on the join), and iter 44 stopped the *learner* from breaking
  their own cert via unenroll. This iteration closes the matching
  server-side path: the PDF endpoint uses `db.get(Course, id)`
  directly so soft-delete doesn't void earned credentials. Covered
  by `tests/test_cert_pdf_survives_delete.py` (2 tests: end-to-end
  earn → soft-delete → still downloadable + verifiable; plus the
  guard-ordering sanity check that an unknown course_id still
  reports `cert.not_enrolled` rather than masking it as 404).

### Fixed (iteration 44)
- **Block unenroll on a completed enrollment.** `DELETE
  /api/v1/me/enrollments/{course_id}` issued a hard
  `db.delete(enrollment)` regardless of completion state. The
  Enrollment row owns the learner's `certificate_id` and (FK
  `ondelete=CASCADE`) all their `lesson_progress` rows, so a single
  DELETE silently invalidated the certificate (`/verify/{cert_id}`
  → 404), threw away every completion timestamp, and lost the quiz
  scores stored on `lesson_progress.payload`. No frontend surface
  currently exposes unenroll, but the API client does — one rogue
  call destroys an achievement record permanently. Refuse with 409
  `enrollment.completed` once the cert has been issued; mid-progress
  unenroll still works as before. Covered by
  `tests/test_unenroll_after_complete.py` (3 tests: refused after
  completion + cert still verifies, mid-progress still allowed,
  unenroll-when-never-enrolled remains an idempotent 200).

### Fixed (iteration 43)
- **Block publishing a course with zero live lessons.**
  `_transition_status` checked only `title` and `overview` before
  letting `draft → published` through. So an instructor could fill in
  two fields, click publish, and push an empty shell into the catalog.
  Students who enrolled landed on a blank syllabus, progress stuck at
  0% forever, with no signal that the author hadn't finished. Now the
  publish path counts live (non-soft-deleted) lessons across the
  course and raises 422 `course.no_lessons` if there are none — same
  rule applies after-the-fact (soft-deleting the last lesson and
  trying to re-publish from draft is rejected). Covered by
  `tests/test_publish_minimum_content.py` (4 tests). Added a
  reusable `seed_lesson` conftest fixture and retrofitted 11 legacy
  tests that had been publishing empty courses as test scaffolding.

### Fixed (iteration 42)
- **`DELETE /admin/tags/{id}` now refuses when the tag is in use.**
  The endpoint issued a raw `db.delete(tag)`; `course_tags.tag_id`
  has `ON DELETE CASCADE`, so the operation silently stripped the
  tag from every course that referenced it — no warning to the
  admin, no audit-friendly trail of what got detached. Brought it
  into line with `delete_subject` (hardened in iter 28): refuse
  with a 409 `tag.in_use` (carrying the count of attached live
  courses) so the admin can clean up first. Soft-deleted courses
  don't block the delete (their join rows cascade quietly with no
  visible impact). Covered by `tests/test_admin_tag_delete.py`
  (5 tests: live-attached refusal, soft-deleted-doesn't-block,
  unused-succeeds, 404, and instructor-can't-call).

### Fixed (iteration 41)
- **Module / lesson reorder rejects partial and malformed mappings.**
  Both reorder paths set every row's `order` to a negative temp value
  (to dodge the `(parent, order)` unique constraint), then assigned
  new orders only to the rows the caller named. A *partial* mapping
  left the unnamed rows stuck at `-1, -2, -3, ...` permanently — and
  since SQL ORDER BY puts negatives first, the syllabus silently
  hoisted them to the top on next render. The official client always
  sends the full ordering, but a buggy mobile build, a network replay,
  or an authenticated bad actor could trigger the bug. We now require
  the mapping to cover every existing id exactly once, reject negative
  or duplicate target values up front (explicit 422 instead of an
  eventual unique-constraint 5xx), and — for lessons — park soft-
  deleted rows just past the live range so they can't collide with a
  new target value either. Covered by
  `tests/test_reorder_completeness.py` (6 tests: partial / negative /
  duplicate / full mappings for modules, plus soft-deleted-skip and
  partial-lesson rejection at the service layer).

### Fixed (iteration 40)
- **Blocked self-reviews on owned courses.** Instructors can enroll in
  their own published course (handy for previewing what learners see)
  but could then post a 5-star review of themselves, padding
  `avg_rating` and the catalog's "top-rated" sort. The notification
  path already had `if course.owner_id != author.id` — the codebase
  knew the scenario but didn't reject it. `reviews.upsert` now
  raises `review.self_review` for the owner, and the frontend hides
  the review editor when viewer owns the course so we don't show a
  button that always 403s. Covered by `tests/test_self_review.py`
  (3 tests: PUT + PATCH rejection, avg_rating staying honest after
  a rejected owner attempt, peer-instructor still allowed to review).

### Security (iteration 39)
- **Unified password strength policy across register / reset / change.**
  Only `RegisterRequest` ran the "mix character classes" check; the
  reset-confirm and change-password endpoints enforced just
  `min_length=12`. So a user who registered with `Password!1234` could
  downgrade to `password12345` via either flow — bypassing the policy
  they agreed to at signup, and giving anyone with a reset token (or
  the user's current session) an easier offline-cracking target.
  Extracted `validate_password_strength` into `app.schemas.auth` and
  wired it to all three sites. Covered by
  `tests/test_password_policy.py` (8 tests: parameterised
  validator accept/reject, schema-level checks on both reset and
  register, end-to-end rejection at reset and change endpoints, plus
  a happy-path change-password to verify the tightening didn't break
  the normal flow).

### Security (iteration 38)
- **Removed the `"*"` content-type wildcard for attachment uploads.**
  The `attachment` kind's allow-list was `{"*"}` — any authenticated
  user could PUT `text/html` / `image/svg+xml` / `application/javascript`
  to the public bucket via a presigned URL, and S3 served those blobs
  inline with the requested Content-Type. Because the bucket sits on
  the platform's own DNS, that turned the upload endpoint into a
  hosted-XSS/phishing surface. Replaced with an enumerated set of
  doc/archive/media/code types learners actually attach. Added
  `ALWAYS_DENIED_TYPES` — applied before every per-kind check — as
  defense-in-depth so any future kind cannot re-open the same hole
  for HTML, SVG, or JavaScript. Covered by
  `tests/test_uploads_content_type_safety.py` (7 tests: structural
  invariants on the allow-list, parameterised rejection of every
  classic XSS carrier, plus the happy path for an attachment PDF).

### Fixed (iteration 37)
- **Password-reset and email-verify links pointed at the API host.**
  Both link builders used `settings.api_base_url` (FastAPI, port 8000
  dev, typically `api.example.com` prod) but the actual reset and
  verification pages are Next.js routes that only exist on the user-
  facing web host (`example.com`). Anyone clicking the link in their
  inbox in prod landed on a 404. Introduced `WEB_BASE_URL` (default
  `http://localhost:3000`) and routed both emails through it; the
  prod-readiness guard now refuses to boot if it's still the dev
  default, mirroring the existing `cors_origins` check. Covered by
  `tests/test_email_link_host.py` (4 tests: prod guard accept/reject,
  reset link host, verify link host).

### Security (iteration 36)
- **Chat WebSocket re-authorises on every post.** The connection
  validated the user and enrollment once at connect, then cached both in
  local variables for the lifetime of the socket. So deactivating an
  account, unenrolling a learner, or unpublishing a course only took
  effect when the socket finally dropped — until then the offender kept
  publishing messages from the stale connect-time session. The message
  branch now reloads the user (`users_repo.get_by_id`) and re-runs
  `ensure_can_chat`; failure sends a typed error frame and closes the
  socket (4401/4403/4404). Typing pings still flow without the recheck
  to keep that path cheap. Covered by `tests/test_chat_ws_revalidate.py`
  — three tests that exercise the underlying primitives the WS now
  depends on (no WS test harness in this repo, so the loop wrapper
  itself is 5 lines on top of well-tested service calls).

### Fixed (iteration 35)
- **Quiz editor stopped reusing question ids after a delete.** The
  `addQ()` helper in the lesson editor minted ids as
  `q${questions.length + 1}`, so deleting the first question and adding
  a new one produced `q1` again — colliding with the next question and
  silently making both share answer keys / grade slots. The helper now
  scans for the lowest unused id. As defense-in-depth on the wire,
  `QuizLessonData` gained a `_unique_question_ids` validator so any
  client (the buggy editor, a mobile app, an import script) sending
  duplicates gets a 422 instead of a corrupt quiz. Covered by
  `tests/test_quiz_question_unique_ids.py`.
- **/learn now resumes at the first incomplete lesson.** The outline
  always defaulted to lesson 1, so a learner 7-of-10 lessons in saw
  lesson 1 selected every time and had to hunt for where they left off.
  Defaults to the first lesson with `completed: false`, falling back to
  lesson 1 only when the course is fully done.

### Added (iteration 34)
- `LessonOut.completed` (per-viewer) on the course-detail endpoint. The
  syllabus on the course page and the lesson outline in `/learn` now show
  a green check next to each lesson the learner has finished, plus a
  strikethrough title style. Anonymous and non-enrolled viewers always
  see `completed: false`. Backed by `repositories.courses.completed_lesson_ids`
  which excludes soft-deleted lessons so the marks line up with what's
  actually in the syllabus. Three regression tests in
  `test_lesson_completion_flag.py` cover the per-viewer flag flip,
  per-viewer isolation, and the anon / non-enrolled fallback.

### Fixed (iteration 33)
- **Certificate PDF's verify URL now points at the real public page.**
  The rendered PDF embedded `verify at /certificates/<id>` — a route
  that doesn't exist; the public verification page lives at
  `/verify/<id>`. Anyone who downloaded a certificate and typed the
  printed URL landed on a 404. Centralised the path in a module
  constant (`VERIFY_PATH = "/verify"`) and updated the rendered
  string. Two regression tests in `test_certificate_pdf.py` lock in
  the new URL and the single-source-of-truth constant.

### Security (iteration 32)
- **Closed the login enumeration timing side-channel.** The authenticate
  path skipped Argon2 verification when the email lookup returned None,
  so a "no such email" response came back roughly an order of magnitude
  faster than a "wrong password" response — a wire-observable oracle
  for which emails are registered. We now run `verify_password` against
  a precomputed dummy hash on the missing-user path, so both branches
  do the same dominant CPU work. `tests/test_login_timing.py` asserts
  the two latencies stay within 3× of each other. Documented in
  `docs/security.md`.

### Fixed (iteration 31)
- **Chat presence no longer drops active senders after 60 seconds.**
  `mark_present` ran once on WebSocket connect; `list_present` filters
  by a 60-second freshness window, so a user who stayed connected and
  kept sending messages fell off the presence list after one minute.
  The WS handler now refreshes the presence sorted-set score on every
  inbound frame — active users stay listed, idle users still expire
  naturally. A `_FakeRedis` test double exercises the
  refresh / absence / stale-cutoff behaviour without standing up a
  real Redis or WebSocket.

### Fixed (iteration 30)
- **Catalog subject tiles stop counting soft-deleted courses.**
  `list_subjects` outer-joined Course with `status == published` only,
  so a course soft-deleted by an instructor still kept inflating the
  badge on the subject tile (the catalog grid shows fewer rows than
  the badge claimed). Outer-join condition now also requires
  `Course.deleted_at IS NULL`. Two regression tests in
  `test_subjects_total.py` cover the soft-delete drop and the
  draft / archived exclusion.

### Fixed (iteration 29)
- **Catalog `?sort=` no longer crashes on unknown / non-column values.**
  `search_courses` resolved the sort field with
  `getattr(Course, name, Course.created_at)`. Crafted values like
  `sort=modules` (relationship), `sort=metadata` (SQLAlchemy
  bookkeeping), or `sort=__class__` returned attributes whose
  `.desc()` raised `AttributeError` and surfaced as a 500. Replaced
  with an explicit allow-list (`created_at`, `published_at`, `title`,
  `is_featured`); unknown values quietly fall back to `created_at`.
  Three regression tests in `test_catalog_sort.py`.

### Fixed (iteration 28)
- **Admin subject deletion no longer 500s when courses are attached.**
  `DELETE /api/v1/admin/subjects/{id}` issued an unconditional DELETE
  and let `Course.subject_id FK ondelete=RESTRICT` crash into the
  unhandled-exception path. The endpoint now pre-counts referencing
  courses (live + soft-deleted, because the FK ignores `deleted_at`)
  and refuses with a clean 409 `subject.in_use` carrying both counts
  in `details`. Four regression tests in `test_admin_subject_delete.py`
  cover the live-course block, the soft-deleted-course block, the
  no-courses success path, and unknown-id 404.

### Fixed (iteration 27)
- **Progress writes against a soft-deleted lesson now 404 cleanly.**
  `POST /me/progress/lessons/{id}` and the quiz submission both routed
  through `courses_repo.get_lesson`, which doesn't filter `deleted_at`.
  An enrolled learner holding a stale lesson id (cached SPA state,
  request replay, etc.) could persist a `LessonProgress` row pointing
  at a removed lesson — the row didn't count toward progress (the count
  query is already filtered, iteration 22) but it cluttered the DB and
  returned a misleading 200. Both endpoints now reject deleted lessons
  with `lesson.not_found`. Two regression tests in
  `test_deleted_lesson_writes.py`.

### Fixed (iteration 26)
- **The learner dashboard no longer renders enrollments to soft-deleted
  courses.** `list_enrollments_for_user` returned every row regardless of
  `Course.deleted_at`, so the "in progress" card linked to a course
  whose detail page 404'd. Repo now joins `Course` and filters
  `deleted_at IS NULL`. Archived / draft courses still show up — only
  truly deleted ones disappear, paired with the iteration-24 fix.

### Fixed (iteration 25)
- **Course slug minting now sees through soft-deletes.** `_unique_slug`
  used `get_course_by_slug`, which hides `deleted_at IS NOT NULL` rows.
  Recreating a course with the same title as a soft-deleted one looked
  fine to the minter then crashed the INSERT against the unconditional
  `UNIQUE(courses.slug)` constraint. Added
  `repositories.courses.slug_is_taken(db, slug, exclude_id=...)` which
  reads the raw table, and switched the slug minter to use it. Three
  regression tests cover delete-then-recreate, repeated duplication, and
  rename-to-same-title.

### Fixed (iteration 24)
- **Archiving (or un-publishing) a course no longer locks out already-
  enrolled learners.** `GET /api/v1/courses/{slug}` previously routed
  visibility through `can_view_unpublished`, which returned True only
  for the course owner and admins. Existing students of a course an
  instructor then archived would start getting a 404 on the syllabus —
  losing the chat link, lesson navigation, and certificate download CTA
  they earned. Introduced `can_view_course(db, course, viewer)` which
  also accepts a current enrolment as proof of access. Anonymous and
  not-enrolled viewers still see 404 for non-published courses. Three
  regression tests in `test_archived_access.py`.

### Fixed (iteration 23)
- **Failing a quiz retake no longer un-passes a previously-passed lesson.**
  The quiz endpoint previously routed through `mark_lesson(completed=…)`,
  which cleared `LessonProgress.completed_at` on every failing attempt.
  A learner who passed and then retook out of curiosity could lose their
  completion (and the course-completion certificate that hinged on it).
  Introduced `enrollment_service.record_quiz_attempt` which always
  records the latest score but only flips `completed_at` on a passing
  attempt — and never clears it. Two regression tests in
  `test_quiz_retake.py` lock the "pass then fail-retake stays complete"
  and "fail-then-pass marks complete with the new score" paths.

### Fixed (iteration 22)
- **Progress could exceed 100% after a lesson was soft-deleted.**
  `count_completed_lessons`, the per-course `avg_progress_pct`, and the
  cohort listing all counted every `LessonProgress` row regardless of
  whether the parent lesson still existed. Soft-deleting a finished
  lesson left ``done > total``, which produced >100% progress for the
  learner and the cohort view, and risked spurious certificate issuance.
  The queries now join `Lesson` and filter on `Lesson.deleted_at IS NULL`,
  so progress always clamps to the surviving curriculum. Three
  regression tests in `test_progress_soft_delete.py` lock the fix in
  for the learner, cohort, and per-course-analytics paths.

### Added (iteration 21)
- ChatRoom test (vitest): swaps in a MockWebSocket double and asserts the
  empty/connecting state, server-pushed messages render, presence count
  updates, outbound frames are valid JSON, Send is disabled until the
  socket is OPEN, transient closes (1006) show "Reconnecting", terminal
  closes (4403) show "Disconnected", and no socket is opened when there's
  no token.

### Fixed (iteration 20)
- `/learn/[slug]` now redirects non-enrolled viewers to the course detail
  page (with a "Enroll to start learning" toast) instead of rendering a
  player whose writes the server silently rejected. Course owners and
  admins bypass the guard so they can preview their own content.

### Added (iteration 20)
- Public free-preview lessons get a real surface: a new
  `/courses/[slug]/preview/[lessonId]` page renders any `is_preview`
  lesson via the existing public endpoint, with a friendly Enroll CTA
  and clear messaging for 403 / 404 cases. The course detail syllabus
  now shows a "Sample →" link beside each preview lesson on published
  courses.
- `Courses.getLesson()` added to the typed API client.

### Fixed (iteration 19)
- Wrapped every `useSearchParams` consumer in `<Suspense>` boundaries so
  Next.js 15 can serve them without forcing full-page dynamic rendering:
  login, reset-password, verify-email, catalog (`/courses`), and the
  HeaderSearch component used on every route via the site header. Each
  boundary ships an opaque skeleton fallback that matches the final
  layout (no layout shift on hydration).

### Changed (iteration 19)
- `docs/api.md` gains a top-of-document Contents section so the ~280-line
  reference stays navigable.

### Added (iteration 18)
- Per-course OpenGraph metadata. The course detail route is split into a
  server `page.tsx` that exports `generateMetadata` and a client
  `course-detail-view.tsx`. Shares now carry the course title,
  description (first 280 chars of overview), `og:image` (cover), and a
  canonical link; 404s become a "Course not found" title.
- ImageUpload component test: file too large is rejected before the API
  is called, signs + PUTs + calls onChange with the public URL, surfaces
  an error toast on PUT failure, Remove clears the value, and the
  preview/placeholder render paths are covered.

### Added (iteration 17)
- SEO: Next.js generates `/robots.txt` (allows public routes, disallows
  auth + studio + admin + learn paths) and `/sitemap.xml` (static routes
  plus the most recent 100 published courses with `lastModified` and a
  boost for featured ones). Sitemap is fail-soft: if the API is down at
  regeneration time, only the static routes are emitted.
- CourseCard tests extended with: hides Featured badge when not featured,
  omits rating tile when `avg_rating` is null, renders the cover `<img>`
  when `cover_url` is set (with the monogram fallback when not), and
  surfaces the difficulty + subject badges.

### Changed (iteration 16)
- README "Features at a glance" rewritten as Learner / Instructor / Admin /
  Cross-cutting sections that match what actually shipped (bookmarks,
  server-graded quizzes, cohort view, sessions UI, cert verification,
  rate limiting, prod-secret guard, studio status tabs, …).
- `docs/security.md` gains a "Rate limiting" section with the per-endpoint
  thresholds and a note on `X-Forwarded-For` trust.

### Added (iteration 16)
- Frontend test for `LessonEditor`: existing-lesson seeding, patch round-
  trip (incl. `is_preview` toggle), create round-trip for a new lesson,
  delete invokes `deleteLesson` + `onDeleted`, quiz "Add question" path,
  Save disabled until a title is entered.

### Fixed (iteration 15)
- **Rate limiting was configured but never wired**. The `slowapi` limiter
  is now mounted on the FastAPI app via `SlowAPIMiddleware`, and the
  high-risk auth endpoints carry per-IP limits: `POST /auth/login` (10/min),
  `POST /auth/register` (5/min), `POST /auth/password-reset/request`
  (3/min), `POST /auth/verify/request` (3/min). 429 responses use the
  standard envelope and include `Retry-After`. Tests use an in-memory
  bucket reset via a `_reset_rate_limiter` autouse fixture.

### Added (iteration 15)
- Frontend tests: CohortCard (empty / mixed-progress / error states) and
  NotificationsBell (unread badge count, mark-on-click, empty state).

### Added (iteration 14)
- Studio courses page gains All / Drafts / Published / Archived filter
  tabs with counts so archived courses stop cluttering the live view.
- Frontend tests: SessionsCard (list render, per-row revoke, sign-out-
  everywhere, empty state) and MyReviewEditor (initial state, seeded
  existing review, save, remove, save-disabled-until-rating).

### Added (iteration 13)
- Server-side quiz grading. `POST /api/v1/me/progress/lessons/{id}/quiz`
  accepts an `{answers: {question_id: ...}}` payload, grades the quiz
  server-side via the new `app.services.quiz` module, persists the score on
  `LessonProgress.score`, marks the lesson complete on pass, and returns
  per-question correctness. The lesson player now submits to this endpoint
  and renders the server-graded result (per-question badges, pass/fail
  message tied to the actual `pass_score`).
- `GET /api/v1/admin/stats` returns platform totals (users, active users,
  instructors, courses by status, enrollments). Admin home renders a
  "Platform at a glance" tile row.

### Added (iteration 12)
- Instructor cohort view: `GET /api/v1/courses/{course_id}/students` returns
  enrolled learners with per-student progress %, completion timestamp, and
  certificate id. Rendered on the studio course page as a new "Students"
  card with status badges (completed / in progress / not started).
- Course detail badges (subject, difficulty, tags) are now Links into
  `/courses?subject=…`, `?difficulty=…`, `?tag=…` for one-click discovery.
- Catalog page now seeds `subject`, `difficulty`, and `tag` from the URL
  in addition to `q`, so deep-links from elsewhere "just work".

### Changed (iteration 12)
- `docs/security.md` refreshed to cover the post-iteration-7 auth surface:
  password change + revoke, password reset (hash-bound JWT), email verify
  (email-bound JWT, idempotent), active sessions, public certificate
  verify (no PII), and the production startup guard.

### Added (iteration 11)
- Chat WebSocket auto-reconnects with exponential backoff (1s → 30s, six
  steps) and a coloured status pill ("Reconnecting…"). Server-refused
  closes (4401/4403/4404) stop retrying. Backoff + retry logic lives in
  `lib/reconnect.ts` and is unit-tested.
- Catalog page renders tag filter chips below the row of selects; clicking
  one filters by `?tag=<slug>`, with a clear button when active.
- Register success toast now hints that a verification email is on the way.

### Changed (iteration 11)
- Catalog tag list fetched once via the existing `/tags` endpoint and
  capped at 20 chips to keep the header compact.

### Added (iteration 10)
- Header search bar (visible on md+ and inside the mobile drawer) routes to
  `/courses?q=…`; the catalog page now seeds its `q` input from the URL.
- `POST /api/v1/admin/search/reindex` (202 Accepted) queues a full catalog
  reindex via Celery; falls back to inline reindex when no broker is
  reachable. Admin home renders a "Reindex catalog" button under a Search
  index card.
- `GET /api/v1/certificates/verify/{certificate_id}` is a public endpoint
  that returns the certificate's course + display name (no PII). A new
  `/verify/[id]` Next.js page renders the result so anyone with the ID can
  confirm a certificate is real.

### Added (iteration 9)
- Active-sessions panel on `/profile` — lists each refresh-token session
  with user-agent + IP + age, per-row revoke, and a "Sign out everywhere"
  button.
- Admin `GET /api/v1/admin/courses` returns the full catalog (filterable
  by `q` and `only_featured`); `PATCH /admin/courses/{id}/feature` toggles
  the featured flag and writes an `admin.course.featured` audit row.
- New `/admin/courses` UI lists every course with status badges and a
  Feature / Unfeature button; admin home tile grid links to it.

### Changed (iteration 9)
- Hoisted the admin router's mid-block imports (selectinload, builders,
  repo, model, schema) to the top of the file for consistency with the
  rest of the codebase.

### Changed (iteration 8)
- Centralized `CourseListItem` / `CourseDetail` construction in
  `app/api/v1/_builders.py`. catalog, courses, enrollments, bookmarks, and
  search routers now share the single builder — eliminates five copies of
  the same field-by-field projection.
- Hoisted mid-file imports in `users.py`, `courses.py`, and `search.py` to
  module-level; removed unused imports along the way.
- `SessionOut` revoke endpoint now raises `NotFoundError` (was a misnamed
  `ValidationAppError`) when the session id is unknown.

### Added (iteration 8)
- Production startup hardening: `Settings.assert_production_ready()` refuses
  to boot when `env=production` if `JWT_SECRET`, `SECRET_KEY`, or
  `S3_SECRET_ACCESS_KEY` are still dev defaults, or if `CORS_ORIGINS`
  contains `localhost`. Called from the FastAPI lifespan.
- Accessibility: skip-to-content link in the root layout, `aria-current="page"`
  on active nav links (desktop and mobile drawer).

### Added (iteration 7)
- Email verification flow: register queues a verification email, `POST
  /api/v1/auth/verify/request` resends, `POST /api/v1/auth/verify/confirm`
  marks `email_verified_at`. Tokens are stateless JWTs bound to the current
  email; idempotent on replay; rejected after email change. Profile page
  shows a verified/unverified badge and a Resend button.
- `/verify-email` page handles the link landing flow.
- Lesson free-preview flag: `is_preview` on lessons; published-course
  preview lessons are fetchable anonymously via `GET
  /api/v1/courses/lessons/{lesson_id}`. Course detail tags them with a
  "free preview" badge; lesson editor exposes the toggle.
- Active sessions: `GET /api/v1/users/me/sessions`,
  `DELETE /api/v1/users/me/sessions` (sign out everywhere),
  `DELETE /api/v1/users/me/sessions/{id}` (revoke one).

### Added (iteration 6)
- `GET /api/v1/courses/{course_id}/analytics` returns per-course metrics
  (enrollments, completions, completion rate, avg rating + count, avg
  progress, new-7d and new-30d enrollments). Surfaced on the studio page.
- `POST /api/v1/courses/{course_id}/duplicate` clones a course (modules +
  lessons) as a draft owned by the caller, with a unique slug. Any instructor
  can duplicate a published course to remix it.
- `scripts/export_openapi.py` + `make openapi` / `make openapi.local` dump
  the OpenAPI schema without a running stack.

### Added (iteration 5)
- Course bookmarks: `GET/PUT/DELETE /api/v1/me/bookmarks/{course_id}`, with
  `is_bookmarked` exposed on the course detail and a Bookmarks section on the
  dashboard.
- Lesson navigation in the learner view: Previous / Next plus a
  "Mark complete & continue" combo button.

### Changed (iteration 5)
- `_owned_module` / `_owned_lesson` now raise `NotFoundError` (not
  `ForbiddenError`) when a parent record is missing — clearer error semantics.
- `docs/api.md` documents the full endpoint inventory across auth, users,
  catalog, search, courses, enrollments, reviews, chat, uploads, certificates,
  admin, bookmarks, and health.

### Added (iteration 4)
- `/api/v1/search/courses` endpoint backed by Meilisearch with an automatic
  Postgres ILIKE fallback when the search service is unavailable.
- Presigned image upload widget wired into the profile avatar and the
  new-course cover image fields.
- `MyReviewEditor` lets enrolled learners post, update, or delete their review
  inline on the course detail page.
- "Preview as student" link on the studio course page.
- Mobile navigation with hamburger toggle that collapses on route change.
- Notifications bell in the header with unread badge and click-to-read.
- Project-level `CLAUDE.md` to orient future agent sessions.

### Changed (iteration 4)
- Quiz grading extracted into `lib/quiz.ts` so the lesson player and tests
  share one implementation.
- `Courses.create` typed signature now accepts `cover_url` and `tag_ids`.
- Site header tracks active route to highlight the current section.

### Fixed (iteration 4)
- Course publish/unpublish/delete now best-effort enqueues a search reindex
  (tolerates a missing Celery broker in dev/tests).

### Foundation
- Complete rewrite from Django prototype to FastAPI + Next.js 15.
- Repository skeleton (monorepo with `apps/backend`, `apps/frontend`).
- SDLC documentation: PRD, architecture, ADRs (0001–0007), SDLC, API conventions, security model, deployment guide.
- Docker Compose for local dev and production.
- FastAPI app factory, settings, async SQLAlchemy, Alembic, structured logging, error handlers, OpenAPI.
- Domain models: User, Subject, Tag, Course, Module, Lesson (polymorphic), Enrollment, Progress, Review, ChatMessage, Notification, AuditEvent, RefreshToken, Asset.
- Auth: register, login, refresh (rotating), logout, current user, password reset stub; RBAC.
- Courses, modules, lessons CRUD with publishing, ordering, content types, instructor permissions.
- Enrollment, progress, reviews, certificates.
- Real-time chat with WebSocket + Redis pub/sub, persistence, presence.
- File uploads via presigned URLs to MinIO.
- Search via Meilisearch (with Postgres fallback).
- Next.js 15 frontend foundation: App Router, Tailwind 4, shadcn/ui, TanStack Query, generated API client.
- Frontend pages: landing, auth, catalog, course detail, learner dashboard, instructor studio, chat UI, profile.
- Test stacks: pytest + httpx + factory-boy for backend; vitest + Playwright for frontend.
- GitHub Actions CI/CD: lint, type-check, test, build, scan, push images, deploy stage on `main`, tag-driven prod.
- Observability: structlog JSON logs, OpenTelemetry, Prometheus metrics endpoint.
- Pre-commit hooks: ruff, eslint, prettier, gitleaks, conventional-commits check.

### Changed
- Original Django project archived to `legacy/`.

### Security
- Argon2id password hashing.
- Refresh-token rotation with reuse detection.
- CSP, HSTS, secure cookie defaults.
- Rate limiting on auth and chat endpoints.
