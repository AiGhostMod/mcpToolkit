# MCP Toolbox - Advanced Guide

MCP Toolbox is a standalone MCP troubleshooting server for **testing, diagnostics, request inspection, network probing, and runtime introspection**. It is designed for lab, dev, and troubleshooting scenarios where you want to see exactly what an MCP client sent and how the server received it.

Looking for the shorter getting-started version? See [README.md](./README.md).

> [!WARNING]
> **Testing/troubleshooting use only. Use at your own risk.** This service can capture request headers, cookies, auth values, bodies, environment data, and recent call history. If you point real traffic at it, you may expose real tokens, secrets, or sensitive payloads. Keep it in trusted environments and assume anything sent to it may be inspected.

## Project layout

- `server.py` - the FastAPI-based MCP server
- `requirements.txt` - Python dependencies
- `Dockerfile` / `.dockerignore` - container build files
- `compose.yaml` - local Docker Compose run
- `.env.example` - local and quick-deploy defaults
- `scripts/smoke_test.py` - health + MCP validation script
- `scripts/deploy_aca.sh` - quick Azure Container Apps deploy from source with `az containerapp up`
- `scripts/deploy_bicep.sh` - automated Bicep bootstrap/build/push/deploy flow for Azure Container Apps
- `terraform/` - Terraform deployment for Azure Container Apps + ACR
- `bicep/` - Bicep deployment for Azure Container Apps + ACR

## What the app exposes

### HTTP endpoints

| Endpoint | Availability | Purpose |
| --- | --- | --- |
| `GET /healthz` | Always on | Basic health probe with app version. |
| `GET /mcp`, `POST /mcp` | Always on | Canonical MCP discovery and JSON-RPC endpoints. |
| `GET/POST /mcp/mcp`, `GET/POST /v1/mcp` | Always on | Explicit MCP aliases for clients that use variant MCP paths. |
| `GET /dashboard`, `GET /api/calls`, `GET /api/calls/latest`, `GET /api/calls/{call_id}`, `GET /api/runtime` | Only when `MCP_DASHBOARD_ENABLED=true` | HTML/JSON diagnostic views over recent captured traffic and runtime metadata. |
| `GET/POST /` and catch-all GET/POST fallback | Enabled by default (`MCP_COMPAT_PATHS_ENABLED=true`) | Compatibility routes for clients that rewrite or omit the `/mcp` path. |

### Available MCP tools

| Tool | What it does |
| --- | --- |
| `debug_request_context` | Returns a deep snapshot of the inbound HTTP request and MCP payload, including headers, auth values, query params, path, and raw body. This is one of the most sensitive tools in the toolbox. |
| `inspect_request_auth` | Returns auth-related headers, cookies, query params, and decoded JWT content. Helpful for troubleshooting auth flows, but dangerous with real credentials. |
| `inspect_request_headers` | Returns the headers exactly as the app received them. Useful when debugging auth, forwarding, or gateway behavior. |
| `inspect_request_body` | Returns body size, text, base64, and parsed JSON when possible. Useful for seeing what actually reached the app. |
| `inspect_request_summary` | Returns a focused summary of the request, caller, and forwarding chain. Good for quick ingress and proxy debugging. |
| `inspect_mcp_envelope` | Returns the parsed MCP / JSON-RPC envelope for the current request. Useful for protocol troubleshooting. |
| `inspect_recent_calls` | Returns the most recent captured calls plus telemetry. Useful for seeing what has hit the service recently. |
| `inspect_runtime` | Returns runtime, process, version, uptime, and general server metadata. |
| `inspect_routes` | Lists the FastAPI routes and methods the app currently exposes. |
| `inspect_environment` | Returns environment variables, optionally filtered by prefix or specific names. Useful for validating deploy-time configuration. |
| `get_server_info` | Returns server identity, protocol version, route count, uptime, and history settings. |
| `echo_payload` | Echoes back arbitrary payload with timestamp and caller metadata. Useful for seeing exactly how payloads round-trip. |
| `http_probe` | Issues an outbound HTTP request from inside the container and returns status, headers, and body preview. Useful for dependency and egress troubleshooting. |
| `tls_probe` | Attempts a TLS handshake and returns certificate, cipher, and TLS version details. Useful for SSL/TLS debugging. |
| `tcp_probe` | Attempts a TCP connection and returns latency plus local/remote address details. Useful for low-level connectivity testing. |
| `dns_resolve` | Resolves a hostname from inside the container. Useful for checking DNS behavior in Docker or Azure. |
| `decode_jwt` | Decodes a JWT-like token and returns its header, payload, and signature segment. Helpful for non-secret token inspection. |
| `get_caller_ip` | Returns the client IP address as seen by the server. Useful for testing proxies, ingress, and forwarding behavior. |
| `utc_now` | Returns the current UTC timestamp from the running container. Useful for verifying liveness and time drift. |
| `add_numbers` | Adds two numbers and returns the sum. Simple sanity-check tool for MCP call flow. |

## Runtime configuration and feature flags

These are the runtime settings the application itself reads:

| Variable | Default | What it controls | Notes |
| --- | --- | --- | --- |
| `HOST` | `0.0.0.0` | Bind address for the FastAPI server. | Usually leave this alone in containers. |
| `PORT` | `8080` | Listening port for the server. | The Azure and Docker deployment definitions keep this aligned with ingress target port. |
| `MCP_HISTORY_SIZE` | `10` | Number of recent calls kept in rolling in-memory history. | Higher values mean more request data retained in memory. |
| `MCP_DASHBOARD_ENABLED` | `false` | Enables the dashboard and diagnostic HTTP surfaces under `/dashboard` and `/api/*`. | **Sensitive**: turning this on means recent requests, including auth material or tokens, may be visible through HTTP views if real traffic hits the tool. |
| `MCP_COMPAT_PATHS_ENABLED` | `true` | Enables `/` and catch-all GET/POST compatibility routes. | Keep this on for Foundry and other clients that probe alternate paths before settling on `/mcp`. |

The default posture is **MCP + health with compatibility routing enabled**: `/mcp` and `/healthz` stay on, dashboard/runtime HTTP views stay off unless explicitly enabled, and compatibility routing for `/` and alternate paths stays on for client interoperability.

### Local and quick-deploy environment variables

`.env.example` includes the values below because the local workflow and `scripts/deploy_aca.sh` use them:

| Variable | Used by | Purpose |
| --- | --- | --- |
| `HOST` | Local Python | Host bind address. |
| `PORT` | Local Python | App listen port. |
| `HOST_PORT` | Docker Compose | Host port mapped to container port `8080`. |
| `MCP_HISTORY_SIZE` | Local / Compose / ACA quick deploy | Rolling history size. |
| `MCP_DASHBOARD_ENABLED` | Local / Compose / ACA quick deploy | Dashboard and recent-call capture flag. |
| `MCP_COMPAT_PATHS_ENABLED` | Local / Compose / ACA quick deploy | Enables `/` and catch-all compatibility routes for non-standard clients. |
| `APP_NAME` | `deploy_aca.sh` | Container App name for the Azure CLI quick deploy path. |
| `RESOURCE_GROUP` | `deploy_aca.sh` | Resource group name for the Azure CLI quick deploy path. |
| `LOCATION` | `deploy_aca.sh` | Azure region for the quick deploy path. |
| `CONTAINERAPPS_ENVIRONMENT` | `deploy_aca.sh` / `deploy_bicep.sh` | Container Apps environment name for the quick deploy path. |
| `LOG_ANALYTICS_WORKSPACE_NAME` | `deploy_bicep.sh` | Optional explicit Log Analytics workspace name for the Bicep quick deploy path. |
| `USER_ASSIGNED_IDENTITY_NAME` | `deploy_bicep.sh` | Optional explicit pull identity name for the Bicep quick deploy path. |
| `ACR_NAME` | `deploy_bicep.sh` | Optional explicit Azure Container Registry name. If blank, the script derives one from the app settings. |
| `IMAGE_REPOSITORY` | `deploy_bicep.sh` | Container repository name to publish and deploy. |
| `IMAGE_TAG` | `deploy_bicep.sh` | Container image tag to publish and deploy. |
| `INGRESS` | `deploy_aca.sh` | Container App ingress mode, typically `external`. |

### Terraform knobs

The Terraform deployment is parameter-driven so users can easily override naming and sizing choices. The most important variables are:

| Variable | Purpose |
| --- | --- |
| `location` | Azure region for all resources. |
| `name_prefix` | Friendly base name used when generated defaults are acceptable. |
| `resource_group_name` | Explicit resource group name override. |
| `acr_name` | Explicit ACR name override. Must be globally unique and alphanumeric only. |
| `log_analytics_workspace_name` | Explicit Log Analytics workspace name override. |
| `container_apps_environment_name` | Explicit Container Apps environment name override. |
| `container_app_name` | Explicit Container App name override. |
| `user_assigned_identity_name` | Explicit managed identity name override. |
| `container_registry_sku` | ACR SKU (`Basic`, `Standard`, or `Premium`). |
| `acr_admin_enabled` | Whether to enable the ACR admin account. |
| `deploy_container_app` | Bootstrap switch. Set `false` to create ACR + ACA dependencies first, then `true` after the image has been pushed. |
| `image_repository` / `image_tag` | Container image repo and tag the Container App will run. |
| `ingress_external` | Whether the Container App is public. |
| `target_port` | Ingress target port and app `PORT`. |
| `cpu` / `memory` | Container size for Azure Container Apps. |
| `min_replicas` / `max_replicas` | Scaling floor and ceiling. |
| `container_app_environment_variables` | Additional app environment variables. |
| `tags` | Tags applied across the Azure resources. |

Use `terraform/terraform.tfvars.example` as the editable starting point.

### Bicep knobs

The Bicep deployment exposes the same major controls:

| Parameter | Purpose |
| --- | --- |
| `location` | Azure region for all resources. |
| `namePrefix` | Friendly base name used when generated defaults are acceptable. |
| `resourceGroupName` | Explicit resource group name override. |
| `acrName` | Explicit ACR name override. Must be globally unique and alphanumeric only. |
| `logAnalyticsWorkspaceName` | Explicit Log Analytics workspace name override. |
| `containerAppsEnvironmentName` | Explicit Container Apps environment name override. |
| `containerAppName` | Explicit Container App name override. |
| `userAssignedIdentityName` | Explicit managed identity name override. |
| `containerRegistrySku` | ACR SKU (`Basic`, `Standard`, or `Premium`). |
| `acrAdminEnabled` | Whether to enable the ACR admin account. |
| `deployContainerApp` | Bootstrap switch. Set `false` to create ACR + ACA dependencies first, then `true` after the image has been pushed. |
| `imageRepository` / `imageTag` | Container image repo and tag the Container App will run. |
| `ingressExternal` | Whether the Container App is public. |
| `targetPort` | Ingress target port and app `PORT`. |
| `cpu` / `memory` | Container size for Azure Container Apps. |
| `minReplicas` / `maxReplicas` | Scaling floor and ceiling. |
| `containerAppEnvironmentVariables` | Additional app environment variables. |
| `tags` | Tags applied across the Azure resources. |

Use `bicep/main.bicepparam` as the editable starting point.

## Quick start - local Python

```bash
cd /path/to/MCP-Toolbox
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
set -a
source .env
set +a
python server.py
```

Useful local URLs:

- MCP discovery: `http://127.0.0.1:${PORT:-8080}/mcp`
- Health: `http://127.0.0.1:${PORT:-8080}/healthz`
- Dashboard (only when `MCP_DASHBOARD_ENABLED=true`): `http://127.0.0.1:${PORT:-8080}/dashboard`

If you are wiring this into an agent or MCP client locally, use:

- **MCP URL:** `http://127.0.0.1:${PORT:-8080}/mcp`

## Quick start - Docker Compose

```bash
cd /path/to/MCP-Toolbox
cp .env.example .env
docker compose up --build
```

## Smoke test

Run this after the server is up:

```bash
cd /path/to/MCP-Toolbox
python3 scripts/smoke_test.py --base-url http://127.0.0.1:8080
```

The smoke test now expects the safer default (`/dashboard` disabled). If you explicitly enable the dashboard, run:

```bash
python3 scripts/smoke_test.py --base-url http://127.0.0.1:8080 --expect-dashboard-enabled
```

## Azure deployment options

All Azure paths in this repo target **Azure Container Apps**. The Terraform and Bicep methods also provision:

- a resource group
- an Azure Container Registry (ACR)
- a Log Analytics workspace
- a Container Apps environment
- a user-assigned managed identity with `AcrPull`
- the Container App itself

If the image is not already present in ACR, use the bootstrap switch (`deploy_container_app` or `deployContainerApp`) so you can create the infrastructure first, push the image, and then create the Container App cleanly.

> [!TIP]
> If you build locally on Apple Silicon or any non-`linux/amd64` host, use `docker buildx build --platform linux/amd64 --push ...` for Azure Container Apps compatibility. The live validation for this repo used that path.

### Option 1 - Azure CLI quick deploy from source

This is the fastest path if you want a working Container App and do not need ACR-backed infrastructure as code.

Prerequisites:

- Azure CLI
- `containerapp` extension
- `az login`

Deploy:

```bash
cd /path/to/MCP-Toolbox
cp .env.example .env
./scripts/deploy_aca.sh
```

This path uses the variables in `.env` and builds from the current repo source.

After deployment, the MCP URL to give an agent or MCP client is:

- **MCP URL:** `https://<container-app-fqdn>/mcp`

### Option 2 - Terraform deployment

1. Create a working vars file.

   ```bash
   cd /path/to/MCP-Toolbox/terraform
   cp terraform.tfvars.example terraform.tfvars
   ```

2. Edit the names and settings you want.

   The most common edits are:

   - `resource_group_name`
   - `acr_name`
   - `container_app_name`
   - `container_apps_environment_name`
   - `log_analytics_workspace_name`
   - `user_assigned_identity_name`
   - `location`
   - `image_repository`
   - `image_tag`
   - `deploy_container_app`
   - `ingress_external`
   - `cpu`, `memory`, `min_replicas`, `max_replicas`
   - `container_app_environment_variables`

3. Bootstrap the infrastructure.

   If the image does not exist yet, keep `deploy_container_app = false` for the first apply.

   ```bash
   terraform init
   terraform apply
   ```

4. Build and push the image into ACR.

   The most reliable local path is `docker buildx`, which also handles the `linux/amd64` requirement cleanly:

   ```bash
   ACR_NAME="$(terraform output -raw acr_name)"

   az acr login --name "$ACR_NAME"
   docker buildx build \
     --platform linux/amd64 \
     -t "$(terraform output -raw image_reference)" \
     --push \
     ..
   ```

5. Create the Container App.

   Set `deploy_container_app = true`, then re-apply:

   ```bash
   terraform apply
   ```

6. Get the app URL, MCP URL, and smoke test it.

   ```bash
   APP_URL="$(terraform output -raw container_app_url)"
   MCP_URL="${APP_URL}/mcp"
   cd ..
   python3 scripts/smoke_test.py --base-url "$APP_URL"
   ```

   Use this in your agent or MCP client:

   - **MCP URL:** `$MCP_URL`

7. Clean up.

   ```bash
   cd terraform
   terraform destroy
   ```

### Option 3 - Bicep deployment

If you want the lowest-friction Bicep path, use `./scripts/deploy_bicep.sh` as described in [README.md](./README.md). The rest of this section documents the manual Bicep flow and its individual steps.

1. Edit `bicep/main.bicepparam`.

   The most common edits are:

   - `resourceGroupName`
   - `acrName`
   - `containerAppName`
   - `containerAppsEnvironmentName`
   - `logAnalyticsWorkspaceName`
   - `userAssignedIdentityName`
   - `location`
   - `imageRepository`
   - `imageTag`
   - `deployContainerApp`
   - `ingressExternal`
   - `cpu`, `memory`, `minReplicas`, `maxReplicas`
   - `containerAppEnvironmentVariables`

2. Bootstrap the infrastructure.

   If the image does not exist yet, keep `deployContainerApp = false` for the first deployment.

   ```bash
   cd /path/to/MCP-Toolbox
   az deployment sub create \
     --name mcp-bicep-bootstrap \
     --location swedencentral \
     --template-file bicep/main.bicep \
     --parameters bicep/main.bicepparam
   ```

3. Build and push the image into ACR.

   The most reliable local path is `docker buildx`, which also handles the `linux/amd64` requirement cleanly:

   ```bash
   ACR_NAME="$(az deployment sub show \
     --name mcp-bicep-bootstrap \
     --location swedencentral \
     --query properties.outputs.acrName.value \
     --output tsv)"

   IMAGE_REF="$(az deployment sub show \
     --name mcp-bicep-bootstrap \
     --location swedencentral \
    --query properties.outputs.imageReference.value \
    --output tsv)"

   az acr login --name "$ACR_NAME"
   docker buildx build \
     --platform linux/amd64 \
     -t "$IMAGE_REF" \
     --push \
     .
   ```

4. Create the Container App.

   Either update `deployContainerApp = true` in `bicep/main.bicepparam`, or override it on the command line:

   ```bash
   az deployment sub create \
     --name mcp-bicep-app \
     --location swedencentral \
     --template-file bicep/main.bicep \
     --parameters bicep/main.bicepparam \
     --parameters deployContainerApp=true
   ```

5. Get the app URL, MCP URL, and smoke test it.

   ```bash
   RESOURCE_GROUP_NAME="$(az deployment sub show \
     --name mcp-bicep-app \
     --location swedencentral \
     --query properties.outputs.resourceGroupName.value \
     --output tsv)"

   CONTAINER_APP_NAME="$(az deployment sub show \
     --name mcp-bicep-app \
     --location swedencentral \
     --query properties.outputs.containerAppName.value \
     --output tsv)"

   APP_FQDN="$(az containerapp show \
     --resource-group "$RESOURCE_GROUP_NAME" \
     --name "$CONTAINER_APP_NAME" \
     --query properties.configuration.ingress.fqdn \
     --output tsv)"

   MCP_URL="https://$APP_FQDN/mcp"
   python3 scripts/smoke_test.py --base-url "https://$APP_FQDN"
   ```

   Use this in your agent or MCP client:

   - **MCP URL:** `$MCP_URL`

6. Clean up.

   ```bash
   az group delete --name "$RESOURCE_GROUP_NAME" --yes
   ```

### Option 4 - Use an existing container registry and/or existing ACA environment

The Terraform and Bicep assets in this repo are written to create a fresh ACR and a fresh Container Apps environment. If you already have one or both of those resources, the fastest path is to reuse them with Azure CLI.

#### Existing ACR only

If you already have an ACR and just want to push this image into it:

```bash
EXISTING_ACR_NAME="<your-acr-name>"
IMAGE_REPO="simple-mcp-server"
IMAGE_TAG="latest"

az acr login --name "$EXISTING_ACR_NAME"
docker buildx build \
  --platform linux/amd64 \
  -t "${EXISTING_ACR_NAME}.azurecr.io/${IMAGE_REPO}:${IMAGE_TAG}" \
  --push \
  /path/to/MCP-Toolbox
```

#### Existing ACA environment only

If you already have a Container Apps environment and an image in some accessible registry, create the app directly:

```bash
RESOURCE_GROUP_NAME="<existing-resource-group>"
CONTAINERAPPS_ENVIRONMENT="<existing-aca-environment>"
CONTAINER_APP_NAME="mcp-toolbox"
IMAGE_REF="<registry>/<repository>:<tag>"

az containerapp create \
  --resource-group "$RESOURCE_GROUP_NAME" \
  --environment "$CONTAINERAPPS_ENVIRONMENT" \
  --name "$CONTAINER_APP_NAME" \
  --image "$IMAGE_REF" \
  --target-port 8080 \
  --ingress external \
  --env-vars PORT=8080 MCP_HISTORY_SIZE=10 MCP_DASHBOARD_ENABLED=false MCP_COMPAT_PATHS_ENABLED=true
```

#### Existing ACR and existing ACA environment

If you already have both, the remaining steps are:

1. Push the image into your ACR.
2. Ensure the Container App can pull from that ACR. The clean approach is a user-assigned identity with `AcrPull`.
3. Create the Container App with that identity.

Example:

```bash
RESOURCE_GROUP_NAME="<existing-resource-group>"
CONTAINERAPPS_ENVIRONMENT="<existing-aca-environment>"
CONTAINER_APP_NAME="mcp-toolbox"
ACR_NAME="<existing-acr-name>"
IMAGE_REPO="simple-mcp-server"
IMAGE_TAG="latest"
IDENTITY_NAME="mcp-toolbox-pull"

az identity create \
  --resource-group "$RESOURCE_GROUP_NAME" \
  --name "$IDENTITY_NAME"

IDENTITY_ID="$(az identity show \
  --resource-group "$RESOURCE_GROUP_NAME" \
  --name "$IDENTITY_NAME" \
  --query id --output tsv)"

IDENTITY_PRINCIPAL_ID="$(az identity show \
  --resource-group "$RESOURCE_GROUP_NAME" \
  --name "$IDENTITY_NAME" \
  --query principalId --output tsv)"

ACR_ID="$(az acr show --name "$ACR_NAME" --query id --output tsv)"

az role assignment create \
  --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role AcrPull \
  --scope "$ACR_ID"

az acr login --name "$ACR_NAME"
docker buildx build \
  --platform linux/amd64 \
  -t "${ACR_NAME}.azurecr.io/${IMAGE_REPO}:${IMAGE_TAG}" \
  --push \
  /path/to/MCP-Toolbox

az containerapp create \
  --resource-group "$RESOURCE_GROUP_NAME" \
  --environment "$CONTAINERAPPS_ENVIRONMENT" \
  --name "$CONTAINER_APP_NAME" \
  --image "${ACR_NAME}.azurecr.io/${IMAGE_REPO}:${IMAGE_TAG}" \
  --target-port 8080 \
  --ingress external \
  --user-assigned "$IDENTITY_ID" \
  --registry-server "${ACR_NAME}.azurecr.io" \
  --registry-identity "$IDENTITY_ID" \
  --env-vars PORT=8080 MCP_HISTORY_SIZE=10 MCP_DASHBOARD_ENABLED=false MCP_COMPAT_PATHS_ENABLED=true
```

The MCP URL for an agent/client is:

- **MCP URL:** `https://<container-app-fqdn>/mcp`

## Cleanup

Use the cleanup path that matches how you ran MCP Toolbox:

| Scenario | Cleanup |
| --- | --- |
| Local Python | Stop the process and remove `.venv` or `.env` if you no longer need them. |
| Docker Compose | `docker compose down` |
| Azure CLI quick deploy (`deploy_aca.sh`) | `az group delete --name "$RESOURCE_GROUP" --yes` |
| Terraform deployment | `cd terraform && terraform destroy` |
| Bicep deployment | `az group delete --name "$RESOURCE_GROUP_NAME" --yes` |
| Existing shared ACA environment | `az containerapp delete --resource-group "$RESOURCE_GROUP_NAME" --name "$CONTAINER_APP_NAME" --yes` |
| Existing shared ACR + ACA | Delete only the Container App and optional pull identity if those were created just for this tool; avoid deleting shared registries or shared ACA environments unless they were dedicated to MCP Toolbox. |

## Operational notes

- The server keeps recent request history **in memory only**. Restarting the container clears it.
- Dashboard HTTP visibility is controlled by `MCP_DASHBOARD_ENABLED`. It now defaults to `false`, so `/dashboard` and `/api/*` stay off unless you explicitly opt in.
- Non-`/mcp` compatibility routing is controlled by `MCP_COMPAT_PATHS_ENABLED`. It now defaults to `true` so `/` and arbitrary-path fallbacks resolve MCP discovery/JSON-RPC for client interoperability.
- Even with the dashboard disabled, the MCP inspection tools can still surface request metadata such as auth headers, cookies, query parameters, or body content. Avoid sending production traffic or real secrets through this service.
- The app is cloud-agnostic; Azure-specific behavior lives in the deployment assets and `scripts/deploy_aca.sh`, not in the server code itself.
