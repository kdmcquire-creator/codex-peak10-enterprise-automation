"""Tests for cross-pillar HTTP clients."""

from __future__ import annotations

import io
import urllib.error

from afa_engine.pillar_clients import DocumentAiClient, DocumentAiClientConfig


def test_document_ai_client_prefers_primary_env_var(monkeypatch):
    monkeypatch.setenv("PILLAR3_DOCUMENT_AI_URL", "https://pillar3.example/")
    monkeypatch.setenv("PILLAR3_BASE_URL", "https://legacy.example/")
    monkeypatch.delenv("PILLAR3_DOCUMENT_AI_KEY", raising=False)

    client = DocumentAiClient()

    assert client.is_available is False
    assert client._config.base_url == "https://pillar3.example"


def test_document_ai_client_falls_back_to_legacy_env_var(monkeypatch):
    monkeypatch.delenv("PILLAR3_DOCUMENT_AI_URL", raising=False)
    monkeypatch.setenv("PILLAR3_BASE_URL", "https://legacy.example/")
    monkeypatch.setenv("PILLAR3_DOCUMENT_AI_KEY", "abc123")

    client = DocumentAiClient()

    assert client.is_available is True
    assert client._config.base_url == "https://legacy.example"
    assert client._config.function_key == "abc123"


def test_stage_document_returns_empty_when_unavailable():
    client = DocumentAiClient(config=DocumentAiClientConfig(base_url="", function_key=""))

    assert client.stage_document({"filename": "test.txt"}) == {}


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_stage_document_retries_transient_http_errors(monkeypatch):
    attempts = {"count": 0}

    def fake_urlopen(request, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                503,
                "Service Unavailable",
                hdrs=None,
                fp=io.BytesIO(b'{"success": false}'),
            )
        return _FakeResponse(b'{"success": true, "document": {"document_id": "doc-1"}}')

    sleep_calls: list[float] = []
    monkeypatch.setattr("afa_engine.pillar_clients.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("afa_engine.pillar_clients.time.sleep", sleep_calls.append)

    client = DocumentAiClient(
        config=DocumentAiClientConfig(
            base_url="https://pillar3.example",
            function_key="abc123",
            max_attempts=3,
            retry_backoff_seconds=0.25,
        )
    )

    response = client.stage_document({"filename": "test.txt"})

    assert response["success"] is True
    assert attempts["count"] == 2
    assert sleep_calls == [0.25]


def test_stage_document_does_not_retry_non_transient_http_errors(monkeypatch):
    attempts = {"count": 0}

    def fake_urlopen(request, timeout):
        attempts["count"] += 1
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"success": false, "error": "invalid payload"}'),
        )

    sleep_calls: list[float] = []
    monkeypatch.setattr("afa_engine.pillar_clients.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("afa_engine.pillar_clients.time.sleep", sleep_calls.append)

    client = DocumentAiClient(
        config=DocumentAiClientConfig(
            base_url="https://pillar3.example",
            function_key="abc123",
            max_attempts=3,
        )
    )

    try:
        client.stage_document({"filename": "test.txt"})
        assert False, "Expected HTTPError to be raised"
    except urllib.error.HTTPError as exc:
        assert exc.code == 400

    assert attempts["count"] == 1
    assert sleep_calls == []
