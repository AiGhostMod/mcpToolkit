resource "random_string" "suffix" {
  count   = var.unique_suffix == null ? 1 : 0
  length  = 6
  lower   = true
  upper   = false
  special = false
}

locals {
  sanitized_base     = trim(replace(lower(var.name_prefix), "/[^0-9a-z-]/", "-"), "-")
  sanitized_acr_base = replace(lower(var.name_prefix), "/[^0-9a-z]/", "")
  base_name          = local.sanitized_base != "" ? local.sanitized_base : "simple-mcp-server"
  acr_base_name      = local.sanitized_acr_base != "" ? local.sanitized_acr_base : "simplemcpserver"
  resolved_suffix    = var.unique_suffix != null ? lower(var.unique_suffix) : random_string.suffix[0].result
  resource_group     = coalesce(var.resource_group_name, "rg-${local.base_name}")
  workspace_name     = coalesce(var.log_analytics_workspace_name, "${local.base_name}-law")
  environment_name   = coalesce(var.container_apps_environment_name, "${local.base_name}-env")
  app_name           = coalesce(var.container_app_name, local.base_name)
  identity_name      = coalesce(var.user_assigned_identity_name, "${local.base_name}-pull")
  acr_name           = coalesce(var.acr_name, substr("${substr(local.acr_base_name, 0, 20)}${local.resolved_suffix}", 0, 50))
  image_reference    = "${azurerm_container_registry.acr.login_server}/${var.image_repository}:${var.image_tag}"
  merged_tags        = merge({ managed_by = "terraform", workload = "simple-mcp-server" }, var.tags)
  container_env_vars = merge(var.container_app_environment_variables, { PORT = tostring(var.target_port) })
}

resource "azurerm_resource_group" "rg" {
  name     = local.resource_group
  location = var.location
  tags     = local.merged_tags
}

resource "azurerm_log_analytics_workspace" "workspace" {
  name                = local.workspace_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_analytics_retention_in_days
  tags                = local.merged_tags
}

resource "azurerm_container_app_environment" "environment" {
  name                       = local.environment_name
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.workspace.id
  tags                       = local.merged_tags
}

resource "azurerm_container_registry" "acr" {
  name                = local.acr_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = var.container_registry_sku
  admin_enabled       = var.acr_admin_enabled
  tags                = local.merged_tags
}

resource "azurerm_user_assigned_identity" "acr_pull" {
  name                = local.identity_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.merged_tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                            = azurerm_container_registry.acr.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_user_assigned_identity.acr_pull.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_container_app" "app" {
  count                        = var.deploy_container_app ? 1 : 0
  name                         = local.app_name
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.environment.id
  revision_mode                = "Single"
  tags                         = local.merged_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.acr_pull.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.acr_pull.id
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "app"
      image  = local.image_reference
      cpu    = var.cpu
      memory = var.memory

      dynamic "env" {
        for_each = local.container_env_vars
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  ingress {
    external_enabled = var.ingress_external
    target_port      = var.target_port
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}
