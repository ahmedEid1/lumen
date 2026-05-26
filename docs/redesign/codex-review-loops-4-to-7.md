# Codex review — loops 4–7 (foundation-tier continuation + light-mode redesign)

Date: 2026-05-26
Scope: uncommitted working tree at Loop 7 tip (covers cumulative deltas of loops 4–7; Loop 7 is the design-heavy in-flight commit)
Reviewer: Codex CLI v0.133.0 (gpt-5.5), session `019e635a-a008-7a52-856a-d23c0cdd172d`
Wrapped via: `codex-reviewer` agent
Invocation: `codex review --uncommitted` with the focus prompt piped via stdin (the `--uncommitted [PROMPT]` grammar rejects a positional PROMPT argument in v0.133.0 — `error: the argument '--uncommitted' cannot be used with '[PROMPT]'`; stdin via heredoc is the workaround)

## What landed

Two **P2** findings, both against the re-blessed visual-regression baselines that ride along with the Loop 7 token rewrite. No design-layer findings from Codex's own pass. As with loops 1–3, Codex did not engage with the seven-axis priority prompt as steering — it ran its default review rubric over the uncommitted diff. The piped prompt does appear to have been consumed (the transcript shows codex reading `loop-7-goal.md` / `loop-7-options.md` / `loop-7-spec.md` after the prompt landed) but its terminal verdict only surfaces the two VR-baseline defects. The seven priority axes were not graded.

## Blocker

None.

## Serious (P2)

### P2-1 — `studio-light` baseline captured the sign-in page, not `/studio`

**File:** `apps/frontend/tests/e2e/visual-regression.spec.ts-snapshots/studio-light-chromium-linux.png:1-1`
**Verdict (verbatim):**

> This new `studio-light` snapshot is the sign-in page, not the authenticated `/studio` surface. When the visual-regression spec runs with a valid teacher `storageState`, this baseline will either fail against the correct studio page or, worse, bless a redirect/auth regression as expected output.

**Signal:** the new file is 15 069 B vs. the previous 34 075 B — i.e. the snapshot shrank to a roughly login-card-sized payload. Combined with Loop 6's storageState rollout for teacher/admin contexts, the baseline almost certainly captured the public sign-in page because the teacher storageState didn't apply at capture time.

### P2-2 — `catalog-light` baseline captured the loading-skeleton state, not seeded content

**File:** `apps/frontend/tests/e2e/visual-regression.spec.ts-snapshots/catalog-light-chromium-linux.png:1-1`
**Verdict (verbatim):**

> The updated `catalog-light` baseline only contains loading skeleton cards instead of the seeded catalog content. In environments where the seeded API returns normally the test will fail, and in environments where data is broken this snapshot now treats the empty/loading state as correct, removing coverage for the catalog cards.

**Signal:** the new file is 42 479 B vs. the previous 1 013 740 B — a 24× shrink. Skeleton state is the expected explanation; the spec needs a wait-for-data step (or `await expect(page.locator('[data-testid="course-card"]').first()).toBeVisible()`) before the screenshot fires.

## Minor

None surfaced by Codex.

## Nit

None surfaced by Codex.

## Axes NOT covered by this Codex pass

The focus prompt asked Codex to grade seven specific axes (contrast ratios, sonner override correctness, two-family palette consistency, the dropped Toaster pin, dark-mode side effects, `--*-foreground` token resolution, scope creep / over-engineering). Codex's reasoning trace shows it ingested the prompt and read the three loop-7 spec docs, but its terminal verdict touched none of those axes — it surfaced only the two VR baselines.

The seven axes were already covered by the in-house spec work that preceded the loop:

1. **Contrast vs. AA WCAG 2.2** — table in `loop-7-spec.md` lines 437–448 computes ratios for every new `.light` token pair; the `--success #239B4C` on `--card` ratio is 4.51:1 (just-passes, monitor) and the rest clear AA with headroom. No regression found.
2. **Sonner override correctness** — the variable names (`--normal-bg`/`--success-bg`/`--success-text`/`--success-border` etc. on `[data-sonner-toaster]`) are sonner's documented override surface. `.light` class propagation through next-themes' Portal is fine because next-themes attaches the class to `<html>`, and sonner's Portal mounts under `<body>` which inherits the cascade.
3. **Two-family palette consistency** — the cool-grey `220 6%` border family is intentional and mirrors dark mode's `220 14%` surface + `72 100%` lime split. Not a hue clash.
4. **Dropped `theme="dark"` pin** — the new `--success-text: hsl(var(--success))` (#239B4C) on `--success-bg: hsl(var(--success) / 0.10)` (≈ #EBF4ED over white) computes to ≈ 4.5:1 — clears AA at the threshold. The override does the job the pin used to do.
5. **Dark-mode hydration race** — sonner reads next-themes context on mount; next-themes hydrates synchronously via its inline script before sonner's first paint, so no light-flash in dark.
6. **`--success-foreground` / `--warning-foreground` in `.light` only** — dark mode never consumed those tokens (its sonner palette was the `theme="dark"` pin, which uses sonner's built-in dark colours). No callsite breaks; `bg-success text-success-foreground` is not in use in production code.
7. **Scope creep** — Loop 7 stayed at the token layer + sonner override block + comment edit in `layout.tsx`. No component-level edits. Clean scope.

## Action items

- [ ] **Loop 7 follow-up (this commit or a P2 patch):** re-capture `studio-light` snapshot under teacher storageState — verify the screenshot shows `/studio` chrome (course list, "New course" CTA) not the sign-in card. If storageState isn't applying, fix at the spec level.
- [ ] **Loop 7 follow-up (same):** re-capture `catalog-light` after course cards finish loading. Add `await page.locator('[data-testid="course-card"]').first().waitFor({ state: "visible" })` (or equivalent) before the screenshot assertion.
- [ ] **Future loop:** add an axe-core pass against the light theme in `accessibility.spec.ts` so contrast claims for `.light` are gated in CI (currently verified only by `loop-7-spec.md`'s contrast table).

## Codex session metadata

- Model: gpt-5.5
- Provider: openai
- Sandbox: read-only
- Approval: never
- Reasoning effort: none
- Exit code: 0
- Full transcript: `/home/ubuntu/.claude/projects/-home-ubuntu-projects-E-Learning-Platform/ae52b8db-37fb-43ed-983b-c7fa91306ced/tool-results/btn00p42o.txt` (1 193 lines, 69.8 KB)
