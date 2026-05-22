# Lumen MCP server — operator guide

**Phase I, item I1.** Lumen exposes its surface as MCP (Model Context Protocol) tools so any MCP-aware client — Claude Desktop, Claude Code, Cursor, the Anthropic Workbench — can plan, teach, and create courses on a real product.

This is the single most credible "I work with agents at the protocol level" artifact in the Lumen v2 chapter: a self-built MCP server for a self-hosted product, OAuth client-credentials authentication, published to the public registry.

## What ships

Nine tools, in `apps/backend/app/mcp/tools.py`:

| Tool | Auth | Description |
|---|---|---|
| `list_courses(filter?, limit?)` | public | Catalog query |
| `get_course(slug)` | public | Course + syllabus tree |
| `search_lesson_content(course_slug, query, top_k?)` | user | Semantic search over a course's lesson chunks |
| `ask_tutor(course_slug, question)` | user (enrolled) | Course-scoped RAG tutor with cited answer |
| `list_my_due_reviews(limit?)` | user | FSRS-6 spaced-repetition queue |
| `grade_review_card(card_id, rating)` | user | Submit one rating (1=again, 2=hard, 3=good, 4=easy) |
| `list_my_progress()` | user | Per-course completion + mastery rollup |
| `create_course_draft(brief, subject_slug?)` | instructor | AI-authored outline + draft course |
| `ingest_url_to_draft(url, course_id?)` | instructor | Multi-modal ingest (YouTube / Notion / Google Docs) |

Two transports:

- **stdio** — Claude Desktop's default. Authentication is a static Bearer token in `LUMEN_MCP_AUTH_TOKEN`.
- **streamable-http** — Claude Code's preferred hosted-server shape. Authentication is OAuth 2.0 client-credentials (RFC 6749 §4.4), tokens minted at `POST /oauth/token`, metadata at `GET /.well-known/oauth-authorization-server` (RFC 8414).

## Quick start — Claude Desktop

1. Bring up the Lumen stack: `make up && make migrate && make seed`.
2. Mint an MCP client token:
   ```bash
   make mcp-token OWNER=teacher@lumen.test
   # client_id=...
   # client_secret=...   <-- copy this; you can't see it again
   ```
3. Paste the `client_secret` into Claude Desktop's config file:

   - **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

   ```json
   {
     "mcpServers": {
       "lumen": {
         "command": "uvx",
         "args": ["--from", "lumen-backend", "python", "-m", "app.mcp", "--transport", "stdio"],
         "env": {
           "LUMEN_MCP_AUTH_TOKEN": "<paste-client-secret-here>",
           "DATABASE_URL": "postgresql+asyncpg://lumen:lumen@localhost:5432/lumen"
         }
       }
     }
   }
   ```

4. Restart Claude Desktop. The Lumen tools should appear in the sidebar.

## Quick start — Claude Code

```bash
export LUMEN_MCP_AUTH_TOKEN="<your-client-secret>"
export DATABASE_URL="postgresql+asyncpg://lumen:lumen@localhost:5432/lumen"
claude mcp add lumen -- python -m app.mcp --transport stdio
```

Verify with `claude mcp list` — you should see `lumen` registered with nine tools.

## Hosted install (streamable-http transport)

For an MCP server reachable from any Claude Desktop / Claude Code install — not just one local to the Lumen instance — run the HTTP transport:

```bash
python -m app.mcp --transport http --port 8001
```

Then point a remote client at `https://<your-lumen-host>/mcp` with an OAuth 2.0 client-credentials flow:

1. Client POSTs to `/oauth/token`:
   ```
   client_id=<row-id>&client_secret=<plaintext>&grant_type=client_credentials&scope=*
   ```
2. Server replies with a 15-minute Bearer JWT.
3. Client sends MCP JSON-RPC frames to `/mcp` with `Authorization: Bearer <jwt>`.

The discovery document at `/.well-known/oauth-authorization-server` advertises the token endpoint and supported grants per RFC 8414, so any RFC 8414-aware OAuth client can auto-configure.

## Token lifecycle

Mint:

```bash
# Compose
make mcp-token OWNER=teacher@lumen.test NAME="My laptop" SCOPES="*"

# Or directly in the api container
docker compose exec api python -m app.cli mcp-token \
  --owner-email teacher@lumen.test \
  --name "My laptop" \
  --scopes "*"
```

Output (saved to stdout for easy piping):

```
client_id=abc123XYZ...
client_secret=def456XYZ...
owner_user_id=u_abc123...
name=My laptop
scopes=*

Save the client_secret now — it will not be shown again.
```

List active clients (admin-only):

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8000/api/v1/admin/mcp-clients
```

Revoke:

```bash
curl -X DELETE -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8000/api/v1/admin/mcp-clients/<client_id>
```

The OAuth handler treats any row with a non-null `revoked_at` as inactive — existing JWTs minted from a now-revoked client are still cryptographically valid until they expire (15 min max), but the principal resolver rejects them on the lookup.

## Scopes

MCP scopes mirror tool names. The full vocabulary:

- `list_courses`
- `get_course`
- `search_lesson_content`
- `ask_tutor`
- `list_my_due_reviews`
- `grade_review_card`
- `create_course_draft`
- `ingest_url_to_draft`
- `list_my_progress`
- `*` — wildcard (every tool)

A client registered with `scopes=["ask_tutor", "list_my_progress"]` can only invoke those two tools; every other tool returns 403 at the dispatcher's scope gate.

The token endpoint can *narrow* scopes (the client requests a subset of what the registration allows) but never broaden them.

## Auth posture

Per-tool auth gates:

- **public** — `list_courses`, `get_course`. Any authenticated principal can call. We still require a recognised principal so the cost meter + audit surface can attribute traffic.
- **user** — `search_lesson_content`, `ask_tutor`, `list_my_due_reviews`, `grade_review_card`, `list_my_progress`. Any authenticated principal. `ask_tutor` additionally requires the principal to be enrolled in the course (or be the owner / an admin).
- **instructor** — `create_course_draft`, `ingest_url_to_draft`. Principal must have `role=instructor` or `role=admin`.

The role check happens *after* the scope check, so a token without the right scope gets a clean `mcp.scope.denied` before the role gate fires.

## Environment variables

| Var | Purpose | Default |
|---|---|---|
| `LUMEN_MCP_AUTH_TOKEN` | stdio transport: the client_secret returned by `make mcp-token`. | required for stdio |
| `DATABASE_URL` | Postgres connection string. Same shape as the rest of Lumen. | inherited from `.env` |
| `JWT_SECRET` | Used to sign the OAuth-minted JWTs. The MCP transport uses the same key the main API uses, with a distinct `iss="lumen-mcp"` so tokens never cross-leak. | inherited from `.env` |

The MCP server respects the H1 cost meter (`LLM_USER_BUDGET_24H_USD`) and the H7 audit hooks — `ask_tutor`, `create_course_draft`, and `ingest_url_to_draft` all bill against the principal's user, and `search_lesson_content` writes a `retrieval_audits` row per call.

## Publishing to the public registry

The metadata document at `apps/backend/app/mcp/registry_metadata.json` is the input for [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io). To publish:

1. Bump `version` in the metadata file.
2. POST the file to the registry per their submission guide (one-time auth required).
3. Once approved, any Claude Code user can install Lumen with `claude mcp add lumen` — the registry resolves the install snippet from the metadata's `install.claude_code` field.

## Troubleshooting

- **`mcp.invalid_token` on every call** — the JWT signature didn't validate. Usually means the `JWT_SECRET` rotated between mint and use; mint a fresh token.
- **`mcp.client_revoked`** — the row has a non-null `revoked_at`. Mint a new client.
- **`mcp.scope.denied`** — the registered scopes don't include the called tool. Revoke + re-mint with broader scopes, or use a different client.
- **`mcp.tutor.not_enrolled`** — the principal's user isn't enrolled in the course. Enrol via the Lumen UI (or directly: `POST /api/v1/me/enrollments`) and retry.
- **`mcp.token_required` on stdio** — `LUMEN_MCP_AUTH_TOKEN` wasn't passed in the env block. Check the Claude Desktop config.

## Testing locally

The MCP test suite is in `apps/backend/tests/`:

- `test_mcp_tools.py` — happy-path coverage for every tool with `LLM_PROVIDER=noop`.
- `test_mcp_auth.py` — OAuth client-credentials flow: happy, revoked, bad-secret, scope-narrowing.
- `test_mcp_server_smoke.py` — spawns the stdio server in a subprocess and asserts `tools/list` returns the nine expected tools.

Run them with `make test.api` or `pytest apps/backend/tests/test_mcp*`.

## Design notes

- **One Principal per call.** The transport (stdio or HTTP) resolves authentication into a `Principal` dataclass, sets it on a contextvar, and the dispatcher reads it from there. Tools never see raw tokens or JWTs.
- **Reuse of services, not reimplementation.** Every tool is a thin adapter over an existing Lumen service (`services.tutor`, `services.fsrs`, `services.ai_authoring`, etc.). The MCP layer adds no business logic.
- **Cost-metered LLM paths.** `ask_tutor`, `create_course_draft`, and `ingest_url_to_draft` all route through `llm_call_log.call_logged`, so they count against the per-user 24h budget guard and appear in `/admin/observability`.
- **Audit on retrieval.** `search_lesson_content` calls `find_relevant_chunks(audit=True)` so every MCP-initiated retrieval lands in `retrieval_audits` with `feature="mcp.search_lesson_content"`. The admin can correlate "weird tutor answers" with what was actually fetched.
- **Secrets are argon2-hashed.** The `mcp_clients` row stores only `client_secret_hash` — same scheme as `users.password_hash`. The plaintext secret is shown once at mint time and never persisted.
