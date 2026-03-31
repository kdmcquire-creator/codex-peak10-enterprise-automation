from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import server as core


HOST = "127.0.0.1"
PORT = 8765
HTTP_DEBUG_LOG = Path(__file__).with_name("http.debug.log")


def _debug(message: str) -> None:
    try:
        with HTTP_DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(encoded)


def _dispatch(message: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}
    _debug(f"method={method!r} id={msg_id!r}")

    requested_protocol = str(params.get("protocolVersion") or core.PROTOCOL_VERSION)

    if method == "initialize":
        return 200, core._response(
            msg_id,
            {
                "protocolVersion": requested_protocol,
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": core.SERVER_NAME, "version": core.SERVER_VERSION},
            },
        )

    if method == "notifications/initialized":
        return 202, None

    if method == "ping":
        return 200, core._response(msg_id, {})

    if method == "tools/list":
        return 200, core._response(msg_id, {"tools": core._tool_definitions()})

    if method == "resources/list":
        return 200, core._response(msg_id, {"resources": core._resource_definitions()})

    if method == "resources/read":
        uri = str(params.get("uri", ""))
        if uri != "info://peak10-live-ops":
            return 200, core._error(msg_id, -32002, f"Unknown resource: {uri}")
        return 200, core._response(
            msg_id,
            {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(core._resource_payload(), indent=2, ensure_ascii=True),
                    }
                ]
            },
        )

    if method == "tools/call":
        name = str(params.get("name", ""))
        arguments = dict(params.get("arguments") or {})
        return 200, core._response(msg_id, core._handle_tool_call(name, arguments))

    return 200, core._error(msg_id, -32601, f"Method not found: {method}")


class McpHandler(BaseHTTPRequestHandler):
    server_version = "Peak10LiveOpsMCP/0.1.0"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        _debug(f"GET {path}")
        if path == "/healthz":
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "server": core.SERVER_NAME,
                    "version": core.SERVER_VERSION,
                    "mcp_endpoint": f"http://{HOST}:{PORT}/mcp",
                },
            )
            return
        if path == "/mcp":
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "message": "POST JSON-RPC requests to /mcp",
                    "resource": "info://peak10-live-ops",
                },
            )
            return
        _json_response(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        _debug(f"POST {path}")
        if path != "/mcp":
            _json_response(self, 404, {"ok": False, "error": "not_found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8", errors="replace")
        _debug(f"body={body[:1000]}")
        try:
            message = json.loads(body)
        except json.JSONDecodeError as exc:
            _json_response(self, 400, {"ok": False, "error": f"invalid_json: {exc}"})
            return

        status, payload = _dispatch(message)
        if payload is None:
            self.send_response(status)
            self.end_headers()
            return
        _json_response(self, status, payload)

    def log_message(self, fmt: str, *args: Any) -> None:
        _debug(fmt % args)


def main() -> int:
    _debug("http_server_start")
    server = ThreadingHTTPServer((HOST, PORT), McpHandler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
