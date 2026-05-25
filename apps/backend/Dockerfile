# syntax=docker/dockerfile:1.7-labs
# ---------------- base ----------------
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:/root/.local/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq5 curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

# install uv
ADD https://astral.sh/uv/install.sh /uv-install.sh
RUN sh /uv-install.sh && rm /uv-install.sh && mv /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app

# ---------------- deps ----------------
FROM base AS deps
# ``pyproject.toml`` (and ``uv.lock`` when it exists) are copied
# *before* the source so Docker's layer cache is keyed on
# dependency declarations only — a code-only change reuses this
# (slow, network-bound) layer, but ANY change to ``pyproject.toml``
# or ``uv.lock`` invalidates it and re-runs the install below.
# This is what makes ``docker compose up --build`` (or
# ``docker compose build api worker beat``) pick up newly added
# backend dependencies automatically — bare ``docker compose up``
# will keep using the previous image until you ask it to rebuild.
COPY pyproject.toml uv.lock* ./
# Stub package layout so ``uv pip install -e '.'`` succeeds on the
# deps-only stage when there's no uv.lock to lean on. The real
# ``app/`` is copied over in the dev / build stages below. Without
# this stub, ``uv pip install -e '.'`` fails with "package
# directory 'app' does not exist" because nothing has copied the
# source yet at this point in the build.
RUN mkdir -p app && touch app/__init__.py
# Two-pass install with a deliberate fallback:
#   1. ``uv sync --frozen`` is the fast path when ``uv.lock`` is
#      already in sync with ``pyproject.toml`` — it installs the
#      pinned graph in seconds.
#   2. If a developer added a dep to ``pyproject.toml`` without
#      re-running ``uv lock``, ``--frozen`` refuses to update the
#      lock and exits non-zero; we then fall back to
#      ``uv pip install -e '.'`` which resolves straight from
#      ``pyproject.toml`` and lays the new dep down.
# We DON'T silence stderr on the sync attempt (the previous
# ``2>/dev/null`` made it impossible to see *why* the fast path
# failed); the fallback's own output is enough to confirm what
# happened.
RUN uv venv /opt/venv \
 && (uv sync --frozen --no-install-project --no-dev || uv pip install -e '.')

# ---------------- dev ----------------
FROM deps AS dev
RUN uv sync --frozen --group dev \
 || uv pip install -e '.[dev]' \
      pytest pytest-asyncio pytest-cov pytest-httpx anyio ruff mypy types-redis types-passlib \
      factory-boy freezegun respx faker
# Real source goes on top of the stub — overrides app/__init__.py.
COPY . .
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app"]

# ---------------- build ----------------
FROM deps AS build
COPY . .

# ---------------- prod ----------------
FROM python:3.13-slim AS prod
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 tini curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1001 lumen

COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app

# /app comes over with root ownership from the build stage's COPY. The
# non-root `lumen` runtime user needs to write into /app/evals/reports
# (the eval harness streams per-item JSONL — without this, `make eval`
# fails with PermissionError on the first item write), and under /app
# generally for tmpfiles. chown the whole tree so the prod runtime never
# hits EACCES on first write.
RUN chown -R lumen:lumen /app

WORKDIR /app
USER lumen
EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health/live', timeout=2).status==200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
