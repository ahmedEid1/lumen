"""Media tasks: probe metadata, sweep unclaimed assets."""

from __future__ import annotations

from app.core.logging import get_logger
from app.workers.celery_app import celery

log = get_logger(__name__)


@celery.task(name="app.workers.tasks.media.probe_asset")
def probe_asset(asset_id: str) -> None:
    log.info("media_probe", asset_id=asset_id)
    # TODO(v1.1): use ffprobe to extract video metadata; for now this is a stub.


@celery.task(name="app.workers.tasks.media.sweep_unclaimed_assets")
def sweep_unclaimed_assets() -> None:
    log.info("media_sweep_unclaimed_assets")
    # TODO(v1.1): list MinIO objects, drop ones older than 24h not referenced in assets.
