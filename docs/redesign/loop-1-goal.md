# Loop 1 — Goal

**Establish the design-token scale that the next 19 loops will reference, without changing a single pixel a user can see.**

Per AUDIT.md §1, the Workbench tokens are strong as colour + radius + 3 durations, but everything else (spacing, z-index, opacity, semantic info, motion variants) is convention-only — relied on Tailwind defaults or hard-coded literals like `z-50`, `/90`, `duration-[160ms]`. This loop adds the named scale so every subsequent primitive / surface / chart can spell its intent.

- **Surface:** `apps/frontend/src/styles/globals.css` (token additions + `@theme inline` aliases) plus three sweep targets — `apps/frontend/src/components/ui/button.tsx:21`, `input.tsx:20`, `progress.tsx:36-37` — where motion duration literals shadow the existing `--duration-base` var.
- **Persona:** the next future agent / maintainer who opens any UI file. They should never have to invent a z-index, pick a "what's hover opacity again", or copy-paste `cubic-bezier(0.16, 1, 0.3, 1)` into a one-off transform.
- **Binary success criteria:**
  1. `globals.css` exports `--info` + `--info-foreground` semantic colour, an 8-step `--space-*` named scale, a 7-step `--z-*` ramp, a 4-step `--opacity-*` ramp, two spring easing curves, and two motion-variable constants for rise distance + press scale.
  2. All new tokens have `@theme inline` Tailwind aliases (`color-info`, `z-index-modal`, `opacity-disabled` etc.) so callsites can spell them as utility classes.
  3. Light-mode counterparts derived where the dark value isn't already neutral.
  4. AA contrast for the new `--info` token verified in both themes (≥4.5:1 against the surface it's used on).
  5. `button.tsx:21`, `input.tsx:20`, `progress.tsx:36-37` reference `var(--duration-base)` / `var(--ease-out-quart)` instead of `duration-[160ms]` / `240ms cubic-bezier(0.16, 1, 0.3, 1)` literals.
  6. A new regression vitest `tests/tokens-foundation.test.ts` reads `globals.css` and asserts every token in the spec exists, plus the three sweep targets contain `var(--duration-base)` not the literal.
  7. `make test.web` green; existing 36 vitest specs unaffected; existing 10 Playwright specs unaffected (this is a no-visible-diff loop).
  8. **Zero visible visual diff** — viewing the running app pre/post should be byte-identical for a casual user. Token additions are dormant until consumed.

Out of scope for this loop:
- Playwright visual-regression baseline (Loop 2).
- Typography scale tokens — current Tailwind utilities are fine; defer until a later loop needs them.
- Light-mode lime redesign (`globals.css:62-68`) — that's its own loop in the sequence (loop 7 per AUDIT.md §7).
- Spacing-token migration of existing utilities (`gap-4` → `gap-[var(--space-sm)]`). The scale is *added* this loop; *adoption* is incremental.
