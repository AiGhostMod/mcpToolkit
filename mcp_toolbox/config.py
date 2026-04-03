from __future__ import annotations

import os
from typing import Any


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

