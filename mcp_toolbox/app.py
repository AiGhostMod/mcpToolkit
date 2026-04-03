from __future__ import annotations

import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from mcp_toolbox.config import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_HISTORY_SIZE,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_BODY_PREVIEW_BYTES,
    MAX_HISTORY_SIZE,
    MAX_RESULT_PREVIEW_CHARS,
    MAX_TEXT_PREVIEW_CHARS,
    MCP_PROTOCOL_VERSION,
    MCP_TRANSPORT,
    _AUTH_MATCH_HINTS,
    _bounded_int_from_env,
    _coerce_bool,
    _coerce_float,
    _coerce_headers,
    _coerce_int,
    _coerce_names,
)
from mcp_toolbox.diagnostics.dashboard import build_dashboard_html, dashboard_payload
from mcp_toolbox.diagnostics.history import CallHistory, should_record_request
from mcp_toolbox.diagnostics.snapshots import request_debug_snapshot
from mcp_toolbox.routes import (
    register_diagnostics_routes,
    register_health_routes,
    register_mcp_routes,
)
from mcp_toolbox.tools import TOOLS, build_tool_handlers
from starlette.concurrency import run_in_threadpool


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


app = FastAPI(title=APP_NAME, version=APP_VERSION)
_START_TIME = time.monotonic()
_HISTORY_LIMIT = _bounded_int_from_env(
    "MCP_HISTORY_SIZE",
    DEFAULT_HISTORY_SIZE,
    minimum=1,
    maximum=MAX_HISTORY_SIZE,
)
_DASHBOARD_ENABLED = _coerce_bool(os.getenv("MCP_DASHBOARD_ENABLED"), default=False)
_COMPAT_PATHS_ENABLED = _coerce_bool(os.getenv("MCP_COMPAT_PATHS_ENABLED"), default=True)
_CALL_HISTORY = CallHistory(limit=_HISTORY_LIMIT)


def _rpc_result_payload(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error_payload(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _runtime_snapshot() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "pythonVersion": sys.version,
        "appName": APP_NAME,
        "appVersion": APP_VERSION,
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "transport": MCP_TRANSPORT,
        "portEnv": os.getenv("PORT"),
        "dashboardEnabled": _DASHBOARD_ENABLED,
        "compatPathsEnabled": _COMPAT_PATHS_ENABLED,
        "historySize": _HISTORY_LIMIT,
        "historyLength": _CALL_HISTORY.length(),
        "uptimeSeconds": round(time.monotonic() - _START_TIME, 3),
    }


def _request_debug_snapshot(
    request: Request,
    *,
    rpc_payload: Any,
    tool_arguments: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    return request_debug_snapshot(
        request,
        rpc_payload=rpc_payload,
        tool_arguments=tool_arguments,
        raw_body=raw_body,
        utc_now=_utc_now(),
        runtime_snapshot=_runtime_snapshot(),
        auth_match_hints=_AUTH_MATCH_HINTS,
        text_preview_limit=MAX_TEXT_PREVIEW_CHARS,
        max_body_preview_bytes=MAX_BODY_PREVIEW_BYTES,
    )


def _route_snapshot() -> dict[str, Any]:
    routes = []
    for route in app.routes:
        methods = sorted(route.methods) if getattr(route, "methods", None) else []
        routes.append({"path": route.path, "name": route.name, "methods": methods})
    return {"count": len(routes), "routes": routes}


def _environment_snapshot(
    *,
    prefix: str | None = None,
    names: list[str] | None = None,
    include_values: bool = True,
) -> dict[str, Any]:
    environment = dict(os.environ)
    if names:
        environment = {key: environment[key] for key in names if key in environment}
    elif prefix:
        environment = {key: value for key, value in environment.items() if key.startswith(prefix)}

    ordered_keys = sorted(environment)
    if include_values:
        variables: dict[str, Any] = {key: environment[key] for key in ordered_keys}
    else:
        variables = {key: {"present": True} for key in ordered_keys}

    return {"count": len(ordered_keys), "variables": variables}


def _server_info() -> dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "transport": MCP_TRANSPORT,
        "uptimeSeconds": round(time.monotonic() - _START_TIME, 3),
        "toolCount": len(TOOLS),
        "historySize": _HISTORY_LIMIT,
        "historyLength": len(_get_recent_calls(_HISTORY_LIMIT)),
        "dashboardEnabled": _DASHBOARD_ENABLED,
        "compatPathsEnabled": _COMPAT_PATHS_ENABLED,
        "runtime": _runtime_snapshot(),
        "routes": {
            "count": len(app.routes),
            "paths": [route.path for route in app.routes],
        },
    }


def _text_preview(text: str, *, limit: int = MAX_RESULT_PREVIEW_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _serialize_preview(value: Any, *, limit: int = MAX_RESULT_PREVIEW_CHARS) -> dict[str, Any]:
    serialized = json.dumps(value, default=str)
    preview, truncated = _text_preview(serialized, limit=limit)
    return {"text": preview, "truncated": truncated, "length": len(serialized)}


def _tool_output_summary(output: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"preview": _serialize_preview(output)}
    if isinstance(output, dict):
        summary["keys"] = sorted(output.keys())
    if isinstance(output, list):
        summary["listLength"] = len(output)
    return summary


def _jsonrpc_result_summary(
    *,
    request_id: Any,
    method: str | None,
    tool_name: str | None = None,
    output: Any | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "statusCode": 200,
        "kind": "result",
        "jsonrpcId": request_id,
        "method": method,
    }
    if tool_name:
        summary["toolName"] = tool_name
    if output is not None:
        summary["output"] = _tool_output_summary(output)
    return summary


def _jsonrpc_error_summary(
    *,
    request_id: Any,
    method: str | None,
    code: int,
    message: str,
    tool_name: str | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "statusCode": 200,
        "kind": "error",
        "jsonrpcId": request_id,
        "method": method,
        "error": {"code": code, "message": message},
    }
    if tool_name:
        summary["toolName"] = tool_name
    return summary


def _should_record_request(path: str) -> bool:
    return should_record_request(path)


def _record_call(
    request: Request,
    *,
    kind: str,
    started_at: float,
    raw_body: bytes,
    rpc_payload: Any,
    tool_arguments: dict[str, Any] | None,
    response_summary: dict[str, Any],
) -> None:
    if not _should_record_request(request.url.path):
        return

    snapshot = _request_debug_snapshot(
        request,
        rpc_payload=rpc_payload,
        tool_arguments=tool_arguments or {},
        raw_body=raw_body,
    )
    record = {
        "callId": uuid4().hex,
        "kind": kind,
        "durationMs": round((time.perf_counter() - started_at) * 1000, 3),
        **snapshot,
        "response": response_summary,
    }

    _CALL_HISTORY.record(record)


def _get_recent_calls(count: int) -> list[dict[str, Any]]:
    return _CALL_HISTORY.recent(count)


def _get_call_by_id(call_id: str) -> dict[str, Any] | None:
    return _CALL_HISTORY.by_id(call_id)


def _dashboard_payload() -> dict[str, Any]:
    return dashboard_payload(
        utc_now=_utc_now(),
        server_info=_server_info(),
        calls=_get_recent_calls(_HISTORY_LIMIT),
    )


def _build_dashboard_html() -> str:
    return build_dashboard_html(APP_NAME, _dashboard_payload())


def _ensure_dashboard_enabled() -> None:
    if not _DASHBOARD_ENABLED:
        raise HTTPException(status_code=404, detail="Dashboard is disabled.")


def _ensure_compat_paths_enabled() -> None:
    if not _COMPAT_PATHS_ENABLED:
        raise HTTPException(status_code=404, detail="Compatibility routes are disabled.")


TOOL_HANDLERS = build_tool_handlers(
    utc_now=_utc_now,
    runtime_snapshot=_runtime_snapshot,
    server_info=_server_info,
    route_snapshot=_route_snapshot,
    environment_snapshot=_environment_snapshot,
    get_recent_calls=_get_recent_calls,
    history_limit=_HISTORY_LIMIT,
    auth_match_hints=_AUTH_MATCH_HINTS,
    text_preview_limit=MAX_TEXT_PREVIEW_CHARS,
    max_body_preview_bytes=MAX_BODY_PREVIEW_BYTES,
    default_timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    coerce_bool=_coerce_bool,
    coerce_float=_coerce_float,
    coerce_headers=_coerce_headers,
    coerce_int=_coerce_int,
    coerce_names=_coerce_names,
)


def _call_tool(
    name: str,
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        raise ValueError(f"Unknown tool '{name}'")
    return handler(arguments, request, rpc_payload=rpc_payload, raw_body=raw_body)


def _mcp_discovery_payload() -> dict[str, Any]:
    return {"name": APP_NAME, "transport": MCP_TRANSPORT}


def _mcp_discovery(request: Request) -> dict[str, Any]:
    started_at = time.perf_counter()
    payload = _mcp_discovery_payload()
    _record_call(
        request,
        kind="mcp-discovery",
        started_at=started_at,
        raw_body=b"",
        rpc_payload=None,
        tool_arguments={},
        response_summary={"statusCode": 200, "kind": "discovery", "payload": payload},
    )
    return payload


async def _mcp_jsonrpc(request: Request) -> JSONResponse:
    started_at = time.perf_counter()
    raw_body = await request.body()
    parsed_payload: Any = None
    tool_arguments: dict[str, Any] = {}

    try:
        parsed_payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        response_payload = _rpc_error_payload(None, -32700, "Parse error")
        _record_call(
            request,
            kind="mcp-jsonrpc",
            started_at=started_at,
            raw_body=raw_body,
            rpc_payload=parsed_payload,
            tool_arguments={},
            response_summary=_jsonrpc_error_summary(
                request_id=None,
                method=None,
                code=-32700,
                message="Parse error",
            ),
        )
        return JSONResponse(response_payload)

    if not isinstance(parsed_payload, dict):
        response_payload = _rpc_error_payload(None, -32600, "Invalid Request")
        _record_call(
            request,
            kind="mcp-jsonrpc",
            started_at=started_at,
            raw_body=raw_body,
            rpc_payload=parsed_payload,
            tool_arguments={},
            response_summary=_jsonrpc_error_summary(
                request_id=None,
                method=None,
                code=-32600,
                message="Invalid Request",
            ),
        )
        return JSONResponse(response_payload)

    rpc_id = parsed_payload.get("id")
    method = parsed_payload.get("method")
    params = parsed_payload.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        response_payload = _rpc_error_payload(rpc_id, -32600, "Invalid params")
        _record_call(
            request,
            kind="mcp-jsonrpc",
            started_at=started_at,
            raw_body=raw_body,
            rpc_payload=parsed_payload,
            tool_arguments={},
            response_summary=_jsonrpc_error_summary(
                request_id=rpc_id,
                method=method,
                code=-32600,
                message="Invalid params",
            ),
        )
        return JSONResponse(response_payload)

    if method == "initialize":
        result = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
        }
        response_payload = _rpc_result_payload(rpc_id, result)
        _record_call(
            request,
            kind="mcp-jsonrpc",
            started_at=started_at,
            raw_body=raw_body,
            rpc_payload=parsed_payload,
            tool_arguments={},
            response_summary=_jsonrpc_result_summary(request_id=rpc_id, method=method, output=result),
        )
        return JSONResponse(response_payload)

    if method == "notifications/initialized":
        result = {}
        response_payload = _rpc_result_payload(rpc_id, result)
        _record_call(
            request,
            kind="mcp-jsonrpc",
            started_at=started_at,
            raw_body=raw_body,
            rpc_payload=parsed_payload,
            tool_arguments={},
            response_summary=_jsonrpc_result_summary(request_id=rpc_id, method=method, output=result),
        )
        return JSONResponse(response_payload)

    if method == "tools/list":
        result = {"tools": TOOLS}
        response_payload = _rpc_result_payload(rpc_id, result)
        _record_call(
            request,
            kind="mcp-jsonrpc",
            started_at=started_at,
            raw_body=raw_body,
            rpc_payload=parsed_payload,
            tool_arguments={},
            response_summary=_jsonrpc_result_summary(request_id=rpc_id, method=method, output=result),
        )
        return JSONResponse(response_payload)

    if method == "tools/call":
        name = params.get("name")
        tool_arguments = params.get("arguments") or {}
        if not name:
            response_payload = _rpc_error_payload(rpc_id, -32602, "Missing tool name")
            _record_call(
                request,
                kind="mcp-jsonrpc",
                started_at=started_at,
                raw_body=raw_body,
                rpc_payload=parsed_payload,
                tool_arguments={},
                response_summary=_jsonrpc_error_summary(
                    request_id=rpc_id,
                    method=method,
                    code=-32602,
                    message="Missing tool name",
                ),
            )
            return JSONResponse(response_payload)
        if not isinstance(tool_arguments, dict):
            response_payload = _rpc_error_payload(rpc_id, -32602, "Tool arguments must be an object")
            _record_call(
                request,
                kind="mcp-jsonrpc",
                started_at=started_at,
                raw_body=raw_body,
                rpc_payload=parsed_payload,
                tool_arguments={},
                response_summary=_jsonrpc_error_summary(
                    request_id=rpc_id,
                    method=method,
                    code=-32602,
                    message="Tool arguments must be an object",
                    tool_name=str(name),
                ),
            )
            return JSONResponse(response_payload)

        try:
            output = await run_in_threadpool(
                _call_tool,
                str(name),
                tool_arguments,
                request,
                rpc_payload=parsed_payload,
                raw_body=raw_body,
            )
        except KeyError as exc:
            message = f"Missing argument: {exc.args[0]}"
            response_payload = _rpc_error_payload(rpc_id, -32602, message)
            _record_call(
                request,
                kind="mcp-jsonrpc",
                started_at=started_at,
                raw_body=raw_body,
                rpc_payload=parsed_payload,
                tool_arguments=tool_arguments,
                response_summary=_jsonrpc_error_summary(
                    request_id=rpc_id,
                    method=method,
                    code=-32602,
                    message=message,
                    tool_name=str(name),
                ),
            )
            return JSONResponse(response_payload)
        except ValueError as exc:
            response_payload = _rpc_error_payload(rpc_id, -32602, str(exc))
            _record_call(
                request,
                kind="mcp-jsonrpc",
                started_at=started_at,
                raw_body=raw_body,
                rpc_payload=parsed_payload,
                tool_arguments=tool_arguments,
                response_summary=_jsonrpc_error_summary(
                    request_id=rpc_id,
                    method=method,
                    code=-32602,
                    message=str(exc),
                    tool_name=str(name),
                ),
            )
            return JSONResponse(response_payload)
        except Exception as exc:
            message = f"Tool execution failed: {exc}"
            response_payload = _rpc_error_payload(rpc_id, -32603, message)
            _record_call(
                request,
                kind="mcp-jsonrpc",
                started_at=started_at,
                raw_body=raw_body,
                rpc_payload=parsed_payload,
                tool_arguments=tool_arguments,
                response_summary=_jsonrpc_error_summary(
                    request_id=rpc_id,
                    method=method,
                    code=-32603,
                    message=message,
                    tool_name=str(name),
                ),
            )
            return JSONResponse(response_payload)

        result = {"content": [{"type": "text", "text": json.dumps(output)}]}
        response_payload = _rpc_result_payload(rpc_id, result)
        _record_call(
            request,
            kind="mcp-jsonrpc",
            started_at=started_at,
            raw_body=raw_body,
            rpc_payload=parsed_payload,
            tool_arguments=tool_arguments,
            response_summary=_jsonrpc_result_summary(
                request_id=rpc_id,
                method=method,
                tool_name=str(name),
                output=output,
            ),
        )
        return JSONResponse(response_payload)

    response_payload = _rpc_error_payload(rpc_id, -32601, f"Method not found: {method}")
    _record_call(
        request,
        kind="mcp-jsonrpc",
        started_at=started_at,
        raw_body=raw_body,
        rpc_payload=parsed_payload,
        tool_arguments={},
        response_summary=_jsonrpc_error_summary(
            request_id=rpc_id,
            method=method,
            code=-32601,
            message=f"Method not found: {method}",
        ),
    )
    return JSONResponse(response_payload)


register_health_routes(app, app_version=APP_VERSION)
register_diagnostics_routes(
    app,
    ensure_dashboard_enabled=_ensure_dashboard_enabled,
    history_limit=_HISTORY_LIMIT,
    get_recent_calls=_get_recent_calls,
    get_call_by_id=_get_call_by_id,
    utc_now=_utc_now,
    server_info=_server_info,
    route_snapshot=_route_snapshot,
    build_dashboard_html=_build_dashboard_html,
)
register_mcp_routes(
    app,
    ensure_compat_paths_enabled=_ensure_compat_paths_enabled,
    mcp_discovery_handler=_mcp_discovery,
    mcp_jsonrpc_handler=_mcp_jsonrpc,
)


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("mcp_toolbox.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
