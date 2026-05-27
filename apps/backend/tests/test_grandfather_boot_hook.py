"""Codex rescue (L21-Sec): email-verify grandfather boot hook MUST
respect ``settings.l21sec_deploy_timestamp`` so it can't auto-verify
users who registered after the deploy (and haven't clicked their
verification email yet).

This is the regression test the rescue surfaced. Two scenarios:

1. Pre-deploy user whose ``email_verified_at`` is still NULL — gets
   grandfathered. ✓
2. Post-deploy user whose ``email_verified_at`` is still NULL — must
   NOT get grandfathered; the verification gate has to do its job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import get_sessionmaker
from app.main import _grandfather_unverified_on_boot
from app.models.user import Role, User


async def _read_user(user_id: str) -> User:
    """Read a user via a FRESH session — bypasses the test session's
    identity-map cache so the boot hook's committed update is visible."""
    Session = get_sessionmaker()
    async with Session() as s:
        result = await s.execute(select(User).where(User.id == user_id))
        return result.scalar_one()


@pytest.fixture(autouse=True)
def _pin_cutoff(monkeypatch):
    """Pin the cutoff so the test doesn't depend on whatever the
    real Settings default happens to be."""
    cutoff = datetime(2026, 5, 27, 0, 0, 0, tzinfo=UTC)
    s = get_settings()
    monkeypatch.setattr(s, "l21sec_deploy_timestamp", cutoff)
    yield


@pytest.mark.asyncio
async def test_pre_deploy_user_gets_grandfathered(db_session: AsyncSession) -> None:
    pre = User(
        email="pre@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Pre-deploy",
        role=Role.student,
        email_verified_at=None,
    )
    db_session.add(pre)
    await db_session.commit()
    # Force created_at into the past so the boot-hook query sees this
    # row as pre-deploy. (SQLAlchemy honours an explicit value set
    # after the server default fired.)
    pre.created_at = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
    await db_session.commit()

    await _grandfather_unverified_on_boot()

    user = await _read_user(pre.id)
    assert user.email_verified_at is not None, (
        "pre-deploy unverified user should have been grandfathered"
    )


@pytest.mark.asyncio
async def test_post_deploy_user_NOT_grandfathered(db_session: AsyncSession) -> None:
    """The critical regression: a user who registered AFTER the
    L21-Sec deploy cutoff and hasn't yet clicked their verification
    email must NOT get auto-verified by the boot hook."""
    post = User(
        email="post@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Post-deploy",
        role=Role.student,
        email_verified_at=None,
    )
    db_session.add(post)
    await db_session.commit()
    # Force created_at to AFTER the cutoff.
    post.created_at = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC) + timedelta(hours=1)
    await db_session.commit()

    await _grandfather_unverified_on_boot()

    user = await _read_user(post.id)
    assert user.email_verified_at is None, (
        "post-deploy user must NOT be grandfathered — verification gate "
        "would otherwise be silently bypassed"
    )
