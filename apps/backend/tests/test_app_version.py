"""The OpenAPI document and ``GET /`` report the package version.

Both used to hard-code ``1.0.0-rebuild`` while the release was v2.0.0.
They now read ``app.__version__``; this test keeps that in step with
``pyproject.toml`` so a version bump can't update one and miss the other.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from app import __version__

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_package_version_matches_pyproject() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert project["version"] == __version__


@pytest.mark.asyncio
async def test_openapi_and_root_report_package_version(client) -> None:
    spec = (await client.get("/openapi.json")).json()
    assert spec["info"]["version"] == __version__
    assert "rebuild" not in spec["info"]["version"]

    root = (await client.get("/")).json()
    assert root["version"] == __version__
