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

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

sanitize_alnum() {
  printf '%s' "$1" | tr -cd '[:alnum:]'
}

default_acr_name() {
  local base hash max_base_len
  base="$(lower "$(sanitize_alnum "${APP_NAME}")")"
  if [[ -z "${base}" ]]; then
    base="mcptoolbox"
  fi

  hash="$(printf '%s' "${RESOURCE_GROUP}:${LOCATION}:${APP_NAME}" | shasum -a 256 | cut -c1-6)"
  max_base_len=$((50 - ${#hash}))
  base="${base:0:${max_base_len}}"

  if [[ ${#base} -lt 5 ]]; then
    base="$(printf '%-5s' "${base}" | tr ' ' '0')"
  fi

  printf '%s%s' "${base}" "${hash}"
}

APP_NAME="${APP_NAME:-mcp-standalone}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-${APP_NAME}}"
LOCATION="${LOCATION:-swedencentral}"
CONTAINERAPPS_ENVIRONMENT="${CONTAINERAPPS_ENVIRONMENT:-${APP_NAME}-env}"
LOG_ANALYTICS_WORKSPACE_NAME="${LOG_ANALYTICS_WORKSPACE_NAME:-${APP_NAME}-law}"
USER_ASSIGNED_IDENTITY_NAME="${USER_ASSIGNED_IDENTITY_NAME:-${APP_NAME}-pull}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-simple-mcp-server}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
MCP_HISTORY_SIZE="${MCP_HISTORY_SIZE:-10}"
MCP_DASHBOARD_ENABLED="${MCP_DASHBOARD_ENABLED:-false}"
MCP_COMPAT_PATHS_ENABLED="${MCP_COMPAT_PATHS_ENABLED:-true}"
ACR_NAME="$(lower "${ACR_NAME:-$(default_acr_name)}")"

if [[ ! "${ACR_NAME}" =~ ^[a-z0-9]{5,50}$ ]]; then
  echo "ACR_NAME must be 5-50 lowercase alphanumeric characters." >&2
  exit 1
fi

ENV_VARS_JSON="$(printf '{"MCP_HISTORY_SIZE":"%s","MCP_DASHBOARD_ENABLED":"%s","MCP_COMPAT_PATHS_ENABLED":"%s"}' \
  "${MCP_HISTORY_SIZE}" \
  "${MCP_DASHBOARD_ENABLED}" \
  "${MCP_COMPAT_PATHS_ENABLED}")"

DEPLOYMENT_SUFFIX="$(date +%m%d%H%M%S)"
BOOTSTRAP_NAME="mcp-bicep-bootstrap-${DEPLOYMENT_SUFFIX}"
APP_DEPLOY_NAME="mcp-bicep-app-${DEPLOYMENT_SUFFIX}"

az account show >/dev/null
az extension add --name containerapp --upgrade --only-show-errors >/dev/null

echo "Deploying MCP Toolbox with Bicep"
echo "  App name: ${APP_NAME}"
echo "  Resource group: ${RESOURCE_GROUP}"
echo "  Location: ${LOCATION}"
echo "  ACR: ${ACR_NAME}"

az deployment sub create \
  --name "${BOOTSTRAP_NAME}" \
  --location "${LOCATION}" \
  --template-file "${PROJECT_DIR}/bicep/main.bicep" \
  --parameters "${PROJECT_DIR}/bicep/main.bicepparam" \
  --parameters \
    location="${LOCATION}" \
    resourceGroupName="${RESOURCE_GROUP}" \
    acrName="${ACR_NAME}" \
    containerAppName="${APP_NAME}" \
    containerAppsEnvironmentName="${CONTAINERAPPS_ENVIRONMENT}" \
    logAnalyticsWorkspaceName="${LOG_ANALYTICS_WORKSPACE_NAME}" \
    userAssignedIdentityName="${USER_ASSIGNED_IDENTITY_NAME}" \
    imageRepository="${IMAGE_REPOSITORY}" \
    imageTag="${IMAGE_TAG}" \
    containerAppEnvironmentVariables="${ENV_VARS_JSON}" \
    deployContainerApp=false \
  >/dev/null

IMAGE_REF="$(az deployment sub show \
  --name "${BOOTSTRAP_NAME}" \
  --query properties.outputs.imageReference.value \
  --output tsv)"

for attempt in 1 2 3 4 5 6; do
  if az acr login --name "${ACR_NAME}" >/dev/null 2>&1; then
    break
  fi

  if [[ "${attempt}" -eq 6 ]]; then
    echo "ACR '${ACR_NAME}' was not ready for docker login in time." >&2
    exit 1
  fi

  echo "Waiting for ACR '${ACR_NAME}' to become ready..."
  sleep 10
done

docker buildx build \
  --platform linux/amd64 \
  -t "${IMAGE_REF}" \
  --push \
  "${PROJECT_DIR}"

az deployment sub create \
  --name "${APP_DEPLOY_NAME}" \
  --location "${LOCATION}" \
  --template-file "${PROJECT_DIR}/bicep/main.bicep" \
  --parameters "${PROJECT_DIR}/bicep/main.bicepparam" \
  --parameters \
    location="${LOCATION}" \
    resourceGroupName="${RESOURCE_GROUP}" \
    acrName="${ACR_NAME}" \
    containerAppName="${APP_NAME}" \
    containerAppsEnvironmentName="${CONTAINERAPPS_ENVIRONMENT}" \
    logAnalyticsWorkspaceName="${LOG_ANALYTICS_WORKSPACE_NAME}" \
    userAssignedIdentityName="${USER_ASSIGNED_IDENTITY_NAME}" \
    imageRepository="${IMAGE_REPOSITORY}" \
    imageTag="${IMAGE_TAG}" \
    containerAppEnvironmentVariables="${ENV_VARS_JSON}" \
    deployContainerApp=true \
  >/dev/null

APP_FQDN="$(az containerapp show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${APP_NAME}" \
  --query properties.configuration.ingress.fqdn \
  --output tsv)"

python3 "${PROJECT_DIR}/scripts/smoke_test.py" --base-url "https://${APP_FQDN}"

echo
echo "Deployment complete."
echo "Resource group: ${RESOURCE_GROUP}"
echo "Container App: ${APP_NAME}"
echo "MCP URL: https://${APP_FQDN}/mcp"
