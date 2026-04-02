targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Log Analytics workspace name.')
param logAnalyticsWorkspaceName string

@description('Container Apps environment name.')
param containerAppsEnvironmentName string

@description('Container App name.')
param containerAppName string

@description('User-assigned identity name.')
param userAssignedIdentityName string

@description('Azure Container Registry name.')
param acrName string

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
  MCP_DASHBOARD_ENABLED: 'true'
}

@description('Optional tags to apply to all Azure resources.')
param tags object = {}

var acrPullRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
var mergedTags = union({
  managed_by: 'bicep'
  workload: 'simple-mcp-server'
}, tags)
var envVars = union(containerAppEnvironmentVariables, {
  PORT: string(targetPort)
})
var acrLoginServer = '${acrName}.azurecr.io'
var imageReference = '${acrLoginServer}/${imageRepository}:${imageTag}'

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  tags: mergedTags
  properties: {
    features: {
      disableLocalAuth: false
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
    retentionInDays: logAnalyticsRetentionInDays
    sku: {
      name: 'PerGB2018'
    }
    workspaceCapping: {
      dailyQuotaGb: -1
    }
  }
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppsEnvironmentName
  location: location
  tags: mergedTags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  tags: mergedTags
  sku: {
    name: containerRegistrySku
  }
  properties: {
    adminUserEnabled: acrAdminEnabled
    anonymousPullEnabled: false
    publicNetworkAccess: 'Enabled'
    policies: {
      azureADAuthenticationAsArmPolicy: {
        status: 'enabled'
      }
    }
  }
}

resource containerRegistryPullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: userAssignedIdentityName
  location: location
  tags: mergedTags
}

resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, containerRegistryPullIdentity.id, acrPullRoleDefinitionId)
  scope: acr
  properties: {
    principalId: containerRegistryPullIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleDefinitionId
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = if (deployContainerApp) {
  name: containerAppName
  location: location
  tags: mergedTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${containerRegistryPullIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        external: ingressExternal
        targetPort: targetPort
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        transport: 'auto'
      }
      registries: [
        {
          server: acrLoginServer
          identity: containerRegistryPullIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'app'
          image: imageReference
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: [
            for item in items(envVars): {
              name: item.key
              value: string(item.value)
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
  dependsOn: [
    acrPullRoleAssignment
  ]
}

output acrName string = acr.name
output acrLoginServer string = acrLoginServer
output containerAppsEnvironmentName string = managedEnvironment.name
output containerAppName string = deployContainerApp ? containerAppName : ''
output containerAppFqdn string = deployContainerApp ? containerApp!.properties.configuration.ingress.fqdn : ''
output containerAppUrl string = deployContainerApp ? 'https://${containerApp!.properties.configuration.ingress.fqdn}' : ''
output imageReference string = imageReference
