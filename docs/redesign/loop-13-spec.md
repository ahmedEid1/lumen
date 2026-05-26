# Loop 13 — spec

Selected option: **B** (Select + Switch + Foundation D closure).

## Files touched

### New
- `apps/frontend/src/components/ui/select.tsx`
- `apps/frontend/src/components/ui/switch.tsx`
- `apps/frontend/tests/select.test.tsx`
- `apps/frontend/tests/switch.test.tsx`
- `docs/redesign/loop-13-{goal,options,spec,result}.md`

### Edited
- `apps/frontend/src/app/studio/new/page.tsx` — 2 native selects → `<Select>`. Delete the local `selectClass` const.
- `apps/frontend/src/app/studio/[id]/page.tsx` — 1 native select → `<Select>`. Delete `selectClass`.
- `apps/frontend/src/app/admin/users/page.tsx` — 1 native select → `<Select>`. Delete `selectClass`.
- `apps/frontend/src/app/profile/page.tsx` — 7 notif-prefs selects → `<Select>` (map-rendered, so one migration).
- `apps/frontend/src/components/lesson/lesson-editor.tsx` — quiz-kind select → `<Select>`; "free preview" checkbox → `<Switch>`.
- `apps/frontend/src/app/admin/courses/page.tsx` — "featured only" checkbox → `<Switch>`.
- `apps/frontend/src/styles/globals.css` — `data-wb-select-content` to the existing `[data-state=open]` animation rule family.
- `apps/frontend/package.json` + `pnpm-lock.yaml` — two new Radix deps.
- `docs/redesign/STATUS.md`, `CHANGELOG.md`.

## Select primitive

- Built on `@radix-ui/react-select`.
- Trigger styled like `<Input>` for visual consistency with adjacent text inputs in form rows: `h-9 rounded-md border-border bg-background px-3 py-1 font-body text-sm`. Right-aligned chevron-down icon.
- Content: same Workbench surface chrome as DropdownMenu (`bg-card border border-border rounded-md p-1`). Z-index `z-popover`.
- `data-wb-select-content` for the open-animation hook.
- Items: hover/highlighted state shifts to `bg-muted`. Selected item shows a `Check` indicator at `ps-8`.

## Switch primitive

- Built on `@radix-ui/react-switch`.
- Track: `h-5 w-9 rounded-full border border-border bg-muted` (off) → `bg-primary` (on).
- Thumb: `h-4 w-4 rounded-full bg-background` (off) / `bg-primary-foreground` (on); translate from `start` to `end` on toggle. Logical-property translate so RTL flips naturally.
- Focus ring matches Checkbox/RadioGroup.
- Accessibility: Radix wires `role="switch"` + `aria-checked` automatically.

## Migration patterns

### Native `<select>` → `<Select>`

Before:
```tsx
const selectClass = "h-9 rounded-md border border-border bg-background px-3 py-1 font-body text-sm focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50";

<select
  value={subject}
  onChange={(e) => setSubject(e.target.value)}
  className={selectClass}
>
  {subjects.map((s) => (
    <option key={s.id} value={s.id}>{s.title}</option>
  ))}
</select>
```

After:
```tsx
<Select value={subject} onValueChange={setSubject}>
  <SelectTrigger>
    <SelectValue placeholder={t("studio.subjectPlaceholder")} />
  </SelectTrigger>
  <SelectContent>
    {subjects.map((s) => (
      <SelectItem key={s.id} value={s.id}>{s.title}</SelectItem>
    ))}
  </SelectContent>
</Select>
```

### Native checkbox → `<Switch>`

Before:
```tsx
<label className="flex items-center gap-2 font-body text-sm">
  <input
    type="checkbox"
    checked={isPreview}
    onChange={(e) => setIsPreview(e.target.checked)}
    className="accent-[hsl(var(--primary))]"
  />
  {t("lessonEditor.freePreview")}
</label>
```

After:
```tsx
<div className="flex items-center gap-2">
  <Switch
    id="lesson-free-preview"
    checked={isPreview}
    onCheckedChange={setIsPreview}
  />
  <label htmlFor="lesson-free-preview" className="font-body text-sm">
    {t("lessonEditor.freePreview")}
  </label>
</div>
```

## Tests

`apps/frontend/tests/select.test.tsx` (~140 LoC):
- Trigger opens content
- Items render with role="option"
- Click item closes + onValueChange fires
- Escape closes
- Placeholder shows when no value
- Selected item shows Check indicator

`apps/frontend/tests/switch.test.tsx` (~80 LoC):
- Renders as role="switch"
- aria-checked="false" by default
- onCheckedChange fires on click
- Disabled prop disables the trigger
- Controlled mode (checked + onCheckedChange) works

Existing tests touched:
- `lesson-editor.test.tsx` — if a quiz-kind picker assertion uses `getByRole("combobox")` it'll still resolve (Radix Select's trigger has role="combobox").
- Other tests: spot-check by running the suite.

## Risks

- **Radix Select trigger role.** Radix Select uses `role="combobox"` on its trigger — that's per the WAI-ARIA Authoring Practices for "selection from a list." If any test queries with `getByRole("button", { name: /role|subject|.../i })` against an old native `<select>`, the migration may break that query. Mitigation: spot-check `lesson-editor.test.tsx`, `admin-users` integration if any, etc.
- **Profile prefs 7-select migration.** Same shape repeated 7× in a map — one diff covers all 7. Verify state still flows correctly through `setNotifPrefs`.
- **Studio difficulty default value.** `/studio/new` defaults difficulty to "beginner" — make sure the Radix Select renders the default value correctly via `defaultValue` or controlled `value`.

## Estimated diff

- Select primitive: ~180 LoC
- Switch primitive: ~50 LoC
- 5 surface migrations (studio/new, studio/[id], admin/users, profile, lesson-editor select): ~250 LoC churn (net likely -50 LoC because `selectClass` constants die)
- 2 boolean toggle migrations: ~30 LoC
- Tests: ~220 LoC
- globals.css: ~3 LoC
- Loop docs: ~400 LoC (doesn't count)
- STATUS + CHANGELOG: ~30 LoC
- pnpm-lock churn: ~50 LoC

**Total source diff: ~700 LoC.** Comfortable under cap.
