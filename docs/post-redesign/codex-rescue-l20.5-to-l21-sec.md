# Codex rescue — post-redesign L20.5 → L21-Sec arc

**Date:** 2026-05-27
**Diff scope:** `31d8fc3..41e66f8` (3 loops + 1 hash backfill)
**Codex command:** `codex review --base 31d8fc3 --title "L19.5+L20.5+L20.6+L21-Sec rescue: ..."`

## CLI limitation surfaced

`codex review --base <sha>` does NOT accept a positional prompt. The
detailed focus-area prompt I prepared (security primitives correctness,
sentry scrubber completeness, email-verify race, IDOR coverage, anon
endpoints, demo seed idempotency) could only be delivered via
`--title`. For deeper area-specific review, use `codex review --commit
<sha>` per loop — that variant accepts a full prompt.

Filing this gap as a memory update so future rescues use the right
invocation shape.

## Findings (verbatim)

### P1: Cast the audit JSON without PostgreSQL shorthand

> `/home/ubuntu/projects/E-Learning-Platform/apps/backend/alembic/versions/2026_07_27_0027-0027_l21sec_grandfather_email_verify_and_tutor_turn_jobs.py:85`
>
> When there are existing users to grandfather, this migration enters
> the audit insert path, but SQLAlchemy `text()` does not treat
> `:data` as a bind parameter when it is immediately followed by
> PostgreSQL's `::jsonb` cast. The statement is sent with the literal
> `:data::jsonb`, so `alembic upgrade head` fails before creating
> `tutor_turn_jobs` on any non-empty deployment. Use a bind-friendly
> cast such as `CAST(:data AS jsonb)` or a typed bind parameter.

**Why CI didn't catch it:** the test DB is empty, so the `if count > 0`
branch never runs. The bug only fires on prod (which has real users).

**Fix:** swap to `CAST(:data AS jsonb)` (commit in this rescue).
Regression test in `tests/test_grandfather_migration_audit.py` exercises
both the fixed shape (succeeds) and the buggy shape (raises) so a
future refactor can't silently regress.

### P1: Limit grandfathering to pre-deploy accounts

> `/home/ubuntu/projects/E-Learning-Platform/apps/backend/app/main.py:313-315`
>
> Because this boot hook updates every `email_verified_at IS NULL`
> row unconditionally on every API start, any user who registers
> after this deploy but has not clicked the verification email will
> be marked verified on the next restart. That bypasses the existing
> email-verification flow for newly registered accounts; the backstop
> needs a cutoff or other marker so it only covers accounts from the
> migration/deploy window.

**Why this is exactly the right call-out:** plan-v7 §V7-F9 already
specified the cutoff design (`settings.l21sec_deploy_timestamp`).
The implementation just didn't honour it.

**Fix:** added `Settings.l21sec_deploy_timestamp: datetime` (defaults
to the L21-Sec migration timestamp, 2026-05-27 00:00 UTC). Boot hook
now reads it and adds `AND created_at < :cutoff` to the UPDATE.
Regression tests in `tests/test_grandfather_boot_hook.py` cover:
1. Pre-deploy user → grandfathered ✓
2. Post-deploy user → NOT grandfathered ✓ (the critical case)

## What Codex did NOT flag

Codex did not surface any issues in:

- The Lua cost scripts (4 files + Python wrapper)
- The subprocess code-runner
- The LLM sanitizer
- The Sentry scrubber
- The two new anon endpoints (`/runtime-flags`, `/demo-questions`)
- IDOR contract tests
- Demo seed idempotency
- The new ADRs (0017/0018/0019)

That's either "those areas are clean" OR "Codex didn't dig into them
because the `--title`-only invocation is less steering than a full
focus-area prompt." The CLI-limitation memory entry covers the latter
for next time.

## Rescue scope

3 commits total (1 fix, 2 regression tests):

| File | Change |
|---|---|
| `apps/backend/alembic/versions/.../0027*.py` | `:data::jsonb` → `CAST(:data AS jsonb)` |
| `apps/backend/app/main.py` | Boot hook reads `settings.l21sec_deploy_timestamp` + adds `AND created_at < :cutoff` |
| `apps/backend/app/core/config.py` | New `Settings.l21sec_deploy_timestamp` field + datetime import |
| `apps/backend/tests/test_grandfather_boot_hook.py` (new) | Pre-deploy vs post-deploy grandfathering |
| `apps/backend/tests/test_grandfather_migration_audit.py` (new) | Audit-INSERT cast shape locked |

## Test results

```
$ docker compose exec api pytest tests/test_grandfather_boot_hook.py \
    tests/test_grandfather_migration_audit.py -v --no-cov
4 passed in 12.42s
```

Backend suite remains 697/697 + 4 = **701 / 701** green.

## Next loop

L21a — backend streaming flag-OFF. Celery task `tutor.run_turn.v1`,
Redis Streams emit, AsyncIterator orchestrator, AsyncOpenAI streaming,
sweep beat job, orphan cleanup beat. Per the every-3-loop cadence
post-rescue, L24 is the next Codex rescue checkpoint.
