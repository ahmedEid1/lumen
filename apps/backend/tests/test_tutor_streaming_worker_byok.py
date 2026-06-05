"""F4 + F3b worker-side coverage for ``_run_turn_async``.

ADR-0027 §4 item 3 (streaming arm) + §Consequences (the missing
``llm_calls`` row). This file tests the *orchestration wiring* inside
``app.workers.tasks.tutor_streaming._run_turn_async`` — NOT the DB. The
task builds its own NullPool engine via ``make_worker_engine`` and its
own Redis client, so we patch those seams plus the service calls the body
fans out to, then assert on the mocks:

- F4 / Gate-A drift: a no-consent ``ByokModelUnavailableError`` raised by
  ``stream_dispatch_for_turn`` must FAIL the turn (the dispatch resolution
  is no longer suppress-wrapped) and ``orchestrate_stream`` must never run.
- F4 / Gate-B auth: an auth-class error raised mid-stream marks the turn's
  credential invalid via ``mark_credential_invalid``.
- F3b / Gate-B row: every terminal transition persists an ``llm_calls``
  row via ``record_streamed_turn_row`` — ``billing_mode="byok"`` when a
  dispatch dict was resolved, ``"platform"`` when not.

DB-free: pure unittest.mock. Run with ``-n 0 --no-cov``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.errors import ByokModelUnavailableError
from app.models.llm_call import BILLING_BYOK, BILLING_PLATFORM, STATUS_ERROR, STATUS_OK
from app.models.tutor_turn_job import TURN_STATUS_COMPLETE, TURN_STATUS_FAILED
from app.workers.tasks import tutor_streaming

BYOK_DISPATCH = {
    "transport": "openai",
    "base_url": "x",
    "api_key": "k",
    "model": "m",
}


class _AuthenticationError(Exception):
    """SDK-shaped: openai/anthropic raise *AuthenticationError* on 401."""


def _make_turn(*, credential_id: str | None) -> MagicMock:
    """A claimed tutor_turn_job row with just the attrs the body reads.

    ``reserved_cost_usd=0`` keeps the reconcile-cost branch off (it only
    fires when reserved microcents > 0), so the test stays focused on the
    dispatch/terminal-row wiring rather than the budget bucket.
    """
    turn = MagicMock()
    turn.user_id = "u_worker"
    turn.conversation_id = "conv_1"
    turn.course_id = None  # skip the L32 retrieval branch entirely
    turn.user_message = "what is a closure?"
    turn.reservation_ip_key = None
    turn.credential_id = credential_id
    turn.reserved_cost_usd = Decimal("0")
    return turn


@asynccontextmanager
async def _session_cm(session):
    yield session


def _patch_worker_seams(monkeypatch, *, turn, mocks):
    """Patch the engine/redis/session-factory + service fan-out seams.

    ``mocks`` is mutated in place to expose the AsyncMocks the tests assert
    on. The session factory yields a fresh MagicMock session per ``Session()``
    call (the body opens several short-lived sessions).
    """
    # Engine + redis are infrastructure; give them async cleanup hooks.
    engine = MagicMock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr(tutor_streaming, "make_worker_engine", lambda: engine)

    redis_client = MagicMock()
    redis_client.aclose = AsyncMock()
    monkeypatch.setattr(
        tutor_streaming.redis.Redis, "from_url", MagicMock(return_value=redis_client)
    )

    def _session_factory(*_a, **_k):
        db = MagicMock()
        db.commit = AsyncMock()
        return lambda: _session_cm(db)

    monkeypatch.setattr(tutor_streaming, "async_sessionmaker", _session_factory)

    claim = AsyncMock(return_value=turn)
    monkeypatch.setattr(tutor_streaming, "claim_pending_turn", claim)

    mark_terminal = AsyncMock(return_value=True)
    monkeypatch.setattr(tutor_streaming, "mark_terminal", mark_terminal)

    record_row = AsyncMock()
    monkeypatch.setattr(tutor_streaming, "record_streamed_turn_row", record_row)

    # S6.8 cooperative-cancellation heartbeat — a DB-free unit test mocks the
    # session, so the account.assert_account_active re-read can't run against the
    # MagicMock session. Stub the seam to a no-op (the cancellation behaviour is
    # covered DB-backed in test_cooperative_cancel.py).
    monkeypatch.setattr(tutor_streaming.account_service, "assert_account_active", AsyncMock())
    monkeypatch.setattr(tutor_streaming, "emit_event", AsyncMock())
    monkeypatch.setattr(tutor_streaming, "set_stream_ttl", AsyncMock())
    monkeypatch.setattr(tutor_streaming, "reconcile_cost", AsyncMock())
    monkeypatch.setattr(tutor_streaming, "release_concurrency", AsyncMock())
    # Retrieval is gated behind course_id (None here) but patch defensively.
    monkeypatch.setattr(tutor_streaming, "run_retriever", AsyncMock())

    # Confirm-round C2: a credential that resolves to a None dispatch (drift
    # fallback to platform) now reserves platform cost worker-side and stamps
    # the row. Both seams default to "succeeded" so the happy-path fallback
    # tests stay green; the cap-refusal test overrides reserve_cost per-test.
    reserve_cost = AsyncMock(return_value=(True, "ok"))
    monkeypatch.setattr(tutor_streaming, "reserve_cost", reserve_cost)
    set_reserved = AsyncMock(return_value=True)
    monkeypatch.setattr(tutor_streaming, "set_reserved_cost", set_reserved)

    mocks["mark_terminal"] = mark_terminal
    mocks["record_row"] = record_row
    mocks["claim"] = claim
    mocks["reserve_cost"] = reserve_cost
    mocks["set_reserved_cost"] = set_reserved


# ---------------------------------------------------------------------
# F4 — no-consent drift FAILS the turn; orchestrate_stream never runs.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_consent_drift_fails_turn(monkeypatch) -> None:
    turn = _make_turn(credential_id="cred_drift")
    mocks: dict = {}
    _patch_worker_seams(monkeypatch, turn=turn, mocks=mocks)

    # The dispatch resolution is no longer suppress-wrapped (F4): a stored
    # model that drifted out of the allowlist with no platform-fallback
    # consent raises here and must propagate to the generic handler.
    monkeypatch.setattr(
        tutor_streaming.byok_service,
        "stream_dispatch_for_turn",
        AsyncMock(side_effect=ByokModelUnavailableError("model drifted")),
    )
    # Auth-class check on the drift error must be False (it's not 401/403).
    monkeypatch.setattr(tutor_streaming.byok_service, "is_auth_error", lambda exc: False)

    orchestrate = MagicMock()
    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", orchestrate)

    with pytest.raises(ByokModelUnavailableError):
        await tutor_streaming._run_turn_async("turn_drift")

    # The turn was FAILED, not completed, with the drift error's class name.
    assert mocks["mark_terminal"].await_count == 1
    _args, kwargs = mocks["mark_terminal"].await_args
    assert kwargs["status"] == TURN_STATUS_FAILED
    assert "ByokModelUnavailable" in kwargs["error_code"]

    # Hard invariant: the platform model was NEVER dispatched on a turn the
    # user explicitly forbade falling back. orchestrate_stream not called.
    orchestrate.assert_not_called()


# ---------------------------------------------------------------------
# F4 — auth-class error mid-stream marks the credential invalid.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_error_marks_credential_invalid(monkeypatch) -> None:
    turn = _make_turn(credential_id="cred_auth")
    mocks: dict = {}
    _patch_worker_seams(monkeypatch, turn=turn, mocks=mocks)

    monkeypatch.setattr(
        tutor_streaming.byok_service,
        "stream_dispatch_for_turn",
        AsyncMock(return_value=dict(BYOK_DISPATCH)),
    )
    mark_invalid = AsyncMock()
    monkeypatch.setattr(tutor_streaming.byok_service, "mark_credential_invalid", mark_invalid)
    # Use the real classifier so the test exercises the actual is_auth_error
    # contract against the SDK-shaped AuthenticationError name.
    assert tutor_streaming.byok_service.is_auth_error(_AuthenticationError("x")) is True

    def _orchestrate(**_kwargs):
        async def _gen():
            # Stream starts, then the provider 401s mid-iteration.
            yield {"event": "synth_chunk", "data": {"delta": "thinking"}}
            raise _AuthenticationError("401 bad key x-request-id=req_LEAK")

        return _gen()

    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", _orchestrate)

    with pytest.raises(_AuthenticationError):
        await tutor_streaming._run_turn_async("turn_auth")

    # The credential the turn carried is marked invalid (one-time notice).
    mark_invalid.assert_awaited_once()
    inv_args, _inv_kwargs = mark_invalid.await_args
    # Signature is mark_credential_invalid(db, credential_id) — positional.
    assert "cred_auth" in inv_args

    # And the failed turn still wrote a BYOK error row (failing key counts
    # toward the request window — no unmetered retries).
    assert mocks["record_row"].await_count == 1
    _r_args, r_kwargs = mocks["record_row"].await_args
    assert r_kwargs["status"] == STATUS_ERROR
    assert r_kwargs["billing_mode"] == BILLING_BYOK


# ---------------------------------------------------------------------
# F3b — completed turn persists an llm_calls row at the terminal transition.
# ---------------------------------------------------------------------


def _completed_orchestrator(monkeypatch):
    """Patch orchestrate_stream to a happy-path generator: a synth chunk
    then a turn_complete carrying cost_usd=0.002 / total_ms=123 plus the
    S7 provider token usage (prompt_tokens=200 / completion_tokens=55)."""

    def _orchestrate(**_kwargs):
        async def _gen():
            yield {"event": "synth_chunk", "data": {"delta": "a closure is..."}}
            yield {
                "event": "turn_complete",
                "data": {
                    "cost_usd": 0.002,
                    "total_ms": 123,
                    "first_token_ms": 10,
                    "prompt_tokens": 200,
                    "completion_tokens": 55,
                },
            }

        return _gen()

    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", _orchestrate)


@pytest.mark.asyncio
async def test_completed_turn_writes_byok_row(monkeypatch) -> None:
    turn = _make_turn(credential_id="cred_ok")
    mocks: dict = {}
    _patch_worker_seams(monkeypatch, turn=turn, mocks=mocks)

    monkeypatch.setattr(
        tutor_streaming.byok_service,
        "stream_dispatch_for_turn",
        AsyncMock(return_value=dict(BYOK_DISPATCH)),
    )
    monkeypatch.setattr(tutor_streaming.byok_service, "is_auth_error", lambda exc: False)
    _completed_orchestrator(monkeypatch)

    await tutor_streaming._run_turn_async("turn_ok_byok")

    # Terminal transition = complete.
    _mt_args, mt_kwargs = mocks["mark_terminal"].await_args
    assert mt_kwargs["status"] == TURN_STATUS_COMPLETE

    # llm_calls row: ok / byok (dispatch dict present) / real cost+latency.
    assert mocks["record_row"].await_count == 1
    _args, kwargs = mocks["record_row"].await_args
    assert kwargs["status"] == STATUS_OK
    assert kwargs["billing_mode"] == BILLING_BYOK
    assert kwargs["cost_usd"] == pytest.approx(0.002)
    assert kwargs["latency_ms"] == 123
    # BYOK provider/model labels come from the dispatch dict, not settings.
    assert kwargs["provider"] == "openai"
    assert kwargs["model"] == "m"
    # S7: provider-reported token usage off the terminal chunk is persisted.
    assert kwargs["prompt_tokens"] == 200
    assert kwargs["completion_tokens"] == 55


@pytest.mark.asyncio
async def test_completed_turn_writes_platform_row(monkeypatch) -> None:
    # No credential on the turn → stream_dispatch_for_turn returns None and
    # the body never even resolves a dispatch dict; billing_mode is platform.
    turn = _make_turn(credential_id=None)
    mocks: dict = {}
    _patch_worker_seams(monkeypatch, turn=turn, mocks=mocks)

    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(tutor_streaming.byok_service, "stream_dispatch_for_turn", dispatch)
    _completed_orchestrator(monkeypatch)

    await tutor_streaming._run_turn_async("turn_ok_platform")

    # credential_id is None, so the dispatch-resolution block is skipped.
    dispatch.assert_not_called()

    _mt_args, mt_kwargs = mocks["mark_terminal"].await_args
    assert mt_kwargs["status"] == TURN_STATUS_COMPLETE

    assert mocks["record_row"].await_count == 1
    _args, kwargs = mocks["record_row"].await_args
    assert kwargs["status"] == STATUS_OK
    assert kwargs["billing_mode"] == BILLING_PLATFORM
    # S7: a completed platform turn also persists the provider token usage.
    assert kwargs["prompt_tokens"] == 200
    assert kwargs["completion_tokens"] == 55


@pytest.mark.asyncio
async def test_completed_turn_with_credential_but_null_dispatch_is_platform(
    monkeypatch,
) -> None:
    """Consented drift-fallback: a credential is set but stream_dispatch
    resolves to None (drift + allow_platform_fallback=True). The turn runs
    on the platform model and the row is billed platform."""
    turn = _make_turn(credential_id="cred_fallback")
    mocks: dict = {}
    _patch_worker_seams(monkeypatch, turn=turn, mocks=mocks)

    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(tutor_streaming.byok_service, "stream_dispatch_for_turn", dispatch)
    monkeypatch.setattr(tutor_streaming.byok_service, "is_auth_error", lambda exc: False)
    _completed_orchestrator(monkeypatch)

    await tutor_streaming._run_turn_async("turn_fallback")

    # The dispatch WAS attempted (credential present) but returned None.
    dispatch.assert_awaited_once()

    assert mocks["record_row"].await_count == 1
    _args, kwargs = mocks["record_row"].await_args
    assert kwargs["status"] == STATUS_OK
    assert kwargs["billing_mode"] == BILLING_PLATFORM


# ---------------------------------------------------------------------
# C2 — worker-side platform fallback reserves cost + stamps the row.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_dispatch_reserves_platform_cost(monkeypatch) -> None:
    """Confirm-round C2: a credential that resolves to a None dispatch
    (consented drift fallback to platform) now reserves platform dollars
    worker-side — the enqueue path skipped that reservation because the
    turn resolved BYOK. On success the row is stamped with the estimate via
    ``set_reserved_cost`` and the turn runs normally."""
    from app.core.config import get_settings
    from app.core.cost_scripts import USD_TO_MICROCENTS

    turn = _make_turn(credential_id="cred_fallback")
    mocks: dict = {}
    _patch_worker_seams(monkeypatch, turn=turn, mocks=mocks)

    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(tutor_streaming.byok_service, "stream_dispatch_for_turn", dispatch)
    monkeypatch.setattr(tutor_streaming.byok_service, "is_auth_error", lambda exc: False)

    orchestrated: list[bool] = []

    def _orchestrate(**_kwargs):
        orchestrated.append(True)

        async def _gen():
            yield {"event": "synth_chunk", "data": {"delta": "x"}}
            yield {
                "event": "turn_complete",
                "data": {"cost_usd": 0.001, "total_ms": 50, "first_token_ms": 5},
            }

        return _gen()

    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", _orchestrate)

    await tutor_streaming._run_turn_async("turn_fallback_reserve")

    # The credential WAS resolved (returned None) → worker reserved platform $.
    dispatch.assert_awaited_once()
    mocks["reserve_cost"].assert_awaited_once()

    # The row was stamped with the estimate (Decimal microcents / 1e6).
    estimate = get_settings().tutor_estimate_microcents
    expected = Decimal(estimate) / Decimal(USD_TO_MICROCENTS)
    mocks["set_reserved_cost"].assert_awaited_once()
    _sr_args, sr_kwargs = mocks["set_reserved_cost"].await_args
    assert sr_kwargs["turn_id"] == "turn_fallback_reserve"
    assert sr_kwargs["reserved_cost_usd"] == expected

    # Orchestration ran (reservation succeeded → stream proceeds) + completed.
    assert orchestrated == [True]
    _mt_args, mt_kwargs = mocks["mark_terminal"].await_args
    assert mt_kwargs["status"] == TURN_STATUS_COMPLETE


@pytest.mark.asyncio
async def test_fallback_dispatch_cap_refusal_fails_turn(monkeypatch) -> None:
    """Confirm-round C2: when the worker-side platform reservation is
    REFUSED (e.g. user cap), the turn fails with a
    ``PlatformFallbackCapError`` and ``orchestrate_stream`` never runs — the
    platform model is never dispatched for a turn whose dollars were denied."""
    turn = _make_turn(credential_id="cred_fallback_cap")
    mocks: dict = {}
    _patch_worker_seams(monkeypatch, turn=turn, mocks=mocks)

    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(tutor_streaming.byok_service, "stream_dispatch_for_turn", dispatch)
    monkeypatch.setattr(tutor_streaming.byok_service, "is_auth_error", lambda exc: False)
    # The reservation refuses (user cap exhausted).
    mocks["reserve_cost"].return_value = (False, "user_cap")

    orchestrate = MagicMock()
    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", orchestrate)

    with pytest.raises(tutor_streaming.PlatformFallbackCapError):
        await tutor_streaming._run_turn_async("turn_fallback_cap")

    # The reservation was attempted but refused → turn FAILED with the cap
    # error's class name; the row was NEVER stamped (no reservation held).
    mocks["reserve_cost"].assert_awaited_once()
    mocks["set_reserved_cost"].assert_not_awaited()

    _mt_args, mt_kwargs = mocks["mark_terminal"].await_args
    assert mt_kwargs["status"] == TURN_STATUS_FAILED
    assert "PlatformFallbackCapError" in mt_kwargs["error_code"]

    # Hard invariant: the platform model was NEVER dispatched.
    orchestrate.assert_not_called()


# ---------------------------------------------------------------------
# F3b — a non-auth failure also persists a (platform/byok) error row.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_turn_writes_error_row_and_no_credential_invalidation(
    monkeypatch,
) -> None:
    """A transient (non-auth) failure on a BYOK turn writes a byok error
    row but does NOT mark the credential invalid (item 4: only auth-class
    failures invalidate)."""
    turn = _make_turn(credential_id="cred_transient")
    mocks: dict = {}
    _patch_worker_seams(monkeypatch, turn=turn, mocks=mocks)

    monkeypatch.setattr(
        tutor_streaming.byok_service,
        "stream_dispatch_for_turn",
        AsyncMock(return_value=dict(BYOK_DISPATCH)),
    )
    mark_invalid = AsyncMock()
    monkeypatch.setattr(tutor_streaming.byok_service, "mark_credential_invalid", mark_invalid)
    # Real classifier: a RuntimeError is not auth-class.
    assert tutor_streaming.byok_service.is_auth_error(RuntimeError("timeout")) is False

    def _orchestrate(**_kwargs):
        async def _gen():
            yield {"event": "synth_chunk", "data": {"delta": "x"}}
            raise RuntimeError("connection timed out")

        return _gen()

    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", _orchestrate)

    with pytest.raises(RuntimeError):
        await tutor_streaming._run_turn_async("turn_transient")

    # Failed + byok error row.
    _mt_args, mt_kwargs = mocks["mark_terminal"].await_args
    assert mt_kwargs["status"] == TURN_STATUS_FAILED
    assert mocks["record_row"].await_count == 1
    _args, kwargs = mocks["record_row"].await_args
    assert kwargs["status"] == STATUS_ERROR
    assert kwargs["billing_mode"] == BILLING_BYOK

    # Transient failure never invalidates the key.
    mark_invalid.assert_not_called()

    # S7: the stream died before any turn_complete usage chunk arrived, so the
    # error row records honest zero tokens — we claim only what the provider
    # actually billed. The failure-path call omits the token kwargs entirely,
    # so they fall back to record_streamed_turn_row's 0 defaults.
    assert kwargs.get("prompt_tokens", 0) == 0
    assert kwargs.get("completion_tokens", 0) == 0


@pytest.mark.asyncio
async def test_stream_aborts_after_partial_tokens_records_zero(monkeypatch) -> None:
    """S7 honest-abort: a stream that yields synth chunks but then raises
    BEFORE the terminal turn_complete event records zero tokens on the error
    row. The worker only captures tokens from turn_complete, which never fired
    here — so no usage is fabricated from the partial stream."""
    turn = _make_turn(credential_id=None)
    mocks: dict = {}
    _patch_worker_seams(monkeypatch, turn=turn, mocks=mocks)

    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(tutor_streaming.byok_service, "stream_dispatch_for_turn", dispatch)
    monkeypatch.setattr(tutor_streaming.byok_service, "is_auth_error", lambda exc: False)

    def _orchestrate(**_kwargs):
        async def _gen():
            yield {"event": "synth_chunk", "data": {"delta": "half an answer"}}
            yield {"event": "synth_chunk", "data": {"delta": " and then..."}}
            raise RuntimeError("upstream reset before usage chunk")

        return _gen()

    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", _orchestrate)

    with pytest.raises(RuntimeError):
        await tutor_streaming._run_turn_async("turn_partial_abort")

    _mt_args, mt_kwargs = mocks["mark_terminal"].await_args
    assert mt_kwargs["status"] == TURN_STATUS_FAILED

    assert mocks["record_row"].await_count == 1
    _args, kwargs = mocks["record_row"].await_args
    assert kwargs["status"] == STATUS_ERROR
    assert kwargs["billing_mode"] == BILLING_PLATFORM
    # Honest zeros — the provider's usage chunk never arrived.
    assert kwargs.get("prompt_tokens", 0) == 0
    assert kwargs.get("completion_tokens", 0) == 0
