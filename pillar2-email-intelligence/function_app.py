"""
Azure Functions HTTP triggers for the Email Intelligence system.

Endpoints:
  POST /api/email/triage           — Triage an inbound email
  POST /api/email/draft-reply      — Generate/save a draft reply
  GET  /api/email/drafts/{msg_id}  — Get drafts for a message
  PUT  /api/email/drafts/{draft_id} — Update a draft (approve/edit)
  DELETE /api/email/drafts/{draft_id} — Delete a draft

  POST /api/documents/classify     — Classify a document (attachment)
  POST /api/documents/correct      — Log a classification correction

  GET  /api/triage/history         — Query triage history from Cosmos DB

  GET  /api/health                 — Health check
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from datetime import datetime, timezone

import azure.functions as func

from email_intel.models import EmailMessage, DraftResponse
from email_intel.triage import (
    build_triage_prompt,
    route_attachments,
    triage_email,
)
from email_intel.serialization import (
    serialize_email,
    serialize_attachment_routing,
    serialize_triage_result,
    serialize_draft_response,
    serialize_classification_result,
    serialize_filing_recommendation,
)
from email_intel.cosmos_client import get_store
from email_intel.graph_client import get_graph_client
from email_intel.ingestion_service import MailboxIngestionService
from email_intel.openai_client import get_openai_client
from email_intel.doc_intelligence import (
    get_doc_intelligence_client,
)
from email_intel.attachment_processing import extract_document_text_from_bytes
from email_intel.classifier import classify_document, build_classification_prompt
from email_intel.naming import recommend_filing
from email_intel.corrections import CorrectionStore
from email_intel.document_models import DocumentType

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
logger = logging.getLogger("email-intel")

# Module-level correction store (backed by Cosmos in production)
_correction_store = CorrectionStore()

DEFAULT_MAILBOX_POLL_SCHEDULE = "0 */1 * * * *"
DEFAULT_MAILBOX_POLL_TOP = 10


def _get_bool_setting(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int_setting(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid integer setting for %s: %r", name, raw)
        return default


# ---------------------------------------------------------------------------
# POST /api/email/triage
# ---------------------------------------------------------------------------

@app.route(route="email/triage", methods=["POST"])
def triage(req: func.HttpRequest) -> func.HttpResponse:
    """Triage an inbound email with persistence and optional AI enhancement."""
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    if not body.get("subject") and not body.get("sender"):
        return _error("'subject' or 'sender' is required", 400)

    email = EmailMessage(
        subject=body.get("subject", ""),
        sender=body.get("sender", ""),
        sender_name=body.get("sender_name", ""),
        recipients=body.get("recipients", []),
        body_preview=body.get("body_preview", ""),
        body_text=body.get("body_text", ""),
        has_attachments=body.get("has_attachments", False),
        attachment_names=body.get("attachment_names", []),
        is_reply=body.get("is_reply", False),
    )

    # Check if AI response was provided, or try to get one from OpenAI
    ai_response = body.get("ai_response")
    result = triage_email(email, ai_response=ai_response)

    # If low confidence and no AI response, try Azure OpenAI
    needs_ai = result.confidence < 0.85 and not ai_response
    ai_prompt = None
    if needs_ai:
        oai = get_openai_client()
        if oai.is_available:
            prompt = build_triage_prompt(email)
            ai_resp = oai.triage_email(prompt)
            if ai_resp:
                result = triage_email(email, ai_response=ai_resp)
                needs_ai = False
        if needs_ai:
            ai_prompt = build_triage_prompt(email)

    # Attachment routing details
    att_routing = []
    if email.has_attachments:
        att_routing = [
            serialize_attachment_routing(r)
            for r in route_attachments(email.attachment_names)
        ]

    # Persist to Cosmos DB
    triage_data = serialize_triage_result(result)
    triage_data["email_subject"] = email.subject
    triage_data["email_sender"] = email.sender
    store = get_store()
    store.save_triage_result(triage_data)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "triage": serialize_triage_result(result),
            "attachment_routing": att_routing,
            "needs_ai_triage": needs_ai,
            "ai_prompt": ai_prompt,
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/email/draft-reply
# ---------------------------------------------------------------------------

@app.route(route="email/draft-reply", methods=["POST"])
def draft_reply(req: func.HttpRequest) -> func.HttpResponse:
    """Generate a draft reply, optionally using Azure OpenAI."""
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    message_id = body.get("message_id", "")
    subject = body.get("subject", "")
    email_body = body.get("body", "")
    sender_name = body.get("sender_name", "")
    tone = body.get("tone", "professional")

    if not message_id:
        return _error("'message_id' is required", 400)

    # Try Azure OpenAI for draft generation
    draft_data = None
    oai = get_openai_client()
    if oai.is_available:
        draft_data = oai.generate_draft_reply(
            email_subject=subject,
            email_body=email_body,
            sender_name=sender_name,
            tone=tone,
        )

    if draft_data:
        draft = DraftResponse(
            message_id=message_id,
            subject=draft_data.get("subject", f"Re: {subject}"),
            body=draft_data.get("body", ""),
            tone=tone,
            confidence=float(draft_data.get("confidence", 0.0)),
            needs_review=True,
        )
    else:
        # Return empty draft shell for manual composition
        draft = DraftResponse(
            message_id=message_id,
            subject=f"Re: {subject}",
            body="",
            tone=tone,
            confidence=0.0,
            needs_review=True,
        )

    # Persist draft
    draft_dict = serialize_draft_response(draft)
    store = get_store()
    store.save_draft(draft_dict)

    return func.HttpResponse(
        body=json.dumps({"success": True, "draft": draft_dict}),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# GET /api/email/drafts/{message_id}
# ---------------------------------------------------------------------------

@app.route(route="email/drafts/{message_id}", methods=["GET"])
def get_drafts(req: func.HttpRequest) -> func.HttpResponse:
    """Get all drafts for a given message."""
    message_id = req.route_params.get("message_id", "")
    if not message_id:
        return _error("message_id is required", 400)

    store = get_store()
    drafts = store.get_drafts_for_message(message_id)

    return func.HttpResponse(
        body=json.dumps({"success": True, "drafts": drafts}),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# PUT /api/email/drafts/{draft_id}
# ---------------------------------------------------------------------------

@app.route(route="email/drafts/{draft_id}", methods=["PUT"])
def update_draft(req: func.HttpRequest) -> func.HttpResponse:
    """Update a draft (edit body, approve for sending, etc.)."""
    draft_id = req.route_params.get("draft_id", "")
    if not draft_id:
        return _error("draft_id is required", 400)

    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    message_id = body.get("message_id", "")
    store = get_store()
    existing = store.get_draft(draft_id, message_id)

    if not existing:
        return _error("Draft not found", 404)

    # Update fields
    if "body" in body:
        existing["body"] = body["body"]
    if "subject" in body:
        existing["subject"] = body["subject"]
    if "tone" in body:
        existing["tone"] = body["tone"]
    if "approved" in body:
        existing["approved"] = body["approved"]
        existing["approved_at"] = datetime.now(timezone.utc).isoformat()
    existing["needs_review"] = not body.get("approved", False)

    store.save_draft(existing)

    return func.HttpResponse(
        body=json.dumps({"success": True, "draft": existing}),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# DELETE /api/email/drafts/{draft_id}
# ---------------------------------------------------------------------------

@app.route(route="email/drafts/{draft_id}", methods=["DELETE"])
def delete_draft(req: func.HttpRequest) -> func.HttpResponse:
    """Delete a draft response."""
    draft_id = req.route_params.get("draft_id", "")
    message_id = req.params.get("message_id", "")
    if not draft_id:
        return _error("draft_id is required", 400)

    store = get_store()
    store.delete_draft(draft_id, message_id)

    return func.HttpResponse(
        body=json.dumps({"success": True}),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/documents/classify
# ---------------------------------------------------------------------------

@app.route(route="documents/classify", methods=["POST"])
def classify_doc(req: func.HttpRequest) -> func.HttpResponse:
    """
    Classify a document attachment.

    Request body:
    {
      "filename": "Invoice_HES_March.pdf",
      "content_text": "<optional extracted text>",
      "source": "email",
      "source_detail": "msg-123"
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
    extraction_summary = None

    if not content_text and body.get("file_bytes_base64"):
        try:
            content_text, extraction_summary = _extract_document_text(
                filename=filename,
                file_bytes_base64=body.get("file_bytes_base64", ""),
                content_type=body.get("content_type", "application/pdf"),
            )
        except ValueError as e:
            return _error(str(e), 400)

    # Run classification
    classification = classify_document(filename, content_text, ai_response)

    # If low confidence and no AI response, try Azure OpenAI
    if classification.confidence < 0.85 and not ai_response:
        oai = get_openai_client()
        if oai.is_available:
            prompt = build_classification_prompt(filename, content_text or "")
            ai_resp = oai.classify_document(prompt)
            if ai_resp:
                classification = classify_document(filename, content_text, ai_resp)

    # Generate filing recommendation
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "pdf"
    filing = recommend_filing(classification, filename, ext)

    # Persist
    doc_data = {
        "document_id": body.get("document_id"),
        "filename": filename,
        "source": body.get("source", "upload"),
        "source_detail": body.get("source_detail", ""),
        "content_text_present": bool(content_text),
        "classification": serialize_classification_result(classification),
        "filing": serialize_filing_recommendation(filing),
    }
    if extraction_summary:
        doc_data["extraction"] = extraction_summary
    store = get_store()
    store.save_document(doc_data)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "classification": serialize_classification_result(classification),
            "filing": serialize_filing_recommendation(filing),
            "extraction": extraction_summary,
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/mailbox/ingest
# ---------------------------------------------------------------------------

@app.route(route="mailbox/ingest", methods=["POST"])
def ingest_mailbox(req: func.HttpRequest) -> func.HttpResponse:
    """Fetch unread messages from Graph, triage them, and stage attachments."""
    try:
        body = req.get_json()
    except ValueError:
        body = {}

    try:
        top = int(body.get("top", 10))
    except (TypeError, ValueError):
        return _error("'top' must be an integer", 400)
    mark_processed = bool(body.get("mark_processed", False))

    try:
        response_items = _run_mailbox_ingestion(
            top=top,
            mark_processed=mark_processed,
        )
    except RuntimeError as e:
        return _error(str(e), 503)

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "processed_count": len(response_items),
                "messages": response_items,
            }
        ),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# TIMER mailbox polling
# ---------------------------------------------------------------------------

@app.schedule(
    schedule="%MAILBOX_POLL_SCHEDULE%",
    arg_name="mailbox_timer",
    run_on_startup=False,
    use_monitor=False,
)
def poll_mailbox(mailbox_timer: func.TimerRequest) -> None:
    """Poll the mailbox on a timer when tenant config enables it."""
    if not _get_bool_setting("MAILBOX_POLL_ENABLED", False):
        logger.debug("Mailbox polling skipped because MAILBOX_POLL_ENABLED is false")
        return

    top = _get_int_setting("MAILBOX_POLL_TOP", DEFAULT_MAILBOX_POLL_TOP)
    mark_processed = _get_bool_setting("MAILBOX_MARK_PROCESSED", True)

    try:
        items = _run_mailbox_ingestion(
            top=top,
            mark_processed=mark_processed,
        )
        logger.info(
            "Mailbox polling completed: processed=%d top=%d past_due=%s",
            len(items),
            top,
            getattr(mailbox_timer, "past_due", False),
        )
    except RuntimeError as e:
        logger.warning("Mailbox polling skipped: %s", e)
    except Exception:
        logger.exception("Mailbox polling failed")
        raise


# ---------------------------------------------------------------------------
# POST /api/documents/correct
# ---------------------------------------------------------------------------

@app.route(route="documents/correct", methods=["POST"])
def correct_classification(req: func.HttpRequest) -> func.HttpResponse:
    """
    Log a user correction to a document classification.

    Request body:
    {
      "document_id": "...",
      "original_type": "contract",
      "corrected_type": "amendment",
      "original_path": "01_CORPORATE/Legal/Contracts",
      "corrected_path": "01_CORPORATE/Legal/Amendments",
      "notes": "This was actually an amendment to the MSA"
    }
    """
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    document_id = body.get("document_id", "")
    if not document_id:
        return _error("'document_id' is required", 400)

    try:
        original_type = DocumentType(body.get("original_type", "unknown"))
        corrected_type = DocumentType(body.get("corrected_type", "unknown"))
    except ValueError:
        return _error("Invalid document type", 400)

    entry = _correction_store.log_correction(
        document_id=document_id,
        original_type=original_type,
        corrected_type=corrected_type,
        original_path=body.get("original_path", ""),
        corrected_path=body.get("corrected_path", ""),
        notes=body.get("notes", ""),
    )

    # Persist to Cosmos DB
    store = get_store()
    store.save_correction({
        "correction_id": entry.correction_id,
        "document_id": entry.document_id,
        "original_type": entry.original_type.value,
        "corrected_type": entry.corrected_type.value,
        "original_path": entry.original_path,
        "corrected_path": entry.corrected_path,
        "corrected_at": entry.corrected_at.isoformat(),
        "notes": entry.notes,
    })

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "correction_id": entry.correction_id,
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# GET /api/triage/history
# ---------------------------------------------------------------------------

@app.route(route="triage/history", methods=["GET"])
def triage_history(req: func.HttpRequest) -> func.HttpResponse:
    """Query triage result history from Cosmos DB."""
    date_filter = req.params.get("date")
    limit = int(req.params.get("limit", "50"))

    store = get_store()
    results = store.query_triage_results(partition_date=date_filter, limit=limit)

    return func.HttpResponse(
        body=json.dumps({"success": True, "results": results, "count": len(results)}),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    store = get_store()
    oai = get_openai_client()
    graph = get_graph_client()
    doc_client = get_doc_intelligence_client()

    return func.HttpResponse(
        body=json.dumps({
            "status": "healthy",
            "service": "email-intelligence",
            "version": "2.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cosmos_connected": store.is_connected,
            "storage_backend": store.storage_backend,
            "openai_available": oai.is_available,
            "graph_available": graph.is_available,
            "graph_mailbox_available": graph.mailbox_available,
            "sharepoint_upload_available": graph.sharepoint_available,
            "document_intelligence_available": doc_client.is_available,
            "mailbox_poll_enabled": _get_bool_setting("MAILBOX_POLL_ENABLED", False),
            "mailbox_poll_schedule": os.environ.get(
                "MAILBOX_POLL_SCHEDULE",
                DEFAULT_MAILBOX_POLL_SCHEDULE,
            ),
            "mailbox_poll_top": _get_int_setting(
                "MAILBOX_POLL_TOP",
                DEFAULT_MAILBOX_POLL_TOP,
            ),
            "triage_results_stored": store.count_triage_results(),
            "drafts_stored": store.count_drafts(),
            "documents_stored": store.count_documents(),
            "corrections_stored": store.count_corrections(),
            "readiness": {
                "mailbox_ingestion_ready": graph.mailbox_available,
                "mailbox_timer_ready": _get_bool_setting("MAILBOX_POLL_ENABLED", False)
                and graph.mailbox_available,
                "sharepoint_filing_ready": graph.sharepoint_available,
                "document_classification_ready": True,
                "production_ai_ready": oai.is_available,
            },
        }),
        mimetype="application/json",
        status_code=200,
    )


def _error(message: str, status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps({"success": False, "error": message}),
        mimetype="application/json",
        status_code=status_code,
    )


def _decode_file_bytes(file_bytes_base64: str) -> bytes:
    try:
        return base64.b64decode(file_bytes_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("Invalid 'file_bytes_base64' payload") from e


def _extract_document_text(
    filename: str,
    file_bytes_base64: str,
    content_type: str,
) -> tuple[str, dict[str, object]]:
    file_bytes = _decode_file_bytes(file_bytes_base64)
    return extract_document_text_from_bytes(
        filename,
        file_bytes,
        content_type=content_type,
        doc_intelligence_client=get_doc_intelligence_client(),
    )


def _run_mailbox_ingestion(
    *,
    top: int,
    mark_processed: bool,
    service: MailboxIngestionService | None = None,
    store=None,
) -> list[dict[str, object]]:
    mailbox_service = service or MailboxIngestionService()
    if not mailbox_service.is_available:
        raise RuntimeError("Microsoft Graph mailbox configuration is incomplete")

    data_store = store or get_store()
    processed = mailbox_service.process_unread_messages(
        top=top,
        mark_processed=mark_processed,
    )

    response_items: list[dict[str, object]] = []
    for item in processed:
        triage_data = serialize_triage_result(item.triage)
        triage_data["email_subject"] = item.email.subject
        triage_data["email_sender"] = item.email.sender
        data_store.save_triage_result(triage_data)

        attachment_items: list[dict[str, object]] = []
        for attachment in item.attachments:
            attachment_items.append(
                {
                    "attachment_id": attachment.attachment.attachment_id,
                    "filename": attachment.attachment.name,
                    "content_type": attachment.attachment.content_type,
                    "classification": serialize_classification_result(attachment.classification),
                    "filing": serialize_filing_recommendation(attachment.filing),
                    "extraction": attachment.extraction_summary,
                    "sharepoint_target": attachment.sharepoint_target,
                    "upload": attachment.upload_result,
                }
            )
            data_store.save_document(
                {
                    "document_id": (
                        attachment.attachment.attachment_id
                        or f"{item.email.message_id}:{attachment.attachment.name}"
                    ),
                    "message_id": item.email.message_id,
                    "filename": attachment.attachment.name,
                    "source": "mailbox_ingestion",
                    "source_detail": item.email.sender,
                    "content_text_present": bool(attachment.extraction_text),
                    "classification": serialize_classification_result(attachment.classification),
                    "filing": serialize_filing_recommendation(attachment.filing),
                    "extraction": attachment.extraction_summary,
                    "sharepoint_target": attachment.sharepoint_target,
                    "upload": attachment.upload_result,
                }
            )

        response_items.append(
            {
                "email": serialize_email(item.email),
                "triage": serialize_triage_result(item.triage),
                "attachments": attachment_items,
                "ai_used": item.ai_used,
                "marked_processed": item.marked_processed,
            }
        )

    return response_items
