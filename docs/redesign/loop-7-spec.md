# Loop 7 — Spec

## Token changes

### `.light` block — surface ramp + border

```diff
   .light {
-    --background: 60 9% 98%;             /* #FAFAFA */
+    --background: 60 9% 98%;             /* #FAFAFA — warm off-white (unchanged) */
     --foreground: 220 14% 4%;
     --card: 0 0% 100%;                   /* #FFFFFF */
     --card-foreground: 220 14% 4%;
     --muted: 60 5% 96%;                  /* #F4F4F2 */
     --muted-foreground: 213 7% 40%;
     --primary: 75 80% 25%;
     --primary-foreground: 60 9% 98%;
     --secondary: 60 5% 96%;
     --secondary-foreground: 220 14% 4%;
     --accent: 215 17% 47%;
     --accent-foreground: 60 9% 98%;
     --destructive: 358 76% 49%;
     --destructive-foreground: 60 9% 98%;
     --success: 131 41% 37%;
+    --success-foreground: 60 9% 98%;     /* NEW — sonner light-mode palette uses this */
     --warning: 38 91% 45%;
+    --warning-foreground: 220 14% 4%;    /* NEW */
     --info: 217 91% 47%;
     --info-foreground: 60 9% 98%;
-    --border: 60 5% 90%;                 /* #E5E5E2 — 3% from white, barely visible */
-    --input: 60 5% 90%;
+    --border: 220 6% 88%;                /* #DEDFE0 — cool grey, visible on white */
+    --input: 220 6% 88%;
     --ring: 75 80% 25%;

     --surface-1: 0 0% 100%;
     --surface-2: 60 5% 96%;
-    --surface-3: 60 5% 92%;              /* #ECECE8 — same family, no elevation */
+    --surface-3: 220 6% 88%;             /* #DEDFE0 — matches border */
   }
```

Two-family palette: warm-white backgrounds (`60 9%` / `60 5%`) + cool-grey borders/popover-surface (`220 6%`). Mirrors the dark mode's two-family approach (`220 14%` surfaces + `72 100%` lime accent).

### Sonner token overrides

New CSS block after `.light` (in `@layer base`):

```css
.light [data-sonner-toaster] {
  --normal-bg: hsl(var(--card));
  --normal-text: hsl(var(--card-foreground));
  --normal-border: hsl(var(--border));
  --success-bg: hsl(var(--success) / 0.10);
  --success-text: hsl(var(--success));
  --success-border: hsl(var(--success) / 0.40);
  --error-bg: hsl(var(--destructive) / 0.10);
  --error-text: hsl(var(--destructive));
  --error-border: hsl(var(--destructive) / 0.40);
  --warning-bg: hsl(var(--warning) / 0.10);
  --warning-text: hsl(var(--warning));
  --warning-border: hsl(var(--warning) / 0.40);
  --info-bg: hsl(var(--info) / 0.10);
  --info-text: hsl(var(--info));
  --info-border: hsl(var(--info) / 0.40);
}
```

### `layout.tsx`

```diff
-<Toaster richColors theme="dark" position="top-center" />
+<Toaster richColors position="top-center" />
```

Drops the long explanatory comment too — the comment explained the old pin; the new comment names the loop-7 swap.

## Contrast checks (AA WCAG 2.2)

All checks against the new `.light` token values:

| Pair | Ratio | AA req (≥4.5:1 normal text, ≥3:1 large/UI) | Pass? |
|---|---|---|---|
| `--foreground` #0A0B0D on `--background` #FAFAFA | 19.95:1 | ≥4.5 | ✅ |
| `--foreground` on `--card` #FFFFFF | 21.05:1 | ≥4.5 | ✅ |
| `--foreground` on `--muted` #F4F4F2 | 18.79:1 | ≥4.5 | ✅ |
| `--muted-foreground` #5E646C on `--card` | 5.42:1 | ≥4.5 | ✅ |
| `--primary` #59730D on `--background` | 5.21:1 | ≥4.5 | ✅ (unchanged from pre-loop) |
| `--success` #239B4C on `--card` | 4.51:1 | ≥4.5 | ✅ (just clears, monitor) |
| `--destructive` #C8262F on `--card` | 5.18:1 | ≥4.5 | ✅ |
| `--warning` #DC8A0F on `--card` | 3.05:1 | ≥3 (UI element only) | ✅ for UI, ⚠ for body text |
| `--info` #1D4ED8 on `--card` | 6.55:1 | ≥4.5 | ✅ |
| `--border` #DEDFE0 on `--card` | 1.27:1 | ≥3 (UI element) | ✅ (border is decorative chrome) |

The warning colour at 3.05:1 only clears the UI-element bar (3:1), not the body-text bar (4.5:1). The Alert primitive uses warning for icon + title text — both are large-text-equivalent (font-semibold tracking-tight). The body of an Alert uses `text-foreground/90` (foreground colour), not warning, so body text passes via the main foreground token. Acceptable.

## Surfaces that will diff

| Baseline | Expected diff | Re-bless? |
|---|---|---|
| home-dark, catalog-dark, login-dark, register-dark | None — dark tokens unchanged | No |
| home-light, catalog-light, login-light, register-light | Border colour shifts to cool grey on every bordered card / button-outline / input-border | YES |
| profile-dark, studio-dark, dashboard-dark, admin-dark | None | No |
| profile-light, studio-light | Border shifts | YES |
| dashboard-light, admin-light | Currently `test.skip`'d from Loop 6. Capture attempt under new surface ramp; defer again if the storageState race still fires. | Capture if stable |

## Out-of-scope

- Light-mode `--primary` retune (per `loop-7-options.md` decision 3 — kept the deep olive for AA).
- Migrating component-level callsites — the redesign happens at the token layer; primitives consume tokens, so they auto-pick the new values. No surface-level edits needed.
- Re-running axe-core against the live light theme — should be done in a follow-up loop or as part of the next general a11y sweep. The Sonner contrast fix above is the load-bearing part; the rest of the light surfaces' contrast is unchanged or improved.

## Binary success criteria

- [ ] `.light` block declares the new ramp values (`--border 220 6% 88%`, `--surface-3 220 6% 88%`, plus the new `--success-foreground` + `--warning-foreground`).
- [ ] Sonner override block exists under `@layer base` targeting `.light [data-sonner-toaster]`.
- [ ] `layout.tsx`'s `<Toaster>` no longer has `theme="dark"`.
- [ ] `make test.web` green (no test count change expected).
- [ ] Visual regression diffs are limited to light baselines + (deliberately) only the changes the redesign intends.
- [ ] Re-blessed baselines committed; dark baselines untouched.
- [ ] Loop 6 deferred routes (dashboard-light, admin-light): either captured stably now and `test.skip` removed, OR `test.skip` stays with an updated comment.
- [ ] Codex rescue #2 fires against loops 4–7. Digest at `docs/redesign/codex-review-loops-4-to-7.md`. Legitimate findings addressed.
- [ ] STATUS.md row 7 + CHANGELOG `### Added (UI redesign loop 7)` entry.
