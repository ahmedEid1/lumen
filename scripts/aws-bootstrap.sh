#!/usr/bin/env bash
# ============================================================================
# scripts/aws-bootstrap.sh — idempotent first-boot setup for a fresh
# AWS EC2 t4g.small VM (Ubuntu 24.04 LTS, ARM64 / Graviton2).
#
# Mirrors steps 3 + 4 of docs/deployment/aws-vps.md, plus a non-destructive
# nudge toward steps 6/7. Re-running it is safe — every block checks state
# before mutating.
#
# Usage (as root, via sudo):
#   curl -fsSL https://raw.githubusercontent.com/ahmedEid1/lumen/main/scripts/aws-bootstrap.sh -o bootstrap.sh
#   chmod +x bootstrap.sh
#   sudo ./bootstrap.sh
#
# The script prompts (once) for:
#   - the admin Linux username to create (default: lumen)
#   - the public domain the demo will live at (e.g. lumen.example.com)
#   - the admin email Let's Encrypt should contact for cert-expiry warnings
#
# It does NOT clone the repo, write .env.production, or boot the compose
# stack — those are deliberate manual steps so secrets aren't auto-generated
# into the wrong place. The script prints the exact next commands at the
# end.
#
# Differences from the retired oracle-bootstrap.sh:
#   - Creates a 4 GB swapfile (t4g.small only has 2 GB RAM; Lumen needs
#     headroom for Celery + Postgres bursts).
#   - Detects EC2 user (ubuntu@) — same as Oracle's Ubuntu image, but
#     SSH key delivery is via the EC2 keypair, not console paste.
#   - No A1.Flex shape-config check; the AMI guarantees aarch64.
# ============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Preconditions
# -----------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: run as root (sudo $0)" >&2
  exit 1
fi

if ! grep -q "Ubuntu 24" /etc/os-release; then
  echo "WARNING: this script is tested on Ubuntu 24.04. Detected:" >&2
  grep PRETTY_NAME /etc/os-release >&2
  if [[ "${LUMEN_BOOTSTRAP_NONINTERACTIVE:-0}" != "1" ]]; then
    read -r -p "Continue anyway? [y/N] " ok
    [[ "$ok" =~ ^[Yy]$ ]] || exit 1
  fi
fi

ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" ]]; then
  echo "WARNING: expected ARM64 (aarch64) — detected $ARCH." >&2
  echo "t4g.small is Graviton2 (ARM). x86_64 means you picked the wrong instance type." >&2
  if [[ "${LUMEN_BOOTSTRAP_NONINTERACTIVE:-0}" != "1" ]]; then
    read -r -p "Continue anyway? [y/N] " ok
    [[ "$ok" =~ ^[Yy]$ ]] || exit 1
  fi
fi

# -----------------------------------------------------------------------------
# Inputs — interactive prompts by default, or env-var driven if
# LUMEN_BOOTSTRAP_NONINTERACTIVE=1 is set (used by Terraform / CI / Claude).
# Required env vars in non-interactive mode: ADMIN_USER, APP_DOMAIN, ADMIN_EMAIL.
# -----------------------------------------------------------------------------
if [[ "${LUMEN_BOOTSTRAP_NONINTERACTIVE:-0}" == "1" ]]; then
  [[ -n "${ADMIN_USER:-}" ]]  || { echo "ADMIN_USER env var required in non-interactive mode" >&2; exit 1; }
  [[ -n "${APP_DOMAIN:-}" ]]  || { echo "APP_DOMAIN env var required in non-interactive mode" >&2; exit 1; }
  [[ -n "${ADMIN_EMAIL:-}" ]] || { echo "ADMIN_EMAIL env var required in non-interactive mode" >&2; exit 1; }
  echo "==> non-interactive mode: ADMIN_USER=$ADMIN_USER, APP_DOMAIN=$APP_DOMAIN, ADMIN_EMAIL=$ADMIN_EMAIL"
else
  read -r -p "Admin Linux user to create [lumen]: " ADMIN_USER
  ADMIN_USER="${ADMIN_USER:-lumen}"

  read -r -p "Public domain for the demo (e.g. lumen.example.com): " APP_DOMAIN
  [[ -n "$APP_DOMAIN" ]] || { echo "domain is required" >&2; exit 1; }

  read -r -p "Admin email for Let's Encrypt expiry notices: " ADMIN_EMAIL
  [[ -n "$ADMIN_EMAIL" ]] || { echo "email is required" >&2; exit 1; }

  echo
  echo "==> About to bootstrap with:"
  echo "    admin user : $ADMIN_USER"
  echo "    domain     : $APP_DOMAIN"
  echo "    email      : $ADMIN_EMAIL"
  read -r -p "OK? [y/N] " ok
  [[ "$ok" =~ ^[Yy]$ ]] || { echo "aborted"; exit 1; }
fi

# -----------------------------------------------------------------------------
# Block A — 4 GB swap file (t4g.small only has 2 GB RAM; Postgres + Celery
# bursts blow past it under tutor load). Idempotent.
# -----------------------------------------------------------------------------
SWAPFILE=/swapfile
if swapon --show=NAME --noheadings | grep -qx "$SWAPFILE"; then
  echo "==> swap already enabled on $SWAPFILE, skipping"
else
  echo "==> creating 4 GB swap file at $SWAPFILE"
  if [[ ! -f $SWAPFILE ]]; then
    fallocate -l 4G "$SWAPFILE" || dd if=/dev/zero of="$SWAPFILE" bs=1M count=4096
  fi
  chmod 600 "$SWAPFILE"
  mkswap "$SWAPFILE"
  swapon "$SWAPFILE"
  if ! grep -q "$SWAPFILE" /etc/fstab; then
    echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
  fi
  # tune for low-RAM box: don't swap unless we have to
  sysctl -w vm.swappiness=10 >/dev/null
  sysctl -w vm.vfs_cache_pressure=50 >/dev/null
  cat >/etc/sysctl.d/99-lumen-low-ram.conf <<EOF
vm.swappiness=10
vm.vfs_cache_pressure=50
EOF
fi

# -----------------------------------------------------------------------------
# Block 3a — non-root admin user with the same authorized_keys as ubuntu@
# -----------------------------------------------------------------------------
if id "$ADMIN_USER" &>/dev/null; then
  echo "==> user $ADMIN_USER already exists, skipping creation"
else
  echo "==> creating user $ADMIN_USER"
  adduser --disabled-password --gecos "" "$ADMIN_USER"
  usermod -aG sudo "$ADMIN_USER"
fi

# copy ssh keys from the invoking sudoer (or from /home/ubuntu — the default
# EC2 user for Canonical Ubuntu AMIs)
SRC_KEYS=""
if [[ -n "${SUDO_USER:-}" && -f "/home/$SUDO_USER/.ssh/authorized_keys" ]]; then
  SRC_KEYS="/home/$SUDO_USER/.ssh/authorized_keys"
elif [[ -f /home/ubuntu/.ssh/authorized_keys ]]; then
  SRC_KEYS=/home/ubuntu/.ssh/authorized_keys
elif [[ -f /root/.ssh/authorized_keys ]]; then
  SRC_KEYS=/root/.ssh/authorized_keys
fi

ADMIN_AUTH_KEYS="/home/$ADMIN_USER/.ssh/authorized_keys"
if [[ -n "$SRC_KEYS" ]]; then
  install -d -m 700 -o "$ADMIN_USER" -g "$ADMIN_USER" "/home/$ADMIN_USER/.ssh"
  install -m 600 -o "$ADMIN_USER" -g "$ADMIN_USER" "$SRC_KEYS" "$ADMIN_AUTH_KEYS"
  echo "==> copied authorized_keys from $SRC_KEYS"
elif [[ -s "$ADMIN_AUTH_KEYS" ]]; then
  echo "==> $ADMIN_AUTH_KEYS already populated, leaving as-is"
else
  echo "WARNING: no source authorized_keys found — populate $ADMIN_AUTH_KEYS manually before disabling password ssh!" >&2
fi

# -----------------------------------------------------------------------------
# Block 3b — sshd: disable password + root login
# -----------------------------------------------------------------------------
if [[ "${LUMEN_SKIP_SSHD_HARDENING:-0}" == "1" ]]; then
  echo "WARNING: LUMEN_SKIP_SSHD_HARDENING=1 set — skipping sshd hardening." >&2
  echo "         You MUST disable PasswordAuthentication and PermitRootLogin manually" >&2
  echo "         before exposing this VM to the internet. See runbook step 3b:" >&2
  echo "         docs/deployment/aws-vps.md" >&2
elif [[ ! -s "$ADMIN_AUTH_KEYS" ]]; then
  cat >&2 <<EOF
ERROR: Refusing to disable password SSH without a verified \`authorized_keys\`.
       You would lose access to this VM.

       No key was found at: $ADMIN_AUTH_KEYS
       (and no source key was discovered at \$SUDO_USER's home, /home/ubuntu,
       or /root).

To recover, either:
  (a) Add a public key to $ADMIN_AUTH_KEYS for $ADMIN_USER
      (chmod 700 the .ssh dir, chmod 600 the file, chown to $ADMIN_USER),
      then re-run this script — it will detect the staged key and proceed.
  (b) Skip sshd hardening on THIS run and harden manually afterwards:
        LUMEN_SKIP_SSHD_HARDENING=1 sudo bash scripts/aws-bootstrap.sh
      (NOT recommended for internet-exposed VMs.)

See runbook step 3 / sub-block 3b in docs/deployment/aws-vps.md for the
manual hardening commands.
EOF
  exit 1
else
  echo "==> hardening sshd"
  sshd_config=/etc/ssh/sshd_config
  cp "$sshd_config" "${sshd_config}.bak.$(date +%s)"
  sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "$sshd_config"
  sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' "$sshd_config"
  sed -i 's/^#\?KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' "$sshd_config"
  # `sshd -t` needs /run/sshd (the privilege-separation chroot). It's
  # normally created by the systemd unit's RuntimeDirectory= directive,
  # but during cloud-init's user_data we may run before that fires, so
  # create it explicitly. Idempotent.
  mkdir -p /run/sshd
  sshd -t   # bail if the edits broke the config
  systemctl restart ssh
fi

# -----------------------------------------------------------------------------
# Block 3c — ufw + fail2ban
# Default fail2ban sshd jail bans after 5 failed auths in 10m for 10m. That's
# too aggressive for an automated deploy that opens many short SSH connections
# in quick succession (rsync + scp + iterative deploy commands). We relax to
# 20 retries / 5m findtime / 5m bantime — still protects against brute-force,
# stops eating our own deploy traffic. Use SSH connection multiplexing
# (ControlMaster) on the client side to stay polite anyway.
# -----------------------------------------------------------------------------
echo "==> installing ufw + fail2ban"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ufw fail2ban
ufw --force default deny incoming
ufw --force default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

mkdir -p /etc/fail2ban/jail.d
cat >/etc/fail2ban/jail.d/sshd-relaxed.local <<'EOF'
# Deploy-friendly sshd jail. Still protects against credential-stuffing
# (20 failed auths in 5 minutes is well past anything automated), but no
# longer bans bursty deploy traffic that opens many short connections.
[sshd]
enabled  = true
findtime = 5m
maxretry = 20
bantime  = 5m
EOF
systemctl enable --now fail2ban
systemctl reload fail2ban || systemctl restart fail2ban

# -----------------------------------------------------------------------------
# Block 4 — Docker Engine + Compose v2 plugin (ARM64)
# -----------------------------------------------------------------------------
if command -v docker &>/dev/null && docker compose version &>/dev/null; then
  echo "==> docker + compose v2 already installed, skipping"
else
  echo "==> installing Docker Engine + Compose plugin via get.docker.com"
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh
  rm -f /tmp/get-docker.sh
fi
usermod -aG docker "$ADMIN_USER"
systemctl enable --now docker

# -----------------------------------------------------------------------------
# Block 5 — install repo prereqs
# -----------------------------------------------------------------------------
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git make jq openssl

# -----------------------------------------------------------------------------
# Block 7 — drop the chosen domain + LE email into /etc/lumen-deploy/deploy.env
# so the operator can `source` it when filling .env.production
# -----------------------------------------------------------------------------
install -d -m 750 -o "$ADMIN_USER" -g "$ADMIN_USER" /etc/lumen-deploy
cat >/etc/lumen-deploy/deploy.env <<EOF
# Generated by aws-bootstrap.sh — used by Caddy ({\$APP_DOMAIN}) and the
# H6 prod-boot guard. Mirror these into your .env.production.
APP_DOMAIN=$APP_DOMAIN
ACME_EMAIL=$ADMIN_EMAIL
EOF
chown "$ADMIN_USER:$ADMIN_USER" /etc/lumen-deploy/deploy.env
chmod 640 /etc/lumen-deploy/deploy.env

# -----------------------------------------------------------------------------
# Done — print next steps
# -----------------------------------------------------------------------------
PUBLIC_IP="$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 || curl -s ifconfig.me || echo '<your-elastic-ip>')"
cat <<EOF

============================================================================
Bootstrap complete.

Memory snapshot (t4g.small budget — keep an eye on this):
$(free -h | awk 'NR==1 || NR==2 || NR==3')

Next (as $ADMIN_USER — log out and back in so docker group takes effect):

  ssh $ADMIN_USER@$PUBLIC_IP
  git clone https://github.com/ahmedEid1/lumen.git lumen
  cd lumen
  cp .env.example .env.production
  # Source the values this script just generated so APP_DOMAIN +
  # ACME_EMAIL are in your shell while you edit .env.production:
  source /etc/lumen-deploy/deploy.env
  # edit .env.production — see Step 5 of docs/deployment/aws-vps.md
  # APP_DOMAIN should be: $APP_DOMAIN

  docker compose -f docker-compose.prod.yml --env-file .env.production pull
  docker compose -f docker-compose.prod.yml --env-file .env.production up -d
  docker compose -f docker-compose.prod.yml exec api alembic upgrade head
  docker compose -f docker-compose.prod.yml exec api python -m app.cli seed
  # Optional — adds 3 extra browse-only courses on top of the curated
  # multi-agent tutor demo that 'seed' already lays down:
  #   docker compose -f docker-compose.prod.yml exec api python -m app.cli demo-seed

Then point an A record for $APP_DOMAIN at this VM's Elastic IP and Caddy
will obtain the Let's Encrypt cert on the first HTTPS request.

Full runbook: docs/deployment/aws-vps.md
============================================================================
EOF
