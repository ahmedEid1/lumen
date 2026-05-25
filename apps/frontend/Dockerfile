# syntax=docker/dockerfile:1.7-labs
# ---------------- base ----------------
FROM node:22-alpine AS base
ENV PNPM_HOME=/root/.local/share/pnpm \
    PATH=/root/.local/share/pnpm:$PATH \
    CI=true
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate
WORKDIR /app

# ---------------- deps ----------------
FROM base AS deps
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install

# ---------------- dev ----------------
FROM deps AS dev
COPY . .
EXPOSE 3000
CMD ["pnpm", "dev"]

# ---------------- build ----------------
FROM deps AS build
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# ---------------- prod ----------------
FROM node:22-alpine AS prod
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    # Next.js standalone server.js reads HOSTNAME and binds to it. Defaults
    # to "localhost" (127.0.0.1 only) when unset, which means:
    #   - Caddy → web:3000 still works (docker DNS resolves to the
    #     container's IP and server.js happens to bind to that too via
    #     the IPv6 fallback) — so the public site is fine.
    #   - The in-container healthcheck (`wget http://localhost:3000`) hits
    #     127.0.0.1 where nothing is listening → "Connection refused" →
    #     container reported "unhealthy" even though traffic flows.
    # 0.0.0.0 binds to all interfaces, fixing both.
    HOSTNAME=0.0.0.0
RUN addgroup -S app && adduser -S app -G app
WORKDIR /app
COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER app
EXPOSE 3000
# Use plain `node` for the healthcheck so we don't depend on wget/curl
# being present in the alpine base. Returns exit 0 only on HTTP 200.
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD node -e "fetch('http://localhost:3000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
