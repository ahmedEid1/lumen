# Loop 13 — options

## Option A — Select only, defer Switch

Smallest scope. Select primitive + 6 native-select migrations. Switch ships next loop.

- **Pros:** narrowest diff, easiest review.
- **Cons:** Foundation D would still be incomplete — Switch is the last form-input primitive. The "primitive + real consumer per loop" rule says Switch should ship with at least one boolean-toggle migration; bundling them is cheap because both are small.

## Option B — Select + Switch + all migrations (chosen)

Both primitives + 6 select migrations + 2-3 switch migrations.

- **Pros:** Foundation D closes as a tier (mirror of Foundation C closing in Loop 12). The selectClass duplicated string finally dies; lesson + admin/courses get real toggle semantics. Estimate ~700 LoC; cap is 2000.
- **Cons:** more code in one commit. Mitigated by the migrations being mechanically identical (each replaces `<select>{options}</select>` with `<Select>{items}</Select>`).

## Option C — Bigger: Select + Switch + Combobox

Adds Combobox (search-as-you-type) which the audit calls for on /courses subject filter.

- **Pros:** unblocks catalog v2 loop earlier.
- **Cons:** Combobox is significantly more complex (needs cmdk or downshift), and the catalog filter UX is downstream of the catalog v2 loop's URL-sync work. Premature.

## Decision

**Option B.** Closes Foundation D as a tier. Stays well under the cap.

## API sketches

```tsx
// Select
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

// Switch — paired with a label
<div className="flex items-center gap-2">
  <Switch id="lesson-free-preview" checked={isPreview} onCheckedChange={setIsPreview} />
  <label htmlFor="lesson-free-preview" className="font-body text-sm">
    {t("lessonEditor.freePreview")}
  </label>
</div>
```

Both share the surface chrome of DropdownMenu / Popover (rounded-md border-border bg-card) so the entire form-input family reads consistently.
