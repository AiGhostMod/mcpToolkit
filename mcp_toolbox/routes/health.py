from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def register_health_routes(app: FastAPI, *, app_version: str) -> None:
    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "version": app_version}

