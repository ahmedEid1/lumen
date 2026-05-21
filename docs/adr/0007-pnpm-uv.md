# ADR-0007: uv for Python, pnpm for Node

- **Status:** Accepted
- **Date:** 2026-05-21
- **Deciders:** @ahmedEid1

## Context

We need fast, reproducible installs in CI and on developer machines for both Python and Node tooling.

## Decision

- **Python:** `uv` for venvs, dependency resolution, and lockfile (`uv.lock`).
- **Node:** `pnpm` with strict node-linker and a committed `pnpm-lock.yaml`.

Both are pinned in `Dockerfile`s by version.

## Alternatives considered

- **Poetry** — proven, slower; fine, but `uv` resolves and installs ~10× faster and produces a single binary lockfile.
- **npm / yarn** — npm is slow on large workspaces; yarn is fine but pnpm's content-addressed store is best for our Docker layer caching strategy.

## Consequences

- Developers install `uv` and `pnpm` (or use the Compose dev containers which include both).
- Faster cold installs, faster CI.

## References

- [uv](https://docs.astral.sh/uv/)
- [pnpm](https://pnpm.io/)
