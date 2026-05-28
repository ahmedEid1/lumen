# ADR-0023: Native arm64-only container builds (drop QEMU multi-arch)

- **Status:** Accepted
- **Date:** 2026-05-28
- **Deciders:** @ahmedEid1 (decided by the autonomous QA loop under delegated judgment)

## Context

`ci.yml`'s `build-images` job published a multi-arch manifest covering
`linux/amd64` (built natively on the `ubuntu-24.04` runner) and `linux/arm64`
(cross-built under QEMU emulation via `docker/setup-qemu-action`). Emulated
builds are roughly an order of magnitude slower than native.

After the frontend picked up heavier build-time dependencies (`react-markdown`
+ `remark-gfm` + Shiki highlighting, iter 16), the emulated arm64 Next.js build
crossed the job's `timeout-minutes: 60` ceiling. On CI run **26587224139**
(2026-05-28) every code job was green — Backend, Frontend, E2E, Accessibility —
but `build-images` was **cancelled at exactly 60:00** on the "Build frontend"
step's arm64 leg, so the `deploy` job was **skipped**. iter-20 (tutor
refusal-chip guardrail) and iter-21 (page titles) never shipped, and the
failure is structural: every subsequent push would hit the same wall, blocking
all deploys.

Two facts make the multi-arch build wasteful rather than merely slow:

1. **The only consumer of the GHCR images is the production box**, an AWS
   `t4g.small` (Graviton / aarch64). `docker-compose.prod.yml` pulls
   `ghcr.io/.../lumen-{api,web}` onto that arm64 host.
2. **Local development never pulls those tags** — `docker-compose.yml` uses
   `build:` to produce `lumen-*:dev` images locally on whatever arch the
   developer is on.

So the published `linux/amd64` image is consumed by nothing. And because this
repository is **public**, GitHub-hosted **arm64 runners** (`ubuntu-24.04-arm`)
are available at no cost.

## Decision

Build **arm64 only, natively, on `ubuntu-24.04-arm`**. Remove
`docker/setup-qemu-action` and the `linux/amd64` platform from both
`ci.yml`'s `build-images` job and `release.yml`'s `publish` job. Drop the
build-images timeout from 60 → 35 minutes (native single-arch should land in
~15–25 min, so 35 fails fast without flaking on a cold cache).

## Alternatives considered

- **Raise `timeout-minutes` past 60.** A band-aid: a 60-plus-minute emulated
  build is an unacceptable deploy cadence, and the frontend will only grow.
  Rejected.
- **Native multi-arch matrix** — amd64 on `ubuntu-24.04` + arm64 on
  `ubuntu-24.04-arm` in parallel, then `buildx imagetools create` to merge the
  two digests into one manifest. This is the canonical fast multi-arch pattern
  and would keep amd64, but amd64 is provably unused here; the extra job,
  digest export, and manifest-merge step add surface area (and a `deploy.needs`
  change pinned by `ci-workflow-shape.test.ts`) for no consumer. Rejected on
  YAGNI; documented in the `build-images` header as the path to take if an
  amd64 consumer ever appears.
- **Keep QEMU, build only arm64 on the amd64 runner.** Still emulated, still
  slow. Rejected.

## Consequences

- **Positive:** the build runs natively and drops well under the timeout, so
  deploys are unblocked. The image arch matches its only consumer. Zero added
  cost (free public-repo arm64 runner). Fixes a latent `release.yml` bug — it
  had no `platforms:` and so published **amd64-only** `:vX.Y.Z` + `:latest`,
  which would have moved `:latest` to an undeployable arch on the next tagged
  release.
- **Negative:** no `linux/amd64` image is published to GHCR, so the images
  can't be pulled/run on an amd64 host. Mitigation: dev builds locally
  (arch-agnostic) and prod is arm64; if an amd64 consumer appears, add the
  native matrix leg described above.
- **Neutral:** the Trivy scans and SARIF upload now run on an arm64 runner
  (both support arm64). GHA layer cache (`type=gha`, per-image scope) is
  unchanged.

## References

- CI run 26587224139 (2026-05-28) — the 60-min build timeout that skipped the
  deploy and motivated this ADR.
- CI run 26433960527 (2026-05-26) — the original `no matching manifest for
  linux/arm64/v8` failure that introduced the QEMU multi-arch build now being
  replaced.
- `docker-compose.prod.yml` (arm64 GHCR consumer) and `docker-compose.yml`
  (local `build:`, no GHCR pull).
- GitHub-hosted arm64 Linux runners (free for public repositories).
