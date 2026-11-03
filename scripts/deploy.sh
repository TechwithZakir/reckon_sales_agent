#!/usr/bin/env bash
# One-command deploy for the Reckon Sales Agent site. Pulls the Sales Agent and reckon_crm apps, migrates,
# builds every app's assets (this includes reckon_crm's /crm frontend), clears the cache and restarts.
#
#   BENCH_DIR=/home/reckon/frappe-bench SITE=distribution.reckon.tech ./scripts/deploy.sh
#
# Stops at the first failure, so a broken build never goes live half-done.
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-$HOME/frappe-bench}"
SITE="${SITE:-distribution.reckon.tech}"

cd "$BENCH_DIR"
for app in reckon_sales_agent reckon_crm; do
  if [ -d "apps/$app/.git" ]; then
    echo "Updating $app"
    git -C "apps/$app" pull --ff-only
  fi
done

echo "Migrating $SITE"
bench --site "$SITE" migrate

# No --app: a full build also builds reckon_crm's /crm frontend (it needs apps/crm next to it).
echo "Building all apps"
bench build

bench --site "$SITE" clear-cache
echo "Restarting services"
sudo supervisorctl restart all
echo "Deployed $SITE"
