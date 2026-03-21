"""Tests for pure helper logic in the email intelligence function app."""

from __future__ import annotations

import base64
import json

import pytest

from email_intel.attachment_processing import ProcessedAttachment
from email_intel.cosmos_client import CosmosDataStore
from email_intel.document_models import (
    ClassificationConfidence,
    ClassificationResult,
    DocumentType,
    FilingRecommendation,
)
from email_intel.ingestion_service import ProcessedEmail
from email_intel.mailbox_ingestion import MailAttachment
from email_intel.models import EmailCategory, EmailMessage, TriageResult, UrgencyTier
from function_app import (
    _decode_file_bytes,
    _extract_document_text,
    _run_mailbox_ingestion,
    ingest_mailbox,
    poll_mailbox,
)


class FakeDocClient:
    def __init__(self, *, available: bool = True, text: str = "Extracted text") -> None:
        self.is_available = available
        self._text = text

    def extract_invoice(self, file_bytes: bytes):
        return type(
            "Extraction",
            (),
            {"text": self._text, "page_count": 1, "confidence": 0.91},
        )()

    def extract_receipt(self, file_bytes: bytes):
        return type(
            "Extraction",
            (),
            {"text": self._text, "page_count": 1, "confidence": 0.89},
        )()

    def extract_text(self, file_bytes: bytes, content_type: str = "application/pdf"):
        return type(
            "Extraction",
            (),
            {"text": self._text, "page_count": 2, "confidence": 0.75},
        )()


class FakeRequest:
    def __init__(self, body: dict | None = None) -> None:
        self._body = body
        self.params = {}
        self.route_params = {}

    def get_json(self):
        if self._body is None:
            raise ValueError("No JSON body")
        return self._body


class FakeMailboxIngestionService:
    def __init__(self, *, available: bool = True) -> None:
        self.is_available = available
        self.last_top: int | None = None
        self.last_mark_processed: bool | None = None

    def process_unread_messages(self, *, top: int = 25, mark_processed: bool = False):
        self.last_top = top
        self.last_mark_processed = mark_processed
        return [
            ProcessedEmail(
                email=EmailMessage(
                    message_id="msg-1",
                    subject="Invoice #123",
                    sender="billing@vendor.com",
                    sender_name="Vendor Billing",
                    recipients=["kmcquire@peak10energy.com"],
                    has_attachments=True,
                    attachment_names=["Invoice_123.pdf"],
                ),
                triage=TriageResult(
                    message_id="msg-1",
                    category=EmailCategory.VENDOR_AP,
                    urgency=UrgencyTier.STANDARD,
                    confidence=0.91,
                ),
                attachments=[
                    ProcessedAttachment(
                        attachment=MailAttachment(
                            attachment_id="att-1",
                            name="Invoice_123.pdf",
                            content_type="application/pdf",
                            content_bytes=b"pdf-bytes",
                        ),
                        classification=ClassificationResult(
                            document_type=DocumentType.INVOICE,
                            confidence=0.90,
                            confidence_level=ClassificationConfidence.HIGH,
                        ),
                        filing=FilingRecommendation(
                            recommended_path="01_CORPORATE/Finance/AP",
                            standardized_name="2026-03-21_Invoice_Test.pdf",
                            document_type=DocumentType.INVOICE,
                            confidence_level=ClassificationConfidence.HIGH,
                            requires_review=False,
                        ),
                        extraction_text="Invoice Number: 123",
                        extraction_summary={
                            "used_document_intelligence": False,
                            "mode": "invoice",
                            "content_type": "application/pdf",
                            "page_count": 0,
                            "confidence": 0.0,
                            "text_length": 19,
                        },
                        sharepoint_target={
                            "disposition": "filed",
                            "folder_path": "01_CORPORATE/Finance/AP",
                            "filename": "2026-03-21_Invoice_Test.pdf",
                            "full_path": "01_CORPORATE/Finance/AP/2026-03-21_Invoice_Test.pdf",
                            "reason": "governed_filing",
                        },
                        upload_result={
                            "attempted": False,
                            "uploaded": False,
                            "backend": "offline",
                            "reason": "sharepoint_unavailable",
                        },
                    )
                ],
                ai_used=False,
                marked_processed=mark_processed,
            )
        ]


class FakeTimerRequest:
    def __init__(self, *, past_due: bool = False) -> None:
        self.past_due = past_due


def test_decode_file_bytes_round_trip():
    raw = b"hello world"
    payload = base64.b64encode(raw).decode("ascii")
    assert _decode_file_bytes(payload) == raw


def test_decode_file_bytes_rejects_invalid_payload():
    with pytest.raises(ValueError, match="file_bytes_base64"):
        _decode_file_bytes("not-base64")


def test_extract_document_text_uses_invoice_mode(monkeypatch):
    monkeypatch.setattr("function_app.get_doc_intelligence_client", lambda: FakeDocClient())
    payload = base64.b64encode(b"fake pdf").decode("ascii")

    text, summary = _extract_document_text(
        filename="Invoice_123.pdf",
        file_bytes_base64=payload,
        content_type="application/pdf",
    )

    assert text == "Extracted text"
    assert summary["used_document_intelligence"] is True
    assert summary["mode"] == "invoice"


def test_extract_document_text_handles_unavailable_client(monkeypatch):
    monkeypatch.setattr(
        "function_app.get_doc_intelligence_client",
        lambda: FakeDocClient(available=False, text=""),
    )
    payload = base64.b64encode(b"fake pdf").decode("ascii")

    text, summary = _extract_document_text(
        filename="Contract.pdf",
        file_bytes_base64=payload,
        content_type="application/pdf",
    )

    assert text == ""
    assert summary["used_document_intelligence"] is False
    assert summary["mode"] == "text"


def test_ingest_mailbox_returns_processed_messages(monkeypatch):
    store = CosmosDataStore(connection_string="")
    monkeypatch.setattr("function_app.MailboxIngestionService", FakeMailboxIngestionService)
    monkeypatch.setattr("function_app.get_store", lambda: store)

    response = ingest_mailbox(FakeRequest({"top": 5, "mark_processed": True}))
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["processed_count"] == 1
    assert payload["messages"][0]["email"]["message_id"] == "msg-1"
    assert payload["messages"][0]["attachments"][0]["sharepoint_target"]["folder_path"] == "01_CORPORATE/Finance/AP"
    assert store.count_triage_results() == 1
    assert store.count_documents() == 1


def test_run_mailbox_ingestion_raises_when_graph_is_unavailable():
    store = CosmosDataStore(connection_string="")

    with pytest.raises(RuntimeError, match="Graph mailbox configuration"):
        _run_mailbox_ingestion(
            top=5,
            mark_processed=False,
            service=FakeMailboxIngestionService(available=False),
            store=store,
        )


def test_run_mailbox_ingestion_persists_results():
    store = CosmosDataStore(connection_string="")
    service = FakeMailboxIngestionService()

    payload = _run_mailbox_ingestion(
        top=3,
        mark_processed=True,
        service=service,
        store=store,
    )

    assert len(payload) == 1
    assert service.last_top == 3
    assert service.last_mark_processed is True
    assert store.count_triage_results() == 1
    assert store.count_documents() == 1


def test_poll_mailbox_skips_when_disabled(monkeypatch):
    calls: list[tuple[int, bool]] = []
    monkeypatch.setenv("MAILBOX_POLL_ENABLED", "false")
    monkeypatch.setattr(
        "function_app._run_mailbox_ingestion",
        lambda top, mark_processed: calls.append((top, mark_processed)),
    )

    poll_mailbox(FakeTimerRequest())

    assert calls == []


def test_poll_mailbox_uses_configured_settings(monkeypatch):
    calls: list[tuple[int, bool]] = []
    monkeypatch.setenv("MAILBOX_POLL_ENABLED", "true")
    monkeypatch.setenv("MAILBOX_POLL_TOP", "7")
    monkeypatch.setenv("MAILBOX_MARK_PROCESSED", "false")
    monkeypatch.setattr(
        "function_app._run_mailbox_ingestion",
        lambda top, mark_processed: calls.append((top, mark_processed)) or [],
    )

    poll_mailbox(FakeTimerRequest(past_due=True))

    assert calls == [(7, False)]
