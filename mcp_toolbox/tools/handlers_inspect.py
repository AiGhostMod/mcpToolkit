from __future__ import annotations

from typing import Any, Callable

from fastapi import Request

from mcp_toolbox.diagnostics.snapshots import (
    body_snapshot,
    extract_auth_details,
    extract_client_ip,
    mcp_snapshot,
    request_debug_snapshot,
    request_snapshot,
)

ToolHandler = Callable[..., dict[str, Any]]


def build_inspect_handlers(
    *,
    utc_now: Callable[[], str],
    runtime_snapshot: Callable[[], dict[str, Any]],
    server_info: Callable[[], dict[str, Any]],
    route_snapshot: Callable[[], dict[str, Any]],
    environment_snapshot: Callable[..., dict[str, Any]],
    get_recent_calls: Callable[[int], list[dict[str, Any]]],
    history_limit: int,
    auth_match_hints: tuple[str, ...],
    text_preview_limit: int,
    max_body_preview_bytes: int,
    coerce_bool: Callable[..., bool],
    coerce_int: Callable[..., int],
    coerce_names: Callable[[Any], list[str]],
) -> dict[str, ToolHandler]:
    def _tool_debug_request_context(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        return request_debug_snapshot(
            request,
            rpc_payload=rpc_payload,
            tool_arguments=arguments,
            raw_body=raw_body,
            utc_now=utc_now(),
            runtime_snapshot=runtime_snapshot(),
            auth_match_hints=auth_match_hints,
            text_preview_limit=text_preview_limit,
            max_body_preview_bytes=max_body_preview_bytes,
        )

    def _tool_inspect_request_summary(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        snapshot = request_snapshot(request)
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
        snapshot = request_snapshot(request)
        return {"headers": snapshot["headers"], "headersRaw": snapshot["headersRaw"]}

    def _tool_inspect_request_body(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        parsed_payload = rpc_payload if isinstance(rpc_payload, (dict, list)) else None
        return body_snapshot(
            raw_body,
            parsed_payload,
            text_preview_limit=text_preview_limit,
            max_body_preview_bytes=max_body_preview_bytes,
        )

    def _tool_inspect_request_auth(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        return {
            "timestampUtc": utc_now(),
            "path": request.url.path,
            "callerIp": extract_client_ip(request),
            "auth": extract_auth_details(request, auth_match_hints=auth_match_hints),
        }

    def _tool_inspect_mcp_envelope(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        return mcp_snapshot(rpc_payload, arguments)

    def _tool_inspect_runtime(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        return {"runtime": runtime_snapshot(), "serverInfo": server_info()}

    def _tool_inspect_routes(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        return route_snapshot()

    def _tool_inspect_environment(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        prefix = arguments.get("prefix")
        names = coerce_names(arguments.get("names"))
        include_values = coerce_bool(arguments.get("includeValues"), default=True)
        return environment_snapshot(prefix=prefix, names=names, include_values=include_values)

    def _tool_inspect_recent_calls(
        arguments: dict[str, Any],
        request: Request,
        *,
        rpc_payload: dict[str, Any],
        raw_body: bytes,
    ) -> dict[str, Any]:
        count = coerce_int(
            arguments.get("count"),
            name="count",
            default=history_limit,
            minimum=1,
            maximum=history_limit,
        )
        return {"count": count, "calls": get_recent_calls(count)}

    return {
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
    }

