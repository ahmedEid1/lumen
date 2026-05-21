"""Search facade — Meilisearch with a Postgres fallback."""

from __future__ import annotations

import contextlib
from typing import Any

import meilisearch

from app.core.config import get_settings


class SearchService:
    def __init__(self) -> None:
        self._client: meilisearch.Client | None = None

    def _meili_enabled(self) -> bool:
        return get_settings().search_backend == "meilisearch"

    def _meili(self) -> meilisearch.Client:
        if self._client is None:
            settings = get_settings()
            self._client = meilisearch.Client(
                settings.meili_url,
                settings.meili_master_key.get_secret_value(),
            )
        return self._client

    def _index(self) -> Any:
        return self._meili().index(get_settings().meili_index_courses)

    def ensure_index(self) -> None:
        if not self._meili_enabled():
            return
        s = get_settings()
        client = self._meili()
        with contextlib.suppress(meilisearch.errors.MeilisearchApiError):
            client.create_index(s.meili_index_courses, {"primaryKey": "id"})
        index = client.index(s.meili_index_courses)
        index.update_filterable_attributes(["subject_slug", "tag_slugs", "difficulty", "status"])
        index.update_searchable_attributes(["title", "overview", "owner_name", "tag_names", "subject_title"])
        index.update_sortable_attributes(["published_at", "avg_rating", "enrollments_count"])

    def index_courses(self, docs: list[dict[str, Any]]) -> None:
        if not docs or not self._meili_enabled():
            return
        self._index().add_documents(docs, primary_key="id")

    def delete_course(self, course_id: str) -> None:
        if not self._meili_enabled():
            return
        self._index().delete_document(course_id)

    def search(self, q: str, *, filters: list[str] | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        if not self._meili_enabled():
            return {"hits": [], "estimatedTotalHits": 0}
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if filters:
            params["filter"] = filters
        return self._index().search(q, params)


search_service = SearchService()
