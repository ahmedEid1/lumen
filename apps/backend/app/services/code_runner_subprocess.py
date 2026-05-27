"""Subprocess-isolated code-runner (L21-Sec).

The legacy in-process runner (``app/services/tutor_subagents/code_runner.py``)
uses RestrictedPython for AST-level guarding + an ``asyncio.wait_for``
wall-clock deadline. Two failure modes the in-process shape can't
defend against:

- **CPU exhaustion.** ``while True: pass`` consumes a CPU core
  indefinitely; ``asyncio.wait_for`` cancels the *await*, not the
  thread the work is running on. The thread keeps spinning until the
  API container restarts.
- **Memory exhaustion.** ``x = "a" * 10**9`` allocates ~1 GB inside
  the API process. Even if the host has the memory, OOMing the API
  takes down auth, the dashboard, every other learner's session.

Mitigation (plan-v7 §V7-Sec code-runner): spawn a dedicated subprocess
with ``resource.setrlimit(RLIMIT_CPU, (n, n))`` and
``RLIMIT_AS`` set to a tight ceiling, then SIGKILL on wall-clock
overrun. The kernel handles the CPU + memory limits; we only have to
worry about not blocking the event loop while we wait.

POSIX-only — ``resource`` doesn't exist on Windows. The dev/test
matrix is Linux + macOS (the prod deploy is Linux); the in-process
runner remains the fallback elsewhere.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from dataclasses import dataclass

from app.core.logging import get_logger

log = get_logger(__name__)


DEFAULT_CPU_SECONDS = 2
DEFAULT_MEMORY_BYTES = 256 * 1024 * 1024  # 256 MB
DEFAULT_WALL_TIMEOUT_SECONDS = 5
MAX_STDOUT_CHARS = 4_000


@dataclass(frozen=True)
class SubprocessResult:
    """Outcome of a subprocess run.

    ``exit_code`` mirrors the in-process runner: 0 ok, 1 runtime error
    (or limit-killed), 2 compile error. ``killed_by`` is set when the
    kernel or this module SIGKILLed the child (CPU/MEM/timeout).
    """

    stdout: str
    exit_code: int
    error_msg: str | None
    killed_by: str | None  # "RLIMIT_CPU" | "RLIMIT_AS" | "wall_timeout" | None


# The script the subprocess runs. Kept inline as a literal so we can
# spawn it via `python -c` and not depend on the path of a separate
# script file (which would break under different working directories).
_CHILD_SCRIPT = r"""
import json
import resource
import sys

cfg = json.loads(sys.stdin.read())
cpu_seconds = int(cfg["cpu_seconds"])
mem_bytes = int(cfg["memory_bytes"])
code = cfg["code"]

# Apply the kernel limits BEFORE importing anything heavy — that way
# a child that gets RLIMIT_AS-killed mid-import looks like an OOM,
# not a mysterious ImportError.
resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

# Import RestrictedPython after rlimits are armed. If the install is
# missing it, surface a structured error.
try:
    from RestrictedPython import compile_restricted
    from RestrictedPython.Eval import default_guarded_getiter
    from RestrictedPython.Guards import safe_builtins, safer_getattr
except ImportError as exc:
    print(json.dumps({
        "stdout": "",
        "exit_code": 2,
        "error_msg": f"sandbox-missing: {exc}",
    }))
    sys.exit(0)


SAFE_MODULES = {"math", "statistics"}

def _safe_import(name, globals_=None, locals_=None, fromlist=(), level=0):
    del globals_, locals_, level
    if name not in SAFE_MODULES:
        raise ImportError(f"import of {name!r} is not allowed in the tutor sandbox")
    import importlib
    return importlib.import_module(name)


captured = []

def _print_fn(*args, **kwargs):
    sep = str(kwargs.get("sep", " "))
    end = str(kwargs.get("end", "\n"))
    captured.append(sep.join(str(a) for a in args) + end)


class _PrintCollector:
    def write(self, text):
        if text:
            captured.append(str(text))
    def __call__(self, *args, **kwargs):
        if args or kwargs:
            sep = str(kwargs.get("sep", " "))
            end = str(kwargs.get("end", "\n"))
            captured.append(sep.join(str(a) for a in args) + end)
            return ""
        return "".join(captured)
    def _call_print(self, *args, **kwargs):
        self.__call__(*args, **kwargs)


class _PrintCollectorFactory:
    def __call__(self, _ignored=None):
        return _PrintCollector()


builtins = dict(safe_builtins)
builtins["__import__"] = _safe_import
builtins["print"] = _print_fn


try:
    compiled = compile_restricted(code, filename="<tutor-sandbox>", mode="exec")
except SyntaxError as exc:
    print(json.dumps({
        "stdout": "",
        "exit_code": 2,
        "error_msg": f"compile error: {exc.msg} at line {exc.lineno}",
    }))
    sys.exit(0)
except Exception as exc:
    print(json.dumps({
        "stdout": "",
        "exit_code": 2,
        "error_msg": f"compile error: {type(exc).__name__}: {exc}",
    }))
    sys.exit(0)

safe_globals = {
    "__builtins__": builtins,
    "_print_": _PrintCollectorFactory(),
    "_getattr_": safer_getattr,
    "_getiter_": default_guarded_getiter,
    "_getitem_": lambda obj, key: obj[key],
    "_write_": lambda x: x,
}

try:
    exec(compiled, safe_globals, safe_globals)
except Exception as exc:
    out = "".join(captured)
    print(json.dumps({
        "stdout": out[:4000],
        "exit_code": 1,
        "error_msg": f"runtime error: {type(exc).__name__}: {exc}",
    }))
    sys.exit(0)

out = "".join(captured)
print(json.dumps({
    "stdout": out[:4000],
    "exit_code": 0,
    "error_msg": None,
}))
"""


async def execute_in_subprocess(
    code: str,
    *,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
    memory_bytes: int = DEFAULT_MEMORY_BYTES,
    wall_timeout_seconds: int = DEFAULT_WALL_TIMEOUT_SECONDS,
) -> SubprocessResult:
    """Spawn a Python subprocess to run ``code`` under RLIMIT_CPU + RLIMIT_AS.

    The child receives its config + code on stdin (a single JSON line),
    runs the RestrictedPython execution under the kernel limits, and
    emits a single JSON line on stdout. The parent times out the
    wall-clock and SIGKILLs on overrun — RLIMIT_CPU is the more
    interesting bound (kills on user-mode CPU usage, not on
    process-blocking I/O), but a deliberate fork-bomb or syscall
    storm could still consume wall time without burning CPU; the
    wall-clock cap is the safety net.
    """
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _CHILD_SCRIPT,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # Tighten the child's process attributes. A new process group
        # makes the killpg easier; closing FDs reduces blast radius if
        # the child somehow gets file-descriptor inheritance wrong.
        start_new_session=True,
        close_fds=True,
    )

    config = json.dumps(
        {
            "cpu_seconds": cpu_seconds,
            "memory_bytes": memory_bytes,
            "code": code,
        }
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=config.encode("utf-8")),
            timeout=wall_timeout_seconds,
        )
    except TimeoutError:
        # SIGKILL the entire process group. SIGTERM-then-wait is the
        # polite shape; here we don't have the luxury — a hanging
        # learner snippet is bad UX.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, 9)  # SIGKILL
        try:
            await proc.wait()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("code_runner_subprocess_wait_after_kill_failed", error=str(exc))
        return SubprocessResult(
            stdout="",
            exit_code=1,
            error_msg=f"execution exceeded {wall_timeout_seconds}s wall-clock deadline",
            killed_by="wall_timeout",
        )

    if proc.returncode != 0:
        # Non-zero exit without our own JSON response = the child was
        # killed by the kernel (CPU/MEM rlimit) before it could write
        # back. Linux returns 128+signum; SIGKILL=9 → 137; some
        # platforms report SIGXCPU=24 → 152.
        if proc.returncode in (137, -9):
            kb = "RLIMIT_AS_or_KILL"
        elif proc.returncode in (152, -24):
            kb = "RLIMIT_CPU"
        else:
            kb = f"exit_{proc.returncode}"
        stderr_text = stderr.decode(errors="replace")[:200]
        return SubprocessResult(
            stdout="",
            exit_code=1,
            error_msg=(f"subprocess killed (returncode={proc.returncode}, stderr={stderr_text!r})"),
            killed_by=kb,
        )

    try:
        body = json.loads(stdout.decode("utf-8").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError, UnicodeDecodeError) as exc:
        return SubprocessResult(
            stdout="",
            exit_code=1,
            error_msg=f"subprocess returned malformed response: {exc}",
            killed_by=None,
        )

    return SubprocessResult(
        stdout=body.get("stdout", ""),
        exit_code=int(body.get("exit_code", 1)),
        error_msg=body.get("error_msg"),
        killed_by=None,
    )
