"""Search facade — Meilisearch with a Postgres fallback."""

from __future__ import annotations

from typing import Any

import meilisearch

from app.core.config import get_settings


class SearchService:
    def __init__(self) -> None:
        self._client: meilisearch.Client | None = None

    def _meili(self) -> meilisearch.Client:
        if self._client is None:
            s = get_settings()
            self._client = meilisearch.Client(s.meili_url, s.meili_master_key.get_secret_value())
        return self._client

    def _index(self) -> Any:
        s = get_settings()
        return self._meili().index(s.meili_index_courses)

    def ensure_index(self) -> None:
        s = get_settings()
        if s.search_backend != "meilisearch":
            return
        client = self._meili()
        try:
            client.create_index(s.meili_index_courses, {"primaryKey": "id"})
        except meilisearch.errors.MeilisearchApiError:
            pass
        self._index().update_filterable_attributes(
            ["subject_slug", "tag_slugs", "difficulty", "status"]
        )
        self._index().update_searchable_attributes(["title", "overview", "owner_name", "tag_names", "subject_title"])
        self._index().update_sortable_attributes(["published_at", "avg_rating", "enrollments_count"])

    def index_courses(self, docs: list[dict[str, Any]]) -> None:
        if get_settings().search_backend != "meilisearch":
            return
        if not docs:
            return
        self._index().add_documents(docs, primary_key="id")

    def delete_course(self, course_id: str) -> None:
        if get_settings().search_backend != "meilisearch":
            return
        self._index().delete_document(course_id)

    def search(self, q: str, *, filters: list[str] | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        if get_settings().search_backend != "meilisearch":
            return {"hits": [], "estimatedTotalHits": 0}
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if filters:
            params["filter"] = filters
        return self._index().search(q, params)


search_service = SearchService()
