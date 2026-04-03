from __future__ import annotations

import base64
import hashlib
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from fastapi import Request

from mcp_toolbox.diagnostics.snapshots import text_preview

ToolHandler = Callable[..., dict[str, Any]]


def build_network_handlers(
    *,
    default_timeout_seconds: float,
    max_body_preview_bytes: int,
    text_preview_limit: int,
    coerce_bool: Callable[..., bool],
    coerce_float: Callable[..., float],
    coerce_headers: Callable[[Any], dict[str, str]],
    coerce_int: Callable[..., int],
) -> dict[str, ToolHandler]:
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

        port = coerce_int(arguments.get("port"), name="port", default=0, minimum=1, maximum=65535)
        timeout_seconds = coerce_float(
            arguments.get("timeoutSeconds"),
            name="timeoutSeconds",
            default=default_timeout_seconds,
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
        headers = coerce_headers(arguments.get("headers"))
        body = arguments.get("body")
        verify_tls = coerce_bool(arguments.get("verifyTls"), default=True)
        timeout_seconds = coerce_float(
            arguments.get("timeoutSeconds"),
            name="timeoutSeconds",
            default=default_timeout_seconds,
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
                body_text, body_truncated = text_preview(
                    response_body.decode("utf-8", errors="replace"),
                    limit=text_preview_limit,
                )
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
                        "base64": base64.b64encode(response_body[:max_body_preview_bytes]).decode("ascii"),
                        "base64Truncated": len(response_body) > max_body_preview_bytes,
                    },
                }
        except urllib.error.HTTPError as exc:
            error_body = exc.read()
            body_text, body_truncated = text_preview(
                error_body.decode("utf-8", errors="replace"),
                limit=text_preview_limit,
            )
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
                    "base64": base64.b64encode(error_body[:max_body_preview_bytes]).decode("ascii"),
                    "base64Truncated": len(error_body) > max_body_preview_bytes,
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

        port = coerce_int(arguments.get("port"), name="port", default=443, minimum=1, maximum=65535)
        server_name = str(arguments.get("serverName") or host)
        verify_certificate = coerce_bool(arguments.get("verifyCertificate"), default=False)
        timeout_seconds = coerce_float(
            arguments.get("timeoutSeconds"),
            name="timeoutSeconds",
            default=default_timeout_seconds,
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

    return {
        "dns_resolve": _tool_dns_resolve,
        "tcp_probe": _tool_tcp_probe,
        "http_probe": _tool_http_probe,
        "tls_probe": _tool_tls_probe,
    }

