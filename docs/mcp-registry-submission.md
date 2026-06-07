# Submitting Lumen to the public MCP registry

> **Superseded 2026-06-07:** publishing now runs through GitHub Actions OIDC —
> `gh workflow run mcp-publish.yml` (see [`.github/workflows/mcp-publish.yml`](../.github/workflows/mcp-publish.yml)).
> No device flow, no local CLI. Bump `version` in `registry_metadata.json`, push, dispatch the workflow;
> it schema-validates, publishes, and verifies the registry serves the new version. The 2.0.0 record went
> live this way. The procedure below is retained for reference (note: `mcp-publisher` ≥1.7 expects a
> `server.json` path argument or cwd file — the §4 syntax predates that).

**Audience:** the operator (Ahmed) running the registry publication once. **Status:** superseded by the OIDC workflow (above). **Schema version:** `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`. **Registry endpoint:** `https://registry.modelcontextprotocol.io`.

The metadata document lives at [`apps/backend/app/mcp/registry_metadata.json`](../apps/backend/app/mcp/registry_metadata.json). It is schema-valid as of commit time (verified locally with `ajv` against the live schema). This guide is the one-shot runbook: install the publisher, authenticate, push, verify, swap the README badge.

---

## 1. Prerequisites

| Requirement | Why | How to verify |
|---|---|---|
| GitHub account `ahmedEid1` | The metadata's `name` is `io.github.ahmedeid1/lumen`. Only that GitHub login can publish under the `io.github.ahmedeid1/*` namespace. | `gh auth status` |
| `apps/backend/app/mcp/registry_metadata.json` exists and is schema-valid | The publisher uploads this file verbatim. | `cat apps/backend/app/mcp/registry_metadata.json \| jq .` |
| Outbound HTTPS to `registry.modelcontextprotocol.io`, `github.com`, and the GitHub device-flow URL | Auth + publish are both HTTPS. | `curl -sI https://registry.modelcontextprotocol.io/health` |

You do **not** need to publish anything to PyPI, npm, or a container registry before submitting — the current metadata uses `websiteUrl` to point users at [`docs/mcp.md`](mcp.md) for the bring-your-own-instance install. If we later cut a `lumen-backend` PyPI release or push a public `ghcr.io/ahmedeid1/lumen-api` image, add a `packages` array in a follow-up version bump.

---

## 2. Install the `mcp-publisher` CLI

The official CLI is **`mcp-publisher`** (not `mcp-registry`, not `mcp` — those are common misspellings). Pick one install path:

**macOS / Linux (curl):**

```bash
curl -L "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_$(uname -s | tr '[:upper:]' '[:lower:]')_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').tar.gz" \
  | tar xz mcp-publisher \
  && sudo mv mcp-publisher /usr/local/bin/
```

**Homebrew:**

```bash
brew install mcp-publisher
```

**Windows (PowerShell):**

```powershell
$arch = if ([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -eq "Arm64") { "arm64" } else { "amd64" }
Invoke-WebRequest -Uri "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_windows_$arch.tar.gz" -OutFile "mcp-publisher.tar.gz"
tar xf mcp-publisher.tar.gz mcp-publisher.exe
Remove-Item mcp-publisher.tar.gz
```

Verify:

```bash
mcp-publisher --help
mcp-publisher --version
```

---

## 3. Authenticate against the registry

The metadata uses the `io.github.ahmedeid1/*` namespace, so authenticate via **GitHub OAuth**:

```bash
mcp-publisher login github
```

The CLI prints a device-flow URL (`https://github.com/login/device`) and a one-time code. Visit the URL in a browser logged in as `ahmedEid1`, paste the code, click *Authorize*. The CLI then prints:

```
Successfully authenticated!
```

The token is cached in the standard publisher config dir (`~/.config/mcp-publisher/` on Linux/macOS, `%APPDATA%\mcp-publisher\` on Windows). Re-run `mcp-publisher login github` to refresh.

> If you ever want to publish under a custom domain (`io.lumen/*` or similar) you would use `mcp-publisher login dns --domain lumen.io --private-key ...` or the equivalent `login http` flow. For the v1.1.0 submission, GitHub OAuth is enough.

---

## 4. Publish (the one command that submits)

From the repo root, with the metadata file path as the argument:

```bash
mcp-publisher publish apps/backend/app/mcp/registry_metadata.json
```

The CLI:

1. Validates the file against the live registry schema (same check we ran locally with `ajv`).
2. Checks the namespace claim — confirms the authenticated GitHub login (`ahmedeid1`) owns `io.github.ahmedeid1/*`.
3. POSTs the document to `registry.modelcontextprotocol.io/v0.1/servers`.
4. Prints a success line with the server URL.

**Expected output (happy path):**

```
✓ Schema validation passed
✓ Namespace io.github.ahmedeid1/lumen authorized for ahmedeid1
✓ Published io.github.ahmedeid1/lumen@1.1.0
  https://registry.modelcontextprotocol.io/v0.1/servers/io.github.ahmedeid1/lumen
```

---

## 5. Verify the listing went live

```bash
curl -sS "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.ahmedeid1/lumen" | jq .
```

You should see a single hit with `"name": "io.github.ahmedeid1/lumen"`, `"version": "1.1.0"`, and the `_meta.io.modelcontextprotocol.registry/publisher-provided` block intact.

Direct GET (no search):

```bash
curl -sS "https://registry.modelcontextprotocol.io/v0.1/servers/io.github.ahmedeid1/lumen" | jq .
```

A `200 OK` with the metadata echoed back confirms the listing is live. The directory UI at `https://registry.modelcontextprotocol.io/` will pick up the entry on its next index cycle (usually <5 min).

---

## 6. Update the README badge

The README badge (top of [`README.md`](../README.md)) currently reads:

```markdown
[![MCP registry](https://img.shields.io/badge/MCP%20registry-pending%20I1-lightgrey)](#use-lumen-from-claude-desktop)
```

Replace with:

```markdown
[![MCP registry](https://img.shields.io/badge/MCP%20registry-io.github.ahmedeid1%2Flumen-blue)](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.ahmedeid1/lumen)
```

This is the only README edit the registry submission requires; the install snippet and operator docs already reference the correct invocation (`claude mcp add lumen -- python -m app.mcp --transport stdio`).

The same `docs/mcp.md` Publishing section at line 170 should be reviewed when the next version is cut, but no edit is required for the v1.1.0 submission.

---

## 7. Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `error: namespace io.github.ahmedeid1 not authorized` | Logged into GitHub as a different account, or the OAuth token expired. | `mcp-publisher login github` and complete the device flow as `ahmedEid1`. |
| `error: schema validation failed` with a property name | Schema drift since this packet was prepared. The 2025-12-11 schema may have been superseded. | Pull the latest schema from `https://static.modelcontextprotocol.io/schemas/<date>/server.schema.json`, diff against the `$schema` URL in `registry_metadata.json`, update fields, rerun. |
| `error: name already exists at version 1.1.0` | A prior submission attempt landed and you're re-publishing the same version. The registry is append-only per version. | Bump `version` in the metadata file to `1.1.1` (or `1.2.0` if there are real changes), commit, re-run `mcp-publisher publish`. |
| `error: invalid_client` from GitHub device flow | The OAuth app rotated client credentials and the local CLI is stale. | Update the CLI: `brew upgrade mcp-publisher` or re-run the curl install. |
| Listing appears in the API but not the directory UI | The directory indexer runs on a short cron. | Wait 5–10 minutes, then refresh `https://registry.modelcontextprotocol.io/`. |
| `claude mcp add lumen` from the registry installs but fails on first call with `mcp.token_required` | The registry install snippet does not (and cannot) embed the operator's `LUMEN_MCP_AUTH_TOKEN`. | Documented behavior — operator must mint a token with `make mcp-token` and set the env var before invoking the registry install. The README + `docs/mcp.md` both call this out. |

---

## 8. After publishing — version bump cadence

The metadata file is the source of truth. To publish a new version:

1. Bump `version` in `apps/backend/app/mcp/registry_metadata.json`. Semver only — no `+` local segment (the registry will reject `1.1.0+agentic`).
2. Bump the matching entry in `CHANGELOG.md` if the change is user-visible.
3. Run `mcp-publisher publish apps/backend/app/mcp/registry_metadata.json` again. The CLI is idempotent per (name, version) pair, append-only across versions.

The registry retains every published version, so an old client pinned to `1.1.0` keeps working when `1.2.0` ships.

---

## 9. Quick reference

```bash
# Install (one-time)
brew install mcp-publisher

# Authenticate (re-run when token expires)
mcp-publisher login github

# Submit (every version bump)
mcp-publisher publish apps/backend/app/mcp/registry_metadata.json

# Verify
curl -sS "https://registry.modelcontextprotocol.io/v0.1/servers/io.github.ahmedeid1/lumen" | jq .
```
