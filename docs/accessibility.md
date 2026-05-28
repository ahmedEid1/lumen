# Accessibility

## What we're gated on

Lumen ships behind a hard CI gate at **WCAG 2.2 Level AA**. The
April 24 2026 effective date applies broadly to consumer-facing
digital products, so this is a release blocker, not a soft check.

The gate is implemented as a Playwright suite that drives
[`@axe-core/playwright`](https://github.com/dequelabs/axe-core-npm/tree/develop/packages/playwright)
against the built Next.js app on every PR and on every push to
`main`. Workflow: the `accessibility` job in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
Tests:
[`apps/frontend/tests/e2e/accessibility.spec.ts`](../apps/frontend/tests/e2e/accessibility.spec.ts).

## Routes audited

| Route                  | Auth         |
|------------------------|--------------|
| `/`                    | logged out   |
| `/courses`             | logged out   |
| `/login`               | logged out   |
| `/register`            | logged out   |
| `/forgot-password`     | logged out   |
| `/courses/{slug}`      | logged out   |
| `/dashboard`           | student      |
| `/profile`             | student      |
| `/studio`              | instructor   |
| `/admin`               | admin        |

The auth flows use the seeded demo accounts (`student@lumen.test`,
`teacher@lumen.test`, `admin@lumen.test`; passwords in `CLAUDE.md`).
The course-detail test picks the first seeded course dynamically so
it stays green if `make seed` slugs change.

## Tags

The audit chains the WCAG ladder up to 2.2 AA:

```
wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa
```

`best-practice` rules are **not** in the gate — they're useful
signal but were never part of the AA conformance contract. If you
want to see them locally, edit `WCAG_TAGS` in `accessibility.spec.ts`.

## Run locally

The suite needs the full dev stack (web + api + db + seeded data),
because the authed routes require real users:

```bash
make up
# wait for the stack to settle (~30s on a cold start)
make migrate
make seed
make a11y
```

`make a11y` runs the same `accessibility.spec.ts` file inside the
`e2e` compose profile, pinned to Chromium (axe's rules are
browser-agnostic, so running across Chromium + WebKit would double
wall-clock for no extra signal).

To iterate on a single failing test without the full stack
overhead, you can also run from the host once `make up` is live:

```bash
cd apps/frontend
pnpm exec playwright test tests/e2e/accessibility.spec.ts --project=chromium --grep "course detail"
```

## Reading a failure

The custom matcher in `accessibility.spec.ts` prints one block per
violation:

```
[serious] color-contrast — Elements must meet minimum color contrast ratio thresholds
  rule:    https://dequeuniversity.com/rules/axe/4.10/color-contrast
  tags:    wcag2aa, wcag143
  nodes:
    - target: ["a.text-muted-foreground"]
      html:   <a class="text-muted-foreground" href="/about">About</a>
      why:    Expected contrast ratio of 4.5:1, but found 3.5:1
```

Three things to triage:

1. **rule** — the Deque docs page explains the rule, what passes,
   what doesn't, and common false positives.
2. **target** — the CSS selector path inside the page. Open
   DevTools, paste into `document.querySelector(...)`, and you've
   got the offending element.
3. **why** — the human-readable failure summary. For contrast
   issues it includes the actual vs. required ratio so you can
   pick the next-darker token without guessing.

When CI fails, the workflow uploads `playwright-report/` and
`test-results/` as an artifact (`playwright-axe-report`) — screenshots
and traces are in there.

## Light-mode primary token (Phase G1)

The light-mode `--primary` token in
`apps/frontend/src/styles/globals.css` is **`hsl(75 80% 25%)`** =
`#59730D` — a deeper sibling of the dark-mode electric lime
(`hsl(72 100% 50%)` / `#C8FF00`). The deeper shade is forced by
WCAG 2.2 AA: the dark-mode lime against the light-mode surfaces
(`#FAFAF9`, `#FFFFFF`, `#F4F4F2`) yields only 2.44 / 2.54 / 2.33
contrast, well below the 4.5:1 floor for body text. The new value
clears the bar with margin:

| Surface              | Hex       | Contrast | Verdict |
|----------------------|-----------|----------|---------|
| Background           | `#FAFAF9` | 5.21:1   | AA pass |
| Card                 | `#FFFFFF` | 5.42:1   | AA pass |
| Muted                | `#F4F4F2` | 4.98:1   | AA pass |

`--primary-foreground` flips to `hsl(60 9% 98%)` in light mode so
`bg-primary text-primary-foreground` buttons still pass AA
(5.21:1 white-on-green). `--ring` follows `--primary`.

**Do not touch the dark-mode `--primary`** — `hsl(72 100% 50%)` is
the Lumen signature lime and reads correctly against the
near-black dark surfaces. The two values are intentionally
different shades of the same green family; they are not derived
from each other and should not be unified.

## When you find a violation

**Default: fix it.** That's why the gate exists. Most violations
trace back to a token (insufficient contrast on a muted text
colour, focus-ring opacity too low) or a primitive (missing
`aria-label` on an icon-only button); fixing the primitive fixes
every surface that uses it.

If a rule needs to be temporarily suppressed during triage:

- Scope the suppression to the *single test* that surfaces it, via
  `new AxeBuilder({ page }).withTags(WCAG_TAGS).disableRules(["rule-id"])`.
- Leave a `// TODO(a11y): <issue-link>` next to the disable.
- Open a tracking issue immediately. We do not maintain a
  long-lived ignore list — the gate is only useful if violations
  are loud.

## Why no separate ignore file

Two reasons:

1. An ignore list grows. A monorepo with three roles and ten
   golden-path routes can rack up dozens of "temporary" exclusions
   in a quarter, and at that point the gate stops gating anything.
2. WCAG 2.2 AA is the floor, not a stretch goal. If a rule is
   genuinely wrong for our app (e.g. a known axe false positive on
   a third-party iframe), suppressing it inline with a code review
   trail is more honest than adding a JSON list nobody reviews.
