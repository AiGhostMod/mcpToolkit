using './main.bicep'

param location = 'swedencentral'
param namePrefix = 'simple-mcp-server'

param resourceGroupName = 'rg-simple-mcp-server'
param logAnalyticsWorkspaceName = 'simple-mcp-server-law'
param containerAppsEnvironmentName = 'simple-mcp-server-env'
param containerAppName = 'simple-mcp-server'
param userAssignedIdentityName = 'simple-mcp-server-pull'

// Azure Container Registry names must be globally unique, 5-50 characters, and alphanumeric only.
param acrName = 'simplemcpserver12345'

param containerRegistrySku = 'Basic'
param acrAdminEnabled = false
param logAnalyticsRetentionInDays = 30

// Leave this false for the first deployment if the image has not been pushed to ACR yet.
param deployContainerApp = false

param imageRepository = 'simple-mcp-server'
param imageTag = '1.1.0'

param ingressExternal = true
param targetPort = 8080
param cpu = '0.5'
param memory = '1.0Gi'
param minReplicas = 1
param maxReplicas = 2

param containerAppEnvironmentVariables = {
  MCP_HISTORY_SIZE: '10'
  MCP_DASHBOARD_ENABLED: 'false'
  MCP_COMPAT_PATHS_ENABLED: 'true'
}

param tags = {
  environment: 'dev'
  project: 'mcpStandalone'
}
