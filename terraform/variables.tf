variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "swedencentral"
}

variable "name_prefix" {
  description = "Friendly base name used when specific resource names are not provided."
  type        = string
  default     = "simple-mcp-server"
}

variable "unique_suffix" {
  description = "Optional short suffix used in generated names. Leave null to let Terraform generate one."
  type        = string
  default     = null
  nullable    = true
}

variable "resource_group_name" {
  description = "Optional resource group name override."
  type        = string
  default     = null
  nullable    = true
}

variable "log_analytics_workspace_name" {
  description = "Optional Log Analytics workspace name override."
  type        = string
  default     = null
  nullable    = true
}

variable "container_apps_environment_name" {
  description = "Optional Container Apps environment name override."
  type        = string
  default     = null
  nullable    = true
}

variable "container_app_name" {
  description = "Optional Container App name override."
  type        = string
  default     = null
  nullable    = true
}

variable "acr_name" {
  description = "Optional Azure Container Registry name override. This must be globally unique, 5-50 characters, and alphanumeric only."
  type        = string
  default     = null
  nullable    = true
}

variable "user_assigned_identity_name" {
  description = "Optional user-assigned identity name override."
  type        = string
  default     = null
  nullable    = true
}

variable "container_registry_sku" {
  description = "SKU for the Azure Container Registry."
  type        = string
  default     = "Basic"

  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.container_registry_sku)
    error_message = "container_registry_sku must be Basic, Standard, or Premium."
  }
}

variable "acr_admin_enabled" {
  description = "Whether to enable the ACR admin account."
  type        = bool
  default     = false
}

variable "log_analytics_retention_in_days" {
  description = "Retention period for Log Analytics data."
  type        = number
  default     = 30
}

variable "deploy_container_app" {
  description = "Set to false to provision the resource group, ACR, and Container Apps environment first, then set to true after the application image has been pushed."
  type        = bool
  default     = true
}

variable "image_repository" {
  description = "Repository name inside ACR for the application image."
  type        = string
  default     = "simple-mcp-server"
}

variable "image_tag" {
  description = "Container image tag that the Container App should run."
  type        = string
  default     = "latest"
}

variable "ingress_external" {
  description = "Whether the Container App should have external ingress."
  type        = bool
  default     = true
}

variable "target_port" {
  description = "Container port exposed by the application."
  type        = number
  default     = 8080
}

variable "cpu" {
  description = "Requested CPU for the Container App workload."
  type        = number
  default     = 0.5
}

variable "memory" {
  description = "Requested memory for the Container App workload."
  type        = string
  default     = "1.0Gi"
}

variable "min_replicas" {
  description = "Minimum number of Container App replicas."
  type        = number
  default     = 1
}

variable "max_replicas" {
  description = "Maximum number of Container App replicas."
  type        = number
  default     = 2
}

variable "container_app_environment_variables" {
  description = "Additional environment variables passed into the Container App. PORT is always aligned to target_port."
  type        = map(string)
  default = {
    MCP_HISTORY_SIZE      = "10"
    MCP_DASHBOARD_ENABLED = "true"
  }
}

variable "tags" {
  description = "Optional tags to apply to all Azure resources."
  type        = map(string)
  default     = {}
}
