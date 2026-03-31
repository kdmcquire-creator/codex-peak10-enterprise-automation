from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SERVER_NAME = "peak10-live-ops"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"
MAX_OUTPUT_CHARS = 50000

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AZURE_CONFIG_DIR = REPO_ROOT / ".azure-codex"
DEBUG_LOG_PATH = REPO_ROOT / "tools" / "live-ops-mcp" / "debug.log"


def _debug(message: str) -> None:
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


def _server_env() -> dict[str, str]:
    env = dict(os.environ)
    if DEFAULT_AZURE_CONFIG_DIR.exists() and not env.get("AZURE_CONFIG_DIR"):
        env["AZURE_CONFIG_DIR"] = str(DEFAULT_AZURE_CONFIG_DIR)
    return env


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    extra = len(text) - MAX_OUTPUT_CHARS
    return f"{text[:MAX_OUTPUT_CHARS]}\n...<truncated {extra} chars>"


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "run_powershell",
            "description": (
                "Run a PowerShell command in the local user environment. "
                "Useful for az, func, git, and file inspection commands."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "PowerShell command text to execute.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory.",
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Optional timeout in milliseconds.",
                        "minimum": 1000,
                        "maximum": 600000,
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
        {
            "name": "http_request",
            "description": (
                "Send an HTTP request directly from the local machine. "
                "Useful for Function App health checks and authenticated endpoint calls."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "HTTP method.",
                        "default": "GET",
                    },
                    "url": {
                        "type": "string",
                        "description": "Absolute URL to request.",
                    },
                    "headers": {
                        "type": "object",
                        "description": "Optional string headers.",
                        "additionalProperties": {"type": "string"},
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional raw request body.",
                    },
                    "json_body": {
                        "description": "Optional JSON body object or array.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Optional timeout in seconds.",
                        "minimum": 1,
                        "maximum": 600,
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    ]


def _resource_definitions() -> list[dict[str, Any]]:
    return [
        {
            "uri": "info://peak10-live-ops",
            "name": "Peak10 Live Ops MCP",
            "description": "Static metadata for the local live-ops MCP server.",
            "mimeType": "application/json",
        }
    ]


def _resource_payload() -> dict[str, Any]:
    azure_config_dir = os.environ.get("AZURE_CONFIG_DIR") or (
        str(DEFAULT_AZURE_CONFIG_DIR) if DEFAULT_AZURE_CONFIG_DIR.exists() else ""
    )
    return {
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "repo_root": str(REPO_ROOT),
        "azure_config_dir": azure_config_dir,
        "tools": [tool["name"] for tool in _tool_definitions()],
    }


def _success_payload(result: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(result, indent=2, ensure_ascii=True)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": result,
        "isError": False,
    }


def _error_payload(message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"success": False, "error": message}
    if details:
        result.update(details)
    text = json.dumps(result, indent=2, ensure_ascii=True)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": result,
        "isError": True,
    }


def _run_powershell(arguments: dict[str, Any]) -> dict[str, Any]:
    command = str(arguments["command"])
    cwd = str(arguments.get("cwd") or REPO_ROOT)
    timeout_ms = int(arguments.get("timeout_ms") or 120000)
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=cwd,
        env=_server_env(),
        capture_output=True,
        text=True,
        timeout=timeout_ms / 1000,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "success": completed.returncode == 0,
        "exit_code": completed.returncode,
        "cwd": cwd,
        "stdout": _truncate(completed.stdout),
        "stderr": _truncate(completed.stderr),
    }


def _http_request(arguments: dict[str, Any]) -> dict[str, Any]:
    method = str(arguments.get("method") or "GET").upper()
    url = str(arguments["url"])
    headers = {str(k): str(v) for k, v in dict(arguments.get("headers") or {}).items()}
    timeout_seconds = int(arguments.get("timeout_seconds") or 60)
    body = arguments.get("body")
    json_body = arguments.get("json_body")

    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif body is not None:
        data = str(body).encode("utf-8")

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return {
                "success": True,
                "status_code": response.status,
                "headers": dict(response.headers.items()),
                "body": _truncate(response_body),
            }
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        return {
            "success": False,
            "status_code": exc.code,
            "headers": dict(exc.headers.items()),
            "body": _truncate(error_body),
        }


def _handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "run_powershell":
        return _success_payload(_run_powershell(arguments))
    if name == "http_request":
        return _success_payload(_http_request(arguments))
    return _error_payload(f"Unknown tool '{name}'")


def _read_message() -> dict[str, Any] | None:
    first_line = sys.stdin.buffer.readline()
    _debug(f"first_line={first_line!r}")
    if not first_line:
        return None

    stripped = first_line.strip()
    if not stripped:
        return _read_message()

    # Support newline-delimited JSON-RPC in addition to Content-Length framing.
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        return json.loads(stripped.decode("utf-8"))

    headers: dict[str, str] = {}
    line = first_line
    while True:
        if line in (b"\r\n", b"\n"):
            break
        key, _, value = line.decode("utf-8").partition(":")
        headers[key.strip().lower()] = value.strip()
        line = sys.stdin.buffer.readline()
        if not line:
            return None

    content_length = int(headers.get("content-length", "0"))
    if content_length <= 0:
        return None
    body = sys.stdin.buffer.read(content_length)
    return json.loads(body.decode("utf-8"))


def _write_message(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _response(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def main() -> int:
    _debug("server_start")
    while True:
        message = _read_message()
        if message is None:
            _debug("server_end")
            return 0

        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}
        _debug(f"method={method!r} id={msg_id!r}")

        try:
            if method == "initialize":
                requested_protocol = str(params.get("protocolVersion") or PROTOCOL_VERSION)
                result = {
                    "protocolVersion": requested_protocol,
                    "capabilities": {
                        "tools": {},
                        "resources": {},
                    },
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                }
                if msg_id is not None:
                    _write_message(_response(msg_id, result))
                continue

            if method == "notifications/initialized":
                continue

            if method == "ping":
                if msg_id is not None:
                    _write_message(_response(msg_id, {}))
                continue

            if method == "tools/list":
                if msg_id is not None:
                    _write_message(_response(msg_id, {"tools": _tool_definitions()}))
                continue

            if method == "resources/list":
                if msg_id is not None:
                    _write_message(_response(msg_id, {"resources": _resource_definitions()}))
                continue

            if method == "resources/read":
                uri = str(params.get("uri", ""))
                if uri != "info://peak10-live-ops":
                    if msg_id is not None:
                        _write_message(_error(msg_id, -32002, f"Unknown resource: {uri}"))
                    continue
                contents = [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(_resource_payload(), indent=2, ensure_ascii=True),
                    }
                ]
                if msg_id is not None:
                    _write_message(_response(msg_id, {"contents": contents}))
                continue

            if method == "tools/call":
                name = str(params.get("name", ""))
                arguments = dict(params.get("arguments") or {})
                result = _handle_tool_call(name, arguments)
                if msg_id is not None:
                    _write_message(_response(msg_id, result))
                continue

            if msg_id is not None:
                _write_message(_error(msg_id, -32601, f"Method not found: {method}"))
        except subprocess.TimeoutExpired as exc:
            _debug(f"timeout={exc.timeout!r}")
            if msg_id is not None:
                _write_message(
                    _response(
                        msg_id,
                        _error_payload(
                            "Command timed out",
                            details={
                                "timeout_seconds": exc.timeout,
                                "stdout": _truncate(exc.stdout or ""),
                                "stderr": _truncate(exc.stderr or ""),
                            },
                        ),
                    )
                )
        except Exception as exc:  # pragma: no cover - defensive server path
            traceback_text = traceback.format_exc()
            _debug(f"exception={traceback_text}")
            if msg_id is not None:
                _write_message(
                    _response(
                        msg_id,
                        _error_payload(
                            str(exc),
                            details={"traceback": _truncate(traceback_text)},
                        ),
                    )
                )


if __name__ == "__main__":
    raise SystemExit(main())
