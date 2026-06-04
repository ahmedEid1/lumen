"""S6.10 — read-time anonymization of tombstoned authors/owners (DR-19).

Any author/owner-bearing DTO must render the localized "a deleted user" label at
READ time when the underlying row is tombstoned (``deleted_at IS NOT NULL``) — or
when a provenance snapshot equals the deletion sentinel — regardless of whether
the one-time snapshot scrub ran (robust to migration ordering, DR-19). PII
(email, real name, avatar, bio) is never exposed for a tombstone.

Single-sourced via the ``common.deletedUser`` i18n key (ADR-0030 §D5): the
backend emits the key string in the name field; the frontend resolves it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.user import DELETED_USER_LABEL, UserPublic
from app.services.account import DELETED_OWNER_SNAPSHOT


async def test_live_user_renders_real_name(db_session: AsyncSession, make_user) -> None:
    user = await make_user(email=f"live-{uuid.uuid4().hex[:6]}@lumen.test", full_name="Real Name")
    user.avatar_url = "https://x/a.png"
    user.bio = "hi"
    await db_session.commit()

    dto = UserPublic.model_validate(user)
    assert dto.full_name == "Real Name"
    assert dto.avatar_url == "https://x/a.png"
    assert dto.bio == "hi"


async def test_tombstoned_author_renders_label(db_session: AsyncSession, make_user) -> None:
    user = await make_user(
        email=f"tomb-{uuid.uuid4().hex[:6]}@lumen.test", full_name="Was A Person"
    )
    user.avatar_url = "https://x/a.png"
    user.bio = "secret bio"
    user.is_active = False
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    dto = UserPublic.model_validate(user)
    # name resolves to the deleted-user label key
    assert dto.full_name == DELETED_USER_LABEL
    # PII suppressed
    assert dto.avatar_url is None
    assert dto.bio is None
    # the real name never appears in the serialized payload
    dumped = dto.model_dump(mode="json")
    assert "Was A Person" not in str(dumped)
    assert "secret bio" not in str(dumped)


async def test_review_of_deleted_author_renders_label(db_session: AsyncSession, make_user) -> None:
    from app.models.course import Course, Review, Subject
    from app.schemas.course import ReviewOut

    author = await make_user(email=f"ra-{uuid.uuid4().hex[:6]}@lumen.test", full_name="Reviewer X")
    owner = await make_user(email=f"ro-{uuid.uuid4().hex[:6]}@lumen.test")
    subject = Subject(title="S", slug=f"s-{uuid.uuid4().hex[:6]}")
    db_session.add(subject)
    await db_session.commit()
    course = Course(
        title="C",
        slug=f"c-{uuid.uuid4().hex[:6]}",
        subject_id=subject.id,
        owner_id=owner.id,
        overview="x",
    )
    db_session.add(course)
    await db_session.commit()
    review = Review(author_id=author.id, course_id=course.id, rating=5, body="great")
    db_session.add(review)
    await db_session.commit()

    # author deletes their account → tombstone
    author.is_active = False
    author.deleted_at = datetime.now(UTC)
    await db_session.commit()

    await db_session.refresh(review, attribute_names=["author"])
    dto = ReviewOut.model_validate(review)
    assert dto.author.full_name == DELETED_USER_LABEL
    assert "Reviewer X" not in str(dto.model_dump(mode="json"))


def test_provenance_sentinel_renders_label() -> None:
    # DR-19: a clone whose origin_owner_name_snapshot equals the deletion
    # sentinel renders the deleted-user label even when the underlying owner row
    # isn't loaded (read-time, snapshot-based). The resolver maps the sentinel.
    from app.schemas.user import resolve_owner_display_name

    assert resolve_owner_display_name(DELETED_OWNER_SNAPSHOT) == DELETED_USER_LABEL
    # a live snapshot renders verbatim
    assert resolve_owner_display_name("Jane Author") == "Jane Author"
    # an empty/None snapshot → label (defensive)
    assert resolve_owner_display_name(None) == DELETED_USER_LABEL
    assert resolve_owner_display_name("") == DELETED_USER_LABEL


def test_provenance_of_deleted_origin_owner_read_time() -> None:
    # DR-19 read-time guarantee: even if the one-time snapshot scrub did NOT run
    # (snapshot still holds the real name), a tombstoned origin owner resolves to
    # the label. resolve_owner_display_name takes the owner's deleted state.
    from app.schemas.user import resolve_owner_display_name

    # snapshot holds the real name, but owner is deleted → label wins
    assert resolve_owner_display_name("Jane Author", owner_is_deleted=True) == DELETED_USER_LABEL
    # owner live → snapshot renders
    assert resolve_owner_display_name("Jane Author", owner_is_deleted=False) == "Jane Author"
