targetScope = 'subscription'

@description('Azure region for the resource group and all resources.')
param location string = 'swedencentral'

@description('Friendly base name used when explicit resource names are not provided.')
param namePrefix string = 'simple-mcp-server'

@description('Resource group name to create or update.')
param resourceGroupName string = 'rg-simple-mcp-server'

@description('Log Analytics workspace name override.')
param logAnalyticsWorkspaceName string = '${namePrefix}-law'

@description('Container Apps environment name override.')
param containerAppsEnvironmentName string = '${namePrefix}-env'

@description('Container App name override.')
param containerAppName string = namePrefix

@description('User-assigned identity name override.')
param userAssignedIdentityName string = '${namePrefix}-pull'

@description('Azure Container Registry name override. Must be globally unique, 5-50 characters, and alphanumeric only.')
param acrName string = 'simplemcp${substring(uniqueString(subscription().id, resourceGroupName, namePrefix), 0, 6)}'

@allowed([
  'Basic'
  'Standard'
  'Premium'
])
@description('SKU for the Azure Container Registry.')
param containerRegistrySku string = 'Basic'

@description('Whether to enable the ACR admin account.')
param acrAdminEnabled bool = false

@description('Retention period for Log Analytics data.')
param logAnalyticsRetentionInDays int = 30

@description('Set to false to provision the resource group, ACR, and Container Apps environment first, then set to true after the application image has been pushed.')
param deployContainerApp bool = true

@description('Repository name inside ACR for the application image.')
param imageRepository string = 'simple-mcp-server'

@description('Container image tag that the Container App should run.')
param imageTag string = 'latest'

@description('Whether the Container App should have external ingress.')
param ingressExternal bool = true

@description('Container port exposed by the application.')
param targetPort int = 8080

@description('Requested CPU for the Container App workload. Use string values like 0.25, 0.5, or 1.0.')
param cpu string = '0.5'

@description('Requested memory for the Container App workload.')
param memory string = '1.0Gi'

@description('Minimum number of Container App replicas.')
param minReplicas int = 1

@description('Maximum number of Container App replicas.')
param maxReplicas int = 2

@description('Additional environment variables passed into the Container App. PORT is always aligned to targetPort.')
param containerAppEnvironmentVariables object = {
  MCP_HISTORY_SIZE: '10'
  MCP_DASHBOARD_ENABLED: 'false'
  MCP_COMPAT_PATHS_ENABLED: 'true'
}

@description('Optional tags to apply to all Azure resources.')
param tags object = {}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: union({
    managed_by: 'bicep'
    workload: 'simple-mcp-server'
  }, tags)
}

module containerAppStack './modules/container-app-stack.bicep' = {
  name: 'containerAppStack'
  scope: resourceGroup(resourceGroupName)
  params: {
    location: location
    logAnalyticsWorkspaceName: logAnalyticsWorkspaceName
    containerAppsEnvironmentName: containerAppsEnvironmentName
    containerAppName: containerAppName
    userAssignedIdentityName: userAssignedIdentityName
    acrName: acrName
    containerRegistrySku: containerRegistrySku
    acrAdminEnabled: acrAdminEnabled
    logAnalyticsRetentionInDays: logAnalyticsRetentionInDays
    deployContainerApp: deployContainerApp
    imageRepository: imageRepository
    imageTag: imageTag
    ingressExternal: ingressExternal
    targetPort: targetPort
    cpu: cpu
    memory: memory
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    containerAppEnvironmentVariables: containerAppEnvironmentVariables
    tags: tags
  }
  dependsOn: [
    rg
  ]
}

output resourceGroupName string = resourceGroupName
output acrName string = containerAppStack.outputs.acrName
output acrLoginServer string = containerAppStack.outputs.acrLoginServer
output containerAppsEnvironmentName string = containerAppStack.outputs.containerAppsEnvironmentName
output containerAppName string = containerAppStack.outputs.containerAppName
output containerAppFqdn string = containerAppStack.outputs.containerAppFqdn
output containerAppUrl string = containerAppStack.outputs.containerAppUrl
output imageReference string = containerAppStack.outputs.imageReference
