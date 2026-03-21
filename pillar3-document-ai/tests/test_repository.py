"""Tests for Document AI repository persistence."""

from __future__ import annotations

from document_ai.models import (
    ClassificationConfidence,
    ClassificationResult,
    CorrectionLog,
    DocumentType,
    FilingRecommendation,
    StagedDocument,
)
from document_ai.repository import DocumentRepository


def test_save_and_get_document(tmp_path):
    repo = DocumentRepository(db_path=str(tmp_path / "document-ai.db"))
    doc = StagedDocument(
        document_id="doc-123",
        original_filename="Invoice_123.pdf",
        file_extension="pdf",
        source="email",
        source_detail="msg-1",
        status="classified",
        classification=ClassificationResult(
            document_type=DocumentType.INVOICE,
            confidence=0.91,
            confidence_level=ClassificationConfidence.HIGH,
        ),
        filing=FilingRecommendation(
            recommended_path="01_CORPORATE/Finance/AP",
            standardized_name="2026-03-21_Invoice_Test.pdf",
            document_type=DocumentType.INVOICE,
            confidence_level=ClassificationConfidence.HIGH,
            requires_review=False,
        ),
    )

    repo.save_document(doc)
    loaded = repo.get_document("doc-123")

    assert loaded is not None
    assert loaded.document_id == "doc-123"
    assert loaded.classification is not None
    assert loaded.classification.document_type == DocumentType.INVOICE
    assert loaded.filing is not None
    assert loaded.filing.recommended_path == "01_CORPORATE/Finance/AP"


def test_save_correction_and_count(tmp_path):
    repo = DocumentRepository(db_path=str(tmp_path / "document-ai.db"))
    correction = CorrectionLog(
        correction_id="corr-123",
        document_id="doc-123",
        original_type=DocumentType.CONTRACT,
        corrected_type=DocumentType.AMENDMENT,
        original_path="01_CORPORATE/Legal/Contracts",
        corrected_path="01_CORPORATE/Legal/Amendments",
    )

    repo.save_correction(correction)
    assert repo.count_corrections() == 1
