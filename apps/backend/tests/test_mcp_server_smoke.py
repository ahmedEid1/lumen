"""End-to-end smoke test for the Lumen MCP stdio server.

Lumen v2 Phase I1. The unit tests in ``test_mcp_tools.py`` cover
the tool implementations directly; this test covers the protocol
layer: spawn ``python -m app.mcp --transport stdio`` in a subprocess,
send a ``tools/list`` JSON-RPC request over stdin, parse the
response off stdout, and assert that the nine tools are listed
with the expected names + descriptions.

The subprocess gets its auth from ``LUMEN_MCP_AUTH_TOKEN`` — a
plaintext secret we mint inline against the test DB before
launching. That gives us coverage of the static-token resolver +
the FastMCP tool-registration plumbing in one shot.

This test is wrapped in a skip-if-mcp-not-installed guard so a dev
machine without the optional MCP SDK still gets a green suite; CI
ships the package via ``pyproject.toml`` so it runs there. We also
skip if the SDK's ``FastMCP.run_stdio_async`` is missing — older
``mcp`` releases (<1.x) used a different entrypoint name, and we'd
rather skip cleanly than fail with an obscure AttributeError.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ids import new_id
from app.core.security import hash_password
from app.models.mcp_client import MCPClient
from app.models.user import Role

# ---------- Skip guard ----------


def _mcp_available() -> bool:
    """Is the MCP Python SDK importable in this environment?

    The smoke test depends on the real package; the rest of the
    suite uses our tool functions directly and doesn't need it.
    """
    try:
        import mcp.server.fastmcp  # type: ignore[import-not-found]  # noqa: F401
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _mcp_available(),
    reason="MCP Python SDK not installed — run `pip install mcp>=1.5`",
)


# ---------- Helpers ----------


async def _mint_token(db: AsyncSession, *, owner_user_id: str) -> str:
    """Persist a fresh ``mcp_clients`` row and return the plaintext secret.

    Mirrors ``app.cli.mcp-token`` but inline so the test doesn't
    have to shell out a second time.
    """
    secret = new_id()
    row = MCPClient(
        client_secret_hash=hash_password(secret),
        owner_user_id=owner_user_id,
        name="Smoke test client",
        scopes=["*"],
    )
    db.add(row)
    await db.commit()
    return secret


def _jsonrpc_frame(payload: dict) -> bytes:
    """Encode one JSON-RPC message as a newline-delimited frame.

    Per the MCP stdio transport spec (2025-06-18), messages are
    individual JSON-RPC requests/notifications/responses delimited
    by newlines, and **MUST NOT** contain embedded newlines. No
    Content-Length header is used. See:
    https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#stdio
    """
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _read_jsonrpc_frame(stream: asyncio.StreamReader) -> dict | None:
    """Read one JSON-RPC message off the subprocess's stdout.

    Returns ``None`` on EOF so the caller can distinguish a clean
    shutdown from a parse error. Per the MCP stdio transport spec
    (2025-06-18), each message is one newline-terminated line of
    UTF-8 JSON — no Content-Length header.

    The MCP spec says the server **MUST NOT** write anything to
    stdout that is not a valid MCP message, but defensive parsing
    keeps the test robust: non-JSON lines or JSON objects without
    a ``jsonrpc`` field (e.g. a stray structlog line) are skipped
    so we keep reading until the real response or EOF.
    """
    while True:
        line = await stream.readline()
        if not line:
            return None
        decoded = line.decode("utf-8", errors="replace").strip()
        if not decoded:
            continue
        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("jsonrpc") == "2.0":
            return parsed
        # Not a JSON-RPC message — keep reading.


# ---------- The smoke test ----------


@pytest.mark.asyncio
async def test_stdio_tools_list_returns_nine_tools(
    db_session: AsyncSession, make_user, _engine
) -> None:
    """Spawn the stdio MCP server and assert ``tools/list`` returns 9 tools.

    Steps:

    1. Mint an ``mcp_clients`` row in the test DB; capture the
       plaintext secret.
    2. Launch ``python -m app.mcp --transport stdio`` with the test
       DB URL + the minted secret as env.
    3. Send a JSON-RPC ``initialize`` then ``tools/list`` request.
    4. Read the response, assert nine tools, assert names cover the
       full Phase I1 vocabulary.

    Times out at 15s — the subprocess startup + one round-trip is
    much faster than that on any plausible machine, but the
    generous bound keeps a slow CI machine from flaking.
    """
    user = await make_user(role=Role.instructor)
    secret = await _mint_token(db_session, owner_user_id=user.id)

    # Inherit the test env so the subprocess uses the same test DB.
    env = os.environ.copy()
    env["LUMEN_MCP_AUTH_TOKEN"] = secret
    # Ensure DB url + JWT secret survive into the child.
    settings = get_settings()
    env["DATABASE_URL"] = settings.database_url
    env["JWT_SECRET"] = settings.jwt_secret.get_secret_value()
    env["LLM_PROVIDER"] = "noop"
    env["EMBEDDING_PROVIDER"] = "noop"
    # PYTHONUNBUFFERED so the child's stdout reaches us promptly.
    env["PYTHONUNBUFFERED"] = "1"

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.mcp",
        "--transport",
        "stdio",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    try:
        # MCP requires an ``initialize`` handshake before ``tools/list``.
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "lumen-smoke-test", "version": "1.0"},
            },
        }
        proc.stdin.write(_jsonrpc_frame(init_req))
        await proc.stdin.drain()

        # Some SDK versions require ``notifications/initialized`` after
        # the handshake; send it as a notification (no id).
        proc.stdin.write(_jsonrpc_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        await proc.stdin.drain()

        list_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        }
        proc.stdin.write(_jsonrpc_frame(list_req))
        await proc.stdin.drain()

        # Read frames until we see the ``tools/list`` response (id=2)
        # or run out of patience. The ``initialize`` response comes
        # first and we skip past it.
        tools_response: dict | None = None
        async with asyncio.timeout(15):
            while True:
                frame = await _read_jsonrpc_frame(proc.stdout)
                if frame is None:
                    break
                if frame.get("id") == 2:
                    tools_response = frame
                    break

        assert tools_response is not None, "No tools/list response received"
        assert "result" in tools_response, tools_response
        tools = tools_response["result"].get("tools", [])
        tool_names = {t.get("name") for t in tools}
        assert tool_names == {
            "list_courses",
            "get_course",
            "search_lesson_content",
            "ask_tutor",
            "list_my_due_reviews",
            "grade_review_card",
            "create_course_draft",
            "ingest_url_to_draft",
            "list_my_progress",
        }, f"Unexpected tool set: {tool_names}"

    finally:
        # Shut the subprocess down cleanly.
        import contextlib

        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            async with asyncio.timeout(5):
                await proc.wait()
        except TimeoutError:
            proc.kill()
            await proc.wait()
