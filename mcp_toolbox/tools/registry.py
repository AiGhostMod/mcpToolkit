from __future__ import annotations

from typing import Any, Callable

from mcp_toolbox.tools.handlers_core import build_core_handlers
from mcp_toolbox.tools.handlers_inspect import build_inspect_handlers
from mcp_toolbox.tools.handlers_network import build_network_handlers

ToolHandler = Callable[..., dict[str, Any]]


def build_tool_handlers(
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
    default_timeout_seconds: float,
    coerce_bool: Callable[..., bool],
    coerce_float: Callable[..., float],
    coerce_headers: Callable[[Any], dict[str, str]],
    coerce_int: Callable[..., int],
    coerce_names: Callable[[Any], list[str]],
) -> dict[str, ToolHandler]:
    handlers: dict[str, ToolHandler] = {}
    handlers.update(
        build_core_handlers(
            utc_now=utc_now,
            server_info=server_info,
        )
    )
    handlers.update(
        build_inspect_handlers(
            utc_now=utc_now,
            runtime_snapshot=runtime_snapshot,
            server_info=server_info,
            route_snapshot=route_snapshot,
            environment_snapshot=environment_snapshot,
            get_recent_calls=get_recent_calls,
            history_limit=history_limit,
            auth_match_hints=auth_match_hints,
            text_preview_limit=text_preview_limit,
            max_body_preview_bytes=max_body_preview_bytes,
            coerce_bool=coerce_bool,
            coerce_int=coerce_int,
            coerce_names=coerce_names,
        )
    )
    handlers.update(
        build_network_handlers(
            default_timeout_seconds=default_timeout_seconds,
            max_body_preview_bytes=max_body_preview_bytes,
            text_preview_limit=text_preview_limit,
            coerce_bool=coerce_bool,
            coerce_float=coerce_float,
            coerce_headers=coerce_headers,
            coerce_int=coerce_int,
        )
    )
    return handlers

