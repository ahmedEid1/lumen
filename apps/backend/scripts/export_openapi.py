"""Dump the FastAPI OpenAPI schema to a file without running uvicorn.

Usage:

    python -m scripts.export_openapi --out openapi.json

Run from `apps/backend/` so the import path resolves.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="openapi.json", help="Output path")
    parser.add_argument("--pretty", action="store_true", help="Indent the JSON")
    args = parser.parse_args()

    # The app reads required env at import time; provide harmless dev defaults so
    # `python -m scripts.export_openapi` works from a clean shell.
    os.environ.setdefault("ENV", "development")
    os.environ.setdefault("JWT_SECRET", "dev-export-only")
    os.environ.setdefault("SECRET_KEY", "dev-export-only")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://lumen:lumen@localhost:5432/lumen")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

    # Ensure `app/` is importable when run as a script.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from app.main import app  # noqa: E402

    schema = app.openapi()
    text = json.dumps(schema, indent=2 if args.pretty else None, sort_keys=True)
    Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(text)} bytes, {len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
