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


def test_stage_document_accepts_pillar1_ach_export_contract_payload(monkeypatch):
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
    assert payload["document"]["binary_available"] is True
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
