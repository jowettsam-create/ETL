#!/usr/bin/env bash
# Pulls the latest app from GitHub (main) and restarts it.  Usage: sudo bash update.sh
set -euo pipefail
APP_DIR=/opt/goodsam-etl
git -C "$APP_DIR" pull --ff-only
docker compose --env-file /etc/goodsam/compose.env -f "$APP_DIR/deploy/oracle/compose.yaml" up -d --build
docker image prune -f >/dev/null
echo "Updated. Check the version number on the page."
