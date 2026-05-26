# Loop 15 — options

## Option A — Spread auth polish across 3 loops

Loop 15 = PasswordInput only. Loop 16 = strength meter + register confirm. Loop 17 = idempotency + Link>Button sweep + Codex.

- **Pros:** smaller per-loop diff.
- **Cons:** Codex rescue cadence wants a coherent tier closure at 15. Splitting auth polish into 3 doesn't match a "tier."

## Option B — Whole auth polish in Loop 15 (chosen)

Two primitives + 5 surface updates + idempotency + Link>Button sweep + Codex rescue, all in one loop. ~1500-1800 LoC. Aligns with the "team-day" iteration size feedback.

- **Pros:** closes the audit's §3 Auth surfaces backlog in one push. Codex rescue at the end audits the whole batch + earlier two loops.
- **Cons:** larger review surface — but the surfaces share the new PasswordInput / StrengthMeter primitives, so the diff is cohesive.

## Option C — zxcvbn-based strength meter

Pull `zxcvbn` (or its slimmer `@zxcvbn-ts/core`) for a real entropy-based score.

- **Pros:** accurate scoring matches industry standard.
- **Cons:** adds ~400KB to bundle for a meter; the simple heuristic (length + class diversity + no common patterns) is sufficient for a UX hint. Reject — Workbench priority is "no unnecessary deps."

## Decision

**Option B.** Reject C in favor of a small in-house heuristic.

## API sketches

### PasswordInput
```tsx
<PasswordInput
  id="password"
  value={password}
  onChange={(e) => setPassword(e.target.value)}
  autoComplete="new-password"
  required
  minLength={12}
/>
```
Renders `<Input>` + Eye/EyeOff toggle button stacked. Toggle is `aria-label`-translated.

### PasswordStrengthMeter
```tsx
<PasswordStrengthMeter value={password} />
```
Renders 5 segmented bars + a label like "Weak" / "Fair" / "Good" / "Strong". Uses `--success` / `--warning` / `--destructive` semantic tokens for fill.

### Register form additions
```tsx
<PasswordInput id="password" ... />
<PasswordStrengthMeter value={password} />
<PasswordInput id="password_confirm" value={confirm} ... />
{confirm && confirm !== password && <p className="text-destructive">{t(...)}</p>}

<div className="flex items-start gap-2">
  <Checkbox id="terms" checked={agreed} onCheckedChange={setAgreed} />
  <label htmlFor="terms" className="font-body text-sm text-muted-foreground">
    {t("auth.register.terms.label")} <Link href="/terms">{t("auth.register.terms.link")}</Link>
  </label>
</div>
```
Submit disabled until: hydrated + email + password + matching confirm + T&C agreed.

### Idempotency guard
```tsx
const calledRef = useRef(false);
useEffect(() => {
  if (calledRef.current) return;
  calledRef.current = true;
  // ... verify call
}, [token]);
```
Same pattern in /verify-email and /confirm-email-change.

## Local-verification protocol (new this loop)

Before any push:
1. `make test.web`
2. `cd apps/frontend && pnpm exec eslint .` — 0 errors
3. `cd apps/frontend && pnpm exec tsc --noEmit --incremental false`
4. `make up` + manually walk:
   - `http://localhost:3000/login` — see eye toggle, click it, password text shows
   - `http://localhost:3000/register` — see eye toggles, meter live-updates, confirm shows error on mismatch, T&C disables submit
   - `http://localhost:3000/verify-email?token=...` (use a fresh token from dev seed)
5. Local axe: `docker compose --profile e2e run --rm e2e accessibility.spec.ts --project=chromium --reporter=list` — green
6. Codex rescue
7. THEN push
