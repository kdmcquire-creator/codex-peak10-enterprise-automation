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

import json
import logging
import os
from datetime import datetime, timezone

import azure.functions as func

from document_ai.classifier import classify_document, build_classification_prompt
from document_ai.corrections import CorrectionStore
from document_ai.models import DocumentType, StagedDocument
from document_ai.repository import get_repository
from document_ai.naming import recommend_filing
from document_ai.serialization import (
    serialize_staged_document,
    serialize_classification,
    serialize_filing,
    serialize_correction,
)

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

    doc = StagedDocument(
        original_filename=filename,
        file_extension=ext,
        source=body.get("source", "upload"),
        source_detail=body.get("source_detail", ""),
        file_size_bytes=body.get("file_size_bytes", 0),
        content_hash=body.get("content_hash", ""),
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

    doc.status = "filed"
    _repository.save_document(doc)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "document_id": doc_id,
            "filed_to": doc.filing.recommended_path,
            "filed_as": doc.filing.standardized_name,
            "status": "filed",
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
            },
            "readiness": {
                "durable_storage_ready": True,
                "sharepoint_configured": bool(
                    os.environ.get("GRAPH_SHAREPOINT_SITE_ID")
                    and os.environ.get("GRAPH_SHAREPOINT_DRIVE_ID")
                ),
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
