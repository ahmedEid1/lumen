# Lumen — Frontend

Next.js 15 + React 19 + Tailwind 4. App Router with RSC for the public catalog and client components for authenticated flows.

## Run

The standard path is `make up` from the repository root. To run only this app:

```bash
docker compose up --build web
```

Local (without Docker):

```bash
pnpm install
pnpm dev          # http://localhost:3000
```

## Scripts

- `pnpm dev` — local dev server
- `pnpm build` — production build (Next standalone output)
- `pnpm start` — serve the production build
- `pnpm lint` — ESLint
- `pnpm typecheck` — `tsc --noEmit`
- `pnpm test` — Vitest unit tests
- `pnpm test:e2e` — Playwright end-to-end tests
- `pnpm openapi:generate` — regenerate the API client types

## Layout

```
src/
├── app/                Next.js routes
├── components/         UI primitives, shared, feature components
├── lib/                api, query, auth, env, utils
├── styles/             global Tailwind layer
└── tests/              vitest unit tests
tests/e2e/              Playwright specs
```
