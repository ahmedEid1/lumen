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
COPY pyproject.toml uv.lock* ./
RUN uv venv /opt/venv \
 && uv sync --frozen --no-install-project --no-dev 2>/dev/null || uv pip install -e '.'

# ---------------- dev ----------------
FROM deps AS dev
RUN uv sync --frozen --group dev 2>/dev/null || uv pip install -e '.[dev]' \
      pytest pytest-asyncio pytest-cov pytest-httpx anyio ruff mypy types-redis types-passlib \
      factory-boy freezegun respx faker
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

WORKDIR /app
USER lumen
EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health/live', timeout=2).status==200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
