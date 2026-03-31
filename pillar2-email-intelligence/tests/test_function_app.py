"""Tests for pure helper logic in the email intelligence function app."""

from __future__ import annotations

import base64
import json

import pytest

from email_intel.attachment_processing import ProcessedAttachment
from email_intel.cosmos_client import CosmosDataStore
from email_intel.document_models import (
    ClassificationConfidence,
    ClassificationResult,
    DocumentType,
    FilingRecommendation,
)
from email_intel.graph_client import GraphRequestError
from email_intel.ingestion_service import ProcessedEmail
from email_intel.mailbox_ingestion import MailAttachment
from email_intel.models import EmailCategory, EmailMessage, TriageResult, UrgencyTier
from function_app import (
    _decode_file_bytes,
    _extract_document_text,
    _evaluate_outbound_recipients,
    _get_outbound_email_mode,
    _normalize_email_addresses,
    _normalize_lowercase_string_list,
    _normalize_string_list,
    _persist_with_warning,
    _resolve_reply_recipients,
    act_on_brief_item,
    apply_mailbox_action,
    brief_review_page,
    calendar_assist,
    morning_brief,
    _run_mailbox_ingestion,
    _summarize_mailbox_ingestion,
    classify_doc,
    correct_classification,
    growth_nudges,
    draft_reply,
    get_brief_item_context,
    create_event_from_draft,
    get_event_drafts,
    ingest_mailbox,
    list_brief_items,
    poll_mailbox,
    send_draft,
    triage,
    update_event_draft,
    update_brief_item_state,
    update_draft,
)


class FakeDocClient:
    def __init__(self, *, available: bool = True, text: str = "Extracted text") -> None:
        self.is_available = available
        self._text = text

    def extract_invoice(self, file_bytes: bytes):
        return type(
            "Extraction",
            (),
            {"text": self._text, "page_count": 1, "confidence": 0.91},
        )()

    def extract_receipt(self, file_bytes: bytes):
        return type(
            "Extraction",
            (),
            {"text": self._text, "page_count": 1, "confidence": 0.89},
        )()

    def extract_text(self, file_bytes: bytes, content_type: str = "application/pdf"):
        return type(
            "Extraction",
            (),
            {"text": self._text, "page_count": 2, "confidence": 0.75},
        )()


class FakeRequest:
    def __init__(self, body: dict | None = None) -> None:
        self._body = body
        self.params = {}
        self.route_params = {}

    def get_json(self):
        if self._body is None:
            raise ValueError("No JSON body")
        return self._body


class FakeMailboxIngestionService:
    def __init__(self, *, available: bool = True) -> None:
        self.is_available = available
        self.last_top: int | None = None
        self.last_mark_processed: bool | None = None

    def process_unread_messages(self, *, top: int = 25, mark_processed: bool = False):
        self.last_top = top
        self.last_mark_processed = mark_processed
        return [
            ProcessedEmail(
                email=EmailMessage(
                    message_id="msg-1",
                    subject="Invoice #123",
                    sender="billing@vendor.com",
                    sender_name="Vendor Billing",
                    recipients=["kmcquire@peak10energy.com"],
                    has_attachments=True,
                    attachment_names=["Invoice_123.pdf"],
                ),
                triage=TriageResult(
                    message_id="msg-1",
                    category=EmailCategory.VENDOR_AP,
                    urgency=UrgencyTier.STANDARD,
                    confidence=0.91,
                ),
                attachments=[
                    ProcessedAttachment(
                        attachment=MailAttachment(
                            attachment_id="att-1",
                            name="Invoice_123.pdf",
                            content_type="application/pdf",
                            content_bytes=b"pdf-bytes",
                        ),
                        classification=ClassificationResult(
                            document_type=DocumentType.INVOICE,
                            confidence=0.90,
                            confidence_level=ClassificationConfidence.HIGH,
                        ),
                        filing=FilingRecommendation(
                            recommended_path="01_CORPORATE/Finance/AP",
                            standardized_name="2026-03-21_Invoice_Test.pdf",
                            document_type=DocumentType.INVOICE,
                            confidence_level=ClassificationConfidence.HIGH,
                            requires_review=False,
                        ),
                        extraction_text="Invoice Number: 123",
                        extraction_summary={
                            "used_document_intelligence": False,
                            "mode": "invoice",
                            "content_type": "application/pdf",
                            "page_count": 0,
                            "confidence": 0.0,
                            "text_length": 19,
                        },
                        sharepoint_target={
                            "disposition": "filed",
                            "folder_path": "01_CORPORATE/Finance/AP",
                            "filename": "2026-03-21_Invoice_Test.pdf",
                            "full_path": "01_CORPORATE/Finance/AP/2026-03-21_Invoice_Test.pdf",
                            "reason": "governed_filing",
                        },
                        upload_result={
                            "attempted": False,
                            "uploaded": False,
                            "backend": "offline",
                            "reason": "sharepoint_unavailable",
                        },
                    )
                ],
                ai_used=False,
                marked_processed=mark_processed,
                warnings=["attachment_fetch_failed: attachments endpoint failed"],
            )
        ]


class FakePillar3MailboxIngestionService(FakeMailboxIngestionService):
    def process_unread_messages(self, *, top: int = 25, mark_processed: bool = False):
        self.last_top = top
        self.last_mark_processed = mark_processed
        return [
            ProcessedEmail(
                email=EmailMessage(
                    message_id="msg-legal-1",
                    subject="MSA draft for review",
                    sender="legal@drillco.com",
                    sender_name="DrillCo Legal",
                    recipients=["kmcquire@peak10energy.com"],
                    conversation_id="thread-legal-1",
                    has_attachments=True,
                    attachment_names=["MSA_DrillCo.pdf"],
                ),
                triage=TriageResult(
                    message_id="msg-legal-1",
                    category=EmailCategory.LEGAL,
                    urgency=UrgencyTier.HIGH,
                    confidence=0.93,
                ),
                attachments=[
                    ProcessedAttachment(
                        attachment=MailAttachment(
                            attachment_id="att-legal-1",
                            name="MSA_DrillCo.pdf",
                            content_type="application/pdf",
                            content_bytes=b"msa-bytes",
                        ),
                        classification=ClassificationResult(
                            document_type=DocumentType.CONTRACT,
                            confidence=0.94,
                            confidence_level=ClassificationConfidence.HIGH,
                        ),
                        filing=FilingRecommendation(
                            recommended_path="01_CORPORATE/Legal/Contracts",
                            standardized_name="2026-03-21_Contract_DrillCo.pdf",
                            document_type=DocumentType.CONTRACT,
                            confidence_level=ClassificationConfidence.HIGH,
                            requires_review=False,
                        ),
                        extraction_text="Master services agreement",
                        extraction_summary={
                            "used_document_intelligence": False,
                            "mode": "text",
                            "content_type": "application/pdf",
                            "page_count": 3,
                            "confidence": 0.0,
                            "text_length": 25,
                        },
                        sharepoint_target={
                            "disposition": "filed",
                            "folder_path": "01_CORPORATE/Legal/Contracts",
                            "filename": "2026-03-21_Contract_DrillCo.pdf",
                            "full_path": "01_CORPORATE/Legal/Contracts/2026-03-21_Contract_DrillCo.pdf",
                            "reason": "governed_filing",
                        },
                        upload_result={
                            "attempted": False,
                            "uploaded": False,
                            "backend": "offline",
                            "reason": "sharepoint_unavailable",
                        },
                    )
                ],
                ai_used=False,
                marked_processed=mark_processed,
                warnings=[],
            )
        ]


class FakeDocumentAiClient:
    def __init__(self, *, available: bool = True, raise_error: Exception | None = None) -> None:
        self.is_available = available
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def stage_document(self, payload: dict) -> dict:
        self.calls.append(payload)
        if self.raise_error is not None:
            raise self.raise_error
        return {
            "success": True,
            "document": {
                "document_id": payload.get("document_id", ""),
                "status": "classified",
            },
        }


class FakeTimerRequest:
    def __init__(self, *, past_due: bool = False) -> None:
        self.past_due = past_due


class FailingMailboxStore:
    is_connected = False
    storage_backend = "in_memory"

    def __init__(self) -> None:
        self.saved_triage = 0
        self.saved_documents = 0

    def save_triage_result(self, triage_data: dict) -> dict:
        self.saved_triage += 1
        raise RuntimeError("triage store offline")

    def save_document(self, doc_data: dict) -> dict:
        self.saved_documents += 1
        raise RuntimeError("document store offline")

    def count_triage_results(self) -> int:
        return 0

    def count_documents(self) -> int:
        return 0

    def count_drafts(self) -> int:
        return 0

    def count_event_drafts(self) -> int:
        return 0

    def count_corrections(self) -> int:
        return 0


class FailingEndpointStore(FailingMailboxStore):
    def save_draft(self, draft_data: dict) -> dict:
        raise RuntimeError("draft store offline")

    def get_draft(self, draft_id: str, message_id: str):
        return {
            "draft_id": draft_id,
            "message_id": message_id,
            "subject": "Re: Test",
            "body": "Original",
            "tone": "professional",
            "approved": False,
        }

    def save_correction(self, correction_data: dict) -> dict:
        raise RuntimeError("correction store offline")

    def save_event_draft(self, draft_data: dict) -> dict:
        raise RuntimeError("event draft store offline")

    def get_event_draft(self, event_draft_id: str, source_message_id: str):
        return {
            "event_draft_id": event_draft_id,
            "source_message_id": source_message_id,
            "title": "Follow-up call",
            "approved": False,
        }

    def query_triage_results(self, partition_date=None, limit: int = 50):
        return []


class FakeDraftGraphClient:
    def __init__(
        self,
        *,
        message: dict | None = None,
        send_error: Exception | None = None,
    ) -> None:
        self.is_available = True
        self.mailbox_available = True
        self.sharepoint_available = True
        self.message = message if message is not None else {
            "from": {"emailAddress": {"address": "sender@example.com"}},
            "replyTo": [],
        }
        self.send_error = send_error
        self.sent_messages: list[dict] = []

    def get_message(self, message_id: str, *, select_fields=None):
        return self.message

    def send_mail(
        self,
        *,
        to_recipients: list[str],
        subject: str,
        body: str,
        cc_recipients: list[str] | None = None,
        content_type: str = "Text",
    ):
        if self.send_error:
            raise self.send_error
        self.sent_messages.append(
            {
                "to_recipients": to_recipients,
                "cc_recipients": cc_recipients or [],
                "subject": subject,
                "body": body,
                "content_type": content_type,
            }
        )
        return {}


class FakeMailboxActionGraphClient:
    def __init__(
        self,
        *,
        update_error: Exception | None = None,
        move_error: Exception | None = None,
        create_event_error: Exception | None = None,
    ) -> None:
        self.is_available = True
        self.mailbox_available = True
        self.sharepoint_available = True
        self.updated_messages: list[tuple[str, dict]] = []
        self.moved_messages: list[tuple[str, str]] = []
        self.created_events: list[dict] = []
        self.update_error = update_error
        self.move_error = move_error
        self.create_event_error = create_event_error
        self.message = {
            "id": "msg-1",
            "subject": "Can we meet next Tuesday at 2 pm?",
            "bodyPreview": "Would next Tuesday at 2 pm work for a quick Zoom?",
            "body": {"content": "Would next Tuesday at 2 pm work for a quick Zoom?"},
            "from": {"emailAddress": {"address": "counterparty@example.com", "name": "Counterparty"}},
            "replyTo": [],
            "toRecipients": [{"emailAddress": {"address": "automation@peak10.test"}}],
            "ccRecipients": [],
            "receivedDateTime": "2026-03-25T08:00:00+00:00",
            "hasAttachments": False,
            "conversationId": "conv-1",
        }

    def update_message(self, message_id: str, updates: dict):
        self.updated_messages.append((message_id, updates))
        if self.update_error:
            raise self.update_error
        return {"id": message_id, **updates}

    def move_message(self, message_id: str, destination_id: str):
        self.moved_messages.append((message_id, destination_id))
        if self.move_error:
            raise self.move_error
        return {"id": f"moved-{message_id}", "parentFolderId": destination_id}

    def get_message(self, message_id: str, *, select_fields=None):
        return dict(self.message)

    def create_calendar_event(
        self,
        *,
        subject: str,
        body: str,
        attendees: list[str],
        start_iso: str,
        end_iso: str,
        location_display_name: str = "",
        timezone_name: str = "UTC",
    ):
        if self.create_event_error:
            raise self.create_event_error
        payload = {
            "subject": subject,
            "body": body,
            "attendees": attendees,
            "start_iso": start_iso,
            "end_iso": end_iso,
            "location_display_name": location_display_name,
            "timezone_name": timezone_name,
        }
        self.created_events.append(payload)
        return {"id": "event-123", "webLink": "https://example.com/event-123"}


class FakeCalendarOpenAIClient:
    def __init__(self, response: dict | None = None) -> None:
        self.is_available = True
        self.response = response or {
            "is_calendar_related": True,
            "meeting_request_type": "new_request",
            "suggested_action": "confirm_time",
            "summary": "The sender is asking to meet next Tuesday at 2 pm.",
            "proposed_time_phrases": ["next Tuesday at 2 pm"],
            "attendees_to_consider": ["counterparty@example.com"],
            "draft_reply": {
                "subject": "Re: Meeting request",
                "body": "Next Tuesday at 2 pm could work. Please send the invite.",
            },
            "confidence": 0.91,
            "reasoning": "Explicit time and meeting language were present.",
        }

    def assist_calendar_request(self, prompt: str):
        return self.response


class FakeInsightStore:
    def query_triage_results(self, partition_date=None, limit: int = 50):
        return self.query_triage_activity(limit=limit)

    def query_triage_activity(self, *, days: int = 90, limit: int = 50):
        return [
            {
                "message_id": "msg-1",
                "category": "deal_related",
                "urgency": 2,
                "email_subject": "Asset package intro",
                "email_sender": "contact@example.com",
                "saved_at": "2026-01-01T12:00:00+00:00",
                "summary": "Initial package outreach.",
            },
            {
                "message_id": "msg-2",
                "category": "deal_related",
                "urgency": 3,
                "email_subject": "Timing may delay this",
                "email_sender": "contact@example.com",
                "saved_at": "2026-01-15T12:00:00+00:00",
                "summary": "There may be a delay because of budget pressure.",
            },
            {
                "message_id": "msg-3",
                "category": "calendar",
                "urgency": 3,
                "email_subject": "Can we meet next week?",
                "email_sender": "contact@example.com",
                "saved_at": "2026-02-01T12:00:00+00:00",
                "summary": "Request to schedule time next week.",
            },
            {
                "message_id": "msg-4",
                "category": "unknown",
                "urgency": 3,
                "email_subject": "Could be interested",
                "email_sender": "third@example.com",
                "saved_at": "2026-03-21T12:00:00+00:00",
                "summary": "They might be interested in an intro.",
            },
            {
                "message_id": "msg-5",
                "category": "unknown",
                "urgency": 3,
                "email_subject": "Need to delay this",
                "email_sender": "other@example.com",
                "saved_at": "2026-03-20T12:00:00+00:00",
                "summary": "We may need to delay.",
            },
        ][:limit]

    def query_drafts(self, *, limit: int = 200, sent_only: bool = False):
        drafts = [
            {
                "draft_id": "draft-1",
                "subject": "Re: Asset package intro",
                "to_recipients": ["contact@example.com"],
                "sent": True,
                "sent_at": "2026-03-10T12:00:00+00:00",
            },
            {
                "draft_id": "draft-2",
                "subject": "Re: Another thread",
                "to_recipients": ["someone@example.com"],
                "sent": False,
            },
        ]
        if sent_only:
            drafts = [draft for draft in drafts if draft.get("sent")]
        return drafts[:limit]

    def count_drafts(self) -> int:
        return 2

    def count_documents(self) -> int:
        return 3


class FakeMorningBriefStore(FakeInsightStore):
    def __init__(self) -> None:
        self._brief_items: dict[str, dict] = {
            "carry-1": {
                "id": "carry-1",
                "item_id": "carry-1",
                "item_kind": "follow_up",
                "type": "awaiting_response",
                "title": "Check in with silent buyer",
                "message": "No reply yet from silent@example.com.",
                "suggested_action": "Send a quick nudge.",
                "priority": "high",
                "state": "open",
                "first_seen_at": "2026-03-22T08:00:00+00:00",
                "last_seen_at": "2026-03-24T08:00:00+00:00",
            }
        }
        self._drafts: dict[str, dict] = {
            "draft-1": {
                "draft_id": "draft-1",
                "message_id": "msg-1",
                "subject": "Re: Waiting on next steps",
                "body": "I can follow up with a narrower next step if that helps.",
                "tone": "professional",
                "to_recipients": ["silent@example.com"],
                "approved": True,
                "needs_review": False,
                "sent": False,
                "saved_at": "2026-03-20T12:00:00+00:00",
            }
        }
        self._event_drafts: dict[str, dict] = {
            "event-1": {
                "event_draft_id": "event-1",
                "source_message_id": "msg-5",
                "source_subject": "Can we meet next week?",
                "title": "Can we meet next week?",
                "attendees": ["regular@example.com"],
                "candidate_time_phrases": ["next week"],
                "meeting_format": "unspecified",
                "duration_minutes": 15,
                "location_hint": "Zoom",
                "review_notes": "Needs confirmation on exact date.",
                "needs_review": True,
                "approved": False,
                "status": "draft",
                "created_event": False,
                "saved_at": "2026-03-21T12:00:00+00:00",
            }
        }

    def query_triage_activity(self, *, days: int = 90, limit: int = 50):
        return [
            {
                "message_id": "msg-1",
                "conversation_id": "conv-1",
                "category": "deal_related",
                "urgency": 2,
                "email_subject": "Lease diligence follow-up",
                "email_sender": "owner@example.com",
                "saved_at": "2026-03-24T14:00:00+00:00",
                "summary": "We may need to delay diligence because of budget pressure.",
            },
            {
                "message_id": "msg-2",
                "conversation_id": "conv-1",
                "category": "deal_related",
                "urgency": 2,
                "email_subject": "Re: Lease diligence follow-up",
                "email_sender": "owner@example.com",
                "saved_at": "2026-03-25T13:00:00+00:00",
                "summary": "Still waiting on a decision from their side.",
            },
            {
                "message_id": "msg-3",
                "category": "deal_related",
                "urgency": 3,
                "email_subject": "Intro call",
                "email_sender": "regular@example.com",
                "saved_at": "2026-01-01T12:00:00+00:00",
                "summary": "Initial outreach.",
            },
            {
                "message_id": "msg-4",
                "category": "deal_related",
                "urgency": 3,
                "email_subject": "Timing update",
                "email_sender": "regular@example.com",
                "saved_at": "2026-01-15T12:00:00+00:00",
                "summary": "Could be interested in moving forward.",
            },
            {
                "message_id": "msg-5",
                "category": "calendar",
                "urgency": 3,
                "email_subject": "Can we meet next week?",
                "email_sender": "regular@example.com",
                "saved_at": "2026-02-01T12:00:00+00:00",
                "summary": "Can we meet next week?",
            },
        ][:limit]

    def query_drafts(self, *, limit: int = 200, sent_only: bool = False):
        drafts = [dict(draft) for draft in self._drafts.values()]
        if sent_only:
            return [draft for draft in drafts if draft.get("sent")][:limit]
        return drafts[:limit]

    def query_event_drafts(self, *, limit: int = 200, approved_only: bool = False):
        drafts = list(self._event_drafts.values())
        if approved_only:
            drafts = [draft for draft in drafts if draft.get("approved")]
        return drafts[:limit]

    def query_brief_items(
        self,
        *,
        states: list[str] | None = None,
        item_kinds: list[str] | None = None,
        since_days: int = 14,
        limit: int = 200,
    ):
        items = list(self._brief_items.values())
        if states:
            allowed_states = {state.lower() for state in states}
            items = [item for item in items if str(item.get("state", "open")).lower() in allowed_states]
        if item_kinds:
            allowed_kinds = set(item_kinds)
            items = [item for item in items if item.get("item_kind") in allowed_kinds]
        return items[:limit]

    def save_brief_item(self, item_data: dict):
        self._brief_items[item_data["item_id"]] = dict(item_data)
        return self._brief_items[item_data["item_id"]]

    def find_brief_item_by_id(self, item_id: str):
        return self._brief_items.get(item_id)

    def count_brief_items(self) -> int:
        return len(self._brief_items)

    def save_draft(self, draft_data: dict):
        self._drafts[draft_data["draft_id"]] = dict(draft_data)
        return dict(self._drafts[draft_data["draft_id"]])

    def get_drafts_for_message(self, message_id: str):
        return [
            dict(draft)
            for draft in self._drafts.values()
            if draft.get("message_id") == message_id
        ]

    def get_draft(self, draft_id: str, message_id: str):
        draft = self._drafts.get(draft_id)
        if draft and draft.get("message_id") == message_id:
            return dict(draft)
        return None

    def find_draft_by_id(self, draft_id: str):
        draft = self._drafts.get(draft_id)
        return dict(draft) if draft else None

    def save_event_draft(self, draft_data: dict):
        self._event_drafts[draft_data["event_draft_id"]] = dict(draft_data)
        return self._event_drafts[draft_data["event_draft_id"]]

    def get_event_drafts_for_message(self, message_id: str):
        return [
            dict(draft)
            for draft in self._event_drafts.values()
            if draft.get("source_message_id") == message_id
        ]

    def get_event_draft(self, event_draft_id: str, source_message_id: str):
        draft = self._event_drafts.get(event_draft_id)
        if draft and draft.get("source_message_id") == source_message_id:
            return dict(draft)
        return None

    def find_event_draft_by_id(self, event_draft_id: str):
        draft = self._event_drafts.get(event_draft_id)
        return dict(draft) if draft else None

    def delete_event_draft(self, event_draft_id: str, source_message_id: str):
        draft = self._event_drafts.get(event_draft_id)
        if draft and draft.get("source_message_id") == source_message_id:
            del self._event_drafts[event_draft_id]

    def count_event_drafts(self) -> int:
        return len(self._event_drafts)


def test_decode_file_bytes_round_trip():
    raw = b"hello world"
    payload = base64.b64encode(raw).decode("ascii")
    assert _decode_file_bytes(payload) == raw


def test_decode_file_bytes_rejects_invalid_payload():
    with pytest.raises(ValueError, match="file_bytes_base64"):
        _decode_file_bytes("not-base64")


def test_persist_with_warning_returns_warning_on_failure():
    persisted, warnings = _persist_with_warning(
        lambda: (_ for _ in ()).throw(RuntimeError("store unavailable")),
        warning_code="triage_persist_failed",
        log_message="Failed to persist triage result for %s: %s",
        log_args=("msg-1",),
    )

    assert persisted is False
    assert warnings == ["triage_persist_failed: store unavailable"]


def test_normalize_email_addresses_filters_duplicates_and_blanks():
    assert _normalize_email_addresses(
        [" sender@example.com ", "", "sender@example.com", None]
    ) == ["sender@example.com"]


def test_normalize_string_list_filters_duplicates_and_blanks():
    assert _normalize_string_list([" archive ", "", "archive", None]) == ["archive"]


def test_normalize_lowercase_string_list_normalizes_case():
    assert _normalize_lowercase_string_list([" CEO@Example.com ", "Team@Example.com"]) == [
        "ceo@example.com",
        "team@example.com",
    ]


def test_get_outbound_email_mode_defaults_to_dry_run(monkeypatch):
    monkeypatch.delenv("OUTBOUND_EMAIL_MODE", raising=False)

    assert _get_outbound_email_mode() == "dry_run"


def test_evaluate_outbound_recipients_rejects_blocked_domain(monkeypatch):
    monkeypatch.setenv("OUTBOUND_EMAIL_BLOCKED_DOMAINS", "gmail.com")

    allowed, reason = _evaluate_outbound_recipients(["person@gmail.com"])

    assert allowed is False
    assert "blocked" in reason


def test_evaluate_outbound_recipients_enforces_allow_list(monkeypatch):
    monkeypatch.setenv("OUTBOUND_EMAIL_ALLOWED_DOMAINS", "example.com")

    allowed, reason = _evaluate_outbound_recipients(
        ["allowed@example.com", "blocked@other.com"]
    )

    assert allowed is False
    assert "not allowed" in reason


def test_resolve_reply_recipients_prefers_reply_to():
    recipients = _resolve_reply_recipients(
        {
            "replyTo": [{"emailAddress": {"address": "reply@example.com"}}],
            "from": {"emailAddress": {"address": "sender@example.com"}},
        }
    )

    assert recipients == ["reply@example.com"]


def test_extract_document_text_uses_invoice_mode(monkeypatch):
    monkeypatch.setattr("function_app.get_doc_intelligence_client", lambda: FakeDocClient())
    payload = base64.b64encode(b"fake pdf").decode("ascii")

    text, summary = _extract_document_text(
        filename="Invoice_123.pdf",
        file_bytes_base64=payload,
        content_type="application/pdf",
    )

    assert text == "Extracted text"
    assert summary["used_document_intelligence"] is True
    assert summary["mode"] == "invoice"


def test_extract_document_text_handles_unavailable_client(monkeypatch):
    monkeypatch.setattr(
        "function_app.get_doc_intelligence_client",
        lambda: FakeDocClient(available=False, text=""),
    )
    payload = base64.b64encode(b"fake pdf").decode("ascii")

    text, summary = _extract_document_text(
        filename="Contract.pdf",
        file_bytes_base64=payload,
        content_type="application/pdf",
    )

    assert text == ""
    assert summary["used_document_intelligence"] is False
    assert summary["mode"] == "text"


def test_ingest_mailbox_returns_processed_messages(monkeypatch):
    store = CosmosDataStore(connection_string="")
    monkeypatch.setattr("function_app.MailboxIngestionService", FakeMailboxIngestionService)
    monkeypatch.setattr("function_app.get_store", lambda: store)

    response = ingest_mailbox(FakeRequest({"top": 5, "mark_processed": True}))
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["processed_count"] == 1
    assert payload["summary"]["processed_messages"] == 1
    assert payload["summary"]["warnings_count"] == 1
    assert payload["messages"][0]["email"]["message_id"] == "msg-1"
    assert payload["messages"][0]["attachments"][0]["sharepoint_target"]["folder_path"] == "01_CORPORATE/Finance/AP"
    assert store.count_triage_results() == 1
    assert store.count_documents() == 1


def test_triage_returns_warning_when_persistence_fails(monkeypatch):
    monkeypatch.setattr("function_app.get_store", lambda: FailingEndpointStore())

    response = triage(
        FakeRequest(
            {
                "subject": "Invoice #123",
                "sender": "billing@vendor.com",
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["persisted"] is False
    assert payload["triage"]["category"] == "vendor_ap"
    assert any("triage_persist_failed" in warning for warning in payload["warnings"])


def test_draft_reply_returns_warning_when_persistence_fails(monkeypatch):
    monkeypatch.setattr("function_app.get_store", lambda: FailingEndpointStore())

    response = draft_reply(
        FakeRequest(
            {
                "message_id": "msg-1",
                "subject": "Invoice #123",
                "body": "Please see attached invoice.",
                "sender_name": "Vendor Billing",
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["persisted"] is False
    assert payload["draft"]["message_id"] == "msg-1"
    assert any("draft_persist_failed" in warning for warning in payload["warnings"])


def test_update_draft_finds_draft_without_message_id(monkeypatch):
    store = CosmosDataStore(connection_string="")
    store.save_draft(
        {
            "draft_id": "draft-1",
            "message_id": "msg-1",
            "subject": "Re: Test",
            "body": "Original",
            "tone": "professional",
            "approved": False,
            "needs_review": True,
        }
    )
    monkeypatch.setattr("function_app.get_store", lambda: store)

    request = FakeRequest(
        {
            "approved": True,
            "to_recipients": ["sender@example.com"],
            "approval_note": "Looks ready to send.",
        }
    )
    request.route_params["draft_id"] = "draft-1"

    response = update_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["draft"]["approved"] is True
    assert payload["draft"]["needs_review"] is False
    assert payload["draft"]["status"] == "approved"
    assert payload["draft"]["approval_note"] == "Looks ready to send."
    assert payload["draft"]["to_recipients"] == ["sender@example.com"]
    assert store.get_draft("draft-1", "msg-1")["approved"] is True


def test_update_draft_can_mark_draft_unapproved(monkeypatch):
    store = CosmosDataStore(connection_string="")
    store.save_draft(
        {
            "draft_id": "draft-1",
            "message_id": "msg-1",
            "subject": "Re: Test",
            "body": "Original",
            "tone": "professional",
            "approved": True,
            "approved_by": "kmcquire",
            "approved_at": "2026-03-27T07:00:00+00:00",
            "needs_review": False,
            "status": "approved",
            "approval_note": "Looks good.",
        }
    )
    monkeypatch.setattr("function_app.get_store", lambda: store)

    request = FakeRequest({"approved": False, "approval_note": "Needs another pass."})
    request.route_params["draft_id"] = "draft-1"

    response = update_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["draft"]["approved"] is False
    assert payload["draft"]["needs_review"] is True
    assert payload["draft"]["status"] == "draft"
    assert payload["draft"]["approved_by"] == ""
    assert payload["draft"]["approval_note"] == "Needs another pass."


def test_send_draft_sends_reply_and_persists_state(monkeypatch):
    monkeypatch.setenv("OUTBOUND_EMAIL_MODE", "send")
    store = CosmosDataStore(connection_string="")
    store.save_draft(
        {
            "draft_id": "draft-1",
            "message_id": "msg-1",
            "subject": "Re: Test",
            "body": "Thanks for the note.",
            "tone": "professional",
            "approved": False,
            "needs_review": True,
        }
    )
    graph_client = FakeDraftGraphClient()
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest({})
    request.route_params["draft_id"] = "draft-1"

    response = send_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["sent"] is True
    assert payload["delivery_mode"] == "send"
    assert payload["draft"]["sent"] is True
    assert payload["draft"]["approved"] is True
    assert payload["draft"]["to_recipients"] == ["sender@example.com"]
    assert graph_client.sent_messages == [
        {
            "to_recipients": ["sender@example.com"],
            "cc_recipients": [],
            "subject": "Re: Test",
            "body": "Thanks for the note.",
            "content_type": "Text",
        }
    ]


def test_send_draft_resolves_brief_item_when_send_completes(monkeypatch):
    monkeypatch.setenv("OUTBOUND_EMAIL_MODE", "send")
    store = FakeMorningBriefStore()
    store.save_brief_item(
        {
            "id": "ctx-draft-send",
            "item_id": "ctx-draft-send",
            "item_kind": "follow_up",
            "type": "awaiting_response",
            "title": "Reply to sender",
            "message": "A reply draft is ready.",
            "suggested_action": "Approve and send the draft.",
            "priority": "medium",
            "state": "open",
            "recipient": "sender@example.com",
            "source_message_id": "msg-1",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    store.save_draft(
        {
            "draft_id": "draft-1",
            "message_id": "msg-1",
            "subject": "Re: Test",
            "body": "Thanks for the note.",
            "tone": "professional",
            "approved": True,
            "approved_by": "kmcquire",
            "needs_review": False,
            "to_recipients": ["sender@example.com"],
        }
    )
    graph_client = FakeDraftGraphClient()
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest({"brief_item_id": "ctx-draft-send", "requested_by": "kmcquire"})
    request.route_params["draft_id"] = "draft-1"

    response = send_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["sent"] is True
    assert payload["resolved_item"]["item_id"] == "ctx-draft-send"
    assert payload["resolved_item"]["state"] == "resolved"
    assert payload["resolved_item"]["reason_code"] == "replied"
    assert payload["resolved_item"]["reason_label"] == "Reply drafted or sent"


def test_send_draft_returns_error_when_no_recipients_can_be_resolved(monkeypatch):
    store = CosmosDataStore(connection_string="")
    store.save_draft(
        {
            "draft_id": "draft-2",
            "message_id": "msg-2",
            "subject": "Re: Test",
            "body": "Thanks",
        }
    )
    graph_client = FakeDraftGraphClient(message={})
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest({})
    request.route_params["draft_id"] = "draft-2"

    response = send_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 400
    assert payload["success"] is False
    assert "No reply recipients" in payload["error"]


def test_send_draft_defaults_to_dry_run_and_persists_attempt(monkeypatch):
    monkeypatch.delenv("OUTBOUND_EMAIL_MODE", raising=False)
    store = CosmosDataStore(connection_string="")
    store.save_draft(
        {
            "draft_id": "draft-3",
            "message_id": "msg-3",
            "subject": "Re: Test",
            "body": "Thanks",
            "approved_by": "kmcquire",
        }
    )
    graph_client = FakeDraftGraphClient()
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest({"requested_by": "assistant"})
    request.route_params["draft_id"] = "draft-3"

    response = send_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["sent"] is False
    assert payload["delivery_mode"] == "dry_run"
    assert payload["draft"]["delivery_mode"] == "dry_run"
    assert payload["draft"]["last_send_attempted_by"] == "assistant"
    assert graph_client.sent_messages == []


def test_send_draft_rejects_recipient_blocked_by_policy(monkeypatch):
    monkeypatch.setenv("OUTBOUND_EMAIL_MODE", "send")
    monkeypatch.setenv("OUTBOUND_EMAIL_BLOCKED_DOMAINS", "example.com")
    store = CosmosDataStore(connection_string="")
    store.save_draft(
        {
            "draft_id": "draft-4",
            "message_id": "msg-4",
            "subject": "Re: Test",
            "body": "Thanks",
            "to_recipients": ["sender@example.com"],
        }
    )
    graph_client = FakeDraftGraphClient()
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest({})
    request.route_params["draft_id"] = "draft-4"

    response = send_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 403
    assert payload["success"] is False
    assert "blocked" in payload["error"]
    assert graph_client.sent_messages == []


def test_apply_mailbox_action_updates_and_moves_message(monkeypatch):
    graph_client = FakeMailboxActionGraphClient()
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest(
        {
            "mark_read": True,
            "category": "Peak10Processed",
            "destination_folder": "archive",
        }
    )
    request.route_params["message_id"] = "msg-1"

    response = apply_mailbox_action(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["updated"] is True
    assert payload["moved"] is True
    assert payload["applied"]["categories"] == ["Peak10Processed"]
    assert graph_client.updated_messages == [
        ("msg-1", {"isRead": True, "categories": ["Peak10Processed"]})
    ]
    assert graph_client.moved_messages == [("msg-1", "archive")]


def test_apply_mailbox_action_requires_at_least_one_operation(monkeypatch):
    graph_client = FakeMailboxActionGraphClient()
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest({})
    request.route_params["message_id"] = "msg-1"

    response = apply_mailbox_action(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 400
    assert payload["success"] is False
    assert "At least one mailbox action" in payload["error"]


def test_apply_mailbox_action_returns_graph_error_details(monkeypatch):
    graph_client = FakeMailboxActionGraphClient(
        move_error=GraphRequestError(
            status_code=404,
            code="ErrorItemNotFound",
            message="The specified object was not found in the store.",
            url="https://graph.microsoft.com/v1.0/users/test/messages/msg-1/move",
        )
    )
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest(
        {
            "mark_read": True,
            "destination_folder": "archive",
        }
    )
    request.route_params["message_id"] = "msg-1"

    response = apply_mailbox_action(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 502
    assert payload["success"] is False
    assert payload["graph_error"]["code"] == "ErrorItemNotFound"
    assert payload["applied"]["destination_folder"] == "archive"


def test_calendar_assist_returns_heuristic_guidance_when_ai_unavailable(monkeypatch):
    class OfflineCalendarClient:
        is_available = False

    monkeypatch.setattr("function_app.get_openai_client", lambda: OfflineCalendarClient())

    response = calendar_assist(
        FakeRequest(
            {
                "message_id": "msg-cal-1",
                "subject": "Can we meet next Tuesday at 2 pm?",
                "sender": "counterparty@example.com",
                "sender_name": "Counterparty",
                "recipients": ["automation@peak10.test"],
                "body_text": "Would next Tuesday at 2 pm work for a quick Zoom?",
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["triage"]["category"] == "calendar"
    assert payload["calendar_assistance"]["is_calendar_related"] is True
    assert payload["calendar_assistance"]["suggested_action"] == "confirm_time"
    assert payload["event_draft"]["title"] == "Can we meet next Tuesday at 2 pm?"
    assert payload["event_draft"]["candidate_time_phrases"] == ["next Tuesday at 2 pm"]
    assert payload["ai_used"] is False


def test_calendar_assist_uses_ai_when_available(monkeypatch):
    monkeypatch.setattr("function_app.get_openai_client", lambda: FakeCalendarOpenAIClient())

    response = calendar_assist(
        FakeRequest(
            {
                "message_id": "msg-cal-2",
                "subject": "Meeting request",
                "sender": "counterparty@example.com",
                "body_text": "Could we meet next Tuesday at 2 pm?",
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["calendar_assistance"]["meeting_request_type"] == "new_request"
    assert payload["calendar_assistance"]["summary"] == "The sender is asking to meet next Tuesday at 2 pm."
    assert payload["event_draft"]["meeting_format"] == "unspecified"
    assert payload["ai_used"] is True


def test_growth_nudges_returns_summary_and_nudges(monkeypatch):
    monkeypatch.setattr("function_app.get_store", lambda: FakeInsightStore())

    request = FakeRequest({})
    request.params["limit"] = "10"

    response = growth_nudges(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["count"] == 5
    assert "relationship_drift" in payload["buckets"]
    nudge_types = {item["type"] for item in payload["nudges"]}
    assert "relationship_drift" in nudge_types
    assert "awaiting_response" in nudge_types
    assert "manual_review" in nudge_types


def test_morning_brief_returns_projects_watchlist_and_protected_time(monkeypatch):
    store = FakeMorningBriefStore()
    monkeypatch.setattr("function_app.get_store", lambda: store)

    response = morning_brief(
        FakeRequest(
            {
                "now": "2026-03-25T08:00:00+00:00",
                "calendar_items": [
                    {
                        "title": "Lunch meeting",
                        "start": "2026-03-25T12:00:00+00:00",
                        "end": "2026-03-25T12:45:00+00:00",
                    }
                ],
                "personal_priorities": [
                    {
                        "name": "Workout",
                        "preferred_days": ["WE", "TH", "FR"],
                        "preferred_window": {"start": "12:00", "end": "13:00"},
                        "duration_minutes": 60,
                    }
                ],
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["overview"]["ongoing_project_count"] >= 1
    assert payload["follow_ups"]
    assert payload["watchlist"]
    assert payload["protected_time"]["conflict_count"] == 1
    assert payload["suggested_focus_blocks"]
    assert payload["brief_items_persisted"] >= 1
    assert any(item["item_id"] == "carry-1" and item["carried_over"] for item in payload["follow_ups"])
    assert store.find_brief_item_by_id("carry-1")["state"] == "open"


def test_update_brief_item_state_resolves_item(monkeypatch):
    store = FakeMorningBriefStore()
    monkeypatch.setattr("function_app.get_store", lambda: store)

    request = FakeRequest({"state": "resolved", "updated_by": "kmcquire", "notes": "Handled in morning review"})
    request.route_params["item_id"] = "carry-1"

    response = update_brief_item_state(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["item"]["state"] == "resolved"
    assert payload["item"]["state_label"] == "Resolved"
    assert payload["item"]["available_actions"] == [{"action": "open", "label": "Reopen"}]
    assert payload["item"]["updated_by"] == "kmcquire"
    assert payload["item"]["notes"] == "Handled in morning review"
    assert store.find_brief_item_by_id("carry-1")["state"] == "resolved"


def test_list_brief_items_returns_ui_ready_items(monkeypatch):
    store = FakeMorningBriefStore()
    store.save_brief_item(
        {
            "id": "watch-1",
            "item_id": "watch-1",
            "item_kind": "watchlist",
            "type": "calendar_signal",
            "title": "Schedule diligence review meeting",
            "message": "The thread may need a calendar hold for next Tuesday.",
            "suggested_action": "Draft an event and confirm timing.",
            "priority": "medium",
            "state": "open",
            "contact": "owner@example.com",
            "source_message_id": "msg-12",
            "source_subject": "Can we meet next Tuesday at 2 pm?",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    store.save_brief_item(
        {
            "id": "watch-2",
            "item_id": "watch-2",
            "item_kind": "watchlist",
            "type": "hesitation_signal",
            "title": "Possible signal in timing email",
            "message": "The thread may be losing momentum.",
            "suggested_action": "Offer a lower-friction next step.",
            "priority": "medium",
            "state": "dismissed",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    monkeypatch.setattr("function_app.get_store", lambda: store)

    request = FakeRequest({})
    request.params["state"] = "open,dismissed"
    request.params["days"] = "30"

    response = list_brief_items(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["summary"]["by_state"]["open"] >= 1
    assert payload["summary"]["by_state"]["dismissed"] == 1
    assert any(item["available_actions"] == [{"action": "open", "label": "Reopen"}] for item in payload["items"])
    assert any(item.get("carry_over_days", 0) >= 1 for item in payload["items"] if item.get("item_id") == "carry-1")
    open_item = next(item for item in payload["items"] if item["item_id"] == "watch-1")
    assert any(action["action"] == "archive" for action in open_item["available_quick_actions"])
    assert any(action["action"] == "generate_event_draft" for action in open_item["available_quick_actions"])


def test_get_brief_item_context_returns_matching_messages_and_drafts(monkeypatch):
    store = FakeMorningBriefStore()
    store.save_brief_item(
        {
            "id": "ctx-1",
            "item_id": "ctx-1",
            "item_kind": "watchlist",
            "type": "hesitation_signal",
            "title": "Possible signal in lease diligence thread",
            "message": "Budget pressure may be developing in the diligence thread.",
            "suggested_action": "Reach out with a narrower next step.",
            "priority": "medium",
            "state": "open",
            "contact": "owner@example.com",
            "recipient": "silent@example.com",
            "thread_key": "conv-1",
            "source_message_id": "msg-2",
            "source_subject": "Re: Lease diligence follow-up",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    monkeypatch.setattr("function_app.get_store", lambda: store)

    request = FakeRequest({})
    request.route_params["item_id"] = "ctx-1"
    request.params["days"] = "30"
    request.params["limit"] = "5"

    response = get_brief_item_context(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["item"]["item_id"] == "ctx-1"
    assert payload["summary"]["message_count"] >= 1
    assert payload["summary"]["draft_count"] >= 1
    assert payload["summary"]["event_draft_count"] == 0
    assert payload["messages"][0]["message_id"] in {"msg-1", "msg-2"}
    assert any(message["matched_on"] in {"source_message", "thread", "contact"} for message in payload["messages"])
    assert any(draft["matched_on"] == "recipient" for draft in payload["drafts"])
    assert payload["drafts"][0]["available_actions"] == [
        {"action": "send", "label": "Send draft"},
        {"action": "unapprove", "label": "Mark unapproved"},
    ]
    assert payload["drafts"][0]["status"] == "approved"


def test_get_brief_item_context_returns_matching_event_drafts(monkeypatch):
    store = FakeMorningBriefStore()
    store.save_brief_item(
        {
            "id": "ctx-event-context",
            "item_id": "ctx-event-context",
            "item_kind": "follow_up",
            "type": "calendar_follow_up",
            "title": "Scheduling thread needs next step",
            "message": "A scheduling event draft already exists for this thread.",
            "suggested_action": "Review the event draft before confirming.",
            "priority": "medium",
            "state": "open",
            "source_message_id": "msg-5",
            "source_subject": "Can we meet next week?",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    monkeypatch.setattr("function_app.get_store", lambda: store)

    request = FakeRequest({})
    request.route_params["item_id"] = "ctx-event-context"
    request.params["days"] = "30"
    request.params["limit"] = "5"

    response = get_brief_item_context(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["summary"]["event_draft_count"] == 1
    assert payload["event_drafts"][0]["matched_on"] == "source_message"
    assert payload["event_drafts"][0]["title"] == "Can we meet next week?"
    assert payload["event_drafts"][0]["status"] == "draft"
    assert payload["event_drafts"][0]["available_actions"] == [
        {"action": "approve", "label": "Approve draft"}
    ]


def test_act_on_brief_item_archives_and_resolves(monkeypatch):
    store = FakeMorningBriefStore()
    store.save_brief_item(
        {
            "id": "ctx-archive",
            "item_id": "ctx-archive",
            "item_kind": "follow_up",
            "type": "awaiting_response",
            "title": "Check in with silent buyer",
            "message": "No reply yet from silent@example.com.",
            "suggested_action": "Send a quick nudge.",
            "priority": "high",
            "state": "open",
            "recipient": "silent@example.com",
            "source_message_id": "msg-1",
            "source_subject": "Lease diligence follow-up",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    graph_client = FakeMailboxActionGraphClient()
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest({"action": "archive", "requested_by": "kmcquire"})
    request.route_params["item_id"] = "ctx-archive"

    response = act_on_brief_item(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["action"] == "archive"
    assert payload["item"]["state"] == "resolved"
    assert payload["item"]["reason_code"] == "archived"
    assert graph_client.updated_messages == [
        ("msg-1", {"isRead": True, "categories": ["Peak10Processed"]})
    ]
    assert graph_client.moved_messages == [("msg-1", "archive")]


def test_act_on_brief_item_archive_falls_back_to_mark_read_resolve(monkeypatch):
    store = FakeMorningBriefStore()
    store.save_brief_item(
        {
            "id": "ctx-archive-fallback",
            "item_id": "ctx-archive-fallback",
            "item_kind": "follow_up",
            "type": "awaiting_response",
            "title": "Check in with silent buyer",
            "message": "No reply yet from silent@example.com.",
            "suggested_action": "Send a quick nudge.",
            "priority": "high",
            "state": "open",
            "recipient": "silent@example.com",
            "source_message_id": "msg-1",
            "source_subject": "Lease diligence follow-up",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    graph_client = FakeMailboxActionGraphClient(
        move_error=GraphRequestError(
            status_code=404,
            code="ErrorItemNotFound",
            message="The specified object was not found in the store.",
            url="https://graph.microsoft.com/v1.0/users/test/messages/msg-1/move",
        )
    )
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest({"action": "archive", "requested_by": "kmcquire"})
    request.route_params["item_id"] = "ctx-archive-fallback"

    response = act_on_brief_item(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["mailbox_action"]["updated"] is True
    assert payload["mailbox_action"]["moved"] is False
    assert payload["mailbox_action"]["fallback"]["applied"] is True
    assert payload["mailbox_action"]["move_error"]["code"] == "ErrorItemNotFound"
    assert "archive_move_failed:ErrorItemNotFound" in payload["warnings"]
    assert payload["item"]["state"] == "resolved"
    assert payload["item"]["reason_code"] == "archive_fallback"
    assert payload["item"]["reason_label"] == "Marked read; archive move failed"
    assert graph_client.updated_messages == [
        ("msg-1", {"isRead": True, "categories": ["Peak10Processed"]})
    ]
    assert graph_client.moved_messages == [("msg-1", "archive")]


def test_act_on_brief_item_archive_resolves_if_source_message_is_missing(monkeypatch):
    store = FakeMorningBriefStore()
    store.save_brief_item(
        {
            "id": "ctx-archive-missing",
            "item_id": "ctx-archive-missing",
            "item_kind": "follow_up",
            "type": "manual_review",
            "title": "Ambiguous inbox items are accumulating",
            "message": "Review unknown items and tune routing where needed.",
            "suggested_action": "Review unknown items and tune routing where needed.",
            "priority": "low",
            "state": "open",
            "source_message_id": "msg-1",
            "source_subject": "Att 2",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    graph_client = FakeMailboxActionGraphClient(
        update_error=GraphRequestError(
            status_code=404,
            code="ErrorItemNotFound",
            message="The specified object was not found in the store.",
            url="https://graph.microsoft.com/v1.0/users/test/messages/msg-1",
        )
    )
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest({"action": "archive", "requested_by": "kmcquire"})
    request.route_params["item_id"] = "ctx-archive-missing"

    response = act_on_brief_item(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["mailbox_action"]["updated"] is False
    assert payload["mailbox_action"]["moved"] is False
    assert payload["mailbox_action"]["fallback"]["applied"] is True
    assert payload["mailbox_action"]["fallback"]["mode"] == "resolve_missing_source"
    assert payload["mailbox_action"]["update_error"]["code"] == "ErrorItemNotFound"
    assert "archive_source_missing:ErrorItemNotFound" in payload["warnings"]
    assert payload["item"]["state"] == "resolved"
    assert payload["item"]["reason_code"] == "source_missing"
    assert payload["item"]["reason_label"] == "Source message no longer in mailbox"
    assert graph_client.updated_messages == [
        ("msg-1", {"isRead": True, "categories": ["Peak10Processed"]})
    ]
    assert graph_client.moved_messages == []


def test_act_on_brief_item_generates_reply_draft(monkeypatch):
    class OfflineOpenAIClient:
        is_available = False

    store = FakeMorningBriefStore()
    store.save_brief_item(
        {
            "id": "ctx-draft",
            "item_id": "ctx-draft",
            "item_kind": "follow_up",
            "type": "awaiting_response",
            "title": "Check in with silent buyer",
            "message": "No reply yet from silent@example.com.",
            "suggested_action": "Send a quick nudge.",
            "priority": "high",
            "state": "open",
            "recipient": "sender@example.com",
            "source_message_id": "msg-9",
            "source_subject": "Need your answer",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    graph_client = FakeDraftGraphClient(
        message={
            "subject": "Need your answer",
            "bodyPreview": "Can you let me know by tomorrow?",
            "from": {"emailAddress": {"address": "sender@example.com", "name": "Sender Person"}},
            "replyTo": [],
            "toRecipients": [],
            "ccRecipients": [],
        }
    )
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)
    monkeypatch.setattr("function_app.get_openai_client", lambda: OfflineOpenAIClient())

    request = FakeRequest({"action": "generate_reply_draft", "requested_by": "kmcquire"})
    request.route_params["item_id"] = "ctx-draft"

    response = act_on_brief_item(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["draft"]["message_id"] == "msg-9"
    assert payload["draft"]["subject"] == "Re: Need your answer"
    assert payload["item"]["last_operator_action"] == "generate_reply_draft"


def test_act_on_brief_item_generates_event_draft(monkeypatch):
    store = FakeMorningBriefStore()
    store.save_brief_item(
        {
            "id": "ctx-event",
            "item_id": "ctx-event",
            "item_kind": "watchlist",
            "type": "calendar_signal",
            "title": "Meeting request needs review",
            "message": "The sender asked whether next Tuesday at 2 pm works.",
            "suggested_action": "Draft an event and confirm timing.",
            "priority": "medium",
            "state": "open",
            "source_message_id": "msg-1",
            "source_subject": "Can we meet next Tuesday at 2 pm?",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    graph_client = FakeMailboxActionGraphClient()
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    class OfflineCalendarClient:
        is_available = False

    monkeypatch.setattr("function_app.get_openai_client", lambda: OfflineCalendarClient())

    request = FakeRequest({"action": "generate_event_draft", "requested_by": "kmcquire"})
    request.route_params["item_id"] = "ctx-event"

    response = act_on_brief_item(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["event_draft"]["title"] == "Can we meet next Tuesday at 2 pm?"
    assert payload["event_draft"]["candidate_time_phrases"] == ["next Tuesday at 2 pm"]
    assert payload["triage"]["category"] == "calendar"
    assert payload["calendar_assistance"]["is_calendar_related"] is True
    assert payload["calendar_assistance"]["meeting_request_type"] == "new_request"
    assert payload["persisted"] is True
    assert payload["item"]["last_operator_action"] == "generate_event_draft"
    assert store.count_event_drafts() == 2


def test_get_event_drafts_returns_message_records(monkeypatch):
    store = FakeMorningBriefStore()
    monkeypatch.setattr("function_app.get_store", lambda: store)

    request = FakeRequest({})
    request.route_params["message_id"] = "msg-5"

    response = get_event_drafts(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["event_drafts"][0]["event_draft_id"] == "event-1"


def test_update_event_draft_approves_persisted_record(monkeypatch):
    store = FakeMorningBriefStore()
    monkeypatch.setattr("function_app.get_store", lambda: store)

    request = FakeRequest({"source_message_id": "msg-5", "approved": True, "approved_by": "kmcquire"})
    request.route_params["event_draft_id"] = "event-1"

    response = update_event_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["event_draft"]["approved"] is True
    assert payload["event_draft"]["approved_by"] == "kmcquire"
    assert payload["event_draft"]["needs_review"] is False
    assert payload["event_draft"]["status"] == "approved"


def test_update_event_draft_can_mark_record_unapproved(monkeypatch):
    store = FakeMorningBriefStore()
    event_draft = store.get_event_draft("event-1", "msg-5")
    assert event_draft is not None
    event_draft["approved"] = True
    event_draft["approved_by"] = "kmcquire"
    event_draft["approved_at"] = "2026-03-27T07:00:00+00:00"
    event_draft["needs_review"] = False
    event_draft["status"] = "approved"
    store.save_event_draft(event_draft)
    monkeypatch.setattr("function_app.get_store", lambda: store)

    request = FakeRequest({"source_message_id": "msg-5", "approved": False, "review_notes": "Needs clarification."})
    request.route_params["event_draft_id"] = "event-1"

    response = update_event_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["event_draft"]["approved"] is False
    assert payload["event_draft"]["approved_by"] == ""
    assert payload["event_draft"]["needs_review"] is True
    assert payload["event_draft"]["status"] == "draft"
    assert payload["event_draft"]["review_notes"] == "Needs clarification."


def test_create_event_from_draft_requires_approval(monkeypatch):
    store = FakeMorningBriefStore()
    graph_client = FakeMailboxActionGraphClient()
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest({"source_message_id": "msg-5", "requested_by": "kmcquire"})
    request.route_params["event_draft_id"] = "event-1"

    response = create_event_from_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 409
    assert "must be approved" in payload["error"]


def test_create_event_from_draft_persists_created_event_metadata(monkeypatch):
    store = FakeMorningBriefStore()
    graph_client = FakeMailboxActionGraphClient()
    store.save_brief_item(
        {
            "id": "ctx-event-create",
            "item_id": "ctx-event-create",
            "item_kind": "follow_up",
            "type": "calendar_follow_up",
            "title": "Scheduling thread needs next step",
            "message": "A saved event draft is ready for approval.",
            "suggested_action": "Approve it and create the calendar event.",
            "priority": "medium",
            "state": "open",
            "source_message_id": "msg-5",
            "source_subject": "Can we meet next week?",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    approved = store.get_event_draft("event-1", "msg-5")
    assert approved is not None
    approved["approved"] = True
    approved["approved_by"] = "kmcquire"
    approved["approved_at"] = "2026-03-27T07:00:00+00:00"
    approved["needs_review"] = False
    approved["status"] = "approved"
    store.save_event_draft(approved)

    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: graph_client)

    request = FakeRequest(
        {
            "source_message_id": "msg-5",
            "requested_by": "kmcquire",
            "brief_item_id": "ctx-event-create",
            "start_at": "2026-04-07T14:00:00+00:00",
            "attendees": ["counterparty@example.com"],
        }
    )
    request.route_params["event_draft_id"] = "event-1"

    response = create_event_from_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["event_draft"]["created_event"] is True
    assert payload["event_draft"]["created_event_id"] == "event-123"
    assert payload["event_draft"]["created_event_web_link"] == "https://example.com/event-123"
    assert payload["event_draft"]["scheduled_start_at"] == "2026-04-07T14:00:00+00:00"
    assert payload["event_draft"]["status"] == "event_created"
    assert payload["created_event"]["web_link"] == "https://example.com/event-123"
    assert payload["created_event"]["start_at"] == "2026-04-07T14:00:00+00:00"
    assert payload["resolved_item"]["item_id"] == "ctx-event-create"
    assert payload["resolved_item"]["state"] == "resolved"
    assert payload["resolved_item"]["reason_code"] == "scheduled"
    assert payload["resolved_item"]["reason_label"] == "Calendar event created"
    assert graph_client.created_events[0]["subject"] == "Can we meet next week?"


def test_create_event_from_draft_retries_after_access_denied(monkeypatch):
    store = FakeMorningBriefStore()
    first_client = FakeMailboxActionGraphClient(
        create_event_error=GraphRequestError(
            status_code=403,
            code="ErrorAccessDenied",
            message="Access is denied. Check credentials and try again.",
            url="https://graph.microsoft.com/v1.0/users/automation@peak10.test/events",
        )
    )
    second_client = FakeMailboxActionGraphClient()
    approved = store.get_event_draft("event-1", "msg-5")
    assert approved is not None
    approved["approved"] = True
    approved["approved_by"] = "kmcquire"
    approved["approved_at"] = "2026-03-27T07:00:00+00:00"
    approved["needs_review"] = False
    approved["status"] = "approved"
    store.save_event_draft(approved)

    clients = iter([first_client, second_client])
    reset_calls: list[str] = []
    monkeypatch.setattr("function_app.get_store", lambda: store)
    monkeypatch.setattr("function_app.get_graph_client", lambda: next(clients))
    monkeypatch.setattr("function_app.reset_graph_client", lambda: reset_calls.append("reset"))

    request = FakeRequest(
        {
            "source_message_id": "msg-5",
            "requested_by": "kmcquire",
            "start_at": "2026-04-07T14:00:00+00:00",
            "attendees": ["counterparty@example.com"],
        }
    )
    request.route_params["event_draft_id"] = "event-1"

    response = create_event_from_draft(request)
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert reset_calls == ["reset"]
    assert first_client.created_events == []
    assert second_client.created_events[0]["subject"] == "Can we meet next week?"
    assert payload["event_draft"]["created_event"] is True


def test_brief_review_page_returns_html():
    request = FakeRequest({})
    request.params["code"] = "example-code"

    response = brief_review_page(request)
    payload = response.get_body().decode("utf-8")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "Morning Brief Review" in payload
    assert "email/brief/items" in payload
    assert "Recently Cleared" in payload
    assert "View context" in payload
    assert "Draft reply" in payload
    assert "Draft event" in payload
    assert "Event draft preview" in payload
    assert "Event drafts" in payload
    assert "updateDraft" in payload
    assert "sendDraft" in payload
    assert "noteForDraft" in payload
    assert "updateEventDraft" in payload
    assert "createEventFromDraft" in payload
    assert "reviewNoteForEventDraft" in payload
    assert "sortItemsByRecency" in payload
    assert "Latest activity" in payload
    assert "Status:" in payload
    assert "Latest action" in payload
    assert "example-code" in payload


def test_morning_brief_suppresses_resolved_item_on_next_run(monkeypatch):
    store = FakeMorningBriefStore()
    store.save_brief_item(
        {
            "id": "carry-1",
            "item_id": "carry-1",
            "item_kind": "follow_up",
            "type": "manual_review",
            "title": "Ambiguous inbox items are accumulating",
            "message": "3 message(s) still landed as unknown, so there may be hidden intent worth sorting manually.",
            "suggested_action": "Review unknown items and tune routing where needed.",
            "priority": "low",
            "state": "resolved",
            "first_seen_at": "2026-03-25T08:00:00+00:00",
            "last_seen_at": "2026-03-25T08:00:00+00:00",
        }
    )
    monkeypatch.setattr("function_app.get_store", lambda: store)

    response = morning_brief(FakeRequest({"now": "2026-03-25T08:00:00+00:00"}))
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert all(item["item_id"] != "carry-1" for item in payload["follow_ups"])


def test_classify_doc_returns_warning_when_persistence_fails(monkeypatch):
    monkeypatch.setattr("function_app.get_store", lambda: FailingEndpointStore())

    response = classify_doc(FakeRequest({"filename": "Invoice_123.pdf"}))
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["persisted"] is False
    assert payload["classification"]["document_type"] == "invoice"
    assert any("document_persist_failed" in warning for warning in payload["warnings"])


def test_correct_classification_returns_warning_when_persistence_fails(monkeypatch):
    monkeypatch.setattr("function_app.get_store", lambda: FailingEndpointStore())

    response = correct_classification(
        FakeRequest(
            {
                "document_id": "doc-1",
                "original_type": "contract",
                "corrected_type": "amendment",
            }
        )
    )
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["persisted"] is False
    assert payload["correction_id"]
    assert any("correction_persist_failed" in warning for warning in payload["warnings"])


def test_run_mailbox_ingestion_raises_when_graph_is_unavailable():
    store = CosmosDataStore(connection_string="")

    with pytest.raises(RuntimeError, match="Graph mailbox configuration"):
        _run_mailbox_ingestion(
            top=5,
            mark_processed=False,
            service=FakeMailboxIngestionService(available=False),
            store=store,
        )


def test_run_mailbox_ingestion_persists_results():
    store = CosmosDataStore(connection_string="")
    service = FakeMailboxIngestionService()

    payload = _run_mailbox_ingestion(
        top=3,
        mark_processed=True,
        service=service,
        store=store,
    )

    assert len(payload) == 1
    assert service.last_top == 3
    assert service.last_mark_processed is True
    assert store.count_triage_results() == 1
    assert store.count_documents() == 1
    assert payload[0]["warnings"] == ["attachment_fetch_failed: attachments endpoint failed"]


def test_run_mailbox_ingestion_dispatches_contracts_to_pillar3(monkeypatch):
    store = CosmosDataStore(connection_string="")
    service = FakePillar3MailboxIngestionService()
    document_ai = FakeDocumentAiClient()
    monkeypatch.setattr("function_app.get_document_ai_client", lambda: document_ai)

    payload = _run_mailbox_ingestion(
        top=2,
        mark_processed=False,
        service=service,
        store=store,
    )

    assert len(payload) == 1
    assert document_ai.calls
    assert document_ai.calls[0]["filename"] == "MSA_DrillCo.pdf"
    assert document_ai.calls[0]["classification"]["document_type"] == "contract"
    assert document_ai.calls[0]["source_metadata"]["email_subject"] == "MSA draft for review"
    assert payload[0]["attachments"][0]["pillar3_stage"]["dispatched"] is True
    assert payload[0]["attachments"][0]["pillar3_stage"]["status"] == "classified"


def test_run_mailbox_ingestion_records_pillar3_stage_failures(monkeypatch):
    store = CosmosDataStore(connection_string="")
    service = FakePillar3MailboxIngestionService()
    document_ai = FakeDocumentAiClient(raise_error=RuntimeError("stage unavailable"))
    monkeypatch.setattr("function_app.get_document_ai_client", lambda: document_ai)

    payload = _run_mailbox_ingestion(
        top=2,
        mark_processed=False,
        service=service,
        store=store,
    )

    assert len(payload) == 1
    assert payload[0]["attachments"][0]["pillar3_stage"]["dispatched"] is False
    assert payload[0]["attachments"][0]["pillar3_stage"]["reason"] == "pillar3_stage_failed"
    assert any("pillar3_stage_failed:MSA_DrillCo.pdf" in warning for warning in payload[0]["warnings"])


def test_run_mailbox_ingestion_records_persistence_failures_without_raising():
    payload = _run_mailbox_ingestion(
        top=3,
        mark_processed=True,
        service=FakeMailboxIngestionService(),
        store=FailingMailboxStore(),
    )

    assert len(payload) == 1
    assert payload[0]["email"]["message_id"] == "msg-1"
    assert payload[0]["attachments"][0]["filename"] == "Invoice_123.pdf"
    assert any("triage_persist_failed" in warning for warning in payload[0]["warnings"])
    assert any(
        "document_persist_failed:Invoice_123.pdf" in warning
        for warning in payload[0]["warnings"]
    )


def test_summarize_mailbox_ingestion_counts_operational_metrics():
    summary = _summarize_mailbox_ingestion(
        [
            {
                "attachments": [
                    {
                        "sharepoint_target": {"disposition": "filed"},
                        "upload": {"uploaded": True},
                    },
                    {
                        "sharepoint_target": {"disposition": "staged_for_review"},
                        "upload": {
                            "uploaded": False,
                            "reason": "sharepoint_upload_failed",
                        },
                    },
                    {
                        "sharepoint_target": {"disposition": "unsupported"},
                        "upload": {"uploaded": False, "reason": "sharepoint_unavailable"},
                    },
                ],
                "warnings": ["warning-a", "warning-b"],
                "marked_processed": True,
            }
        ]
    )

    assert summary == {
        "processed_messages": 1,
        "messages_marked_processed": 1,
        "warnings_count": 2,
        "attachments_processed": 3,
        "attachments_uploaded": 1,
        "attachments_filed": 1,
        "attachments_staged_for_review": 1,
        "attachments_unsupported": 1,
        "attachments_upload_failures": 1,
    }


def test_poll_mailbox_skips_when_disabled(monkeypatch):
    calls: list[tuple[int, bool]] = []
    monkeypatch.setenv("MAILBOX_POLL_ENABLED", "false")
    monkeypatch.setattr(
        "function_app._run_mailbox_ingestion",
        lambda top, mark_processed: calls.append((top, mark_processed)),
    )

    poll_mailbox(FakeTimerRequest())

    assert calls == []


def test_poll_mailbox_uses_configured_settings(monkeypatch):
    calls: list[tuple[int, bool]] = []
    monkeypatch.setenv("MAILBOX_POLL_ENABLED", "true")
    monkeypatch.setenv("MAILBOX_POLL_TOP", "7")
    monkeypatch.setenv("MAILBOX_MARK_PROCESSED", "false")
    monkeypatch.setattr(
        "function_app._run_mailbox_ingestion",
        lambda top, mark_processed: calls.append((top, mark_processed)) or [],
    )

    poll_mailbox(FakeTimerRequest(past_due=True))

    assert calls == [(7, False)]
