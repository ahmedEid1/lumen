# Software Development Life Cycle

## 1. Process model

Trunk-based development with short-lived branches and continuous deployment to a staging environment. Production deploys are tag-driven and gated.

```
ideate ──► PRD/ADR ──► spike ──► design review ──► implement (branch)
   ▲                                                    │
   │                                                    ▼
   │                                              automated CI
   │                                                    │
   └──── postmortem ◄── prod release (tag) ◄── stage deploy ◄── PR review
```

## 2. Branching model

- `main` — always green, always deployable. Protected.
- `feat/<short-name>` — new feature; rebase onto `main` before merging.
- `fix/<short-name>` — bug fix.
- `chore/<short-name>` — tooling/docs/refactor with no user-visible change.
- `release/<vX.Y.Z>` — only when stabilizing a release; rare.

PRs squash-merge by default. Commit subjects follow Conventional Commits:

```
feat(courses): add publishing workflow
fix(chat): close ws on enrollment revoke
chore(deps): bump pydantic to 2.10
docs(adr): record presigned upload decision
```

## 3. Definition of Ready

A task may enter `in-progress` when it has:

- A clear acceptance criterion (or test it must pass).
- A linked PRD section or ADR for non-trivial work.
- No unresolved blocking questions.

## 4. Definition of Done

A change merges when it has:

- Passing CI (lint, type-check, unit, integration, E2E smoke).
- Adequate tests (new behaviour has a test; bug fixes have a regression test).
- Updated docs if API or contract changed.
- ADR if it introduced or changed a load-bearing decision.
- No unaddressed review comments.
- A CHANGELOG entry if user-visible.

## 5. Code review

- At least one reviewer with context.
- Use the `review` skill or `/ultrareview` for non-trivial diffs.
- Reviewers focus on: correctness, security, test coverage, naming, public API surface.
- Authors are responsible for their PR landing — chase reviews, rebase as needed.

## 6. Quality gates

| Gate | Tool | Blocks merge? |
|------|------|---------------|
| Format    | ruff format, prettier         | ✓ |
| Lint      | ruff, eslint                  | ✓ |
| Types     | mypy, tsc                     | ✓ |
| Unit      | pytest, vitest                | ✓ |
| Integration | pytest with real Postgres+Redis | ✓ |
| E2E smoke | Playwright (auth, enroll, lesson) | ✓ |
| Coverage  | ≥ 80% backend `app/`          | ✓ |
| Container scan | Trivy on built images    | warns |
| Secrets   | gitleaks pre-commit + CI      | ✓ |

## 7. Release process

1. CI on `main` builds and pushes `:main` images.
2. Maintainer tags `vX.Y.Z` (semver) when ready.
3. Tag workflow promotes images to `:vX.Y.Z` + `:latest`, generates SBOM, and creates a GitHub Release with the CHANGELOG slice.
4. Staging auto-deploys on `:main`; production deploys on `:vX.Y.Z` via the deployment guide.
5. Hotfixes branch from the tag, bump patch version, follow the same flow.

### Versioning

- Semantic versioning. Public API surface = OpenAPI schema + WebSocket protocol + CLI.
- Breaking schema changes require migration plan + deprecation notice for ≥ one minor.

## 8. Migration & data discipline

- Alembic for schema changes; one revision per logical change.
- Migrations must be reversible unless impossible (then documented).
- Backfills run as Celery tasks, not in migrations, when they touch user data.
- Never edit a merged migration; always create a new one.

## 9. Issue & PR templates

Under `.github/`:
- `ISSUE_TEMPLATE/bug_report.yml`
- `ISSUE_TEMPLATE/feature_request.yml`
- `PULL_REQUEST_TEMPLATE.md`

## 10. ADRs

Every non-trivial architectural decision lives under [`docs/adr/`](adr/). Format: MADR-style with status, context, decision, consequences. Create one by copying the template and bumping the number.

## 11. On-call & incidents

- Runbooks live under `docs/runbooks/`.
- Severities (SEV1–SEV4) defined in `docs/runbooks/incident-response.md`.
- Postmortems are blameless; one per SEV1/SEV2; tracked in `docs/postmortems/`.

## 12. Dependency management

- Renovate keeps dependencies fresh; major updates require ADR if API surface affected.
- Lockfiles committed (`uv.lock`, `pnpm-lock.yaml`).
- SBOMs generated per release tag (CycloneDX).
