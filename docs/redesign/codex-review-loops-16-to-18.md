# Codex review — Loops 16-18 (Block renderer + Course detail + Mastery/Path viz + RTL + Cmd+K)

Date: 2026-05-26
Codex CLI: v0.133.0
Scope: commits `5d4a513` (Loop 16) + `ebbf49d` (Loop 17) + `a041d91` (Loop 18) — diff against `a092c5b`.
Command: `codex review --base a092c5b`

## Findings

**None.** Codex's verdict: *"I did not find any discrete, actionable bugs introduced by the changes. The frontend typecheck also passes with incremental output disabled in the read-only workspace."*

Codex's exploration trace (3,694 lines, persisted at `~/.claude/.../tool-results/brcvjai0s.txt`) shows it read into:
- The Loop 18 `CommandPalette` surface area + `cmdk` integration
- `LessonVideo`'s `crossOrigin` handling
- The PDF certificate fetch path
- `slugToTitle` helper
- `Skeleton` + `Progress` primitives + the `--info` token in `globals.css`
- `CourseListItem` type
- `apps/frontend/package.json` for cmdk dep version

Codex then concluded there are no actionable issues.

## Note on Codex CLI grammar

`codex review --base <sha> "<focus prompt>"` is rejected in v0.133.0. Ran without the prompt — Codex did its default review.

This is the cleanest rescue so far. Loop 12's rescue caught 2 P2 regressions; Loop 15's caught 2 P1 regressions (one diff-scope, one real); this rescue caught nothing. Suggests the local-first workflow (introduced for Loop 15) is genuinely catching regressions pre-push.

## Self-review on the 8 focus questions

Codex couldn't see the focus questions because of the CLI grammar quirk. Brief self-review:

1. **CommandPalette listener cleanup.** `useEffect` returns both removals (`keydown` + `lumen:open-command-palette`). No leaks.
2. **Cmd+K browser conflicts.** `e.preventDefault()` on keydown when both `e.key === "k"` and (`metaKey` or `ctrlKey`) — that's the standard pattern. Firefox's bookmark search uses Ctrl+B not Ctrl+K, so no conflict there. Other shortcuts (Cmd+K in macOS Mail = clear search) are app-internal and don't bubble to web.
3. **`shouldFilter={false}` + manual filter.** Cmdk's built-in filter is fuzzy-match; for our `t()`-translated labels a simple `includes()` is more predictable. Pattern is sound — items not matching are filtered out before being rendered, so the Command.List's empty-state surfaces correctly.
4. **CustomEvent bus for header→palette.** Stateless + decoupled — no context/store needed for one-way fire-and-forget. The custom-event listener is symmetric with the keydown listener (both call `setOpen(true)`).
5. **`new Error` vs `ApiError`.** Single callsite, locally caught + toasted. Acceptable.
6. **slugToTitle**: no proper-noun handling. Documented as an acceptable trade-off; real `course_title` would need a backend change.
7. **`crossOrigin="anonymous"` scoped to captions.** Confirmed by the source comment: bare-presigned MinIO URLs fail CORS preflight if crossOrigin is set always-on.
8. **RTL leaks.** Sweep hit the 4 audit-listed leaks. A fresh grep for `left-[0-9]|text-left|right-[0-9]|text-right` shows only the leaks we fixed; no new ones.

## Time spent

- Codex run #1 (Loop 18 not yet committed → diff-scope artifact): ~2 min.
- Loop 18 commit + Codex run #2 (clean): ~3 min.
- Self-review on focus questions + digest: ~5 min.

Total: ~10 min. Within rescue budget. Clean signal that local-first verification is working.
