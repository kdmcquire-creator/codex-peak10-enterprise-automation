"""Tests for the Document Intelligence client wrapper (offline)."""

from __future__ import annotations

import pytest
from email_intel.doc_intelligence import (
    DocumentIntelligenceClient,
    ExtractionResult,
    suggest_extraction_mode,
    reset_doc_intelligence_client,
    get_doc_intelligence_client,
)


class TestDocIntelligenceOffline:
    def test_unavailable_without_endpoint(self):
        client = DocumentIntelligenceClient(endpoint="", api_key="")
        assert not client.is_available

    def test_unavailable_without_api_key(self):
        client = DocumentIntelligenceClient(
            endpoint="https://example.cognitiveservices.azure.com",
            api_key="",
        )
        assert not client.is_available

    def test_extract_text_returns_empty_when_unavailable(self):
        client = DocumentIntelligenceClient(endpoint="", api_key="")
        result = client.extract_text(b"fake pdf bytes")
        assert isinstance(result, ExtractionResult)
        assert result.text == ""
        assert result.page_count == 0

    def test_extract_invoice_returns_empty_when_unavailable(self):
        client = DocumentIntelligenceClient(endpoint="", api_key="")
        result = client.extract_invoice(b"fake pdf bytes")
        assert result.text == ""

    def test_extract_receipt_returns_empty_when_unavailable(self):
        client = DocumentIntelligenceClient(endpoint="", api_key="")
        result = client.extract_receipt(b"fake pdf bytes")
        assert result.text == ""

    def test_singleton_pattern(self):
        reset_doc_intelligence_client()
        c1 = get_doc_intelligence_client()
        c2 = get_doc_intelligence_client()
        assert c1 is c2
        reset_doc_intelligence_client()


class TestExtractionModeSuggestion:
    def test_invoice_mode(self):
        assert suggest_extraction_mode("Invoice_HES_March2026.pdf") == "invoice"

    def test_receipt_mode(self):
        assert suggest_extraction_mode("Uber_Receipt_20260314.pdf") == "receipt"

    def test_text_mode(self):
        assert suggest_extraction_mode("Contract_DrillCo_MSA.pdf") == "text"
