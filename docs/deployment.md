# Deployment guide

This guide covers a single-node production deployment using Docker Compose. The same artifacts (images, env contract) work behind Kubernetes, but the v1 reference target is a managed VM.

## Reference host

- 4 vCPU / 8 GB RAM / 80 GB SSD
- Ubuntu 24.04 LTS
- Docker Engine 27 + Compose v2
- A DNS A/AAAA record pointing at the host
- Open inbound 80/443

## Provisioning

```bash
sudo apt-get update && sudo apt-get install -y curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

## Layout on host

```
/opt/lumen/
├── .env                       # production secrets (chmod 600, owner root)
├── docker-compose.prod.yml
├── infra/
│   ├── caddy/Caddyfile
│   └── postgres/
└── backups/
```

## Environment

Copy `.env.example` to `.env`, then set:

```env
ENV=production
APP_DOMAIN=lumen.example.com
JWT_SECRET=<32+ random bytes, base64>
POSTGRES_PASSWORD=<long random>
MINIO_ROOT_USER=<value>
MINIO_ROOT_PASSWORD=<long random>
S3_BUCKET=lumen-assets
SMTP_HOST=...
SMTP_USERNAME=...
SMTP_PASSWORD=...
SENTRY_DSN=
```

Validate with `make config.check` (calls `docker compose -f docker-compose.prod.yml config -q`).

## First boot

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d db redis s3 search
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose.prod.yml run --rm api python -m app.cli bootstrap-admin
docker compose -f docker-compose.prod.yml up -d
```

Caddy obtains a Let's Encrypt certificate on first request to `APP_DOMAIN`.

## Health checks

| Endpoint | Used by |
|----------|---------|
| `/api/v1/health/live`   | container `HEALTHCHECK`, k8s liveness |
| `/api/v1/health/ready`  | reverse proxy readiness; touches db + redis |
| `/api/health` (FE)      | container `HEALTHCHECK` |

## Backups

Logical Postgres dumps run nightly via the `backup` profile:

```bash
docker compose --profile backup -f docker-compose.prod.yml run --rm backup
```

Stored under `/opt/lumen/backups/`. Rotate to off-host storage (BorgBase, S3, etc.) — example cron under `infra/cron/`.

To restore:

```bash
docker compose -f docker-compose.prod.yml stop api worker beat
gunzip -c backups/lumen-2026-05-20.sql.gz | docker compose exec -T db psql -U lumen -d lumen
docker compose start api worker beat
```

## Upgrades

```bash
cd /opt/lumen
git pull
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose.prod.yml up -d
```

Rolling restarts work for `api`, `web`, and `worker`. `beat` is a singleton — stop it first if migrations alter relevant tables.

## Rollback

```bash
docker compose -f docker-compose.prod.yml stop api worker beat web
git checkout v<previous>
docker compose -f docker-compose.prod.yml pull
# downgrade only if forward migration is irreversible — usually skipped
docker compose -f docker-compose.prod.yml up -d
```

## Observability

- Prometheus is included under the `metrics` profile; default scrape every 15 s.
- Logs flow to Docker's `local` driver; ship to your log aggregator with the `logspout` sidecar (example in `infra/compose/logspout.yml`).
- Set `SENTRY_DSN` in `.env` to enable error tracking.

## Hardening checklist

- [ ] UFW: only 22/80/443 inbound.
- [ ] SSH key-only login; `PermitRootLogin no`.
- [ ] Fail2ban for SSH and `caddy-access`.
- [ ] Docker daemon `userns-remap` enabled.
- [ ] Automatic security updates (`unattended-upgrades`).
- [ ] Off-host encrypted backup tested with a quarterly restore drill.
- [ ] Monitoring alerts wired (uptime + Sentry + Prometheus).
