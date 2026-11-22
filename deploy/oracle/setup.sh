#!/usr/bin/env bash
# Sets up the GoodSAM -> REDCap web app on a fresh Ubuntu VM (Oracle Cloud Always Free, Sydney).
#   curl -fsSL https://raw.githubusercontent.com/jowettsam-create/ETL/main/deploy/oracle/setup.sh -o setup.sh
#   sudo bash setup.sh
# Safe to run again (e.g. to change the web address). To change credentials:
#   sudo rm /etc/goodsam/goodsam.env && sudo bash setup.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/jowettsam-create/ETL.git}"
APP_DIR=/opt/goodsam-etl
CFG_DIR=/etc/goodsam
ENV_FILE="$CFG_DIR/goodsam.env"
COMPOSE_ENV="$CFG_DIR/compose.env"
COMPOSE_FILE="$APP_DIR/deploy/oracle/compose.yaml"

if [ "$(id -u)" -ne 0 ]; then echo "Please run with sudo:  sudo bash setup.sh"; exit 1; fi
export DEBIAN_FRONTEND=noninteractive

echo "== 1/6 Installing Docker and tools =="
apt-get update -y
apt-get install -y ca-certificates curl git iptables-persistent
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sh; fi
systemctl enable --now docker

echo "== 2/6 Swap file (helps small VMs) =="
if ! swapon --show | grep -q '^/swapfile'; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== 3/6 Opening ports 80 and 443 in the VM's own firewall =="
# Oracle's Ubuntu images reject everything except SSH by default.
for port in 80 443; do
  iptables -C INPUT -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null \
    || iptables -I INPUT -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT
done
netfilter-persistent save >/dev/null

echo "== 4/6 Getting the app code =="
if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" pull --ff-only
else git clone --depth 1 "$REPO_URL" "$APP_DIR"; fi

echo "== 5/6 Settings =="
mkdir -p "$CFG_DIR" && chmod 700 "$CFG_DIR"
PUBLIC_IP="$(curl -fsS https://api.ipify.org || curl -fsS https://ifconfig.me || true)"
DEFAULT_SITE="${PUBLIC_IP//./-}.sslip.io"
CURRENT_SITE="$(sed -n 's/^SITE_ADDRESS=//p' "$COMPOSE_ENV" 2>/dev/null || true)"
read -rp "Web address [${CURRENT_SITE:-$DEFAULT_SITE}]: " SITE
SITE="${SITE:-${CURRENT_SITE:-$DEFAULT_SITE}}"
echo "SITE_ADDRESS=$SITE" > "$COMPOSE_ENV"

if [ ! -f "$ENV_FILE" ]; then
  echo "Enter the credentials (typing is hidden for secrets). They're stored only on this server, in $ENV_FILE."
  read -rp  "GoodSAM username / API client ID: " GS_USER
  read -rsp "GoodSAM password / API client secret: " GS_PASS; echo
  read -rsp "REDCap API token: " RC_TOKEN; echo
  APP_PW=""
  while [ -z "$APP_PW" ]; do read -rsp "App password (what users type to get in; required): " APP_PW; echo; done
  umask 077
  cat > "$ENV_FILE" <<ENV
GOODSAM_USERNAME=$GS_USER
GOODSAM_PASSWORD=$GS_PASS
REDCAP_API_URL=https://nswa-redcap.ambulance.nsw.gov.au/redcap/api/
REDCAP_API_TOKEN=$RC_TOKEN
APP_PASSWORD=$APP_PW
GOODSAM_SHARED=1
ENV
  chmod 600 "$ENV_FILE"
else
  echo "Using existing credentials in $ENV_FILE"
fi

echo "== 6/6 Building and starting (first time takes a few minutes) =="
docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" up -d --build

echo
echo "Done. Open:  https://$SITE"
echo "(The HTTPS certificate can take a minute on first start.)"
echo "Then use 🔧 Connection check in the sidebar to confirm REDCap and GoodSAM are reachable."
echo "To update later:  sudo bash $APP_DIR/deploy/oracle/update.sh"
