"""S4.9 — lazy clone-asset re-homing (download → revalidate bytes → reupload).

DR-9: NOT ``CopyObject``. Each in-bucket object is fetched, its BYTES re-validated
against the per-kind allowlist (R-S5 — a source whose stored content_type lies
must be caught on the bytes), re-uploaded under the cloner's namespace, a new
owned ``Asset`` row minted, and the lesson/cover ref rewritten. Best-effort per
object (missing/denied → ref stripped + recorded, task never 500s, FR-CLONE-13);
external URLs left as-is; cooperative-cancel on suspend (R-S10); orphan sweep
reclaims rollback debris (R-G7).

The S3 layer is a deterministic in-memory fake (``_FakeS3``) injected via
``uploads._client``; the DB walk runs against the test session injected into the
worker-task cores (``_copy_clone_assets_async(db=...)``).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.core.security import hash_password
from app.models.asset import Asset
from app.models.audit import AuditEvent
from app.models.course import Course, Lesson, Module, Subject
from app.models.user import Role, User
from app.services import uploads
from app.workers.tasks import media

pytestmark = pytest.mark.asyncio

# A tiny valid PNG header so the byte-sniff classifies it as image/png.
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_HTML = b"<!DOCTYPE html><script>alert(1)</script>"
_BUCKET_BASE = "http://localhost:9000/lumen-assets/"


class _FakeS3:
    """In-memory S3 stand-in: get/put/delete over a ``{key: (bytes, ctype)}`` map."""

    def __init__(self, objects: dict[str, tuple[bytes, str]]):
        self.objects = objects
        self.deleted: list[str] = []

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(f"NoSuchKey: {Key}")
        body, ctype = self.objects[Key]
        return {"Body": _Body(body), "ContentType": ctype}

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.objects[Key] = (Body, ContentType)

    def delete_object(self, *, Bucket, Key):
        self.deleted.append(Key)
        self.objects.pop(Key, None)


class _Body:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


@pytest.fixture
def fake_s3(monkeypatch):
    store: dict[str, tuple[bytes, str]] = {}
    client = _FakeS3(store)
    monkeypatch.setattr(uploads, "_client", lambda s=None: client)
    return client


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


async def _user(db: AsyncSession) -> User:
    u = User(
        email=f"u-{new_id()[:10]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Cloner",
        role=Role.user,
    )
    db.add(u)
    await db.flush()
    return u


async def _clone_course(db: AsyncSession, owner: User, *, cover_url=None) -> Course:
    subject = Subject(title="S", slug=f"s-{uuid.uuid4().hex[:8]}")
    db.add(subject)
    await db.flush()
    c = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=f"Clone {uuid.uuid4().hex[:6]}",
        slug=f"clone-{uuid.uuid4().hex[:10]}",
        overview="",
        cover_url=cover_url,
    )
    db.add(c)
    await db.flush()
    return c


async def _lesson(db: AsyncSession, course: Course, *, data: dict, order: int = 0) -> Lesson:
    mod = Module(course_id=course.id, title="M", description="", order=order)
    db.add(mod)
    await db.flush()
    le = Lesson(module_id=mod.id, title="L", order=0, type=data["type"], data=data)
    db.add(le)
    await db.flush()
    return le


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_copy_clone_asset_revalidates_bytes(db_session, fake_s3):
    """An allowed image is re-homed; a new owned Asset row exists; validation
    ran on the FETCHED bytes (a source whose stored type lies but whose bytes are
    a denied type is NOT re-homed)."""
    owner = await _user(db_session)
    course = await _clone_course(db_session, owner)
    # Lesson 1: a real PNG behind an asset_key — should re-home.
    good_key = "lesson/origin/2026/01/01/aaa/pic.png"
    fake_s3.objects[good_key] = (_PNG, "image/png")
    le_good = await _lesson(
        db_session, course, data={"type": "image", "asset_key": good_key, "alt": "x"}, order=0
    )
    # Lesson 2: stored type lies (claims png) but bytes are HTML — must be stripped.
    liar_key = "lesson/origin/2026/01/01/bbb/evil.png"
    fake_s3.objects[liar_key] = (_HTML, "image/png")
    le_liar = await _lesson(
        db_session,
        course,
        data={"type": "image", "asset_key": liar_key, "alt": "x"},
        order=1,
    )
    await db_session.commit()

    summary = await media._copy_clone_assets_async(course.id, db=db_session)
    await db_session.commit()
    assert summary["copied"] == 1
    assert summary["failed"] == 1

    # Good lesson: rewritten to the cloner's namespace + a new Asset row exists.
    await db_session.refresh(le_good)
    new_key = le_good.data["asset_key"]
    assert new_key != good_key
    assert new_key.startswith(f"lesson/{owner.id}/")
    asset = (await db_session.execute(select(Asset).where(Asset.key == new_key))).scalar_one()
    assert asset.owner_id == owner.id

    # Liar lesson: ref stripped (denied bytes), no Asset minted for it.
    await db_session.refresh(le_liar)
    assert "asset_key" not in le_liar.data


async def test_copy_clone_asset_rewrites_lesson_refs(db_session, fake_s3):
    owner = await _user(db_session)
    cover_key = "cover/origin/2026/01/01/ccc/cover.png"
    fake_s3.objects[cover_key] = (_PNG, "image/png")
    course = await _clone_course(db_session, owner, cover_url=_BUCKET_BASE + cover_key)
    video_url = _BUCKET_BASE + "lesson/origin/2026/01/01/ddd/v.mp4"
    fake_s3.objects[video_url[len(_BUCKET_BASE) :]] = (b"\x00\x00\x00\x20ftypmp4", "video/mp4")
    captions_url = _BUCKET_BASE + "lesson/origin/2026/01/01/eee/c.vtt"
    fake_s3.objects[captions_url[len(_BUCKET_BASE) :]] = (b"WEBVTT\n\n00:00", "text/vtt")
    le = await _lesson(
        db_session,
        course,
        data={
            "type": "video",
            "url": video_url,
            "captions_url": captions_url,
            "captions_label": "English",
            "captions_lang": "en",
        },
    )
    await db_session.commit()

    await media._copy_clone_assets_async(course.id, db=db_session)
    await db_session.commit()

    await db_session.refresh(course)
    await db_session.refresh(le)
    assert course.cover_url.startswith(_BUCKET_BASE + f"cover/{owner.id}/")
    assert le.data["url"].startswith(_BUCKET_BASE + f"lesson/{owner.id}/")
    assert le.data["captions_url"].startswith(_BUCKET_BASE + f"lesson/{owner.id}/")


async def test_copy_missing_object_best_effort(db_session, fake_s3):
    """A source object that 404s → lesson survives, ref stripped, failure
    recorded on the clone audit, task succeeds."""
    owner = await _user(db_session)
    course = await _clone_course(db_session, owner)
    # Audit row the failure should be appended to.
    db_session.add(
        AuditEvent(
            actor_id=owner.id,
            action="course.cloned",
            target_type="course",
            target_id=course.id,
            data={"asset_copy_failures": []},
        )
    )
    missing_key = "lesson/origin/2026/01/01/zzz/gone.png"  # not in fake_s3
    le = await _lesson(
        db_session, course, data={"type": "image", "asset_key": missing_key, "alt": "x"}
    )
    await db_session.commit()

    summary = await media._copy_clone_assets_async(course.id, db=db_session)
    await db_session.commit()
    assert summary["failed"] == 1

    await db_session.refresh(le)
    assert "asset_key" not in le.data  # stripped to a safe placeholder
    audit = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "course.cloned", AuditEvent.target_id == course.id
            )
        )
    ).scalar_one()
    assert len(audit.data["asset_copy_failures"]) == 1
    assert audit.data["asset_copy_failures"][0]["reason"] == "fetch_failed"


async def test_external_url_left_as_is(db_session, fake_s3):
    owner = await _user(db_session)
    course = await _clone_course(db_session, owner)
    external = "https://youtube.com/watch?v=abc"
    le = await _lesson(db_session, course, data={"type": "video", "url": external})
    await db_session.commit()

    summary = await media._copy_clone_assets_async(course.id, db=db_session)
    await db_session.commit()
    assert summary["copied"] == 0 and summary["failed"] == 0
    await db_session.refresh(le)
    assert le.data["url"] == external  # untouched


async def test_cooperative_cancel_on_suspend(db_session, fake_s3):
    """If the cloner flips inactive mid-task, the task aborts at a lesson
    boundary (R-S10) and leaves later lessons un-rehomed."""
    owner = await _user(db_session)
    course = await _clone_course(db_session, owner)
    k1 = "lesson/origin/2026/01/01/p1/a.png"
    k2 = "lesson/origin/2026/01/01/p2/b.png"
    fake_s3.objects[k1] = (_PNG, "image/png")
    fake_s3.objects[k2] = (_PNG, "image/png")
    await _lesson(db_session, course, data={"type": "image", "asset_key": k1, "alt": "x"}, order=0)
    await _lesson(db_session, course, data={"type": "image", "asset_key": k2, "alt": "x"}, order=1)
    # Suspend the owner BEFORE the task runs → first assert_account_active fails.
    owner.is_active = False
    await db_session.commit()

    summary = await media._copy_clone_assets_async(course.id, db=db_session)
    await db_session.commit()
    assert summary["cancelled"] is True
    assert summary["copied"] == 0


async def test_sweep_orphan_clone_assets(db_session, fake_s3):
    """An Asset in a cloner namespace with no live lesson/cover ref, older than
    24h, is dropped (R-G7); a referenced asset survives."""
    from datetime import UTC, datetime, timedelta

    owner = await _user(db_session)
    course = await _clone_course(db_session, owner)
    old = datetime.now(UTC) - timedelta(hours=48)

    orphan_key = f"lesson/{owner.id}/2026/01/01/orphan/x.png"
    orphan_url = _BUCKET_BASE + orphan_key
    fake_s3.objects[orphan_key] = (_PNG, "image/png")
    orphan = Asset(
        owner_id=owner.id,
        kind="lesson",
        key=orphan_key,
        content_type="image/png",
        size_bytes=10,
        public_url=orphan_url,
    )
    db_session.add(orphan)
    await db_session.flush()
    orphan.created_at = old  # backdate past the 24h cutoff

    referenced_key = f"lesson/{owner.id}/2026/01/01/live/y.png"
    referenced_url = _BUCKET_BASE + referenced_key
    fake_s3.objects[referenced_key] = (_PNG, "image/png")
    referenced = Asset(
        owner_id=owner.id,
        kind="lesson",
        key=referenced_key,
        content_type="image/png",
        size_bytes=10,
        public_url=referenced_url,
    )
    db_session.add(referenced)
    await db_session.flush()
    referenced.created_at = old
    # A live lesson references it → must NOT be swept.
    await _lesson(
        db_session, course, data={"type": "image", "asset_key": referenced_key, "alt": "x"}
    )
    await db_session.commit()

    reclaimed = await media._sweep_orphan_clone_assets_async(db=db_session)
    await db_session.commit()
    assert reclaimed == 1
    assert orphan_key in fake_s3.deleted
    # Orphan Asset row gone, referenced survives.
    remaining = (
        (await db_session.execute(select(Asset.key).where(Asset.owner_id == owner.id)))
        .scalars()
        .all()
    )
    assert orphan_key not in remaining
    assert referenced_key in remaining


async def test_copy_clone_assets_missing_course_logs_error_non_success(db_session):
    """S4 gate Codex-C1: a missing clone row no longer returns silent SUCCESS —
    it logs at error level and returns a non-success ``missing`` marker so the
    sweep/asset semantics stay honest."""
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        summary = await media._copy_clone_assets_async("does-not-exist", db=db_session)
    assert summary == {"copied": 0, "failed": 0, "cancelled": False, "missing": True}
    missing = [
        e for e in logs if e.get("event") == "copy_clone_assets_course_missing"
    ]
    assert len(missing) == 1
    assert missing[0]["log_level"] == "error"
    assert missing[0]["course_id"] == "does-not-exist"


# ---------------------------------------------------------------------------
# S4 gate Codex-C2 / Gate-B B3 — idempotency-key TTL sweep
# ---------------------------------------------------------------------------


async def test_sweep_expired_idempotency_keys(db_session):
    """Expired idempotency rows are swept; non-expired rows are kept."""
    from datetime import UTC, datetime, timedelta

    from app.models.idempotency import IdempotencyKey

    owner = await _user(db_session)
    now = datetime.now(UTC)
    expired = IdempotencyKey(
        user_id=owner.id,
        idempotency_key="old",
        endpoint="course.clone",
        response_target_id="c1",
        expires_at=now - timedelta(hours=1),
    )
    fresh = IdempotencyKey(
        user_id=owner.id,
        idempotency_key="new",
        endpoint="course.clone",
        response_target_id="c2",
        expires_at=now + timedelta(hours=23),
    )
    db_session.add_all([expired, fresh])
    await db_session.commit()

    reclaimed = await media._sweep_expired_idempotency_keys_async(db=db_session)
    await db_session.commit()
    assert reclaimed == 1
    remaining = (
        (await db_session.execute(select(IdempotencyKey.idempotency_key))).scalars().all()
    )
    assert "old" not in remaining
    assert "new" in remaining
