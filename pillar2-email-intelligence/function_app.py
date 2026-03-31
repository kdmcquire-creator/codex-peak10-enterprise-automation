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
from datetime import datetime, timedelta, timezone

import azure.functions as func

from email_intel.models import EmailCategory, EmailMessage, DraftResponse, EventDraft
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
    serialize_event_draft,
    serialize_classification_result,
    serialize_filing_recommendation,
)
from email_intel.cosmos_client import get_store
from email_intel.graph_client import GraphRequestError, get_graph_client, reset_graph_client
from email_intel.ingestion_service import MailboxIngestionService
from email_intel.briefing import build_morning_brief, present_brief_item
from email_intel.insights import build_growth_nudges
from email_intel.openai_client import get_openai_client
from email_intel.pillar_clients import get_document_ai_client
from email_intel.doc_intelligence import (
    get_doc_intelligence_client,
)
from email_intel.attachment_processing import extract_document_text_from_bytes
from email_intel.calendar import assist_calendar_request, build_calendar_assistant_prompt
from email_intel.calendar import build_event_draft
from email_intel.classifier import classify_document, build_classification_prompt
from email_intel.brief_review import build_brief_review_html
from email_intel.naming import recommend_filing
from email_intel.corrections import CorrectionStore
from email_intel.document_models import DocumentType

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
logger = logging.getLogger("email-intel")

# Module-level correction store (backed by Cosmos in production)
_correction_store = CorrectionStore()

DEFAULT_MAILBOX_POLL_SCHEDULE = "0 */1 * * * *"
DEFAULT_MAILBOX_POLL_TOP = 10
DEFAULT_OUTBOUND_EMAIL_MODE = "dry_run"


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


def _get_str_setting(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip()
    return value or default


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
    triage_data["email"] = serialize_email(email)
    triage_data["email_subject"] = email.subject
    triage_data["email_sender"] = email.sender
    triage_data["email_sender_name"] = email.sender_name
    triage_data["email_recipients"] = email.recipients
    triage_data["received_at"] = email.received_at.isoformat()
    triage_data["conversation_id"] = email.conversation_id
    store = get_store()
    persisted, warnings = _persist_with_warning(
        lambda: store.save_triage_result(triage_data),
        warning_code="triage_persist_failed",
        log_message="Failed to persist triage result for %s: %s",
        log_args=(result.message_id or email.subject or "<unknown>",),
    )

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "persisted": persisted,
            "triage": serialize_triage_result(result),
            "attachment_routing": att_routing,
            "needs_ai_triage": needs_ai,
            "ai_prompt": ai_prompt,
            "warnings": warnings,
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
    to_recipients = _normalize_email_addresses(body.get("to_recipients", []))
    cc_recipients = _normalize_email_addresses(body.get("cc_recipients", []))

    if not message_id:
        return _error("'message_id' is required", 400)

    draft_dict, persisted, warnings = _create_and_persist_draft(
        message_id=message_id,
        subject=subject,
        email_body=email_body,
        sender_name=sender_name,
        tone=tone,
        to_recipients=to_recipients,
        cc_recipients=cc_recipients,
    )

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "persisted": persisted,
                "draft": draft_dict,
                "warnings": warnings,
            }
        ),
        mimetype="application/json",
        status_code=200,
    )


@app.route(route="email/brief/items/{item_id}/actions", methods=["POST"])
def act_on_brief_item(req: func.HttpRequest) -> func.HttpResponse:
    """Run a direct operator action from a Morning Brief item."""
    item_id = req.route_params.get("item_id", "")
    if not item_id:
        return _error("item_id is required", 400)

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    action = str(body.get("action", "")).strip().lower()
    if action not in {"archive", "mark_read", "mark_read_archive", "generate_reply_draft", "generate_event_draft"}:
        return _error(
            "'action' must be one of: archive, mark_read, mark_read_archive, generate_reply_draft, generate_event_draft",
            400,
        )

    store = get_store()
    item = store.find_brief_item_by_id(item_id) if hasattr(store, "find_brief_item_by_id") else None
    if not item:
        return _error("Brief item not found", 404)

    message_id = _resolve_brief_item_message_id(item, store=store)
    if not message_id:
        return _error("No source message could be resolved for this brief item", 400)

    graph = get_graph_client()
    if not graph.mailbox_available:
        return _error("Microsoft Graph mailbox configuration is incomplete", 503)

    requested_by = str(body.get("requested_by", "")).strip()
    notes = str(body.get("notes", "")).strip()
    reason_code = str(body.get("reason", "")).strip().lower()
    state_after_action = str(body.get("state_after_action", "")).strip().lower()
    timestamp = datetime.now(timezone.utc).isoformat()

    response_payload: dict[str, object] = {
        "success": True,
        "action": action,
        "item_id": item_id,
        "message_id": message_id,
    }
    response_warnings: list[str] = []

    try:
        if action in {"archive", "mark_read", "mark_read_archive"}:
            mailbox_payload = _brief_mailbox_action_payload(action)
            update_result: dict[str, object] = {}
            update_error: dict[str, object] = {}
            move_result: dict[str, object] = {}
            move_error: dict[str, object] = {}
            fallback: dict[str, object] = {"applied": False}
            destination_folder = str(mailbox_payload["destination_folder"])
            if mailbox_payload["updates"]:
                try:
                    update_result = graph.update_message(message_id, mailbox_payload["updates"])
                except GraphRequestError as exc:
                    update_error = _graph_error_details(exc)
                    if action in {"archive", "mark_read_archive"} and _is_missing_graph_item_error(exc):
                        fallback = {
                            "applied": True,
                            "mode": "resolve_missing_source",
                            "reason": "source_message_missing",
                        }
                        response_warnings.append(
                            "archive_source_missing"
                            if not update_error.get("code")
                            else f"archive_source_missing:{update_error['code']}"
                        )
                        if not state_after_action:
                            state_after_action = "resolved"
                        if not reason_code:
                            reason_code = "source_missing"
                    else:
                        raise
            if destination_folder and not fallback.get("applied"):
                try:
                    move_result = graph.move_message(message_id, destination_folder)
                except GraphRequestError as exc:
                    move_error = _graph_error_details(exc)
                    if action in {"archive", "mark_read_archive"}:
                        fallback = {
                            "applied": True,
                            "mode": "mark_read_resolve",
                            "reason": "graph_move_failed",
                        }
                        response_warnings.append(
                            "archive_move_failed"
                            if not move_error.get("code")
                            else f"archive_move_failed:{move_error['code']}"
                        )
                        if not state_after_action:
                            state_after_action = "resolved"
                        if not reason_code:
                            reason_code = "archive_fallback"
                    else:
                        raise
            response_payload["mailbox_action"] = {
                "updated": bool(update_result),
                "moved": bool(move_result),
                "update_result": update_result,
                "update_error": update_error,
                "move_result": move_result,
                "move_error": move_error,
                "fallback": fallback,
                "applied": {
                    "mark_read": mailbox_payload["updates"].get("isRead"),
                    "categories": mailbox_payload["updates"].get("categories", []),
                    "destination_folder": destination_folder,
                },
            }
            if not state_after_action:
                state_after_action = "resolved" if action in {"archive", "mark_read_archive"} else ""
            if not reason_code and action in {"archive", "mark_read_archive"}:
                reason_code = "archived"

        elif action == "generate_reply_draft":
            message = graph.get_message(
                message_id,
                select_fields=["id", "subject", "bodyPreview", "from", "replyTo", "toRecipients", "ccRecipients"],
            )
            if not message:
                return _error("Unable to load the source message from Microsoft Graph", 502)

            subject = _graph_message_subject(message)
            sender_name = _graph_message_sender_name(message)
            email_body = _graph_message_body_preview(message)
            recipients = _resolve_reply_recipients(message)
            draft_dict, persisted, warnings = _create_and_persist_draft(
                message_id=message_id,
                subject=subject,
                email_body=email_body,
                sender_name=sender_name,
                tone=str(body.get("tone", "professional")).strip() or "professional",
                to_recipients=recipients,
                cc_recipients=[],
            )
            response_payload["draft"] = draft_dict
            response_payload["persisted"] = persisted
            response_payload["warnings"] = warnings
            if not state_after_action:
                state_after_action = ""
            if not reason_code:
                reason_code = "replied"

        elif action == "generate_event_draft":
            message = graph.get_message(
                message_id,
                select_fields=[
                    "id",
                    "subject",
                    "bodyPreview",
                    "body",
                    "from",
                    "replyTo",
                    "toRecipients",
                    "ccRecipients",
                    "receivedDateTime",
                    "hasAttachments",
                    "conversationId",
                ],
            )
            if not message:
                return _error("Unable to load the source message from Microsoft Graph", 502)

            email = _graph_message_to_email(message)
            triage_result, guidance, used_ai = _build_calendar_guidance(
                email=email,
                calendar_hint=str(item.get("type") or item.get("source_bucket") or ""),
            )
            event_draft_payload = build_event_draft(email, guidance, triage=triage_result)
            event_draft, persisted, event_warnings = _create_and_persist_event_draft(
                email=email,
                event_draft_payload=event_draft_payload,
                guidance=guidance,
                approved_by=requested_by,
            )
            response_payload["triage"] = serialize_triage_result(triage_result)
            response_payload["calendar_assistance"] = guidance
            response_payload["event_draft"] = event_draft
            response_payload["persisted"] = persisted
            response_payload["ai_used"] = used_ai
            if event_warnings:
                response_warnings.extend(event_warnings)
            if not reason_code:
                reason_code = "monitor_only"

    except GraphRequestError as exc:
        details = _graph_error_details(exc)
        logger.warning("Failed to run brief item action %s for %s: %s", action, item_id, details)
        return func.HttpResponse(
            body=json.dumps(
                {
                    "success": False,
                    "error": f"Failed to run brief item action: {exc}",
                    "graph_error": details,
                    "action": action,
                    "item_id": item_id,
                    "message_id": message_id,
                }
            ),
            mimetype="application/json",
            status_code=502,
        )
    except Exception as exc:
        logger.warning("Failed to run brief item action %s for %s: %s", action, item_id, exc)
        return _error(f"Failed to run brief item action: {exc}", 502)

    item["last_operator_action"] = action
    item["last_operator_action_at"] = timestamp
    item["last_operator_action_by"] = requested_by
    if notes:
        item["last_operator_action_notes"] = notes
    history = item.get("action_history", [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "action": action,
            "at": timestamp,
            "by": requested_by,
            "notes": notes,
        }
    )
    item["action_history"] = history[-20:]

    if state_after_action in {"open", "resolved", "dismissed"}:
        item["state"] = state_after_action
        item["state_changed_at"] = timestamp
        if reason_code:
            item["reason_code"] = reason_code
        if notes:
            item["reason_detail"] = notes
        if requested_by:
            item["updated_by"] = requested_by
        item["updated_at"] = timestamp
        if state_after_action == "open":
            item["carried_over"] = False

    try:
        store.save_brief_item(item)
    except Exception as exc:
        logger.warning("Failed to persist brief item action %s for %s: %s", action, item_id, exc)
        response_warnings.append(f"brief_item_persist_failed: {exc}")

    if response_warnings:
        response_payload["warnings"] = [*response_payload.get("warnings", []), *response_warnings]
    response_payload["item"] = present_brief_item(item)
    return func.HttpResponse(
        body=json.dumps(response_payload),
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
# GET /api/email/messages/{message_id}/event-drafts
# ---------------------------------------------------------------------------

@app.route(route="email/messages/{message_id}/event-drafts", methods=["GET"])
def get_event_drafts(req: func.HttpRequest) -> func.HttpResponse:
    """Get all event drafts for a given source message."""
    message_id = req.route_params.get("message_id", "")
    if not message_id:
        return _error("message_id is required", 400)

    store = get_store()
    drafts = (
        store.get_event_drafts_for_message(message_id)
        if hasattr(store, "get_event_drafts_for_message")
        else []
    )

    return func.HttpResponse(
        body=json.dumps({"success": True, "event_drafts": drafts}),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/email/calendar/assist
# ---------------------------------------------------------------------------

@app.route(route="email/calendar/assist", methods=["POST"])
def calendar_assist(req: func.HttpRequest) -> func.HttpResponse:
    """Analyze an email for scheduling intent and return meeting-assistant guidance."""
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    if not body.get("subject") and not body.get("sender"):
        return _error("'subject' or 'sender' is required", 400)

    email = EmailMessage(
        message_id=body.get("message_id", ""),
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

    triage_result, guidance, used_ai = _build_calendar_guidance(
        email=email,
        triage_ai_response=body.get("triage_ai_response"),
        ai_response=body.get("ai_response"),
        calendar_hint=str(body.get("calendar_hint", "") or ""),
    )
    event_draft = build_event_draft(email, guidance, triage=triage_result)
    persisted = False
    warnings: list[str] = []
    if bool(body.get("persist")):
        event_draft, persisted, warnings = _create_and_persist_event_draft(
            email=email,
            event_draft_payload=event_draft,
            guidance=guidance,
            approved_by=str(body.get("approved_by", "")).strip(),
        )

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "triage": serialize_triage_result(triage_result),
                "calendar_assistance": guidance,
                "event_draft": event_draft,
                "ai_used": used_ai or bool(body.get("ai_response")),
                "persisted": persisted,
                "warnings": warnings,
            }
        ),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/email/messages/{message_id}/actions
# ---------------------------------------------------------------------------

@app.route(route="email/messages/{message_id}/actions", methods=["POST"])
def apply_mailbox_action(req: func.HttpRequest) -> func.HttpResponse:
    """Apply mailbox actions such as read-state changes, categories, and moves."""
    message_id = req.route_params.get("message_id", "")
    if not message_id:
        return _error("message_id is required", 400)

    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    graph = get_graph_client()
    if not graph.mailbox_available:
        return _error("Microsoft Graph mailbox configuration is incomplete", 503)

    categories = _normalize_string_list(body.get("categories"))
    if not categories and body.get("category"):
        categories = _normalize_string_list([body.get("category")])

    updates: dict[str, object] = {}
    if "mark_read" in body:
        updates["isRead"] = bool(body.get("mark_read"))
    if categories:
        updates["categories"] = categories

    destination_folder = str(body.get("destination_folder", "")).strip()
    if not updates and not destination_folder:
        return _error(
            "At least one mailbox action is required: mark_read, category/categories, or destination_folder",
            400,
        )

    try:
        update_result = graph.update_message(message_id, updates) if updates else {}
        move_result = (
            graph.move_message(message_id, destination_folder)
            if destination_folder
            else {}
        )
    except GraphRequestError as exc:
        details = _graph_error_details(exc)
        logger.warning("Failed to apply mailbox action to %s: %s", message_id, details)
        return func.HttpResponse(
            body=json.dumps(
                {
                    "success": False,
                    "error": f"Failed to apply mailbox action: {exc}",
                    "graph_error": details,
                    "message_id": message_id,
                    "applied": {
                        "mark_read": updates.get("isRead"),
                        "categories": updates.get("categories", []),
                        "destination_folder": destination_folder,
                    },
                }
            ),
            mimetype="application/json",
            status_code=502,
        )
    except Exception as exc:
        logger.warning("Failed to apply mailbox action to %s: %s", message_id, exc)
        return _error(f"Failed to apply mailbox action: {exc}", 502)

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "message_id": message_id,
                "updated": bool(updates),
                "moved": bool(destination_folder),
                "update_result": update_result,
                "move_result": move_result,
                "applied": {
                    "mark_read": updates.get("isRead"),
                    "categories": updates.get("categories", []),
                    "destination_folder": destination_folder,
                },
            }
        ),
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

    store = get_store()
    existing = _get_existing_draft(
        store,
        draft_id,
        body.get("message_id", ""),
    )

    if not existing:
        return _error("Draft not found", 404)

    message_id = existing.get("message_id", "")

    # Update fields
    if "body" in body:
        existing["body"] = body["body"]
    if "subject" in body:
        existing["subject"] = body["subject"]
    if "tone" in body:
        existing["tone"] = body["tone"]
    if "to_recipients" in body:
        existing["to_recipients"] = _normalize_email_addresses(
            body.get("to_recipients", [])
        )
    if "cc_recipients" in body:
        existing["cc_recipients"] = _normalize_email_addresses(
            body.get("cc_recipients", [])
        )
    if "approval_note" in body:
        existing["approval_note"] = str(body.get("approval_note", "")).strip()
    if "approved" in body:
        existing["approved"] = bool(body["approved"])
        existing["approved_at"] = (
            datetime.now(timezone.utc).isoformat()
            if existing["approved"]
            else None
        )
        existing["approved_by"] = (
            str(body.get("approved_by", "")).strip()
            if existing["approved"]
            else ""
        )
    existing["needs_review"] = not existing.get("approved", False)
    if existing.get("sent"):
        existing["status"] = "sent"
    elif existing.get("approved"):
        existing["status"] = "approved"
    else:
        existing["status"] = "draft"

    persisted, warnings = _persist_with_warning(
        lambda: store.save_draft(existing),
        warning_code="draft_persist_failed",
        log_message="Failed to update draft %s for %s: %s",
        log_args=(draft_id, message_id),
    )

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "persisted": persisted,
                "draft": existing,
                "warnings": warnings,
            }
        ),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/email/drafts/{draft_id}/send
# ---------------------------------------------------------------------------

@app.route(route="email/drafts/{draft_id}/send", methods=["POST"])
def send_draft(req: func.HttpRequest) -> func.HttpResponse:
    """Send an approved draft reply using the monitored mailbox."""
    draft_id = req.route_params.get("draft_id", "")
    if not draft_id:
        return _error("draft_id is required", 400)

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    store = get_store()
    existing = _get_existing_draft(
        store,
        draft_id,
        body.get("message_id", ""),
    )
    if not existing:
        return _error("Draft not found", 404)
    if existing.get("sent"):
        return _error("Draft has already been sent", 409)

    graph = get_graph_client()
    if not graph.mailbox_available:
        return _error("Microsoft Graph mailbox configuration is incomplete", 503)

    message_id = existing.get("message_id", "")
    original_message = graph.get_message(
        message_id,
        select_fields=["id", "from", "replyTo", "toRecipients", "ccRecipients"],
    )

    to_recipients = _normalize_email_addresses(
        body.get("to_recipients") or existing.get("to_recipients", [])
    ) or _resolve_reply_recipients(original_message)
    cc_recipients = _normalize_email_addresses(
        body.get("cc_recipients") or existing.get("cc_recipients", [])
    )

    if not to_recipients:
        return _error("No reply recipients could be determined for this draft", 400)

    subject = body.get("subject", existing.get("subject", ""))
    draft_body = body.get("body", existing.get("body", ""))
    approved_by = str(
        body.get("approved_by")
        or existing.get("approved_by", "")
        or body.get("requested_by", "")
    ).strip()
    requested_by = str(body.get("requested_by", "")).strip()
    delivery_mode = _get_outbound_email_mode(
        body.get("delivery_mode") or body.get("mode")
    )
    if "approval_note" in body:
        existing["approval_note"] = str(body.get("approval_note", "")).strip()

    allowed, block_reason = _evaluate_outbound_recipients(
        [*to_recipients, *cc_recipients]
    )
    timestamp = datetime.now(timezone.utc).isoformat()
    existing["subject"] = subject
    existing["body"] = draft_body
    existing["to_recipients"] = to_recipients
    existing["cc_recipients"] = cc_recipients
    existing["approved"] = True
    existing["approved_at"] = existing.get("approved_at") or timestamp
    existing["approved_by"] = approved_by or existing.get("approved_by", "")
    existing["needs_review"] = False
    existing["last_send_attempt_at"] = timestamp
    existing["last_send_attempted_by"] = requested_by or approved_by
    existing["delivery_mode"] = delivery_mode
    existing["send_block_reason"] = ""
    existing["status"] = "approved"

    if not allowed:
        existing["send_block_reason"] = block_reason
        persisted, warnings = _persist_with_warning(
            lambda: store.save_draft(existing),
            warning_code="draft_persist_failed",
            log_message="Failed to persist blocked draft %s for %s: %s",
            log_args=(draft_id, message_id),
        )
        return func.HttpResponse(
            body=json.dumps(
                {
                    "success": False,
                    "sent": False,
                    "persisted": persisted,
                    "draft": existing,
                    "warnings": warnings,
                    "error": block_reason,
                }
            ),
            mimetype="application/json",
            status_code=403,
        )

    if delivery_mode == "disabled":
        existing["send_block_reason"] = "Outbound email sending is disabled"
        persisted, warnings = _persist_with_warning(
            lambda: store.save_draft(existing),
            warning_code="draft_persist_failed",
            log_message="Failed to persist disabled draft %s for %s: %s",
            log_args=(draft_id, message_id),
        )
        return func.HttpResponse(
            body=json.dumps(
                {
                    "success": False,
                    "sent": False,
                    "persisted": persisted,
                    "draft": existing,
                    "warnings": warnings,
                    "error": "Outbound email sending is disabled",
                }
            ),
            mimetype="application/json",
            status_code=403,
        )

    if delivery_mode == "send":
        try:
            graph.send_mail(
                to_recipients=to_recipients,
                cc_recipients=cc_recipients,
                subject=subject,
                body=draft_body,
            )
        except Exception as exc:
            logger.warning("Failed to send draft %s for %s: %s", draft_id, message_id, exc)
            return _error(f"Failed to send draft: {exc}", 502)
        existing["sent"] = True
        existing["sent_at"] = timestamp
        existing["sent_by"] = requested_by or approved_by
        existing["status"] = "sent"
        sent = True
    else:
        sent = False

    persisted, warnings = _persist_with_warning(
        lambda: store.save_draft(existing),
        warning_code="draft_persist_failed",
        log_message="Failed to persist sent draft %s for %s: %s",
        log_args=(draft_id, message_id),
    )

    resolved_item = None
    brief_item_id = str(body.get("brief_item_id", "")).strip()
    if sent and brief_item_id and hasattr(store, "find_brief_item_by_id"):
        brief_item = store.find_brief_item_by_id(brief_item_id)
        if brief_item:
            brief_item["state"] = "resolved"
            brief_item["updated_at"] = timestamp
            brief_item["state_changed_at"] = timestamp
            brief_item["reason_code"] = "replied"
            brief_item["reason_detail"] = str(body.get("notes", "")).strip()
            if requested_by or approved_by:
                brief_item["updated_by"] = requested_by or approved_by
            try:
                store.save_brief_item(brief_item)
                resolved_item = present_brief_item(brief_item)
            except Exception as exc:
                logger.warning(
                    "Failed to resolve brief item %s after sending draft %s: %s",
                    brief_item_id,
                    draft_id,
                    exc,
                )
                warnings.append("brief_item_resolve_failed")

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "sent": sent,
                "persisted": persisted,
                "delivery_mode": delivery_mode,
                "draft": existing,
                "resolved_item": resolved_item,
                "warnings": warnings,
            }
        ),
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
    if not draft_id:
        return _error("draft_id is required", 400)

    store = get_store()
    existing = _get_existing_draft(
        store,
        draft_id,
        req.params.get("message_id", ""),
    )
    if not existing:
        return _error("Draft not found", 404)

    store.delete_draft(draft_id, existing.get("message_id", ""))

    return func.HttpResponse(
        body=json.dumps({"success": True}),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# PUT /api/email/event-drafts/{event_draft_id}
# ---------------------------------------------------------------------------

@app.route(route="email/event-drafts/{event_draft_id}", methods=["PUT"])
def update_event_draft(req: func.HttpRequest) -> func.HttpResponse:
    """Update a persisted event draft for review and approval workflows."""
    event_draft_id = req.route_params.get("event_draft_id", "")
    if not event_draft_id:
        return _error("event_draft_id is required", 400)

    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    store = get_store()
    existing = _get_existing_event_draft(
        store,
        event_draft_id,
        body.get("source_message_id", ""),
    )
    if not existing:
        return _error("Event draft not found", 404)

    source_message_id = existing.get("source_message_id", "")
    for field in (
        "title",
        "attendees",
        "candidate_time_phrases",
        "duration_minutes",
        "meeting_format",
        "location_hint",
        "summary",
        "description",
        "suggested_action",
        "review_notes",
        "status",
        "scheduled_start_at",
        "scheduled_end_at",
    ):
        if field in body:
            existing[field] = body[field]

    if "approved" in body:
        existing["approved"] = bool(body["approved"])
        existing["approved_at"] = (
            datetime.now(timezone.utc).isoformat()
            if existing["approved"]
            else None
        )
        existing["approved_by"] = (
            str(body.get("approved_by", "")).strip()
            if existing["approved"]
            else ""
        )
    existing["needs_review"] = not existing.get("approved", False)
    if existing.get("approved") and not existing.get("status"):
        existing["status"] = "approved"
    elif existing.get("approved"):
        existing["status"] = "approved"
    elif not existing.get("created_event"):
        existing["status"] = "draft"

    persisted, warnings = _persist_with_warning(
        lambda: store.save_event_draft(existing),
        warning_code="event_draft_persist_failed",
        log_message="Failed to update event draft %s for %s: %s",
        log_args=(event_draft_id, source_message_id),
    )

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "persisted": persisted,
                "event_draft": existing,
                "warnings": warnings,
            }
        ),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# DELETE /api/email/event-drafts/{event_draft_id}
# ---------------------------------------------------------------------------

@app.route(route="email/event-drafts/{event_draft_id}", methods=["DELETE"])
def delete_event_draft(req: func.HttpRequest) -> func.HttpResponse:
    """Delete a persisted event draft."""
    event_draft_id = req.route_params.get("event_draft_id", "")
    if not event_draft_id:
        return _error("event_draft_id is required", 400)

    store = get_store()
    existing = _get_existing_event_draft(
        store,
        event_draft_id,
        req.params.get("source_message_id", ""),
    )
    if not existing:
        return _error("Event draft not found", 404)

    if hasattr(store, "delete_event_draft"):
        store.delete_event_draft(event_draft_id, existing.get("source_message_id", ""))

    return func.HttpResponse(
        body=json.dumps({"success": True}),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/email/event-drafts/{event_draft_id}/create-event
# ---------------------------------------------------------------------------

@app.route(route="email/event-drafts/{event_draft_id}/create-event", methods=["POST"])
def create_event_from_draft(req: func.HttpRequest) -> func.HttpResponse:
    """Create a real calendar event from an approved event draft."""
    event_draft_id = req.route_params.get("event_draft_id", "")
    if not event_draft_id:
        return _error("event_draft_id is required", 400)

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    store = get_store()
    existing = _get_existing_event_draft(
        store,
        event_draft_id,
        body.get("source_message_id", ""),
    )
    if not existing:
        return _error("Event draft not found", 404)
    if not existing.get("approved"):
        return _error("Event draft must be approved before creating an event", 409)
    if existing.get("created_event"):
        return _error("Event draft has already been used to create an event", 409)

    schedule = _resolve_event_draft_schedule(existing, body)
    if not schedule:
        return _error(
            "A start time is required. Provide 'start_at' or update the event draft with a concrete candidate time first.",
            400,
        )

    graph = get_graph_client()
    if not graph.mailbox_available:
        return _error("Microsoft Graph mailbox configuration is incomplete", 503)

    requested_by = str(body.get("requested_by", "")).strip()
    attendees = _normalize_email_addresses(body.get("attendees", existing.get("attendees", [])))
    if not attendees:
        attendees = _normalize_email_addresses(existing.get("attendees", []))

    location_hint = str(body.get("location_hint", existing.get("location_hint", ""))).strip()
    description = str(body.get("description", existing.get("description", ""))).strip()

    try:
        created = graph.create_calendar_event(
            subject=str(existing.get("title", "")).strip() or "Scheduling follow-up",
            body=description,
            attendees=attendees,
            start_iso=schedule["start_at"],
            end_iso=schedule["end_at"],
            location_display_name=location_hint,
        )
    except GraphRequestError as exc:
        if _should_retry_graph_auth_error(exc):
            logger.info(
                "Retrying calendar event creation for draft %s after resetting cached Graph token",
                event_draft_id,
            )
            reset_graph_client()
            graph = get_graph_client()
            try:
                created = graph.create_calendar_event(
                    subject=str(existing.get("title", "")).strip() or "Scheduling follow-up",
                    body=description,
                    attendees=attendees,
                    start_iso=schedule["start_at"],
                    end_iso=schedule["end_at"],
                    location_display_name=location_hint,
                )
            except GraphRequestError as retry_exc:
                exc = retry_exc
            else:
                exc = None
        if exc is None:
            pass
        else:
            details = _graph_error_details(exc)
            logger.warning("Failed to create calendar event from draft %s: %s", event_draft_id, details)
            return func.HttpResponse(
                body=json.dumps(
                    {
                        "success": False,
                        "error": f"Failed to create calendar event: {exc}",
                        "graph_error": details,
                        "event_draft_id": event_draft_id,
                    }
                ),
                mimetype="application/json",
                status_code=502,
            )

    now_text = datetime.now(timezone.utc).isoformat()
    existing["created_event"] = True
    existing["created_event_at"] = now_text
    existing["created_event_by"] = requested_by
    existing["created_event_id"] = str(created.get("id", "")).strip()
    existing["created_event_web_link"] = str(created.get("webLink", "")).strip()
    existing["status"] = "event_created"
    existing["needs_review"] = False
    existing["attendees"] = attendees
    existing["location_hint"] = location_hint or existing.get("location_hint", "")
    existing["scheduled_start_at"] = schedule["start_at"]
    existing["scheduled_end_at"] = schedule["end_at"]

    persisted, warnings = _persist_with_warning(
        lambda: store.save_event_draft(existing),
        warning_code="event_draft_persist_failed",
        log_message="Failed to persist created-event state for event draft %s: %s",
        log_args=(event_draft_id,),
    )

    resolved_item = None
    brief_item_id = str(body.get("brief_item_id", "")).strip()
    if brief_item_id and hasattr(store, "find_brief_item_by_id"):
        brief_item = store.find_brief_item_by_id(brief_item_id)
        if brief_item:
            brief_item["state"] = "resolved"
            brief_item["updated_at"] = now_text
            brief_item["state_changed_at"] = now_text
            brief_item["reason_code"] = "scheduled"
            brief_item["reason_detail"] = str(body.get("notes", "")).strip()
            if requested_by:
                brief_item["updated_by"] = requested_by
            try:
                store.save_brief_item(brief_item)
                resolved_item = present_brief_item(brief_item)
            except Exception as exc:
                logger.warning(
                    "Failed to resolve brief item %s after creating calendar event from draft %s: %s",
                    brief_item_id,
                    event_draft_id,
                    exc,
                )
                warnings.append("brief_item_resolve_failed")

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "persisted": persisted,
                "event_draft": existing,
                "created_event": {
                    "id": existing["created_event_id"],
                    "web_link": existing["created_event_web_link"],
                    "start_at": existing["scheduled_start_at"],
                    "end_at": existing["scheduled_end_at"],
                    "attendees": attendees,
                },
                "resolved_item": resolved_item,
                "warnings": warnings,
            }
        ),
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
    persisted, warnings = _persist_with_warning(
        lambda: store.save_document(doc_data),
        warning_code="document_persist_failed",
        log_message="Failed to persist document classification for %s: %s",
        log_args=(filename,),
    )

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "persisted": persisted,
            "classification": serialize_classification_result(classification),
            "filing": serialize_filing_recommendation(filing),
            "extraction": extraction_summary,
            "warnings": warnings,
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
                "summary": _summarize_mailbox_ingestion(response_items),
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
        summary = _summarize_mailbox_ingestion(items)
        logger.info(
            (
                "Mailbox polling completed: processed=%d marked=%d attachments=%d "
                "uploaded=%d warnings=%d top=%d past_due=%s"
            ),
            summary["processed_messages"],
            summary["messages_marked_processed"],
            summary["attachments_processed"],
            summary["attachments_uploaded"],
            summary["warnings_count"],
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
    persisted, warnings = _persist_with_warning(
        lambda: store.save_correction(
            {
                "correction_id": entry.correction_id,
                "document_id": entry.document_id,
                "original_type": entry.original_type.value,
                "corrected_type": entry.corrected_type.value,
                "original_path": entry.original_path,
                "corrected_path": entry.corrected_path,
                "corrected_at": entry.corrected_at.isoformat(),
                "notes": entry.notes,
            }
        ),
        warning_code="correction_persist_failed",
        log_message="Failed to persist correction for %s: %s",
        log_args=(document_id,),
    )

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "correction_id": entry.correction_id,
            "persisted": persisted,
            "warnings": warnings,
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
# POST /api/email/brief/morning
# ---------------------------------------------------------------------------

@app.route(route="email/brief/morning", methods=["POST"])
def morning_brief(req: func.HttpRequest) -> func.HttpResponse:
    """Assemble a Morning Brief from recent triage history plus optional calendar inputs."""
    try:
        body = req.get_json()
    except ValueError:
        body = {}

    days = int(body.get("days", req.params.get("days", "14")))
    limit = int(body.get("limit", req.params.get("limit", "250")))
    sent_limit = int(body.get("sent_limit", req.params.get("sent_limit", "100")))
    lookback_days = int(body.get("lookback_days", req.params.get("lookback_days", "3")))
    carry_over_days = int(body.get("carry_over_days", req.params.get("carry_over_days", "7")))
    brief_item_window_days = int(
        body.get(
            "brief_item_window_days",
            req.params.get("brief_item_window_days", str(max(days, carry_over_days + 7))),
        )
    )
    calendar_items = body.get("calendar_items", [])
    personal_priorities = body.get("personal_priorities", [])
    now_override = body.get("now")
    now = datetime.fromisoformat(now_override) if isinstance(now_override, str) and now_override else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    store = get_store()
    if hasattr(store, "query_triage_activity"):
        results = store.query_triage_activity(days=days, limit=limit)
    else:
        results = store.query_triage_results(limit=limit)

    drafts = store.query_drafts(limit=sent_limit, sent_only=True) if hasattr(store, "query_drafts") else []
    warnings: list[str] = []
    try:
        stored_brief_items = (
            store.query_brief_items(
                since_days=brief_item_window_days,
                limit=limit,
            )
            if hasattr(store, "query_brief_items")
            else []
        )
    except Exception as exc:
        logger.warning("Failed to query Morning Brief carry-over items: %s", exc)
        stored_brief_items = []
        warnings.append(f"brief_item_query_failed: {exc}")
    brief = build_morning_brief(
        results,
        drafts=drafts,
        calendar_items=calendar_items if isinstance(calendar_items, list) else [],
        personal_priorities=personal_priorities if isinstance(personal_priorities, list) else [],
        stored_brief_items=stored_brief_items,
        draft_count=store.count_drafts(),
        document_count=store.count_documents(),
        now=now,
        lookback_days=lookback_days,
        carry_over_days=carry_over_days,
    )
    brief_items_persisted = 0
    for item in brief.get("brief_item_records", []):
        try:
            store.save_brief_item(item)
            brief_items_persisted += 1
        except Exception as exc:
            logger.warning("Failed to persist Morning Brief item %s: %s", item.get("item_id", "<unknown>"), exc)
            warnings.append(f"brief_item_persist_failed:{item.get('item_id', '<unknown>')}: {exc}")

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "count": len(results),
                "brief_items_persisted": brief_items_persisted,
                "warnings": warnings,
                **brief,
            }
        ),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/email/brief/items/{item_id}/state
# ---------------------------------------------------------------------------

@app.route(route="email/brief/review", methods=["GET"])
def brief_review_page(req: func.HttpRequest) -> func.HttpResponse:
    """Serve a lightweight operator UI for Morning Brief review workflows."""
    api_code = req.params.get("code", "")
    return func.HttpResponse(
        body=build_brief_review_html(api_code=api_code),
        mimetype="text/html",
        status_code=200,
    )

@app.route(route="email/brief/items", methods=["GET"])
def list_brief_items(req: func.HttpRequest) -> func.HttpResponse:
    """List recent Morning Brief items for UI review flows."""
    limit = int(req.params.get("limit", "100"))
    days = int(req.params.get("days", "30"))
    states = _split_setting_list(req.params.get("state", "open"))
    item_kinds = _split_setting_list(req.params.get("item_kind", ""))

    store = get_store()
    items = (
        store.query_brief_items(
            states=states or None,
            item_kinds=item_kinds or None,
            since_days=days,
            limit=limit,
        )
        if hasattr(store, "query_brief_items")
        else []
    )
    presented_items = [present_brief_item(item) for item in items]

    by_state: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for item in presented_items:
        by_state[item["state"]] = by_state.get(item["state"], 0) + 1
        by_kind[item["item_kind"]] = by_kind.get(item["item_kind"], 0) + 1

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "count": len(presented_items),
                "summary": {
                    "by_state": by_state,
                    "by_kind": by_kind,
                },
                "items": presented_items,
            }
        ),
        mimetype="application/json",
        status_code=200,
    )

@app.route(route="email/brief/items/{item_id}/context", methods=["GET"])
def get_brief_item_context(req: func.HttpRequest) -> func.HttpResponse:
    """Return the underlying message and draft context for a Morning Brief item."""
    item_id = req.route_params.get("item_id", "")
    if not item_id:
        return _error("item_id is required", 400)

    days = int(req.params.get("days", "30"))
    limit = int(req.params.get("limit", "12"))

    store = get_store()
    item = store.find_brief_item_by_id(item_id) if hasattr(store, "find_brief_item_by_id") else None
    if not item:
        return _error("Brief item not found", 404)

    context = _build_brief_item_context(item, store=store, days=days, limit=limit)
    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "item": present_brief_item(item),
                **context,
            }
        ),
        mimetype="application/json",
        status_code=200,
    )

@app.route(route="email/brief/items/{item_id}/state", methods=["POST"])
def update_brief_item_state(req: func.HttpRequest) -> func.HttpResponse:
    """Update the state of a Morning Brief follow-up or watchlist item."""
    item_id = req.route_params.get("item_id", "")
    if not item_id:
        return _error("item_id is required", 400)

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    state = str(body.get("state", "")).strip().lower()
    if state not in {"open", "resolved", "dismissed"}:
        return _error("'state' must be one of: open, resolved, dismissed", 400)

    store = get_store()
    item = store.find_brief_item_by_id(item_id) if hasattr(store, "find_brief_item_by_id") else None
    if not item:
        return _error("Brief item not found", 404)

    timestamp = datetime.now(timezone.utc).isoformat()
    updated_by = str(body.get("updated_by", "")).strip()
    notes = str(body.get("notes", "")).strip()
    reason_code = str(body.get("reason", "")).strip().lower()

    item["state"] = state
    item["updated_at"] = timestamp
    item["state_changed_at"] = timestamp
    if updated_by:
        item["updated_by"] = updated_by
    if notes:
        item["notes"] = notes
        item["reason_detail"] = notes
    if reason_code:
        item["reason_code"] = reason_code
    if state == "open":
        item["carried_over"] = False

    try:
        store.save_brief_item(item)
    except Exception as exc:
        logger.warning("Failed to persist Morning Brief state update for %s: %s", item_id, exc)
        return _error(f"Failed to update brief item state: {exc}", 500)

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "item": present_brief_item(item),
            }
        ),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# GET /api/email/insights/nudges
# ---------------------------------------------------------------------------

@app.route(route="email/insights/nudges", methods=["GET"])
def growth_nudges(req: func.HttpRequest) -> func.HttpResponse:
    """Summarize recent triage activity and return lightweight growth nudges."""
    date_filter = req.params.get("date")
    limit = int(req.params.get("limit", "50"))
    days = int(req.params.get("days", "90"))
    sent_limit = int(req.params.get("sent_limit", "100"))

    store = get_store()
    if hasattr(store, "query_triage_activity"):
        results = store.query_triage_activity(days=days, limit=limit)
    else:
        results = store.query_triage_results(partition_date=date_filter, limit=limit)

    drafts = store.query_drafts(limit=sent_limit, sent_only=True) if hasattr(store, "query_drafts") else []
    insights = build_growth_nudges(
        results,
        drafts=drafts,
        draft_count=store.count_drafts(),
        document_count=store.count_documents(),
    )

    return func.HttpResponse(
        body=json.dumps(
            {
                "success": True,
                "date": date_filter or datetime.now(timezone.utc).date().isoformat(),
                "count": len(results),
                **insights,
            }
        ),
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
    document_ai = get_document_ai_client()
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
            "pillar3_document_ai_available": document_ai.is_available,
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
            "event_drafts_stored": store.count_event_drafts() if hasattr(store, "count_event_drafts") else 0,
            "documents_stored": store.count_documents(),
            "corrections_stored": store.count_corrections(),
            "brief_items_stored": store.count_brief_items() if hasattr(store, "count_brief_items") else 0,
            "outbound_email_mode": _get_outbound_email_mode(),
            "readiness": {
                "mailbox_ingestion_ready": graph.mailbox_available,
                "mailbox_timer_ready": _get_bool_setting("MAILBOX_POLL_ENABLED", False)
                and graph.mailbox_available,
                "sharepoint_filing_ready": graph.sharepoint_available,
                "pillar3_stage_ready": document_ai.is_available,
                "document_classification_ready": True,
                "production_ai_ready": oai.is_available,
                "outbound_send_ready": graph.mailbox_available
                and _get_outbound_email_mode() == "send",
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


def _persist_with_warning(
    operation,
    *,
    warning_code: str,
    log_message: str,
    log_args: tuple[object, ...] = (),
) -> tuple[bool, list[str]]:
    try:
        operation()
        return True, []
    except Exception as exc:
        logger.warning(log_message, *log_args, exc)
        return False, [f"{warning_code}: {exc}"]


def _build_brief_item_context(
    item: dict[str, object],
    *,
    store,
    days: int,
    limit: int,
) -> dict[str, object]:
    triage_limit = max(limit * 8, 100)
    if hasattr(store, "query_triage_activity"):
        triage_items = store.query_triage_activity(days=days, limit=triage_limit)
    elif hasattr(store, "query_triage_results"):
        triage_items = store.query_triage_results(limit=triage_limit)
    else:
        triage_items = []

    matched_messages: list[dict[str, object]] = []
    seen_message_ids: set[str] = set()
    for triage_item in triage_items:
        matched_on = _match_brief_item_to_triage(item, triage_item)
        if not matched_on:
            continue
        message_id = _brief_context_message_id(triage_item)
        if message_id and message_id in seen_message_ids:
            continue
        if message_id:
            seen_message_ids.add(message_id)
        matched_messages.append(_serialize_brief_context_message(triage_item, matched_on=matched_on))

    matched_messages.sort(
        key=lambda message: str(message.get("saved_at") or message.get("received_at") or ""),
        reverse=True,
    )

    draft_limit = max(limit * 4, 50)
    drafts = store.query_drafts(limit=draft_limit, sent_only=False) if hasattr(store, "query_drafts") else []
    matched_drafts = [
        _serialize_brief_context_draft(draft, matched_on=matched_on)
        for draft in drafts
        if (matched_on := _match_brief_item_to_draft(item, draft))
    ]
    matched_drafts.sort(
        key=lambda draft: str(draft.get("sent_at") or draft.get("saved_at") or ""),
        reverse=True,
    )
    event_drafts = (
        store.query_event_drafts(limit=draft_limit, approved_only=False)
        if hasattr(store, "query_event_drafts")
        else []
    )
    matched_event_drafts = [
        _serialize_brief_context_event_draft(event_draft, matched_on=matched_on)
        for event_draft in event_drafts
        if (matched_on := _match_brief_item_to_event_draft(item, event_draft))
    ]
    matched_event_drafts.sort(
        key=lambda event_draft: str(event_draft.get("approved_at") or event_draft.get("saved_at") or ""),
        reverse=True,
    )

    latest_activity = ""
    for candidate in [*matched_messages, *matched_drafts, *matched_event_drafts]:
        timestamp = str(
            candidate.get("saved_at")
            or candidate.get("received_at")
            or candidate.get("sent_at")
            or candidate.get("approved_at")
            or ""
        )
        if timestamp > latest_activity:
            latest_activity = timestamp

    return {
        "summary": {
            "message_count": len(matched_messages[:limit]),
            "draft_count": len(matched_drafts[:limit]),
            "event_draft_count": len(matched_event_drafts[:limit]),
            "latest_activity_at": latest_activity,
        },
        "messages": matched_messages[:limit],
        "drafts": matched_drafts[: min(limit, 6)],
        "event_drafts": matched_event_drafts[: min(limit, 6)],
    }


def _resolve_brief_item_message_id(item: dict[str, object], *, store) -> str:
    source_message_id = str(item.get("source_message_id", "")).strip()
    if source_message_id:
        return source_message_id

    context = _build_brief_item_context(item, store=store, days=30, limit=1)
    messages = context.get("messages", [])
    if isinstance(messages, list) and messages:
        return str(messages[0].get("message_id", "")).strip()
    return ""


def _brief_mailbox_action_payload(action: str) -> dict[str, object]:
    if action == "archive":
        return {
            "updates": {"isRead": True, "categories": ["Peak10Processed"]},
            "destination_folder": "archive",
        }
    if action == "mark_read_archive":
        return {
            "updates": {"isRead": True, "categories": ["Peak10Processed"]},
            "destination_folder": "archive",
        }
    if action == "mark_read":
        return {
            "updates": {"isRead": True},
            "destination_folder": "",
        }
    return {
        "updates": {},
        "destination_folder": "",
    }


def _graph_error_details(exc: GraphRequestError) -> dict[str, object]:
    return {
        "status_code": exc.status_code,
        "code": exc.code,
        "message": str(exc),
        "url": exc.url,
    }


def _is_missing_graph_item_error(exc: GraphRequestError) -> bool:
    return exc.status_code == 404 and exc.code == "ErrorItemNotFound"


def _should_retry_graph_auth_error(exc: GraphRequestError) -> bool:
    return exc.status_code in {401, 403} and exc.code in {"InvalidAuthenticationToken", "ErrorAccessDenied"}


def _graph_message_subject(message: dict[str, object]) -> str:
    return str(message.get("subject", "")).strip()


def _graph_message_body_preview(message: dict[str, object]) -> str:
    body_preview = str(message.get("bodyPreview", "")).strip()
    if body_preview:
        return body_preview
    body = message.get("body", {})
    if isinstance(body, dict):
        return str(body.get("content", "")).strip()
    return ""


def _graph_message_to_email(message: dict[str, object]) -> EmailMessage:
    return EmailMessage(
        message_id=str(message.get("id", "")).strip(),
        subject=_graph_message_subject(message),
        sender=_graph_message_sender_address(message),
        sender_name=_graph_message_sender_name(message),
        recipients=_extract_graph_addresses(message.get("toRecipients")),
        body_preview=_graph_message_body_preview(message),
        body_text=_graph_message_body_preview(message),
        received_at=_parse_iso_datetime(
            str(message.get("receivedDateTime", "")).strip()
        ) or datetime.now(timezone.utc),
        has_attachments=bool(message.get("hasAttachments", False)),
        conversation_id=str(message.get("conversationId", "")).strip(),
        is_reply=bool(str(message.get("subject", "")).strip().lower().startswith("re:")),
    )


def _graph_message_sender_address(message: dict[str, object]) -> str:
    sender = message.get("from", {})
    if isinstance(sender, dict):
        email = sender.get("emailAddress", {})
        if isinstance(email, dict):
            return str(email.get("address", "")).strip()
    return ""


def _build_calendar_guidance(
    *,
    email: EmailMessage,
    triage_ai_response: object = None,
    ai_response: object = None,
    calendar_hint: str = "",
) -> tuple[object, dict[str, object], bool]:
    triage_result = triage_email(email, ai_response=triage_ai_response)
    normalized_hint = calendar_hint.strip().lower()
    hint_is_calendar = normalized_hint.startswith("calendar") or normalized_hint in {
        "meeting",
        "schedule",
        "scheduling",
    }
    if hint_is_calendar and triage_result.category != EmailCategory.CALENDAR:
        triage_result.category = EmailCategory.CALENDAR
        triage_result.confidence = max(triage_result.confidence, 0.72)
        if not triage_result.summary:
            triage_result.summary = "The source thread was already promoted as calendar-related."
        reasoning = str(triage_result.reasoning or "").strip()
        hint_reason = f"Brief item hint '{normalized_hint}' indicates calendar follow-up."
        triage_result.reasoning = f"{reasoning} {hint_reason}".strip() if reasoning else hint_reason

    used_ai = False
    calendar_ai_response = ai_response
    if not calendar_ai_response:
        oai = get_openai_client()
        if oai.is_available:
            prompt = build_calendar_assistant_prompt(email, triage_result)
            calendar_ai_response = oai.assist_calendar_request(prompt)
            used_ai = calendar_ai_response is not None

    guidance = assist_calendar_request(
        email,
        triage=triage_result,
        ai_response=calendar_ai_response,
    )
    if hint_is_calendar and not guidance.get("is_calendar_related"):
        guidance["is_calendar_related"] = True
        guidance["confidence"] = max(float(guidance.get("confidence", 0.0) or 0.0), 0.72)
        guidance["reasoning"] = (
            f"{str(guidance.get('reasoning', '')).strip()} "
            f"Brief item hint '{normalized_hint}' reinforced calendar intent."
        ).strip()
    if hint_is_calendar and guidance.get("meeting_request_type") == "unknown":
        proposed_times = [
            str(value).strip()
            for value in guidance.get("proposed_time_phrases", [])
            if str(value).strip()
        ]
        guidance["meeting_request_type"] = "new_request"
        guidance["suggested_action"] = "confirm_time" if proposed_times else "offer_times"
        if proposed_times:
            guidance["summary"] = (
                f"The thread is already being treated as a calendar follow-up and mentions {proposed_times[0]}."
            )
        elif not str(guidance.get("summary", "")).strip():
            guidance["summary"] = (
                "The thread is already being treated as a calendar follow-up and likely needs scheduling coordination."
            )
    return triage_result, guidance, used_ai


def _parse_iso_datetime(value: str) -> datetime | None:
    candidate = value.strip()
    if not candidate:
        return None
    try:
        normalized = candidate.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _graph_message_sender_name(message: dict[str, object]) -> str:
    sender = message.get("from", {})
    if isinstance(sender, dict):
        email_address = sender.get("emailAddress", {})
        if isinstance(email_address, dict):
            return str(email_address.get("name", "")).strip()
    return ""


def _create_and_persist_draft(
    *,
    message_id: str,
    subject: str,
    email_body: str,
    sender_name: str,
    tone: str,
    to_recipients: list[str],
    cc_recipients: list[str],
) -> tuple[dict[str, object], bool, list[str]]:
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
            to_recipients=to_recipients,
            cc_recipients=cc_recipients,
        )
    else:
        draft = DraftResponse(
            message_id=message_id,
            subject=f"Re: {subject}",
            body="",
            tone=tone,
            confidence=0.0,
            needs_review=True,
            to_recipients=to_recipients,
            cc_recipients=cc_recipients,
        )

    draft_dict = serialize_draft_response(draft)
    store = get_store()
    persisted, warnings = _persist_with_warning(
        lambda: store.save_draft(draft_dict),
        warning_code="draft_persist_failed",
        log_message="Failed to persist draft for %s: %s",
        log_args=(message_id,),
    )
    return draft_dict, persisted, warnings


def _create_and_persist_event_draft(
    *,
    email: EmailMessage,
    event_draft_payload: dict[str, object],
    guidance: dict[str, object],
    approved_by: str = "",
) -> tuple[dict[str, object], bool, list[str]]:
    event_draft = EventDraft(
        source_message_id=email.message_id,
        source_subject=email.subject,
        thread_key=email.conversation_id,
        title=str(event_draft_payload.get("title", "")).strip(),
        attendees=_normalize_email_addresses(event_draft_payload.get("attendees", [])),
        candidate_time_phrases=_normalize_string_list(
            event_draft_payload.get("candidate_time_phrases", [])
        ),
        duration_minutes=int(event_draft_payload.get("duration_minutes", 30) or 30),
        meeting_format=str(event_draft_payload.get("meeting_format", "unspecified")).strip() or "unspecified",
        location_hint=str(event_draft_payload.get("location_hint", "TBD")).strip() or "TBD",
        summary=str(event_draft_payload.get("summary", "")).strip(),
        description=str(event_draft_payload.get("description", "")).strip(),
        suggested_action=str(event_draft_payload.get("suggested_action", "")).strip(),
        needs_review=bool(event_draft_payload.get("needs_review", True)),
        confidence=float(event_draft_payload.get("confidence", 0.0) or 0.0),
        review_notes=str(event_draft_payload.get("review_notes", "")).strip()
        or str(guidance.get("reasoning", "")).strip(),
        approved=False,
        approved_by=approved_by,
        scheduled_start_at=str(event_draft_payload.get("scheduled_start_at", "")).strip() or None,
        scheduled_end_at=str(event_draft_payload.get("scheduled_end_at", "")).strip() or None,
    )
    draft_dict = serialize_event_draft(event_draft)
    store = get_store()
    persisted, warnings = _persist_with_warning(
        lambda: store.save_event_draft(draft_dict),
        warning_code="event_draft_persist_failed",
        log_message="Failed to persist event draft for %s: %s",
        log_args=(email.message_id or email.subject or "<unknown>",),
    )
    return draft_dict, persisted, warnings


def _match_brief_item_to_triage(item: dict[str, object], triage_item: dict[str, object]) -> str | None:
    item_message_id = str(item.get("source_message_id", "")).strip()
    triage_message_id = _brief_context_message_id(triage_item)
    if item_message_id and triage_message_id and item_message_id == triage_message_id:
        return "source_message"

    item_thread_key = str(item.get("thread_key", "")).strip().lower()
    triage_thread_key = _brief_context_thread_key(triage_item).lower()
    if item_thread_key and triage_thread_key and item_thread_key == triage_thread_key:
        return "thread"

    item_contact = str(item.get("contact") or item.get("source_sender") or "").strip().lower()
    triage_sender = _brief_context_sender(triage_item).lower()
    if item_contact and triage_sender and item_contact == triage_sender:
        return "contact"

    item_subject = str(item.get("source_subject", "")).strip().lower()
    triage_subject = _brief_context_subject(triage_item).lower()
    if item_subject and triage_subject and item_subject == triage_subject:
        return "subject"

    item_type = str(item.get("type", "")).strip().lower()
    triage_category = str(triage_item.get("category", "")).strip().lower()
    if item_type == "manual_review" and triage_category == "unknown":
        return "manual_review_pool"
    if item_type == "calendar_load" and triage_category == "calendar":
        return "calendar_pool"

    return None


def _match_brief_item_to_draft(item: dict[str, object], draft: dict[str, object]) -> str | None:
    item_message_id = str(item.get("source_message_id", "")).strip()
    draft_message_id = str(draft.get("message_id", "")).strip()
    if item_message_id and draft_message_id and item_message_id == draft_message_id:
        return "source_message"

    item_recipient = str(item.get("recipient", "")).strip().lower()
    recipients = _normalize_lowercase_string_list(draft.get("to_recipients", []))
    if item_recipient and item_recipient in recipients:
        return "recipient"

    item_subject = str(item.get("source_subject", "")).strip().lower()
    draft_subject = str(draft.get("subject", "")).strip().lower()
    if item_subject and draft_subject and item_subject in draft_subject:
        return "subject"

    if str(item.get("type", "")).strip().lower() == "reply_backlog":
        return "reply_backlog"

    return None


def _match_brief_item_to_event_draft(item: dict[str, object], event_draft: dict[str, object]) -> str | None:
    item_message_id = str(item.get("source_message_id", "")).strip()
    draft_message_id = str(event_draft.get("source_message_id", "")).strip()
    if item_message_id and draft_message_id and item_message_id == draft_message_id:
        return "source_message"

    item_subject = str(item.get("source_subject", "")).strip().lower()
    draft_subject = str(event_draft.get("source_subject", "")).strip().lower()
    if item_subject and draft_subject and item_subject == draft_subject:
        return "subject"

    item_contact = str(item.get("contact") or item.get("source_sender") or "").strip().lower()
    attendees = _normalize_lowercase_string_list(event_draft.get("attendees", []))
    if item_contact and item_contact in attendees:
        return "contact"

    if str(item.get("type", "")).strip().lower().startswith("calendar"):
        return "calendar_follow_up"

    return None


def _serialize_brief_context_message(triage_item: dict[str, object], *, matched_on: str) -> dict[str, object]:
    return {
        "message_id": _brief_context_message_id(triage_item),
        "thread_key": _brief_context_thread_key(triage_item),
        "subject": _brief_context_subject(triage_item),
        "sender": _brief_context_sender(triage_item),
        "received_at": _brief_context_received_at(triage_item),
        "saved_at": str(triage_item.get("saved_at", "")),
        "category": str(triage_item.get("category", "") or "unknown"),
        "urgency": triage_item.get("urgency"),
        "summary": str(triage_item.get("summary", "")).strip(),
        "matched_on": matched_on,
    }


def _serialize_brief_context_draft(draft: dict[str, object], *, matched_on: str) -> dict[str, object]:
    sent = bool(draft.get("sent"))
    approved = bool(draft.get("approved"))
    payload = {
        "draft_id": str(draft.get("draft_id", "")).strip(),
        "message_id": str(draft.get("message_id", "")).strip(),
        "subject": str(draft.get("subject", "")).strip(),
        "body": str(draft.get("body", "")).strip(),
        "tone": str(draft.get("tone", "")).strip(),
        "confidence": float(draft.get("confidence", 0.0) or 0.0),
        "needs_review": bool(draft.get("needs_review", True)),
        "approved": approved,
        "approved_at": str(draft.get("approved_at", "")).strip(),
        "approved_by": str(draft.get("approved_by", "")).strip(),
        "to_recipients": _normalize_email_addresses(draft.get("to_recipients", [])),
        "cc_recipients": _normalize_email_addresses(draft.get("cc_recipients", [])),
        "sent": sent,
        "saved_at": str(draft.get("saved_at", "")).strip(),
        "sent_at": str(draft.get("sent_at", "")).strip(),
        "sent_by": str(draft.get("sent_by", "")).strip(),
        "delivery_mode": str(draft.get("delivery_mode", "")).strip(),
        "last_send_attempt_at": str(draft.get("last_send_attempt_at", "")).strip(),
        "last_send_attempted_by": str(draft.get("last_send_attempted_by", "")).strip(),
        "send_block_reason": str(draft.get("send_block_reason", "")).strip(),
        "approval_note": str(draft.get("approval_note", "")).strip(),
        "status": str(
            draft.get("status")
            or ("sent" if sent else "approved" if approved else "draft")
        ).strip(),
        "matched_on": matched_on,
    }
    payload["available_actions"] = _build_draft_actions(payload)
    return payload


def _build_draft_actions(draft: dict[str, object]) -> list[dict[str, str]]:
    if bool(draft.get("sent")):
        return []
    actions: list[dict[str, str]] = []
    if not bool(draft.get("approved")):
        actions.append({"action": "approve", "label": "Approve draft"})
    else:
        actions.append({"action": "send", "label": "Send draft"})
        actions.append({"action": "unapprove", "label": "Mark unapproved"})
    return actions


def _serialize_brief_context_event_draft(event_draft: dict[str, object], *, matched_on: str) -> dict[str, object]:
    payload = {
        "event_draft_id": str(event_draft.get("event_draft_id", "")).strip(),
        "source_message_id": str(event_draft.get("source_message_id", "")).strip(),
        "source_subject": str(event_draft.get("source_subject", "")).strip(),
        "thread_key": str(event_draft.get("thread_key", "")).strip(),
        "title": str(event_draft.get("title", "")).strip(),
        "attendees": _normalize_email_addresses(event_draft.get("attendees", [])),
        "candidate_time_phrases": _normalize_string_list(event_draft.get("candidate_time_phrases", [])),
        "meeting_format": str(event_draft.get("meeting_format", "")).strip(),
        "duration_minutes": int(event_draft.get("duration_minutes", 0) or 0),
        "location_hint": str(event_draft.get("location_hint", "")).strip(),
        "summary": str(event_draft.get("summary", "")).strip(),
        "description": str(event_draft.get("description", "")).strip(),
        "suggested_action": str(event_draft.get("suggested_action", "")).strip(),
        "review_notes": _normalize_review_notes(event_draft.get("review_notes", "")),
        "needs_review": bool(event_draft.get("needs_review", True)),
        "confidence": float(event_draft.get("confidence", 0.0) or 0.0),
        "approved": bool(event_draft.get("approved")),
        "approved_by": str(event_draft.get("approved_by", "")).strip(),
        "status": str(event_draft.get("status", "")).strip() or "draft",
        "created_event": bool(event_draft.get("created_event")),
        "created_event_at": str(event_draft.get("created_event_at", "")).strip(),
        "created_event_by": str(event_draft.get("created_event_by", "")).strip(),
        "created_event_id": str(event_draft.get("created_event_id", "")).strip(),
        "created_event_web_link": str(event_draft.get("created_event_web_link", "")).strip(),
        "scheduled_start_at": str(event_draft.get("scheduled_start_at", "")).strip(),
        "scheduled_end_at": str(event_draft.get("scheduled_end_at", "")).strip(),
        "saved_at": str(event_draft.get("saved_at", "")).strip(),
        "approved_at": str(event_draft.get("approved_at", "")).strip(),
        "matched_on": matched_on,
    }
    payload["available_actions"] = _build_event_draft_actions(payload)
    return payload


def _normalize_review_notes(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return " | ".join(str(item).strip() for item in value if str(item).strip())
    if value is None:
        return ""
    return str(value).strip()


def _build_event_draft_actions(event_draft: dict[str, object]) -> list[dict[str, str]]:
    if bool(event_draft.get("created_event")):
        return []
    actions: list[dict[str, str]] = []
    if not bool(event_draft.get("approved")):
        actions.append({"action": "approve", "label": "Approve draft"})
    if bool(event_draft.get("approved")):
        actions.append({"action": "create_event", "label": "Create event"})
        actions.append({"action": "unapprove", "label": "Mark unapproved"})
    return actions


def _resolve_event_draft_schedule(
    event_draft: dict[str, object],
    body: dict[str, object],
) -> dict[str, str] | None:
    start_text = str(body.get("start_at", "")).strip()
    end_text = str(body.get("end_at", "")).strip()

    start_dt = _parse_iso_datetime(start_text) if start_text else None
    end_dt = _parse_iso_datetime(end_text) if end_text else None

    if start_dt is None:
        candidate_times = _normalize_string_list(event_draft.get("candidate_time_phrases", []))
        if candidate_times:
            start_dt = _parse_event_candidate_time(candidate_times[0])

    if start_dt is None:
        return None

    if end_dt is None:
        duration_minutes = int(event_draft.get("duration_minutes", 30) or 30)
        end_dt = start_dt + timedelta(minutes=max(duration_minutes, 15))

    return {
        "start_at": start_dt.isoformat(),
        "end_at": end_dt.isoformat(),
    }


def _parse_event_candidate_time(value: str) -> datetime | None:
    candidate = (value or "").strip()
    if not candidate:
        return None

    direct = _parse_iso_datetime(candidate)
    if direct is not None:
        return direct

    now = datetime.now(timezone.utc)
    lower = candidate.lower()
    weekday_map = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", lower)
    weekday_match = re.search(r"(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", lower)

    if weekday_match and time_match:
        target_weekday = weekday_map[weekday_match.group(2)]
        days_ahead = (target_weekday - now.weekday()) % 7
        if days_ahead == 0 or weekday_match.group(1):
            days_ahead = 7 if days_ahead == 0 else days_ahead
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        meridiem = time_match.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        target_date = (now + timedelta(days=days_ahead)).date()
        return datetime.combine(target_date, time(hour=hour, minute=minute), timezone.utc)

    return None


def _brief_context_message_id(triage_item: dict[str, object]) -> str:
    email = triage_item.get("email", {})
    if isinstance(email, dict) and email.get("message_id"):
        return str(email.get("message_id", "")).strip()
    return str(triage_item.get("message_id", "")).strip()


def _brief_context_thread_key(triage_item: dict[str, object]) -> str:
    email = triage_item.get("email", {})
    if isinstance(email, dict) and email.get("conversation_id"):
        return str(email.get("conversation_id", "")).strip()
    return str(triage_item.get("conversation_id", "")).strip()


def _brief_context_subject(triage_item: dict[str, object]) -> str:
    email = triage_item.get("email", {})
    if isinstance(email, dict) and email.get("subject"):
        return str(email.get("subject", "")).strip()
    return str(triage_item.get("email_subject", "")).strip()


def _brief_context_sender(triage_item: dict[str, object]) -> str:
    email = triage_item.get("email", {})
    if isinstance(email, dict) and email.get("sender"):
        return str(email.get("sender", "")).strip()
    return str(triage_item.get("email_sender", "")).strip()


def _brief_context_received_at(triage_item: dict[str, object]) -> str:
    email = triage_item.get("email", {})
    if isinstance(email, dict) and email.get("received_at"):
        return str(email.get("received_at", "")).strip()
    return str(triage_item.get("saved_at", "")).strip()


def _normalize_email_addresses(values: object) -> list[str]:
    return _normalize_string_list(values)


def _normalize_string_list(values: object) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []

    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _normalize_lowercase_string_list(values: object) -> list[str]:
    return [value.lower() for value in _normalize_string_list(values)]


def _split_setting_list(raw: str) -> list[str]:
    if not raw:
        return []
    return _normalize_string_list([part.strip() for part in raw.split(",")])


def _get_outbound_email_mode(override: object = None) -> str:
    if override is None:
        raw_mode = _get_str_setting("OUTBOUND_EMAIL_MODE", DEFAULT_OUTBOUND_EMAIL_MODE)
    else:
        raw_mode = str(override).strip() or DEFAULT_OUTBOUND_EMAIL_MODE

    normalized = raw_mode.lower()
    if normalized in {"enabled", "live", "send"}:
        return "send"
    if normalized in {"off", "disabled", "disable"}:
        return "disabled"
    return "dry_run"


def _extract_domain(address: str) -> str:
    if "@" not in address:
        return ""
    return address.rsplit("@", 1)[-1].strip().lower()


def _evaluate_outbound_recipients(recipients: list[str]) -> tuple[bool, str]:
    normalized_recipients = _normalize_lowercase_string_list(recipients)
    if not normalized_recipients:
        return False, "No outbound recipients were provided"

    blocked_recipients = set(
        _normalize_lowercase_string_list(
            _split_setting_list(_get_str_setting("OUTBOUND_EMAIL_BLOCKED_RECIPIENTS", ""))
        )
    )
    blocked_domains = set(
        _normalize_lowercase_string_list(
            _split_setting_list(_get_str_setting("OUTBOUND_EMAIL_BLOCKED_DOMAINS", ""))
        )
    )
    allowed_recipients = set(
        _normalize_lowercase_string_list(
            _split_setting_list(_get_str_setting("OUTBOUND_EMAIL_ALLOWED_RECIPIENTS", ""))
        )
    )
    allowed_domains = set(
        _normalize_lowercase_string_list(
            _split_setting_list(_get_str_setting("OUTBOUND_EMAIL_ALLOWED_DOMAINS", ""))
        )
    )

    for recipient in normalized_recipients:
        domain = _extract_domain(recipient)
        if recipient in blocked_recipients:
            return False, f"Recipient {recipient} is blocked by outbound email policy"
        if domain and domain in blocked_domains:
            return False, f"Domain {domain} is blocked by outbound email policy"

    if allowed_recipients or allowed_domains:
        for recipient in normalized_recipients:
            domain = _extract_domain(recipient)
            if recipient in allowed_recipients:
                continue
            if domain and domain in allowed_domains:
                continue
            return False, f"Recipient {recipient} is not allowed by outbound email policy"

    return True, ""


def _extract_graph_addresses(recipients: object) -> list[str]:
    if not isinstance(recipients, list):
        return []

    addresses: list[str] = []
    for recipient in recipients:
        if not isinstance(recipient, dict):
            continue
        email_address = recipient.get("emailAddress", {})
        if not isinstance(email_address, dict):
            continue
        address = str(email_address.get("address", "")).strip()
        if address and address not in addresses:
            addresses.append(address)
    return addresses


def _resolve_reply_recipients(message: dict[str, object]) -> list[str]:
    if not isinstance(message, dict):
        return []

    reply_to = _extract_graph_addresses(message.get("replyTo"))
    if reply_to:
        return reply_to

    sender = message.get("from", {})
    if isinstance(sender, dict):
        return _extract_graph_addresses([sender])

    return []


def _get_existing_draft(store, draft_id: str, message_id: str = "") -> dict[str, object] | None:
    if message_id:
        draft = store.get_draft(draft_id, message_id)
        if draft:
            return draft
    finder = getattr(store, "find_draft_by_id", None)
    if callable(finder):
        return finder(draft_id)
    return None


def _get_existing_event_draft(store, event_draft_id: str, source_message_id: str = "") -> dict[str, object] | None:
    if source_message_id and hasattr(store, "get_event_draft"):
        draft = store.get_event_draft(event_draft_id, source_message_id)
        if draft:
            return draft
    finder = getattr(store, "find_event_draft_by_id", None)
    if callable(finder):
        return finder(event_draft_id)
    return None


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


def _stage_attachment_in_pillar3(
    email: EmailMessage,
    attachment,
) -> dict[str, object]:
    routes = route_attachments([attachment.attachment.name])
    route = routes[0] if routes else None
    if route is None or route.target_pillar != "pillar3":
        return {
            "attempted": False,
            "dispatched": False,
            "reason": "not_routed_to_pillar3",
        }

    client = get_document_ai_client()
    if not client.is_available:
        return {
            "attempted": False,
            "dispatched": False,
            "reason": "pillar3_not_configured",
        }

    payload = {
        "document_id": (
            attachment.attachment.attachment_id
            or f"{email.message_id}:{attachment.attachment.name}"
        ),
        "filename": attachment.attachment.name,
        "source": "email",
        "source_detail": email.message_id or email.subject,
        "message_id": email.message_id,
        "attachment_id": attachment.attachment.attachment_id,
        "sender": email.sender,
        "thread_key": email.conversation_id,
        "content_type": attachment.attachment.content_type,
        "file_size_bytes": len(attachment.attachment.content_bytes or b""),
        "file_bytes_base64": base64.b64encode(
            attachment.attachment.content_bytes or b""
        ).decode("utf-8"),
        "classification": serialize_classification_result(attachment.classification),
        "filing": serialize_filing_recommendation(attachment.filing),
        "extraction": attachment.extraction_summary,
        "source_metadata": {
            "email_subject": email.subject,
            "sender_name": email.sender_name,
            "sharepoint_disposition": str(
                attachment.sharepoint_target.get("disposition", "")
            ),
            "sharepoint_target_path": str(
                attachment.sharepoint_target.get("full_path", "")
            ),
        },
    }

    try:
        response = client.stage_document(payload)
        document = response.get("document", {}) if isinstance(response, dict) else {}
        return {
            "attempted": True,
            "dispatched": bool(response.get("success", False)) if isinstance(response, dict) else False,
            "reason": "" if isinstance(response, dict) and response.get("success", False) else "pillar3_empty_response",
            "document_id": str(document.get("document_id", payload["document_id"])),
            "status": str(document.get("status", "")),
        }
    except Exception as exc:
        logger.warning(
            "Pillar 3 staging failed for %s/%s: %s",
            email.message_id,
            attachment.attachment.name,
            exc,
        )
        return {
            "attempted": True,
            "dispatched": False,
            "reason": "pillar3_stage_failed",
            "warning": f"pillar3_stage_failed:{attachment.attachment.name}: {exc}",
        }


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
        warnings = list(item.warnings)
        triage_data = serialize_triage_result(item.triage)
        triage_data["email"] = serialize_email(item.email)
        triage_data["email_subject"] = item.email.subject
        triage_data["email_sender"] = item.email.sender
        triage_data["email_sender_name"] = item.email.sender_name
        triage_data["email_recipients"] = item.email.recipients
        triage_data["received_at"] = item.email.received_at.isoformat()
        triage_data["conversation_id"] = item.email.conversation_id
        try:
            data_store.save_triage_result(triage_data)
        except Exception as exc:
            logger.warning(
                "Failed to persist triage result for %s: %s",
                item.email.message_id,
                exc,
            )
            warnings.append(f"triage_persist_failed: {exc}")

        attachment_items: list[dict[str, object]] = []
        for attachment in item.attachments:
            pillar3_stage_result = _stage_attachment_in_pillar3(item.email, attachment)
            warning = pillar3_stage_result.get("warning")
            if isinstance(warning, str) and warning:
                warnings.append(warning)
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
                    "pillar3_stage": pillar3_stage_result,
                }
            )
            try:
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
                        "pillar3_stage": pillar3_stage_result,
                    }
                )
            except Exception as exc:
                logger.warning(
                    "Failed to persist document %s for %s: %s",
                    attachment.attachment.name,
                    item.email.message_id,
                    exc,
                )
                warnings.append(
                    f"document_persist_failed:{attachment.attachment.name}: {exc}"
                )

        response_items.append(
            {
                "email": serialize_email(item.email),
                "triage": serialize_triage_result(item.triage),
                "attachments": attachment_items,
                "ai_used": item.ai_used,
                "marked_processed": item.marked_processed,
                "warnings": warnings,
            }
        )

    return response_items


def _summarize_mailbox_ingestion(items: list[dict[str, object]]) -> dict[str, int]:
    attachments: list[dict[str, object]] = []
    warnings_count = 0
    messages_marked_processed = 0

    for item in items:
        attachments.extend(item.get("attachments", []))
        warnings_count += len(item.get("warnings", []))
        if item.get("marked_processed"):
            messages_marked_processed += 1

    return {
        "processed_messages": len(items),
        "messages_marked_processed": messages_marked_processed,
        "warnings_count": warnings_count,
        "attachments_processed": len(attachments),
        "attachments_uploaded": sum(
            1
            for attachment in attachments
            if attachment.get("upload", {}).get("uploaded")
        ),
        "attachments_filed": sum(
            1
            for attachment in attachments
            if attachment.get("sharepoint_target", {}).get("disposition") == "filed"
        ),
        "attachments_staged_for_review": sum(
            1
            for attachment in attachments
            if attachment.get("sharepoint_target", {}).get("disposition")
            == "staged_for_review"
        ),
        "attachments_unsupported": sum(
            1
            for attachment in attachments
            if attachment.get("sharepoint_target", {}).get("disposition") == "unsupported"
        ),
        "attachments_upload_failures": sum(
            1
            for attachment in attachments
            if attachment.get("upload", {}).get("reason") == "sharepoint_upload_failed"
        ),
    }
