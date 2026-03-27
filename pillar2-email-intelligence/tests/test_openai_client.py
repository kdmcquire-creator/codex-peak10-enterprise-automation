"""Tests for the Azure OpenAI client wrapper (offline — no real API calls)."""

from __future__ import annotations

import pytest
from email_intel.openai_client import (
    AzureOpenAIClient,
    OpenAIClientConfig,
    reset_openai_client,
    get_openai_client,
)


class TestOpenAIClientOffline:
    def test_unavailable_without_endpoint(self):
        client = AzureOpenAIClient(config=OpenAIClientConfig())
        assert not client.is_available

    def test_triage_returns_none_when_unavailable(self):
        client = AzureOpenAIClient(config=OpenAIClientConfig())
        result = client.triage_email("test prompt")
        assert result is None

    def test_classify_returns_none_when_unavailable(self):
        client = AzureOpenAIClient(config=OpenAIClientConfig())
        result = client.classify_document("test prompt")
        assert result is None

    def test_draft_reply_returns_none_when_unavailable(self):
        client = AzureOpenAIClient(config=OpenAIClientConfig())
        result = client.generate_draft_reply("Re: Test", "Hello", "John")
        assert result is None

    def test_calendar_assist_returns_none_when_unavailable(self):
        client = AzureOpenAIClient(config=OpenAIClientConfig())
        result = client.assist_calendar_request("calendar prompt")
        assert result is None

    def test_usage_log_empty_when_unavailable(self):
        client = AzureOpenAIClient(config=OpenAIClientConfig())
        client.triage_email("test")
        assert client.total_tokens_used == 0
        assert len(client.usage_log) == 0

    def test_singleton_pattern(self):
        reset_openai_client()
        c1 = get_openai_client()
        c2 = get_openai_client()
        assert c1 is c2
        reset_openai_client()
