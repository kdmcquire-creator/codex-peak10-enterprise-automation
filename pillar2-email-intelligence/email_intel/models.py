"""
Data models for the Executive Communications Intelligence system.

Defines: email classification, urgency tiers, deal signals,
draft responses, and inter-pillar routing decisions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UrgencyTier(int, Enum):
    """Email urgency tiers (1 = highest)."""
    CRITICAL = 1     # Requires immediate CEO attention (legal threats, regulator)
    HIGH = 2         # Time-sensitive business (deal responses, board requests)
    STANDARD = 3     # Normal business correspondence
    LOW = 4          # Informational, newsletters, FYI items
    NOISE = 5        # Marketing, spam that passed filters, automated alerts


class EmailCategory(str, Enum):
    """Primary classification categories for inbound email."""
    DEAL_RELATED = "deal_related"
    VENDOR_AP = "vendor_ap"
    LEGAL = "legal"
    REGULATORY = "regulatory"
    OPERATIONS = "operations"
    INTERNAL = "internal"
    PERSONAL = "personal"
    CALENDAR = "calendar"
    RECEIPT = "receipt"
    NEWSLETTER = "newsletter"
    SPAM = "spam"
    UNKNOWN = "unknown"


class DealSignalType(str, Enum):
    """Deal-stage signals detected in email content."""
    NEW_OPPORTUNITY = "new_opportunity"          # "I have a package for you"
    LOI_DISCUSSION = "loi_discussion"            # LOI terms, counter-offers
    DUE_DILIGENCE = "due_diligence"              # Title, environmental, reserve data
    PSA_NEGOTIATION = "psa_negotiation"           # PSA drafts, redlines
    CLOSING_ACTION = "closing_action"             # Wire instructions, closing docs
    POST_CLOSE = "post_close"                     # Transition items
    DEAL_DEAD = "deal_dead"                       # Pass, withdrawn, no longer available


class ActionType(str, Enum):
    """Recommended actions for the executive."""
    REPLY = "reply"
    FORWARD = "forward"
    SCHEDULE_MEETING = "schedule_meeting"
    FILE_DOCUMENT = "file_document"             # Route attachment to Pillar 3
    CREATE_EXPENSE = "create_expense"           # Route receipt to Pillar 4
    ADD_TO_AP = "add_to_ap"                     # Route invoice to Pillar 1
    FLAG_FOR_REVIEW = "flag_for_review"
    ARCHIVE = "archive"
    DELETE = "delete"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

@dataclass
class EmailMessage:
    """Represents an inbound email for processing."""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subject: str = ""
    sender: str = ""
    sender_name: str = ""
    recipients: list[str] = field(default_factory=list)
    body_preview: str = ""       # First ~2000 chars
    body_text: str = ""          # Full plain-text body
    received_at: datetime = field(default_factory=utc_now)
    has_attachments: bool = False
    attachment_names: list[str] = field(default_factory=list)
    conversation_id: str = ""
    is_reply: bool = False


@dataclass
class DealSignal:
    """A deal-stage signal detected in an email."""
    signal_type: DealSignalType = DealSignalType.NEW_OPPORTUNITY
    confidence: float = 0.0
    evidence: str = ""           # The phrase/sentence that triggered detection
    suggested_action: str = ""   # E.g., "Schedule diligence call"


@dataclass
class TriageResult:
    """Complete triage result for an email."""
    message_id: str = ""
    category: EmailCategory = EmailCategory.UNKNOWN
    urgency: UrgencyTier = UrgencyTier.STANDARD
    confidence: float = 0.0
    summary: str = ""            # 1-2 sentence summary of the email
    deal_signals: list[DealSignal] = field(default_factory=list)
    recommended_actions: list[ActionType] = field(default_factory=list)
    routing: list[str] = field(default_factory=list)  # Inter-pillar routing targets
    reasoning: str = ""


@dataclass
class DraftResponse:
    """AI-generated draft reply."""
    draft_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_id: str = ""
    subject: str = ""
    body: str = ""
    tone: str = "professional"   # "professional" | "brief" | "warm"
    confidence: float = 0.0
    needs_review: bool = True
    approved: bool = False
    approved_at: Optional[str] = None
    approved_by: str = ""
    to_recipients: list[str] = field(default_factory=list)
    cc_recipients: list[str] = field(default_factory=list)
    sent: bool = False
    sent_at: Optional[str] = None
    sent_by: str = ""
    delivery_mode: str = "unsent"
    last_send_attempt_at: Optional[str] = None
    last_send_attempted_by: str = ""
    send_block_reason: str = ""


@dataclass
class EventDraft:
    """Structured meeting draft derived from a scheduling-oriented email."""
    event_draft_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_message_id: str = ""
    source_subject: str = ""
    thread_key: str = ""
    title: str = ""
    attendees: list[str] = field(default_factory=list)
    candidate_time_phrases: list[str] = field(default_factory=list)
    duration_minutes: int = 30
    meeting_format: str = "unspecified"
    location_hint: str = "TBD"
    summary: str = ""
    description: str = ""
    suggested_action: str = ""
    needs_review: bool = True
    confidence: float = 0.0
    review_notes: str = ""
    approved: bool = False
    approved_at: Optional[str] = None
    approved_by: str = ""
    status: str = "draft"
    created_event: bool = False
    created_event_at: Optional[str] = None
    created_event_by: str = ""
    created_event_id: str = ""
    created_event_web_link: str = ""


@dataclass
class AttachmentRouting:
    """Routing decision for an email attachment to another pillar."""
    attachment_name: str = ""
    detected_type: str = ""      # "invoice", "receipt", "contract", etc.
    target_pillar: str = ""      # "pillar1", "pillar3", "pillar4"
    target_endpoint: str = ""    # API endpoint to call
    confidence: float = 0.0
