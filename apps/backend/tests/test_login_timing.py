"""Regression: login latency must not leak whether an email is registered.

Before iteration 32 the authenticate path skipped Argon2 verification
entirely when the user lookup returned None. Argon2 deliberately costs
several ms per attempt, so a "no such email" response came back ~10x
faster than a "wrong password" response — handing an enumeration
oracle to anyone who could observe wire timings.

The fix runs ``verify_password`` against a pre-computed dummy hash on
the missing-user path, so both branches do the same dominant CPU work.
We don't promise byte-equal timing (Argon2 is variance-y), but we do
require the unknown-email path to be in the same neighbourhood as the
wrong-password path.
"""

from __future__ import annotations

import time

from httpx import AsyncClient


async def _login_time(client: AsyncClient, email: str, password: str) -> float:
    """Median of 3 attempts to dampen Argon2 jitter."""
    samples: list[float] = []
    for _ in range(3):
        t0 = time.perf_counter()
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        samples.append(time.perf_counter() - t0)
        assert r.status_code == 401
    samples.sort()
    return samples[len(samples) // 2]


async def test_unknown_email_and_wrong_password_take_similar_time(
    client: AsyncClient, make_user
) -> None:
    await make_user(email="exists@lumen.test", password="Password!1234")

    unknown = await _login_time(client, "missing@lumen.test", "Password!1234")
    wrong = await _login_time(client, "exists@lumen.test", "wrong-password")

    # Both paths now exercise Argon2 once. The unknown path was previously
    # ~10x faster than the wrong-password path; we want them within ~3x of
    # each other to allow for Argon2 / CI variance without re-opening the
    # enumeration oracle.
    ratio = max(unknown, wrong) / max(1e-6, min(unknown, wrong))
    assert ratio < 3, (
        f"unknown={unknown * 1000:.1f}ms wrong={wrong * 1000:.1f}ms — timing "
        f"side-channel re-opened (ratio={ratio:.1f}×)"
    )
