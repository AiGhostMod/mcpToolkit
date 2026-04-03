#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_DIR}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

APP_NAME="${APP_NAME:-mcp-standalone}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-${APP_NAME}}"
LOCATION="${LOCATION:-swedencentral}"
CONTAINERAPPS_ENVIRONMENT="${CONTAINERAPPS_ENVIRONMENT:-${APP_NAME}-env}"
INGRESS="${INGRESS:-external}"
MCP_HISTORY_SIZE="${MCP_HISTORY_SIZE:-10}"
MCP_DASHBOARD_ENABLED="${MCP_DASHBOARD_ENABLED:-false}"
MCP_COMPAT_PATHS_ENABLED="${MCP_COMPAT_PATHS_ENABLED:-true}"

az account show >/dev/null
az extension add --name containerapp --upgrade --only-show-errors >/dev/null
az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" --only-show-errors >/dev/null

FQDN="$(
  az containerapp up \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --environment "${CONTAINERAPPS_ENVIRONMENT}" \
    --source "${PROJECT_DIR}" \
    --ingress "${INGRESS}" \
    --target-port 8080 \
    --revisions-mode single \
    --env-vars \
      PORT=8080 \
      MCP_HISTORY_SIZE="${MCP_HISTORY_SIZE}" \
      MCP_DASHBOARD_ENABLED="${MCP_DASHBOARD_ENABLED}" \
      MCP_COMPAT_PATHS_ENABLED="${MCP_COMPAT_PATHS_ENABLED}" \
    --query properties.configuration.ingress.fqdn \
    --output tsv
)"

echo "Container App FQDN: ${FQDN}"
echo "MCP URL: https://${FQDN}/mcp"
dashboard_enabled_normalized="$(printf '%s' "${MCP_DASHBOARD_ENABLED}" | tr '[:upper:]' '[:lower:]')"
compat_paths_enabled_normalized="$(printf '%s' "${MCP_COMPAT_PATHS_ENABLED}" | tr '[:upper:]' '[:lower:]')"

if [[ "${dashboard_enabled_normalized}" == "true" ]]; then
  echo "Dashboard URL: https://${FQDN}/dashboard"
else
  echo "Dashboard disabled by default. Set MCP_DASHBOARD_ENABLED=true to enable /dashboard and /api/*."
fi

if [[ "${compat_paths_enabled_normalized}" != "true" ]]; then
  echo "Compatibility routes are disabled for this deployment. Use the explicit MCP endpoint: https://${FQDN}/mcp"
fi
