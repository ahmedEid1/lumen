# Lumen 2.0 — Rebuild Design

| Field         | Value                                          |
|---------------|------------------------------------------------|
| Status        | Approved (autonomous-execution mode)           |
| Date          | 2026-05-22                                     |
| Branch        | `Rewrite`                                      |
| Supersedes    | `docs/product-requirements.md` v1.0            |
| Driver        | "Rethink from scratch + open visual pivot now" |

## 1. Product direction — Archetype B+

**Lumen is an AI-first OSS learning platform with a light async-cohort surface.**

This is a deliberate bet against three alternatives that the discovery surfaced:
- **A (Coursera-clone OSS LMS):** dead-on-arrival in 2026. Moodle 5.2 and Open edX with AI Course Creator V2 already do this for free.
- **B (pure AI-first):** strong but loses the social loop that drives retention.
- **C (cohort/community-led):** Maven and Skool own this; competing means rebuilding their video + payments stack.

**The defensible wedge:** there is no credible OSS AI-first LMS shipping in May 2026. Coursera Coach is on 97% of their courses and drives +9.5% quiz pass rate, +11.6% lessons/hour. Khanmigo is paywalled at $4/mo. The closest OSS option is Open edX's AI Course Creator V2 — but that is authoring-only, not tutor-grounded-on-content. Lumen wins by shipping both, self-hostable.

### 1.1 Positioning sentence

> Lumen is the self-hostable AI-first LMS for serious learners and instructors who want the platform to actually understand the course content — not just store it.

### 1.2 Primary personas (unchanged from PRD)
- **Lina (learner):** wants AI tutor + spaced rep + a credible credential
- **Tareq (instructor):** wants AI authoring + multi-modal ingest + real analytics
- **Sara (admin):** wants the same self-host simplicity Lumen already promises

## 2. Visual direction — Workbench

Linear / Raycast / Vercel-dashboard density. The previous "Skillpath" cobalt palette is replaced wholesale.

### 2.1 Token foundation

| Token | Value |
|---|---|
| Bg (dark, default) | `#0A0B0D` |
| Bg (light) | `#FAFAF9` |
| Surface layers (dark) | `#111316` / `#171A1F` / `#1E2228` |
| Surface layers (light) | `#FFFFFF` / `#F4F4F2` |
| Foreground (dark) | `#E8EAED` primary / `#9BA1AA` secondary / `#5E646C` muted |
| Hero accent | `#C8FF00` electric lime — one use per screen, never twice |
| Supporting | `#7C8FA8` cool blue-grey for instructor/metadata |
| Semantic | `#F5A524` amber / `#E5484D` red / `#46A758` green — desaturated |
| Display font | Inter Display (32–64px only, tight tracking, OFL) |
| Body font | Inter 14/20 default, compressed, OFL |
| Mono | JetBrains Mono — IDs, durations, timestamps, slugs, OFL |
| Arabic | IBM Plex Sans Arabic, OFL |
| Easing | `cubic-bezier(0.16, 1, 0.3, 1)` |
| Durations | 80 / 160 / 240ms |
| Icon family | Lucide at 16px / 1.5px stroke, max 20px in app chrome |
| Grid | 8px base, religious adherence |
| Mood | Lab-grade, alert |

### 2.2 Composition rules

- Dense functional. Catalog defaults to a table; grid is a toggle.
- Hero = working product screenshot, no mockup frame, no gradient backdrop. Headline left-aligned, 48px max.
- Borders do the elevation work — no shadows, no glass blur, no gradients.
- Skeletons pulse subtly (no shimmer sweep). Inline spinners in lime for in-place actions.
- Focus rings: 2px lime, always visible.
- Dark mode is the default. Light mode is a careful inversion, not the canonical experience.

### 2.3 What this kills
- Cobalt palette (Skillpath)
- Egyptian deity branding on the home page (Thoth / Seshat / Ptah)
- 3D tilt on hero cards
- Mesh gradients, text-shine, parallax
- Marketing-style scroll reveals

## 3. Features — kept, cut, rethought, added

### 3.1 KEEP & polish
Auth, profile, catalog, courses CRUD, modules+lessons, quizzes (with retake history), enrollments+progress, reviews, uploads, admin, i18n+RTL, soft-delete on user-visible content, the FastAPI/Next 15/Tailwind 4 stack itself.

### 3.2 CUT
| What | Reason |
|---|---|
| Bookmarks (model + UI + repo + tests) | Redundant with enrollments; UX anti-pattern |
| DiscussionSubscription | Dead delivery layer, no digest job exists |
| LessonProgress.payload | Duplicates QuizAttempt; use QuizAttempt as source of truth |
| Idempotency middleware | No payments in v1; revisit when needed |
| Duplicate-course feature | Not in PRD; instructor can create new manually |
| Per-course real-time WebSocket chat | Untested, lossy on reload, replaced by async lesson comments + AI tutor |
| PDF certificates as primary credential | Open Badges 3.0 / W3C VC is the 2026 default; PDF stays as fallback only |
| Meilisearch + worker stub | Postgres `tsvector` + GIN covers v1; pgvector later |
| Egyptian deity copy on home page | Visual orphan after Skillpath pivot |
| Lumen primitive no-op shells (Cartouche, Glyph, EyeDivider, PapyrusBg, Torchlight) | Verify and delete |

### 3.3 RETHINK
| What | New shape |
|---|---|
| Search | Postgres `tsvector` + GIN index on (title, overview, tags). pgvector for semantic later in Phase E. |
| Discussions | Replace dedicated forum with per-lesson lightweight comments + course-level AI tutor. Drop subscription. |
| Notifications | Smart digest (daily) + transactional only; per-kind user preferences. Drop bell-only theater. |
| Quizzes | Add rubric-graded short-answer (LLM-backed) and optional code grader. MCQ stays. |
| Authoring | Block-based editor (Notion-style) with AI scaffolds, replacing module → lesson → type forms |

### 3.4 ADD — 2026 table-stakes + AI moat
1. **RAG AI tutor** scoped to course content with inline lesson citations
2. **AI authoring studio** — outline → scaffolded modules + quizzes + summaries
3. **Multi-modal ingest** — paste YouTube/Notion/Docs URL → transcript + chapters + quiz
4. **Spaced-repetition review queue** (FSRS-6 scheduler)
5. **Open Badges 3.0 / W3C VC credentials** (with PDF fallback)
6. **Per-learner mastery dashboard** ("what to review next")
7. **Light gamification** — streaks, points, completion badges
8. **Instructor analytics** (PRD-promised, missing)
9. **"Preview as student"** from studio (PRD-promised, missing)
10. **Onboarding tour** (3-minute interactive)
11. **WCAG 2.2 AA hard CI gate** (April 24, 2026 deadline applies broadly)

## 4. Execution plan

Six phases. Within each phase, items run in parallel where independent, sequential where there are real dependencies. Each completed change ships as one commit with a "why" body + a CHANGELOG entry under `### Added/Fixed/Changed/Removed (rebuild phase X)`. The user is in autonomous-execution mode — no per-iteration review.

### Phase A — Cuts (parallel)
Remove what doesn't earn its keep before fixing or repainting it. ~8 independent units of work.

1. Rip Meilisearch + search worker → Postgres `tsvector` + GIN
2. Cut bookmarks (model, repo, service, API, schemas, UI, tests)
3. Delete per-course WebSocket chat (model, ws, REST, UI) — replaced later
4. Delete DiscussionSubscription model + references
5. Cut LessonProgress.payload column + migration
6. Remove idempotency middleware
7. Cut duplicate-course feature
8. Remove Egyptian deity copy from home page (placeholder pending Phase C)
9. Verify and delete dead Lumen primitive shells

### Phase B — Stop-the-bleed bug fixes (parallel, depends on A landing)
1. Progress N+1 batch query in enrollment_service
2. Rate-limit on `/certificates/verify`
3. Partial unique index on `(slug, deleted_at IS NULL)` for courses
4. Remove hardcoded test credentials from login page
5. Account-deletion revokes all refresh tokens + flags user for token rejection
6. Notification index → `(user_id, created_at)` instead of `(user_id, read_at)`
7. Add max-attempt cap + manual-reconnect UX to any remaining WebSocket consumers
8. Collapse repository pass-through layer where it adds zero value

### Phase C — Workbench visual pivot (sequential foundation, then parallel)
1. **C0 (sequential):** token foundation — `globals.css`, Tailwind config, font loading, semantic CSS variables
2. **C1 (sequential):** primitives repaint — Button, Card, Input, Select, Dialog, Tooltip, Toast, Skeleton, Badge, Tabs, Table
3. **C2 (parallel):** per-surface repaints — home (with new copy, no deity branding), catalog, course detail, learn, dashboard, studio (list/new/edit/module/lesson), admin (root/users/subjects/tags/courses/audit), profile, auth flows, system pages
4. **C3 (sequential):** dark mode default + light mode parity sweep
5. **C4 (sequential):** RTL sweep — every repainted surface tested under `dir="rtl"`

### Phase D — PRD-promised quick wins (parallel)
1. "Preview as student" mode in studio (read-only learner view of the draft course)
2. Instructor analytics page — enrollment count, completion %, avg rating, recent reviews, per-lesson drop-off
3. Onboarding tour — 3-minute interactive walkthrough on first login per role
4. Smart-digest notifications + per-kind email preferences in profile/settings
5. WCAG 2.2 AA CI gate using `axe-core` against built pages

### Phase E — AI-native differentiators (mixed)
1. **E0 (sequential):** infrastructure — pgvector extension, embedding service interface (provider-agnostic), course-content embedding pipeline triggered on publish
2. **E1 (depends on E0):** course-scoped RAG tutor — `/courses/{slug}/tutor` chat surface, retrieval + citation rendering, "ask about this lesson" CTA on the lesson player
3. **E2 (parallel with E1, after E0):** AI authoring studio — outline → modules + lessons + draft quizzes; instructor in the loop
4. **E3 (parallel after E0):** multi-modal ingest — YouTube/Notion/Google Docs URL → transcript + auto chapters + draft module skeleton
5. **E4 (independent):** FSRS-6 review queue — per-learner scheduling on completed quiz items
6. **E5 (independent):** Open Badges 3.0 issuance + verifiable JSON-LD; PDF fallback download stays
7. **E6 (depends on C primitives):** block editor for lesson body authoring, replacing free-form markdown
8. **E7 (depends on E1 + E4):** mastery dashboard — "what to review next", per-skill progress, weakness signals

### Phase F — Ship
1. Playwright E2E against `docker compose up` for all golden paths (login per role, enroll, complete lesson, post comment, take quiz, ask tutor, language switch, dark/light, mobile breakpoint)
2. Performance pass — Lighthouse on key pages, N+1 audit, cold-start benchmark
3. Updated `docs/product-requirements.md` reflecting the actual shipped scope
4. CHANGELOG version bump + tag

## 5. Acceptance criteria

For the rebuild to be considered done:
- Backend pytest green against real Postgres + Redis + (no Meili)
- Frontend vitest green
- Playwright E2E green against `docker compose up -d`
- All Phase A cuts confirmed by `git log` + `grep` showing the code is gone, not just inert
- Workbench tokens applied to 100% of frontend surfaces (no orphan cobalt or Skillpath references in CSS or copy)
- AI tutor returns answers with at least one lesson citation for any question grounded in course content
- Open Badges 3.0 credential validates against `verify.openbadges.org` (or equivalent)
- WCAG 2.2 AA axe-core check passes for landing, catalog, course detail, learn, dashboard, studio, admin
- `docker compose down && docker compose up -d` cycle reboots clean, 60s idle produces no new error logs

## 6. Out of scope (explicitly)

- Payments / Stripe (PRD non-goal preserved)
- Live video conferencing (embed Zoom/Meet if needed later)
- Native mobile apps (responsive web only)
- Multi-tenant SaaS isolation
- Marketplace / creator-economy hooks
- LTI integration (deferred)
- SCORM authoring (import only, much later)
- Knowledge graph + prerequisite detection across catalog
- White-label theming

## 7. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Phase A cuts break tests that depend on cut code | Cut migrations + test deletion are part of each cut unit; CI catches any straggler |
| Visual pivot in Phase C ships inconsistently across surfaces | Phase C2 is fan-out from a single token + primitive foundation; surfaces only repaint after primitives are stable |
| AI tutor hallucinates outside course content | Strict RAG with rejection threshold; tutor refuses if confidence < threshold instead of guessing |
| Open Badges 3.0 spec is moving | Issue a current valid VC + leave the verification URL behind a feature flag if the spec shifts |
| Token budget runs out mid-phase | Commits are per-change; resuming from any commit point produces a clean continuation |
| pgvector + embedding provider is a runtime cost | Provider interface accepts any embedding source (OpenAI/Anthropic/local); self-host can use local sentence-transformers |

## 8. Migration notes for cut features

- **Bookmarks:** existing bookmark records dropped via Alembic; no user notice (dev-only data).
- **WebSocket chat:** existing chat messages migrated to a per-lesson `LessonComment` row keyed by `(lesson_id, author_id, created_at)`. Schema documented in Phase A unit 3.
- **Meilisearch:** index drop is part of the cut; Postgres FTS is online before the cut commits.
- **PDF certificates:** existing certificate records preserved; new issuance defaults to Open Badges 3.0 with PDF as on-demand fallback.
- **Egyptian copy:** home page falls back to a placeholder during Phase A and is fully repainted in Phase C2.
