---
name: pytest-infra
description: Backend pytest is parallelized with xdist (4 workers) and uses memory limiter via forced ENV=test; full suite under 3 min local / 12 min CI
metadata: 
  node_type: memory
  type: project
  originSessionId: 4059c30a-7172-4501-9264-82e562516963
---

The backend test suite runs under pytest-xdist with `-n 4` workers (matched to CI's 4 vCPU ubuntu-24.04). Each worker gets its own UUID-suffixed Postgres DB (`lumen_test_{gwN}_{uuid}`), and rate-limit tests rely on the in-process `memory://` slowapi backend that's only selected when `ENV=test` — `conftest.py` now forces `os.environ["ENV"] = "test"` unconditionally (was `setdefault`, which was a no-op locally because the dev api container ships ENV=development).

**Why:** Before this work the suite was timing out at the 25-min CI cap (run 26421524850 hit 34 min, manually cancelled). 608 tests serial on a session-scoped asyncio loop with TRUNCATE between each test is genuinely wall-time bound, not deadlock-bound.

**How to apply:**
- Don't bump `-n 4` to `-n auto`. On 12-core dev boxes that's 12 concurrent `CREATE DATABASE` statements — postgres serializes and workers crash with `KeyError: <WorkerController gwN>`.
- `--timeout-method=thread` is required for asyncio tests; `signal` doesn't compose with the session-scoped event loop.
- `--max-worker-restart=0` prevents a 14-min xdist deadlock when a worker is killed via `os._exit` from pytest-timeout — fail-fast instead of hang.
- `--timeout=120` (not 60): CI is ~10× slower per test than local Docker due to 4-vCPU contention between workers + postgres + redis service containers.
- TRUNCATE list in `db_session` is now metadata-driven (`Base.metadata.tables`), so new tables join the cleanup set automatically.
- Drop `-q` everywhere (CI workflow, Makefile) — pyproject `addopts` pins `-v --durations=10` for streaming output; quiet mode would override and re-introduce the "hung suite" diagnostic blindspot.

Local: 2:42 (632 passed, coverage 71.86%). CI: ~12 min backend job. See [[session-handoff]] for current branch state.
