# Loop 4 — Options

## Decision 1 — How much chrome does `<AuthCard>` own?

- **Option A: chrome only.** AuthCard renders the outer wrapper + bordered card + cartouche eyebrow + heading + subtitle. Everything inside the card (form, errors, submit button, footer links) is the page's `children`.
- **Option B: chrome + footer slot.** AuthCard takes `cartouche`, `heading`, `subtitle`, `children`, **AND** `footer`. The "forgot / sign up" and "have account? sign in" links route through the footer slot. Reduces per-page boilerplate further.
- **Option C: chrome + footer + form.** AuthCard owns the `<form>` element too; pages pass an `onSubmit` handler and the form fields go in `children`. Most aggressive collapse.

**Decision: A.** Reasons:
- The "footer" content varies non-trivially across the seven pages (forgot+signup links on `/login`; "have account?" on `/register`; nothing on the auto-confirm pages). A `footer` slot would be `undefined | one link | two links | a centred paragraph with embedded link`, which is just `children` in disguise.
- Option C couples the AuthCard primitive to a *form pattern* that doesn't apply to the four verify/confirm pages (they auto-fire on mount, no form).
- Option A's children-only approach lets every page compose its body however it wants. The collapse is in the chrome — 30 lines per page — which is enough.

## Decision 2 — Should AuthCard wire `useHydrated` itself, or expose it to the page?

- **Option A: AuthCard exposes `useHydrated`'s output via a render prop.** `<AuthCard>{({ hydrated }) => …}</AuthCard>`. Pages don't have to import the hook.
- **Option B: Pages call `useHydrated()` themselves; AuthCard stays pure presentational.** AuthCard knows nothing about the hydration gate.
- **Option C: AuthCard wraps children in a `<Suspense>` / `<HydrationGate>` boundary that internally calls `useHydrated`.** The page never sees the hook.

**Decision: B.** Reasons:
- Option A introduces a render-prop pattern that the rest of the codebase doesn't use. A single new pattern just for one primitive's hydration gate.
- Option C breaks the auto-confirm pages (`verify-email`, `confirm-email-change`) that DON'T have a submit button to gate — wrapping their content in a hydration gate would suppress the auto-fire effect.
- Option B is the most explicit: pages that need a hydration gate call `useHydrated()` and pass the result to `<Button disabled={!hydrated || submitting}>`. Pages that don't (verify/confirm) skip the hook entirely. The four existing copy-pasted paragraphs collapse to a single import + a single line each.

## Decision 3 — Re-blessing vs holding the public baselines

Migrating `/login` and `/register` to AuthCard *should* produce byte-identical DOM (same classes, same elements, same order). But Tailwind class-string ordering or whitespace differences could land a 1-pixel diff that fails `maxDiffPixels: 100`.

- **Option A: Hold strictly.** Migrate, run VR, fix any diff to be byte-identical, do NOT re-bless.
- **Option B: Re-bless if diff is purely cosmetic.** If the diff is e.g. anti-aliasing on a moved-by-one-pixel border, re-bless and call it out.
- **Option C: Always re-bless after a primitive migration.** Cheaper but loses the "did this loop drift the chrome" signal.

**Decision: A first, then B if needed.** Goal is byte-identical DOM so the existing baselines pass without re-blessing — proves the migration preserved chrome. If the diff is unavoidable (e.g. `space-y-1.5` vs `space-y-1` mismatch in one branch), re-bless explicitly and note it in the result doc.

## Decision matrix

| Concern | Decision |
|---|---|
| AuthCard scope | Chrome only (Option 1A) |
| `useHydrated` ownership | Pages call directly (Option 2B) |
| Baseline re-blessing | Hold first, re-bless if forced (Option 3A→B) |
| Codex rescue findings | Address legitimate ones in this loop's commit; queue speculative ones explicitly |
