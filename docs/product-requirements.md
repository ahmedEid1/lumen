# Product Requirements Document — Lumen

| Field         | Value                              |
|---------------|------------------------------------|
| Status        | Approved for v1.0                  |
| Owner         | @ahmedEid1                         |
| Last updated  | 2026-05-21                         |
| Target launch | 2026-Q3                            |

## 1. Problem statement

The original `E-Learning-Platform` was a Django prototype demonstrating CRUD courses, drag-and-drop modules, and a tiny chat. It lacked authentication beyond Django sessions, had no progress tracking, no search, no quizzes, no certificates, no observability, no containerization, and could not scale beyond a single demo instance. It also used a single SQLite file and ran without tests.

Educators on the original platform asked repeatedly for: durable user accounts they could share with cohorts, assessments that auto-grade, a way to see how far students have progressed, and a mobile-friendly UI. Independent learners asked for a public catalog that they could browse without an account, search across courses, and pick up where they left off.

**Lumen** is the rewrite that solves these problems while preserving the original features (courses, modules, polymorphic content, drag-drop ordering, chat, REST API).

## 2. Vision

> A self-hostable, accessible, modern LMS that an instructor can stand up in fifteen minutes with `docker compose up` and that scales to thousands of learners with the same artifacts.

## 3. Users & personas

### 3.1 Learner (Lina, 24, junior developer)
- Discovers courses via public catalog or search
- Enrolls free; sees personal dashboard with in-progress courses
- Watches/reads lessons; quiz answers are graded immediately
- Chats with classmates and instructor in course room
- Receives a certificate when complete

### 3.2 Instructor (Tareq, 38, university lecturer)
- Builds courses with modules and lessons (text / video / image / file / quiz)
- Reorders modules and lessons by dragging
- Publishes drafts when ready
- Sees per-student progress, quiz scores, and reviews
- Answers questions in the course chat

### 3.3 Admin (Sara, platform operator)
- Manages subjects, tags, featured courses
- Grants/revokes instructor permission
- Reviews abuse reports and audit log
- Monitors system health via dashboards

## 4. Goals & non-goals

### Goals (v1.0)
1. Feature parity with the legacy app (courses, modules, polymorphic content, drag-drop ordering, chat, REST API).
2. Modern authentication (JWT + refresh, password reset, optional OAuth).
3. Public catalog with search, filters, ratings.
4. Per-lesson progress tracking and course-level completion %.
5. Quizzes (MCQ + short-answer) with auto-grading.
6. Reviews & ratings (1–5 stars + free text).
7. Real-time chat per course with history and presence.
8. File uploads via S3-compatible storage.
9. Email notifications (account, enrollment, completion).
10. Certificates (PDF) on 100% completion.
11. Accessibility: WCAG 2.2 AA across all learner-facing pages.
12. Fully containerized; `docker compose up` → working dev env.
13. CI on every PR; production-ready Docker images for deploy.
14. ≥ 80% line coverage on backend domain modules; smoke E2E for golden paths.

### Non-goals (v1.0 — explicitly out of scope)
- Payments (architecture leaves room for Stripe; no integration shipped).
- Live video conferencing (chat only).
- Mobile native apps (responsive web is sufficient).
- Multi-tenant SaaS isolation (single-tenant install).
- Advanced LRS / xAPI integration.
- AI-generated content (separate roadmap).

## 5. Functional requirements

### 5.1 Identity & access
- Register with email + password; verification email.
- Login returns short-lived JWT access (15 min) + rotating refresh (14 d, httpOnly cookie).
- Password reset via email link (30 min TTL).
- Roles: `student` (default), `instructor`, `admin`. RBAC enforced server-side.
- Admin can promote a user to instructor.
- Logout invalidates the refresh token server-side.
- Account: profile edit, avatar upload, change password, export data (GDPR), delete account.

### 5.2 Catalog & discovery
- Public landing with featured courses and subject grid.
- `/courses` list with: subject filter, tag filter, difficulty filter, free-text search, sort (newest / most popular / top rated).
- Course detail page: overview, syllabus (modules → lessons), instructor card, reviews, enroll CTA.
- Search powered by Meilisearch; index updates on publish.

### 5.3 Authoring (instructor studio)
- Create course (title, slug, subject, tags, difficulty, overview, cover image).
- Course states: `draft`, `published`, `archived`.
- Modules: title, description, order. Drag-drop reorder.
- Lessons: title, type (`text` | `video` | `image` | `file` | `quiz`), order. Drag-drop reorder.
- Lesson content forms are type-specific (e.g. quiz editor with questions + choices).
- Preview as student.
- Instructor analytics: enrollment count, completion %, avg rating, recent reviews.

### 5.4 Learning
- Enroll/unenroll from a published course.
- Personal dashboard: in-progress courses (with %), completed courses, bookmarks.
- Lesson player: renders by type; marks complete on view-or-submit.
- Quiz attempts persisted; show score & per-question feedback.
- Course-level completion % = completed_lessons / total_lessons.
- Certificate auto-issued at 100% and downloadable as PDF.

### 5.5 Engagement
- Reviews: 1–5 stars + text, one per enrolled course, editable.
- Per-course chat room: history persisted, presence list, typing indicator.
- Notifications: in-app bell + email for (enrolled, lesson available, certificate ready, review received).

### 5.6 Admin
- Manage subjects and tags.
- Promote/demote users.
- View audit log (filterable by user, action, date range).
- Feature/unfeature courses.

### 5.7 API
- REST + OpenAPI at `/docs`.
- Token auth (Bearer) for programmatic clients.
- Resources: subjects, tags, courses, modules, lessons, enrollments, reviews, users (self).

## 6. Non-functional requirements

| NFR              | Target |
|------------------|--------|
| API p95 latency  | < 200 ms for cached reads, < 500 ms for writes |
| Page LCP         | < 2.5 s on 4G mobile (catalog & dashboard) |
| Availability     | 99.5% (single-region single-node deploy budget) |
| Test coverage    | ≥ 80% lines on `apps/backend/app` (excluding migrations) |
| Accessibility    | WCAG 2.2 AA |
| Security         | OWASP ASVS L1 baseline; no critical findings in `trivy` on shipped images |
| Browser support  | Last 2 versions of Chromium, Firefox, Safari |
| RTO / RPO        | RTO 4 h, RPO 24 h (daily logical backups) |
| Container size   | Backend image ≤ 350 MB, frontend image ≤ 250 MB |

## 7. Constraints & assumptions

- Single Postgres instance; we do not require HA in v1.0.
- Object storage is S3-API-compatible (MinIO in dev; SES + S3 in prod).
- All services run as containers; no host-installed dependencies beyond Docker.
- Operator has ≥ 4 vCPU / 8 GB RAM / 50 GB disk on production host.

## 8. Open questions

- Should certificates carry blockchain verification? *Deferred to v1.1.*
- Multi-language content (vs UI only)? *Deferred to v1.1; data model leaves room.*
- LiveKit integration for video? *Tracked as ADR-014 placeholder.*

## 9. Success metrics (post-launch)

- DAU / MAU > 0.25 within 90 days of pilot.
- Median course completion rate > 35%.
- p95 API latency under target for 28 rolling days.
- < 1 critical incident per quarter.
- NPS ≥ 30 from instructor cohort.

## 10. Glossary

- **Course** — collection of modules taught by an instructor.
- **Module** — section within a course; contains lessons.
- **Lesson** — atomic unit of content (text/video/image/file/quiz).
- **Enrollment** — a learner's link to a course; carries progress.
- **Certificate** — proof of 100% completion, PDF.
