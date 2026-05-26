# Loop 13 — result

Surface: Foundation D closure — `<Select>` + `<Switch>` primitives + 6 native-select migrations + 2 boolean-toggle migrations.

**Foundation D closes here.** Together with Loop 9 (RadioGroup + Checkbox), the form-input primitive family is complete: Field / Input / Textarea / Select / Switch / Checkbox / RadioGroup.

## What shipped

- **`apps/frontend/src/components/ui/select.tsx`** (167 LoC). Radix Select with full sub-component family. Trigger styled like Input (`h-9 border bg-background`); content matches DropdownMenu chrome.
- **`apps/frontend/src/components/ui/switch.tsx`** (52 LoC). Radix Switch with semantic on/off colour + logical-property thumb translate.
- **`apps/frontend/src/styles/globals.css`** — added `data-wb-select-content` to the existing fade-in animation rule family.
- **`apps/frontend/src/app/studio/new/page.tsx`** — 2 native `<select>` → `<Select>`. Deleted the local `selectClass` constant.
- **`apps/frontend/src/app/studio/[id]/page.tsx`** — 1 native `<select>` → `<Select>`. Deleted `selectClass`.
- **`apps/frontend/src/app/admin/users/page.tsx`** — per-row role `<select>` → `<Select>`. Deleted `selectClass`. Added `adminUsers.roleLabel` i18n key.
- **`apps/frontend/src/app/profile/page.tsx`** — 7 notif-prefs `<select>` → `<Select>` (map-rendered, one diff covers all 7).
- **`apps/frontend/src/components/lesson/lesson-editor.tsx`** — quiz-kind `<select>` → `<Select>`; "free preview" `<input type="checkbox">` → `<Switch>`.
- **`apps/frontend/src/app/admin/courses/page.tsx`** — "featured only" `<input type="checkbox">` → `<Switch>`.
- **`apps/frontend/src/lib/i18n/messages/{en,ar}.ts`** — added `adminUsers.roleLabel` for the Select's aria-label.
- **`apps/frontend/tests/setup.ts`** — added happy-dom stubs for `Element.hasPointerCapture`, `Element.scrollIntoView`, `Element.releasePointerCapture`. Radix Select + DropdownMenu portal positioning reaches for these; happy-dom doesn't implement them.
- **`apps/frontend/tests/select.test.tsx`** (6 tests).
- **`apps/frontend/tests/switch.test.tsx`** (6 tests).
- **`apps/frontend/package.json`** — `@radix-ui/react-select ^2.2.6` + `@radix-ui/react-switch ^1.2.6`.

## Success criteria

- [x] Select primitive ships, Radix-backed with full sub-component family.
- [x] Switch primitive ships with semantic on/off colour.
- [x] All 6 surfaces' native `<select>` instances migrated; `selectClass` constants deleted.
- [x] 2 boolean toggles migrated to `<Switch>`.
- [x] `make test.web`: 43 files / 244 tests green.
- [x] i18n parity test still green (new `adminUsers.roleLabel` key added to both en + ar).
- [ ] CI 5 gates green — pending push.
- [ ] Prod deploy + visual review pass — pending.

## What didn't ship (intentional)

- DataTable, Tabs, Breadcrumb → Foundation E (Loop 14 onwards).
- Combobox / type-ahead Select. Deferred to a catalog v2 loop where the subject filter on `/courses` would consume it.
- Admin/users `is_active` toggle still uses the "Disable/Enable" button + Badge pair (rather than a Switch). That's a deliberate keep — the active toggle is a heavier action (sends a PATCH; the button is the explicit confirm). A future admin polish loop can re-evaluate.

## Lessons

- **happy-dom needs pointer-capture stubs for Radix Select + DropdownMenu.** Standard stub trio: `hasPointerCapture`, `scrollIntoView`, `releasePointerCapture`. Without them, Radix Select's open-flow throws before mounting the portal — symptoms are 4 tests failing with `findAllByRole("option")` not resolving. The stubs go into `tests/setup.ts` so every spec benefits.
- **The `selectClass` constant pattern was even worse than the audit flagged.** 3 files each carried a slightly different copy of the same ~100-character class string. Picking one Workbench-true definition (inside the Select primitive) and deleting all three copies is the kind of consolidation Foundation D primitives unlock.
- **Map-rendered native selects condense to one Select migration.** The 7-pref profile section was the biggest visible change in this loop and the smallest diff — the `<select>` to `<Select>` swap happens once inside the `Object.entries(notifPrefs).map(...)` body.
- **`role="combobox"` on Select trigger surprised one assertion.** Radix Select uses `role="combobox"` per WAI-ARIA. Existing tests that queried for `getByRole("button")` against the old native select would break, but happily no existing test did that — every test that touched a select queried by accessible-name (`getByLabel(...)` / `getByDisplayValue(...)`).

## Estimated vs actual diff

| Surface | Estimate (spec) | Actual |
|---|---|---|
| Select primitive | ~180 LoC | 167 LoC |
| Switch primitive | ~50 LoC | 52 LoC |
| 5 select-surface migrations | ~250 LoC churn / net -50 | net -65 LoC (selectClass dies in 3 places) |
| 2 boolean toggle migrations | ~30 LoC | ~10 LoC |
| Tests | ~220 LoC | ~190 LoC |
| globals.css | +3 LoC | +1 LoC |
| setup.ts pointer-capture stubs | (not estimated) | +15 LoC |
| Loop docs | ~400 LoC | ~440 LoC |
| STATUS + CHANGELOG | ~30 LoC | ~40 LoC |
| pnpm-lock churn | ~50 LoC | ~70 LoC |

**Total source diff: ~600 LoC.** Under the 2000 LoC cap.

## Codex rescue

Next Codex rescue at end of Loop 15 (every-3rd-loop cadence; rescue at 12, next at 15). Loop 13 ships without rescue per the spec.
