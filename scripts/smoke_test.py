#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from typing import Any


def _get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_text(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.status, response.read().decode("utf-8")


def _post_json(url: str, payload: dict[str, Any]) -> Any:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _call_tool(base_url: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    response = _post_json(f"{base_url}/mcp", payload)
    if "error" in response:
        raise RuntimeError(response["error"])
    return json.loads(response["result"]["content"][0]["text"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the standalone MCP server.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    try:
        health = _get_json(f"{base_url}/healthz")
        dashboard_status, dashboard_text = _get_text(f"{base_url}/dashboard")
        initialize = _post_json(
            f"{base_url}/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        tools = _post_json(
            f"{base_url}/mcp",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        runtime = _call_tool(base_url, "inspect_runtime", {})
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    tool_names = [tool["name"] for tool in tools["result"]["tools"]]
    summary = {
        "ok": True,
        "healthz": health,
        "dashboardStatus": dashboard_status,
        "dashboardHasRecentCalls": "Recent calls" in dashboard_text,
        "serverInfo": initialize["result"]["serverInfo"],
        "toolCount": len(tool_names),
        "toolNames": tool_names,
        "runtimeVersion": runtime["runtime"]["appVersion"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
