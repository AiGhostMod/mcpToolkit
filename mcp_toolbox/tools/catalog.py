from __future__ import annotations

from mcp_toolbox.config import MAX_HISTORY_SIZE

TOOLS = [
    {
        "name": "get_caller_ip",
        "description": (
            "Use when you need to verify caller source IP or proxy forwarding behavior. "
            "Returns the client IP as resolved from forwarding headers and connection metadata."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "add_numbers",
        "description": (
            "Use as a minimal tool-call sanity check when validating MCP wiring. "
            "Returns the numeric sum of inputs 'a' and 'b'."
        ),
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
        "description": (
            "Use to confirm the server is responsive and compare clock/timezone behavior. "
            "Returns the current UTC timestamp from the running container."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "debug_request_context",
        "description": (
            "Use for deep troubleshooting when you need the full inbound request and MCP context in one result. "
            "Returns headers, auth values/tokens, query params, path, body snapshots, envelope details, and runtime metadata."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_request_summary",
        "description": (
            "Use first for a quick request diagnostic without dumping everything. "
            "Returns a focused summary of method/path, caller identity hints, and forwarding chain details."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_request_headers",
        "description": (
            "Use when debugging missing/rewritten headers (auth, proxy, tracing, custom headers). "
            "Returns header keys/values and raw header pairs exactly as received by the app."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_request_body",
        "description": (
            "Use when payload format, encoding, or truncation issues are suspected. "
            "Returns body size plus text, base64, and parsed JSON views when available."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_request_auth",
        "description": (
            "Use for authentication debugging, especially when users ask to inspect token/JWT details. "
            "Returns auth-related headers/cookies/query params and decoded JWT header/payload when present."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_mcp_envelope",
        "description": (
            "Use when troubleshooting MCP protocol shape issues (method, id, params, notifications). "
            "Returns the parsed MCP/JSON-RPC envelope from the current request."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_runtime",
        "description": (
            "Use when verifying what is currently running in production/test (version, flags, uptime, process info). "
            "Returns runtime/process metadata and key server settings."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_routes",
        "description": (
            "Use when clients report 404/path mismatch issues and you need the authoritative route map. "
            "Returns all registered API paths and HTTP methods exposed by the server."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "inspect_environment",
        "description": (
            "Use when confirming deployment/runtime configuration values. "
            "Returns environment variables, optionally filtered by prefix or explicit names, with optional value redaction."
        ),
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
        "description": (
            "Use after a series of requests to review what recently hit the server and how it responded. "
            "Returns captured recent MCP/discovery calls with telemetry and timing."
        ),
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
        "description": (
            "Use for a concise health/capability snapshot without deep request detail. "
            "Returns server identity, protocol/version info, uptime, route count, and history settings."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "echo_payload",
        "description": (
            "Use to verify payload round-trip integrity through the MCP path. "
            "Returns your payload unchanged with timestamp and caller metadata."
        ),
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
        "description": (
            "Use when a user gives you a token and asks to view JWT claims/payload explicitly. "
            "Decodes a JWT-like string and returns header, payload, and signature segments without verification."
        ),
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
        "description": (
            "Use when outbound calls fail and you need to confirm DNS resolution from inside the running environment. "
            "Resolves a hostname (optionally with port) using the container's DNS path."
        ),
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
        "description": (
            "Use to test basic network reachability before HTTP/TLS debugging. "
            "Attempts a raw TCP connection to host:port and reports latency plus socket address details."
        ),
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
        "description": (
            "Use when validating outbound API access, response behavior, and egress networking from the container. "
            "Sends an HTTP request and returns status, headers, and a response body preview."
        ),
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
        "description": (
            "Use when diagnosing TLS/SSL issues (certificate, SNI, handshake, cipher/version mismatches). "
            "Attempts a TLS handshake and returns certificate and negotiated connection details."
        ),
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

