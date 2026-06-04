"""Media tasks: probe metadata, lazy clone-asset re-homing, orphan sweep.

The clone-asset re-homing (S4.9 / ADR-0028 §"Service / worker changes", DR-9)
is the only place ``Asset`` rows are minted for a clone. It runs AFTER the clone
tree commits (best-effort enqueue, mirroring ``_schedule_embedding_index``):

* :func:`copy_clone_assets` walks the clone's lessons + ``cover_url`` and, for
  each in-bucket object reference, downloads → re-validates the BYTES (R-S5,
  NOT ``CopyObject``) → re-uploads under the cloner's namespace via
  ``uploads.download_revalidate_reupload``, mints a new owned ``Asset`` row, and
  rewrites the lesson ``data``/``cover_url`` ref to the new public URL.
  Best-effort per object (FR-CLONE-13): a missing/410/denied object strips the
  ref to a safe placeholder and appends to the clone audit
  ``data.asset_copy_failures[]`` — the task always succeeds (no 500). External
  (non-bucket) URLs are referenced as-is. Cooperative cancellation (R-S10): the
  cloner's ``is_active`` is re-checked at each lesson boundary via
  ``assert_account_active``; a suspended/deleted cloner aborts the task.

* :func:`sweep_orphan_clone_assets` reclaims ``Asset`` rows in cloner namespaces
  with no live lesson/cover reference, older than 24h (rollback debris, R-G7).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import get_logger
from app.db import base as db_base
from app.workers.celery_app import celery

log = get_logger(__name__)


@celery.task(name="app.workers.tasks.media.probe_asset")
def probe_asset(asset_id: str) -> None:
    log.info("media_probe", asset_id=asset_id)
    # TODO(v1.1): use ffprobe to extract video metadata; for now this is a stub.


# ---------------------------------------------------------------------------
# Clone asset re-homing
# ---------------------------------------------------------------------------

#: The lesson ``data`` fields that may carry an in-bucket object reference. Each
#: maps a URL-bearing field; ``asset_key`` is the bare key, the others are full
#: public URLs. We rewrite whichever are present + in-bucket.
_LESSON_URL_FIELDS = ("url", "captions_url")


async def _rehome_one(db, *, src_key: str, kind: str, owner_id: str, filename: str | None) -> dict:
    """Re-home one object + mint a new owned Asset row (in ``db``). Returns the
    new ref. ``download_revalidate_reupload`` re-validates the FETCHED BYTES
    (R-S5) and raises :class:`AssetRevalidationError` on a denied/oversized
    object — the caller treats that as a best-effort per-object failure."""
    from app.models.asset import Asset
    from app.services import uploads

    result = uploads.download_revalidate_reupload(
        src_key=src_key, dst_kind=kind, dst_owner_id=owner_id, filename=filename
    )
    db.add(
        Asset(
            owner_id=owner_id,
            kind=kind,
            key=str(result["key"]),
            content_type=str(result["content_type"]),
            size_bytes=int(result["size_bytes"]),
            public_url=str(result["public_url"]),
        )
    )
    await db.flush()
    return result


async def _copy_clone_assets_async(new_course_id: str, *, db=None) -> dict:
    """Walk the clone tree + cover, re-home in-bucket objects, rewrite refs.

    Returns a small summary ``{copied, failed, cancelled}`` for the task log.
    ``db`` is injectable for tests; in production it opens a per-task NullPool
    worker session (``worker_session_scope``).
    """
    if db is None:
        async with db_base.worker_session_scope() as Session, Session() as session:
            summary = await _copy_clone_assets_async(new_course_id, db=session)
            await session.commit()
            return summary

    from app.models.course import Course, Lesson, Module
    from app.services import uploads
    from app.services.account import assert_account_active

    copied = 0
    failures: list[dict] = []
    cancelled = False

    course = await db.get(Course, new_course_id)
    if course is None:
        # With the after-commit enqueue (S4 gate Codex-C1) this should be rare —
        # the enqueue fires only AFTER the clone tree commits. A missing row now
        # means the clone was deleted/rolled-back between commit and task pickup;
        # silent SUCCESS would lie to the orphan/asset-sweep semantics, so log at
        # error level and return a non-success marker the task log can flag.
        log.error("copy_clone_assets_course_missing", course_id=new_course_id)
        return {"copied": 0, "failed": 0, "cancelled": False, "missing": True}
    owner_id = course.owner_id

    # ---- Cover (cover/{owner}/...) ----
    if uploads.is_bucket_url(course.cover_url):
        src_key = uploads.key_from_bucket_url(course.cover_url)  # type: ignore[arg-type]
        try:
            res = await _rehome_one(
                db, src_key=src_key, kind="cover", owner_id=owner_id, filename=None
            )
            course.cover_url = str(res["public_url"])
            copied += 1
        except Exception as exc:  # best-effort per object (FR-CLONE-13)
            reason = getattr(exc, "reason", "fetch_failed")
            failures.append({"ref": course.cover_url, "field": "cover_url", "reason": reason})
            course.cover_url = None  # strip to a safe placeholder
        await db.flush()

    # ---- Lessons (cooperative-cancel at each lesson boundary, R-S10) ----
    mod_ids = (
        (await db.execute(select(Module.id).where(Module.course_id == new_course_id)))
        .scalars()
        .all()
    )
    lessons = (
        (
            await db.execute(
                select(Lesson).where(Lesson.module_id.in_(mod_ids), Lesson.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )

    for lesson in lessons:
        try:
            await assert_account_active(db, owner_id)
        except Exception:  # AccessRevokedError → abort at the boundary
            cancelled = True
            break

        data = dict(lesson.data or {})
        mutated = False
        kind = "lesson"

        # asset_key: a bare in-bucket key (image/file lessons).
        asset_key = data.get("asset_key")
        if isinstance(asset_key, str) and asset_key:
            try:
                res = await _rehome_one(
                    db,
                    src_key=asset_key,
                    kind=kind,
                    owner_id=owner_id,
                    filename=data.get("filename"),
                )
                data["asset_key"] = str(res["key"])
                # NB: don't also set ``data["url"]`` here — the URL-field loop
                # below would then re-home the just-written in-bucket URL a second
                # time (double count). ``asset_key`` is the canonical ref for
                # image/file lessons; the player derives the URL from it.
                copied += 1
                mutated = True
            except Exception as exc:
                reason = getattr(exc, "reason", "fetch_failed")
                failures.append({"lesson_id": lesson.id, "field": "asset_key", "reason": reason})
                data.pop("asset_key", None)
                mutated = True

        # Full public-URL fields (video url / captions_url).
        for field in _LESSON_URL_FIELDS:
            val = data.get(field)
            if not uploads.is_bucket_url(val):
                continue  # external URL → referenced as-is
            src_key = uploads.key_from_bucket_url(val)
            try:
                res = await _rehome_one(
                    db, src_key=src_key, kind=kind, owner_id=owner_id, filename=None
                )
                data[field] = str(res["public_url"])
                copied += 1
                mutated = True
            except Exception as exc:
                reason = getattr(exc, "reason", "fetch_failed")
                failures.append({"lesson_id": lesson.id, "field": field, "reason": reason})
                data[field] = None
                mutated = True

        if mutated:
            lesson.data = data
            flag_modified(lesson, "data")

    # Record failures on the clone audit row (append to asset_copy_failures[]).
    if failures:
        await _append_asset_failures(db, new_course_id, failures)

    return {"copied": copied, "failed": len(failures), "cancelled": cancelled}


async def _append_asset_failures(db, course_id: str, failures: list[dict]) -> None:
    """Append best-effort copy failures to the clone's course.cloned audit row."""
    from app.models.audit import AuditEvent

    row = (
        await db.execute(
            select(AuditEvent)
            .where(AuditEvent.action == "course.cloned", AuditEvent.target_id == course_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return
    data = dict(row.data or {})
    existing = list(data.get("asset_copy_failures") or [])
    existing.extend(failures)
    data["asset_copy_failures"] = existing
    row.data = data
    flag_modified(row, "data")
    await db.flush()


@celery.task(
    name="app.workers.tasks.media.copy_clone_assets",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def copy_clone_assets(new_course_id: str) -> dict:
    """Re-home a clone's in-bucket media into the cloner's namespace (S4.9)."""
    log.info("copy_clone_assets_start", course_id=new_course_id)
    summary = asyncio.run(_copy_clone_assets_async(new_course_id))
    log.info("copy_clone_assets_done", course_id=new_course_id, **summary)
    return summary


# ---------------------------------------------------------------------------
# Orphan sweep (R-G7)
# ---------------------------------------------------------------------------


async def _sweep_orphan_clone_assets_async(max_age_hours: int = 24, *, db=None) -> int:
    """Drop Asset rows + objects with no live lesson/cover reference, older than
    ``max_age_hours`` (rollback debris). Returns the number reclaimed. ``db`` is
    injectable for tests; production opens a per-task worker session."""
    if db is None:
        async with db_base.worker_session_scope() as Session, Session() as session:
            reclaimed = await _sweep_orphan_clone_assets_async(max_age_hours, db=session)
            await session.commit()
            return reclaimed

    from app.models.asset import Asset
    from app.models.course import Course, Lesson
    from app.services import uploads

    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    reclaimed = 0
    candidates = (
        (
            await db.execute(
                select(Asset).where(
                    Asset.kind.in_(("lesson", "cover")),
                    Asset.created_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return 0

    # Live references: any lesson.data URL/asset_key or course.cover_url that
    # contains the asset's public_url/key.
    referenced_urls = set(
        (await db.execute(select(Course.cover_url).where(Course.cover_url.is_not(None))))
        .scalars()
        .all()
    )
    lesson_blobs = (
        (await db.execute(select(Lesson.data).where(Lesson.deleted_at.is_(None)))).scalars().all()
    )

    def _is_referenced(asset: Asset) -> bool:
        if asset.public_url and asset.public_url in referenced_urls:
            return True
        for blob in lesson_blobs:
            if not blob:
                continue
            for v in blob.values():
                if isinstance(v, str) and (
                    v == asset.public_url or v == asset.key or asset.key in v
                ):
                    return True
        return False

    s = uploads.get_settings()
    client = uploads._client(s)
    for asset in candidates:
        if _is_referenced(asset):
            continue
        try:
            client.delete_object(Bucket=s.s3_bucket, Key=asset.key)
        except Exception:  # pragma: no cover — object may already be gone
            log.warning("orphan_object_delete_failed", key=asset.key)
        await db.delete(asset)
        reclaimed += 1
    await db.flush()
    return reclaimed


@celery.task(name="app.workers.tasks.media.sweep_orphan_clone_assets")
def sweep_orphan_clone_assets() -> int:
    """Periodic orphan-clone-asset reclamation (R-G7)."""
    log.info("sweep_orphan_clone_assets_start")
    reclaimed = asyncio.run(_sweep_orphan_clone_assets_async())
    log.info("sweep_orphan_clone_assets_done", reclaimed=reclaimed)
    return reclaimed


@celery.task(name="app.workers.tasks.media.sweep_unclaimed_assets")
def sweep_unclaimed_assets() -> None:
    log.info("media_sweep_unclaimed_assets")
    # TODO(v1.1): list MinIO objects, drop ones older than 24h not referenced in assets.


# ---------------------------------------------------------------------------
# Idempotency-key TTL sweep (S4 gate Codex-C2 / Gate-B B3)
# ---------------------------------------------------------------------------


async def _sweep_expired_idempotency_keys_async(*, db=None) -> int:
    """Delete idempotency rows past their ``expires_at`` (TTL replay window).

    Mirrors the orphan-asset sweep shape: ``db`` is injectable for tests; in
    production it opens a per-task NullPool worker session. Returns the count
    reclaimed."""
    if db is None:
        async with db_base.worker_session_scope() as Session, Session() as session:
            reclaimed = await _sweep_expired_idempotency_keys_async(db=session)
            await session.commit()
            return reclaimed

    from app.services import idempotency as idempotency_service

    return await idempotency_service.sweep_expired(db)


@celery.task(name="app.workers.tasks.media.sweep_expired_idempotency_keys")
def sweep_expired_idempotency_keys() -> int:
    """Periodic expired-idempotency-key reclamation (S4 gate)."""
    log.info("sweep_expired_idempotency_keys_start")
    reclaimed = asyncio.run(_sweep_expired_idempotency_keys_async())
    log.info("sweep_expired_idempotency_keys_done", reclaimed=reclaimed)
    return reclaimed
