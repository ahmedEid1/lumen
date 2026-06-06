"""S7pre.7 — ORM cascade invariant (DR-6-R2 / PR-15).

The single load-bearing change: ``User.courses_owned`` cascade goes from
``all, delete-orphan`` → ``save-update`` so a self-delete can never silently
orphan-delete a user's courses (which the ``Course.owner_id`` RESTRICT FK
forbids at the DB level — the relationship and the FK had opposite intents).

DR-6-R2 / PR-24 supersede ADR-0030 D1: change ONLY ``courses_owned``. Leave
``enrollments`` and ``reviews`` as ``all, delete-orphan`` (they are
internally consistent with their CASCADE FKs and never fire under
anonymize-in-place), and keep ``refresh_tokens`` unchanged. This test
introspects ``User.__mapper__.relationships`` so it needs no DB.
"""

from __future__ import annotations

from app.models.user import User


def _cascade(rel_name: str) -> set[str]:
    rel = User.__mapper__.relationships[rel_name]
    # SQLAlchemy's CascadeOptions is a frozenset-like of cascade tokens.
    return {tok.replace("_", "-") for tok in rel.cascade}


def test_courses_owned_is_save_update_no_delete_orphan():
    cascade = _cascade("courses_owned")
    assert "delete-orphan" not in cascade, (
        "User.courses_owned must NOT delete-orphan (DR-6-R2): it contradicts "
        "Course.owner_id RESTRICT and would silently orphan-delete courses"
    )
    assert "delete" not in cascade, "courses_owned must not cascade delete either"
    assert "save-update" in cascade


def test_enrollments_unchanged_delete_orphan():
    """DR-6-R2: leave enrollments as all, delete-orphan (do NOT over-correct)."""
    cascade = _cascade("enrollments")
    assert "delete-orphan" in cascade


def test_reviews_unchanged_delete_orphan():
    """DR-6-R2: leave reviews as all, delete-orphan."""
    cascade = _cascade("reviews")
    assert "delete-orphan" in cascade


def test_refresh_tokens_unchanged_delete_orphan():
    """ADR-0030 D1: refresh_tokens stay all, delete-orphan (ephemeral hard-delete)."""
    cascade = _cascade("refresh_tokens")
    assert "delete-orphan" in cascade


def test_exactly_one_relationship_changed():
    """Belt-and-suspenders: courses_owned is the ONLY no-delete-orphan content
    relationship; the other three keep delete-orphan."""
    delete_orphan = {
        name
        for name in ("courses_owned", "enrollments", "reviews", "refresh_tokens")
        if "delete-orphan" in _cascade(name)
    }
    assert delete_orphan == {"enrollments", "reviews", "refresh_tokens"}
