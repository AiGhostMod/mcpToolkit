output "resource_group_name" {
  description = "Name of the resource group created for the deployment."
  value       = azurerm_resource_group.rg.name
}

output "acr_name" {
  description = "Name of the Azure Container Registry."
  value       = azurerm_container_registry.acr.name
}

output "acr_login_server" {
  description = "Login server for the Azure Container Registry."
  value       = azurerm_container_registry.acr.login_server
}

output "container_apps_environment_name" {
  description = "Name of the Container Apps environment."
  value       = azurerm_container_app_environment.environment.name
}

output "container_app_name" {
  description = "Name of the deployed Container App, if enabled."
  value       = try(azurerm_container_app.app[0].name, null)
}

output "container_app_fqdn" {
  description = "Public FQDN of the Container App, if ingress is enabled."
  value       = try(azurerm_container_app.app[0].ingress[0].fqdn, null)
}

output "container_app_url" {
  description = "Public URL of the Container App, if ingress is enabled."
  value       = try("https://${azurerm_container_app.app[0].ingress[0].fqdn}", null)
}

output "image_reference" {
  description = "Fully qualified image reference expected by the Container App."
  value       = local.image_reference
}
