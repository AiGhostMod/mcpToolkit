from __future__ import annotations

import base64
import binascii
import hashlib
import html
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool


APP_NAME = "simple-mcp-server"
APP_VERSION = "1.1.0"
MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_TRANSPORT = "streamable-http"
DEFAULT_HISTORY_SIZE = 10
MAX_HISTORY_SIZE = 200
MAX_BODY_PREVIEW_BYTES = 32 * 1024
MAX_TEXT_PREVIEW_CHARS = 16 * 1024
MAX_RESULT_PREVIEW_CHARS = 4 * 1024
DEFAULT_TIMEOUT_SECONDS = 5.0
_AUTH_MATCH_HINTS = ("auth", "token", "jwt", "key", "secret", "cookie")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_int_from_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        parsed = int(raw_value)
    except ValueError:
        return default

    return max(minimum, min(parsed, maximum))


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Expected a boolean-compatible value, got {value!r}")


def _coerce_int(value: Any, *, name: str, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Argument '{name}' must be an integer.") from exc
    return max(minimum, min(parsed, maximum))


def _coerce_float(value: Any, *, name: str, default: float, minimum: float, maximum: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Argument '{name}' must be a number.") from exc
    return max(minimum, min(parsed, maximum))


def _coerce_headers(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Argument 'headers' must be an object of string keys and values.")
    return {str(key): str(header_value) for key, header_value in value.items()}


def _coerce_names(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Argument 'names' must be an array of strings.")
    return [str(item) for item in value]


app = FastAPI(title=APP_NAME, version=APP_VERSION)
_START_TIME = time.monotonic()
_HISTORY_LIMIT = _bounded_int_from_env(
    "MCP_HISTORY_SIZE",
    DEFAULT_HISTORY_SIZE,
    minimum=1,
    maximum=MAX_HISTORY_SIZE,
)
_DASHBOARD_ENABLED = _coerce_bool(os.getenv("MCP_DASHBOARD_ENABLED"), default=True)
_CALL_HISTORY: deque[dict[str, Any]] = deque(maxlen=_HISTORY_LIMIT)
_CALL_HISTORY_LOCK = Lock()


def _rpc_result_payload(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error_payload(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _rpc_result(request_id: Any, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse(_rpc_result_payload(request_id, result))


def _rpc_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(_rpc_error_payload(request_id, code, message))


def _extract_client_ip(request: Request) -> str:
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()

    if request.client:
        return request.client.host

    return "unknown"


def _decode_base64url_json(segment: str) -> dict[str, Any] | str:
    padded = f"{segment}{'=' * (-len(segment) % 4)}"
    decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    try:
        return json.loads(decoded)
    except json.JSONDecodeError:
        return decoded


def _extract_token_candidate(raw_value: str | None) -> str | None:
    if not raw_value:
        return None

    value = raw_value.strip()
    if not value:
        return None

    scheme, separator, credential = value.partition(" ")
    if separator and credential and scheme.lower() in {"bearer", "jwt", "token"}:
        return credential.strip() or None

    return value


def _decode_jwt_token(raw_value: str | None) -> dict[str, Any] | None:
    token = _extract_token_candidate(raw_value)
    if not token:
        return None

    parts = token.split(".")
    jwt_details: dict[str, Any] = {
        "raw": token,
        "partsCount": len(parts),
        "isJwt": len(parts) == 3,
    }
    if len(parts) != 3:
        return jwt_details

    try:
        jwt_details["header"] = _decode_base64url_json(parts[0])
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        jwt_details["headerDecodeError"] = str(exc)

    try:
        jwt_details["payload"] = _decode_base64url_json(parts[1])
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        jwt_details["payloadDecodeError"] = str(exc)

    jwt_details["signature"] = parts[2]
    return jwt_details


def _extract_auth_details(request: Request) -> dict[str, Any]:
    normalized_headers = {key.lower(): value for key, value in request.headers.items()}
    auth_related_headers = {
        key: value
        for key, value in normalized_headers.items()
        if any(hint in key for hint in _AUTH_MATCH_HINTS)
    }

    auth_related_query_params: dict[str, list[str]] = {}
    for key, value in request.query_params.multi_items():
        lower_key = key.lower()
        if any(hint in lower_key for hint in _AUTH_MATCH_HINTS):
            auth_related_query_params.setdefault(key, []).append(value)

    authorization_raw = normalized_headers.get("authorization")
    parsed_authorization: dict[str, Any] = {
        "raw": authorization_raw,
        "scheme": None,
        "credential": None,
        "bearerToken": None,
        "jwt": None,
        "basicDecoded": None,
    }
    if authorization_raw:
        scheme, _, credential = authorization_raw.partition(" ")
        parsed_authorization["scheme"] = scheme
        parsed_authorization["credential"] = credential or None

        scheme_lower = scheme.lower()
        if scheme_lower == "bearer" and credential:
            parsed_authorization["bearerToken"] = credential
            parsed_authorization["jwt"] = _decode_jwt_token(credential)
        elif scheme_lower == "basic" and credential:
            try:
                parsed_authorization["basicDecoded"] = base64.b64decode(credential.encode("ascii")).decode(
                    "utf-8",
                    errors="replace",
                )
            except (ValueError, binascii.Error) as exc:
                parsed_authorization["basicDecodeError"] = str(exc)
        elif credential:
            parsed_authorization["jwt"] = _decode_jwt_token(credential)

    decoded_jwt_auth_headers = {
        key: decoded
        for key, value in auth_related_headers.items()
        for decoded in [_decode_jwt_token(value)]
        if decoded
    }

    decoded_jwt_query_params: dict[str, list[dict[str, Any]]] = {}
    for key, values in auth_related_query_params.items():
        decoded_items = [decoded for decoded in (_decode_jwt_token(value) for value in values) if decoded]
        if decoded_items:
            decoded_jwt_query_params[key] = decoded_items

    cookie_map = dict(request.cookies)
    decoded_jwt_cookies = {
        key: decoded
        for key, value in cookie_map.items()
        for decoded in [_decode_jwt_token(value)]
        if decoded
    }

    return {
        "authorization": parsed_authorization,
        "authHeaders": auth_related_headers,
        "queryAuthParams": auth_related_query_params,
        "cookies": cookie_map,
        "decodedJwt": {
            "authorization": parsed_authorization.get("jwt"),
            "authHeaders": decoded_jwt_auth_headers,
            "queryAuthParams": decoded_jwt_query_params,
            "cookies": decoded_jwt_cookies,
        },
    }


def _text_preview(text: str, *, limit: int = MAX_TEXT_PREVIEW_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _body_snapshot(raw_body: bytes, parsed_json: Any) -> dict[str, Any]:
    raw_body_text = raw_body.decode("utf-8", errors="replace")
    text_value, text_truncated = _text_preview(raw_body_text)
    base64_limit = min(len(raw_body), MAX_BODY_PREVIEW_BYTES)
    base64_value = base64.b64encode(raw_body[:base64_limit]).decode("ascii")

    return {
        "sizeBytes": len(raw_body),
        "text": text_value,
        "textTruncated": text_truncated,
        "base64": base64_value,
        "base64Truncated": len(raw_body) > MAX_BODY_PREVIEW_BYTES,
        "json": parsed_json,
    }


def _query_pairs(request: Request) -> list[dict[str, str]]:
    return [{"name": key, "value": value} for key, value in request.query_params.multi_items()]


def _raw_header_pairs(request: Request) -> list[dict[str, str]]:
    return [
        {
            "name": key.decode("latin-1", errors="replace"),
            "value": value.decode("latin-1", errors="replace"),
        }
        for key, value in request.scope.get("headers", [])
    ]


def _request_snapshot(request: Request) -> dict[str, Any]:
    server_host, server_port = (None, None)
    if request.scope.get("server"):
        server_host, server_port = request.scope["server"]

    x_forwarded_for = request.headers.get("x-forwarded-for")
    forwarded_chain = [item.strip() for item in x_forwarded_for.split(",")] if x_forwarded_for else []

    return {
        "method": request.method,
        "url": str(request.url),
        "baseUrl": str(request.base_url),
        "path": request.url.path,
        "rawPath": request.scope.get("raw_path", b"").decode("latin-1", errors="replace"),
        "queryString": request.scope.get("query_string", b"").decode("latin-1", errors="replace"),
        "queryParams": dict(request.query_params),
        "queryParamsMulti": _query_pairs(request),
        "pathParams": dict(request.path_params),
        "headers": dict(request.headers),
        "headersRaw": _raw_header_pairs(request),
        "client": {
            "host": request.client.host if request.client else None,
            "port": request.client.port if request.client else None,
        },
        "server": {"host": server_host, "port": server_port},
        "scheme": request.scope.get("scheme"),
        "httpVersion": request.scope.get("http_version"),
        "rootPath": request.scope.get("root_path"),
        "callerIp": _extract_client_ip(request),
        "userAgent": request.headers.get("user-agent"),
        "forwarding": {
            "host": request.headers.get("host"),
            "xForwardedFor": x_forwarded_for,
            "xForwardedForChain": forwarded_chain,
            "xRealIp": request.headers.get("x-real-ip"),
            "xForwardedHost": request.headers.get("x-forwarded-host"),
            "xForwardedProto": request.headers.get("x-forwarded-proto"),
            "xForwardedPort": request.headers.get("x-forwarded-port"),
            "xEnvoyExternalAddress": request.headers.get("x-envoy-external-address"),
        },
    }


def _mcp_snapshot(rpc_payload: Any, tool_arguments: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(rpc_payload, dict):
        return {
            "jsonrpc": rpc_payload.get("jsonrpc"),
            "id": rpc_payload.get("id"),
            "method": rpc_payload.get("method"),
            "params": rpc_payload.get("params"),
            "toolArguments": tool_arguments or {},
        }

    return {
        "jsonrpc": None,
        "id": None,
        "method": None,
        "params": None,
        "toolArguments": tool_arguments or {},
        "rawPayloadType": type(rpc_payload).__name__ if rpc_payload is not None else None,
    }


def _scope_snapshot(request: Request) -> dict[str, Any]:
    return {
        "type": request.scope.get("type"),
        "asgi": request.scope.get("asgi"),
        "extensions": request.scope.get("extensions"),
        "client": request.scope.get("client"),
        "server": request.scope.get("server"),
    }


def _runtime_snapshot() -> dict[str, Any]:
    with _CALL_HISTORY_LOCK:
        history_length = len(_CALL_HISTORY)

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
        "historySize": _HISTORY_LIMIT,
        "historyLength": history_length,
        "uptimeSeconds": round(time.monotonic() - _START_TIME, 3),
    }


def _request_debug_snapshot(
    request: Request,
    *,
    rpc_payload: Any,
    tool_arguments: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    return {
        "timestampUtc": _utc_now(),
        "request": _request_snapshot(request),
        "body": _body_snapshot(raw_body, rpc_payload if isinstance(rpc_payload, (dict, list)) else None),
        "mcp": _mcp_snapshot(rpc_payload, tool_arguments),
        "auth": _extract_auth_details(request),
        "runtime": _runtime_snapshot(),
        "scope": _scope_snapshot(request),
    }


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
        "runtime": _runtime_snapshot(),
        "routes": {
            "count": len(app.routes),
            "paths": [route.path for route in app.routes],
        },
    }


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
    if path == "/healthz":
        return False
    if path == "/dashboard":
        return False
    if path.startswith("/api/"):
        return False
    return True


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

    with _CALL_HISTORY_LOCK:
        _CALL_HISTORY.appendleft(record)


def _get_recent_calls(count: int) -> list[dict[str, Any]]:
    requested = max(1, min(count, _HISTORY_LIMIT))
    with _CALL_HISTORY_LOCK:
        return list(_CALL_HISTORY)[:requested]


def _get_call_by_id(call_id: str) -> dict[str, Any] | None:
    with _CALL_HISTORY_LOCK:
        for item in _CALL_HISTORY:
            if item["callId"] == call_id:
                return item
    return None


def _dashboard_payload() -> dict[str, Any]:
    return {
        "generatedAtUtc": _utc_now(),
        "serverInfo": _server_info(),
        "calls": _get_recent_calls(_HISTORY_LIMIT),
    }


def _build_dashboard_html() -> str:
    payload = _dashboard_payload()
    calls = payload["calls"]
    call_sections = []
    if not calls:
        call_sections.append("<p>No calls captured yet.</p>")
    else:
        for entry in calls:
            title = (
                f"{entry['timestampUtc']} | {entry['request']['method']} {entry['request']['path']} | "
                f"{entry['response'].get('kind')} | {entry['durationMs']} ms"
            )
            title_html = html.escape(title)
            body_html = html.escape(json.dumps(entry, indent=2, default=str))
            call_sections.append(
                f"<details><summary>{title_html}</summary><pre>{body_html}</pre></details>"
            )

    server_info = html.escape(json.dumps(payload["serverInfo"], indent=2, default=str))
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>{html.escape(APP_NAME)} dashboard</title>
    <style>
      body {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 2rem; background: #111827; color: #e5e7eb; }}
      a {{ color: #93c5fd; }}
      h1, h2 {{ margin-bottom: 0.5rem; }}
      pre {{ white-space: pre-wrap; word-break: break-word; background: #0b1220; padding: 1rem; border-radius: 8px; }}
      details {{ margin-bottom: 1rem; background: #1f2937; padding: 0.75rem 1rem; border-radius: 8px; }}
      summary {{ cursor: pointer; }}
      code {{ color: #bfdbfe; }}
      .meta {{ margin-bottom: 1rem; color: #9ca3af; }}
    </style>
  </head>
  <body>
    <h1>{html.escape(APP_NAME)} dashboard</h1>
    <p class="meta">Recent MCP/discovery calls captured in-memory. JSON views: <a href="/api/calls">/api/calls</a>, <a href="/api/calls/latest">/api/calls/latest</a>, <a href="/api/runtime">/api/runtime</a></p>
    <h2>Server info</h2>
    <pre>{server_info}</pre>
    <h2>Recent calls</h2>
    {''.join(call_sections)}
  </body>
</html>"""


def _ensure_dashboard_enabled() -> None:
    if not _DASHBOARD_ENABLED:
        raise HTTPException(status_code=404, detail="Dashboard is disabled.")


def _tool_get_caller_ip(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    return {"callerIp": _extract_client_ip(request)}


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
    return {"utc": _utc_now()}


def _tool_debug_request_context(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    return _request_debug_snapshot(
        request,
        rpc_payload=rpc_payload,
        tool_arguments=arguments,
        raw_body=raw_body,
    )


def _tool_inspect_request_summary(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    snapshot = _request_snapshot(request)
    return {
        "request": {
            "method": snapshot["method"],
            "url": snapshot["url"],
            "baseUrl": snapshot["baseUrl"],
            "path": snapshot["path"],
            "rawPath": snapshot["rawPath"],
            "queryString": snapshot["queryString"],
            "queryParams": snapshot["queryParams"],
            "queryParamsMulti": snapshot["queryParamsMulti"],
            "pathParams": snapshot["pathParams"],
            "client": snapshot["client"],
            "server": snapshot["server"],
            "scheme": snapshot["scheme"],
            "httpVersion": snapshot["httpVersion"],
            "rootPath": snapshot["rootPath"],
            "callerIp": snapshot["callerIp"],
            "userAgent": snapshot["userAgent"],
            "forwarding": snapshot["forwarding"],
        }
    }


def _tool_inspect_request_headers(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    snapshot = _request_snapshot(request)
    return {"headers": snapshot["headers"], "headersRaw": snapshot["headersRaw"]}


def _tool_inspect_request_body(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    return _body_snapshot(raw_body, rpc_payload)


def _tool_inspect_request_auth(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    return {
        "timestampUtc": _utc_now(),
        "path": request.url.path,
        "callerIp": _extract_client_ip(request),
        "auth": _extract_auth_details(request),
    }


def _tool_inspect_mcp_envelope(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    return _mcp_snapshot(rpc_payload, arguments)


def _tool_inspect_runtime(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    return {"runtime": _runtime_snapshot(), "serverInfo": _server_info()}


def _tool_inspect_routes(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    return _route_snapshot()


def _tool_inspect_environment(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    prefix = arguments.get("prefix")
    names = _coerce_names(arguments.get("names"))
    include_values = _coerce_bool(arguments.get("includeValues"), default=True)
    return _environment_snapshot(prefix=prefix, names=names, include_values=include_values)


def _tool_inspect_recent_calls(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    count = _coerce_int(arguments.get("count"), name="count", default=_HISTORY_LIMIT, minimum=1, maximum=_HISTORY_LIMIT)
    return {"count": count, "calls": _get_recent_calls(count)}


def _tool_get_server_info(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    return _server_info()


def _tool_echo_payload(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    return {
        "timestampUtc": _utc_now(),
        "hostname": socket.gethostname(),
        "label": arguments.get("label"),
        "payload": arguments.get("payload"),
        "request": {
            "path": request.url.path,
            "callerIp": _extract_client_ip(request),
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

    decoded = _decode_jwt_token(token)
    if not decoded:
        raise ValueError("Unable to decode token.")
    return decoded


def _tool_dns_resolve(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    hostname = arguments.get("hostname")
    if not isinstance(hostname, str) or not hostname.strip():
        raise ValueError("Argument 'hostname' must be a non-empty string.")

    port = arguments.get("port")
    try:
        address_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"DNS lookup failed for '{hostname}': {exc}") from exc

    records = []
    for family, socktype, protocol, canonname, sockaddr in address_info:
        records.append(
            {
                "family": socket.AddressFamily(family).name,
                "socketType": socket.SocketKind(socktype).name,
                "protocol": protocol,
                "canonicalName": canonname,
                "socketAddress": list(sockaddr) if isinstance(sockaddr, tuple) else sockaddr,
            }
        )

    return {"hostname": hostname, "port": port, "recordCount": len(records), "records": records}


def _tool_tcp_probe(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    host = arguments.get("host")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("Argument 'host' must be a non-empty string.")

    port = _coerce_int(arguments.get("port"), name="port", default=0, minimum=1, maximum=65535)
    timeout_seconds = _coerce_float(
        arguments.get("timeoutSeconds"),
        name="timeoutSeconds",
        default=DEFAULT_TIMEOUT_SECONDS,
        minimum=0.1,
        maximum=60.0,
    )

    started_at = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as connection:
            local_host, local_port = connection.getsockname()
            remote_host, remote_port = connection.getpeername()
    except OSError as exc:
        raise ValueError(f"TCP probe failed for {host}:{port}: {exc}") from exc

    return {
        "host": host,
        "port": port,
        "timeoutSeconds": timeout_seconds,
        "connected": True,
        "latencyMs": round((time.perf_counter() - started_at) * 1000, 3),
        "localAddress": {"host": local_host, "port": local_port},
        "remoteAddress": {"host": remote_host, "port": remote_port},
    }


def _tool_http_probe(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    url = arguments.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Argument 'url' must be a non-empty string.")

    method = str(arguments.get("method") or "GET").upper()
    headers = _coerce_headers(arguments.get("headers"))
    body = arguments.get("body")
    verify_tls = _coerce_bool(arguments.get("verifyTls"), default=True)
    timeout_seconds = _coerce_float(
        arguments.get("timeoutSeconds"),
        name="timeoutSeconds",
        default=DEFAULT_TIMEOUT_SECONDS,
        minimum=0.1,
        maximum=60.0,
    )
    data = None
    if body is not None:
        data = str(body).encode("utf-8")

    ssl_context = None
    if url.lower().startswith("https://"):
        ssl_context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()

    req = urllib.request.Request(url=url, data=data, method=method, headers=headers)
    started_at = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds, context=ssl_context) as response:
            response_body = response.read()
            body_text, body_truncated = _text_preview(response_body.decode("utf-8", errors="replace"))
            return {
                "url": url,
                "finalUrl": response.geturl(),
                "method": method,
                "statusCode": response.status,
                "reason": response.reason,
                "verifyTls": verify_tls,
                "timeoutSeconds": timeout_seconds,
                "latencyMs": round((time.perf_counter() - started_at) * 1000, 3),
                "headers": dict(response.headers.items()),
                "body": {
                    "sizeBytes": len(response_body),
                    "text": body_text,
                    "textTruncated": body_truncated,
                    "base64": base64.b64encode(response_body[:MAX_BODY_PREVIEW_BYTES]).decode("ascii"),
                    "base64Truncated": len(response_body) > MAX_BODY_PREVIEW_BYTES,
                },
            }
    except urllib.error.HTTPError as exc:
        error_body = exc.read()
        body_text, body_truncated = _text_preview(error_body.decode("utf-8", errors="replace"))
        return {
            "url": url,
            "finalUrl": exc.geturl(),
            "method": method,
            "statusCode": exc.code,
            "reason": exc.reason,
            "verifyTls": verify_tls,
            "timeoutSeconds": timeout_seconds,
            "latencyMs": round((time.perf_counter() - started_at) * 1000, 3),
            "headers": dict(exc.headers.items()),
            "body": {
                "sizeBytes": len(error_body),
                "text": body_text,
                "textTruncated": body_truncated,
                "base64": base64.b64encode(error_body[:MAX_BODY_PREVIEW_BYTES]).decode("ascii"),
                "base64Truncated": len(error_body) > MAX_BODY_PREVIEW_BYTES,
            },
        }
    except (urllib.error.URLError, ValueError, ssl.SSLError, OSError) as exc:
        raise ValueError(f"HTTP probe failed for '{url}': {exc}") from exc


def _tool_tls_probe(
    arguments: dict[str, Any],
    request: Request,
    *,
    rpc_payload: dict[str, Any],
    raw_body: bytes,
) -> dict[str, Any]:
    host = arguments.get("host")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("Argument 'host' must be a non-empty string.")

    port = _coerce_int(arguments.get("port"), name="port", default=443, minimum=1, maximum=65535)
    server_name = str(arguments.get("serverName") or host)
    verify_certificate = _coerce_bool(arguments.get("verifyCertificate"), default=False)
    timeout_seconds = _coerce_float(
        arguments.get("timeoutSeconds"),
        name="timeoutSeconds",
        default=DEFAULT_TIMEOUT_SECONDS,
        minimum=0.1,
        maximum=60.0,
    )

    ssl_context = ssl.create_default_context() if verify_certificate else ssl._create_unverified_context()
    started_at = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as tcp_connection:
            with ssl_context.wrap_socket(tcp_connection, server_hostname=server_name) as tls_connection:
                peer_cert = tls_connection.getpeercert()
                peer_cert_der = tls_connection.getpeercert(binary_form=True)
                local_host, local_port = tls_connection.getsockname()
                remote_host, remote_port = tls_connection.getpeername()
                return {
                    "host": host,
                    "port": port,
                    "serverName": server_name,
                    "verifyCertificate": verify_certificate,
                    "timeoutSeconds": timeout_seconds,
                    "latencyMs": round((time.perf_counter() - started_at) * 1000, 3),
                    "tlsVersion": tls_connection.version(),
                    "cipher": tls_connection.cipher(),
                    "localAddress": {"host": local_host, "port": local_port},
                    "remoteAddress": {"host": remote_host, "port": remote_port},
                    "peerCertificate": peer_cert,
                    "peerCertificateSha256": hashlib.sha256(peer_cert_der).hexdigest(),
                }
    except (ssl.SSLError, OSError, ValueError) as exc:
        raise ValueError(f"TLS probe failed for {host}:{port}: {exc}") from exc


TOOLS = [
    {
        "name": "get_caller_ip",
        "description": "Return the IP address of the MCP client calling this server.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "add_numbers",
        "description": "Add two numbers and return the sum.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    },
    {
        "name": "utc_now",
        "description": "Return the current UTC timestamp from the server.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "debug_request_context",
        "description": (
            "Return a detailed snapshot of the inbound HTTP request and MCP payload, "
            "including headers, auth values/tokens, query params, path, and raw body."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_request_summary",
        "description": "Return a focused summary of the inbound request, caller, and forwarding chain.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_request_headers",
        "description": "Return request headers and raw header pairs exactly as the app received them.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_request_body",
        "description": "Return the inbound request body as text, base64, size, and parsed JSON when possible.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_request_auth",
        "description": "Return auth-related headers, cookies, query params, and decoded JWT content.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_mcp_envelope",
        "description": "Return the parsed MCP/JSON-RPC envelope for the current request.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_runtime",
        "description": "Return runtime, process, version, uptime, and server metadata.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_routes",
        "description": "Return the registered FastAPI routes and methods exposed by the server.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_environment",
        "description": "Return environment variables, optionally filtered by prefix or specific names.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prefix": {"type": "string"},
                "names": {"type": "array", "items": {"type": "string"}},
                "includeValues": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "inspect_recent_calls",
        "description": "Return the most recent captured MCP/discovery calls and their telemetry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "minimum": 1, "maximum": MAX_HISTORY_SIZE},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_server_info",
        "description": "Return server identity, protocol, uptime, route count, and history settings.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "echo_payload",
        "description": "Echo back an arbitrary payload with timestamp and caller metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "payload": {},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "decode_jwt",
        "description": "Decode a JWT-like token and return its header, payload, and signature segment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "token": {"type": "string"},
            },
            "required": ["token"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dns_resolve",
        "description": "Resolve a hostname from inside the container using the container's DNS path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hostname": {"type": "string"},
                "port": {"type": "integer"},
            },
            "required": ["hostname"],
            "additionalProperties": False,
        },
    },
    {
        "name": "tcp_probe",
        "description": "Attempt a TCP connection to a host and port and report latency and addresses.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "timeoutSeconds": {"type": "number"},
            },
            "required": ["host", "port"],
            "additionalProperties": False,
        },
    },
    {
        "name": "http_probe",
        "description": "Issue an HTTP request from inside the container and return status, headers, and body preview.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string"},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "body": {"type": "string"},
                "timeoutSeconds": {"type": "number"},
                "verifyTls": {"type": "boolean"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "tls_probe",
        "description": "Attempt a TLS handshake and return certificate, cipher, and version details.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "serverName": {"type": "string"},
                "timeoutSeconds": {"type": "number"},
                "verifyCertificate": {"type": "boolean"},
            },
            "required": ["host"],
            "additionalProperties": False,
        },
    },
]


TOOL_HANDLERS = {
    "get_caller_ip": _tool_get_caller_ip,
    "add_numbers": _tool_add_numbers,
    "utc_now": _tool_utc_now,
    "debug_request_context": _tool_debug_request_context,
    "inspect_request_summary": _tool_inspect_request_summary,
    "inspect_request_headers": _tool_inspect_request_headers,
    "inspect_request_body": _tool_inspect_request_body,
    "inspect_request_auth": _tool_inspect_request_auth,
    "inspect_mcp_envelope": _tool_inspect_mcp_envelope,
    "inspect_runtime": _tool_inspect_runtime,
    "inspect_routes": _tool_inspect_routes,
    "inspect_environment": _tool_inspect_environment,
    "inspect_recent_calls": _tool_inspect_recent_calls,
    "get_server_info": _tool_get_server_info,
    "echo_payload": _tool_echo_payload,
    "decode_jwt": _tool_decode_jwt,
    "dns_resolve": _tool_dns_resolve,
    "tcp_probe": _tool_tcp_probe,
    "http_probe": _tool_http_probe,
    "tls_probe": _tool_tls_probe,
}


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


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "version": APP_VERSION}


def _mcp_discovery_payload() -> dict[str, Any]:
    return {"name": APP_NAME, "transport": MCP_TRANSPORT}


@app.get("/dashboard")
def dashboard() -> HTMLResponse:
    _ensure_dashboard_enabled()
    return HTMLResponse(_build_dashboard_html())


@app.get("/api/calls")
def api_calls(count: int | None = None) -> dict[str, Any]:
    _ensure_dashboard_enabled()
    requested = count if count is not None else _HISTORY_LIMIT
    count_value = max(1, min(requested, _HISTORY_LIMIT))
    return {"count": count_value, "calls": _get_recent_calls(count_value)}


@app.get("/api/calls/latest")
def api_calls_latest() -> dict[str, Any]:
    _ensure_dashboard_enabled()
    calls = _get_recent_calls(1)
    if not calls:
        raise HTTPException(status_code=404, detail="No calls captured yet.")
    return calls[0]


@app.get("/api/calls/{call_id}")
def api_call_by_id(call_id: str) -> dict[str, Any]:
    _ensure_dashboard_enabled()
    entry = _get_call_by_id(call_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Call '{call_id}' was not found.")
    return entry


@app.get("/api/runtime")
def api_runtime() -> dict[str, Any]:
    _ensure_dashboard_enabled()
    return {"generatedAtUtc": _utc_now(), "serverInfo": _server_info(), "routes": _route_snapshot()}


@app.get("/")
@app.get("/mcp")
@app.get("/mcp/")
@app.get("/mcp/mcp")
@app.get("/mcp/mcp/")
@app.get("/v1/mcp")
@app.get("/v1/mcp/")
def mcp_discovery(request: Request) -> dict[str, Any]:
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


@app.post("/")
@app.post("/mcp")
@app.post("/mcp/")
@app.post("/mcp/mcp")
@app.post("/mcp/mcp/")
@app.post("/v1/mcp")
@app.post("/v1/mcp/")
async def mcp_endpoint(request: Request) -> JSONResponse:
    return await _mcp_jsonrpc(request)


# Some MCP clients normalize or rewrite endpoint paths. Accept any GET/POST path and
# serve MCP discovery/JSON-RPC to avoid false 404s caused purely by path shape.
@app.get("/{_remaining_path:path}")
def mcp_discovery_fallback(_remaining_path: str, request: Request) -> dict[str, Any]:
    return mcp_discovery(request)


@app.post("/{_remaining_path:path}")
async def mcp_endpoint_fallback(_remaining_path: str, request: Request) -> JSONResponse:
    return await _mcp_jsonrpc(request)


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("server:app", host=host, port=port, log_level="info")
