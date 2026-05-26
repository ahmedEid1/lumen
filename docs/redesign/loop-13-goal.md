# Loop 13 — goal

Foundation D closure: **`<Select>` + `<Switch>` primitives + migrate every native `<select>` and the boolean toggle drift in studio/admin/profile/lesson-editor**.

Loop 9 already shipped `<RadioGroup>` + `<Checkbox>`. With Select + Switch landing here, Foundation D (Form-input primitives — AUDIT.md §7 row 4) closes as a tier alongside the just-closed Foundation C.

## Why now

- Foundation C closed in Loop 12 (overlays). Form-input primitives are the next tier with the most usage gravity (★★★ in AUDIT.md §2). Every form across studio/admin/profile/lesson-editor uses native `<select>` plus a duplicated `selectClass` string — exactly the "token drift + a11y holes" the audit flagged.
- Codex rescue cadence: next anchor is Loop 15. Loop 13 ships without rescue.

## What "done" looks like

1. **`apps/frontend/src/components/ui/select.tsx`** — Radix Select with `Select`, `SelectGroup`, `SelectValue`, `SelectTrigger`, `SelectContent`, `SelectViewport`, `SelectLabel`, `SelectItem`, `SelectSeparator`, `SelectScrollUpButton`, `SelectScrollDownButton`. Workbench surface chrome matching DropdownMenu (Loop 11). Trigger reads as an `Input`-like field for visual consistency with adjacent text inputs.
2. **`apps/frontend/src/components/ui/switch.tsx`** — Radix Switch. Workbench binary toggle: lime fill when on, muted border when off. Small (`h-5 w-9`), single-track no-shadow.
3. **Native `<select>` migrations** (kills the duplicated `selectClass` string):
   - `apps/frontend/src/app/studio/new/page.tsx` — subject + difficulty selects.
   - `apps/frontend/src/app/studio/[id]/page.tsx` — subject select.
   - `apps/frontend/src/app/admin/users/page.tsx` — role select.
   - `apps/frontend/src/app/profile/page.tsx` — the 7 notif-prefs dispatch selects (4-way: off / in_app / email_immediate / digest_daily; Select fits because the choice is not binary).
   - `apps/frontend/src/components/lesson/lesson-editor.tsx` — quiz-kind select.
4. **Boolean toggle migrations to `<Switch>`**:
   - Lesson editor "free preview" checkbox.
   - Admin/courses "featured only" filter checkbox.
   - (Admin/users active toggle is a clickable button + icon today, not a checkbox — leaving it alone unless audit revisits.)
5. **Unit tests** in `apps/frontend/tests/{select,switch}.test.tsx`.
6. **Existing tests stay green** — `studio` flow, `admin/users`, `admin/courses`, `profile`, `lesson-editor` units.
7. **`make test.web` green.**
8. STATUS.md row + CHANGELOG entry + `loop-13-result.md` retrospective.

## Out of scope

- DataTable, Tabs, Breadcrumb → Foundation E (Loop 14).
- Combobox / type-ahead Select. The audit calls for it on `/courses` subject filter; deferred to a later catalog loop.
- Studio dnd-kit DragOverlay improvements → Loop 17 (studio polish).

## Success criteria

- [ ] Select primitive ships, anchored via Radix.
- [ ] Switch primitive ships, with semantic on/off colour.
- [ ] All 6 surfaces' native `<select>` instances migrated; `selectClass` string deleted from each.
- [ ] At least 2 boolean toggles migrated to `<Switch>`.
- [ ] `make test.web`: green, file count grows by 2.
- [ ] CI 5 gates green.
- [ ] Prod deploy + visual review pass.
