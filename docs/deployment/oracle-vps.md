# Oracle Cloud Always Free — Lumen live demo

This is the operator runbook for putting Lumen on the public internet at
**$0/forever** using Oracle Cloud's Always Free tier. One ARM VM, the
unmodified `docker-compose.prod.yml`, containerised Caddy for TLS,
Cloudflare DNS proxying as an optional add-on.

| Resource         | Always-Free allowance                                            | What lives there                                                                                  |
|------------------|------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| ARM Ampere A1 VM | 4 OCPU + 24 GB RAM (flexible, billed as 3 000 OCPU·h/mo)         | FastAPI api + Celery worker + beat + Postgres-pgvector + Redis + MinIO + Caddy (one compose file) |
| Block storage    | 200 GB combined boot + block (5 free volume backups)             | Postgres data, Redis AOF, MinIO objects, Caddy `/data` (Let's Encrypt cert + ACME state)          |
| Egress           | 10 TB/mo outbound from the home region                           | Public HTTPS traffic to your demo                                                                 |
| TLS              | Let's Encrypt via the Caddy 2 container (auto-renewing)          | Origin TLS on `:443`                                                                              |

Steady-state cost at zero traffic: **$0/mo, forever**. The Always-Free
allowance does not expire when the 30-day Free Trial credit runs out;
Oracle just stops you from creating *paid* resources unless you upgrade.

> **Loom screencast:** `<TODO operator — drop the 90-second demo URL here once recorded>`

---

## Prereqs

- An Oracle Cloud Infrastructure account (signup below — free, but the KYC step does check a credit card).
- A domain you control (or a subdomain). The runbook uses `lumen.example.com`; substitute yours.
- An SSH key pair on your workstation (`ssh-keygen -t ed25519` if you don't already have one).
- About 90 minutes the first time, ~15 minutes on every subsequent deploy.

---

## Step 1 — Sign up for Oracle Cloud

1. Go to <https://signup.cloud.oracle.com>. Pick a **home region** close to your audience: this region is permanent for the tenancy, so don't pick at random.
2. Fill the form. The card-check step is mandatory but **does not charge** the card — Oracle uses it to keep crypto-mining bots out.
3. **Region rejection.** Some popular regions (Frankfurt, London, Ashburn) auto-reject new Always-Free signups when capacity is exhausted. If you see "your account is not eligible", restart the signup and pick a less-loaded region (e.g. `eu-stockholm-1`, `ap-melbourne-1`, `sa-vinhedo-1`). Your home region is permanent, so a fresh signup is the only way to change it.
4. Wait for the "your tenancy is ready" email (usually <10 minutes).

---

## Step 2 — Create the Always-Free ARM A1 VM

In the OCI console (left rail → *Compute → Instances → Create instance*):

| Field            | Value                                                                  |
|------------------|------------------------------------------------------------------------|
| Name             | `lumen-prod`                                                           |
| Compartment      | root (default)                                                         |
| Image            | **Canonical Ubuntu 24.04** (the *aarch64* build — the console auto-picks it for ARM shapes) |
| Shape            | **VM.Standard.A1.Flex** → **4 OCPU, 24 GB memory** (the entire Always-Free allowance) |
| VCN              | "Create new VCN" — accept defaults (10.0.0.0/16, public subnet)        |
| Public IPv4      | **Assign**                                                             |
| SSH keys         | Upload your `~/.ssh/id_ed25519.pub`                                    |
| Boot volume      | 100 GB (you have 200 GB total budget — leave headroom for a backup volume later) |

Click *Create*. The instance moves through `PROVISIONING` → `STARTING` → `RUNNING` in 2–5 min. Copy the **public IP** from the instance detail page.

Then open the firewall on the security list (left rail → *Networking → Virtual cloud networks → your VCN → Default security list*) and add three **ingress** rules:

| Source       | Protocol | Dest port |
|--------------|----------|-----------|
| 0.0.0.0/0    | TCP      | 22        |
| 0.0.0.0/0    | TCP      | 80        |
| 0.0.0.0/0    | TCP      | 443       |

The default subnet's egress is already wide open — leave it alone.

---

## Step 3 — First-login hardening

SSH in as the default Ubuntu user:

```bash
ssh ubuntu@<your-public-ip>
```

Everything from Step 3 onwards can be automated — see **[`scripts/oracle-bootstrap.sh`](../../scripts/oracle-bootstrap.sh)**, which mirrors steps 3, 4, and the Caddy boot from step 6 in one idempotent script. Run it instead of the manual commands below if you want the fast path:

```bash
curl -fsSL https://raw.githubusercontent.com/ahmedEid1/E-Learning-Platform/master/scripts/oracle-bootstrap.sh -o bootstrap.sh
chmod +x bootstrap.sh
sudo ./bootstrap.sh
```

The manual equivalent (each block matches a block in the script):

```bash
# 3a — create a non-root admin user
sudo adduser --disabled-password --gecos "" lumen
sudo usermod -aG sudo lumen
sudo mkdir -p /home/lumen/.ssh
sudo cp ~/.ssh/authorized_keys /home/lumen/.ssh/
sudo chown -R lumen:lumen /home/lumen/.ssh
sudo chmod 700 /home/lumen/.ssh && sudo chmod 600 /home/lumen/.ssh/authorized_keys

# 3b — disable password ssh + root login
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart ssh

# 3c — ufw + fail2ban
sudo apt update && sudo apt install -y ufw fail2ban
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw --force enable
sudo systemctl enable --now fail2ban
```

Open a **second** terminal and verify you can `ssh lumen@<ip>` before closing the original session.

---

## Step 4 — Install Docker Engine + Compose plugin

The official convenience script installs both Docker Engine and the `docker compose` v2 plugin, and is ARM-compatible on Ubuntu 24.04:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker lumen
# log out, log back in for the group change to apply
exit
ssh lumen@<your-public-ip>
docker compose version       # expect: Docker Compose version v2.x.x
```

---

## Step 5 — Clone the repo + generate production secrets

```bash
sudo apt install -y git make
git clone https://github.com/ahmedEid1/E-Learning-Platform.git lumen
cd lumen
cp .env.example .env.production
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

---

## Step 6 — Boot the stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production pull
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
docker compose -f docker-compose.prod.yml ps          # all healthy?
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
docker compose -f docker-compose.prod.yml exec api python -m app.cli seed
docker compose -f docker-compose.prod.yml exec api python -m app.cli demo-seed
```

The `api` healthcheck takes ~30 s to flip green on first boot (model warmup + first DB connection).

---

## Step 7 — TLS via the containerised Caddy

**Good news:** Caddy is already a service in `docker-compose.prod.yml` (the `proxy:` block). It mounts `infra/caddy/Caddyfile`, terminates TLS on `:443`, and reverse-proxies `/api/*` → `api:8000`, `/api/v1/ws/*` → `api:8000` with WebSocket upgrades, `/assets/*` → `s3:9000` (MinIO read), everything else → `web:3000`. The Caddyfile reads `{$APP_DOMAIN}` from the env you set in step 5, so **nothing further is required on the host** — Caddy will ACME-fetch a Let's Encrypt cert as soon as DNS resolves (step 8).

If you ever need to swap the Caddyfile, edit `infra/caddy/Caddyfile` and `docker compose -f docker-compose.prod.yml restart proxy`. The `caddy-data` volume keeps the cert across restarts; do **not** delete it casually or you'll burn through Let's Encrypt's renewal rate limit.

---

## Step 8 — Point DNS at the VM

Create a single **A record**:

| Type | Name  | Value                | TTL   | Proxy  |
|------|-------|----------------------|-------|--------|
| A    | lumen | `<your-public-ip>`   | 300 s | off    |

Wait for propagation (`dig lumen.example.com +short` should return the VM IP), then Caddy will obtain the Let's Encrypt cert automatically on the next request. Tail the logs to watch the ACME handshake:

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
# update the stack to the latest image tag
cd ~/lumen && git pull
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml exec api alembic upgrade head

# backup Postgres (the `backup` compose profile dumps + gzips to ./backups)
docker compose -f docker-compose.prod.yml --profile backup run --rm backup
# copy off-box via rsync/scp once a day; cron it from your workstation
```

Rotate a secret: edit `.env.production`, then `docker compose -f
docker-compose.prod.yml up -d` (Compose only restarts services whose env
actually changed). Rotating `JWT_SECRET` invalidates every in-flight
token — plan a brief "log in again" window.

---

## Troubleshooting

| Symptom                                        | Cause                                                                                  | Fix                                                                                          |
|------------------------------------------------|----------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| VM stuck in `PROVISIONING` >10 min             | Region out of A1 capacity                                                              | Wait + retry, or use the *"Try again in another availability domain"* button in the console.  |
| `curl https://lumen.example.com` → connection refused | Security list rule for 80/443 missing                                          | Re-check Step 2's three ingress rules in *Networking → VCN → security list*.                  |
| Caddy log: `no such host` or ACME `connection refused` | DNS hasn't propagated yet                                                       | `dig +short lumen.example.com` from another network — wait for it to return the VM IP.        |
| `docker compose pull` → `no matching manifest for linux/arm64/v8` | You picked an x86 image somewhere                                  | Confirm the VM shape is **A1.Flex** (ARM). The default `pgvector/pgvector:pg17`, `redis:7-alpine`, `caddy:2-alpine`, and `minio` images all ship ARM64 manifests. |
| `prod_guards.py` boot failure: `SECRET_KEY too short` | You left an example value in `.env.production`                                  | Re-run the `openssl rand -base64 32` loop in Step 5.                                          |
| Let's Encrypt rate-limited (`too many certificates`) | You bounced the `caddy-data` volume during testing                              | Wait 7 days, or temporarily set Caddy to staging via `ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory`. |

---

## See also

- [`docker-compose.prod.yml`](../../docker-compose.prod.yml) — the single source of compose truth
- [`infra/caddy/Caddyfile`](../../infra/caddy/Caddyfile) — TLS + routing rules
- [`scripts/oracle-bootstrap.sh`](../../scripts/oracle-bootstrap.sh) — automated Steps 3–4 for fresh VMs
- [`.env.example`](../../.env.example) — every env var Lumen reads
