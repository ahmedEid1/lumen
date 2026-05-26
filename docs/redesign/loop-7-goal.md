# Loop 7 — Goal

**Make light mode a designed theme, not an axe-suite escape hatch.** Fix the broken surface ramp (current deltas are 2-3% lightness — invisible elevation), pull Sonner's `theme="dark"` pin off by giving sonner a real light palette via the Workbench tokens, and capture the two light-mode auth-gated baselines that Loop 6 had to skip.

The audit's exact words (AUDIT.md §1, also globals.css:62-68 self-flag):
> Light mode is currently an axe-suite escape hatch, not a designed theme — `globals.css:62-68` admits the lime was bumped to clear AA, Sonner is pinned `theme="dark"` because the light palette failed axe, surface ramp is flat.

This loop closes that critique. What it does NOT do (per the options doc): retune the lime accent to feel electric in light. That's a token-architecture rewrite (adding `--primary-bright` + migrating every `bg-primary` callsite) and the visual payoff isn't worth the surface area of the change — light mode reads "operator-deep" rather than "operator-electric" by design. Workbench's electric vibe is dark-mode's signature; light mode is the "professional / printable / shared-screen" companion.

- **Surface:**
  - `apps/frontend/src/styles/globals.css` — rewrite the `.light` block's surface ramp + border; add sonner-targeting CSS overrides in `@layer base` that consume Workbench tokens for each `data-type` (default/success/warning/error/info).
  - `apps/frontend/src/app/layout.tsx` — drop the `theme="dark"` pin on `<Toaster />`.
  - `apps/frontend/tests/e2e/visual-regression.spec.ts` — un-skip the 2 light auth-gated routes deferred in Loop 6 (the root cause may or may not be resolved by the surface-ramp change; verify and decide).
  - Re-bless 4 public light baselines + 2 dark public baselines (anything that consumes `--border` will diff), + capture the 2 deferred auth-gated light baselines, + re-bless the 4 existing auth-gated baselines.
  - Update `loop-1-spec.md` referenced AA contrast numbers if the new ramp changes which surface a token contrasts against.

- **Persona:** a portfolio reviewer toggling the theme. Pre-loop-7 they see a "deflated" app — borders invisible, hierarchy unreadable, toasts pinned to dark. Post-loop-7 they see a real designed light theme.

- **Binary success criteria:**
  1. New `.light` surface ramp has visible elevation deltas (`surface-3` and `border` ≥ 10% lightness below `card`).
  2. Sonner toaster in `layout.tsx` is unpinned (no `theme="dark"` attr).
  3. Sonner toasts under `.light` clear axe-core WCAG 1.4.3 for success / warning / error / info types (each one's foreground vs. background ≥ 4.5:1).
  4. The 2 deferred auth-gated light baselines (dashboard-light, admin-light) either capture stably under the new ramp OR remain documented as deferred with a more specific root-cause hypothesis.
  5. Re-blessed light baselines committed; dark baselines unchanged.
  6. `make test.web` green (no new tests this loop; existing pass).
  7. STATUS.md row 7 + CHANGELOG `### Added (UI redesign loop 7)`.
  8. Codex rescue #2 invoked against loops 4–7 via `codex review --commit <SHA>` per-loop (workaround for the `--base` grammar prompt-rejection). Digest at `docs/redesign/codex-review-loops-4-to-7.md`; legitimate findings addressed.

Out of scope:
- Adding a new `--primary-bright` token / migrating `bg-primary` callsites. Light mode stays "operator-deep" by design (Workbench's electric is the dark-mode signature).
- Light-mode typography re-tuning. Inter at the current sizes reads fine on white.
- Migrating `text-yellow-500/15` or any pre-existing raw Tailwind hue that's still pre-Loop-5. Those got swept in Loop 5; this loop touches only `.light` block + sonner.
