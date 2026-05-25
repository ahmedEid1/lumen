# Operator activation runbook — Lumen 1.1.0-agentic

> **Status (2026-05-25):** ✅ **LIVE.** The demo is reachable at <https://lumen.ahmedhobeishy.tech>. Steps 1–3 (AWS signup, t4g.small launch, deploy) are complete; Step 5 (MCP publish) and Step 6 (captioned screencast) shipped earlier in the day. Real LLM via Groq Llama 3.3 70B, real retrieval via Cloudflare Workers AI embeddings, the README badge now resolves green. Step 4 (tutor-eval re-run against the live VM) and Step 7 (PR open + voiced Loom) are the remaining stretch items. The runbook below is kept as a reproducible record of how the deploy landed — re-runnable verbatim if you ever need to stand the box up again on a new account or in a different region.

This is the single, ordered runbook for getting Lumen from "the code is on a branch in your worktree" to "a recruiter can click your live demo, see the MCP server in the public registry, watch a 90-second Loom, and the PR is open on GitHub." Everything below is **operator-driven** — Claude prepared every artifact but cannot run external accounts on your behalf.

**Time budget:** ~2 hours of focused work in one sitting. AWS Free Plan signup is instant (no async approval). Steps 5 (MCP publish) and 6 (screencast) are already complete; only Steps 1–4 + 7 remain.

**Status:** Branch `claude/romantic-mayer-ab2e85` at HEAD `5f348fd`, 45 commits ahead of `15cb431` (the 1.1.0-agentic release), backend 628/628 + frontend 139/139, working tree clean. Pivoted from Oracle Always Free to AWS t4g.small on 2026-05-25 after Frankfurt A1 capacity stayed saturated for 24h and Oracle's PAYG region-subscription cap blocked the Stockholm fallback.

---

## Variables you'll capture as you go

Keep these in a sticky note as you progress. Several steps feed each other.

| Variable | Set in step | Used in step |
|---|---|---|
| `AWS_REGION` (e.g. `eu-central-1`) | 1 | 2 |
| `VM_IP` (Elastic IP) | 2 | 3, 6 |
| `SSH_KEY_PATH` (e.g. `~/.ssh/lumen-prod.pem`) | 2 | 3 |
| `DOMAIN_NAME` (optional — e.g. `lumen.ahmedhobeishy.de`) | 2 (optional) | 3, 6 |
| `GROQ_KEY` (starts with `gsk_`) | 3 | 4, 5 |
| `EVAL_SCORE` (e.g. `4.2/5`) | 4 | ping Claude |
| `MCP_REGISTRY_URL` | (Step 5 — already done) | n/a |
| `LOOM_URL` or `SCREENCAST_PATH` | (Step 6 — already done) | n/a |

🛑 markers below = stop here and ping Claude so Claude can do the code-side work (paste keys, update README, push branch).

---

## Step 1 — AWS Free Plan signup (~15 min, instant activation)

1. Open <https://signup.aws.amazon.com>.
2. Pick the **Free Plan** option (the no-card, 6-month, up-to-$200-credit path) — *not* the legacy 12-month free tier.
3. **Email** + **AWS account name** (you can change the display name later; the underlying 12-digit account ID is permanent).
4. **Mobile SMS verify** (no card required for the Free Plan path).
5. Pick a **home region**. Good defaults for Essen: `eu-central-1` (Frankfurt, ~15 ms) or `eu-west-1` (Ireland, ~30 ms). AWS regions are not locked to your account — you can spin up resources anywhere — but free t4g.small hours are aggregated across regions so pick one and stick with it. Capture as `AWS_REGION`.
6. Activation is **instant** — the welcome email arrives in <1 min.

Once in the console:

1. **Set a $5/month budget alarm** under *Billing → Budgets → Create budget* (template: "Monthly cost budget", threshold $5, alert email = your address). Belt-and-braces — the Free Plan auto-blocks at $0 actual charges, but the email warns you well before the 6-month auto-close lands.
2. **Complete the 5 onboarding tasks** (Billing → Free Plan → Earn more credits) to unlock the second $100 of credits: launch+terminate an EC2 instance, configure an RDS instance, deploy a Lambda function, test a Bedrock prompt, set up a budget. Total ~30 min of clicking through "hello world" tutorials. Save the tasks for after Step 2 — the EC2 task there counts.

🛑 Ping Claude with: "AWS Free Plan active, region `<AWS_REGION>`." (No code change needed yet.)

---

## Step 2 — Launch the t4g.small EC2 instance (~15 min)

### 2.1 Prepare an SSH key

Two options — pick one:

**(a) Reuse an existing local key** (recommended if you already have `~/.ssh/id_ed25519`). You'll upload the public key into the EC2 console as a "key pair" so the instance accepts your local private key.

**(b) Let AWS generate a new keypair.** The EC2 launch wizard offers this. AWS gives you a `.pem` file to download once — save it to `~/.ssh/lumen-prod.pem` and `chmod 600` immediately or SSH will refuse to use it.

Either way, capture the path as `SSH_KEY_PATH`.

### 2.2 Launch the instance

In the EC2 console (top-right region picker → `<AWS_REGION>` → *EC2 → Instances → Launch instances*):

| Field | Value |
|---|---|
| Name | `lumen-prod` |
| AMI | **Canonical Ubuntu 24.04 LTS** — the *arm64* build (the wizard auto-picks it once you select t4g.small) |
| Instance type | **t4g.small** (2 vCPU + 2 GB Graviton2 — the only type covered by the free promo) |
| Key pair | Existing key (option a) or "Create new key pair" → save `.pem` (option b) |
| Network settings → Auto-assign public IP | **Enable** |
| Network settings → Firewall (security group) | Create new `lumen-prod-sg` — see ingress rules below |
| Storage | 30 GB **gp3** root volume |

**Security group ingress rules** (add three before launching):

| Type | Protocol | Port | Source |
|---|---|---|---|
| SSH | TCP | 22 | `0.0.0.0/0` (or your `<your-ip>/32` for tighter posture) |
| HTTP | TCP | 80 | `0.0.0.0/0` |
| HTTPS | TCP | 443 | `0.0.0.0/0` |

Default egress (`0.0.0.0/0`, all protocols) is fine — leave it.

Click **Launch instance**. State moves `pending → running` in ~30 s.

⚠️ **If you see `InsufficientInstanceCapacity`:** AWS briefly out of t4g.small in this AZ. Pick a different Availability Zone (subnet) in the same region and retry — rarely sustains >5 min. Full alt-AZ recovery in [`docs/deployment/aws-vps.md`](../deployment/aws-vps.md) troubleshooting.

### 2.3 Allocate an Elastic IP (so the public address survives stop/start)

*EC2 → Network & Security → Elastic IPs → Allocate Elastic IP address* (defaults are fine). Then *Actions → Associate Elastic IP address* → instance `lumen-prod`. EIP attached to a running instance is free; the unattached/idle case is the only thing that bills ($3.65/mo). Do not allocate spares.

Capture the Elastic IP address — **this is `VM_IP`.**

### 2.4 Verify SSH works

```bash
chmod 600 ~/.ssh/lumen-prod.pem   # only needed for option-b keys
ssh -i <SSH_KEY_PATH> ubuntu@<VM_IP>
# Type "yes" to accept the host key on first connect.
# You should land at a `ubuntu@ip-...:~$` prompt.
exit
```

🛑 Ping Claude with: "EC2 up at `<VM_IP>`, SSH works." No code change needed yet — but capturing it tells Claude you're ready for Step 3.

### 2.5 Optional — point a domain at the Elastic IP

If you own a domain (e.g. `ahmedhobeishy.de`):
1. Create an A record `lumen.ahmedhobeishy.de → <VM_IP>` at your DNS provider (Route 53, Cloudflare, registrar's DNS — any works).
2. Wait 5–15 min for propagation (`dig lumen.ahmedhobeishy.de` shows the IP).
3. Capture `DOMAIN_NAME` for Step 3.

**No domain?** Use [`<VM_IP>.nip.io`](https://nip.io) — a free wildcard DNS service that resolves any IP-shaped subdomain back to that IP. Caddy will fetch a Let's Encrypt cert against it. Your `DOMAIN_NAME` is literally `<VM_IP>.nip.io` (e.g. `52.18.123.45.nip.io`).

### 2.6 Optional — point a domain at the VM

If you own a domain (e.g. `ahmedhobeishy.de`):
1. Create an A record `lumen.ahmedhobeishy.de → <VM_IP>` at your DNS provider.
2. Wait 5–15 min for propagation (`dig lumen.ahmedhobeishy.de` shows the IP).
3. Capture `DOMAIN_NAME` for Step 3.

**No domain?** Use [`<VM_IP>.nip.io`](https://nip.io) — a free wildcard DNS service that resolves any IP-shaped subdomain back to that IP. Caddy will fetch a Let's Encrypt cert against it. Your `DOMAIN_NAME` is literally `<VM_IP>.nip.io` (e.g. `141.144.123.45.nip.io`).

---

## Step 3 — Bootstrap the VM + deploy Lumen (~45 min)

### 3.1 Get a Groq API key (free, instant)

1. Open <https://console.groq.com> and sign up (Google OAuth works; ~30 sec).
2. **API Keys** → **Create API Key** → name it `lumen-prod`.
3. Copy the key — starts with `gsk_...`. **You see it ONCE.** This is `GROQ_KEY`.

### 3.2 SSH into the EC2 and run the bootstrap script

```bash
ssh -i <SSH_KEY_PATH> ubuntu@<VM_IP>

# In a SECOND local terminal (don't close the ssh session):
scp -i <SSH_KEY_PATH> scripts/aws-bootstrap.sh ubuntu@<VM_IP>:~/

# Back in the ssh session:
chmod +x aws-bootstrap.sh
sudo ./aws-bootstrap.sh
```

The script will prompt you for:
- **Admin username** for the new non-root user (default `lumen` — accept).
- **Domain name** for TLS (paste `DOMAIN_NAME` from Step 2.6 — see optional step below).
- **Admin email** for Let's Encrypt notifications (your real email).

It will then: create a 4 GB swapfile (critical for the 2 GB RAM cap), install Docker + Compose, harden sshd (key-only auth), enable ufw, install fail2ban. **Idempotent** — re-runnable.

⚠️ **If the script halts with "Refusing to disable password SSH without verified authorized_keys":** that's the M1 guard working as intended. It means your key wasn't found in the expected location. Re-run with `LUMEN_SKIP_SSHD_HARDENING=1 sudo ./aws-bootstrap.sh` and harden manually after the deploy works.

### 3.3 Verify you can ssh in as the new admin user

```bash
# Open a THIRD terminal — don't close the ubuntu@ session yet.
ssh -i <SSH_KEY_PATH> lumen@<VM_IP>
# Should land at a lumen@ip-...:~$ prompt.
```

Once that works, you can close the original `ubuntu@` session.

### 3.4 Clone the repo onto the VM

The branch isn't on GitHub yet (we'll push it in Step 7). So clone via scp:

```bash
# On your LOCAL machine, from the worktree root:
rsync -avz -e "ssh -i <SSH_KEY_PATH>" \
  --exclude='.venv' --exclude='node_modules' --exclude='.next' \
  --exclude='.git/objects' --exclude='.playwright-mcp' \
  ./ lumen@<VM_IP>:~/lumen/

# Then ssh in and finish the .git bootstrap:
ssh -i <SSH_KEY_PATH> lumen@<VM_IP>
cd ~/lumen
git status   # should show clean tree on claude/romantic-mayer-ab2e85
```

**Alternative if rsync isn't installed:** push the branch to a private GitHub branch first (`git push origin claude/romantic-mayer-ab2e85` from your laptop), then `git clone -b claude/romantic-mayer-ab2e85 git@github.com:ahmedEid1/E-Learning-Platform.git lumen` on the VM.

### 3.5 Configure `.env.production`

```bash
cd ~/lumen
cp .env.example .env.production
nano .env.production   # or vim, your call
```

**Edit these values** (everything else can keep example defaults for now):

```env
# --- domain & TLS ---
APP_DOMAIN=<your DOMAIN_NAME from Step 2.6>
ACME_EMAIL=<your email>

# --- secrets — REGENERATE EVERY ONE OF THESE ---
# Run this in a separate terminal to mint each value:
#   openssl rand -base64 32
JWT_SECRET=<paste output>
SECRET_KEY=<paste output>
S3_ACCESS_KEY_ID=<paste output>
S3_SECRET_ACCESS_KEY=<paste output>
POSTGRES_PASSWORD=<paste output>
REDIS_PASSWORD=<paste output>

# --- LLM provider (Groq for free + fast) ---
LLM_PROVIDER=openai
OPENAI_API_BASE=https://api.groq.com/openai/v1
OPENAI_API_KEY=<paste GROQ_KEY from Step 3.1>
LLM_MODEL=llama-3.3-70b-versatile

# --- production hardening ---
ENVIRONMENT=production
ALLOWED_HOSTS=<DOMAIN_NAME>
CORS_ORIGINS=https://<DOMAIN_NAME>
WEB_BASE_URL=https://<DOMAIN_NAME>
```

Then append the **2 GB RAM tuning block** (t4g.small only has 2 GB):

```env
# t4g.small low-memory tuning — wired into docker-compose.prod.yml
# via the redis and worker `command:` blocks; effective on next `up -d`.
REDIS_MAXMEMORY=64mb
CELERY_CONCURRENCY=1
```

The `pgvector/pgvector:pg17` image runs with stock Postgres 17
defaults; the 4 GB swapfile that `aws-bootstrap.sh` installed
covers the 2 GB ceiling for normal operation. If Postgres itself
OOMs under sustained load, add `-c shared_buffers=128MB -c
effective_cache_size=512MB` to the `db:` service's `command:` in
`docker-compose.prod.yml`.

Save + exit.

### 3.6 Boot the stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
# Wait ~60 seconds for Postgres healthcheck + migration container to finish.
# Watch memory: `free -h` and `docker stats --no-stream` should show
# ~1.8 GB used (of 2 GB) + minimal swap on a quiet box.

docker compose -f docker-compose.prod.yml --env-file .env.production exec api alembic upgrade head
docker compose -f docker-compose.prod.yml --env-file .env.production exec api python -m app.cli seed
docker compose -f docker-compose.prod.yml --env-file .env.production exec api python -m app.cli demo-seed
```

### 3.7 Verify the live demo works

```bash
# From the VM:
curl -sS https://<DOMAIN_NAME>/api/v1/health/live
# Should return: {"status": "ok", ...}

# From your laptop, open in a browser:
https://<DOMAIN_NAME>
# Should show the Lumen landing page with TLS green-lock.
# Log in as student@lumen.test / Learn!2026 and click around.
```

⚠️ **If Caddy can't get a cert:** Let's Encrypt has rate limits (5 certs per domain per week). If you've been retrying, check `docker compose -f docker-compose.prod.yml logs proxy` for `ratelimited` errors. Fall back to ACME staging (`STAGING=1` env) for testing, then switch back to prod once everything else works.

🛑 Ping Claude: "Demo live at https://`<DOMAIN_NAME>`, login works." Claude updates the README's `LIVE_DEMO_URL_TBD` placeholder with the real URL.

✅ **Done 2026-05-25.** Live at <https://lumen.ahmedhobeishy.tech>. README badge resolves green at the live URL; the placeholder is gone.

---

## Step 4 — Run the eval suite for a real tutor score (~5 min)

This produces the `tutor eval: X/5` number that fills the README badge.

```bash
# On the VM, inside the lumen dir:
docker compose -f docker-compose.prod.yml --env-file .env.production exec api \
  python -m app.evals run --suite tutor
```

This runs all 30 tutor items against Groq Llama 3.3 70B with the LLM-as-judge. Takes ~3–5 min. Watch the progress; final line prints `mean overall: X.XX/5`.

```bash
# Copy the report file off the VM to commit it locally:
# From your laptop:
scp lumen@<VM_IP>:~/lumen/apps/backend/evals/reports/tutor-*.jsonl ./apps/backend/evals/reports/
```

🛑 Ping Claude with the mean score (e.g. `tutor eval: 4.2/5 (n=30)`). Claude:
1. Updates the README badge from `TBD/5` → real number
2. Commits the report JSONL (the `.gitignore` excludes it by default; we commit this one specifically as evidence)

---

## Step 5 — Publish the MCP server to the public registry — ✅ DONE

Already shipped on 2026-05-25. `io.github.ahmedEid1/lumen` v1.1.0 is live at <https://registry.modelcontextprotocol.io/v0/servers?search=io.github.ahmedEid1%2Flumen>. The README badge already resolves green. No action needed.

---

## Step 6 — Screencast walkthrough — ✅ DONE (silent captioned MP4)

A silent captioned walkthrough was autonomously recorded against the local Docker stack and committed at [`docs/screencast/walkthrough.mp4`](../screencast/walkthrough.mp4). It covers the same 6 beats originally scoped for the Loom version (landing → tutor → agent reasoning → trace surface → self-critique authoring → observability) without depending on a live URL.

**Optional follow-up (after Step 3.7 confirms `https://<DOMAIN_NAME>` is live):** record a 90-second voiced Loom against the *live* demo for the README hero spot. The captioned MP4 stays as the primary demo asset either way. The 6-beat script lives at [`docs/release/loom-recording-script.md`](loom-recording-script.md) with both local-stack + live-URL variants; capture URL as `LOOM_URL` and ping Claude to update the README.

---

## Step 7 — Push the branch and open the PR (~5 min)

This is the moment everything goes public.

### 7.1 Verify your local state

```bash
# In your local worktree:
git status   # clean
git log --oneline -3   # HEAD at 8a8eb21 (or wherever Claude's last commit is)
```

### 7.2 Verify `gh` is logged in

```bash
gh auth status
# If "You are not logged into any GitHub hosts":
gh auth login
# Pick GitHub.com → HTTPS → Login with browser.
```

### 7.3 Run the publish target

```bash
make publish-rewrite
```

This will:
1. Show you `git log origin/Rewrite..Rewrite --oneline | head -25` so you can see what's about to be pushed.
2. Prompt `[y/N]`. **Type `y` and Enter.**
3. Run `git push origin Rewrite`.
4. Run `gh pr create --base master --head Rewrite --title "..." --body-file docs/release/1.1.0-agentic-pr-body.md`.

You'll get a PR URL back. Open it in a browser, eyeball it, and **leave it open** (don't merge yet — let it sit for a day so anyone you reach out to can see the PR is fresh).

🛑 Ping Claude with the PR URL so it's in the session log.

---

## Step 8 — Apply (out of scope for Claude, but the actual reason we did all this)

Now the portfolio is live. Hit your shortlist:
- **Anthropic / OpenAI / Mistral** applied-AI teams (stretch)
- **Hugging Face, Cohere EU, n8n, ElevenLabs, Aleph Alpha, Black Forest Labs** (realistic EU AI tech)
- **Cursor, Replit, Vercel** + smaller forward-deployed teams (broad)
- LinkedIn DMs to recruiters with the demo URL + GitHub + a sentence about agentic-AI craft

Reference the README's "Built by" section and link the Loom in your cover paragraph.

---

## Recovery / common issues

- **AWS `InsufficientInstanceCapacity` on launch:** Pick a different Availability Zone (subnet) within `<AWS_REGION>` and retry. Rarely sustains >5 min.
- **Free Plan credits exhausted before 6 months:** Check *Billing → Cost Explorer*. Most likely culprit is an unattached Elastic IP — release any spares (`EC2 → Elastic IPs → Actions → Release`). t4g.small instance hours are free regardless of credits through Dec 31 2026.
- **Free Plan auto-close email at 6 months:** Either add a card to upgrade to Paid Plan (~$18/mo steady-state after Dec 31 2026) or migrate the deploy to Oracle Always Free A1 / Hetzner CAX11 — the compose stack works on all three because all three are ARM64 Ubuntu 24.04. Migration mostly means rerunning Steps 2–3 against the new target.
- **Out-of-memory killer reaped a container:** t4g.small is tight. Set `CELERY_CONCURRENCY=1` and `REDIS_MAXMEMORY=64mb` in `.env.production`, or move the Next.js frontend to Vercel free (see "Split deploy" in `docs/deployment/aws-vps.md`). If Postgres is the OOM victim, add `-c shared_buffers=128MB -c effective_cache_size=512MB` to the `db:` service's `command:` in `docker-compose.prod.yml`.
- **Groq rate-limit during eval:** free tier is 30 req/min on Llama 3.3 70B. The eval runner respects this; if it errors, re-run — it resumes from the report's last line.
- **Caddy TLS won't issue:** check `docker compose logs proxy`; the most common cause is DNS not propagated yet. `dig <DOMAIN_NAME>` from the VM should return its own IP.
- **`make publish-rewrite` says "no commits to push":** you're on the wrong local branch. `git checkout Rewrite` first.

---

## Where Claude takes over (the 🛑 moments)

1. After Step 1 — Claude acknowledges AWS Free Plan is active. ✅ done.
2. After Step 2 — Claude acknowledges EC2 is up. ✅ done.
3. After Step 3.7 — Claude updates `LIVE_DEMO_URL_TBD` → real URL in README + commits. ✅ done 2026-05-25 → <https://lumen.ahmedhobeishy.tech>.
4. After Step 4 — Claude updates the tutor-eval badge in README + commits the report JSONL. (Authoring badge already at 3.85/5; tutor re-run against the live VM remains the stretch follow-up.)
5. Step 5 (MCP publish) — already done; no action.
6. Step 6 (screencast) — already done as `docs/screencast/walkthrough.mp4`; the optional voiced Loom against the live URL is a stretch goal.
7. After Step 7 — Claude logs the PR URL for the session record.

After all of these, the README has zero placeholders, the demo is live, the MCP server is publicly listed, the screencast is committed, and the PR is open. **That is the "ready to apply" state.**
