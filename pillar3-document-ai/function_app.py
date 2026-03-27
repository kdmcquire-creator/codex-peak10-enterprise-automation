"""
Azure Functions HTTP triggers for the Document AI system.

Endpoints:
  POST /api/documents/classify      — Classify a staged document
  POST /api/documents/file          — File a classified document
  POST /api/documents/correct       — Log a user correction
  POST /api/documents/stage         — Stage a new document (from Pillar 1/2/4)
  GET  /api/documents/<id>          — Get document status
  GET  /api/health                  — Health check
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

import azure.functions as func

from document_ai.classifier import (
    classify_document,
    build_classification_prompt,
    infer_document_version_state,
)
from document_ai.corrections import CorrectionStore
from document_ai.models import DocumentType, StagedDocument
from document_ai.repository import get_repository
from document_ai.naming import recommend_filing
from document_ai.serialization import (
    serialize_staged_document,
    serialize_classification,
    serialize_filing,
    serialize_correction,
    deserialize_classification,
    deserialize_filing,
)
from document_ai.blob_storage import get_blob_staging_client
from document_ai.sharepoint_client import get_sharepoint_client

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
logger = logging.getLogger("document-ai")
_repository = get_repository()
_correction_store = CorrectionStore()


# ---------------------------------------------------------------------------
# POST /api/documents/classify
# ---------------------------------------------------------------------------

@app.route(route="documents/classify", methods=["POST"])
def classify_doc(req: func.HttpRequest) -> func.HttpResponse:
    """
    Classify a staged document.

    Request body:
    {
      "document_id": "...",
      "filename": "Invoice_Halliburton_2026-03.pdf",
      "content_text": "<optional extracted text>",
      "ai_response": {<optional AI classification JSON>}
    }
    """
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    filename = body.get("filename", "")
    if not filename:
        return _error("'filename' is required", 400)

    content_text = body.get("content_text")
    ai_response = body.get("ai_response")

    classification = classify_document(
        filename=filename,
        content_text=content_text,
        ai_response=ai_response,
    )

    # If document is tracked, update it
    doc_id = body.get("document_id")
    if doc_id:
        doc = _repository.get_document(doc_id)
    else:
        doc = None
    if doc:
        doc.classification = classification
        doc.status = "classified"

    # Generate filing recommendation
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "pdf"
    filing = recommend_filing(classification, filename, ext)

    if doc:
        doc.filing = filing
        _repository.save_document(doc)

    # If AI is needed, return the prompt for the caller to execute
    needs_ai = classification.confidence < 0.85 and not ai_response
    ai_prompt = None
    if needs_ai:
        ai_prompt = build_classification_prompt(filename, content_text or "")

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "classification": serialize_classification(classification),
            "filing": serialize_filing(filing),
            "needs_ai_classification": needs_ai,
            "ai_prompt": ai_prompt,
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/documents/stage
# ---------------------------------------------------------------------------

@app.route(route="documents/stage", methods=["POST"])
def stage_document(req: func.HttpRequest) -> func.HttpResponse:
    """
    Stage a new document from any source (upload, email, Pillar 1, Pillar 4).

    Request body:
    {
      "filename": "...",
      "source": "pillar1",
      "source_detail": "run-abc123",
      "file_size_bytes": 102400,
      "content_hash": "sha256:..."
    }
    """
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    filename = body.get("filename", "")
    if not filename:
        return _error("'filename' is required", 400)

    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    provided_document_id = body.get("document_id")
    if not isinstance(provided_document_id, str):
        provided_document_id = ""
    if provided_document_id and not _is_safe_document_id(provided_document_id):
        return _error("'document_id' contains unsafe characters", 400)

    content_text = body.get("content_text")
    if not isinstance(content_text, str):
        content_text = ""

    doc = StagedDocument(
        original_filename=filename,
        file_extension=ext,
        source=body.get("source", "upload"),
        source_detail=body.get("source_detail", ""),
        source_metadata=_normalize_object_dict(body.get("source_metadata", {})),
        file_size_bytes=body.get("file_size_bytes", 0),
        content_hash=body.get("content_hash", ""),
        content_type=body.get("content_type", ""),
    )
    if provided_document_id:
        doc.document_id = provided_document_id

    if isinstance(body.get("message_id"), str) and body.get("message_id"):
        doc.source_metadata.setdefault("message_id", body["message_id"])
    if isinstance(body.get("attachment_id"), str) and body.get("attachment_id"):
        doc.source_metadata.setdefault("attachment_id", body["attachment_id"])
    if isinstance(body.get("thread_key"), str) and body.get("thread_key"):
        doc.source_metadata.setdefault("thread_key", body["thread_key"])
    if isinstance(body.get("sender"), str) and body.get("sender"):
        doc.source_metadata.setdefault("sender", body["sender"])

    if isinstance(body.get("classification"), dict):
        doc.classification = deserialize_classification(body["classification"])
        doc.status = "classified"
    if isinstance(body.get("filing"), dict):
        doc.filing = deserialize_filing(body["filing"])
        if doc.classification is not None:
            doc.status = "classified"
    extraction = _normalize_object_dict(body.get("extraction", {}))
    if extraction:
        doc.extraction = extraction

    version_status, version_evidence = infer_document_version_state(
        filename,
        content_text=content_text,
    )
    doc.source_metadata.setdefault("version_status", version_status)
    if version_evidence:
        doc.source_metadata.setdefault("version_signal", version_evidence)

    file_bytes_base64 = body.get("file_bytes_base64", "")
    if file_bytes_base64:
        try:
            file_bytes = _decode_file_bytes(file_bytes_base64)
            if not content_text:
                content_text = _maybe_extract_text_preview(file_bytes)
        except ValueError as exc:
            return _error(str(exc), 400)
        try:
            storage_backend, storage_reference = _persist_document_bytes(
                doc.document_id,
                file_bytes,
                content_type=doc.content_type,
            )
        except ValueError as exc:
            return _error(str(exc), 400)
        doc.binary_available = True
        doc.storage_backend = storage_backend
        doc.storage_reference = storage_reference
        doc.file_size_bytes = len(file_bytes)
        if not doc.content_hash:
            doc.content_hash = f"sha256:{hashlib.sha256(file_bytes).hexdigest()}"
        if not doc.content_type:
            doc.content_type = "application/octet-stream"

    if doc.classification is None and content_text:
        doc.classification = classify_document(
            filename=filename,
            content_text=content_text,
        )
    if doc.classification is not None and doc.filing is None:
        ext_for_filing = doc.file_extension or "bin"
        doc.filing = recommend_filing(doc.classification, filename, ext_for_filing)
    if doc.classification is not None:
        doc.status = "classified"
        doc.classification.metadata.custom_fields.setdefault("version_status", version_status)
        if version_evidence:
            doc.classification.metadata.custom_fields.setdefault(
                "version_signal",
                version_evidence,
            )

    _repository.save_document(doc)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "document": serialize_staged_document(doc),
        }),
        mimetype="application/json",
        status_code=201,
    )


# ---------------------------------------------------------------------------
# POST /api/documents/file
# ---------------------------------------------------------------------------

@app.route(route="documents/file", methods=["POST"])
def file_document(req: func.HttpRequest) -> func.HttpResponse:
    """
    Confirm filing of a classified document.

    Request body:
    {
      "document_id": "...",
      "confirmed_path": "<optional override>",
      "confirmed_name": "<optional override>"
    }
    """
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    doc_id = body.get("document_id")
    if not doc_id:
        return _error("'document_id' is required", 400)

    doc = _repository.get_document(doc_id)
    if not doc:
        return _error(f"Document '{doc_id}' not found", 404)

    if not doc.classification:
        return _error("Document has not been classified yet", 409)

    # Allow user to override path/name
    if body.get("confirmed_path"):
        doc.filing.recommended_path = body["confirmed_path"]
    if body.get("confirmed_name"):
        doc.filing.standardized_name = body["confirmed_name"]

    upload = {
        "attempted": False,
        "uploaded": False,
        "backend": "metadata_only",
        "reason": "",
        "item_id": "",
        "web_url": "",
    }
    sharepoint = get_sharepoint_client()
    file_bytes = _load_document_bytes(doc)
    upload_required = bool(file_bytes)
    upload_succeeded = False
    if file_bytes:
        if sharepoint.is_available:
            try:
                upload["attempted"] = True
                upload["backend"] = "sharepoint"
                response = sharepoint.upload_file(
                    doc.filing.standardized_name,
                    file_bytes,
                    folder_path=doc.filing.recommended_path,
                )
                upload["uploaded"] = bool(response)
                upload_succeeded = bool(response)
                upload["reason"] = "" if response else "sharepoint_empty_response"
                upload["item_id"] = str(response.get("id", "")) if response else ""
                upload["web_url"] = str(response.get("webUrl", "")) if response else ""
                doc.filing_backend = "sharepoint"
                doc.filing_reference = str(response.get("webUrl", "")) if response else ""
            except Exception as exc:
                logger.warning("SharePoint upload failed for %s: %s", doc_id, exc)
                upload["attempted"] = True
                upload["backend"] = "sharepoint"
                upload["reason"] = f"sharepoint_upload_failed: {exc}"
        else:
            upload["reason"] = "sharepoint_not_configured"
    else:
        upload["reason"] = "document_bytes_unavailable"

    if upload_required and not upload_succeeded:
        doc.status = "classified"
        doc.filed_at = None
    else:
        doc.status = "filed"
        doc.filed_at = datetime.now(timezone.utc).isoformat()
    _repository.save_document(doc)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "document_id": doc_id,
            "filed_to": doc.filing.recommended_path,
            "filed_as": doc.filing.standardized_name,
            "status": doc.status,
            "upload": upload,
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/documents/correct
# ---------------------------------------------------------------------------

@app.route(route="documents/correct", methods=["POST"])
def correct_classification(req: func.HttpRequest) -> func.HttpResponse:
    """
    Log a user correction to classification or filing.

    Request body:
    {
      "document_id": "...",
      "corrected_type": "contract",
      "corrected_path": "01_CORPORATE/Legal/Contracts",
      "notes": "This was actually an MSA, not correspondence"
    }
    """
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    doc_id = body.get("document_id")
    if not doc_id:
        return _error("'document_id' is required", 400)

    doc = _repository.get_document(doc_id)
    if not doc:
        return _error(f"Document '{doc_id}' not found", 404)

    try:
        corrected_type = DocumentType(body.get("corrected_type", "unknown"))
    except ValueError:
        return _error(f"Invalid document type: {body.get('corrected_type')}", 400)

    original_type = doc.classification.document_type if doc.classification else DocumentType.UNKNOWN
    original_path = doc.filing.recommended_path if doc.filing else ""

    correction = _correction_store.log_correction(
        document_id=doc_id,
        original_type=original_type,
        corrected_type=corrected_type,
        original_path=original_path,
        corrected_path=body.get("corrected_path", ""),
        notes=body.get("notes", ""),
    )
    _repository.save_correction(correction)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "correction": serialize_correction(correction),
            "total_corrections": _repository.count_corrections(),
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}
# ---------------------------------------------------------------------------

@app.route(route="documents/{document_id}", methods=["GET"])
def get_document(req: func.HttpRequest) -> func.HttpResponse:
    doc_id = req.route_params.get("document_id")
    doc = _repository.get_document(doc_id)  # type: ignore[arg-type]
    if not doc:
        return _error(f"Document '{doc_id}' not found", 404)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "document": serialize_staged_document(doc),
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    blob_staging = get_blob_staging_client()
    sharepoint = get_sharepoint_client()
    return func.HttpResponse(
        body=json.dumps({
            "status": "healthy",
            "service": "document-ai",
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "documents_staged": _repository.count_documents(),
            "corrections_logged": _repository.count_corrections(),
            "persistence": {
                "backend": "sqlite",
                "db_path": _repository.db_path,
                "staging_dir": str(getattr(_repository, "staging_dir", "")),
                "blob_staging_available": blob_staging.is_available,
            },
            "readiness": {
                "durable_storage_ready": True,
                "blob_staging_ready": blob_staging.is_available,
                "sharepoint_configured": bool(
                    os.environ.get("GRAPH_SHAREPOINT_SITE_ID")
                    and os.environ.get("GRAPH_SHAREPOINT_DRIVE_ID")
                ),
                "sharepoint_filing_ready": sharepoint.is_available,
            },
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error(message: str, status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps({"success": False, "error": message}),
        mimetype="application/json",
        status_code=status_code,
    )


def _decode_file_bytes(file_bytes_base64: str) -> bytes:
    try:
        return base64.b64decode(file_bytes_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid 'file_bytes_base64' payload") from exc


def _normalize_object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _is_safe_document_id(document_id: str) -> bool:
    if len(document_id) > 200:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._:-]+", document_id))


def _maybe_extract_text_preview(file_bytes: bytes) -> str:
    """
    Lightweight text preview extraction from bytes for content-first rules.
    Keeps staging resilient and avoids hard dependencies on external OCR here.
    """
    try:
        return file_bytes.decode("utf-8", errors="ignore")[:2000]
    except Exception:
        return ""


def _persist_document_bytes(
    document_id: str,
    file_bytes: bytes,
    *,
    content_type: str = "",
) -> tuple[str, str]:
    blob_staging = get_blob_staging_client()
    if blob_staging.is_available:
        reference = blob_staging.upload_bytes(
            document_id,
            file_bytes,
            content_type=content_type,
        )
        if reference:
            return "azure_blob", reference

    reference = _repository.save_document_bytes(document_id, file_bytes)
    return "local_fs", reference


def _load_document_bytes(doc: StagedDocument) -> bytes | None:
    if doc.storage_backend == "azure_blob":
        blob_staging = get_blob_staging_client()
        if blob_staging.is_available:
            return blob_staging.download_bytes(doc.document_id)

    if getattr(_repository, "has_document_bytes", None):
        try:
            if _repository.has_document_bytes(doc.document_id):
                return _repository.get_document_bytes(doc.document_id)
        except ValueError:
            return None
    return None
