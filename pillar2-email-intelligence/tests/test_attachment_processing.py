"""Tests for attachment extraction and SharePoint filing decisions."""

from __future__ import annotations

from email_intel.attachment_processing import (
    process_attachment,
    resolve_sharepoint_target,
)
from email_intel.document_models import (
    ClassificationConfidence,
    ClassificationResult,
    DocumentType,
    FilingRecommendation,
)
from email_intel.mailbox_ingestion import MailAttachment


class FakeGraphClient:
    sharepoint_available = True

    def upload_file(self, filename: str, file_bytes: bytes, *, folder_path: str = ""):
        return {
            "id": "sp-item-1",
            "webUrl": f"https://sharepoint.example/{folder_path}/{filename}",
        }


class FailingGraphClient:
    sharepoint_available = True

    def upload_file(self, filename: str, file_bytes: bytes, *, folder_path: str = ""):
        raise RuntimeError("sharepoint unavailable")


class FakeOpenAIClient:
    is_available = False


class FakeDocClient:
    is_available = False


def test_resolve_sharepoint_target_stages_low_confidence_documents():
    classification = ClassificationResult(
        document_type=DocumentType.UNKNOWN,
        confidence=0.20,
        confidence_level=ClassificationConfidence.LOW,
    )
    filing = FilingRecommendation(
        recommended_path="01_CORPORATE/Finance/AP",
        standardized_name="2026-03-21_Document_Unidentified.pdf",
        document_type=DocumentType.UNKNOWN,
        confidence_level=ClassificationConfidence.LOW,
        requires_review=True,
    )

    target = resolve_sharepoint_target("mystery.pdf", classification, filing)

    assert target["disposition"] == "staged_for_review"
    assert target["folder_path"] == "00_STAGING/Inbox"
    assert target["filename"] == "mystery.pdf"


def test_resolve_sharepoint_target_sends_unsupported_files_to_errors():
    classification = ClassificationResult(
        document_type=DocumentType.UNKNOWN,
        confidence=0.0,
        confidence_level=ClassificationConfidence.LOW,
    )
    filing = FilingRecommendation(
        recommended_path="00_STAGING/Errors",
        standardized_name="ignored.zip",
        document_type=DocumentType.UNKNOWN,
        confidence_level=ClassificationConfidence.LOW,
        requires_review=True,
    )

    target = resolve_sharepoint_target("archive.zip", classification, filing)

    assert target["disposition"] == "unsupported"
    assert target["folder_path"] == "00_STAGING/Errors"


def test_process_attachment_uploads_when_sharepoint_is_available():
    attachment = MailAttachment(
        attachment_id="att-1",
        name="Invoice_123.pdf",
        content_type="application/pdf",
        content_bytes=b"invoice-bytes",
    )

    processed = process_attachment(
        attachment,
        graph_client=FakeGraphClient(),
        openai_client=FakeOpenAIClient(),
        doc_intelligence_client=FakeDocClient(),
    )

    assert processed.classification.document_type == DocumentType.INVOICE
    assert processed.sharepoint_target["disposition"] == "filed"
    assert processed.sharepoint_target["folder_path"] == "01_CORPORATE/Finance/AP"
    assert processed.upload_result["attempted"] is True
    assert processed.upload_result["uploaded"] is True


def test_process_attachment_records_upload_failure_without_raising():
    attachment = MailAttachment(
        attachment_id="att-1",
        name="Invoice_123.pdf",
        content_type="application/pdf",
        content_bytes=b"invoice-bytes",
    )

    processed = process_attachment(
        attachment,
        graph_client=FailingGraphClient(),
        openai_client=FakeOpenAIClient(),
        doc_intelligence_client=FakeDocClient(),
    )

    assert processed.classification.document_type == DocumentType.INVOICE
    assert processed.upload_result["attempted"] is True
    assert processed.upload_result["uploaded"] is False
    assert processed.upload_result["reason"] == "sharepoint_upload_failed"
    assert "sharepoint unavailable" in str(processed.upload_result["error"])
