# Screenshots

This directory holds the screenshots referenced from the top-level [`README.md`](../../README.md).

## Conventions

- File names are lowercase-kebab-case (`hero.png`, `tutor-trace.png`, `eval-dashboard.png`).
- Source format is PNG at 2x retina width (the README's hero target is 2400 x 1500). Keep individual files under ~500 KB; run them through `oxipng -o4` or equivalent before committing.
- One hero (`hero.png`) is referenced unconditionally from the README; the rest are optional inline references from prose.

## Pending captures

These slots are referenced from the README with `_TBD` comments and are owned by the operator (Ahmed) — they need a working live demo (Phase H, item H4) before they can be captured:

- `hero.png` — the tutor surface on a real course with a citation pill open and the agent-trace expander visible. This is the screenshot a recruiter sees first; it should make the "agentic-AI engineering signature project" framing legible at a glance.
- *(future)* `tutor-trace.png` — the planner-orchestrator's tool-call log on a single turn (after Phase I, item I2 lands).
- *(future)* `eval-dashboard.png` — `/admin/evals` with a real tutor-suite run plotted against the previous one.
- *(future)* `mcp-claude-desktop.png` — Claude Desktop's tool sidebar showing Lumen's MCP tools firing on `'list my courses'` (after Phase I, item I1 lands).

## Why this directory exists before the screenshots do

Phase H, item H5 (the README rewrite) lands ahead of H4 (the live demo) so the README's positioning is ready to take the live URL as soon as H4 ships. The README references `docs/screenshots/hero.png`; this placeholder directory keeps that link from looking broken on the repo browser between H5 landing and H4's first screenshot being captured.
