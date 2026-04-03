from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse


def register_diagnostics_routes(
    app: FastAPI,
    *,
    ensure_dashboard_enabled: Callable[[], None],
    history_limit: int,
    get_recent_calls: Callable[[int], list[dict[str, Any]]],
    get_call_by_id: Callable[[str], dict[str, Any] | None],
    utc_now: Callable[[], str],
    server_info: Callable[[], dict[str, Any]],
    route_snapshot: Callable[[], dict[str, Any]],
    build_dashboard_html: Callable[[], str],
) -> None:
    @app.get("/dashboard")
    def dashboard() -> HTMLResponse:
        ensure_dashboard_enabled()
        return HTMLResponse(build_dashboard_html())

    @app.get("/api/calls")
    def api_calls(count: int | None = None) -> dict[str, Any]:
        ensure_dashboard_enabled()
        requested = count if count is not None else history_limit
        count_value = max(1, min(requested, history_limit))
        return {"count": count_value, "calls": get_recent_calls(count_value)}

    @app.get("/api/calls/latest")
    def api_calls_latest() -> dict[str, Any]:
        ensure_dashboard_enabled()
        calls = get_recent_calls(1)
        if not calls:
            raise HTTPException(status_code=404, detail="No calls captured yet.")
        return calls[0]

    @app.get("/api/calls/{call_id}")
    def api_call_by_id(call_id: str) -> dict[str, Any]:
        ensure_dashboard_enabled()
        entry = get_call_by_id(call_id)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Call '{call_id}' was not found.")
        return entry

    @app.get("/api/runtime")
    def api_runtime() -> dict[str, Any]:
        ensure_dashboard_enabled()
        return {"generatedAtUtc": utc_now(), "serverInfo": server_info(), "routes": route_snapshot()}

