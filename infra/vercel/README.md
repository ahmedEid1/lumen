# Vercel — Lumen frontend deploy

This directory holds the **operator's source-of-truth Vercel config** for the
Next.js frontend (`apps/frontend/`). The actual deploy is driven by Vercel's
GitHub integration, not by `flyctl` or GitHub Actions — push to `Rewrite` and
Vercel rebuilds.

Steady-state cost target on Vercel's Hobby tier: **$0/mo** (free for personal
projects, soft 100 GB/mo bandwidth ceiling — see the cost-watch table in
`docs/deployment/free-tier.md`).

## One-time setup

1. **Import the repo on Vercel.**
   - Vercel dashboard → *Add New* → *Project* → pick this repo.
   - When prompted for the **Root Directory**, leave it at the repo root.
     `vercel.json` here tells Vercel to filter into `apps/frontend/` via
     the pnpm workspace filter in `buildCommand`.
   - Alternative (simpler if you don't care about monorepo niceties):
     set the Root Directory to `apps/frontend`, remove `vercel.json` from
     this directory's path scope, and Vercel runs `pnpm build` from that
     subdir with no filter gymnastics. Pick whichever you'll remember
     six months from now.
   - Framework Preset should auto-detect as **Next.js** (Vercel reads
     `apps/frontend/package.json`).

2. **Set environment variables.** In the Vercel project's *Settings →
   Environment Variables* tab, add the four variables below. The pointer-style
   names (`@lumen_api_base_url`) in `vercel.json` resolve against these:

   | Variable                   | Production value                              | Preview / Dev                                                |
   |----------------------------|-----------------------------------------------|--------------------------------------------------------------|
   | `NEXT_PUBLIC_API_BASE_URL` | `https://lumen-api.fly.dev`                   | same (or your `lumen-api-staging.fly.dev` if you split envs) |
   | `NEXT_PUBLIC_WS_BASE_URL`  | `wss://lumen-api.fly.dev`                     | same                                                          |
   | `API_INTERNAL_BASE_URL`    | `https://lumen-api.fly.dev`                   | same                                                          |
   | `NEXT_TELEMETRY_DISABLED`  | `1`                                           | `1`                                                           |

   Production scope: *Production* only. Preview/Dev scope: same values for now
   (no separate staging api yet).

3. **Wire the custom domain (optional).** If you don't want `lumen.vercel.app`,
   add a custom domain under *Settings → Domains* — Vercel handles the cert.

4. **Disable analytics + speed insights** if you want to keep the bandwidth
   ledger as clean as possible (both ship a small client-side script). Hobby
   tier includes them for free but each script call counts as a request.

## Wiring the api ↔ frontend CORS contract

Fly's `fly.api.toml` ships with:

```toml
CORS_ORIGINS = '["https://lumen.vercel.app"]'
```

If you change the Vercel hostname (custom domain or alternate preview domain
that needs api access), update the Fly secret:

```bash
flyctl secrets set --app lumen-api \
  CORS_ORIGINS='["https://lumen.example.com","https://lumen.vercel.app"]'
```

The H6 production guard refuses to boot with `localhost` or `.test` entries —
the value must be real public origins.

## Preview deploys

Vercel auto-builds previews on every PR. Previews land on
`lumen-<branch>-<hash>.vercel.app`. The CORS list above does **not** allow
random preview hostnames; if you need a preview to talk to the live api, either:

- Add the preview hostname to the api's `CORS_ORIGINS` (manual, friction-y), OR
- Spin up a separate `lumen-api-staging` Fly app with relaxed CORS for branch
  previews (recommended once the project sees real traffic). The deploy
  workflow already takes a `--config` flag so adding a staging variant is one
  file change.

## What lives in `vercel.json`

- `buildCommand` / `installCommand` — pnpm monorepo filters so Vercel only
  installs and builds the frontend workspace.
- `outputDirectory` — Next 15 standalone output lives here.
- `ignoreCommand` — skip rebuilds when only backend / unrelated files change
  (saves your free-tier build minutes).
- `headers` — security defaults that match the self-hosted Caddyfile.
- `github.silent` — suppress the per-push PR comments; the dashboard still
  shows deploy status and the `deploy.yml` workflow links to it.

## What does **not** live here

- Secrets. Never. Use the Vercel dashboard or `vercel env add`.
- Build-time API keys. The frontend never holds the LLM / Anthropic key — all
  LLM calls go through the Fly api.
- Anything Fly-specific. The fly.* configs live next door in `infra/fly/`.

## Triage cheatsheet

| Symptom                                                      | Likely cause                                                                            |
|--------------------------------------------------------------|------------------------------------------------------------------------------------------|
| Build fails with "Cannot find module 'next/...'"             | Vercel didn't read `vercel.json`'s `installCommand`. Re-trigger a clean deploy.          |
| Build succeeds, runtime 500s with CORS error in browser      | Vercel hostname not in Fly api's `CORS_ORIGINS`. See "Wiring the api ↔ frontend" above.  |
| `API_INTERNAL_BASE_URL` env missing in RSC fetch             | Variable scope set to Preview only; set it to Production *and* Preview.                  |
| 404 on `/api/health`                                         | The frontend `/api/health` route is the Next.js healthcheck — confirm it isn't shadowed. |
| Bandwidth alert from Vercel                                  | See `docs/deployment/free-tier.md` cost-watch section.                                   |

See `docs/deployment/free-tier.md` for the full first-deploy runbook.
