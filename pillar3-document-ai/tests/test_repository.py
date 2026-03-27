"""Tests for Document AI repository persistence."""

from __future__ import annotations

import shutil
from pathlib import Path
import uuid
import pytest

from document_ai.models import (
    ClassificationConfidence,
    ClassificationResult,
    CorrectionLog,
    DocumentType,
    FilingRecommendation,
    StagedDocument,
)
from document_ai.repository import DocumentRepository


def _make_test_dir() -> Path:
    path = Path.cwd() / ".test-temp" / f"repo-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_save_and_get_document():
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
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
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_save_correction_and_count():
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
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
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_save_and_get_document_bytes(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))

    reference = repo.save_document_bytes("doc-123", b"hello world")

    assert reference
    assert repo.has_document_bytes("doc-123") is True
    assert repo.get_document_bytes("doc-123") == b"hello world"
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_save_document_bytes_rejects_unsafe_document_id(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))

    with pytest.raises(ValueError, match="Invalid document_id"):
        repo.save_document_bytes("..\\..\\escape", b"hello world")
    shutil.rmtree(temp_dir, ignore_errors=True)
