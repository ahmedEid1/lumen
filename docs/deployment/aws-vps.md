# AWS EC2 t4g.small — Lumen live demo

This is the operator runbook for putting Lumen on the public internet
using AWS's t4g.small (Graviton2 ARM) free-trial allowance. One ARM VM,
the unmodified `docker-compose.prod.yml`, containerised Caddy for TLS,
Cloudflare DNS proxying as an optional add-on.

| Resource         | Free allowance                                                     | What lives there                                                                                  |
|------------------|--------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| EC2 t4g.small    | 750 hr/mo (24×7 one instance) **through Dec 31, 2026**, 2 vCPU + 2 GB RAM | FastAPI api + Celery worker + beat + Postgres-pgvector + Redis + MinIO + Caddy (one compose file) |
| EBS gp3          | 30 GB (free for first 12 months on new accounts, ~$2.40/mo after)  | Postgres data, Redis AOF, MinIO objects, Caddy `/data` (Let's Encrypt cert + ACME state)          |
| Egress           | 100 GB/mo outbound (free across all tiers)                         | Public HTTPS traffic to the demo                                                                  |
| Elastic IP       | $0 when attached to a running instance, ~$3.65/mo otherwise         | Stable public endpoint for DNS                                                                    |
| TLS              | Let's Encrypt via the Caddy 2 container (auto-renewing)            | Origin TLS on `:443`                                                                              |

**Cost reality:** on a new-account Free Plan (6 months, up to $200 in
credits), this deploy costs ~$0 wall-clock — credits absorb the Elastic
IP and any backup snapshots. On an existing AWS account, plan ~$6/mo
(IPv4 + EBS) until Dec 31 2026, then ~$18/mo (instance hours start
billing). Migration path off AWS at end-of-trial: rerun this runbook
against Oracle Always Free A1 (if capacity ever appears) or Hetzner
CAX11 — the compose stack is identical because both targets are ARM64
Ubuntu 24.04.

> **Loom screencast:** `<TODO operator — drop the 90-second demo URL here once recorded>`

> **Why t4g.small and not t4g.medium?** Medium (4 GB) costs ~$24/mo
> after the free hours run out and is *not* in the free-trial promo —
> only t4g.small is. The 2 GB constraint is real (Lumen wants 24 GB on
> Oracle's design point) but a 4 GB swapfile + tuned Postgres config
> handles bursty demo traffic. For sustained multi-user load, the
> "split deploy" section at the bottom pushes the Next.js frontend to
> Vercel free.

---

## Prereqs

- An AWS account (signup below — free, no card needed for the Free Plan).
- A domain you control (or a subdomain). The runbook uses `lumen.example.com`; substitute yours.
- An SSH key pair on your workstation (`ssh-keygen -t ed25519` if you don't already have one).
- About 90 minutes the first time, ~15 minutes on every subsequent deploy.

---

## Step 1 — Sign up for AWS

1. Go to <https://signup.aws.amazon.com>. Pick the **"Free Plan"** option (6-month, $200-credit, no-card-required path) — *not* the legacy 12-month free tier with card-on-file.
2. Pick a **home region** close to your audience. Unlike Oracle, AWS regions are *not* locked per account — you can spin up resources in any region — but free-trial t4g.small hours are aggregated across regions, so pick one and stick with it. Good defaults: `eu-central-1` (Frankfurt), `us-east-1` (N. Virginia), `ap-southeast-1` (Singapore).
3. Complete the 5 onboarding tasks in the AWS console to unlock the second $100 of credits: launch & terminate an EC2 instance, configure an RDS database, deploy a Lambda function, test a Bedrock prompt, set up a Budgets alert. Total time ~30 min.
4. **Set a $5/month budget alarm** under *Billing → Budgets* — for a Free Plan account this is belt-and-braces (the account auto-blocks at $0 charges anyway, but the email warns you well before the 6-month auto-close).

---

## Step 2 — Create the t4g.small EC2 instance

In the EC2 console (top-right region picker → your chosen region → *EC2 → Instances → Launch instances*):

| Field                  | Value                                                                  |
|------------------------|------------------------------------------------------------------------|
| Name                   | `lumen-prod`                                                           |
| AMI                    | **Canonical Ubuntu 24.04 LTS** (the *arm64* build — the launch wizard auto-picks it when you select a t4g instance type) |
| Instance type          | **t4g.small** (2 vCPU + 2 GB) — the only instance covered by the free promo |
| Key pair               | Create new (Ed25519) or upload your `~/.ssh/id_ed25519.pub`; save the `.pem` private key to `~/.ssh/lumen-prod.pem` and `chmod 600` it |
| Network                | Default VPC, default public subnet, **enable auto-assign public IP**   |
| Security group         | Create new `lumen-prod-sg` — see ingress rules below                   |
| Storage                | 30 GB **gp3** root volume (covered by 30 GB free EBS for new accounts; ~$2.40/mo on existing accounts) |
| Detailed monitoring    | off (free tier only includes basic 5-min metrics)                      |

**Security group ingress rules** (add three):

| Type       | Protocol | Port | Source      |
|------------|----------|------|-------------|
| SSH        | TCP      | 22   | `0.0.0.0/0` (or your /32 for tighter posture) |
| HTTP       | TCP      | 80   | `0.0.0.0/0` |
| HTTPS      | TCP      | 443  | `0.0.0.0/0` |

Default egress (`0.0.0.0/0`, all protocols) is fine — leave it alone.

Click *Launch instance*. State moves through `pending` → `running` in ~30 s. Copy the **public IPv4 address** from the instance detail page.

**Allocate + associate an Elastic IP** so the public address survives instance stop/start: *EC2 → Network & Security → Elastic IPs → Allocate*, then *Actions → Associate* to `lumen-prod`. An EIP attached to a *running* instance is free; it's the unattached/idle case that bills $3.65/mo, so don't allocate spares.

---

## Step 3 — First-login hardening

SSH in as the default Ubuntu user:

```bash
ssh -i ~/.ssh/lumen-prod.pem ubuntu@<your-elastic-ip>
```

Everything from Step 3 onwards can be automated — see **[`scripts/aws-bootstrap.sh`](../../scripts/aws-bootstrap.sh)**, which mirrors steps 3, 4, and the Caddy boot from step 6 in one idempotent script (plus a 4 GB swapfile for the 2 GB RAM constraint). Run it instead of the manual commands below if you want the fast path:

```bash
curl -fsSL https://raw.githubusercontent.com/ahmedEid1/E-Learning-Platform/main/scripts/aws-bootstrap.sh -o bootstrap.sh
chmod +x bootstrap.sh
sudo ./bootstrap.sh
```

The manual equivalent (each block matches a block in the script):

```bash
# 3a — 4 GB swapfile (t4g.small only has 2 GB RAM; Postgres + Celery bursts blow past it)
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo sysctl -w vm.swappiness=10

# 3b — create a non-root admin user
sudo adduser --disabled-password --gecos "" lumen
sudo usermod -aG sudo lumen
sudo mkdir -p /home/lumen/.ssh
sudo cp ~/.ssh/authorized_keys /home/lumen/.ssh/
sudo chown -R lumen:lumen /home/lumen/.ssh
sudo chmod 700 /home/lumen/.ssh && sudo chmod 600 /home/lumen/.ssh/authorized_keys

# 3c — disable password ssh + root login
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart ssh

# 3d — ufw + fail2ban
sudo apt update && sudo apt install -y ufw fail2ban
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw --force enable
sudo systemctl enable --now fail2ban
```

Open a **second** terminal and verify you can `ssh lumen@<elastic-ip>` before closing the original session.

---

## Step 4 — Install Docker Engine + Compose plugin

The official convenience script installs both Docker Engine and the `docker compose` v2 plugin, and is ARM-compatible on Ubuntu 24.04 / Graviton2:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker lumen
# log out, log back in for the group change to apply
exit
ssh lumen@<your-elastic-ip>
docker compose version       # expect: Docker Compose version v2.x.x
```

---

## Step 5 — Clone the repo + generate production secrets

```bash
sudo apt install -y git make
git clone https://github.com/ahmedEid1/E-Learning-Platform.git lumen
cd lumen
cp .env.example .env.production

# If you ran scripts/aws-bootstrap.sh in Step 3, source the values
# it persisted so APP_DOMAIN + ACME_EMAIL are available in your shell
# while you fill in .env.production:
source /etc/lumen-deploy/deploy.env
```

Edit `.env.production` and replace **every** placeholder below. The H6 prod-boot guard refuses to start if any of these is the example value, too short (<32 chars for `SECRET_KEY` / `JWT_SECRET`), or points at `localhost`.

```bash
# 32-byte random secrets — one per line
for var in SECRET_KEY JWT_SECRET S3_SECRET_ACCESS_KEY MINIO_ROOT_PASSWORD POSTGRES_PASSWORD; do
  printf "%s=%s\n" "$var" "$(openssl rand -base64 32 | tr -d '\n')"
done
```

Required edits in `.env.production`:

| Env var                         | Value                                                                 |
|---------------------------------|-----------------------------------------------------------------------|
| `ENV`                           | `production`                                                          |
| `APP_DOMAIN`                    | `lumen.example.com` (the public host you control)                     |
| `SECRET_KEY` / `JWT_SECRET`     | 32+ char random from the loop above                                   |
| `POSTGRES_PASSWORD`             | random; mirror into `DATABASE_URL` / `DATABASE_URL_SYNC` userinfo     |
| `DATABASE_URL`                  | `postgresql+asyncpg://lumen:<pw>@db:5432/lumen`                       |
| `DATABASE_URL_SYNC`             | `postgresql+psycopg://lumen:<pw>@db:5432/lumen`                       |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | random; mirror into `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` |
| `S3_ENDPOINT_URL`               | `http://s3:9000` (internal compose hostname)                          |
| `WEB_BASE_URL`                  | `https://lumen.example.com`                                           |
| `BADGES_ISSUER_URL`             | `https://lumen.example.com`                                           |
| `LLM_PROVIDER` / `OPENAI_API_BASE` / `OPENAI_API_KEY` / `LLM_MODEL` | Groq path: `openai` / `https://api.groq.com/openai/v1` / `<groq-key>` / `llama-3.3-70b-versatile` |
| `SMTP_*`                        | Resend or any SMTP provider (free tier is fine for a demo)            |
| `CORS_ORIGINS`                  | `["https://lumen.example.com"]`                                       |

**2 GB RAM tuning** — append to `.env.production`:

```dotenv
# t4g.small low-memory tuning — these are read by docker-compose.prod.yml's
# redis and worker `command:` blocks and take effect on the next `up -d`.
REDIS_MAXMEMORY=64mb
CELERY_CONCURRENCY=1
```

Postgres on t4g.small runs cleanly with the `pgvector/pgvector:pg17`
image's stock defaults plus the 4 GB swapfile. If sustained
indexing pushes Postgres to OOM regardless, you have two options:
add `-c shared_buffers=128MB -c effective_cache_size=512MB` to the
`db:` service's `command:` (the pgvector image is just stock
Postgres 17 underneath), or bind-mount a tuned `postgresql.conf`.
Both are operator-level overrides — there's no env-var indirection
for these in compose.

---

## Step 6 — Boot the stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production pull
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
docker compose -f docker-compose.prod.yml ps          # all healthy?
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
docker compose -f docker-compose.prod.yml exec api python -m app.cli seed
# Optional: 'demo-seed' adds 3 extra browse-only courses on top of
# the curated multi-agent tutor turn that 'seed' already lays down.
# Skip it unless you specifically want a fuller catalog to click through.
#   docker compose -f docker-compose.prod.yml exec api python -m app.cli demo-seed
```

The `api` healthcheck takes ~30 s to flip green on first boot (model warmup + first DB connection). Watch `free -h` and `htop` the first time — if you see swap usage climb above 1 GB sustained, drop `CELERY_CONCURRENCY` lower or skip MinIO and switch to S3 (see "split deploy" below).

---

## Step 7 — TLS via the containerised Caddy

**Good news:** Caddy is already a service in `docker-compose.prod.yml` (the `proxy:` block). It mounts `infra/caddy/Caddyfile`, terminates TLS on `:443`, and reverse-proxies `/api/*` → `api:8000`, `/api/v1/ws/*` → `api:8000` with WebSocket upgrades, `/assets/*` → `s3:9000` (MinIO read), everything else → `web:3000`. The Caddyfile reads `{$APP_DOMAIN}` from the env you set in step 5, so **nothing further is required on the host** — Caddy will ACME-fetch a Let's Encrypt cert as soon as DNS resolves (step 8).

If you ever need to swap the Caddyfile, edit `infra/caddy/Caddyfile` and `docker compose -f docker-compose.prod.yml restart proxy`. The `caddy-data` volume keeps the cert across restarts; do **not** delete it casually or you'll burn through Let's Encrypt's renewal rate limit.

---

## Step 8 — Point DNS at the Elastic IP

Create a single **A record**:

| Type | Name  | Value                | TTL   | Proxy  |
|------|-------|----------------------|-------|--------|
| A    | lumen | `<your-elastic-ip>`  | 300 s | off    |

Wait for propagation (`dig lumen.example.com +short` should return the EIP), then Caddy will obtain the Let's Encrypt cert automatically on the next request. Tail the logs to watch the ACME handshake:

```bash
docker compose -f docker-compose.prod.yml logs -f proxy
# look for: "certificate obtained successfully" for {$APP_DOMAIN}
```

**Optional: Cloudflare DNS proxy in front.** Once the basic deploy works end-to-end, you can move DNS to Cloudflare and flip the orange-cloud proxy on for DDoS shielding, bot challenges, and analytics. With Cloudflare proxy on, set the SSL/TLS mode to **Full (strict)** — Caddy is still terminating a real Let's Encrypt cert at the origin, so strict-mode validation passes. Do **not** enable Cloudflare's "Always Use HTTPS" until the cert is confirmed obtained, or the ACME http-01 challenge will be hijacked.

---

## Step 9 — Post-deploy smokes

```bash
curl https://lumen.example.com/api/v1/health/live    # → {"status":"ok"}
curl https://lumen.example.com/api/v1/health/ready   # → {"status":"ok","checks":{...}}
curl https://lumen.example.com/api/v1/catalog/courses | jq '.[].slug'
```

Then in a browser:

1. Open `https://lumen.example.com` — catalog should load with the demo courses.
2. Log in as `demo@lumen.test` / `Demo!2026`.
3. Enrol in a course, open a lesson, click **Ask the tutor**, send "explain pgvector cosine distance". Watch the agent trace render.

If all three pass, the deploy is live.

---

## Step 10 — Day-2 operations

```bash
# tail logs
docker compose -f docker-compose.prod.yml logs -f api worker beat

# memory health (t4g.small is tight — watch this regularly)
free -h
docker stats --no-stream

# update the stack
cd ~/lumen && git pull
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml exec api alembic upgrade head

# backup Postgres (the `backup` compose profile dumps + gzips to ./backups)
docker compose -f docker-compose.prod.yml --profile backup run --rm backup
# copy off-box via rsync/scp once a day; cron it from your workstation
# or push to S3 (free tier: 5 GB) via `aws s3 cp`
```

Rotate a secret: edit `.env.production`, then `docker compose -f docker-compose.prod.yml up -d` (Compose only restarts services whose env actually changed). Rotating `JWT_SECRET` invalidates every in-flight token — plan a brief "log in again" window.

---

## Split deploy — pushing the frontend off-box

If the 2 GB cap bites under real load, move the Next.js frontend to **Vercel free tier**, leaving only api + worker + db + redis + minio + caddy on the EC2. Frees up ~250 MB on the box.

1. Pin the Vercel project to `apps/frontend` and set `NEXT_PUBLIC_API_BASE_URL=https://api.lumen.example.com`.
2. Point `api.lumen.example.com` at the Elastic IP via a second A record.
3. Edit `infra/caddy/Caddyfile` to drop the `/ → web:3000` block and bind to `api.lumen.example.com` only.
4. Remove the `web:` service from `docker-compose.prod.yml` (or `docker compose stop web` and disable on subsequent boots).
5. CORS: add `"https://lumen.vercel.app"` (or your custom Vercel domain) to `CORS_ORIGINS`.

---

## Troubleshooting

| Symptom                                        | Cause                                                                                  | Fix                                                                                          |
|------------------------------------------------|----------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| EC2 launch fails: `InsufficientInstanceCapacity` | t4g.small briefly out of capacity in the AZ                                          | Try a different Availability Zone (subnet) in the same region. AWS rarely sustains this >5 min.   |
| `curl https://lumen.example.com` → connection refused | Security group rule for 80/443 missing                                          | Re-check Step 2's three ingress rules in *EC2 → Security Groups → lumen-prod-sg*.             |
| Caddy log: `no such host` or ACME `connection refused` | DNS hasn't propagated yet                                                       | `dig +short lumen.example.com` from another network — wait for it to return the EIP.          |
| `docker compose pull` → `no matching manifest for linux/arm64/v8` | You picked an x86 instance somewhere                               | Confirm the instance type is **t4g.small** (Graviton2 ARM). The default `pgvector/pgvector:pg17`, `redis:7-alpine`, `caddy:2-alpine`, and `minio` images all ship ARM64 manifests. |
| `prod_guards.py` boot failure: `SECRET_KEY too short` | You left an example value in `.env.production`                                  | Re-run the `openssl rand -base64 32` loop in Step 5.                                          |
| Let's Encrypt rate-limited (`too many certificates`) | You bounced the `caddy-data` volume during testing                              | Wait 7 days, or temporarily set Caddy to staging via `ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory`. |
| `OutOfMemory` killer reaped a container         | t4g.small is tight; bursty work pushed past 2 GB + 4 GB swap                          | Set `CELERY_CONCURRENCY=1` and `REDIS_MAXMEMORY=64mb` in `.env.production`, or switch to the **split deploy** above. If Postgres itself is the OOM victim, add `-c shared_buffers=128MB -c effective_cache_size=512MB` to the `db:` service's `command:` in `docker-compose.prod.yml`. |
| Free Plan auto-close warning email             | 6 months elapsed or $200 credits exhausted                                            | Add a card to upgrade to Paid Plan (~$18/mo steady-state) or migrate to Oracle Always Free / Hetzner CAX11. |

---

## See also

- [`docker-compose.prod.yml`](../../docker-compose.prod.yml) — the single source of compose truth
- [`infra/caddy/Caddyfile`](../../infra/caddy/Caddyfile) — TLS + routing rules
- [`scripts/aws-bootstrap.sh`](../../scripts/aws-bootstrap.sh) — automated Steps 3–4 for fresh VMs
- [`.env.example`](../../.env.example) — every env var Lumen reads
