# Loop 1 — Options

Three branches for the spacing scale (the only token-set choice non-obvious enough to brainstorm). Z-index, opacity, info-colour, and motion variants are mechanical extensions of the existing pattern; they don't need three options.

## Option A — Named scale (xs / sm / md / lg / xl / 2xl / 3xl), additive

```css
--space-xs: 0.5rem;   /*  8px */
--space-sm: 1rem;     /* 16px */
--space-md: 1.5rem;   /* 24px */
--space-lg: 2rem;     /* 32px */
--space-xl: 3rem;     /* 48px */
--space-2xl: 4rem;    /* 64px */
--space-3xl: 6rem;    /* 96px */
```

- **Pros:** matches the t-shirt convention every downstream primitive (Skeleton, EmptyState, Field) already wants to consume (`<EmptyState padding="md">`). 8px-aligned by construction, no odd-unit escape hatch. Coexists with Tailwind's 4px scale — nothing has to migrate. Light footprint (~7 vars).
- **Cons:** introduces a *second* spacing vocabulary alongside Tailwind. A developer can write `p-3` (12px, off-grid) or `p-[var(--space-md)]` (24px); only social pressure stops the off-grid choice. Named scales blur the line between "use case A" and "use case B" — when does `<EmptyState padding="md">` use `--space-md` vs `--space-lg`?
- **Why it's the leading candidate:** the named scale buys component-prop ergonomics. Primitives in Loop 2 onwards take a `density="comfortable" | "compact"` prop that maps to `--space-{md,sm}`; without the named tokens, every primitive open-codes the 8px multiples.

## Option B — Numeric scale aligned to Tailwind's even units only

```css
--space-1: 0.5rem;    /*  8px == Tailwind p-2 */
--space-2: 1rem;      /* 16px == Tailwind p-4 */
--space-3: 1.5rem;    /* 24px == Tailwind p-6 */
--space-4: 2rem;      /* 32px == Tailwind p-8 */
--space-5: 3rem;      /* 48px == Tailwind p-12 */
--space-6: 4rem;      /* 64px == Tailwind p-16 */
```

- **Pros:** numeric scale is the most "designer's grid" convention. 1-indexed makes the 8px-step relationship obvious. Maps 1:1 to even Tailwind units so `p-2` and `var(--space-1)` are interchangeable mentally.
- **Cons:** the numbers don't match Tailwind's (`p-2` ≠ `--space-2` — Tailwind's 2 is 8px, ours would be 16px). Cognitive load: two scales with different "what does 2 mean". Component props read worse (`<EmptyState padding="3">` vs `<EmptyState padding="md">`).

## Option C — Zero new spacing tokens, document the 8px discipline via ESLint rule

```js
// .eslintrc — custom rule banning odd Tailwind unit suffixes
'no-odd-tailwind-spacing': 'error',
// flags p-1, p-3, p-5, p-7, p-9, p-11; allows p-0, p-2, p-4, p-6, p-8, p-10, p-12, p-16
```

- **Pros:** no token surface growth at all. Pure enforcement of the existing CLAUDE.md convention. Tailwind utilities stay the only vocabulary.
- **Cons:** writing a custom ESLint rule that understands Tailwind class extraction (from `cn(…)`, from `cva(…)`, from `className={…}`) is at least 100 LoC of fragile AST work. Doesn't solve the component-prop ergonomics — `<EmptyState padding="md">` still needs *something* to map onto. Doesn't surface the 8px discipline to anyone reading globals.css (a token list is the canonical place to document it).
- **Why rejected:** the work to ship the rule is ~3x the work to ship the named tokens, and the named tokens don't preclude adding a lint rule later.

## Decision

**Option A.** Reasons:
1. The component-prop ergonomics matter — every primitive shipping in Loops 3–6 wants `density` / `padding` / `gap` props, and t-shirt sizes read better than numbers.
2. Coexistence with Tailwind's 4px scale is a feature, not a bug — primitives lock to 8px via the scale, hand-written one-offs can still pick `p-1` if a real reason exists.
3. The named-token risk (developer writes `p-3` instead of `p-[var(--space-md)]`) is the same risk as today's "developer ignores the 8px grid", which is already convention-only. The scale doesn't make that worse; it gives the right answer a single name.

The naming "t-shirt sizes" mirrors `--font-size-{sm,base,lg}` in Tailwind's own utility set, which is the closest precedent the team will already recognise.

## Decision matrix (one-line summary)

| Concern | A (named) | B (numeric) | C (lint only) |
|---|---|---|---|
| Component-prop ergonomics | ✅ | ⚠ ("3" reads worse) | ❌ |
| Tailwind cognitive overlap | low | high (same number ≠ same px) | none |
| Implementation cost | <50 LoC | <50 LoC | ~150 LoC + ongoing |
| Migration burden | zero (additive) | zero | medium (lint flips many sites) |
| Documents the 8px discipline | yes (in globals.css) | yes (in globals.css) | only in rule config |

→ **A.**
