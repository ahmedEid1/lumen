### Activation (A6)

Pre-wrote the GitHub PR body for the `Rewrite → master` release at
`docs/release/1.1.0-agentic-pr-body.md` (lifts the
`[1.1.0-agentic]` CHANGELOG section verbatim, adds an architecture
diff vs `1.0.0-rebuild`, lists the verification gates, and embeds
the operator's seven-item definition-of-done checklist). Added a
`make publish-rewrite` Makefile target that previews the pending
commits, prompts `[y/N]`, then runs `git push origin Rewrite` + `gh
pr create --base master --head Rewrite --body-file …`. No push or
PR was opened from this task — materials only.

### Operator runbook (publish)

```bash
make publish-rewrite
```
