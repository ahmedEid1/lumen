# Operator activation runbook — Lumen 1.1.0-agentic

This is the single, ordered runbook for getting Lumen from "the code is on a branch in your worktree" to "a recruiter can click your live demo, see the MCP server in the public registry, watch a 90-second Loom, and the PR is open on GitHub." Everything below is **operator-driven** — Claude prepared every artifact but cannot run external accounts on your behalf.

**Time budget:** ~3 hours of focused work spread across ~1 day (Oracle account approval is async).

**Status:** Branch `claude/romantic-mayer-ab2e85` at HEAD `8a8eb21`, 43 commits ahead of `15cb431` (the 1.1.0-agentic release), backend 628/628 + frontend 139/139, working tree clean.

---

## Variables you'll capture as you go

Keep these in a sticky note as you progress. Several steps feed each other.

| Variable | Set in step | Used in step |
|---|---|---|
| `REGION` (e.g. `eu-stockholm-1`) | 1 | 2 |
| `VM_IP` (public IPv4) | 2 | 3, 6 |
| `SSH_KEY_PATH` (e.g. `~/.ssh/id_ed25519`) | 2 | 3 |
| `DOMAIN_NAME` (optional — e.g. `lumen.ahmedhobeishy.de`) | 2 (optional) | 3, 6 |
| `GROQ_KEY` (starts with `gsk_`) | 3 | 4, 5 |
| `EVAL_SCORE` (e.g. `4.2/5`) | 4 | ping Claude |
| `MCP_REGISTRY_URL` | 5 | ping Claude |
| `LOOM_URL` | 6 | ping Claude |

🛑 markers below = stop here and ping Claude so Claude can do the code-side work (paste keys, update README, push branch).

---

## Step 1 — Oracle Cloud Always Free signup (~30 min active, then async approval)

Full screen-by-screen walkthrough is in chat. Short version:

1. Open <https://signup.cloud.oracle.com>
2. **Country:** Germany. **Cloud Account Name:** a lowercase-only slug (this is permanent — becomes part of your console URL).
3. ⚠️ **Home region: pick `eu-stockholm-1`.** Do NOT pick Frankfurt, London, Ashburn, or Phoenix — all saturated for ARM A1. Stockholm has reliable A1 capacity, ~25 ms RTT from Essen.
4. Mobile SMS verify (German +49 number).
5. **Card check:** credit card or Visa/MC debit. Oracle takes a €1 temporary hold, never charges Always Free. Prepaid cards (Vimpay, Revolut virtual) usually get rejected.
6. Submit and **bookmark the tenancy URL** Oracle shows (looks like `cloud.oracle.com/?tenant=<slug>&region=eu-stockholm-1`).

**Wait for the "Your Oracle Cloud account is ready" email.** 80% of the time it lands in under 10 minutes; 15% takes 1–4 hours; rare cases 24 h.

**While waiting → start Step 5 (MCP registry publish) in parallel** — it's fully independent of Oracle.

🛑 When the approval email arrives, ping Claude with "Oracle approved, what next." (No code changes needed at this step.)

---

## Step 2 — Create the ARM A1 VM (~20 min after approval lands)

### 2.1 Generate an SSH key on your local machine (skip if you already have one)

```bash
# Check first:
ls ~/.ssh/id_ed25519.pub 2>/dev/null && echo "have one"

# If not:
ssh-keygen -t ed25519 -C "lumen-oracle"
# Press Enter for default path. Set a passphrase (recommended) or leave empty.
```

The public key (`~/.ssh/id_ed25519.pub`) is what you paste into Oracle. The private key (`~/.ssh/id_ed25519`) stays on your machine forever.

### 2.2 Create the VM in the OCI console

Log in to your tenancy URL. Left rail → **Compute → Instances → Create instance**.

| Field | Value |
|---|---|
| Name | `lumen-prod` |
| Image | **Canonical Ubuntu 24.04** (aarch64 — the console auto-picks ARM when the shape is A1) |
| Shape | **VM.Standard.A1.Flex** → set OCPU=**4**, Memory=**24 GB** |
| VCN | "Create new VCN" → accept all defaults |
| Public IPv4 | **Assign** (toggle on) |
| SSH keys | Paste the contents of `~/.ssh/id_ed25519.pub` |
| Boot volume | 100 GB |

Click **Create**. Wait 2–5 min for `PROVISIONING → STARTING → RUNNING`.

⚠️ **If you see "Out of host capacity":** Stockholm is briefly out. Wait 15 min and retry. If it persists 24 h, the runbook in `docs/deployment/oracle-vps.md` has alt-region recovery steps.

### 2.3 Capture the public IP

Instance detail page → **Public IPv4 Address**. **Write it down — this is `VM_IP`.**

### 2.4 Open the firewall

Left rail → **Networking → Virtual cloud networks → your VCN → Default security list → Add ingress rules**:

| Source CIDR | Protocol | Destination port |
|---|---|---|
| `0.0.0.0/0` | TCP | 22 |
| `0.0.0.0/0` | TCP | 80 |
| `0.0.0.0/0` | TCP | 443 |

### 2.5 Verify SSH works

```bash
ssh ubuntu@<VM_IP>
# Type "yes" to accept the host key on first connect.
# You should land at a `ubuntu@lumen-prod:~$` prompt.
exit
```

🛑 Ping Claude with: "VM up at `<VM_IP>`, SSH works." No code change needed yet — but capturing it tells Claude you're ready for Step 3.

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

### 3.2 SSH into the VM and run the bootstrap script

```bash
ssh ubuntu@<VM_IP>

# Pull the bootstrap script from the branch you're about to deploy.
# (Branch is claude/romantic-mayer-ab2e85, but the script lives on it — we
# fetch via the GitHub raw URL once the branch is pushed, OR we can scp it
# from your laptop. We'll do scp since the branch isn't pushed yet.)

# In a SECOND local terminal (don't close the ssh session):
scp scripts/oracle-bootstrap.sh ubuntu@<VM_IP>:~/

# Back in the ssh session:
chmod +x oracle-bootstrap.sh
sudo ./oracle-bootstrap.sh
```

The script will prompt you for:
- **Admin username** for the new non-root user (default `lumen` — accept).
- **Domain name** for TLS (paste `DOMAIN_NAME` from Step 2.6).
- **Admin email** for Let's Encrypt notifications (your real email).

It will then: install Docker + Compose, harden sshd (key-only auth), enable ufw, install fail2ban. **Idempotent** — re-runnable.

⚠️ **If the script halts with "Refusing to disable password SSH without verified authorized_keys":** that's the M1 guard working as intended. It means your key wasn't found in the expected location. Re-run with `LUMEN_SKIP_SSHD_HARDENING=1 sudo ./oracle-bootstrap.sh` and harden manually after the deploy works.

### 3.3 Verify you can ssh in as the new admin user

```bash
# Open a THIRD terminal — don't close the ubuntu@ session yet.
ssh lumen@<VM_IP>
# Should land at a lumen@lumen-prod:~$ prompt.
```

Once that works, you can close the original `ubuntu@` session.

### 3.4 Clone the repo onto the VM

The branch isn't on GitHub yet (we'll push it in Step 7). So clone via scp:

```bash
# On your LOCAL machine, from the worktree root:
rsync -avz --exclude='.venv' --exclude='node_modules' --exclude='.next' \
  --exclude='.git/objects' --exclude='.playwright-mcp' \
  ./ lumen@<VM_IP>:~/lumen/

# Then ssh in and finish the .git bootstrap:
ssh lumen@<VM_IP>
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

Save + exit.

### 3.6 Boot the stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
# Wait ~60 seconds for Postgres healthcheck + migration container to finish.

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

## Step 5 — Publish the MCP server to the public registry (~10 min, can run in parallel with steps 1–4)

Detailed runbook at `docs/mcp-registry-submission.md`. Short version:

### 5.1 Install `mcp-publisher`

```bash
# On your LOCAL machine (not the VM):
npm install -g @modelcontextprotocol/registry-publisher
mcp-publisher --version
```

### 5.2 Authenticate with GitHub OAuth

```bash
mcp-publisher login github
# Opens browser. Sign in as ahmedEid1 (the namespace owner).
```

### 5.3 Submit the metadata

```bash
# From the worktree root:
mcp-publisher publish apps/backend/app/mcp/registry_metadata.json
```

Expected output: `Published io.github.ahmedeid1/lumen v1.1.0`.

Verify at <https://registry.modelcontextprotocol.io/v0.1/servers/io.github.ahmedeid1/lumen>.

🛑 Ping Claude: "MCP published, listing live at `<MCP_REGISTRY_URL>`." Claude verifies the README badge URL now resolves green (instead of 404).

---

## Step 6 — Record the 90-second Loom (~15 min)

Sign up at <https://www.loom.com> (free tier is fine; 5-min cap per video, 25 videos total).

Install the Loom Chrome extension or desktop app.

### The script (90 seconds, broken into 6 beats — 15 sec each)

1. **Beat 1 (0:00–0:15) — Landing.** Open https://`<DOMAIN_NAME>` in a fresh incognito window. Say: "This is Lumen — an open-source agentic learning platform I built as a portfolio piece. The whole thing runs on $0 of infra."
2. **Beat 2 (0:15–0:30) — Log in + tutor.** Log in as `student@lumen.test`. Open a course. Click into the tutor. Ask: "Explain backpressure in FastAPI."
3. **Beat 3 (0:30–0:45) — Agent reasoning.** When the answer renders, click the **AgentReasoningPanel** expander. Say: "The tutor is a multi-agent orchestrator — planner, retriever, web-searcher, code-runner, quiz-gen, concept-explainer. You can see which tools fired and what each returned."
4. **Beat 4 (0:45–1:00) — Trace surface.** Navigate to `/dashboard/tutor/<conversationId>/turn/<messageId>`. Say: "Every turn writes an observable trace — token usage, cost, retrieval audit, the planner's decisions."
5. **Beat 5 (1:00–1:15) — Self-critique authoring.** Switch to teacher login (`teacher@lumen.test`). Open Studio → click into the seeded `AI Tutor Design Patterns` draft → click Replay. Say: "Authoring uses a self-critique loop — researcher → outliner → critic → reviser. Every step is recorded for replay."
6. **Beat 6 (1:15–1:30) — Wrap.** Switch to admin (`admin@lumen.test`) → `/admin/observability`. Say: "And it all flows through a cost meter with per-user budget guards — production-grade observability from day one. The full source is on GitHub, MCP server is in the public registry, eval suite is open."

End the recording. Copy the share URL.

🛑 Ping Claude with the Loom URL. Claude pastes it into the `LOOM_URL_TBD` placeholder in `README.md`.

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

- **Oracle approval stuck >24h:** open a [support ticket](https://support.oracle.com/portal/) citing your tenancy slug. Or sign up again with a different email + a less-saturated region.
- **A1 capacity unavailable for weeks:** Stockholm is usually fine, but if not, try `ap-mumbai-1` or `sa-vinhedo-1`. Latency hurts the demo but the portfolio still works.
- **Groq rate-limit during eval:** free tier is 30 req/min on Llama 3.3 70B. The eval runner respects this; if it errors, re-run — it resumes from the report's last line.
- **Caddy TLS won't issue:** check `docker compose logs proxy`; the most common cause is DNS not propagated yet. `dig <DOMAIN_NAME>` from the VM should return its own IP.
- **`make publish-rewrite` says "no commits to push":** you're on the wrong local branch. `git checkout Rewrite` first.

---

## Where Claude takes over (the 🛑 moments)

1. After Step 2 — Claude doesn't need to do anything but acknowledges the VM is up.
2. After Step 3.7 — Claude updates `LIVE_DEMO_URL_TBD` → real URL in README + commits.
3. After Step 4 — Claude updates the tutor-eval badge in README + commits the report JSONL.
4. After Step 5 — Claude verifies the MCP badge URL resolves.
5. After Step 6 — Claude pastes Loom URL into `LOOM_URL_TBD` + commits.
6. After Step 7 — Claude logs the PR URL for the session record.

After all 6, the README has zero placeholders, the demo is live, the MCP server is publicly listed, and the PR is open. **That is the "ready to apply" state.**
