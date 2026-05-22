"""Lumen MCP server — the protocol surface Claude talks to.

Lumen v2 Phase I1. This module builds the MCP server instance,
registers every tool declared in :mod:`app.mcp.tools`, and exposes
both transports the spec calls for:

* **stdio** — Claude Desktop's default transport. The client
  launches us as a subprocess and speaks JSON-RPC over stdin/stdout.
  Authentication is a static Bearer token in ``LUMEN_MCP_AUTH_TOKEN``
  — the operator pastes the secret into the Claude Desktop config
  block, we resolve it to an :class:`~app.mcp.principal.Principal`
  on every call.
* **streamable-http** — Claude Code's preferred transport for hosted
  servers. The client POSTs JSON-RPC frames to our HTTP endpoint
  and streams responses back. Authentication is OAuth 2.0 client-
  credentials (see :mod:`app.mcp.auth`): every JSON-RPC request
  carries a Bearer JWT in ``Authorization``, we decode it,
  resolve the principal, and dispatch.

The high-level shape uses :class:`mcp.server.fastmcp.FastMCP`, which
is the Python SDK's recommended frontend. Tools are registered via
the ``@mcp.tool()`` decorator; we walk :data:`TOOL_SPECS` from
``tools.py`` and bind each to a closure that:

1. Pulls the current :class:`Principal` off the request context
   (set by either the stdio static-token resolver or the HTTP
   OAuth middleware).
2. Runs the spec's auth gate (``public`` / ``user`` / ``instructor``
   / ``admin``).
3. Runs the per-tool scope check (the OAuth ``scopes`` claim).
4. Opens an ``AsyncSession`` and calls the matching tool function.

This module is deliberately conservative about importing the ``mcp``
package eagerly — it's pulled in inside :func:`create_mcp_server` so
the rest of the codebase (including the migrations CLI) can import
``app.mcp.tools`` for type checking without paying the SDK's import
cost. The tests for the tool implementations don't need the SDK at
all and reach into ``tools.py`` directly.

The CLI entrypoint lives in :mod:`app.mcp.__main__` (``python -m
app.mcp.server`` works because we also expose the create-and-run
helpers here; ``__main__.py`` is the argparse shell on top).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, ClassVar

from app.core.config import get_settings
from app.core.errors import (
    AppError,
    ForbiddenError,
    UnauthorizedError,
)
from app.core.logging import get_logger
from app.db.base import get_sessionmaker
from app.mcp import auth as mcp_auth
from app.mcp import tools as mcp_tools
from app.mcp.principal import (
    Principal,
    resolve_from_jwt,
    resolve_from_static_token,
)
from app.mcp.tools import TOOL_SPECS, ToolSpec

log = get_logger(__name__)


# ContextVar carrying the active :class:`Principal` for the duration
# of one tool call. The transport layer (stdio or HTTP) sets this
# before invoking the dispatcher; the dispatcher reads it via
# :func:`current_principal`.
_PRINCIPAL_VAR: ContextVar[Principal | None] = ContextVar("lumen_mcp_principal", default=None)


def current_principal() -> Principal:
    """Return the principal in scope or raise :class:`UnauthorizedError`.

    The error case isn't a soft "anonymous" return — the dispatcher
    sets the principal before every tool call, so a missing value
    is a programming error (or a misconfigured transport) rather than
    an unauthenticated request. Surfacing the failure as
    :class:`UnauthorizedError` lets the framework map it to the
    correct JSON-RPC error code without a special case.
    """
    p = _PRINCIPAL_VAR.get()
    if p is None:
        raise UnauthorizedError("No MCP principal in scope", code="mcp.no_principal")
    return p


def _enforce_auth(spec: ToolSpec, principal: Principal) -> None:
    """Enforce the tool's static auth posture before invoking it.

    The ``public`` posture still requires a principal — we just
    don't gate on role / scope. This lets the cost meter + audit
    surface attribute every MCP call to a known identity.
    """
    if spec.auth == "public":
        # Even public tools need a recognised principal so we can
        # attribute traces / costs. Scope check still applies though.
        pass
    elif spec.auth == "user":
        pass  # any authenticated principal is fine
    elif spec.auth == "instructor":
        if not principal.is_instructor:
            raise ForbiddenError(
                "MCP tool requires instructor role",
                code="mcp.role.instructor_required",
                details={"tool": spec.name},
            )
    elif spec.auth == "admin":
        if not principal.is_admin:
            raise ForbiddenError(
                "MCP tool requires admin role",
                code="mcp.role.admin_required",
                details={"tool": spec.name},
            )
    else:  # pragma: no cover - defensive
        raise ForbiddenError(
            f"Unknown auth posture {spec.auth!r}",
            code="mcp.role.unknown",
        )

    if not principal.has_scope(spec.name):
        raise ForbiddenError(
            "MCP token lacks scope for this tool",
            code="mcp.scope.denied",
            details={"tool": spec.name, "scopes": principal.scopes},
        )


# Map from MCP tool name to the underlying ``tools.py`` coroutine.
# Built once at import; the dispatcher loop reads it per call.
_DISPATCH: dict[str, Callable[..., Awaitable[Any]]] = {
    "list_courses": mcp_tools.list_courses,
    "get_course": mcp_tools.get_course,
    "search_lesson_content": mcp_tools.search_lesson_content,
    "ask_tutor": mcp_tools.ask_tutor,
    "list_my_due_reviews": mcp_tools.list_my_due_reviews,
    "grade_review_card": mcp_tools.grade_review_card,
    "create_course_draft": mcp_tools.create_course_draft,
    "ingest_url_to_draft": mcp_tools.ingest_url_to_draft,
    "list_my_progress": mcp_tools.list_my_progress,
}


async def dispatch_tool(name: str, *, principal: Principal, **kwargs: Any) -> Any:
    """Run one tool call after the transport has resolved a principal.

    The transport-layer code is responsible for:

    1. Authenticating the inbound request and resolving a
       :class:`Principal`.
    2. Setting :data:`_PRINCIPAL_VAR` for the duration of the call
       (via :func:`set_principal`).
    3. Decoding the JSON-RPC params into kwargs.

    This dispatcher then runs the static auth + scope checks,
    opens an ``AsyncSession``, and invokes the matching tool
    function with the principal threaded in.

    Returns the tool's typed Pydantic output (a dict / list of
    dicts after ``.model_dump(mode='json')``) — the FastMCP layer
    serialises that as the JSON-RPC response.
    """
    spec = next((s for s in TOOL_SPECS if s.name == name), None)
    if spec is None:
        raise ValueError(f"Unknown MCP tool: {name!r}")

    func = _DISPATCH.get(name)
    if func is None:  # pragma: no cover - keep parity with TOOL_SPECS
        raise ValueError(f"No dispatcher entry for MCP tool {name!r}")

    _enforce_auth(spec, principal)

    Session = get_sessionmaker()
    async with Session() as session:
        try:
            result = await func(session, principal=principal, **kwargs)
            await session.commit()
        except AppError:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise

    # All tool outputs are Pydantic models or lists of them — dump
    # to a JSON-safe shape for the wire.
    if isinstance(result, list):
        return [item.model_dump(mode="json") for item in result]
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return result  # pragma: no cover — defensive


def set_principal(principal: Principal | None) -> Any:
    """Set the active principal for the current task; return the reset token.

    The transport calls this as a one-liner around each tool call so
    nested calls (e.g. an HTTP transport handling a JSON-RPC batch)
    don't leak the previous request's identity.
    """
    return _PRINCIPAL_VAR.set(principal)


def reset_principal(token: Any) -> None:
    """Pop the principal set by a previous :func:`set_principal` call."""
    _PRINCIPAL_VAR.reset(token)


# ---------- FastMCP server construction ----------


def _import_fastmcp():  # type: ignore[no-untyped-def]
    """Defer the ``mcp`` import to call time.

    Several test paths (and the migrations CLI) import this module
    just to read :data:`TOOL_SPECS` or :func:`dispatch_tool`; pulling
    the heavyweight ``mcp`` package in at module-level would force
    everyone to install it even when they don't need it. The
    transport entrypoints (``run_stdio`` / ``run_http``) are the only
    callers that actually need the SDK, and they hit this helper.
    """
    try:
        # The MCP Python SDK exposes a high-level ``FastMCP`` server
        # under ``mcp.server.fastmcp``. We don't import it at module
        # scope so the rest of the codebase can read TOOL_SPECS
        # without installing the SDK.
        from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - install-time guard
        raise RuntimeError("mcp package is not installed — `pip install mcp>=1.5`") from exc
    return FastMCP


def create_mcp_server(server_name: str = "lumen") -> Any:
    """Build a :class:`FastMCP` instance with every tool registered.

    Each tool is wired with a thin closure that:

    1. Reads the active :class:`Principal` off the context var.
    2. Runs the dispatcher (which handles auth + DB session).
    3. Returns the JSON-serialised result.

    Returning the raw FastMCP instance keeps this helper transport-
    agnostic — the caller (CLI or test) decides whether to run it
    over stdio or HTTP.
    """
    FastMCP = _import_fastmcp()
    mcp = FastMCP(server_name)

    for spec in TOOL_SPECS:
        _register_tool(mcp, spec)

    return mcp


def _register_tool(mcp: Any, spec: ToolSpec) -> None:
    """Bind one tool to its dispatcher closure on the FastMCP instance.

    The FastMCP decorator inspects the wrapped function's type
    annotations to build the JSON schema MCP clients see in
    ``tools/list``. We declare a thin async wrapper per tool with the
    same signature as the underlying ``tools.py`` function (minus
    ``db`` + ``principal``, both supplied by the dispatcher) so the
    SDK can introspect the parameters Claude needs to pass.
    """
    name = spec.name
    description = spec.description

    # Per-tool closures — we use ``if / elif`` rather than a single
    # ``**kwargs`` shape so FastMCP's schema introspection sees the
    # actual parameter names + types. Each wrapper just forwards to
    # the dispatcher.

    if name == "list_courses":

        @mcp.tool(name=name, description=description)
        async def _list_courses(filter: str | None = None, limit: int = 20) -> Any:
            return await dispatch_tool(
                name, principal=current_principal(), filter=filter, limit=limit
            )

    elif name == "get_course":

        @mcp.tool(name=name, description=description)
        async def _get_course(slug: str) -> Any:
            return await dispatch_tool(name, principal=current_principal(), slug=slug)

    elif name == "search_lesson_content":

        @mcp.tool(name=name, description=description)
        async def _search_lesson_content(course_slug: str, query: str, top_k: int = 5) -> Any:
            return await dispatch_tool(
                name,
                principal=current_principal(),
                course_slug=course_slug,
                query=query,
                top_k=top_k,
            )

    elif name == "ask_tutor":

        @mcp.tool(name=name, description=description)
        async def _ask_tutor(course_slug: str, question: str) -> Any:
            return await dispatch_tool(
                name,
                principal=current_principal(),
                course_slug=course_slug,
                question=question,
            )

    elif name == "list_my_due_reviews":

        @mcp.tool(name=name, description=description)
        async def _list_my_due_reviews(limit: int = 20) -> Any:
            return await dispatch_tool(name, principal=current_principal(), limit=limit)

    elif name == "grade_review_card":

        @mcp.tool(name=name, description=description)
        async def _grade_review_card(card_id: str, rating: int) -> Any:
            return await dispatch_tool(
                name,
                principal=current_principal(),
                card_id=card_id,
                rating=rating,
            )

    elif name == "create_course_draft":

        @mcp.tool(name=name, description=description)
        async def _create_course_draft(brief: str, subject_slug: str | None = None) -> Any:
            return await dispatch_tool(
                name,
                principal=current_principal(),
                brief=brief,
                subject_slug=subject_slug,
            )

    elif name == "ingest_url_to_draft":

        @mcp.tool(name=name, description=description)
        async def _ingest_url_to_draft(url: str, course_id: str | None = None) -> Any:
            return await dispatch_tool(
                name,
                principal=current_principal(),
                url=url,
                course_id=course_id,
            )

    elif name == "list_my_progress":

        @mcp.tool(name=name, description=description)
        async def _list_my_progress() -> Any:
            return await dispatch_tool(name, principal=current_principal())

    else:  # pragma: no cover - kept in sync with TOOL_SPECS
        raise RuntimeError(f"No wrapper defined for MCP tool {name!r}")


# ---------- Transport entrypoints ----------


async def run_stdio() -> None:
    """Run the MCP server over stdio.

    Resolves the static Bearer token from ``LUMEN_MCP_AUTH_TOKEN``
    once at startup (cheap argon2 verify per registered client) and
    pins it on the context var for the duration of the process —
    every tool call by this stdio client acts as the same principal.

    Claude Desktop launches us as a subprocess; the conventional
    config block in ``~/Library/Application Support/Claude/claude_desktop_config.json``
    passes the env vars through. See :doc:`docs/mcp.md` for the
    operator-facing setup.
    """
    token = os.environ.get("LUMEN_MCP_AUTH_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "LUMEN_MCP_AUTH_TOKEN env var is required for stdio transport."
            " Run `make mcp-token` to mint one."
        )

    Session = get_sessionmaker()
    async with Session() as session:
        principal = await resolve_from_static_token(session, token)
        await session.commit()

    log.info(
        "mcp_stdio_principal_resolved",
        user_id=principal.user_id,
        client_id=principal.client_id,
        scopes=principal.scopes,
    )

    # Pin the principal for the lifetime of the stdio process. Tools
    # all dispatch through the same context, so this single set is
    # sufficient — we never swap principals on a stdio connection
    # because the protocol has no concept of switching identity
    # mid-stream.
    _PRINCIPAL_VAR.set(principal)

    mcp = create_mcp_server()
    # FastMCP exposes a ``run_stdio_async`` coroutine that owns the
    # I/O loop. If the SDK ever renames it, this is the one line to
    # update.
    await mcp.run_stdio_async()


async def run_http(*, host: str = "0.0.0.0", port: int = 8001) -> None:  # noqa: S104
    """Run the MCP server over streamable HTTP with OAuth gating.

    The FastMCP SDK exposes a Starlette app under
    ``mcp.streamable_http_app()``. We wrap it in a middleware that:

    1. Mounts ``POST /oauth/token`` and ``GET /.well-known/oauth-
       authorization-server`` from :mod:`app.mcp.auth`.
    2. Intercepts every MCP request, decodes the Bearer JWT, resolves
       the principal, sets the context var, and proxies to the
       FastMCP app.

    The wrapping happens inside this function so the SDK import
    stays deferred — same reasoning as :func:`create_mcp_server`.
    """
    # Imported here so the SDK isn't pulled in unless we actually
    # run the HTTP transport.
    import uvicorn  # type: ignore[import-not-found]
    from starlette.applications import Starlette  # type: ignore[import-not-found]
    from starlette.middleware.base import BaseHTTPMiddleware  # type: ignore[import-not-found]
    from starlette.requests import Request  # type: ignore[import-not-found]
    from starlette.responses import JSONResponse  # type: ignore[import-not-found]
    from starlette.routing import Mount, Route  # type: ignore[import-not-found]

    settings = get_settings()
    jwt_secret = settings.jwt_secret.get_secret_value()
    jwt_algorithm = settings.jwt_algorithm

    mcp = create_mcp_server()

    async def token_endpoint(request: Request) -> JSONResponse:
        """RFC 6749 §4.4 client-credentials token endpoint."""
        try:
            form = await request.form()
            client_id = str(form.get("client_id") or "")
            client_secret = str(form.get("client_secret") or "")
            scope_str = str(form.get("scope") or "").strip()
        except Exception:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        requested_scopes = scope_str.split() if scope_str else None

        Session = get_sessionmaker()
        try:
            async with Session() as session:
                payload = await mcp_auth.issue_token(
                    session,
                    client_id=client_id,
                    client_secret=client_secret,
                    requested_scopes=requested_scopes,
                    jwt_secret=jwt_secret,
                    jwt_algorithm=jwt_algorithm,
                )
                await session.commit()
            return JSONResponse(payload)
        except UnauthorizedError as exc:
            return JSONResponse(
                {"error": "invalid_client", "error_description": exc.message},
                status_code=401,
            )

    async def metadata_endpoint(request: Request) -> JSONResponse:
        """RFC 8414 authorisation-server metadata."""
        base = f"{request.url.scheme}://{request.url.netloc}"
        return JSONResponse(mcp_auth.authorization_server_metadata(base_url=base))

    class _OAuthBearerMiddleware(BaseHTTPMiddleware):
        """Decode the Bearer JWT and pin a Principal for each MCP request.

        Skips the OAuth endpoints + the metadata document so the
        token-mint round-trip itself isn't gated.
        """

        SKIP_PATHS: ClassVar[set[str]] = {
            "/oauth/token",
            "/.well-known/oauth-authorization-server",
        }

        async def dispatch(self, request, call_next):  # type: ignore[override]
            if request.url.path in self.SKIP_PATHS:
                return await call_next(request)

            authz = request.headers.get("authorization", "")
            if not authz.lower().startswith("bearer "):
                return JSONResponse({"error": "missing_token"}, status_code=401)
            token = authz.split(" ", 1)[1].strip()

            Session = get_sessionmaker()
            try:
                async with Session() as session:
                    principal = await resolve_from_jwt(
                        session,
                        token,
                        jwt_secret=jwt_secret,
                        jwt_algorithm=jwt_algorithm,
                    )
            except UnauthorizedError as exc:
                return JSONResponse(
                    {"error": exc.code, "error_description": exc.message},
                    status_code=401,
                )

            reset = set_principal(principal)
            try:
                return await call_next(request)
            finally:
                reset_principal(reset)

    # FastMCP gives us a Starlette ASGI app for the streamable-HTTP
    # transport; we mount it under ``/mcp`` and add our OAuth routes
    # at the root.
    sub_app = mcp.streamable_http_app()
    app = Starlette(
        routes=[
            Route("/oauth/token", token_endpoint, methods=["POST"]),
            Route(
                "/.well-known/oauth-authorization-server",
                metadata_endpoint,
                methods=["GET"],
            ),
            Mount("/mcp", app=sub_app),
        ],
    )
    app.add_middleware(_OAuthBearerMiddleware)

    config = uvicorn.Config(app=app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def run() -> None:
    """Default entrypoint — stdio transport.

    Convenience for ``python -m app.mcp.server`` without the full
    argparse shim. The richer CLI lives in :mod:`app.mcp.__main__`.
    """
    asyncio.run(run_stdio())


__all__ = [
    "create_mcp_server",
    "current_principal",
    "dispatch_tool",
    "reset_principal",
    "run",
    "run_http",
    "run_stdio",
    "set_principal",
]


if __name__ == "__main__":  # pragma: no cover
    # ``python -m app.mcp.server`` is the alternative entrypoint mentioned
    # in the operator docs; defers to the richer argparse CLI in
    # :mod:`app.mcp.__main__` so the two paths can't drift.
    import sys as _sys

    from app.mcp.__main__ import main as _cli_main

    _sys.exit(_cli_main(_sys.argv[1:]))
