# Codex rescue — L21a → L22 streaming arc

**Date:** 2026-05-27
**Diff scope:** `2ab45c1..56a3d56` (L21a + L21b + L22 + L22 ledger backfill)
**Codex command:** `codex review --base 2ab45c1 --title "L21a+L21b+L22 streaming arc rescue: …"` (CLI quirk from last rescue still applies — no positional prompt with `--base`).

## Findings (verbatim from Codex)

### P1: Start new streams from the beginning

> `apps/backend/app/api/v1/tutor_streaming.py:224`
>
> For an initial subscription after `POST /tutor/turns`, using `$`
> tells Redis to return only entries added after the `XREAD` begins.
> If the Celery worker emits any planner/synth/terminal events before
> the browser opens this GET (very likely for the current fast noop
> path), those events are skipped and the UI can sit blank/in-flight
> until the read times out. Initial reads should start from `0-0`
> (reserve `Last-Event-ID` only for resumes) so already-emitted turn
> events are replayed.

**Why this matters in practice:** the L21a noop orchestrator emits
its full event sequence in ~30 ms. The browser GET arrives ~100 ms
after the POST returns (request latency + React effect dispatch). The
browser would consistently see *no* events with the `$` offset.

**Fix:** `last_event_id or "0-0"` — Last-Event-ID only takes
precedence when present (resume).

### P1: Serialize SSE event data as JSON

> `apps/backend/app/api/v1/tutor_streaming.py:229-233`
>
> When Redis events are delivered to the SSE client,
> `_data_dict.__str__()` produces Python repr syntax with single
> quotes/`None`, not JSON. The new frontend reducer calls
> `JSON.parse(ev.data)`, so `synth_chunk` payloads fall into the
> parse-error path and `data.delta` is lost; the assistant text
> never renders even though chunks were emitted. Use
> `json.dumps(_data_dict)` for the SSE `data` field.

**Why this matters in practice:** the L21b reducer has a `try/catch`
around `JSON.parse(ev.data)`. The catch branch stores `{_raw: ev.data}`
in the snapshot. The synth-chunk reducer then reads `data.delta` —
which doesn't exist in the `{_raw}` shape — so the accumulated text
stays empty for the entire turn.

**Fix:** import `json`, use `json.dumps(_data_dict or {})`.

### P2: Preserve aborted terminal status

> `apps/backend/app/services/tutor_turn_service.py:132-138`
>
> Because `mark_terminal` updates by id regardless of the current
> status, a user who calls DELETE while the worker is still running
> can have the row marked `aborted`, but the worker later calls the
> same helper with `complete` and overwrites the cancellation. In
> that scenario `/status` reports a successful turn after
> cancellation; terminal transitions should avoid replacing an
> existing terminal state.

**Why this matters in practice:** the timing window is realistic — a
recruiter might hit "stop" mid-stream; if the orchestrator is in its
final synth chunk, it'll complete ~ms after the DELETE and silently
re-mark the row.

**Fix:** add `AND status NOT IN ('complete', 'failed', 'aborted')`
to the UPDATE; `mark_terminal` returns `bool` so callers can log the
no-op.

## What Codex did NOT flag

Areas Codex looked at and didn't comment on:

- Lua wire-up gaps (focus area #2) — implicit OK; the `reserved_cost_usd=0`
  + zero-magnitude reconcile is safe.
- IDOR coverage (focus area #5) — implicit OK; all four endpoints
  pass `user_id=current_user.id`.
- Hook race safety in `useTutorStream` (focus area #4) — implicit OK.
- Demo-question chip rail injection vectors (focus area #6) — implicit OK.

Per the [[codex-cli-flags]] memory note: `--base` review without a
positional prompt is less area-steering than `--commit` calls would
be. The clean review on those areas might be either "they really are
clean" or "Codex didn't dig there." The streaming arc's main risk
was always the wire-format + race correctness, and the rescue caught
both of those — so this is a useful confidence boost without being
exhaustive.

## Rescue scope

3 fixes (2 P1 + 1 P2) + 3 regression tests in one commit:

| File | Change |
|---|---|
| `apps/backend/app/api/v1/tutor_streaming.py` | `$` → `0-0` initial offset; `__str__()` → `json.dumps()` |
| `apps/backend/app/services/tutor_turn_service.py` | `mark_terminal` returns `bool` + WHERE clause refuses to overwrite terminal status |
| `apps/backend/tests/test_tutor_terminal_race.py` (new) | 3 regression tests covering pending→aborted, aborted-not-overwritten-by-complete, idempotent-on-same |

## Test results

```
$ docker compose exec api pytest tests/test_tutor_terminal_race.py \
    tests/test_tutor_streaming_endpoints.py -v --no-cov
8 passed in 15.61s
```

Backend suite: 708 → 711 green.

## Next loop

L23 — Turn drill-down at `/dashboard/tutor/{cid}/turn/{mid}` with
token/cost/latency breakdown + tool-step list. Closing CTA when the
per-IP cost cap is hit (cost-cap-hit-503 surface). Per the cadence,
next Codex rescue checkpoint is after L25.
