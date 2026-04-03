from __future__ import annotations

import socket
from typing import Any, Callable

from fastapi import Request

from mcp_toolbox.diagnostics.snapshots import decode_jwt_token, extract_client_ip

ToolHandler = Callable[..., dict[str, Any]]


def build_core_handlers(
    *,
    utc_now: Callable[[], str],
    server_info: Callable[[], dict[str, Any]],
) -> dict[str, ToolHandler]:
    def _tool_get_caller_ip(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        return {"callerIp": extract_client_ip(request)}

    def _tool_add_numbers(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        return {"sum": float(arguments["a"]) + float(arguments["b"])}

    def _tool_utc_now(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        return {"utc": utc_now()}

    def _tool_get_server_info(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        return server_info()

    def _tool_echo_payload(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        return {
            "timestampUtc": utc_now(),
            "hostname": socket.gethostname(),
            "label": arguments.get("label"),
            "payload": arguments.get("payload"),
            "request": {
                "path": request.url.path,
                "callerIp": extract_client_ip(request),
                "userAgent": request.headers.get("user-agent"),
            },
        }

    def _tool_decode_jwt(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        token = arguments.get("token")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Argument 'token' must be a non-empty string.")

        decoded = decode_jwt_token(token)
        if not decoded:
            raise ValueError("Unable to decode token.")
        return decoded

    return {
        "get_caller_ip": _tool_get_caller_ip,
        "add_numbers": _tool_add_numbers,
        "utc_now": _tool_utc_now,
        "get_server_info": _tool_get_server_info,
        "echo_payload": _tool_echo_payload,
        "decode_jwt": _tool_decode_jwt,
    }

