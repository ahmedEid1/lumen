"""Lumen MCP server — Phase I1.

Re-exports the public surface so callers can write
``from app.mcp import create_mcp_server`` without poking into the
submodules. See :mod:`app.mcp.server` for the actual implementation
and :doc:`/docs/mcp.md` for the operator-facing guide.
"""

from app.mcp.principal import Principal
from app.mcp.server import (
    create_mcp_server,
    dispatch_tool,
    run_http,
    run_stdio,
)
from app.mcp.tools import TOOL_SPECS, all_tool_names

__all__ = [
    "TOOL_SPECS",
    "Principal",
    "all_tool_names",
    "create_mcp_server",
    "dispatch_tool",
    "run_http",
    "run_stdio",
]
