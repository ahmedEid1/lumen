### Activation (A3)

The Lumen MCP server is now packet-ready for `registry.modelcontextprotocol.io`. The `apps/backend/app/mcp/registry_metadata.json` document was rewritten against the current 2025-12-11 registry schema (the previous file used the 2024 shape and would have been rejected at validation), renamed to the `io.github.ahmedeid1/lumen` namespace required for GitHub-OAuth publishing, aligned to version `1.1.0`, and validated locally with `ajv` against the live schema. A new operator runbook at [`docs/mcp-registry-submission.md`](../mcp-registry-submission.md) walks through `mcp-publisher` install, GitHub OAuth login, the one-line submit, verification, and the README badge swap. No submission was performed — the operator runs `mcp-publisher publish` manually.

### Operator runbook (MCP registry)

```bash
# one-time setup
brew install mcp-publisher                      # or curl from the GitHub release
mcp-publisher login github                      # device flow as ahmedEid1

# submit (re-run on every version bump)
mcp-publisher publish apps/backend/app/mcp/registry_metadata.json
```

Expected output:

```
✓ Schema validation passed
✓ Namespace io.github.ahmedeid1/lumen authorized for ahmedeid1
✓ Published io.github.ahmedeid1/lumen@1.1.0
  https://registry.modelcontextprotocol.io/v0.1/servers/io.github.ahmedeid1/lumen
```

Verify:

```bash
curl -sS "https://registry.modelcontextprotocol.io/v0.1/servers/io.github.ahmedeid1/lumen" | jq .
```

Then swap the README badge per `docs/mcp-registry-submission.md` §6. Full failure-mode table and version-bump cadence live in that runbook.
