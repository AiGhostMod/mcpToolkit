from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from fastapi import Request


def extract_client_ip(request: Request) -> str:
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


def decode_jwt_token(raw_value: str | None) -> dict[str, Any] | None:
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


def extract_auth_details(request: Request, *, auth_match_hints: tuple[str, ...]) -> dict[str, Any]:
    normalized_headers = {key.lower(): value for key, value in request.headers.items()}
    auth_related_headers = {
        key: value for key, value in normalized_headers.items() if any(hint in key for hint in auth_match_hints)
    }

    auth_related_query_params: dict[str, list[str]] = {}
    for key, value in request.query_params.multi_items():
        lower_key = key.lower()
        if any(hint in lower_key for hint in auth_match_hints):
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
            parsed_authorization["jwt"] = decode_jwt_token(credential)
        elif scheme_lower == "basic" and credential:
            try:
                parsed_authorization["basicDecoded"] = base64.b64decode(credential.encode("ascii")).decode(
                    "utf-8",
                    errors="replace",
                )
            except (ValueError, binascii.Error) as exc:
                parsed_authorization["basicDecodeError"] = str(exc)
        elif credential:
            parsed_authorization["jwt"] = decode_jwt_token(credential)

    decoded_jwt_auth_headers = {
        key: decoded
        for key, value in auth_related_headers.items()
        for decoded in [decode_jwt_token(value)]
        if decoded
    }

    decoded_jwt_query_params: dict[str, list[dict[str, Any]]] = {}
    for key, values in auth_related_query_params.items():
        decoded_items = [decoded for decoded in (decode_jwt_token(value) for value in values) if decoded]
        if decoded_items:
            decoded_jwt_query_params[key] = decoded_items

    cookie_map = dict(request.cookies)
    decoded_jwt_cookies = {
        key: decoded
        for key, value in cookie_map.items()
        for decoded in [decode_jwt_token(value)]
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


def text_preview(text: str, *, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def body_snapshot(
    raw_body: bytes,
    parsed_json: Any,
    *,
    text_preview_limit: int,
    max_body_preview_bytes: int,
) -> dict[str, Any]:
    raw_body_text = raw_body.decode("utf-8", errors="replace")
    text_value, text_truncated = text_preview(raw_body_text, limit=text_preview_limit)
    base64_limit = min(len(raw_body), max_body_preview_bytes)
    base64_value = base64.b64encode(raw_body[:base64_limit]).decode("ascii")

    return {
        "sizeBytes": len(raw_body),
        "text": text_value,
        "textTruncated": text_truncated,
        "base64": base64_value,
        "base64Truncated": len(raw_body) > max_body_preview_bytes,
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


def request_snapshot(request: Request) -> dict[str, Any]:
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
        "callerIp": extract_client_ip(request),
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


def mcp_snapshot(rpc_payload: Any, tool_arguments: dict[str, Any] | None) -> dict[str, Any]:
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


def scope_snapshot(request: Request) -> dict[str, Any]:
    return {
        "type": request.scope.get("type"),
        "asgi": request.scope.get("asgi"),
        "extensions": request.scope.get("extensions"),
        "client": request.scope.get("client"),
        "server": request.scope.get("server"),
    }


def request_debug_snapshot(
    request: Request,
    *,
    rpc_payload: Any,
    tool_arguments: dict[str, Any],
    raw_body: bytes,
    utc_now: str,
    runtime_snapshot: dict[str, Any],
    auth_match_hints: tuple[str, ...],
    text_preview_limit: int,
    max_body_preview_bytes: int,
) -> dict[str, Any]:
    parsed_json = rpc_payload if isinstance(rpc_payload, (dict, list)) else None
    return {
        "timestampUtc": utc_now,
        "request": request_snapshot(request),
        "body": body_snapshot(
            raw_body,
            parsed_json,
            text_preview_limit=text_preview_limit,
            max_body_preview_bytes=max_body_preview_bytes,
        ),
        "mcp": mcp_snapshot(rpc_payload, tool_arguments),
        "auth": extract_auth_details(request, auth_match_hints=auth_match_hints),
        "runtime": runtime_snapshot,
        "scope": scope_snapshot(request),
    }

