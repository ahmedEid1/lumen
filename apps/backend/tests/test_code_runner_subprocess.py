"""Code-runner subprocess hardening (L21-Sec).

These exercise the kernel-level RLIMIT_CPU + RLIMIT_AS + wall-timeout
defences. Linux-only — `resource` doesn't exist on Windows, and macOS
RLIMIT_AS behaviour differs enough to be noisy. CI runs on Ubuntu.
"""

from __future__ import annotations

import sys

import pytest

from app.services.code_runner_subprocess import execute_in_subprocess

# All tests need the real Python interpreter + RestrictedPython
# installed in the test container; conftest already gates that for
# the rest of the suite.
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="subprocess RLIMIT tests are Linux-only",
)


async def test_happy_path_runs_and_captures_stdout() -> None:
    res = await execute_in_subprocess("print(2 + 2)")
    assert res.exit_code == 0
    assert res.stdout.strip() == "4"
    assert res.error_msg is None
    assert res.killed_by is None


async def test_imports_a_safe_module() -> None:
    res = await execute_in_subprocess("import math\nprint(math.sqrt(16))")
    assert res.exit_code == 0
    assert "4" in res.stdout


async def test_blocks_unsafe_module_import() -> None:
    res = await execute_in_subprocess("import os\nprint(os.environ)")
    # RestrictedPython compiles fine but our _safe_import refuses; the
    # body runs and raises ImportError → runtime error.
    assert res.exit_code in (1, 2)
    if res.exit_code == 1:
        assert "not allowed" in (res.error_msg or "")


async def test_syntax_error_returned_as_compile_error() -> None:
    res = await execute_in_subprocess("def broken(:")
    assert res.exit_code == 2
    assert "compile error" in (res.error_msg or "")


async def test_runtime_error_captured() -> None:
    res = await execute_in_subprocess("print(1/0)")
    assert res.exit_code == 1
    assert "ZeroDivisionError" in (res.error_msg or "")


async def test_infinite_loop_killed_by_cpu_limit_or_wall_clock() -> None:
    """``while True: pass`` should not consume more than the CPU
    quota; we accept either RLIMIT_CPU kill or our wall-clock fallback
    (depends on whether the loop yields to anything)."""
    res = await execute_in_subprocess(
        "while True: pass",
        cpu_seconds=2,
        wall_timeout_seconds=4,
    )
    assert res.exit_code == 1
    assert res.killed_by in ("RLIMIT_CPU", "wall_timeout", "RLIMIT_AS_or_KILL"), res
    assert (
        "execut" in (res.error_msg or "").lower() or "subprocess" in (res.error_msg or "").lower()
    )


async def test_memory_bomb_killed_by_address_space_limit() -> None:
    """Allocating ~512 MB exceeds the 256 MB RLIMIT_AS — the child
    either gets MemoryError (caught + surfaced as runtime error) or
    is SIGKILLed by the kernel."""
    res = await execute_in_subprocess(
        "x = 'a' * (512 * 1024 * 1024)\nprint(len(x))",
        memory_bytes=256 * 1024 * 1024,
        wall_timeout_seconds=4,
    )
    assert res.exit_code == 1
    # Either we caught the MemoryError ourselves or the kernel
    # SIGKILLed the child. Both outcomes are acceptable defences.
    assert res.killed_by in ("RLIMIT_AS_or_KILL", None), res
    assert res.error_msg is not None


async def test_empty_code_returns_empty_stdout() -> None:
    res = await execute_in_subprocess("pass")
    assert res.exit_code == 0
    assert res.stdout == ""
