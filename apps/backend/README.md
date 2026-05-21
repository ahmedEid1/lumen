# Lumen — Backend

FastAPI service that powers Lumen.

## Run

The standard path is `make up` from the repository root. To run only this service:

```bash
docker compose up --build api
```

Local (without Docker):

```bash
uv sync --group dev
uv run uvicorn app.main:app --reload
```

## Layout

See [`docs/architecture.md`](../../docs/architecture.md#4-module-layout--backend) for the canonical module layout.

## CLI

```bash
python -m app.cli --help
python -m app.cli seed                # load demo data
python -m app.cli bootstrap-admin     # create initial admin
python -m app.cli reindex             # reindex search
```

## Tests

```bash
pytest                 # unit + integration
pytest -m 'not slow'   # skip slow
pytest --cov           # coverage (fails under 80%)
```
