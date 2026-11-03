#!/usr/bin/env bash
# One-command deploy for the Reckon Sales Agent site. Pulls the Sales Agent and reckon_crm apps, migrates, builds every
# app's assets (this includes reckon_crm's /crm frontend), clears the cache, restarts, and checks the /crm build is live.
#
#   BENCH_DIR=/home/reckon/frappe-bench SITE=distribution.reckon.tech ./scripts/deploy.sh
#
# Stops at the first problem, with a message that says what to fix.
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-$HOME/frappe-bench}"
SITE="${SITE:-distribution.reckon.tech}"

fail() { echo "DEPLOY STOPPED: $1" >&2; exit 1; }

cd "$BENCH_DIR" || fail "BENCH_DIR $BENCH_DIR does not exist."

# Preflight: both apps must be in the bench, and the CRM frontend must be installed for the reckon_crm build.
[ -d apps/reckon_sales_agent ] || fail "apps/reckon_sales_agent is missing from the bench."
[ -d apps/reckon_crm ] || fail "apps/reckon_crm is missing. Run: bench get-app <reckon_crm repo URL>, then bench --site $SITE install-app reckon_crm"
[ -d apps/crm/frontend ] || fail "apps/crm/frontend is missing. Frappe CRM must be installed in this bench (bench get-app crm)."
[ -d apps/crm/frontend/node_modules ] || fail "CRM frontend dependencies are not installed. Run: (cd apps/crm/frontend && npm install), then deploy again."

for app in reckon_sales_agent reckon_crm; do
  echo "Updating $app"
  git -C "apps/$app" pull --ff-only || fail "git pull failed for $app (uncommitted changes or no network)."
done

# reckon_crm must be installed on the site, not just present in the bench, or its /crm override never loads.
if ! bench --site "$SITE" list-apps | grep -q '^reckon_crm'; then
  echo "Installing reckon_crm on $SITE"
  bench --site "$SITE" install-app reckon_crm || fail "install-app reckon_crm failed on $SITE."
fi

echo "Migrating $SITE"
bench --site "$SITE" migrate

# No --app: a full build also builds reckon_crm's /crm frontend.
echo "Building all apps"
bench build || fail "bench build failed. The Reckon CRM build message above says why."

[ -f apps/reckon_crm/reckon_crm/templates/reckon_crm.json ] || fail "The reckon_crm build did not produce its template (reckon_crm.json)."

bench --site "$SITE" clear-cache
echo "Restarting services"
sudo supervisorctl restart all

# Verify the /crm build is served, not just built.
build_id=$(grep -o '"buildId": *"[^"]*"' apps/reckon_crm/reckon_crm/templates/reckon_crm.json | sed 's/.*"\([^"]*\)"$//')
code=$(curl -s -o /dev/null -w "%{http_code}" "https://$SITE/assets/reckon_crm/frontend/$build_id/registerSW.js" || true)
[ "$code" = "200" ] || echo "WARNING: /crm assets returned $code. Check the reckon_crm build output above."

echo "Deployed $SITE"
