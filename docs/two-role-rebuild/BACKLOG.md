# Two-Role Rebuild — Post-Ship Backlog

> Honest backlog captured after **2.0.0-two-role** shipped to prod (2026-06-06, merge c212b3c).
> One line per item, severity-tagged. Sourced from the W11 local walk, the W12 prod live walk, and
> operator/deploy transcripts. Severity: P1 broken/urgent · P2 should-fix-soon · P3 polish/hygiene.

## P2 — should fix soon

- **P2 — prod SMTP unconfigured.** MITIGATED (EMAIL_ENABLED=false on prod) — real provider still a user decision. `send_email` now short-circuits at the service level when `EMAIL_ENABLED=false`, logging one `email_disabled_skipped` line instead of letting verify-email/reset/digest Celery tasks retry-crash on `socket.gaierror` (was 7 tracebacks/registration; prod never had an SMTP host). Flip `EMAIL_ENABLED=true` once a mail provider is wired.
- **P2 — rotate the Cloudflare `EMBEDDING_OPENAI_API_KEY`.** Surfaced in an operator transcript during the 2026-06-06 deploy diagnosis (exposure: local session transcripts + Anthropic conversation retention only — never git/CI/public; token is Workers-AI-inference-scoped). **DEFERRED by owner 2026-06-06** — accepted risk for now. To rotate later: dash.cloudflare.com as the account owner → My Profile → API Tokens → roll token `fb754872b91fac5f5deb95056b8afaa1` (or mint a Workers AI: Read replacement) → drop the value in a file on the dev box and have the operator swap it into prod env via the deploy workflow (never bare `up -d` — IMAGE_TAG trap).

## P3 — polish / hygiene

- ~~P3 — brief elicitation misses time-budget from compound replies~~ **DONE 2026-06-06** (8e83d6a — rate×duration prompt rules + deterministic regex fallback that never overwrites LLM values + no-re-ask prompt pins; 109-test battery green).
- ~~P3 — "Instructor studio" heading copy~~ **DONE 2026-06-06** (7e76832 — reworded to "Studio", en+ar).
- ~~P3 — BYOK model-select pristine state~~ **DONE 2026-06-06** (f7d86b7 — provider change programmatically sets the first model in form state; Save enables honestly).
- ~~P3 — e2e-user rows pollute dev `/admin/users`~~ **DONE 2026-06-06** (d25495d + 053475a — `python -m app.cli prune-e2e-users` w/ dry-run + prod refusal, foreign-loop-safe; dev pruned).
- ~~P3 — consolidate `common.deletedUser` vs `discussions.deletedUser`~~ **DONE 2026-06-06** (6ef015d — single key `common.deletedUser`; parity green).

## Released

- **v2.0.0 tagged 2026-06-06** at 053475a — https://github.com/ahmedEid1/lumen/releases/tag/v2.0.0 (release.yml publishes arm64 `:v2.0.0` + `:latest`).
