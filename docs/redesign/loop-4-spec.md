# Loop 4 — Spec

## Visual sketch

Byte-equivalent to today's auth chrome (deliberately):

```
+--------------------- (mx-auto max-w-[440px] px-6 py-20) --------------------+
|                                                                            |
|   +------------ (rounded-md border border-border bg-card p-8) ----------+   |
|   |                                                                    |   |
|   |   AUTH.CARTOUCHE.KEY   (mono uppercase muted, mb-6)                |   |
|   |                                                                    |   |
|   |   Heading (font-display text-3xl tracking-tight)                   |   |
|   |   Subtitle (font-body text-sm text-muted-foreground, mb-7)         |   |
|   |                                                                    |   |
|   |   {children}                                                       |   |
|   |                                                                    |   |
|   +--------------------------------------------------------------------+   |
+----------------------------------------------------------------------------+
```

## AuthCard API

```ts
interface AuthCardProps {
  cartouche: string;            // mono-uppercase eyebrow text
  heading: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;           // applied to the OUTER wrapper (rarely needed)
}
```

## File layout

```
apps/frontend/src/components/ui/
└── auth-card.tsx                          (NEW — ~50 LoC)

apps/frontend/tests/
└── auth-card.test.tsx                     (NEW — ~80 LoC)

apps/frontend/src/app/
├── login/page.tsx                         (-30 / +15 LoC, net -15)
├── register/page.tsx                      (-30 / +15)
├── forgot-password/page.tsx               (-30 / +15)
├── reset-password/page.tsx                (-30 / +15)
├── verify-email/page.tsx                  (-25 / +12)
├── verify/[id]/page.tsx                   (-25 / +12)
└── confirm-email-change/page.tsx          (-25 / +12)

apps/frontend/tests/e2e/
├── visual-regression.spec.ts              (re-add auth-gated ROUTES, +6 lines)
└── visual-regression.spec.ts-snapshots/
    ├── dashboard-{dark,light}-chromium-linux.png   (NEW — 2 baselines)
    ├── profile-{dark,light}-chromium-linux.png     (NEW — 2 baselines)
    ├── studio-{dark,light}-chromium-linux.png      (NEW — 2 baselines)
    └── admin-{dark,light}-chromium-linux.png       (NEW — 2 baselines)
```

Net code: roughly **−180 LoC across the seven page migrations**, **+50 LoC for AuthCard**, **+80 LoC for the test**, **+8 binary baselines**. Comfortably under the 2000-line cap.

## Migration recipe per page

1. Replace the outer `<div className="mx-auto flex w-full max-w-[440px] flex-col px-6 py-20"><div className="rounded-md border border-border bg-card p-8">…cartouche…header…</div></div>` with `<AuthCard cartouche={t(...)} heading={t(...)} subtitle={t(...)}>`.
2. Replace `const [mounted, setMounted] = useState(false); useEffect(() => setMounted(true), []);` with `const hydrated = useHydrated();`.
3. Update submit button `disabled={submitting || !mounted}` → `disabled={submitting || !hydrated}`.
4. If the page wraps a `<Button>` inside `<Link>`, convert to `<LinkButton>`.

## A11y

`<AuthCard>` is presentational. The page-level h1 lands inside the card; no role assignment needed. The mono cartouche stays a plain `<p>` (it's metadata for sighted users; screen-reader users hear the heading and don't need the eyebrow).

## Visual regression strategy

- Loop 2's existing 8 baselines run first. If `login` or `register` diffs (purely a class-order or whitespace artefact of the migration), inspect, and re-bless explicitly. If anything ELSE diffs, that's a real regression — fix the migration, don't re-bless.
- Then update `ROUTES` in `visual-regression.spec.ts` to add the 4 auth-gated routes, run with `--update-snapshots` to capture the 8 new baselines.
- Re-run without `--update-snapshots` to confirm all 16 baselines stable.

## Codex rescue findings

The rescue is running in parallel; its digest will land at `docs/redesign/codex-review-loops-1-to-3.md`. When it returns:
- **Blocker findings:** fix in this loop's commit before the AuthCard work merges. Document each in `loop-4-result.md` with the file:line and the fix.
- **Serious findings:** address in this loop if cheap; queue explicitly with rationale otherwise.
- **Minor / nit:** queue as follow-ups in `loop-4-result.md`; address in the next loop that touches the affected code.

## Binary success criteria (review checklist)

- [ ] `apps/frontend/src/components/ui/auth-card.tsx` exists with the API documented above.
- [ ] All 7 auth pages consume `<AuthCard>`. `grep -r "rounded-md border border-border bg-card p-8" apps/frontend/src/app/{login,register,forgot-password,reset-password,verify-email,verify,confirm-email-change}` returns 0 hits.
- [ ] `grep -r "const \[mounted, setMounted\]" apps/frontend/src/app/{login,register,forgot-password,reset-password}` returns 0 hits.
- [ ] At least three of `reset-password/page.tsx`, `verify-email/page.tsx`, `verify/[id]/page.tsx` import `LinkButton`.
- [ ] `make test.web` ≥ 36 files / 195+ tests green (Loop 3 was 35/185; add auth-card.test.tsx).
- [ ] Visual regression: 16 baselines (8 public + 8 auth-gated) pass stable.
- [ ] STATUS.md row 4 + CHANGELOG `### Added (UI redesign loop 4)` entry.
- [ ] Codex rescue digest at `docs/redesign/codex-review-loops-1-to-3.md`; legitimate findings either fixed in this commit or explicitly queued.
