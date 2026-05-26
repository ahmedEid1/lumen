# Loop 4 — Goal

**Compose `<AuthCard>` from the loop-3 primitives + `useHydrated` and migrate the seven auth surfaces. Capture the eight auth-gated visual-regression baselines that loop 2 deferred. End on the loops-1–3 Codex rescue digest.**

AUDIT.md cross-cutting #1 names the auth chrome as the highest-value collapse target: "Every auth surface re-implements the same `mounted` hydration gate" — four copies of one paragraph — plus "all auth pages live in inline JSX blobs of 130-150 lines with no shared `<AuthCard>` / `<AuthHeader>` primitive even though the chrome is byte-identical (mono cartouche + `font-display` h1 + subtitle + card with `rounded-md border border-border bg-card p-8`)". This loop kills both with one primitive + one hook, then visually pins the result.

- **Surface:**
  - New: `apps/frontend/src/components/ui/auth-card.tsx`.
  - Edits: `apps/frontend/src/app/{login,register,forgot-password,reset-password,verify-email,confirm-email-change}/page.tsx` + `apps/frontend/src/app/verify/[id]/page.tsx`.
  - Re-bless: `login-{dark,light}.png` + `register-{dark,light}.png` if the AuthCard composition changes any pixel (expected: not, since the resulting DOM should be identical).
  - Add: 8 new auth-gated baselines (`dashboard`, `profile`, `studio`, `admin` × 2 themes).
- **Persona:** every future auth-surface tweak. Right now a copy change in the cartouche treatment edits 7 files. After this loop it edits 1 file.
- **Binary success criteria:**
  1. `<AuthCard cartouche heading subtitle>` exports a primitive matching the existing chrome byte-for-byte.
  2. All seven auth pages consume `<AuthCard>`. Each loses ~30-40 LoC of chrome.
  3. The four hydration-gate paragraphs (login:47-58, register:34-35, forgot:30-31, reset:44-45) collapse to `const hydrated = useHydrated();`.
  4. The four nested `<Link><Button>` patterns (reset-password:92, verify-email:113, verify/[id]:105 — course-detail-view is out of scope for this loop) convert to `<LinkButton>`.
  5. Form error displays use `<Alert tone="destructive">` only for **page-level** auth errors (where the destructive `role="alert"` is warranted); per-field validation continues to use `<Field error>` (deferred to loop 5).
  6. `make test.web` green; new vitest in `tests/auth-card.test.tsx` (~60 LoC).
  7. Visual-regression: existing 8 public baselines remain stable (≤ `maxDiffPixels: 100`); 4 of them (`login`, `register`) may re-bless if DOM changes; the 8 new auth-gated baselines pass cleanly.
  8. Codex rescue digest published at `docs/redesign/codex-review-loops-1-to-3.md`; legitimate findings addressed in this loop (or queued explicitly with rationale).

Out of scope (deferred):
- Per-field inline validation (e.g. live password-strength meter, password-confirm matching). That's the auth-polish loop later in the sequence.
- Migrating non-auth nested `Link>Button` (course-detail-view:370). That site moves with the course-detail polish loop.
- Replacing the per-page error region's `aria-live` with the new `<Alert>` everywhere. We use Alert where it strictly makes sense (destructive page error). The inline error inside forms stays a single `<p className="text-destructive">` for now — Loop 5's Field migration covers that.

## Why split this from loop 5 (the broader application sweep)

Loop 5 will apply Skeleton, EmptyState, Spinner across studio/mastery/reviews/dashboard/admin loading + empty sites. Bundling that with auth migration produces a 3000+ LoC commit; splitting keeps each diff reviewable. Order also matters: AuthCard depends on Loop 3's Field + useHydrated, and the auth-gated VR baselines depend on `useHydrated` collapsing the hydration race. Loop 5 has no such dependency on Loop 4.
