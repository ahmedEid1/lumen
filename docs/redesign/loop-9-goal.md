# Loop 9 — Goal

**Land the `<RadioGroup>` + `<Checkbox>` primitives and migrate the quiz options in `lesson-player.tsx` from bare `<button>` rows to proper radiogroup / checkbox-group semantics.**

AUDIT.md §3 Block-renderer is the heaviest a11y indictment in the audit:

> Quiz options are not a radiogroup — bare `<button>` rows, no `role="radio"`/`role="checkbox"`, no arrow-key nav, no `aria-checked`, no fieldset/legend. Keyboard users tab through every option; screen readers don't know it's a question.

This loop closes that finding. The same loop ships two of the three form-input primitives the audit named (Switch is deferred — it's profile-notif-prefs scope, not quiz scope). Radix has `react-radio-group` and `react-checkbox` packages; both are tiny additions.

- **Surface:**
  - NEW `apps/frontend/src/components/ui/radio-group.tsx` (Radix-backed, ~50 LoC).
  - NEW `apps/frontend/src/components/ui/checkbox.tsx` (Radix-backed, ~40 LoC).
  - `apps/frontend/package.json` — adds `@radix-ui/react-radio-group` + `@radix-ui/react-checkbox`.
  - MODIFIED `apps/frontend/src/components/lesson/lesson-player.tsx:233-256` — quiz-option block split: `q.kind === "single"` renders `<RadioGroup>` + `<RadioGroupItem>` per choice; `q.kind === "multi"` renders a `<ul>` of `<Checkbox>` + label rows. The outer container becomes a `<fieldset>` with `<legend>` (the question prompt) so screen readers announce "Question 3, radio group, 4 options" instead of "button, ..., button, ...".
  - NEW `apps/frontend/tests/quiz-radiogroup.test.tsx` — vitest coverage for the migrated quiz: arrow-key nav across radio options, aria-checked toggles, fieldset/legend semantics.

- **Persona:** every keyboard + screen-reader user taking a quiz. Pre-loop they tab through every option and never hear "this is a question". Post-loop they get fieldset/legend announcement + arrow-key navigation within the choice group.

- **Binary success criteria:**
  1. `<RadioGroup value onValueChange><RadioGroupItem value>` exported from `components/ui/radio-group.tsx`. Visually matches the previous quiz-button look (bordered row, hover shifts border).
  2. `<Checkbox checked onCheckedChange>` exported from `components/ui/checkbox.tsx`. Same visual family.
  3. `lesson-player.tsx` quiz options use the new primitives. The outer per-question block is a `<fieldset>` with `<legend>` (the prompt).
  4. Arrow-key navigation works in single-select quizzes (Radix provides this).
  5. Each radio / checkbox has `aria-checked` (or the native equivalent) that screen readers can read.
  6. Visual regression: no auth-gated `/learn/[slug]` baseline today (this loop *could* add one but the lesson player has video + image content that's data-dependent, so the baseline would be fragile). Skip the VR addition; lean on the new vitest spec for the regression.
  7. New vitest spec passes; existing 36-file / 194-test suite still green.
  8. STATUS.md row 9 + CHANGELOG `### Added (UI redesign loop 9)`.

Out of scope:
- `<Switch>` primitive for the profile notif-prefs migration. Separate loop.
- Block-renderer's other AUDIT.md findings (syntax highlighting on code blocks, video poster, image aspect-ratio). Those ship together as Loop 10 or paired with the lesson-player mobile pass.
- Quiz history visual polish, past-attempt pills using lucide icon (audit §3 last bullet). Out of scope; absorb in the lesson-player mobile pass.
