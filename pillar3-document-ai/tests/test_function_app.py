"""Tests for Document AI Azure Function handlers."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import uuid

from document_ai.models import (
    ClassificationConfidence,
    ClassificationResult,
    DocumentType,
    FilingRecommendation,
    StagedDocument,
)
from document_ai.repository import DocumentRepository
import function_app


class FakeRequest:
    def __init__(self, body: dict | None = None) -> None:
        self._body = body
        self.params = {}
        self.route_params = {}

    def get_json(self):
        if self._body is None:
            raise ValueError("No JSON body")
        return self._body


class FakeSharePointClient:
    def __init__(self, *, available: bool = True) -> None:
        self.is_available = available
        self.calls: list[dict[str, object]] = []

    def upload_file(self, filename: str, file_bytes: bytes, *, folder_path: str = "") -> dict[str, object]:
        self.calls.append(
            {
                "filename": filename,
                "file_bytes": file_bytes,
                "folder_path": folder_path,
            }
        )
        return {
            "id": "item-123",
            "webUrl": f"https://sharepoint.test/{folder_path}/{filename}",
        }


class FailingSharePointClient(FakeSharePointClient):
    def upload_file(self, filename: str, file_bytes: bytes, *, folder_path: str = "") -> dict[str, object]:
        raise RuntimeError("sharepoint unavailable")


class FakeBlobStagingClient:
    def __init__(self, *, available: bool = True) -> None:
        self.is_available = available
        self.payloads: dict[str, bytes] = {}

    def upload_bytes(self, document_id: str, file_bytes: bytes, *, content_type: str = "") -> str:
        self.payloads[document_id] = file_bytes
        return f"https://blob.test/staging-documents/{document_id}"

    def download_bytes(self, document_id: str) -> bytes | None:
        return self.payloads.get(document_id)

    def has_bytes(self, document_id: str) -> bool:
        return document_id in self.payloads


def _make_test_dir() -> Path:
    path = Path.cwd() / ".test-temp" / f"function-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_stage_document_persists_binary_payload(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    request = FakeRequest(
        {
            "filename": "Invoice_123.pdf",
            "source": "email",
            "file_bytes_base64": base64.b64encode(b"pdf-bytes").decode("utf-8"),
            "content_type": "application/pdf",
        }
    )

    response = function_app.stage_document(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 201
    assert payload["document"]["binary_available"] is True
    assert payload["document"]["storage_backend"] == "local_fs"
    assert payload["document"]["file_size_bytes"] == len(b"pdf-bytes")
    assert repo.has_document_bytes(payload["document"]["document_id"]) is True
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_list_documents_returns_recent_queue(monkeypatch):
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    repo.save_document(
        StagedDocument(
            document_id="doc-a",
            original_filename="Invoice_A.pdf",
            source="pillar1",
            status="classified",
        )
    )
    repo.save_document(
        StagedDocument(
            document_id="doc-b",
            original_filename="Receipt_B.pdf",
            source="pillar4",
            status="pending",
        )
    )

    request = FakeRequest()
    request.params = {"source": "pillar4", "limit": "10"}
    response = function_app.list_documents(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["documents"][0]["document_id"] == "doc-b"
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_stage_document_prefers_blob_storage_when_available(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    fake_blob = FakeBlobStagingClient()
    monkeypatch.setattr(function_app, "_repository", repo)
    monkeypatch.setattr(function_app, "get_blob_staging_client", lambda: fake_blob)

    response = function_app.stage_document(
        FakeRequest(
            {
                "filename": "Invoice_999.pdf",
                "file_bytes_base64": base64.b64encode(b"blob-pdf").decode("utf-8"),
                "content_type": "application/pdf",
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 201
    assert payload["document"]["storage_backend"] == "azure_blob"
    assert payload["document"]["storage_reference"].endswith(payload["document"]["document_id"])
    assert repo.has_document_bytes(payload["document"]["document_id"]) is False
    assert fake_blob.has_bytes(payload["document"]["document_id"]) is True
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_stage_document_preserves_upstream_classification_and_metadata(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    response = function_app.stage_document(
        FakeRequest(
            {
                "filename": "MSA_DrillCo.pdf",
                "source": "email",
                "source_detail": "msg-123",
                "message_id": "msg-123",
                "attachment_id": "att-456",
                "sender": "land@drillco.com",
                "classification": {
                    "document_type": "contract",
                    "confidence": 0.93,
                    "confidence_level": "high",
                    "metadata": {"counterparty": "DrillCo", "custom_fields": {}},
                    "reasoning": "Upstream classifier matched MSA language.",
                },
                "filing": {
                    "recommended_path": "01_CORPORATE/Legal/Contracts",
                    "standardized_name": "2026-03-27_Contract_DrillCo.pdf",
                    "document_type": "contract",
                    "confidence_level": "high",
                    "requires_review": False,
                    "alternative_paths": [],
                },
                "extraction": {
                    "used_document_intelligence": False,
                    "text_length": 481,
                },
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 201
    assert payload["document"]["status"] == "classified"
    assert payload["document"]["classification"]["document_type"] == "contract"
    assert payload["document"]["filing"]["recommended_path"] == "01_CORPORATE/Legal/Contracts"
    assert payload["document"]["source_metadata"]["message_id"] == "msg-123"
    assert payload["document"]["source_metadata"]["attachment_id"] == "att-456"
    assert payload["document"]["extraction"]["text_length"] == 481
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_stage_document_accepts_pillar1_ach_export_payload_and_queues_database_update(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    response = function_app.stage_document(
        FakeRequest(
            {
                "document_id": "run-abc:ach_export",
                "filename": "2026-03-27_AP_ACH_Export_run-abc.txt",
                "source": "pillar1",
                "source_detail": "run-abc",
                "source_metadata": {
                    "artifact_type": "ach_export",
                    "run_status": "exported",
                    "version_status": "final",
                    "total_allocated": "500.00",
                },
                "content_type": "text/plain",
                "file_bytes_base64": base64.b64encode(b"nacha-lines").decode("utf-8"),
                "classification": {
                    "document_type": "ach_export",
                    "confidence": 0.99,
                    "confidence_level": "high",
                    "metadata": {
                        "reference_number": "run-abc",
                        "custom_fields": {"run_id": "run-abc"},
                    },
                    "reasoning": "Generated by AFA Engine export workflow.",
                },
                "filing": {
                    "recommended_path": "01_CORPORATE/Finance/AP",
                    "standardized_name": "2026-03-27_AP_ACH_Export_run-abc.txt",
                    "document_type": "ach_export",
                    "confidence_level": "high",
                    "requires_review": False,
                    "alternative_paths": [],
                },
                "extraction": {
                    "amount": "500.00",
                    "run_id": "run-abc",
                    "record_count": 1,
                    "vendor_count": 1,
                },
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 201
    assert payload["document"]["document_id"] == "run-abc:ach_export"
    assert payload["document"]["status"] == "classified"
    assert payload["document"]["classification"]["document_type"] == "ach_export"
    assert payload["document"]["filing"]["recommended_path"] == "01_CORPORATE/Finance/AP"
    assert payload["document"]["source"] == "pillar1"
    assert payload["document"]["source_metadata"]["artifact_type"] == "ach_export"
    assert payload["document"]["source_metadata"]["version_status"] == "final"
    assert payload["document"]["binary_available"] is True
    assert payload["database_update_created"] is True
    assert payload["database_update"]["target_table"] == "finance_ap_schedule"
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_stage_document_detects_final_and_wip_version_markers(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    final_response = function_app.stage_document(
        FakeRequest(
            {
                "filename": "Agreement_ExecutionVersion.pdf",
                "file_bytes_base64": base64.b64encode(b"execution version").decode("utf-8"),
            }
        )
    )
    final_payload = json.loads(final_response.get_body().decode("utf-8"))
    assert final_response.status_code == 201
    assert final_payload["document"]["source_metadata"]["version_status"] == "final"

    wip_response = function_app.stage_document(
        FakeRequest(
            {
                "filename": "Agreement_v12.docx",
                "file_bytes_base64": base64.b64encode(b"draft").decode("utf-8"),
            }
        )
    )
    wip_payload = json.loads(wip_response.get_body().decode("utf-8"))
    assert wip_response.status_code == 201
    assert wip_payload["document"]["source_metadata"]["version_status"] == "wip"
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_stage_document_queues_database_update_for_final_document(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    response = function_app.stage_document(
        FakeRequest(
            {
                "filename": "MSA_ExecutionVersion.pdf",
                "content_text": "Master Services Agreement between Peak10 and DrillCo.",
                "extraction": {
                    "counterparty": "DrillCo Services",
                    "effective_date": "2026-03-27",
                },
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 201
    assert payload["database_update_created"] is True
    assert payload["database_update"]["status"] == "pending_approval"
    assert payload["database_update"]["target_table"] == "legal_contracts"
    assert repo.count_database_updates() == 1
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_stage_document_skips_database_update_for_wip_document(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    response = function_app.stage_document(
        FakeRequest(
            {
                "filename": "MSA_v12.docx",
                "extraction": {"counterparty": "DrillCo Services"},
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 201
    assert payload["database_update"] is None
    assert payload["database_update_created"] is False
    assert payload["database_update_reason"] == "version_not_final"
    assert repo.count_database_updates() == 0
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_stage_document_uses_content_first_classification_when_content_text_is_present(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    response = function_app.stage_document(
        FakeRequest(
            {
                "filename": "Invoice_123.pdf",
                "content_text": "This Purchase and Sale Agreement is entered into by and between...",
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 201
    assert payload["document"]["classification"]["document_type"] == "psa"
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_stage_document_rejects_unsafe_document_id(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    response = function_app.stage_document(
        FakeRequest(
            {
                "document_id": "..\\..\\escape",
                "filename": "Invoice_123.pdf",
                "file_bytes_base64": base64.b64encode(b"bytes").decode("utf-8"),
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 400
    assert "unsafe characters" in payload["error"]
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_stage_document_generates_content_hash_from_bytes(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    response = function_app.stage_document(
        FakeRequest(
            {
                "filename": "invoice.pdf",
                "file_bytes_base64": base64.b64encode(b"hash-me").decode("utf-8"),
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 201
    assert payload["document"]["content_hash"].startswith("sha256:")
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_file_document_uploads_staged_bytes_to_sharepoint(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    doc = StagedDocument(
        document_id="doc-123",
        original_filename="Invoice_123.pdf",
        file_extension="pdf",
        source="email",
        content_type="application/pdf",
        binary_available=True,
        storage_backend="local_fs",
        classification=ClassificationResult(
            document_type=DocumentType.INVOICE,
            confidence=0.92,
            confidence_level=ClassificationConfidence.HIGH,
        ),
        filing=FilingRecommendation(
            recommended_path="01_CORPORATE/Finance/AP",
            standardized_name="2026-03-21_Invoice_123.pdf",
            document_type=DocumentType.INVOICE,
            confidence_level=ClassificationConfidence.HIGH,
            requires_review=False,
        ),
    )
    repo.save_document(doc)
    repo.save_document_bytes(doc.document_id, b"pdf-bytes")

    fake_sharepoint = FakeSharePointClient()
    monkeypatch.setattr(function_app, "get_sharepoint_client", lambda: fake_sharepoint)

    response = function_app.file_document(FakeRequest({"document_id": "doc-123"}))
    payload = json.loads(response.get_body().decode("utf-8"))
    stored = repo.get_document("doc-123")

    assert response.status_code == 200
    assert payload["upload"]["attempted"] is True
    assert payload["upload"]["uploaded"] is True
    assert payload["upload"]["backend"] == "sharepoint"
    assert fake_sharepoint.calls[0]["folder_path"] == "01_CORPORATE/Finance/AP"
    assert stored is not None
    assert stored.status == "filed"
    assert stored.filing_backend == "sharepoint"
    assert stored.filing_reference.endswith("/01_CORPORATE/Finance/AP/2026-03-21_Invoice_123.pdf")
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_file_document_uploads_blob_staged_bytes_to_sharepoint(monkeypatch):
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    fake_blob = FakeBlobStagingClient()
    fake_sharepoint = FakeSharePointClient()
    monkeypatch.setattr(function_app, "_repository", repo)
    monkeypatch.setattr(function_app, "get_blob_staging_client", lambda: fake_blob)
    monkeypatch.setattr(function_app, "get_sharepoint_client", lambda: fake_sharepoint)

    doc = StagedDocument(
        document_id="doc-blob",
        original_filename="Board_Minutes.pdf",
        file_extension="pdf",
        source="upload",
        content_type="application/pdf",
        binary_available=True,
        storage_backend="azure_blob",
        storage_reference="https://blob.test/staging-documents/doc-blob",
        classification=ClassificationResult(
            document_type=DocumentType.BOARD_MINUTES,
            confidence=0.91,
            confidence_level=ClassificationConfidence.HIGH,
        ),
        filing=FilingRecommendation(
            recommended_path="04_GOVERNANCE/Board_Minutes",
            standardized_name="2026-03-21_Board_Minutes.pdf",
            document_type=DocumentType.BOARD_MINUTES,
            confidence_level=ClassificationConfidence.HIGH,
            requires_review=False,
        ),
    )
    repo.save_document(doc)
    fake_blob.upload_bytes(doc.document_id, b"board-bytes", content_type="application/pdf")

    response = function_app.file_document(FakeRequest({"document_id": "doc-blob"}))
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["upload"]["uploaded"] is True
    assert fake_sharepoint.calls[0]["file_bytes"] == b"board-bytes"
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_file_document_reports_metadata_only_when_bytes_are_missing(monkeypatch):
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    doc = StagedDocument(
        document_id="doc-456",
        original_filename="Contract.pdf",
        file_extension="pdf",
        source="upload",
        classification=ClassificationResult(
            document_type=DocumentType.CONTRACT,
            confidence=0.88,
            confidence_level=ClassificationConfidence.HIGH,
        ),
        filing=FilingRecommendation(
            recommended_path="01_CORPORATE/Legal/Contracts",
            standardized_name="2026-03-21_Contract.pdf",
            document_type=DocumentType.CONTRACT,
            confidence_level=ClassificationConfidence.HIGH,
            requires_review=False,
        ),
    )
    repo.save_document(doc)
    monkeypatch.setattr(function_app, "get_sharepoint_client", lambda: FakeSharePointClient())

    response = function_app.file_document(FakeRequest({"document_id": "doc-456"}))
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["status"] == "filed"
    assert payload["upload"]["attempted"] is False
    assert payload["upload"]["reason"] == "document_bytes_unavailable"
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_file_document_does_not_mark_filed_when_upload_fails(monkeypatch):
    temp_dir = _make_test_dir()
    monkeypatch.setenv("DOCUMENT_AI_STAGING_DIR", str(temp_dir / "staged-files"))
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)
    monkeypatch.setattr(function_app, "get_sharepoint_client", lambda: FailingSharePointClient())

    doc = StagedDocument(
        document_id="doc-fail",
        original_filename="Invoice_321.pdf",
        file_extension="pdf",
        source="email",
        content_type="application/pdf",
        binary_available=True,
        storage_backend="local_fs",
        classification=ClassificationResult(
            document_type=DocumentType.INVOICE,
            confidence=0.94,
            confidence_level=ClassificationConfidence.HIGH,
        ),
        filing=FilingRecommendation(
            recommended_path="01_CORPORATE/Finance/AP",
            standardized_name="2026-03-21_Invoice_321.pdf",
            document_type=DocumentType.INVOICE,
            confidence_level=ClassificationConfidence.HIGH,
            requires_review=False,
        ),
    )
    repo.save_document(doc)
    repo.save_document_bytes(doc.document_id, b"invoice-bytes")

    response = function_app.file_document(FakeRequest({"document_id": "doc-fail"}))
    payload = json.loads(response.get_body().decode("utf-8"))
    stored = repo.get_document("doc-fail")

    assert response.status_code == 200
    assert payload["status"] == "classified"
    assert payload["upload"]["attempted"] is True
    assert payload["upload"]["uploaded"] is False
    assert "sharepoint_upload_failed" in payload["upload"]["reason"]
    assert stored is not None
    assert stored.status == "classified"
    assert stored.filed_at is None
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_database_update_propose_and_review_workflow(monkeypatch):
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    doc = StagedDocument(
        document_id="doc-db-1",
        original_filename="MSA_ExecutionVersion.pdf",
        file_extension="pdf",
        source="email",
        source_metadata={"version_status": "final"},
        status="classified",
        extraction={
            "counterparty": "DrillCo Services",
            "effective_date": "2026-03-27",
            "amount": "150000.00",
        },
        classification=ClassificationResult(
            document_type=DocumentType.CONTRACT,
            confidence=0.93,
            confidence_level=ClassificationConfidence.HIGH,
        ),
        filing=FilingRecommendation(
            recommended_path="01_CORPORATE/Legal/Contracts",
            standardized_name="2026-03-27_MSA_DrillCo.pdf",
            document_type=DocumentType.CONTRACT,
            confidence_level=ClassificationConfidence.HIGH,
            requires_review=False,
        ),
    )
    repo.save_document(doc)

    propose_response = function_app.propose_database_update(
        FakeRequest({"document_id": "doc-db-1"})
    )
    propose_payload = json.loads(propose_response.get_body().decode("utf-8"))
    update_id = propose_payload["database_update"]["update_id"]

    assert propose_response.status_code == 201
    assert propose_payload["created"] is True
    assert propose_payload["database_update"]["status"] == "pending_approval"

    review_response = function_app.review_database_update(
        FakeRequest(
            {
                "update_id": update_id,
                "decision": "approve",
                "reviewed_by": "finance.owner",
                "review_notes": "Approved with corrected amount.",
                "edited_field_updates": {"amount": "149500.00"},
            }
        )
    )
    review_payload = json.loads(review_response.get_body().decode("utf-8"))
    assert review_response.status_code == 200
    assert review_payload["database_update"]["status"] == "approved"
    assert review_payload["database_update"]["approved_field_updates"]["amount"] == "149500.00"
    assert review_payload["database_update"]["reviewed_by"] == "finance.owner"
    assert review_payload["learning_evidence"]["event_type"] == "review"
    assert review_payload["learning_evidence"]["decision"] == "approve"

    list_request = FakeRequest()
    list_request.params = {"status": "approved"}
    list_response = function_app.list_database_updates(list_request)
    list_payload = json.loads(list_response.get_body().decode("utf-8"))

    assert list_response.status_code == 200
    assert list_payload["count"] == 1
    assert list_payload["database_updates"][0]["update_id"] == update_id
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_database_update_review_rejects_pending_item(monkeypatch):
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)

    doc = StagedDocument(
        document_id="doc-db-2",
        original_filename="Invoice_Executed.pdf",
        file_extension="pdf",
        source="email",
        source_metadata={"version_status": "final"},
        status="classified",
        extraction={"vendor_name": "Rig Services", "amount": "1200.00"},
        classification=ClassificationResult(
            document_type=DocumentType.INVOICE,
            confidence=0.91,
            confidence_level=ClassificationConfidence.HIGH,
        ),
    )
    repo.save_document(doc)

    propose_response = function_app.propose_database_update(
        FakeRequest({"document_id": "doc-db-2"})
    )
    propose_payload = json.loads(propose_response.get_body().decode("utf-8"))
    update_id = propose_payload["database_update"]["update_id"]

    reject_response = function_app.review_database_update(
        FakeRequest(
            {
                "update_id": update_id,
                "decision": "reject",
                "reviewed_by": "ops.owner",
                "review_notes": "Not enough data quality.",
            }
        )
    )
    reject_payload = json.loads(reject_response.get_body().decode("utf-8"))
    assert reject_response.status_code == 200
    assert reject_payload["database_update"]["status"] == "rejected"
    assert reject_payload["database_update"]["approved_field_updates"] == {}
    assert reject_payload["learning_evidence"]["decision"] == "reject"
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_database_update_apply_shadow_mode(monkeypatch):
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)
    monkeypatch.setenv("DATABASE_UPDATE_MODE", "shadow")

    doc = StagedDocument(
        document_id="doc-db-shadow",
        original_filename="Invoice_Executed.pdf",
        file_extension="pdf",
        source="email",
        source_metadata={"version_status": "final"},
        status="classified",
        extraction={"vendor_name": "Rig Services", "amount": "1200.00"},
        classification=ClassificationResult(
            document_type=DocumentType.INVOICE,
            confidence=0.94,
            confidence_level=ClassificationConfidence.HIGH,
        ),
    )
    repo.save_document(doc)
    propose_payload = json.loads(
        function_app.propose_database_update(FakeRequest({"document_id": "doc-db-shadow"}))
        .get_body()
        .decode("utf-8")
    )
    update_id = propose_payload["database_update"]["update_id"]
    function_app.review_database_update(
        FakeRequest({"update_id": update_id, "decision": "approve"})
    )

    apply_response = function_app.apply_database_update(
        FakeRequest({"update_id": update_id, "applied_by": "ops.bot"})
    )
    apply_payload = json.loads(apply_response.get_body().decode("utf-8"))

    assert apply_response.status_code == 200
    assert apply_payload["mode"] == "shadow"
    assert apply_payload["applied"] is False
    assert apply_payload["database_update"]["apply_state"] == "shadow_applied"
    assert apply_payload["learning_evidence"]["event_type"] == "apply"
    assert repo.count_applied_updates() == 0
    assert repo.count_learning_evidence() >= 2
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_database_update_apply_active_mode(monkeypatch):
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)
    monkeypatch.setenv("DATABASE_UPDATE_MODE", "active")

    doc = StagedDocument(
        document_id="doc-db-active",
        original_filename="Invoice_Executed.pdf",
        file_extension="pdf",
        source="email",
        source_metadata={"version_status": "final"},
        status="classified",
        extraction={"vendor_name": "Rig Services", "amount": "1200.00"},
        classification=ClassificationResult(
            document_type=DocumentType.INVOICE,
            confidence=0.94,
            confidence_level=ClassificationConfidence.HIGH,
        ),
    )
    repo.save_document(doc)
    propose_payload = json.loads(
        function_app.propose_database_update(FakeRequest({"document_id": "doc-db-active"}))
        .get_body()
        .decode("utf-8")
    )
    update_id = propose_payload["database_update"]["update_id"]
    function_app.review_database_update(
        FakeRequest({"update_id": update_id, "decision": "approve"})
    )

    apply_response = function_app.apply_database_update(
        FakeRequest({"update_id": update_id, "applied_by": "ops.bot"})
    )
    apply_payload = json.loads(apply_response.get_body().decode("utf-8"))

    assert apply_response.status_code == 200
    assert apply_payload["mode"] == "active"
    assert apply_payload["applied"] is True
    assert apply_payload["database_update"]["apply_state"] == "applied"
    assert repo.count_applied_updates() == 1
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_database_update_apply_rejects_already_applied_update(monkeypatch):
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)
    monkeypatch.setenv("DATABASE_UPDATE_MODE", "active")

    doc = StagedDocument(
        document_id="doc-db-already-applied",
        original_filename="Invoice_Executed.pdf",
        file_extension="pdf",
        source="email",
        source_metadata={"version_status": "final"},
        status="classified",
        extraction={"vendor_name": "Rig Services", "amount": "1200.00"},
        classification=ClassificationResult(
            document_type=DocumentType.INVOICE,
            confidence=0.94,
            confidence_level=ClassificationConfidence.HIGH,
        ),
    )
    repo.save_document(doc)
    propose_payload = json.loads(
        function_app.propose_database_update(
            FakeRequest({"document_id": "doc-db-already-applied"})
        )
        .get_body()
        .decode("utf-8")
    )
    update_id = propose_payload["database_update"]["update_id"]
    function_app.review_database_update(
        FakeRequest({"update_id": update_id, "decision": "approve"})
    )
    first_apply = function_app.apply_database_update(
        FakeRequest({"update_id": update_id, "applied_by": "ops.bot"})
    )
    first_payload = json.loads(first_apply.get_body().decode("utf-8"))

    second_apply = function_app.apply_database_update(
        FakeRequest({"update_id": update_id, "applied_by": "ops.bot"})
    )
    second_payload = json.loads(second_apply.get_body().decode("utf-8"))

    assert first_apply.status_code == 200
    assert first_payload["applied"] is True
    assert second_apply.status_code == 409
    assert second_payload["success"] is False
    assert "already applied" in second_payload["error"]
    assert repo.count_applied_updates() == 1
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_database_update_learning_eval_endpoint(monkeypatch):
    temp_dir = _make_test_dir()
    repo = DocumentRepository(db_path=str(temp_dir / "document-ai.db"))
    monkeypatch.setattr(function_app, "_repository", repo)
    monkeypatch.setenv("DATABASE_UPDATE_MODE", "shadow")

    doc = StagedDocument(
        document_id="doc-db-eval",
        original_filename="Invoice_Executed.pdf",
        file_extension="pdf",
        source="email",
        source_metadata={"version_status": "final"},
        status="classified",
        extraction={"vendor_name": "Rig Services", "amount": "1200.00"},
        classification=ClassificationResult(
            document_type=DocumentType.INVOICE,
            confidence=0.94,
            confidence_level=ClassificationConfidence.HIGH,
        ),
    )
    repo.save_document(doc)
    propose_payload = json.loads(
        function_app.propose_database_update(FakeRequest({"document_id": "doc-db-eval"}))
        .get_body()
        .decode("utf-8")
    )
    update_id = propose_payload["database_update"]["update_id"]
    function_app.review_database_update(
        FakeRequest({"update_id": update_id, "decision": "approve"})
    )
    function_app.apply_database_update(FakeRequest({"update_id": update_id}))

    request = FakeRequest()
    request.params = {"limit": "25"}
    eval_response = function_app.get_learning_eval(request)
    eval_payload = json.loads(eval_response.get_body().decode("utf-8"))

    assert eval_response.status_code == 200
    assert eval_payload["sample_size"] >= 2
    assert "approval_rate" in eval_payload["report"]
    shutil.rmtree(temp_dir, ignore_errors=True)
