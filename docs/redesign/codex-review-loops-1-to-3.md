# Codex review — loops 1–3 (foundation tier rescue)

Date: 2026-05-26
Scope: commit range `c3450a8..0103371` (the last pre-redesign tip → current `main` tip)
Reviewer: Codex CLI (gpt-5.5), session `019e632a-0816-7083-bd25-3818f200bb38`
Wrapped via: `codex-reviewer` agent

## What landed

One **P2** finding from Codex's default review rubric. The seven-axis priority prompt I tried to pass via `codex review --title` was treated as a header label, not as a steering prompt — `codex review` doesn't accept a free-form prompt argument alongside `--base <branch>`. So this is Codex's *own* read of the diff, not a directed audit. That's still useful as an independent verdict; the limitation is just that Codex didn't grade against the spec docs the way the in-house review team would have.

## P2 — `LinkButton` doesn't honor the `disabled` prop

**File:** `apps/frontend/src/components/ui/link-button.tsx:30-50`
**Verdict (verbatim):**

> Because `LinkButtonProps` inherits `disabled` from `ButtonProps`, callers can pass `<LinkButton disabled>`, but with `asChild` the disabled prop/class lands on an `<a>`/Next `<Link>` instead of a real button. Anchors do not match the `:disabled` selector and still navigate/click, so any loading or permission-gated link button remains interactive unless the component explicitly maps disabled to `aria-disabled`, `tabIndex`, click prevention, and disabled styling.

**Assessment:** real defect. `disabled` on `<a>` is invalid HTML (browsers ignore it) and the anchor never matches `:disabled`, so `button.tsx`'s `disabled:pointer-events-none` + `disabled:opacity-50` variants are no-ops when `Button asChild` wraps a Link/anchor. A loading-state `<LinkButton disabled>` would still navigate on click — exactly the surface the audit's nested-`<Link><Button>` migration was meant to clean up.

**Fix (this commit):**
- When `disabled`, render a plain `<a>` *without* `href` (so no navigation is possible at all), set `aria-disabled="true"`, set `tabIndex={-1}`, and add an `onClick` handler that calls `e.preventDefault()`.
- Don't forward `disabled` to `Button` in the disabled branch (it would just emit an invalid `disabled` attribute on the anchor). Instead apply `opacity-50 pointer-events-none` via the component's own className so the visual styling matches the disabled Button.
- When not disabled, the non-disabled branch is unchanged.
- New vitest cases in `primitives-foundation.test.tsx` pin the contract: `<LinkButton disabled>` renders an anchor with `aria-disabled="true"`, no `href`, and a click handler that calls `preventDefault`.

## Axes NOT covered by this Codex pass

The original priority prompt asked Codex to audit seven axes. Because the prompt wasn't accepted as steering, Codex flagged only one issue (the LinkButton defect above) and didn't grade the rest. The remaining six axes were spot-checked by the in-house review during loops 1–3's own implementation:

1. **Spec violations vs `loop-{N}-spec.md`** — none found; each loop's `loop-{N}-result.md` walked its own binary criteria.
2. **Token discipline regressions** — none found; new code consumes the tokens defined in loop 1 (info, semantic colours, durations). Two pre-existing leaks documented in AUDIT.md §4 #1 (`admin/evals/ScoreBadge` raw hues, `LLMTracesTab` StatusBadge raw yellow) are not introduced by loops 1–3 — they'll be cleaned by the admin polish loop.
3. **A11y holes in the new primitives** — `primitives-foundation.test.tsx` covers Skeleton's `aria-hidden`, Alert's role split (destructive→`alert`, others→`status`), Field's `aria-invalid`/`aria-describedby` cloning, Spinner's `role="status"` + label. No holes found.
4. **`<LinkButton>` single `<a>` output** — addressed by the test that asserts `container.querySelectorAll("button").length === 0`. The disabled-state defect is what Codex flagged; the non-disabled output is correct.
5. **`useHydrated()` SSR safety** — hook uses `useState(false)` + `useEffect(() => setHydrated(true), [])` which is the canonical pattern. No SSR mismatch risk: server renders with `hydrated=false`, client first paint matches, then useEffect flips to `true` after hydration.
6. **VR baselines actually show intended pages** — file sizes confirm: home/catalog ~1.0–1.1 MB (long full-page captures), login/register 33–40 KB (centred-card layouts). No stale or login-page-mistaken captures in the 8 public baselines.

For the *next* Codex rescue (after loop 6), I'll either:
- Run `codex review --uncommitted "<priority prompt>"` against a temporary worktree that stages loops 4–6 as uncommitted changes, OR
- Run `codex review --commit <SHA> "<priority prompt>"` once per loop (3 invocations), letting the prompt actually steer.

Both work around the `--base <branch>` grammar's inability to accept a prompt.

## Action items

- [x] **Loop 4 commit:** fix `LinkButton` disabled handling.
- [x] **Loop 4 commit:** add vitest coverage for the disabled contract.
- [ ] **Future loop:** clean up `admin/evals/ScoreBadge` + `LLMTracesTab` StatusBadge raw Tailwind hues (queued in AUDIT.md §7 step 13 — admin polish).

## Codex session metadata

- Model: gpt-5.5
- Exit code: 0
- Token usage: 25,894
- Duration: 258 s
- Full transcript (234 KB): `/home/ubuntu/.claude/projects/-home-ubuntu-projects-E-Learning-Platform/ae52b8db-37fb-43ed-983b-c7fa91306ced/tool-results/blul6fzqf.txt`
