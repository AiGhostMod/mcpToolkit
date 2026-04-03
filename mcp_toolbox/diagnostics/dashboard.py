from __future__ import annotations

import html
import json
from typing import Any


def dashboard_payload(
    *,
    utc_now: str,
    server_info: dict[str, Any],
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "generatedAtUtc": utc_now,
        "serverInfo": server_info,
        "calls": calls,
    }


def build_dashboard_html(app_name: str, payload: dict[str, Any]) -> str:
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
            call_sections.append(f"<details><summary>{title_html}</summary><pre>{body_html}</pre></details>")

    server_info = html.escape(json.dumps(payload["serverInfo"], indent=2, default=str))
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>{html.escape(app_name)} dashboard</title>
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
    <h1>{html.escape(app_name)} dashboard</h1>
    <p class="meta">Recent MCP/discovery calls captured in-memory. JSON views: <a href="/api/calls">/api/calls</a>, <a href="/api/calls/latest">/api/calls/latest</a>, <a href="/api/runtime">/api/runtime</a></p>
    <h2>Server info</h2>
    <pre>{server_info}</pre>
    <h2>Recent calls</h2>
    {''.join(call_sections)}
  </body>
</html>"""

