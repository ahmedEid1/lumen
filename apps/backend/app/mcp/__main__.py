"""CLI entrypoint for the Lumen MCP server.

Two transports, switched by ``--transport``:

* ``stdio`` (default) — for Claude Desktop / Cursor / Claude Code's
  ``claude mcp add`` flow. Reads ``LUMEN_MCP_AUTH_TOKEN`` from the
  env block of the parent's config file.
* ``http`` — for hosted installs. Listens on ``--host:--port`` (8001
  by default), exposes ``/oauth/token`` + the streamable-HTTP MCP
  endpoint at ``/mcp``.

``--db-url`` overrides the ``DATABASE_URL`` env var for the duration
of the process — useful for a quick "point the MCP server at a
specific Lumen instance" check without editing ``.env``.

Examples
--------

.. code-block:: shell

   # Claude Desktop's launch shape (set via the config file's
   # `command` + `args`; this command is what the JSON args evaluate
   # to once expanded).
   $ LUMEN_MCP_AUTH_TOKEN=<secret> \\
     DATABASE_URL=postgresql+asyncpg://... \\
     python -m app.mcp --transport stdio

   # Hosted install — runs alongside the main API on the same Lumen
   # box, listening on port 8001.
   $ python -m app.mcp --transport http --port 8001
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from app.core.config import get_settings
from app.core.logging import get_logger
from app.mcp.server import run_http, run_stdio

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.mcp",
        description="Run the Lumen MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="MCP transport to expose. Default: stdio (Claude Desktop).",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",  # noqa: S104 — bound inside a container by default
        help="HTTP transport bind host. Ignored for stdio.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="HTTP transport bind port. Ignored for stdio.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help=(
            "Override DATABASE_URL for this process. Equivalent to setting"
            " the env var; passed for convenience."
        ),
    )
    return parser.parse_args(argv)


def _apply_db_override(args: argparse.Namespace) -> None:
    """Re-point the engine if the operator passed ``--db-url``."""
    if not args.db_url:
        return
    os.environ["DATABASE_URL"] = args.db_url
    # Force ``get_settings`` to re-read the env. The DB engine factory
    # in ``app.db.base`` is lazy and will pick up the new value on the
    # next ``get_engine()`` call.
    get_settings.cache_clear()  # type: ignore[attr-defined]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _apply_db_override(args)

    if args.transport == "stdio":
        log.info("mcp_server_starting", transport="stdio")
        asyncio.run(run_stdio())
    elif args.transport == "http":
        log.info(
            "mcp_server_starting",
            transport="http",
            host=args.host,
            port=args.port,
        )
        asyncio.run(run_http(host=args.host, port=args.port))
    else:  # pragma: no cover - argparse already constrains this
        log.error("mcp_unknown_transport", transport=args.transport)
        return 2

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
