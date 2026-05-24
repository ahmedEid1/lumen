#!/usr/bin/env bash
# ============================================================================
# scripts/oracle-bootstrap.sh — idempotent first-boot setup for a fresh
# Oracle Cloud Always-Free Ampere A1 VM (Ubuntu 24.04 LTS, ARM64).
#
# Mirrors steps 3 + 4 of docs/deployment/oracle-vps.md (plus a non-destructive
# nudge towards step 6/7). Re-running it is safe — every block checks state
# before mutating.
#
# Usage (as root, via sudo):
#   curl -fsSL https://raw.githubusercontent.com/ahmedEid1/E-Learning-Platform/master/scripts/oracle-bootstrap.sh -o bootstrap.sh
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
  read -r -p "Continue anyway? [y/N] " ok
  [[ "$ok" =~ ^[Yy]$ ]] || exit 1
fi

ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" ]]; then
  echo "WARNING: expected ARM64 (aarch64) — detected $ARCH." >&2
  echo "The Always-Free A1 VM is ARM; x86_64 means you picked the wrong shape." >&2
  read -r -p "Continue anyway? [y/N] " ok
  [[ "$ok" =~ ^[Yy]$ ]] || exit 1
fi

# -----------------------------------------------------------------------------
# Prompts
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Block 3a — non-root admin user with the same authorized_keys as ubuntu@
# (runbook step 3)
# -----------------------------------------------------------------------------
if id "$ADMIN_USER" &>/dev/null; then
  echo "==> user $ADMIN_USER already exists, skipping creation"
else
  echo "==> creating user $ADMIN_USER"
  adduser --disabled-password --gecos "" "$ADMIN_USER"
  usermod -aG sudo "$ADMIN_USER"
fi

# copy ssh keys from the invoking sudoer (or from /home/ubuntu if invoked
# directly as root from cloud-init)
SRC_KEYS=""
if [[ -n "${SUDO_USER:-}" && -f "/home/$SUDO_USER/.ssh/authorized_keys" ]]; then
  SRC_KEYS="/home/$SUDO_USER/.ssh/authorized_keys"
elif [[ -f /home/ubuntu/.ssh/authorized_keys ]]; then
  SRC_KEYS=/home/ubuntu/.ssh/authorized_keys
elif [[ -f /root/.ssh/authorized_keys ]]; then
  SRC_KEYS=/root/.ssh/authorized_keys
fi

if [[ -n "$SRC_KEYS" ]]; then
  install -d -m 700 -o "$ADMIN_USER" -g "$ADMIN_USER" "/home/$ADMIN_USER/.ssh"
  install -m 600 -o "$ADMIN_USER" -g "$ADMIN_USER" "$SRC_KEYS" "/home/$ADMIN_USER/.ssh/authorized_keys"
  echo "==> copied authorized_keys from $SRC_KEYS"
else
  echo "WARNING: no source authorized_keys found — populate /home/$ADMIN_USER/.ssh/authorized_keys manually before disabling password ssh!" >&2
fi

# -----------------------------------------------------------------------------
# Block 3b — sshd: disable password + root login
# (runbook step 3)
# -----------------------------------------------------------------------------
echo "==> hardening sshd"
sshd_config=/etc/ssh/sshd_config
cp "$sshd_config" "${sshd_config}.bak.$(date +%s)"
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "$sshd_config"
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' "$sshd_config"
sed -i 's/^#\?KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' "$sshd_config"
sshd -t   # bail if the edits broke the config
systemctl restart ssh

# -----------------------------------------------------------------------------
# Block 3c — ufw + fail2ban
# (runbook step 3)
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
systemctl enable --now fail2ban

# -----------------------------------------------------------------------------
# Block 4 — Docker Engine + Compose v2 plugin (ARM64)
# (runbook step 4)
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
# (runbook step 5)
# -----------------------------------------------------------------------------
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git make jq openssl

# -----------------------------------------------------------------------------
# Block 7 — drop the chosen domain + LE email into /etc/lumen-deploy.env so
# the operator can `source` it when filling .env.production
# (runbook step 7)
# -----------------------------------------------------------------------------
install -d -m 750 -o "$ADMIN_USER" -g "$ADMIN_USER" /etc/lumen-deploy
cat >/etc/lumen-deploy/deploy.env <<EOF
# Generated by oracle-bootstrap.sh — used by Caddy ({\$APP_DOMAIN}) and the
# H6 prod-boot guard. Mirror these into your .env.production.
APP_DOMAIN=$APP_DOMAIN
ACME_EMAIL=$ADMIN_EMAIL
EOF
chown "$ADMIN_USER:$ADMIN_USER" /etc/lumen-deploy/deploy.env
chmod 640 /etc/lumen-deploy/deploy.env

# -----------------------------------------------------------------------------
# Done — print next steps
# -----------------------------------------------------------------------------
cat <<EOF

============================================================================
Bootstrap complete.

Next (as $ADMIN_USER — log out and back in so docker group takes effect):

  ssh $ADMIN_USER@\$(curl -s ifconfig.me)
  git clone https://github.com/ahmedEid1/E-Learning-Platform.git lumen
  cd lumen
  cp .env.example .env.production
  # edit .env.production — see Step 5 of docs/deployment/oracle-vps.md
  # APP_DOMAIN should be: $APP_DOMAIN

  docker compose -f docker-compose.prod.yml --env-file .env.production pull
  docker compose -f docker-compose.prod.yml --env-file .env.production up -d
  docker compose -f docker-compose.prod.yml exec api alembic upgrade head
  docker compose -f docker-compose.prod.yml exec api python -m app.cli seed
  docker compose -f docker-compose.prod.yml exec api python -m app.cli demo-seed

Then point an A record for $APP_DOMAIN at this VM's public IP and Caddy
will obtain the Let's Encrypt cert on the first HTTPS request.

Full runbook: docs/deployment/oracle-vps.md
============================================================================
EOF
