"""Tests for the Cosmos DB persistence layer (in-memory fallback)."""

from __future__ import annotations

import pytest
from email_intel.cosmos_client import CosmosDataStore, reset_store, get_store


@pytest.fixture
def store():
    """Fresh in-memory store for each test."""
    return CosmosDataStore()


class TestInMemoryFallback:
    def test_uses_memory_when_no_connection(self, store):
        assert not store.is_connected

    def test_singleton_pattern(self):
        reset_store()
        s1 = get_store()
        s2 = get_store()
        assert s1 is s2
        reset_store()


class TestTriageResults:
    def test_save_and_retrieve(self, store):
        data = {"message_id": "msg-1", "category": "deal_related", "urgency": 2}
        saved = store.save_triage_result(data)
        assert saved["id"] == "msg-1"
        assert "saved_at" in saved
        assert "partition_date" in saved

    def test_get_triage_result(self, store):
        store.save_triage_result({"message_id": "msg-2", "category": "vendor_ap"})
        result = store.get_triage_result("msg-2")
        assert result is not None
        assert result["category"] == "vendor_ap"

    def test_get_missing_returns_none(self, store):
        assert store.get_triage_result("nonexistent") is None

    def test_query_returns_list(self, store):
        store.save_triage_result({"message_id": "msg-a", "category": "legal"})
        store.save_triage_result({"message_id": "msg-b", "category": "operations"})
        results = store.query_triage_results()
        assert len(results) >= 2


class TestDraftResponses:
    def test_save_and_get_draft(self, store):
        draft = {
            "draft_id": "draft-1",
            "message_id": "msg-1",
            "subject": "Re: Test",
            "body": "Hello",
        }
        store.save_draft(draft)
        result = store.get_draft("draft-1", "msg-1")
        assert result is not None
        assert result["body"] == "Hello"

    def test_get_drafts_for_message(self, store):
        store.save_draft({"draft_id": "d1", "message_id": "msg-1", "body": "v1"})
        store.save_draft({"draft_id": "d2", "message_id": "msg-1", "body": "v2"})
        drafts = store.get_drafts_for_message("msg-1")
        assert len(drafts) >= 2

    def test_find_draft_by_id(self, store):
        store.save_draft({"draft_id": "d-find", "message_id": "msg-9", "body": "v1"})

        draft = store.find_draft_by_id("d-find")

        assert draft is not None
        assert draft["message_id"] == "msg-9"

    def test_delete_draft(self, store):
        store.save_draft({"draft_id": "d-del", "message_id": "msg-1", "body": "bye"})
        store.delete_draft("d-del", "msg-1")
        assert store.get_draft("d-del", "msg-1") is None


class TestDocuments:
    def test_save_and_get_document(self, store):
        doc = {"document_id": "doc-1", "filename": "invoice.pdf", "classification": {}}
        store.save_document(doc)
        result = store.get_document("doc-1")
        assert result is not None
        assert result["filename"] == "invoice.pdf"

    def test_get_missing_document(self, store):
        assert store.get_document("missing") is None


class TestCorrections:
    def test_save_correction(self, store):
        correction = {
            "correction_id": "c-1",
            "document_id": "doc-1",
            "original_type": "contract",
            "corrected_type": "amendment",
        }
        saved = store.save_correction(correction)
        assert "saved_at" in saved

    def test_get_corrections_for_type(self, store):
        store.save_correction({
            "correction_id": "c-2",
            "original_type": "contract",
            "corrected_type": "nda",
        })
        results = store.get_corrections_for_type("contract")
        assert len(results) >= 1
