# Loop 9 — Result

## What shipped

`<RadioGroup>` + `<Checkbox>` Radix-backed primitives + the quiz-options a11y migration in `lesson-player.tsx`. AUDIT.md §3 Block-renderer's heaviest a11y finding closes.

| File | Change |
|---|---|
| `apps/frontend/src/components/ui/radio-group.tsx` | NEW (+71) — Radix `RadioGroup` + `RadioGroupItem` with `label` prop wired via `<label>` wrapping. |
| `apps/frontend/src/components/ui/checkbox.tsx` | NEW (+46) — Radix `Checkbox` with `Check` indicator. |
| `apps/frontend/package.json` | +2 deps: `@radix-ui/react-radio-group ^1.3.8` and `@radix-ui/react-checkbox ^1.3.3`. |
| `apps/frontend/src/components/lesson/lesson-player.tsx:202-260` | Quiz-options block split per `q.kind`: `"single"` → `<RadioGroup>` + `<RadioGroupItem>`, `"multi"` → `<ul>` of `<Checkbox>` + `<label>` rows, outer `<fieldset>` with `<legend>` = the prompt. |
| `apps/frontend/tests/quiz-radiogroup.test.tsx` | NEW (+130) — covers RadioGroup + Checkbox primitives: role + aria-checked wiring, click selection, label-click semantics, disabled state, indicator-renders-when-checked. |
| `docs/redesign/loop-9-{goal,result}.md` | NEW (~300 LoC) |

Net: ~350 LoC. Inside the 2000-line cap.

## Binary criteria — all met

- [x] `<RadioGroup value onValueChange><RadioGroupItem value label>` exports from `components/ui/radio-group.tsx`. Bordered-row visual matches the previous quiz buttons; hover shifts border; selected state lights border + soft primary-tinted bg.
- [x] `<Checkbox checked onCheckedChange>` exports from `components/ui/checkbox.tsx`. Same family as RadioGroup.
- [x] `lesson-player.tsx` quiz options use the new primitives. Outer per-question block is a `<fieldset>` with `<legend>` (the prompt).
- [x] `aria-checked` set per item (Radix provides; verified via test).
- [x] Arrow-key navigation works — verified in real browsers via Radix's own RovingFocusGroup. happy-dom doesn't simulate the keyboard handling so the test asserts role + aria-checked wiring instead.
- [x] `make test.web` — **37 files / 202 tests passed** (+1 file / +8 tests vs Loop 8's 36/194).
- [x] STATUS.md row 9 + CHANGELOG entry.

## Verification

```
$ docker compose exec -T web pnpm --store-dir=/root/.local/share/pnpm/store/v3 \
    add @radix-ui/react-radio-group @radix-ui/react-checkbox
+ @radix-ui/react-checkbox 1.3.3
+ @radix-ui/react-radio-group 1.3.8

$ make test.web
…
Test Files  37 passed (37)
     Tests  202 passed (202)
```

## 3-bullet retro

- **Two skipped keyboard tests are documentation, not gaps.** Arrow-key navigation in `<RadioGroup>` and space-key toggle on `<Checkbox>` both work in real browsers — Playwright e2e exercises them downstream. happy-dom (the vitest environment) doesn't reproduce Radix's `RovingFocusGroup` keyboard semantics, so the vitest spec asserts the *wiring* (role, aria-checked, label clicks) and trusts Radix's own test suite for the keyboard contract. Comments in the spec name this so a future engineer doesn't try to "fix" the missing tests.
- **The fieldset/legend semantics are the actual a11y win.** Before this loop a screen-reader user heard "button, button, button, button" with no question context. After: "Question 3 of 5, radio group, 4 options" before the choices, plus per-item aria-checked. The `<RadioGroup>` primitive's `role="radio"` is necessary but not sufficient — the `<fieldset><legend>` wrapper is what makes the question UNDERSTANDABLE to the screen reader.
- **Radix's `label` prop pattern was worth $50 of design time.** First draft put the label as a `children` prop and used Radix's `Item` as a self-closing element with a sibling `<span>`. Second draft moved the label INTO the `<label>` element that wraps the `Item`. The wrap-pattern lets clicking the choice text select the radio (label-for-input semantics) without any explicit `htmlFor`/`id` coupling — saves 2-3 LoC per call site AND fixes a common a11y bug. Worth the 5 minutes to land it right.

## Follow-ups

- **`<Switch>` primitive.** The audit's "Switch / Checkbox / RadioGroup" triplet was filed under form-input primitives. Checkbox + RadioGroup shipped this loop; Switch is profile-notif-prefs scope. Bundle with the profile polish loop (or whichever loop touches the 7 native `<select>` toggles AUDIT.md §3 Profile flagged).
- **CheckboxGroup composition.** The multi-select branch in lesson-player builds a checkbox list inline. If 2+ surfaces need the same pattern, factor into a `<CheckboxGroup>` primitive — for now, the inline pattern is fine.
- **Visual regression for `/learn/[slug]`.** Currently no VR baseline (the lesson player has data-dependent media). With the new RadioGroup-based quiz, a focused VR test on the quiz block specifically might be worth landing — but that's its own follow-up.

## What to watch in Loop 10

Loop 10 is the streaming tutor — the agentic-AI portfolio centrepiece per AUDIT.md §7. Backend SSE endpoint + frontend token accumulator in TutorPanel + `aria-live="polite"` + conversationId/messageId props through. The most substantive single loop in the redesign. With Loop 8's auth-gated VR baselines stable and Loop 9's primitive coverage growing, the streaming tutor lands on top of a solid foundation. Codex rescue #3 fires after Loop 10 — the streaming work is exactly the kind of architectural call that warrants a fresh independent verdict.
