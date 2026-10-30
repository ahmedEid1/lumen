# Redeploying Lumen

**Status:** the hosted demo at `lumen.ahmedhobeishy.tech` ran from 2026-05-25 to 2026-10-30 on one AWS EC2 t4g.small (eu-central-1, Graviton, 2 vCPU, 2 GB RAM, 30 GB gp3), built with [Terraform](../../infra/aws/). It was taken down on 2026-10-30, and the domain no longer serves the app. Recordings of the last live version are in [`docs/demo/2026-10-30/`](../demo/2026-10-30/) (walkthrough video: [`video/lumen-walkthrough.mp4`](../demo/2026-10-30/video/lumen-walkthrough.mp4)). Why and how it was retired: [ADR-0032](../adr/0032-retire-hosted-demo.md).

This guide brings the same stack back on a fresh host, with the last production data.

## What survived the teardown

| Piece | Where |
|---|---|
| App images | `ghcr.io/ahmedeid1/lumen-api` and `lumen-web`, public, tagged by commit SHA, `main` and `latest`. Built for **linux/arm64 only**. |
| Infra code | [`infra/aws/`](../../infra/aws/) (Terraform), [`scripts/aws-bootstrap.sh`](../../scripts/aws-bootstrap.sh), the full runbook [`aws-vps.md`](aws-vps.md) |
| Data | The final `pg_dump -Fc` and the production env file from 2026-10-30, kept by the owner **outside git**. The final dump was restore-tested: 43 courses, 412 lessons, 185 embedded chunks, 21 users, schema at migration 0053. Uploaded files: none (MinIO held no objects). |
| CI/CD | `ci.yml` → `deploy.yml`: an SSH deploy with a post-deploy smoke test. Rollback is manual: `gh workflow run deploy.yml -f image_tag=<sha> -f commit_sha=<sha> -f run_migrations=false`. Deploys are off until the repo variable `DEPLOY_ENABLED` is `true`. |

Not kept:
- The `eval-reports` volume, which held the promoted baseline run that `/eval` showed. Its summary is in [`docs/eval/README.md`](../eval/README.md) and screenshot 17, but the raw report was lost with the server.
- Redis, which held only the queue and cache.
- The Prometheus history.
- Caddy's certificates. Caddy requests new ones on its own.

After a redeploy, `/eval` shows no promoted runs until you run `eval-baseline.yml` and promote a report again.

## 1. Pick a host

- **AWS (the documented path).** Run `terraform apply` in `infra/aws/` (≈90 min the first time, including DNS and TLS). A t4g.small costs about $21 a month on demand in eu-central-1: instance $14.0, public IPv4 $3.7, 30 GB gp3 $2.9. A t4g.medium (4 GB) removes the swap pressure and costs about $35.
- **Any other arm64 Ubuntu 24.04 VPS** with ≥ 2 GB RAM (4 GB preferred) and ≥ 30 GB disk. Run `scripts/aws-bootstrap.sh` non-interactively, as described in [`infra/aws/README.md`](../../infra/aws/README.md). The Terraform stack does two things outside the bootstrap: the user data adds the passwordless-sudo rule for `lumen`, and the security group opens 80/443. On another provider, add `lumen ALL=(ALL) NOPASSWD:ALL` under `/etc/sudoers.d/` before the bootstrap disables root SSH, and open 80/443 in the provider's firewall.
- **amd64 hosts** also need an amd64 leg in the `build-images` job of `ci.yml` and in `release.yml`. All third-party images are already multi-arch.

## 2. Build the box

AWS:

```bash
cd infra/aws
terraform init
terraform apply -var admin_email=<you@example.com>
IP=$(terraform output -raw public_ip)
ssh -i keys/lumen-prod.pem ubuntu@$IP 'cloud-init status --wait'   # the first boot installs Docker
ssh -i keys/lumen-prod.pem lumen@$IP
```

Run steps 3 and 4 as `lumen`. Only `lumen` is in the `docker` group, and CI deploys as `lumen` into `~/lumen` with `~/.env.production`.

The instance ignores later edits to the bootstrap script and new AMIs (`lifecycle.ignore_changes`), so re-applying does not replace the box. To rebuild it on purpose, use `terraform apply -replace=aws_instance.lumen`. That deletes the root volume, so back up first.

## 3. Restore the configuration

1. Copy the saved env file to `/home/lumen/.env.production` (mode 600).
2. Before starting anything, change these values:
   - `BADGES_SIGNING_KEY`: **generate a new Ed25519 key**. The old one was exposed in a log on 2026-10-30. Badges issued earlier stop verifying, which is fine, since the old issuer URL was offline.
   - `OPENAI_API_KEY` (Groq) and `EMBEDDING_OPENAI_API_KEY` (Cloudflare Workers AI): new keys if the old ones were revoked. The embedding model must stay `@cf/baai/bge-small-en-v1.5` (384 dimensions). Otherwise the stored chunks no longer match: run `$C exec -T api python -m app.cli ingest-embeddings --all` after step 4.
   - If the domain changes:
     - `APP_DOMAIN`. CORS, the `NEXT_PUBLIC_*` URLs and the asset URL derive from it in `docker-compose.prod.yml`.
     - `WEB_BASE_URL`, `API_BASE_URL` and `BADGES_ISSUER_URL`, if they are set.
     - The `APP_DOMAIN` secret in step 6.
     - `metadataBase` in `apps/frontend/src/app/layout.tsx` (needs an image rebuild).
     - The host in step 7.
   - Keep `BYOK_MASTER_KEYS`. Without it, the users' saved model keys can't be decrypted.
   - On a 2 GB box, add `REDIS_MAXMEMORY=64mb` and `CELERY_CONCURRENCY=1`. The old env file didn't have them, and the box ran 1.5 GB into swap.

## 4. Restore the data

```bash
set -euo pipefail
git clone https://github.com/ahmedEid1/lumen.git ~/lumen && cd ~/lumen
C="docker compose -f docker-compose.prod.yml --env-file $HOME/.env.production"
$C pull
$C up -d --wait db redis s3   # returns once the healthchecks pass
# copy the dump to the box first, e.g. scp lumen-final-<ts>.dump lumen@<host>:~/
$C exec -T db sh -c 'pg_restore --no-owner --no-privileges --exit-on-error -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < ~/lumen-final-<ts>.dump
$C up -d
$C exec -T api alembic upgrade head
```

The restore goes into the fresh, empty database the `db` container creates, and stops at the first error, so the app never starts on half the data. These flags were tested against the final dump on a clean `pgvector/pgvector:pg17` container. The dump was taken at commit `067eb81` with the schema at head. The chunks and their embeddings are inside it, so no reindex is needed.

## 5. DNS and TLS

1. If `lumen.ahmedhobeishy.tech` is attached to the `lumen-retired` redirect Worker (Cloudflare → Workers & Pages → `lumen-retired` → Settings → Domains & Routes), remove that custom domain. You can then delete the Worker.
2. Add `A lumen → <new IP>`, **DNS only** (grey cloud). Caddy on the box gets the Let's Encrypt certificate itself and needs ports 80 and 443 to reach it.
3. Run `$C restart proxy`. Caddy's certificate attempts fail until DNS points at the box, and then back off; the restart makes it retry at once.

## 6. Turn CI deploys back on

```bash
H=<host-or-ip>   # use the same value for the host and the known_hosts scan
gh secret set AWS_SSH_HOST --body "$H"
gh secret set AWS_SSH_USER --body lumen
gh secret set AWS_SSH_PRIVATE_KEY < infra/aws/keys/lumen-prod.pem
ssh-keyscan -H "$H" | gh secret set AWS_KNOWN_HOSTS
gh secret set APP_DOMAIN --body lumen.ahmedhobeishy.tech
# the production environment, deployable from main only (it was deleted with the demo)
gh api -X PUT repos/ahmedEid1/lumen/environments/production \
  -F 'deployment_branch_policy[protected_branches]=false' \
  -F 'deployment_branch_policy[custom_branch_policies]=true'
gh api -X POST repos/ahmedEid1/lumen/environments/production/deployment-branch-policies -f name=main
gh variable set DEPLOY_ENABLED --body true
```

After that, every green push to `main` deploys. To deploy one image by hand: `gh workflow run deploy.yml -f image_tag=<sha>`. The manual workflows `eval-baseline.yml`, `flip-flag.yml` and `prod-seed.yml` need the same secrets and the variable.

## 7. Smoke test

```bash
curl -fsS https://lumen.ahmedhobeishy.tech/api/v1/health/ready
curl -fsS https://lumen.ahmedhobeishy.tech/api/v1/health/llm
curl -fsS -o /dev/null -w '%{http_code}\n' https://lumen.ahmedhobeishy.tech/demo
```

Then ask the tutor one question in the featured course and check that the answer cites a lesson.

## 8. Undo the retirement notes

Change the README status line back to "Live", and, in the owner's materials, the CV, portfolio, LinkedIn and cover-letter lines that say the demo is retired.
