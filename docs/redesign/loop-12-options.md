# Loop 12 — options

Three approaches considered.

## Option A — Tooltip only

Ship Tooltip + apply to theme toggle. Defer the 4 modal migrations.

- **Pros:** smallest diff, easiest review.
- **Cons:** AUDIT.md §3 specifically calls out the 4 hand-rolled modals as a11y holes (no focus trap, click-outside via `e.target === e.currentTarget`). The Dialog primitive shipped two loops ago; leaving consumers un-migrated is technical debt sitting next to a fix.

## Option B — All-overlay-debt-clear (chosen)

Tooltip + 4 modal migrations + Codex rescue #3 in one loop.

- **Pros:** closes the overlay primitive backlog completely. Foundation C is "done" as a tier — every overlay surface uses a Radix primitive. Codex rescue at the end validates the entire tier (Loops 10-12).
- **Cons:** estimate ~700 LoC, plus rescue-driven follow-ups could push higher. Soft cap is 2000 LoC; comfortable.

## Option C — Split: tooltip + 2 modals this loop, 2 modals + rescue next loop

Tooltip + ai-outline-modal + ingest-modal this loop. Onboarding-tour + profile delete + Codex rescue next.

- **Pros:** smaller per-loop diff.
- **Cons:** delays Codex rescue past the 3-loop anchor (cadence rules say loop 12 = rescue). Also: the 4 modals are mechanically similar (all `fixed inset-0` + manual Escape); batching them keeps the migration discipline tight (same `<Dialog>` import, same `<DialogContent>` chrome). Splitting tempts inconsistency.

## Decision

**Option B.** Reasons:
1. Each migration is ~30 LoC of chrome swap; the internals are preserved. 4 migrations = ~120 LoC, easily within budget.
2. Codex rescue cadence anchors here; pushing it later breaks the rhythm and lets review debt accumulate across 4 loops by Loop 15.
3. The "primitive + real consumer per loop" rule is satisfied — Tooltip lands with the theme-toggle consumer. The 4 modal migrations are bonus value, not the cost driver.
4. Foundation C closes out as a coherent tier: Loops 10-12 ship Dialog/Sheet/Popover/DropdownMenu/Tooltip + every overlay migration the audit flagged. The post-loop state is the design system the AUDIT.md §2 fill list called for.

## Concrete migration pattern (same shape for all 4)

```diff
- // Manual Escape listener
- useEffect(() => {
-   const onKey = (e: KeyboardEvent) => {
-     if (e.key === "Escape") { e.preventDefault(); onClose(); }
-   };
-   document.addEventListener("keydown", onKey);
-   return () => document.removeEventListener("keydown", onKey);
- }, [onClose]);

- // Hand-rolled chrome
- <div
-   role="dialog"
-   aria-modal="true"
-   aria-labelledby="…-title"
-   className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 px-4 py-8 backdrop-blur-sm"
-   onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
- >
-   <div className="surface flex max-h-[90vh] w-full max-w-3xl flex-col gap-4 overflow-hidden p-6 sm:p-8">
-     <header className="flex items-start justify-between gap-3">
-       <h2 id="…-title" className="…">{t("…title")}</h2>
-       <button onClick={onClose} className="…">{t("common.cancel")}</button>
-     </header>
-     {/* body */}
-   </div>
- </div>

+ <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
+   <DialogContent className="max-w-3xl">
+     <DialogHeader>
+       <DialogTitle>{t("…title")}</DialogTitle>
+     </DialogHeader>
+     {/* body */}
+   </DialogContent>
+ </Dialog>
```

The manual close button in the header goes away — `<DialogContent>` ships a built-in close X via `srLabelClose`. The Escape listener becomes Radix's responsibility. The click-outside via `e.target === e.currentTarget` becomes Radix's overlay click handler.
