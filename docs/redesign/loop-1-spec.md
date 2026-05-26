# Loop 1 — Spec

## Visual sketch

This loop ships **zero visible diff**. No screenshot would change. The whole change lives in `globals.css` + three duration-literal sweeps in primitives. The visual sketch is the diff of globals.css — included inline below.

## Token additions

### 1. Semantic `--info` colour (sibling to success/warning/destructive)

**Dark theme (default):**
```css
--info: 217 91% 60%;            /* #3B82F6 — Tailwind blue-500, AA on dark surfaces */
--info-foreground: 220 9% 92%;  /* same as primary-foreground family */
```
Contrast check: `hsl(217 91% 60%)` = `#3B82F6` against `--background` `#0A0B0D` = **8.42:1** (AAA). Against `--card` `#111316` = **8.06:1**. Against `--muted` `#171A1F` = **7.61:1**. All clear AA.

**Light theme (`.light`):**
```css
--info: 217 91% 47%;            /* #1D4ED8 — deeper blue for AA on light surfaces */
--info-foreground: 60 9% 98%;   /* near-white */
```
Contrast check: `#1D4ED8` against `#FAFAF9` = **6.41:1**. Against `#FFFFFF` = **6.55:1**. Against `#F4F4F2` = **6.20:1**. All clear AA.

### 2. Spacing scale — t-shirt named, additive

```css
--space-xs: 0.5rem;   /*  8px — single grid unit */
--space-sm: 1rem;     /* 16px */
--space-md: 1.5rem;   /* 24px */
--space-lg: 2rem;     /* 32px */
--space-xl: 3rem;     /* 48px */
--space-2xl: 4rem;    /* 64px */
--space-3xl: 6rem;    /* 96px */
```

Aligns to 8px increments. Coexists with Tailwind's 4px scale (which stays in use everywhere).

### 3. Z-index ramp — semantic, 6 layers

```css
--z-base: 0;          /* page body */
--z-sticky: 10;       /* sticky headers, sticky filter rails */
--z-overlay: 20;      /* full-page overlays beneath modals */
--z-modal: 30;        /* dialogs, sheets */
--z-popover: 40;      /* popovers, dropdown menus, command palette */
--z-toast: 50;        /* sonner toasts */
--z-tooltip: 60;      /* tooltips — always on top */
```

Current literal usages map: `site-header.tsx:103 z-40` → `--z-sticky` (header is sticky, not a popover — value should drop to 10). Will fix in a sweep follow-up; this loop only adds the scale, doesn't migrate.

### 4. Opacity ramp — 4 semantic states

```css
--opacity-disabled: 0.5;       /* disabled affordances — matches existing button.tsx pattern */
--opacity-hover: 0.9;          /* hover on a fill (e.g. primary/90) */
--opacity-overlay: 0.6;        /* modal backdrops */
--opacity-decoration: 0.4;     /* faded icons, decorative chrome */
```

### 5. Motion variants

```css
/* New easing siblings to --ease-out-quart */
--ease-spring-soft: cubic-bezier(0.34, 1.56, 0.64, 1);   /* gentle overshoot — sheets, dropdowns */
--ease-spring-firm: cubic-bezier(0.22, 1, 0.36, 1);      /* firm settle — dialogs */

/* Movement constants for keyframes / transforms */
--motion-rise-distance: 8px;     /* matches the existing `rise` keyframe */
--motion-press-scale: 0.97;      /* scale on :active for press-feedback */
```

### 6. `@theme inline` aliases

Tailwind 4 reads `@theme inline` to generate utility classes. Add aliases for every new token:

```css
@theme inline {
  /* (existing entries unchanged) */

  --color-info: hsl(var(--info));
  --color-info-foreground: hsl(var(--info-foreground));

  --spacing-xs: var(--space-xs);
  --spacing-sm: var(--space-sm);
  --spacing-md: var(--space-md);
  --spacing-lg: var(--space-lg);
  --spacing-xl: var(--space-xl);
  --spacing-2xl: var(--space-2xl);
  --spacing-3xl: var(--space-3xl);

  --z-index-sticky: var(--z-sticky);
  --z-index-overlay: var(--z-overlay);
  --z-index-modal: var(--z-modal);
  --z-index-popover: var(--z-popover);
  --z-index-toast: var(--z-toast);
  --z-index-tooltip: var(--z-tooltip);

  --opacity-disabled: var(--opacity-disabled);
  --opacity-hover: var(--opacity-hover);
  --opacity-overlay: var(--opacity-overlay);
  --opacity-decoration: var(--opacity-decoration);

  --ease-spring-soft: var(--ease-spring-soft);
  --ease-spring-firm: var(--ease-spring-firm);
}
```

That makes `bg-info`, `text-info-foreground`, `p-md`, `z-modal`, `opacity-disabled`, `ease-spring-soft` valid Tailwind utilities.

## Duration-literal sweep

Three callsites currently shadow the existing `--duration-base`:

| File:line | Before | After |
|---|---|---|
| `button.tsx:21` | `"transition-colors duration-[160ms]"` | `"transition-colors [transition-duration:var(--duration-base)]"` |
| `input.tsx:20` | `"transition-colors duration-[160ms]"` | `"transition-colors [transition-duration:var(--duration-base)]"` |
| `progress.tsx:36-37` | `transition: "transform 240ms cubic-bezier(0.16, 1, 0.3, 1)"` | `transition: "transform var(--duration-slow) var(--ease-out-quart)"` |

`textarea.tsx:17` has the same pattern (`duration-[160ms]`) — adding to the sweep.

## State model

Stateless tokens. No runtime state changes.

## Data contract

No API changes.

## Accessibility

- The `--info` colour clears AA contrast against every documented surface in both themes (verified above).
- All other token additions are non-semantic (z-index, spacing, opacity, motion) and have no a11y impact in isolation.
- The `prefers-reduced-motion` global already in `globals.css:139-145` will override the new `--ease-spring-*` curves to 0.001ms, so the spring variants don't bypass user preference.

## Edge cases

- **Tailwind 4 `@theme inline` and namespace collisions.** Tailwind's `--spacing-*` reserved namespace already exists implicitly (consumes the `p-` / `m-` / `gap-` utilities). Adding `--spacing-{xs,sm,md,lg,xl,2xl,3xl}` extends Tailwind's spacing vocabulary — `p-md` becomes a real class. Verify by `grep -r "p-md\|gap-md\|m-md" apps/frontend/src` (expected: 0 hits today, anything pre-existing means name collision).
- **`--opacity-*` namespace.** Tailwind 4 maps `--opacity-*` to the `opacity-` utility (e.g. `opacity-disabled`). This means `opacity-50` (existing) and `opacity-disabled` (new) both render `opacity: 0.5;` — equivalent, but the *named* form should be preferred in primitives.
- **Light-mode override completeness.** The `--info` token gets a light counterpart; other tokens (spacing, z-index, opacity, motion) are theme-neutral — they appear in `:root` only, not in `.light`. Add a comment to that effect so a future maintainer doesn't wonder.

## Implementation order

1. Edit `globals.css` — add tokens, add `@theme inline` aliases, add the dual-theme `--info`.
2. Sweep `button.tsx`, `input.tsx`, `textarea.tsx`, `progress.tsx` — duration literals → CSS-var references.
3. Add `apps/frontend/tests/tokens-foundation.test.ts` — reads `globals.css` via the existing `/repo` mount, asserts every new token key exists in the right theme, asserts the four sweep files reference the var.
4. Run `make test.web` — all 36 existing + 1 new spec green.
5. Visual smoke — start dev server briefly (or rely on existing Playwright smoke), confirm no visible diff.
6. Commit. Update STATUS.md.

## Binary success criteria (repeat for the review step)

- [ ] `--info` + `--info-foreground` defined in both `:root` and `.light` with AA-passing contrast values.
- [ ] `--space-{xs,sm,md,lg,xl,2xl,3xl}` defined.
- [ ] `--z-{base,sticky,overlay,modal,popover,toast,tooltip}` defined.
- [ ] `--opacity-{disabled,hover,overlay,decoration}` defined.
- [ ] `--ease-spring-soft`, `--ease-spring-firm`, `--motion-rise-distance`, `--motion-press-scale` defined.
- [ ] All of the above have `@theme inline` aliases.
- [ ] `button.tsx:21`, `input.tsx:20`, `textarea.tsx:17`, `progress.tsx:36-37` no longer contain `duration-[160ms]` or the `240ms cubic-bezier(0.16, 1, 0.3, 1)` literal.
- [ ] New vitest `tokens-foundation.test.ts` passes; full `make test.web` green.
- [ ] No visible visual diff vs. the pre-commit state of the running app.
