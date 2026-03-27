"""Tests for calendar and meeting-assistant helpers."""

from __future__ import annotations

from email_intel.calendar import assist_calendar_request, build_calendar_assistant_prompt
from email_intel.models import EmailCategory, EmailMessage, TriageResult, UrgencyTier


def test_assist_calendar_request_extracts_time_phrases_and_action():
    email = EmailMessage(
        subject="Can we meet next Tuesday at 2 pm?",
        sender="counterparty@example.com",
        recipients=["automation@peak10.test"],
        body_text="Would next Tuesday at 2 pm work for a quick Zoom to discuss the package?",
    )
    triage = TriageResult(
        message_id=email.message_id,
        category=EmailCategory.CALENDAR,
        urgency=UrgencyTier.STANDARD,
        confidence=0.88,
    )

    guidance = assist_calendar_request(email, triage=triage)

    assert guidance["is_calendar_related"] is True
    assert guidance["meeting_request_type"] == "new_request"
    assert guidance["suggested_action"] == "confirm_time"
    assert any("Tuesday" in phrase for phrase in guidance["proposed_time_phrases"])
    assert guidance["draft_reply"]["subject"] == "Re: Can we meet next Tuesday at 2 pm?"


def test_assist_calendar_request_prefers_ai_response_when_present():
    email = EmailMessage(
        subject="Meeting request",
        sender="counterparty@example.com",
        body_text="Can you do tomorrow afternoon?",
    )

    guidance = assist_calendar_request(
        email,
        ai_response={
            "is_calendar_related": True,
            "meeting_request_type": "reschedule",
            "suggested_action": "offer_times",
            "summary": "The sender needs to move the meeting.",
            "proposed_time_phrases": ["tomorrow afternoon"],
            "attendees_to_consider": ["counterparty@example.com"],
            "draft_reply": {
                "subject": "Re: Meeting request",
                "body": "Happy to reschedule. Please send a few alternate times.",
            },
            "confidence": 0.93,
            "reasoning": "AI found explicit rescheduling language.",
        },
    )

    assert guidance["meeting_request_type"] == "reschedule"
    assert guidance["summary"] == "The sender needs to move the meeting."
    assert guidance["confidence"] == 0.93


def test_assist_calendar_request_detects_soft_scheduling_language():
    email = EmailMessage(
        subject="Let us connect next week",
        sender="partner@example.com",
        body_text="Could we connect next week to review the revised numbers and find a time that works?",
    )

    guidance = assist_calendar_request(email)

    assert guidance["is_calendar_related"] is True
    assert guidance["meeting_request_type"] == "new_request"
    assert guidance["suggested_action"] == "offer_times"
    assert "Please send a few time options" in guidance["draft_reply"]["body"]


def test_assist_calendar_request_uses_meeting_keywords_with_proposed_time():
    email = EmailMessage(
        subject="Quick call next Thursday",
        sender="partner@example.com",
        body_text="I have next Thursday at 11 am open if you want to jump on a call.",
    )

    guidance = assist_calendar_request(email)

    assert guidance["meeting_request_type"] == "new_request"
    assert any("next Thursday at 11 am" in phrase for phrase in guidance["proposed_time_phrases"])


def test_build_calendar_assistant_prompt_includes_triage_context():
    email = EmailMessage(
        subject="Board meeting invite",
        sender="board@example.com",
        body_text="Please join us Friday at 10 am.",
    )
    triage = TriageResult(
        message_id=email.message_id,
        category=EmailCategory.CALENDAR,
        urgency=UrgencyTier.HIGH,
        confidence=0.9,
        summary="Board scheduling request.",
    )

    prompt = build_calendar_assistant_prompt(email, triage)

    assert "Triage category: calendar" in prompt
    assert "Triage urgency: HIGH" in prompt
    assert "Board scheduling request." in prompt
