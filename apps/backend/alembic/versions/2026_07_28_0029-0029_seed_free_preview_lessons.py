"""Mark the first lesson of every published course as is_preview.

QA-iter2 backfill. The free-preview feature was wired end-to-end —
the schema (lessons.is_preview), the auth bypass in
``app/api/v1/courses.py``'s get_lesson, the "Try preview" link on
``components/course/course-syllabus.tsx``, and the
``/courses/{slug}/preview/{lessonId}`` route — but **zero seeded
lessons had is_preview=True**, so an anonymous visitor clicking
through the catalog never saw the link, and the public-preview
branch of get_lesson never fired in real use. The demo seed change
(``apps/backend/app/seeds/demo.py``) only takes effect on a fresh
DB; this migration backfills the same intent on existing rows so the
feature surfaces immediately on the next prod deploy without a
re-seed.

Scope: for each published, not-deleted course, flip ``is_preview``
on its lowest-order lesson in the lowest-order module. The
downgrade reverts those rows to ``False`` — there's no way to know
which rows the operator might have flipped on by hand after the
upgrade ran, so the downgrade is "best effort, dev-only" and is
safe against the operator-touched rows in production because those
would be set via the studio editor (UPDATE) and overwriting them on
downgrade is the lesser harm (downgrade is dev-only anyway).

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_SQL = """
UPDATE lessons
SET is_preview = TRUE
WHERE id IN (
    SELECT DISTINCT ON (c.id) l.id
    FROM lessons l
    JOIN modules m ON m.id = l.module_id
    JOIN courses c ON c.id = m.course_id
    WHERE c.status = 'published'
      AND c.deleted_at IS NULL
      AND l.deleted_at IS NULL
    ORDER BY c.id, m."order" ASC, l."order" ASC
)
"""

_DOWNGRADE_SQL = """
UPDATE lessons
SET is_preview = FALSE
WHERE id IN (
    SELECT DISTINCT ON (c.id) l.id
    FROM lessons l
    JOIN modules m ON m.id = l.module_id
    JOIN courses c ON c.id = m.course_id
    WHERE c.status = 'published'
      AND c.deleted_at IS NULL
      AND l.deleted_at IS NULL
    ORDER BY c.id, m."order" ASC, l."order" ASC
)
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
