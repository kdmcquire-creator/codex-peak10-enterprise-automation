"""Tests for cross-pillar HTTP clients."""

from __future__ import annotations

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
