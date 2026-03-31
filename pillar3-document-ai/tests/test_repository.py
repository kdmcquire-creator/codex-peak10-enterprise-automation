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
    DatabaseUpdateProposal,
    DatabaseUpdateStatus,
    DocumentType,
    FilingRecommendation,
    LearningEvidence,
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


def test_list_documents_filters_by_status_and_source():
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))

    first = StagedDocument(
        document_id="doc-1",
        original_filename="Invoice_1.pdf",
        source="pillar1",
        status="classified",
    )
    second = StagedDocument(
        document_id="doc-2",
        original_filename="Receipt_1.pdf",
        source="pillar4",
        status="pending",
    )
    repo.save_document(first)
    repo.save_document(second)

    classified = repo.list_documents(status="classified", limit=10)
    pillar4 = repo.list_documents(source="pillar4", limit=10)

    assert len(classified) == 1
    assert classified[0].document_id == "doc-1"
    assert len(pillar4) == 1
    assert pillar4[0].document_id == "doc-2"
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


def test_save_and_list_database_updates():
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))

    pending = DatabaseUpdateProposal(
        update_id="upd-pending",
        document_id="doc-123",
        document_type=DocumentType.CONTRACT,
        version_status="final",
        target_table="legal_contracts",
        proposed_field_updates={"counterparty": "Acme"},
    )
    approved = DatabaseUpdateProposal(
        update_id="upd-approved",
        document_id="doc-456",
        document_type=DocumentType.INVOICE,
        version_status="final",
        target_table="finance_ap_invoices",
        proposed_field_updates={"amount": "15000"},
        approved_field_updates={"amount": "14950"},
        status=DatabaseUpdateStatus.APPROVED,
    )

    repo.save_database_update(pending)
    repo.save_database_update(approved)

    all_updates = repo.list_database_updates(limit=10)
    pending_updates = repo.list_database_updates(
        status=DatabaseUpdateStatus.PENDING_APPROVAL,
        limit=10,
    )

    assert len(all_updates) == 2
    assert len(pending_updates) == 1
    assert pending_updates[0].update_id == "upd-pending"
    assert repo.count_database_updates() == 2
    assert repo.count_database_updates(status=DatabaseUpdateStatus.APPROVED) == 1
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_get_pending_database_update_for_document():
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))

    rejected = DatabaseUpdateProposal(
        update_id="upd-old",
        document_id="doc-123",
        document_type=DocumentType.CONTRACT,
        version_status="final",
        target_table="legal_contracts",
        proposed_field_updates={"counterparty": "Acme"},
        status=DatabaseUpdateStatus.REJECTED,
    )
    pending = DatabaseUpdateProposal(
        update_id="upd-new",
        document_id="doc-123",
        document_type=DocumentType.CONTRACT,
        version_status="final",
        target_table="legal_contracts",
        proposed_field_updates={"counterparty": "Acme II"},
    )
    repo.save_database_update(rejected)
    repo.save_database_update(pending)

    loaded = repo.get_pending_database_update_for_document("doc-123")
    assert loaded is not None
    assert loaded.update_id == "upd-new"
    assert loaded.status == DatabaseUpdateStatus.PENDING_APPROVAL
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_save_learning_evidence_and_applied_updates():
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))

    evidence = LearningEvidence(
        evidence_id="evi-1",
        update_id="upd-1",
        document_id="doc-1",
        document_type=DocumentType.CONTRACT,
        target_table="legal_contracts",
        event_type="review",
        decision="approve",
        proposed_field_updates={"counterparty": "Acme"},
        final_field_updates={"counterparty": "Acme"},
        actor="db.owner",
    )
    repo.save_learning_evidence(evidence)
    records = repo.list_learning_evidence(limit=10)
    reference = repo.save_applied_update("upd-1", {"counterparty": "Acme"})

    assert len(records) == 1
    assert records[0].evidence_id == "evi-1"
    assert repo.count_learning_evidence() == 1
    assert reference.endswith("/upd-1")
    assert repo.count_applied_updates() == 1
    shutil.rmtree(temp_dir, ignore_errors=True)
