# Product Requirements Document — Lumen

| Field         | Value                              |
|---------------|------------------------------------|
| Status        | Shipped (rebuild 2026-Q2)          |
| Owner         | @ahmedEid1                         |
| Last updated  | 2026-05-22                         |
| Supersedes    | PRD v1.0 (2026-05-21)              |
| Rebuild spec  | `docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md` |

## 0. Status — what shipped vs the original PRD

The original PRD targeted a 2026-Q3 launch of a Coursera-style OSS LMS. Mid-cycle discovery surfaced that **Moodle 5.2 + Open edX with AI Course Creator V2 already cover that ground for free**, while no credible OSS AI-first LMS shipped in May 2026. Lumen pivoted to **Archetype B+: AI-first OSS learning platform with a light async-cohort surface**, executed across six rebuild phases (A–F) over 25+ commits on the `Rewrite` branch.

The shipped diff:

- **Visual identity:** "Workbench" dense functional palette (electric lime accent on `#0A0B0D`, Inter / JetBrains Mono, border-driven elevation, dark-mode-default). The Skillpath cobalt theme and the prior Egyptian-deity branding are both gone.
- **Search:** Meilisearch was ripped (Cut A9); full-text search runs on Postgres `tsvector` + GIN; semantic retrieval ships on **pgvector** with a provider-agnostic embedding service (local sentence-transformers / OpenAI / noop).
- **Discussions / chat:** Per-course WebSocket chat was removed (Cut A8). Replaced by per-lesson async comments + the course-scoped **AI tutor** (E1) for "ask about this lesson"-style questions.
- **Credentials:** PDF certificates are now a fallback only. The primary credential is an **Open Badges 3.0 / W3C Verifiable Credential** signed with an Ed25519 key (E5), with a public `/api/v1/credentials/{cert_id}/verify` endpoint.
- **Cuts:** Bookmarks (A7), DiscussionSubscription (A4), `LessonProgress.payload` (A3), idempotency middleware (A2), duplicate-course feature (A5), and several Skillpath-era no-op primitive shells are all gone.
- **AI moat (Phase E):** course-scoped RAG tutor with citations (E1), AI-assisted course authoring with human-in-the-loop preview (E2), multi-modal ingest from YouTube / Notion / Google Docs (E3), FSRS-6 spaced repetition queue (E4), Tiptap block editor for lesson bodies (E6), mastery dashboard (E7).
- **PRD-promised quick wins (Phase D):** "Preview as student" (D1), instructor analytics (D2), first-login onboarding tour (D3), smart digest + per-kind email preferences (D4), and a **WCAG 2.2 AA axe-core CI gate** (D5) blocking on every PR.
- **Bug fixes / hardening (Phase B):** dashboard N+1 collapse, public certificate-verify rate limit, partial-unique slug on live courses, demo credentials no longer ship to prod, account-delete revokes all refresh tokens, notifications composite index swap.

The original goals around auth, catalog, progress tracking, quizzes, reviews, uploads, certificates (now as fallback), email notifications, RBAC, i18n + RTL, container-first dev, and CI on every PR all shipped; the goals around per-course chat and bookmark-as-dashboard-surface were superseded by AI tutor + comments and dropped as anti-patterns respectively. The non-goal list (payments, video conferencing, native mobile, multi-tenant SaaS, LRS/xAPI, AI-generated content) has narrowed: **AI-generated content is now in-scope and shipped**, gated behind explicit instructor confirmation; everything else remains out of scope.

## 1. Problem statement

The original `E-Learning-Platform` was a Django prototype: CRUD courses, drag-and-drop modules, a tiny chat. It lacked durable auth, progress tracking, search, quizzes, certificates, observability, and any container story. It also ran on SQLite without tests.

Educators on the original platform asked for: durable accounts they could share with cohorts, auto-grading assessments, visibility into student progress, and a mobile-friendly UI. Independent learners asked for a browsable catalog without an account, search, and resumption.

**Lumen** is the rewrite that solves these problems while reframing the wedge around what is uniquely OSS in 2026: a self-hostable AI-first learning surface that actually understands the course content, with a credible asynchronous social loop on top.

## 2. Vision

> Lumen is the self-hostable AI-first LMS for serious learners and instructors who want the platform to actually understand the course content — not just store it.

The fifteen-minute `docker compose up` promise stays. The same artifacts scale from a single instructor demo to thousands of learners.

## 3. Users & personas

### 3.1 Learner (Lina, 24, junior developer)
- Discovers courses via public catalog or full-text search
- Enrolls free; sees a personal dashboard with in-progress courses
- Watches / reads lessons rendered by a Tiptap block renderer; quiz answers auto-grade
- Asks the **course-scoped AI tutor** when stuck — answers ground in retrieved lesson chunks and surface inline citations
- Sees a **review queue** (FSRS-6) per quiz card and works through due items
- Receives an **Open Badges 3.0** credential on 100% completion, with the PDF certificate as a fallback download

### 3.2 Instructor (Tareq, 38, university lecturer)
- Builds courses with modules and lessons; drag-and-drop ordering
- Lesson bodies authored in a **block editor** (Tiptap; Notion-style)
- Optional **AI authoring studio**: paste a brief, get a proposed outline + draft lesson bodies + draft quizzes — all reviewed before any DB write
- Optional **multi-modal ingest**: paste a YouTube / Notion / public Google Doc URL, get a draft course skeleton with anchor-deep links back to the source
- Publishes drafts when ready; publish triggers embedding indexing for the AI tutor
- Sees per-course analytics: enrollment count, completion %, avg rating, recent reviews, per-lesson drop-off
- **"Preview as student"** mode renders the draft course exactly as a learner would see it

### 3.3 Admin (Sara, platform operator)
- Manages subjects, tags, featured courses
- Grants / revokes instructor permission
- Reviews abuse reports and audit log
- Triggers a course-embedding reindex after flipping `EMBEDDING_PROVIDER`
- Monitors system health via Prometheus + structlog

## 4. Goals & non-goals

### Goals (shipped in 1.0.0-rebuild)
1. Modern authentication: JWT access + rotating refresh, password reset, account deletion with full token revocation, optional OAuth-ready surface.
2. Public catalog with full-text search (Postgres `tsvector` + GIN), filters, ratings, partial-unique slug on live courses.
3. Per-lesson progress tracking and course-level completion %.
4. Quizzes (MCQ + short-answer) with auto-grading and append-only attempt history.
5. Reviews & ratings (1–5 stars + free text).
6. Per-lesson async comments + course-scoped AI tutor (replacing the v1 per-course WebSocket chat).
7. File uploads via S3-compatible storage; image pipeline.
8. Email notifications: transactional + daily digest worker, per-kind dispatch preferences (`off | in_app | email_immediate | digest_daily`).
9. Credentials: Open Badges 3.0 / W3C VC as primary, PDF as fallback. Public signature verify endpoint.
10. Accessibility: **WCAG 2.2 AA gated in CI** via `@axe-core/playwright` against built pages on every PR.
11. Fully containerized; `docker compose up` produces a working dev env.
12. CI on every PR; production-ready Docker images; Trivy + CodeQL + gitleaks.
13. AI-native differentiators: RAG tutor with citations, AI authoring with human-in-the-loop, multi-modal ingest, FSRS-6 review queue, mastery dashboard, block editor.
14. ≥ 80% line coverage on backend domain modules; smoke E2E on golden paths.
15. **Workbench visual identity** applied to 100% of frontend surfaces (no orphan cobalt or Skillpath references).

### Non-goals (preserved)
- Payments (architecture leaves room for Stripe; no integration shipped).
- Live video conferencing.
- Mobile native apps (responsive web only).
- Multi-tenant SaaS isolation.
- Advanced LRS / xAPI integration.
- LTI integration (deferred).
- SCORM authoring (import-only, much later).
- Marketplace / creator-economy hooks.
- White-label theming.
- Knowledge graph + prerequisite detection across catalog.

### Non-goal lifted in this rebuild
- AI-generated content. Now in-scope: AI authoring + AI tutor + multi-modal ingest all shipped, every generate path is human-in-the-loop (no auto-persist).

## 5. Functional requirements (shipped surface)

### 5.1 Identity & access
- Register with email + password; verification email via Mailpit / SMTP.
- Login returns short-lived JWT access (15 min) + rotating refresh (14 d, httpOnly cookie). Cookies for browsers; Bearer for API clients; `?token=` for WebSockets.
- Password reset via emailed link (30 min TTL).
- Roles: `student` (default), `instructor`, `admin`. RBAC enforced at the service layer.
- Admin can promote a user to instructor.
- Logout invalidates the refresh token server-side.
- Account: profile edit, avatar upload, change password, export data (GDPR), delete account. **Delete revokes all refresh tokens in the same transaction and flips `is_active = False`.**

### 5.2 Catalog & discovery
- Public landing with featured courses and a subject grid (no marketing chrome — Workbench rules).
- `/courses` list with subject filter, tag filter, difficulty filter, free-text search, sort (newest / most popular / top rated).
- Course detail page: overview, syllabus (modules → lessons), instructor card, reviews, enroll CTA.
- Search powered by Postgres generated `search_vector` column + GIN; ILIKE fallback for partial-word matches.

### 5.3 Authoring (instructor studio)
- Create course (title, slug, subject, tags, difficulty, overview, cover image).
- Course states: `draft`, `published`, `archived`.
- Modules: title, description, order. Drag-drop reorder.
- Lessons: title, type (`text` | `video` | `image` | `file` | `quiz`), order. Drag-drop reorder.
- Lesson bodies authored in a Tiptap block editor (paragraph, headings, lists, blockquote, code block with lowlight, image, link, callout, horizontal rule). Legacy markdown bodies render and promote to a paragraph block on first edit.
- **AI-assisted authoring (E2):** `POST /studio/ai/outline | /lesson-body | /quiz | /commit-outline` — all rate-limited at 5/min per user, all human-in-the-loop, all return previews that the instructor must explicitly accept before anything lands in the DB.
- **Multi-modal ingest (E3):** `POST /studio/ingest/detect | /preview | /commit` — YouTube via `youtube-transcript-api`, Notion via the official SDK (token-only), Google Docs via the public `/export?format=txt` endpoint. Source-detection is exposed both server-side (whitelist) and client-side (instant UI badging).
- **"Preview as student" (D1):** read-only learner view of the draft course.
- **Instructor analytics (D2):** enrollment count, completion %, avg rating, recent reviews, per-lesson drop-off.

### 5.4 Learning
- Enroll / unenroll from a published course.
- Personal dashboard: in-progress courses with %, completed courses with credential links (OB3 + PDF), recent activity.
- Lesson player: renders by type; marks complete on view-or-submit. Block-doc lessons render via a tiny `BlockRenderer` that imports no editor runtime.
- Quiz attempts persisted in `quiz_attempts`; show score & per-question feedback.
- Course-level completion % = completed_lessons / total_lessons.
- **OB3 credential auto-issued at 100%**, plus PDF download as fallback. Public verifier endpoint resolves the signature offline against the issuer's published key.
- **AI tutor:** `<TutorPanel>` on every course surface, course-scoped retrieval against pgvector, inline `[L:<lesson_id>]` citations rendered as clickable pills, message-post rate-limited at 20/min per identity.
- **Review queue (E4):** FSRS-6 scheduler per `(user_id, lesson_id)` card; `/dashboard/reviews` surface with grade buttons (Again / Hard / Good / Easy — none lime, all equal-status).
- **Mastery dashboard (E7):** "what to review next" + per-skill progress + weakness signals.

### 5.5 Engagement
- Reviews: 1–5 stars + text, one per enrolled course, editable.
- Per-lesson async comments (replaced per-course WebSocket chat).
- Notifications: in-app bell + per-kind dispatch preferences in `users.notification_prefs` JSONB. Modes: `off | in_app | email_immediate | digest_daily`. Daily digest worker fires at 07:00 UTC via Celery Beat.
- **Onboarding tour (D3):** three-step interactive walkthrough on first dashboard visit (learners) or first studio visit (instructors / admins), localStorage-only persistence.

### 5.6 Admin
- Manage subjects and tags.
- Promote / demote users.
- View audit log (filterable by user, action, date range; mono+tabular-nums table).
- Feature / unfeature courses.
- Trigger embedding reindex (now actually fans out one task per published course — pre-rebuild this was a 202 no-op).

### 5.7 API
- REST + OpenAPI at `/docs`.
- Token auth (Bearer) for programmatic clients.
- Resources: subjects, tags, courses, modules, lessons, enrollments, reviews, users (self), tutor, credentials, reviews queue, notification prefs, studio/ai, studio/ingest, mastery.
- Public verify endpoint at `/api/v1/credentials/{certificate_id}/verify` (rate-limited 60/min, IP-keyed).

## 6. Non-functional requirements

| NFR              | Target |
|------------------|--------|
| API p95 latency  | < 200 ms for cached reads, < 500 ms for writes |
| Page LCP         | < 2.5 s on 4G mobile (catalog & dashboard) |
| Availability     | 99.5% (single-region single-node deploy budget) |
| Test coverage    | ≥ 80% lines on `apps/backend/app` (excluding migrations) |
| Accessibility    | **WCAG 2.2 AA — gated in CI (axe-core)** |
| Security         | OWASP ASVS L1 baseline; no critical findings in `trivy` on shipped images; secrets via `gitleaks` |
| Browser support  | Last 2 versions of Chromium, Firefox, Safari |
| RTO / RPO        | RTO 4 h, RPO 24 h (daily logical backups) |
| Container size   | Backend image ≤ 400 MB (pgvector + LLM SDKs); frontend image ≤ 350 MB |

## 7. Constraints & assumptions

- Single Postgres instance with the `pgvector` extension; no HA in v1.
- Object storage is S3-API-compatible (MinIO in dev; SES + S3 in prod).
- All services run as containers; no host-installed deps beyond Docker.
- Operator has ≥ 4 vCPU / 8 GB RAM / 50 GB disk on production host.
- LLM provider is operator-configurable (`LLM_PROVIDER=anthropic|openai|noop`); same for embedding provider (`EMBEDDING_PROVIDER=local|openai|noop`). The `noop` providers exist explicitly to support self-host deployments that cannot or do not want to call out.
- OB3 credential signing uses an Ed25519 key configured via `BADGES_SIGNING_KEY` (PEM PKCS#8); the production-readiness guard refuses to boot if `BADGES_ISSUER_URL` still points at localhost.

## 8. Open questions (carried to v1.1)

- Live video conferencing (LiveKit integration — placeholder ADR-014).
- Multi-language content (vs UI only).
- Knowledge-graph prerequisites across the catalog.
- Per-question (vs per-lesson) FSRS cards if learner feedback asks for it.
- Background-task variant of multi-modal ingest for long-form sources (Notion workspaces, PDFs).

## 9. Success metrics (post-launch)

- DAU / MAU > 0.25 within 90 days of pilot.
- Median course completion rate > 35%.
- p95 API latency under target for 28 rolling days.
- < 1 critical incident per quarter.
- NPS ≥ 30 from instructor cohort.
- **AI tutor citation rate:** ≥ 1 lesson citation on any answer grounded in course content; refusal otherwise (no hallucinated answers shipped).

## 10. Glossary

- **Course** — collection of modules taught by an instructor.
- **Module** — section within a course; contains lessons.
- **Lesson** — atomic unit of content (text / video / image / file / quiz). Text lessons store a Tiptap JSON block tree.
- **Enrollment** — a learner's link to a course; carries progress and the OB3 `badge_credential` JSONB.
- **Certificate / Credential** — proof of 100% completion. Primary form is an Open Badges 3.0 / W3C VC signed with Ed25519. PDF is a fallback download.
- **Review card** — `(user_id, lesson_id)` row carrying FSRS-6 memory state (`stability`, `difficulty`, scheduler state, `due_at`).
- **Lesson chunk** — a ~500-token sliding window of lesson text with a 384-dim embedding, stored in `lesson_chunks` with an HNSW index for sub-linear cosine search.
- **Tutor conversation** — per-(user, course) chat history with the RAG tutor, persisted across sessions.
