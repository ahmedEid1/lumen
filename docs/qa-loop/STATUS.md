# QA + Improvement Loop — running log

A persona-driven walk of the live app. Each iteration appends. Format:

```
## Iter N — YYYY-MM-DD — <short title>
**Surfaces walked:** ...
**Fixes landed:** ...
**Improvements landed:** ...
**Improvements rejected (don't re-propose):** ... (with reason)
**Open / deferred:** ...
**Commits:** ...
```

The reject ledger matters — without it, future iterations re-propose the
same things. Be specific about *why* an idea was rejected.

---

## Iter 1 — 2026-05-27 — kickoff (in flight)

**Starting point:** redesign closed Loop 20 (`4f71a4a`); eval arc closed
L41 (`572477d`) with mean=+0.93 / grounding=+2.78 on `/eval/public`. Prod
healthy at https://lumen.ahmedhobeishy.tech. Working tree clean.

**Surfaces inventoried (frontend routes):**
- Public: `/`, `/courses`, `/courses/[slug]`, `/courses/[slug]/preview/[lessonId]`, `/blog`, `/case-study`, `/demo`, `/eval`, `/eval/methodology`, `/login`, `/register`, `/forgot-password`, `/reset-password`, `/verify-email`, `/verify/[id]`, `/confirm-email-change`
- Student: `/dashboard`, `/dashboard/mastery`, `/dashboard/path`, `/dashboard/reviews`, `/dashboard/tutor/...`, `/learn/[slug]`, `/courses/[slug]/discussions/...`, `/profile`
- Instructor: `/studio`, `/studio/new`, `/studio/[id]`, `/studio/[id]/modules/[moduleId]`, `/studio/draft/[courseId]`, `/studio/draft/[courseId]/replay`
- Admin: `/admin`, `/admin/users`, `/admin/courses`, `/admin/subjects`, `/admin/tags`, `/admin/audit`, `/admin/observability`, `/admin/observability/llm-calls/[callId]`, `/admin/evals`, `/admin/evals/[suite]`, `/admin/evals/[suite]/[reportId]`

### Walk findings (raw)

**Public landing (`/`, anonymous):**
- `/favicon.ico → 404` — no favicon at all
- `/api/v1/auth/refresh → 401` fires on cold mount (AuthProvider's `refresh()` runs unconditionally, even for anonymous visitors)
- Footer "Docs" link points to `/docs` which is FastAPI's Swagger UI — misleading label for product visitors

**Catalog (`/courses`):**
- `picsum.photos` cover images flake with `ERR_CONNECTION_CLOSED` (saw it for `react-18-server-components`, `data-engineering-foundations`) — external dependency for portfolio cover art is fragile
- Title is the default `Lumen — Learn what you actually use.` — every non-`/eval` route has the same root title (per-route metadata gap)

**Demo flow (`/demo`):**
- **Major UX bug.** Headline CTA "Try the demo" redirects anonymous visitors to `/learn/typescript-variance?tutor=open&q=...` which is auth-gated. Visitors land on "Sign in to open this course" with no mention of the seeded `demo@lumen.test / Demo!2026` credentials. The README documents them but a recruiter clicking through hits a dead-end.

**Student dashboard:**
- Greeting + completion + mastery surfaces render cleanly; "0 % mastery" is honest (no quiz attempts seeded for the demo learner)
- Mobile @ 375×812 — no horizontal scroll, header 65px

**Instructor studio (`/studio`):**
- **Pluralization bug** in course-list rows: "1 students" / "1 modules" (should be "1 student" / "1 module")
- Onboarding tour appears on first load — works correctly, dismiss button labeled "Skip"
- Course editor, module editor, lesson editor, AI authoring draft replay all render without console errors

**Admin (`/admin`):**
- **Missing cards** on the admin landing: `/admin/observability` and `/admin/evals` are reachable only via direct URL (the landing's "Admin" card grid lists Subjects / Tags / Courses / Users / Audit only)
- Observability: Celery worker shows "celery inspect probe timed out" + Workers panel reads "no data" — needs follow-up (likely worker is up but the inspect RPC is slow; queue depths read 0)
- LLM Traces / Audit / Subjects / Tags / Courses / Eval admin all render with real data

### Fixes to ship this iteration

1. **`app/icon.tsx`** — proper favicon (Next.js convention, derived from Lumen mark)
2. **Per-route metadata** — `Metadata` exports on every public + auth-gated server-renderable surface; client pages get a `metadata.ts` sibling where needed
3. **Footer "Docs" → "API"** — i18n key + label change; the link still points to `/docs` but the label is now honest
4. **Pluralization helper** — `formatCount(n, "student"|"students")` (zero-cost wrapper around `Intl.PluralRules`); use it in the studio course-list + anywhere else "N items" leaks
5. **Demo-flow rescue** — `/demo` now redirects through `/login?next=...&demo=1`; the login page detects `?demo=1`, pre-fills `demo@lumen.test / Demo!2026`, and surfaces a callout: "These demo credentials are public — sign in to watch the tutor work."
6. **Admin landing missing cards** — Observability + Eval harness cards added to the `/admin` grid
7. **Course cover image fallback** — `<CourseCardImage onError>` swaps to a deterministic local SVG placeholder so picsum flakes never paint broken images

### Improvements rejected (don't re-propose)

- *Public indicator cookie + skip refresh-401 on cold mount* — touches auth semantics; would need a non-HTTP-only marker cookie alongside the refresh token so the frontend can decide whether to call `/refresh`. Per the guardrails, anything that changes auth shape is propose-don't-implement. Reason: would be the right fix but is out of scope for a QA-pass iteration. Track separately as a follow-up.

### Improvements deferred (propose, not implementing)

- **Permanent move off `picsum.photos`** — bundle a small set of cover-art SVGs and have the seed pick deterministically per course id. The onError fallback (item #7) covers the immediate console noise but the proper fix is to never depend on an external image service for portfolio cover art at all.

---

**Walk complete.** Moving to apply.

