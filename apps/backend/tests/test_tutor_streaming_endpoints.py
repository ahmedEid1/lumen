"""L21a streaming-tutor endpoint coverage.

ALL four endpoints (POST/status/stream/cancel) gate on
``settings.feature_tutor_streaming``. While the flag is OFF (default
until L21b), every endpoint returns 503 ``tutor.streaming_disabled``.

These tests cover:
- 503 gating when flag is OFF (the default L21a state)
- Happy path when flag is ON (POST creates a pending row + enqueues)
- IDOR: status / cancel on another user's turn collapse to 404
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.tutor_turn_job import TURN_STATUS_ABORTED, TURN_STATUS_PENDING, TutorTurnJob
from app.models.user import Role


@pytest.fixture(autouse=True)
def _stub_celery_enqueue():
    """Don't fire real Celery enqueues during HTTP tests — Redis is
    mocked enough by conftest but `delay()` would still try to ship
    the task. Patch it to a no-op so the after_commit listener fires
    cleanly without hitting the broker."""
    with patch("app.workers.tasks.tutor_streaming.run_turn.delay") as m:
        m.return_value = None
        yield m


@pytest.fixture(autouse=True)
def _stub_cost_scripts():
    """L33 — stub the cost-cap + concurrency Lua wrappers so HTTP
    tests don't need a live Redis. The default returns let every
    request through; tests that want to exercise the cap branches
    monkey-patch these per-test via the yielded dict."""
    from unittest.mock import AsyncMock

    conc_mock = AsyncMock(return_value=(True, 1))
    res_mock = AsyncMock(return_value=(True, "ok"))
    rel_mock = AsyncMock(return_value=0)
    with (
        patch("app.api.v1.tutor_streaming.check_concurrency", conc_mock),
        patch("app.api.v1.tutor_streaming.reserve_cost", res_mock),
        patch("app.api.v1.tutor_streaming.release_concurrency", rel_mock),
    ):
        yield {
            "check_concurrency": conc_mock,
            "reserve_cost": res_mock,
            "release_concurrency": rel_mock,
        }


async def test_post_returns_503_when_streaming_disabled(client: AsyncClient, auth_headers) -> None:
    """Default state: flag OFF → 503 with the documented error code."""
    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "hi"},
        headers=headers,
    )
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "tutor.streaming_disabled"


async def test_status_returns_503_when_streaming_disabled(
    client: AsyncClient, auth_headers
) -> None:
    headers = await auth_headers(role=Role.student)
    r = await client.get("/api/v1/tutor/turns/anything/status", headers=headers)
    assert r.status_code == 503


async def test_delete_returns_503_when_streaming_disabled(
    client: AsyncClient, auth_headers
) -> None:
    headers = await auth_headers(role=Role.student)
    r = await client.delete("/api/v1/tutor/turns/anything", headers=headers)
    assert r.status_code == 503


async def test_post_creates_pending_row_when_flag_on(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """Flag ON: POST inserts a pending row + (mocked) enqueue fires."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "what is variance?"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == TURN_STATUS_PENDING
    turn_id = body["id"]

    # Row really exists with the expected status.
    row = await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    turn = row.scalar_one_or_none()
    assert turn is not None
    assert turn.status == TURN_STATUS_PENDING


async def test_post_with_course_slug_resolves_to_course_id(
    client: AsyncClient,
    auth_headers,
    make_user,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """L32 — POST /tutor/turns with a known course_slug stores the
    resolved course_id on the turn row. The Celery task reads it back
    to scope the pgvector retrieval."""
    import uuid

    from app.models.course import (
        Course,
        CourseStatus,
        Difficulty,
        ModerationState,
        Subject,
        Visibility,
    )

    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    owner = await make_user(role=Role.instructor)
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"L32 {suffix}", slug=f"l32-{suffix}")
    db_session.add(subject)
    await db_session.flush()
    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=f"L32 Course {suffix}",
        slug=f"l32-course-{suffix}",
        overview="o",
        difficulty=Difficulty.beginner,
        status=CourseStatus.published,
        # S2.6: the streaming slug lookup now gates on can_view_course, so a
        # non-owner student can only resolve a publicly-LISTED course.
        visibility=Visibility.public,
        moderation_state=ModerationState.approved,
    )
    db_session.add(course)
    await db_session.commit()

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "Q?", "course_slug": course.slug},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    turn_id = r.json()["id"]

    row = await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    turn = row.scalar_one_or_none()
    assert turn is not None
    assert turn.course_id == course.id
    assert turn.user_message == "Q?"


async def test_post_with_unknown_course_slug_returns_404(
    client: AsyncClient,
    auth_headers,
    monkeypatch,
) -> None:
    """L32 — unknown slug → 404, not 500. The streaming demo's caller
    (the frontend) won't normally hit this, but a typo in the URL bar
    on /learn/<slug> must surface as a clean error."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "Q?", "course_slug": "no-such-course-12345"},
        headers=headers,
    )
    assert r.status_code == 404, r.text


async def test_post_429_when_concurrency_cap_hit(
    client: AsyncClient,
    auth_headers,
    monkeypatch,
    _stub_cost_scripts,
) -> None:
    """L33 — concurrency check returns (False, N) → 429
    tutor.too_many_concurrent. Reserve_cost is never called because
    the concurrency check fences ahead of it (cheaper)."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)
    _stub_cost_scripts["check_concurrency"].return_value = (False, 3)

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "q"},
        headers=headers,
    )
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "tutor.too_many_concurrent"
    _stub_cost_scripts["reserve_cost"].assert_not_called()


async def test_post_429_when_user_cost_cap_hit_releases_concurrency(
    client: AsyncClient,
    auth_headers,
    monkeypatch,
    _stub_cost_scripts,
) -> None:
    """L33 — reserve_cost rejects with `user_cap` → 429
    tutor.user_cap. The handler MUST release the concurrency slot
    it just acquired (else the next retry consumes the slot too
    and the user can lock themselves out)."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)
    _stub_cost_scripts["reserve_cost"].return_value = (False, "user_cap")

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "q"},
        headers=headers,
    )
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "tutor.user_cap"
    _stub_cost_scripts["release_concurrency"].assert_called_once()


async def test_post_429_when_ip_cost_cap_hit(
    client: AsyncClient,
    auth_headers,
    monkeypatch,
    _stub_cost_scripts,
) -> None:
    """L33 — ip_cap rejection surfaces as tutor.ip_cap."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)
    _stub_cost_scripts["reserve_cost"].return_value = (False, "ip_cap")

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "q"},
        headers=headers,
    )
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "tutor.ip_cap"


async def test_post_429_when_global_cost_cap_hit(
    client: AsyncClient,
    auth_headers,
    monkeypatch,
    _stub_cost_scripts,
) -> None:
    """L33 — global_cap rejection surfaces as tutor.global_cap."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)
    _stub_cost_scripts["reserve_cost"].return_value = (False, "global_cap")

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "q"},
        headers=headers,
    )
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "tutor.global_cap"


async def test_post_persists_reserved_cost_on_row(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """L33 — the persisted reserved_cost_usd equals
    `tutor_estimate_microcents / 1e6` as a Decimal. The Celery task
    converts back to integer microcents at reconcile time."""
    from decimal import Decimal

    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)
    monkeypatch.setattr(s, "tutor_estimate_microcents", 7_500)  # $0.0075

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "q"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    turn_id = r.json()["id"]

    row = await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    turn = row.scalar_one_or_none()
    assert turn is not None
    # Decimal equality is sensitive to scale; compare via subtraction.
    assert abs(turn.reserved_cost_usd - Decimal("0.0075")) < Decimal("0.0000001")


async def test_streaming_post_rate_limited_at_20_per_minute(
    client: AsyncClient,
    auth_headers,
    monkeypatch,
    _stub_cost_scripts,
) -> None:
    """L39 — POST /tutor/turns now wears the same `@limiter.limit
    20/minute` the legacy POST has. The 21st request from one
    identity inside a one-minute window should 429.

    Cost + concurrency stubs return ok so the rate limit (not the
    cap) is the gate this test exercises.
    """
    from app.core.ratelimit import reset_for_tests as _reset_limiter

    _reset_limiter()
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)
    learner = await auth_headers(role=Role.student)
    _reset_limiter()  # auth_headers' login hit a different limiter bucket

    last_status = 0
    for _ in range(22):
        r = await client.post(
            "/api/v1/tutor/turns",
            json={"content": "ping"},
            headers=learner,
        )
        last_status = r.status_code
        if r.status_code == 429:
            break
    assert last_status == 429


async def test_status_idor_collapses_to_404(
    client: AsyncClient,
    auth_headers,
    monkeypatch,
) -> None:
    """Learner B querying learner A's turn status sees 404, not 403 —
    so the endpoint doesn't reveal whether the id exists."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    headers_a = await auth_headers(role=Role.student)
    headers_b = await auth_headers(role=Role.student)

    new = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "first user's turn"},
        headers=headers_a,
    )
    assert new.status_code == 201
    turn_id = new.json()["id"]

    r = await client.get(f"/api/v1/tutor/turns/{turn_id}/status", headers=headers_b)
    assert r.status_code == 404


# ----------------------------------------------------------------------------
# F3 (S5 BYOK gate) — POST /tutor/turns reservation semantics for BYOK turns.
#
# ADR-0027 §4-§5 + charter decision 5: a BYOK turn pays the user's own
# provider, so the enqueue path must (a) resolve the BYOK context BEFORE the
# dollar reservation, (b) SKIP the platform dollar reservation entirely, and
# (c) instead enforce the non-dollar BYOK request windows. Platform turns must
# keep reserving dollars exactly as before — these guard the reorder.
# ----------------------------------------------------------------------------


@pytest.fixture
def _byok_on(monkeypatch):
    """Local (NOT autouse) BYOK-on toggle. Mirrors tests/test_byok_threading.py:
    flip FEATURE_BYOK_ENABLED, bust the settings cache + crypto state, then
    restore on teardown so the surrounding flag-OFF default is preserved."""
    from app.core import secrets_crypto

    monkeypatch.setenv("FEATURE_BYOK_ENABLED", "true")
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()
    yield
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()


async def _store_active_credential(db_session, user_id):
    """Seed one active+enabled credential for ``user_id`` directly in the DB.

    Shape copied from tests/test_byok_threading.py::_store — an encrypted
    blob (never plaintext on the row), is_active=True so the partial unique
    index treats it as the user's single live credential. ``enabled`` and
    ``last_validation_status`` keep their model defaults (True / unvalidated),
    so byok.resolve_context returns a BYOK context carrying this id."""
    from app.core import secrets_crypto
    from app.models.user_llm_credential import UserLLMCredential

    sentinel = "sk-F3-RESERVATION-SENTINEL-00000000ab"
    blob = secrets_crypto.encrypt(sentinel.encode())
    cred = UserLLMCredential(
        user_id=user_id,
        provider="groq",
        model="llama-3.3-70b-versatile",
        enc_blob=blob,
        key_version=1,
        key_fingerprint=secrets_crypto.key_fingerprint(sentinel),
        last4=secrets_crypto.last4(sentinel),
        is_active=True,
    )
    db_session.add(cred)
    await db_session.commit()
    await db_session.refresh(cred)
    return cred


async def _login_headers(client: AsyncClient, make_user, *, role=Role.student):
    """Create a user and mint Bearer headers for it — unlike the auth_headers
    fixture (which hides the user it creates), this returns BOTH so the
    credential row and the request principal are guaranteed the same id."""
    import uuid

    email = f"f3-{uuid.uuid4().hex[:8]}@lumen.test"
    password = "Password!1234"
    user = await make_user(email=email, password=password, role=role)
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return user, {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_byok_turn_skips_dollar_reservation(
    client: AsyncClient,
    make_user,
    db_session: AsyncSession,
    monkeypatch,
    _byok_on,
    _stub_cost_scripts,
) -> None:
    """A BYOK turn (active credential present) must NOT call reserve_cost:
    it pays the user's own provider, so platform cost buckets stay untouched.
    The persisted row carries reserved_cost_usd == 0 and the credential id."""
    from decimal import Decimal

    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    user, headers = await _login_headers(client, make_user, role=Role.student)
    cred = await _store_active_credential(db_session, user.id)

    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "byok question"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    turn_id = r.json()["id"]

    # The dollar reservation was skipped entirely for the BYOK turn.
    _stub_cost_scripts["reserve_cost"].assert_not_called()

    row = await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    turn = row.scalar_one_or_none()
    assert turn is not None
    assert turn.reserved_cost_usd == Decimal(0)
    assert turn.credential_id == cred.id


async def test_byok_turn_trips_request_window(
    client: AsyncClient,
    make_user,
    db_session: AsyncSession,
    monkeypatch,
    _byok_on,
    _stub_cost_scripts,
) -> None:
    """With the BYOK 24h request window set to 0, a BYOK turn trips the
    non-dollar quota → 429 llm.quota_exceeded. The concurrency slot acquired
    ahead of the window check MUST be released so retries don't lock the user
    out of their own concurrency budget."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)
    monkeypatch.setattr(s, "byok_requests_24h", 0)

    user, headers = await _login_headers(client, make_user, role=Role.student)
    await _store_active_credential(db_session, user.id)

    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "byok over quota"},
        headers=headers,
    )
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "llm.quota_exceeded"
    # The slot was given back when the window tripped.
    _stub_cost_scripts["release_concurrency"].assert_called_once()
    # No dollar reservation ever happened for the BYOK turn.
    _stub_cost_scripts["reserve_cost"].assert_not_called()


async def test_platform_turn_still_reserves(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
    _stub_cost_scripts,
) -> None:
    """Regression guard for the F3 reorder: a turn with NO credential is a
    platform turn and must still reserve dollars exactly once."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "platform question"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    _stub_cost_scripts["reserve_cost"].assert_called_once()


# ----------------------------------------------------------------------------
# C3 (confirm-round) — cancelling a still-PENDING BYOK turn (reserved $0) must
# release its concurrency slot even though it held no cost reservation. The
# previous `reserved>0` release condition leaked the slot until the Redis TTL.
# ----------------------------------------------------------------------------


async def test_cancel_pending_byok_turn_releases_concurrency(
    client: AsyncClient,
    make_user,
    db_session: AsyncSession,
    monkeypatch,
    _byok_on,
    _stub_cost_scripts,
) -> None:
    """A BYOK turn reserves zero dollars, so the cancel path's release
    condition can't key off ``reserved>0`` — it must release the slot
    because the still-PENDING turn was never claimed by a worker (whose
    finally would otherwise own the release). ``reconcile_cost`` must NOT
    run (nothing was reserved)."""
    from unittest.mock import AsyncMock

    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    user, headers = await _login_headers(client, make_user, role=Role.student)
    await _store_active_credential(db_session, user.id)

    # POST a BYOK turn: 201, pending, reserved $0 (the F3 skip-reservation path).
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "byok cancel me"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == TURN_STATUS_PENDING
    turn_id = body["id"]
    _stub_cost_scripts["reserve_cost"].assert_not_called()

    row = await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    turn = row.scalar_one_or_none()
    assert turn is not None
    from decimal import Decimal

    assert turn.reserved_cost_usd == Decimal(0)

    # cancel_turn imports reconcile_cost locally from app.core.cost_scripts —
    # patch that binding to prove it is NOT invoked for a zero-reservation
    # cancel (the fixture only stubs release_concurrency / reserve_cost).
    reconcile_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("app.core.cost_scripts.reconcile_cost", reconcile_mock)

    d = await client.delete(f"/api/v1/tutor/turns/{turn_id}", headers=headers)
    assert d.status_code == 204, d.text

    # The slot was released (was_unclaimed branch) even though reserved == 0.
    # cancel_turn calls release_concurrency directly = the patched module
    # binding (app.api.v1.tutor_streaming.release_concurrency).
    _stub_cost_scripts["release_concurrency"].assert_called_once()
    # Zero reservation → no cost reconciliation.
    reconcile_mock.assert_not_called()


async def test_cancel_pending_platform_turn_releases_both(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
    _stub_cost_scripts,
) -> None:
    """Sanity for the C3 reshape: a still-PENDING PLATFORM turn (reserved>0)
    still reconciles its cost AND releases its slot — the held-cost branch is
    unchanged for claimed-by-nobody platform turns."""
    from decimal import Decimal
    from unittest.mock import AsyncMock

    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)
    monkeypatch.setattr(s, "tutor_estimate_microcents", 5_000)

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "platform cancel me"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    turn_id = r.json()["id"]
    _stub_cost_scripts["reserve_cost"].assert_called_once()

    row = await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    turn = row.scalar_one_or_none()
    assert turn is not None
    assert turn.reserved_cost_usd > Decimal(0)

    reconcile_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("app.core.cost_scripts.reconcile_cost", reconcile_mock)

    d = await client.delete(f"/api/v1/tutor/turns/{turn_id}", headers=headers)
    assert d.status_code == 204, d.text

    # Platform turn held cost → both release AND reconcile fire.
    _stub_cost_scripts["release_concurrency"].assert_called_once()
    reconcile_mock.assert_called_once()


async def test_cancel_claimed_byok_turn_does_not_release_slot(
    client: AsyncClient,
    make_user,
    db_session: AsyncSession,
    monkeypatch,
    _byok_on,
    _stub_cost_scripts,
) -> None:
    """Confirm-round-2 race (Codex): a worker claiming the turn between the
    cancel handler's ORM read and the terminal transition must NOT lead to
    a double slot release. The unclaimed verdict now comes from the atomic
    pending→aborted UPDATE (``abort_pending``): once the row is claimed
    (status=running), the API cancel marks it aborted but leaves the
    concurrency slot to the worker's ``finally`` — releasing here too
    would double-decrement the Redis counter and bypass the cap."""
    from unittest.mock import AsyncMock

    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    user, headers = await _login_headers(client, make_user, role=Role.student)
    await _store_active_credential(db_session, user.id)

    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "claim then cancel"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    turn_id = r.json()["id"]

    # Simulate the worker winning the race: claim pending → running.
    from app.services.tutor_turn_service import claim_pending_turn

    claimed = await claim_pending_turn(db_session, turn_id)
    assert claimed is not None
    await db_session.commit()

    reconcile_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("app.core.cost_scripts.reconcile_cost", reconcile_mock)
    _stub_cost_scripts["release_concurrency"].reset_mock()

    r = await client.delete(f"/api/v1/tutor/turns/{turn_id}", headers=headers)
    assert r.status_code == 204, r.text

    # Claimed + zero-reserved: neither cost reconcile nor slot release —
    # the worker's finally owns the slot.
    _stub_cost_scripts["release_concurrency"].assert_not_called()
    reconcile_mock.assert_not_called()

    # The abort ran in the app's session via raw SQL — expire this
    # session's identity map so the re-read sees the committed row.
    db_session.expire_all()
    row = await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    turn = row.scalar_one_or_none()
    assert turn is not None and turn.status == TURN_STATUS_ABORTED


async def test_abort_pending_is_atomic_unclaimed_verdict(
    db_session: AsyncSession, make_user
) -> None:
    """``abort_pending`` semantics: True exactly once, only from pending."""
    from decimal import Decimal

    from app.services.tutor_turn_service import abort_pending, create_turn

    user = await make_user()
    turn = await create_turn(
        db_session,
        user_id=user.id,
        conversation_id=None,
        reserved_cost_usd=Decimal(0),
        reservation_ip_key="t",
        enqueue_task=False,
    )
    turn_id = turn.id  # capture before expire_all (async lazy-load trap)
    await db_session.commit()

    assert await abort_pending(db_session, turn_id=turn_id, error_code="x") is True
    # Second attempt: already terminal → False (idempotent, no re-release).
    assert await abort_pending(db_session, turn_id=turn_id, error_code="x") is False
    await db_session.commit()

    # abort_pending updates via raw SQL — expire the identity map so the
    # ORM re-read reflects the committed transition.
    db_session.expire_all()
    row = await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    refreshed = row.scalar_one()
    assert refreshed.status == TURN_STATUS_ABORTED
    assert refreshed.reserved_cost_usd == Decimal(0)
