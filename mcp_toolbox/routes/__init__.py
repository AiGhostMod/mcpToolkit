"""Route modules for MCP Toolbox."""

from mcp_toolbox.routes.diagnostics import register_diagnostics_routes
from mcp_toolbox.routes.health import register_health_routes
from mcp_toolbox.routes.mcp import register_mcp_routes

__all__ = ["register_health_routes", "register_diagnostics_routes", "register_mcp_routes"]
