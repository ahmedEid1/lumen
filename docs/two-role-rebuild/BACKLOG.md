# Two-Role Rebuild — Post-Ship Backlog

> Honest backlog captured after **2.0.0-two-role** shipped to prod (2026-06-06, merge c212b3c).
> One line per item, severity-tagged. Sourced from the W11 local walk, the W12 prod live walk, and
> operator/deploy transcripts. Severity: P1 broken/urgent · P2 should-fix-soon · P3 polish/hygiene.

## P2 — should fix soon

- **P2 — prod SMTP unconfigured.** MITIGATED (EMAIL_ENABLED=false on prod) — real provider still a user decision. `send_email` now short-circuits at the service level when `EMAIL_ENABLED=false`, logging one `email_disabled_skipped` line instead of letting verify-email/reset/digest Celery tasks retry-crash on `socket.gaierror` (was 7 tracebacks/registration; prod never had an SMTP host). Flip `EMAIL_ENABLED=true` once a mail provider is wired.
- **P2 — rotate the Cloudflare `EMBEDDING_OPENAI_API_KEY`.** Surfaced in an operator transcript during the 2026-06-06 deploy diagnosis; rotate the embedding provider key.

## P3 — polish / hygiene

- **P3 — brief elicitation misses time-budget from compound replies.** When a user answers several intake questions in one message, time-budget extraction is dropped and the agent re-asks; the 6-turn cap saves the UX but it reads as not-listening. (Observed on the W12 prod walk.)
- **P3 — "Instructor studio" heading copy.** Stale three-role framing; everyone authors now — reword the studio heading.
- **P3 — BYOK model-select pristine state.** When a provider exposes only one model, Save stays disabled until the select is explicitly touched; default-select the sole option (or treat single-option as touched).
- **P3 — e2e-user rows pollute dev `/admin/users`.** Playwright-created `e2e-*` users accumulate in the dev DB and clutter the admin users list; add a data-hygiene sweep.
- **P3 — consolidate `common.deletedUser` vs `discussions.deletedUser`.** Two i18n keys carry the same deleted-user label; collapse to one shared key.
