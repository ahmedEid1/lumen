# Loop 19.5 — founding story + empty blog index

**Date:** 2026-05-27
**Scope:** README opener replacement + `/blog` route (empty)

## What shipped

### README opener

Replaced the one-line tagline at the top of `README.md` with the V6-F6
locked founding paragraph (planning session 2026-05-26, plan-v7). The
existing tagline "An open-source, AI-first LMS built as a portfolio
anchor for agentic-AI engineering work" now sits below as the italic
subtitle, then badges as before.

Locked text (`~85 words`):

> Lumen started in late 2020 as a Django side-project — a learning
> platform for myself. Five years and one model revolution later, the
> original prototype is gone and what remains is the question: can an
> agent actually teach? Not just summarize and quote. So I rebuilt it.
> Custom orchestrator, no LangChain. Groq Llama 3.3 for the
> latency-per-dollar that makes "watch it think" real. Public evals so
> you can audit the agent's competence yourself.
>
> — *Ahmed Hobeishy*

Year (2020) verified against `git log --reverse` → first commit
`2020-11-29 19:30`. The "five years" framing rounds down from 5.5y on
purpose for cadence; owner confirmed this exact wording before insert.

### `/blog` route

New surface at `apps/frontend/src/app/blog/page.tsx`. Server component
exporting `Metadata` (OG card + description) that delegates to the
client `blog-index.tsx`. The client child renders the same section
header pattern as `/courses` (cartouche + h1 + subline) and a single
`<EmptyState>` (lucide `FileText` icon, locked "No posts yet." copy
explaining that case-study posts arrive with L30).

Why empty now: the redesign closed at L20, but the post-redesign
roadmap defers actual blog posts until L30 (case study) so external
distribution can link to a stable URL once the case study + screencap
ship. Crawlable today via `sitemap.ts` (added `/blog` at priority 0.5,
weekly).

### i18n + tests

- New keys: `blog.cartouche`, `blog.title`, `blog.subline`,
  `blog.empty.title`, `blog.empty.body` — added to `en.ts` and `ar.ts`
  (728 → 733 keys each). `i18n-parity.test.ts` green.
- New spec `tests/blog-page.test.tsx` — 2 tests covering the section
  header + EmptyState.
- Suite: **51 files / 286 tests green** (+1 file / +2 tests over
  loop-20 baseline of 50 / 284).

### Sitemap

`/blog` added to the `staticRoutes` list in `apps/frontend/src/app/sitemap.ts`
between `/courses` and the dynamic course enumeration. Priority 0.5,
weekly. No RSS feed shipped — `feed.xml` lands with L30 once posts
exist; doing it now would just be an empty `<channel>`.

## What did NOT ship (and why)

- **RSS feed** — deferred to L30 (nothing to syndicate yet).
- **Navigation link to `/blog`** — deferred. Adding it to the site
  header now would invite users into an empty page. The route is
  reachable via direct URL + sitemap; we'll wire it into the nav once
  the first post lands.
- **Per-post template** (`/blog/[slug]/page.tsx`) — same reason; lands
  with the first post.

## Verification

- `pnpm exec eslint src/app/blog src/lib/i18n/messages tests/blog-page.test.tsx` — clean
- `pnpm exec tsc --noEmit --incremental false` — clean
- `pnpm exec vitest run` — 51 files / 286 tests green
- `pnpm exec vitest run tests/i18n-parity.test.ts` — 2/2 green

Per LOCAL-FIRST: holding this commit on the local branch and bundling
the push with L20.5 (TS course + `/demo` route + ADRs) so one CI cycle
covers both. L20.5 starts next.

## Files

- `README.md` (modified — opener + subtitle)
- `apps/frontend/src/app/blog/page.tsx` (new)
- `apps/frontend/src/app/blog/blog-index.tsx` (new)
- `apps/frontend/src/app/sitemap.ts` (modified — +`/blog`)
- `apps/frontend/src/lib/i18n/messages/en.ts` (+5 keys)
- `apps/frontend/src/lib/i18n/messages/ar.ts` (+5 keys)
- `apps/frontend/tests/blog-page.test.tsx` (new)
- `docs/post-redesign/STATUS.md` (new — ledger file)
- `docs/post-redesign/loop-19.5.md` (this file)
- `CHANGELOG.md` (modified — new Unreleased entry)
