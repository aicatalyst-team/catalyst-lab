#!/usr/bin/env bash
# export-grafana-dashboard.sh -- Export Grafana dashboard JSON for version control
#
# Exports the "AI Catalyst Lab Overview" dashboard from Grafana and saves it
# to grafana/catalyst-lab-overview.json for reproducibility.
#
# Usage:
#   # Option 1: Port-forward to Grafana, then export
#   kubectl port-forward -n monitoring svc/grafana 3000:3000 &
#   ./scripts/export-grafana-dashboard.sh
#
#   # Option 2: Use ingress URL
#   GRAFANA_URL=http://grafana.<INGRESS_IP>.nip.io ./scripts/export-grafana-dashboard.sh
#
# To import the dashboard back:
#   curl -X POST "$GRAFANA_URL/api/dashboards/db" \
#     -H "Content-Type: application/json" \
#     -d @grafana/catalyst-lab-overview.json
#
set -euo pipefail

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
DASHBOARD_UID="catalyst-lab-overview"
OUTPUT_FILE="grafana/catalyst-lab-overview.json"

echo "Exporting dashboard '${DASHBOARD_UID}' from ${GRAFANA_URL}..."

# Fetch the dashboard
response=$(curl -s -w "\n%{http_code}" "${GRAFANA_URL}/api/dashboards/uid/${DASHBOARD_UID}")
http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
  echo "Error: Grafana returned HTTP ${http_code}"
  echo "$body" | head -5
  exit 1
fi

# Save the full response (includes dashboard + meta)
# Wrap it for re-import: need {"dashboard": ..., "overwrite": true}
echo "$body" | python3 -c "
import sys, json
data = json.load(sys.stdin)
dashboard = data.get('dashboard', data)
# Remove runtime fields that change on each save
dashboard.pop('id', None)
dashboard.pop('version', None)
# Keep the uid for deterministic URLs
export = {
    'dashboard': dashboard,
    'overwrite': True,
    'folderId': 0
}
json.dump(export, sys.stdout, indent=2)
print()
" > "${OUTPUT_FILE}"

echo "Saved to ${OUTPUT_FILE}"
echo "Dashboard UID: ${DASHBOARD_UID}"
echo ""
echo "To import on another Grafana instance:"
echo "  curl -X POST \"\$GRAFANA_URL/api/dashboards/db\" \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d @${OUTPUT_FILE}"
