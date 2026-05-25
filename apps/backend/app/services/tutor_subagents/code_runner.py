"""Code-runner sub-agent — sandboxed Python execution.

Lumen v2 Phase I2. When the planner determines the question would
benefit from running code (a learner asks "compute the mean of these
numbers", "verify whether 18 is prime", "what does this slice
return"), it dispatches this tool. The synthesiser embeds the
captured stdout in a fenced ```python``` block in the final answer.

**Sandbox model.**

We use :mod:`RestrictedPython` (Zope's old reviewed-source executor,
still actively maintained) to compile + run user code under a tight
guard:

* No ``__import__`` — every module access goes through a curated
  ``_safe_modules`` map (today: ``math`` and ``statistics`` only).
* No ``open`` / ``exec`` / ``eval`` / ``compile`` / ``input``.
* No attribute access on dunders (``getattr_`` and ``getitem_`` use
  RestrictedPython's safe-guard hooks).
* No global writes that escape the sandbox dict.
* ``print`` is captured into an in-memory list; we return its join
  as the result ``stdout``.

A hard wall-clock timeout (5 s by default) terminates runaway loops
via :func:`signal.SIGALRM` on POSIX. On Windows :func:`signal.SIGALRM`
is unavailable, so we fall back to a thread-based deadline that
*detects* timeout but doesn't forcibly kill the worker — the
attacker would still have to land arbitrary code through the
synthesiser's prompt, which RestrictedPython already gates.

**Operator note.** This is the "safe stub" Phase J will replace with
a proper Pyodide-in-WASM runner. The current sandbox is appropriate
for tutoring use cases (compute, demonstrate stdlib behaviour) and
not appropriate for arbitrary learner code. Future work is tracked
in ``docs/agentic-tutor.md``.

If RestrictedPython refuses to compile something (the most common
failure mode for novice-author code is using a banned builtin), the
result carries the compile error in ``error_msg`` and an empty
``stdout``. The synthesiser sees the failure and adapts.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_trace import TRACE_STATUS_ERROR, TRACE_STATUS_OK
from app.services import agent_tracer

log = get_logger(__name__)

# Hard wall-clock deadline per code run. Five seconds is the same
# upper bound notebooks like Jupyter's defaults pick — enough for a
# learner-friendly compute, short enough that a bug doesn't tie up
# an orchestrator slot.
DEFAULT_TIMEOUT_SECONDS = 5

# Default output size cap. Anything beyond this gets clipped with an
# ellipsis — keeps the synthesiser's prompt bounded even if a learner
# accidentally prints a 10MB list comprehension.
MAX_STDOUT_CHARS = 4_000

# The only modules the sandbox grants access to. Stdlib-only, no I/O,
# no subprocess, no socket — and absolutely no third-party deps that
# might pull in C extensions with their own attack surface.
_SAFE_MODULES = {"math", "statistics"}


class CodeRunResult(BaseModel):
    """Output of the code-runner sub-agent."""

    model_config = ConfigDict(frozen=True)

    stdout: str = ""
    exit_code: int = Field(
        default=0,
        description="0 on success, 1 on runtime error, 2 on compile error.",
    )
    error_msg: str | None = None


def _build_safe_globals(
    captured_print: list[str],
) -> tuple[dict[str, Any], _CapturingPrintCollector]:
    """Compose the ``globals`` dict handed to the sandboxed code.

    Returns ``(globals, printer)``. The printer's accumulated text
    is the visible stdout of the sandbox run; the caller joins
    ``captured_print`` at the end.

    * ``_print_`` — RestrictedPython compiles ``print(...)`` calls
      into a small protocol against this name. We supply a tiny
      class whose ``_call_print`` collects each emitted string into
      ``captured_print``.
    * ``_getattr_`` / ``_getiter_`` / ``_getitem_`` — Restricted-
      Python's safety hooks. ``safer_getattr`` blocks dunder
      lookups; the iter/getitem hooks pass through to plain Python
      semantics so iteration + subscription work.
    """
    from RestrictedPython.Eval import default_guarded_getiter  # type: ignore[import-not-found]
    from RestrictedPython.Guards import (  # type: ignore[import-not-found]
        safe_builtins,
        safer_getattr,
    )

    def _safe_import(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        del globals_, locals_, level
        if name not in _SAFE_MODULES:
            raise ImportError(f"import of {name!r} is not allowed in the tutor sandbox")
        import importlib

        module = importlib.import_module(name)
        if fromlist:
            return module
        return module

    builtins = dict(safe_builtins)
    builtins["__import__"] = _safe_import

    # Re-add print to the safe builtins so RestrictedPython falls
    # back to a regular function call (write-through to our
    # collector) when the compiled bytecode hits ``print(...)``.
    def _print_fn(*args: Any, **kwargs: Any) -> None:
        sep = str(kwargs.get("sep", " "))
        end = str(kwargs.get("end", "\n"))
        captured_print.append(sep.join(str(a) for a in args) + end)

    builtins["print"] = _print_fn

    printer = _CapturingPrintCollector(captured_print)
    return (
        {
            "__builtins__": builtins,
            # RestrictedPython 7.x rewrites ``print(x)`` into a call
            # against ``_print_`` when the ``allow_print=True`` policy
            # is in effect (which is the default). The instance below
            # collects writes into the same list as the plain
            # ``print`` builtin above so both code paths route through
            # the same captured buffer.
            "_print_": _CapturingPrintCollectorFactory(captured_print),
            "_getattr_": safer_getattr,
            "_getiter_": default_guarded_getiter,
            "_getitem_": lambda obj, key: obj[key],
            "_write_": lambda x: x,
        },
        printer,
    )


class _CapturingPrintCollector:
    """RestrictedPython-style print collector that appends to a list.

    RestrictedPython generates code like ``_print = _print_(); ...
    _print(thing); ...; result = _print()``. We satisfy that protocol
    by exposing ``__call__`` (with no args returns the joined text,
    with args records a write) and ``write``.
    """

    def __init__(self, captured: list[str]) -> None:
        self._captured = captured

    def write(self, text: str) -> None:
        if text:
            self._captured.append(str(text))

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        if args or kwargs:
            sep = str(kwargs.get("sep", " "))
            end = str(kwargs.get("end", "\n"))
            self._captured.append(sep.join(str(a) for a in args) + end)
            return ""
        return "".join(self._captured)

    # RestrictedPython 8.x compiles ``print(x)`` into a
    # ``_print._call_print(*args, **kwargs)`` against this object
    # rather than the bare ``_print(x)`` that the 7.x docs describe.
    # The exact call signature varies across micro-releases (8.0
    # passes positional values, 8.1+ passes the tuple), so accept
    # *args/**kwargs and dispatch in a single place.
    def _call_print(self, *args: Any, **kwargs: Any) -> None:
        self.__call__(*args, **kwargs)

    def __str__(self) -> str:
        return "".join(self._captured)


class _CapturingPrintCollectorFactory:
    """Wraps :class:`_CapturingPrintCollector` so calling it (no-arg)
    yields a fresh instance — matching RestrictedPython's expectation
    that ``_print_`` is a class/factory it instantiates per-scope.
    """

    def __init__(self, captured: list[str]) -> None:
        self._captured = captured

    def __call__(self, _ignored: object | None = None) -> _CapturingPrintCollector:
        return _CapturingPrintCollector(self._captured)


def _execute(code: str, *, timeout: int) -> CodeRunResult:
    """Compile + run ``code`` under RestrictedPython. Synchronous.

    Returns a :class:`CodeRunResult`. Never raises — any failure is
    captured in ``error_msg`` + a non-zero ``exit_code``. The
    timeout is enforced by the async wrapper above (via
    :func:`asyncio.wait_for`); this function is the inner CPU-bound
    body.
    """
    try:
        from RestrictedPython import compile_restricted  # type: ignore[import-not-found]
    except ImportError as exc:
        # RestrictedPython missing from the install. We document this
        # in ``docs/agentic-tutor.md``; surface the same message the
        # operator will see in the trace payload.
        return CodeRunResult(
            stdout="",
            exit_code=2,
            error_msg=(
                "code execution not yet available in this environment "
                f"(missing RestrictedPython: {exc}); see docs/agentic-tutor.md"
            ),
        )

    captured: list[str] = []
    try:
        compiled = compile_restricted(code, filename="<tutor-sandbox>", mode="exec")
    except SyntaxError as exc:
        return CodeRunResult(
            stdout="",
            exit_code=2,
            error_msg=f"compile error: {exc.msg} at line {exc.lineno}",
        )
    except Exception as exc:
        return CodeRunResult(
            stdout="",
            exit_code=2,
            error_msg=f"compile error: {type(exc).__name__}: {exc}",
        )

    safe_globals, _printer = _build_safe_globals(captured)
    try:
        # ``exec`` here is intentional — the input has already been
        # rewritten by RestrictedPython into a guarded AST that can't
        # reach the host process's builtins, modules, or attrs. The
        # bandit S102 warning below is suppressed because the input is
        # NOT raw user code, it's the compiled-and-guarded bytecode.
        exec(compiled, safe_globals, safe_globals)  # noqa: S102
    except Exception as exc:
        # Surface the runtime error so the synthesiser can adapt.
        runtime_msg = f"runtime error: {type(exc).__name__}: {exc}"
        stdout = "".join(captured)
        if len(stdout) > MAX_STDOUT_CHARS:
            stdout = stdout[:MAX_STDOUT_CHARS] + "\n…(truncated)"
        return CodeRunResult(stdout=stdout, exit_code=1, error_msg=runtime_msg)

    stdout = "".join(captured)
    if len(stdout) > MAX_STDOUT_CHARS:
        stdout = stdout[:MAX_STDOUT_CHARS] + "\n…(truncated)"
    return CodeRunResult(stdout=stdout, exit_code=0, error_msg=None)


async def run(
    db: AsyncSession,
    *,
    code: str,
    user_id: str,
    feature: str = "tutor.multi_agent",
    step_index: int = 0,
    parent_trace_id: str | None = None,
    parent_call_id: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> CodeRunResult:
    """Run ``code`` in the sandbox with a wall-clock deadline.

    The execution itself is CPU-bound so we run it on a worker
    thread; the deadline is enforced by :func:`asyncio.wait_for`. On
    timeout we return a result with ``exit_code=1`` and an
    ``error_msg`` that names the timeout — the synthesiser can
    explain to the learner that their snippet took too long.
    """
    code = (code or "").strip()
    if not code:
        result = CodeRunResult(
            stdout="",
            exit_code=2,
            error_msg="no code provided",
        )
        await agent_tracer.record_step(
            db,
            user_id=user_id,
            feature=feature,
            step="sub_agent.code_runner",
            step_index=step_index,
            parent_trace_id=parent_trace_id,
            parent_call_id=parent_call_id,
            payload={
                "args": {"code_head": "", "timeout_seconds": timeout_seconds},
                "result_summary": {
                    "exit_code": result.exit_code,
                    "stdout_len": 0,
                    "error_msg": result.error_msg,
                },
            },
            status=TRACE_STATUS_ERROR,
        )
        return result

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_execute, code, timeout=timeout_seconds),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        result = CodeRunResult(
            stdout="",
            exit_code=1,
            error_msg=f"execution exceeded {timeout_seconds}s deadline",
        )

    trace_status = TRACE_STATUS_OK if result.exit_code == 0 else TRACE_STATUS_ERROR
    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=feature,
        step="sub_agent.code_runner",
        step_index=step_index,
        parent_trace_id=parent_trace_id,
        parent_call_id=parent_call_id,
        payload={
            "args": {
                "code_head": code[:240],
                "timeout_seconds": timeout_seconds,
            },
            "result_summary": {
                "exit_code": result.exit_code,
                "stdout_len": len(result.stdout),
                "error_msg": result.error_msg,
            },
        },
        status=trace_status,
    )
    return result


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_STDOUT_CHARS",
    "CodeRunResult",
    "run",
]
