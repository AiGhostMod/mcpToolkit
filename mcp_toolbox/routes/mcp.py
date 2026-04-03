from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def register_mcp_routes(
    app: FastAPI,
    *,
    ensure_compat_paths_enabled: Callable[[], None],
    mcp_discovery_handler: Callable[[Request], dict[str, Any]],
    mcp_jsonrpc_handler: Callable[[Request], Awaitable[JSONResponse]],
) -> None:
    @app.get("/")
    @app.get("/mcp")
    @app.get("/mcp/")
    @app.get("/mcp/mcp")
    @app.get("/mcp/mcp/")
    @app.get("/v1/mcp")
    @app.get("/v1/mcp/")
    def mcp_discovery(request: Request) -> dict[str, Any]:
        if request.url.path == "/":
            ensure_compat_paths_enabled()
        return mcp_discovery_handler(request)

    @app.post("/")
    @app.post("/mcp")
    @app.post("/mcp/")
    @app.post("/mcp/mcp")
    @app.post("/mcp/mcp/")
    @app.post("/v1/mcp")
    @app.post("/v1/mcp/")
    async def mcp_endpoint(request: Request) -> JSONResponse:
        if request.url.path == "/":
            ensure_compat_paths_enabled()
        return await mcp_jsonrpc_handler(request)

    # Some MCP clients normalize or rewrite endpoint paths. These optional compatibility
    # routes can serve MCP discovery/JSON-RPC to avoid false 404s caused purely by path shape.
    @app.get("/{_remaining_path:path}")
    def mcp_discovery_fallback(_remaining_path: str, request: Request) -> dict[str, Any]:
        ensure_compat_paths_enabled()
        return mcp_discovery_handler(request)

    @app.post("/{_remaining_path:path}")
    async def mcp_endpoint_fallback(_remaining_path: str, request: Request) -> JSONResponse:
        ensure_compat_paths_enabled()
        return await mcp_jsonrpc_handler(request)

