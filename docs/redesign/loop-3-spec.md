# Loop 3 — Spec

## File layout

```
apps/frontend/src/
├── components/ui/
│   ├── skeleton.tsx       (NEW — variants: line/text/card/image/circle)
│   ├── empty-state.tsx    (NEW — icon/title/body/cta slots)
│   ├── alert.tsx          (NEW — tones: info/success/warning/destructive)
│   ├── field.tsx          (NEW — label/hint/error wrapper)
│   ├── spinner.tsx        (NEW — sizes: sm/md/lg)
│   └── link-button.tsx    (NEW — Button asChild wrapper for next/link)
└── lib/
    └── use-hydrated.ts    (NEW — useEffect-flips-state hook)
apps/frontend/tests/
└── primitives-foundation.test.tsx  (NEW — covers all 7 above)
```

## API shapes (concrete)

### `<Skeleton variant>` — cva, shape variants

```ts
type SkeletonVariant = "line" | "text" | "card" | "image" | "circle";
interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  variant?: SkeletonVariant;
}
```

Variants:
- `line` — `h-4 w-full rounded-sm` — single bar (the most-used loading shape)
- `text` — a flex column of 3 `line` skeletons at decreasing widths (`w-full`, `w-5/6`, `w-3/4`) for prose blocks
- `card` — `h-32 w-full rounded-md` — surface placeholder
- `image` — `aspect-[16/10] w-full rounded-md` — cover image placeholder; matches `course-card.tsx:22`
- `circle` — `h-10 w-10 rounded-full` — avatar placeholder

Animation: `animate-pulse` (Tailwind's default) — *not* the custom `.skeleton` utility from globals.css. Future loop sweeps the utility class consumers; for now, the component is the new entry point.

Class composition (consumer extends via `className`):
```tsx
<Skeleton variant="image" className="w-64" />
```

### `<EmptyState>` — composed, no cva

```ts
interface EmptyStateProps {
  icon?: LucideIcon;          // optional lucide icon component (NOT element)
  title: string;
  body?: string;
  cta?: ReactNode;            // typically a <Button> or <LinkButton>
  className?: string;
}
```

Layout: centred column inside a bordered `surface` block (consumes the existing `surface` utility from globals.css). Icon renders at `h-10 w-10 text-muted-foreground/40`. Title at `font-display text-lg tracking-tight`. Body at `font-body text-sm text-muted-foreground`. Padding `p-8`.

### `<Alert tone>` — cva, tone variants

```ts
type AlertTone = "info" | "success" | "warning" | "destructive";
interface AlertProps extends HTMLAttributes<HTMLDivElement> {
  tone?: AlertTone;
  icon?: LucideIcon;
  title?: string;
}
```

Layout: bordered block with `tone`-coloured border + tone/10 background + tone foreground for the title; body at default foreground. Icon renders at `h-4 w-4 text-{tone}` (matches Badge's tone-coloured icon pattern).

Tone-to-token mapping:
- `info` → border `--info/40`, bg `--info/10`, title `--info`
- `success` → existing `--success` tokens
- `warning` → `--warning`
- `destructive` → `--destructive`

`role="alert"` on the root for `tone="destructive"`, `role="status"` for the others.

### `<Field>` — composed

```ts
interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  htmlFor: string;            // required; aligns label with input
  required?: boolean;
  className?: string;
  children: ReactNode;        // the input/textarea/select
}
```

Layout: vertical stack — label (`font-body text-sm font-medium`), child input, then hint (`text-xs text-muted-foreground`) OR error (`text-xs text-destructive`). Required mark: `*` after the label text in `text-destructive`.

When `error` is set: child input receives `aria-invalid="true"` + `aria-describedby={errorId}` automatically via `cloneElement`. When only `hint` is set: input receives `aria-describedby={hintId}`.

### `<Spinner size>` — composed, sizes

```ts
interface SpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
  "aria-label"?: string;
}
```

Sizes: `sm` = `h-3.5 w-3.5`, `md` = `h-4 w-4`, `lg` = `h-5 w-5`. Wraps lucide `Loader2` with `animate-spin`. Default `aria-label="Loading"`; caller can override.

### `<LinkButton>` — composed

```ts
interface LinkButtonProps extends Omit<ButtonProps, "asChild"> {
  href: string;
  external?: boolean;          // true → <a target="_blank" rel="noopener noreferrer">
}
```

Consumes `<Button asChild>` + Next's `<Link>`. Solves the audit's nested-interactive pattern at reset-password:92, verify-email:113, verify/[id]:105, course-detail-view:370.

Implementation:
```tsx
<Button asChild {...buttonProps}>
  {external
    ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    : <Link href={href}>{children}</Link>}
</Button>
```

### `useHydrated()` — hook

```ts
function useHydrated(): boolean
```

Returns `false` on first SSR render + first client render before useEffect runs; `true` after. Stateless, no params. Replaces:

```tsx
const [mounted, setMounted] = useState(false);
useEffect(() => setMounted(true), []);
if (!mounted) return null;
```

…across `app/login/page.tsx:47-58`, `app/register/page.tsx:34-35`, `app/forgot-password/page.tsx:30-31`, `app/reset-password/page.tsx:44-45`.

Implementation is the same shape but consolidated:
```ts
export function useHydrated(): boolean {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  return hydrated;
}
```

## State + a11y per primitive (quick table)

| Primitive | State | ARIA |
|---|---|---|
| Skeleton | none | `aria-hidden="true"` (skeletons aren't read to screen readers; the post-load content is) |
| EmptyState | none | semantic — title is `<p>`, body is `<p>` — no role needed |
| Alert | none | `role="alert"` for destructive, `role="status"` for others |
| Field | none | label `htmlFor`, child input `aria-describedby`, `aria-invalid` when `error` is set |
| Spinner | none | `role="status"` + `aria-label` (default "Loading") |
| LinkButton | none | passes through `Button` ARIA |
| useHydrated | hook | n/a |

## Token consumption

- Skeleton: `bg-muted` (existing) + animate-pulse
- EmptyState: `surface` utility, `text-muted-foreground/40`, `font-display`, `--space-` not migrated (kept Tailwind `p-8` for now — the named scale becomes mandatory only when a primitive ships a `density` prop)
- Alert (info): `border-info/40`, `bg-info/10`, `text-info` — exercises loop-1 `--info` token
- Field: `text-destructive` for required-mark + error
- Spinner: `text-current` (inherits parent colour) + `animate-spin`

No new CSS in this loop. All consumption goes through Tailwind 4 utilities from the existing `@theme inline` block (extended in Loop 1).

## Tests

One file `tests/primitives-foundation.test.tsx` covers:

1. Skeleton renders with each variant, has `aria-hidden`.
2. EmptyState renders title + body + cta + icon; no icon when undefined.
3. Alert renders each tone, has `role="alert"` only for destructive, has the loop-1 `--info` token reference in className for tone=info.
4. Field renders label + hint, applies `aria-describedby` to child input, sets `aria-invalid` when `error` is present, doesn't apply `aria-invalid` when error is missing.
5. Spinner renders with each size, has `role="status"` + `aria-label`, accepts a className override.
6. LinkButton renders as an `<a>` element with the href, `external={true}` adds `target="_blank"` + `rel="noopener noreferrer"`.
7. useHydrated starts false, flips to true after a microtask.

## Implementation order

1. `useHydrated` hook (1 file, zero deps).
2. Spinner (lucide wrap, ~25 LoC).
3. Skeleton (cva, 5 variants, ~50 LoC).
4. Alert (cva, 4 tones, ~70 LoC).
5. Field (cloneElement for ARIA wiring, ~80 LoC).
6. EmptyState (composition, ~50 LoC).
7. LinkButton (Button asChild + Link wrap, ~30 LoC).
8. primitives-foundation.test.tsx (1 file, ~280 LoC).
9. `make test.web` — expect 35 files / 168+ tests green.
10. Visual-regression re-run — expect 8/8 stable (no rendered diff since application is Loop 4).

## Binary success criteria (review checklist)

- [ ] 6 new `.tsx` files in `src/components/ui/`
- [ ] 1 new `.ts` file in `src/lib/`
- [ ] 1 new `.test.tsx` file under `tests/`
- [ ] `make test.web` green (≥161 tests)
- [ ] Visual-regression re-run: 8/8 baselines stable (zero pixel diff)
- [ ] No application of new primitives to existing surfaces this loop (Loop 4)
- [ ] STATUS.md row added; CHANGELOG `### Added (UI redesign loop 3)` entry added
