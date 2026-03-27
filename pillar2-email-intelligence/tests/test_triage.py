"""
Tests for the email triage engine.

Covers:
  - Sender domain rules (regulatory, legal, newsletters)
  - Subject keyword classification
  - Deal signal detection in body text
  - Attachment routing to correct pillars
  - AI response parsing
  - Unified triage pipeline
  - Edge cases
"""

from __future__ import annotations

import pytest

from email_intel.models import (
    ActionType,
    DealSignalType,
    EmailCategory,
    EmailMessage,
    UrgencyTier,
)
from email_intel.triage import (
    detect_deal_signals,
    parse_ai_triage,
    route_attachments,
    triage_by_rules,
    triage_email,
)


def make_email(**kwargs) -> EmailMessage:
    defaults = {
        "subject": "Test email",
        "sender": "test@example.com",
        "sender_name": "Test User",
        "body_preview": "Hello, this is a test.",
    }
    defaults.update(kwargs)
    return EmailMessage(**defaults)


# ---------------------------------------------------------------------------
# Sender domain rules
# ---------------------------------------------------------------------------

class TestSenderDomainRules:
    def test_rrc_regulatory(self):
        email = make_email(sender="notice@rrc.texas.gov", subject="Compliance Notice")
        result = triage_by_rules(email)
        assert result is not None
        assert result.category == EmailCategory.REGULATORY
        assert result.urgency == UrgencyTier.CRITICAL

    def test_epa_regulatory(self):
        email = make_email(sender="enforcement@epa.gov", subject="Inspection")
        result = triage_by_rules(email)
        assert result is not None
        assert result.category == EmailCategory.REGULATORY

    def test_newsletter_noreply(self):
        email = make_email(sender="noreply@marketing.com", subject="Weekly digest")
        result = triage_by_rules(email)
        assert result is not None
        assert result.category == EmailCategory.NEWSLETTER
        assert result.urgency == UrgencyTier.NOISE


# ---------------------------------------------------------------------------
# Subject keyword classification
# ---------------------------------------------------------------------------

class TestSubjectRules:
    def test_deal_loi(self):
        email = make_email(subject="RE: Letter of Intent - Loving County Assets")
        result = triage_by_rules(email)
        assert result is not None
        assert result.category == EmailCategory.DEAL_RELATED
        assert result.urgency == UrgencyTier.HIGH

    def test_deal_closing(self):
        email = make_email(subject="Wire instructions for closing")
        result = triage_by_rules(email)
        assert result is not None
        assert result.urgency == UrgencyTier.CRITICAL

    def test_vendor_invoice(self):
        email = make_email(subject="Invoice #2026-0412 - Halliburton Services")
        result = triage_by_rules(email)
        assert result is not None
        assert result.category == EmailCategory.VENDOR_AP
        assert ActionType.ADD_TO_AP in result.recommended_actions

    def test_operations_emergency(self):
        email = make_email(subject="URGENT: H2S detected at Well #7")
        result = triage_by_rules(email)
        assert result is not None
        assert result.category == EmailCategory.OPERATIONS
        assert result.urgency == UrgencyTier.CRITICAL

    def test_receipt(self):
        email = make_email(subject="Your Uber receipt")
        result = triage_by_rules(email)
        assert result is not None
        assert result.category == EmailCategory.RECEIPT
        assert ActionType.CREATE_EXPENSE in result.recommended_actions

    def test_airline_receipt(self):
        email = make_email(subject="American Airlines booking confirmation")
        result = triage_by_rules(email)
        assert result is not None
        assert result.category == EmailCategory.RECEIPT

    def test_calendar_meeting_language(self):
        email = make_email(subject="Can we meet next Tuesday at 2 pm?")
        result = triage_by_rules(email)
        assert result is not None
        assert result.category == EmailCategory.CALENDAR

    def test_unknown_subject(self):
        email = make_email(subject="Hello there", sender="friend@gmail.com")
        result = triage_by_rules(email)
        assert result is None  # no rules match


# ---------------------------------------------------------------------------
# Deal signal detection
# ---------------------------------------------------------------------------

class TestDealSignals:
    def test_new_opportunity(self):
        text = "We have a new package of Permian Basin assets for sale."
        signals = detect_deal_signals(text)
        assert len(signals) == 1
        assert signals[0].signal_type == DealSignalType.NEW_OPPORTUNITY

    def test_loi_discussion(self):
        text = "Please find attached our non-binding offer for your review."
        signals = detect_deal_signals(text)
        assert any(s.signal_type == DealSignalType.LOI_DISCUSSION for s in signals)

    def test_closing_action(self):
        text = "Wire instructions are attached. Closing date is March 20."
        signals = detect_deal_signals(text)
        assert any(s.signal_type == DealSignalType.CLOSING_ACTION for s in signals)

    def test_deal_dead(self):
        text = "Unfortunately, the package is no longer available."
        signals = detect_deal_signals(text)
        assert any(s.signal_type == DealSignalType.DEAL_DEAD for s in signals)

    def test_multiple_signals(self):
        text = "We are entering the data room for due diligence. PSA redline attached."
        signals = detect_deal_signals(text)
        types = {s.signal_type for s in signals}
        assert DealSignalType.DUE_DILIGENCE in types
        assert DealSignalType.PSA_NEGOTIATION in types

    def test_no_signals(self):
        text = "Let's grab lunch next week."
        signals = detect_deal_signals(text)
        assert len(signals) == 0


# ---------------------------------------------------------------------------
# Attachment routing
# ---------------------------------------------------------------------------

class TestAttachmentRouting:
    def test_invoice_to_pillar1(self):
        routes = route_attachments(["Invoice_HES_March2026.pdf"])
        assert len(routes) == 1
        assert routes[0].target_pillar == "pillar1"

    def test_receipt_to_pillar4(self):
        routes = route_attachments(["Uber_Receipt_20260314.pdf"])
        assert len(routes) == 1
        assert routes[0].target_pillar == "pillar4"

    def test_contract_to_pillar3(self):
        routes = route_attachments(["MSA_Agreement_DrillCo.pdf"])
        assert len(routes) == 1
        assert routes[0].target_pillar == "pillar3"

    def test_generic_pdf_to_pillar3(self):
        routes = route_attachments(["document.pdf"])
        assert len(routes) == 1
        assert routes[0].target_pillar == "pillar3"

    def test_multiple_attachments(self):
        routes = route_attachments([
            "Invoice_123.pdf",
            "Receipt_Uber.pdf",
            "Contract_Amendment.docx",
        ])
        assert len(routes) == 3
        pillars = {r.target_pillar for r in routes}
        assert "pillar1" in pillars
        assert "pillar4" in pillars
        assert "pillar3" in pillars


# ---------------------------------------------------------------------------
# AI response parsing
# ---------------------------------------------------------------------------

class TestAIResponseParsing:
    def test_valid_response(self):
        ai_resp = {
            "category": "deal_related",
            "urgency": 2,
            "summary": "Broker presenting Loving County acreage package.",
            "confidence": 0.92,
            "deal_signals": [
                {"signal_type": "new_opportunity", "confidence": 0.88, "evidence": "package of assets"}
            ],
            "recommended_actions": ["flag_for_review", "reply"],
            "reasoning": "Deal-related email from known broker",
        }
        result = parse_ai_triage(ai_resp, "msg-123")
        assert result.category == EmailCategory.DEAL_RELATED
        assert result.urgency == UrgencyTier.HIGH
        assert result.confidence == 0.92
        assert len(result.deal_signals) == 1

    def test_unknown_category_fallback(self):
        result = parse_ai_triage({"category": "alien_mail"}, "msg-1")
        assert result.category == EmailCategory.UNKNOWN

    def test_empty_response(self):
        result = parse_ai_triage({}, "msg-1")
        assert result.category == EmailCategory.UNKNOWN
        assert result.urgency == UrgencyTier.STANDARD


# ---------------------------------------------------------------------------
# Unified pipeline
# ---------------------------------------------------------------------------

class TestUnifiedPipeline:
    def test_rule_based_triage(self):
        email = make_email(
            subject="Invoice #789 Past Due",
            sender="billing@halliburton.com",
        )
        result = triage_email(email)
        assert result.category == EmailCategory.VENDOR_AP

    def test_deal_signals_added_to_result(self):
        email = make_email(
            subject="RE: Loving County Acquisition",
            body_text="Please find our letter of intent attached.",
        )
        result = triage_email(email)
        assert result.category == EmailCategory.DEAL_RELATED
        assert any(s.signal_type == DealSignalType.LOI_DISCUSSION for s in result.deal_signals)

    def test_ai_overrides_low_confidence_rules(self):
        email = make_email(subject="FYI", sender="someone@company.com")
        ai_resp = {
            "category": "deal_related",
            "urgency": 2,
            "confidence": 0.90,
            "summary": "Broker presenting new deal",
            "deal_signals": [],
            "recommended_actions": ["flag_for_review"],
            "reasoning": "test",
        }
        result = triage_email(email, ai_response=ai_resp)
        assert result.category == EmailCategory.DEAL_RELATED

    def test_receipt_routing_to_pillar4(self):
        email = make_email(
            subject="Your Uber receipt",
            has_attachments=True,
            attachment_names=["receipt_uber.pdf"],
        )
        result = triage_email(email)
        assert "pillar4:/api/expenses/attach-receipt" in result.routing

    def test_completely_unknown(self):
        email = make_email(
            subject="Hey",
            sender="friend@gmail.com",
            body_text="Want to grab coffee?",
        )
        result = triage_email(email)
        assert result.category == EmailCategory.UNKNOWN
