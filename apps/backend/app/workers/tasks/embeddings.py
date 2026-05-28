"""Celery task — (re)index a course's lesson chunks.

Rebuild Phase E0. Fired from :mod:`app.services.courses` whenever a
course transitions to ``published``, and from the admin reindex
endpoint as a bulk catch-up. The actual work lives in
:mod:`app.services.embeddings_ingest`; this wrapper just bridges
async-into-sync inside the Celery worker process, matching the
``send_daily_digests`` pattern in :mod:`app.workers.tasks.digest`.
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.db import base as db_base
from app.services.embeddings_ingest import ingest_course
from app.workers.celery_app import celery

log = get_logger(__name__)


async def _index_course_async(course_id: str) -> int:
    # Per-task NullPool engine — the Celery worker runs this under a
    # fresh asyncio.run loop, where the shared pooled engine would
    # raise "got Future attached to a different loop". See
    # app.db.base.worker_session_scope.
    async with db_base.worker_session_scope() as Session, Session() as db:
        return await ingest_course(db, course_id)


@celery.task(
    name="app.workers.tasks.embeddings.index_course_embeddings",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def index_course_embeddings(course_id: str) -> int:
    """Embed every live lesson in ``course_id``. Returns chunk count."""
    log.info("index_course_embeddings_start", course_id=course_id)
    written = asyncio.run(_index_course_async(course_id))
    log.info("index_course_embeddings_done", course_id=course_id, chunks=written)
    return written
