"""Helpers for meeting and calendar-oriented email assistance."""

from __future__ import annotations

import re
from typing import Any

from .models import EmailCategory, EmailMessage, TriageResult


MEETING_KEYWORDS = re.compile(
    r"(?i)\b(meet|meeting|calendar|invite|rsvp|schedule|availability|reschedul|call|zoom|teams|connect|get together)\b"
)
SCHEDULING_REQUEST_KEYWORDS = re.compile(
    r"(?i)\b("
    r"can we|could we|would you|are you available|does .* work|let'?s meet|schedule time|find time|"
    r"meet next week|connect next week|jump on a call|grab 15|grab 30|quick call|find a time|"
    r"when are you free|what time works|next monday|next tuesday|next wednesday|next thursday|next friday"
    r")\b"
)
RESCHEDULE_KEYWORDS = re.compile(r"(?i)\b(reschedul|move (this )?meeting|push (this )?back|find another time)\b")
CONFIRM_KEYWORDS = re.compile(r"(?i)\b(confirm|confirmed|works for me|see you then)\b")
TIME_PHRASE_PATTERN = re.compile(
    r"(?i)\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b[^.\n]{0,40}"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b[^.\n]{0,40}"
    r"|\b\d{1,2}:\d{2}\s*(?:am|pm)\b[^.\n]{0,30}"
    r"|\b\d{1,2}\s*(?:am|pm)\b[^.\n]{0,30}"
    r"|\b(?:tomorrow|today|next week|next monday|next tuesday|next wednesday|next thursday|next friday)\b[^.\n]{0,40}"
)


def build_calendar_assistant_prompt(email: EmailMessage, triage: TriageResult | None = None) -> str:
    """Build a structured prompt for meeting-assistant extraction."""
    triage_summary = triage.summary if triage else ""
    triage_category = triage.category.value if triage else "unknown"
    triage_urgency = triage.urgency.name if triage else "STANDARD"

    return f"""You are an executive scheduling assistant for K. McQuire, CEO of Peak 10 Energy.

Analyze this email for meeting and calendar intent. Extract only what is supported by the email.

From: {email.sender_name} <{email.sender}>
To: {", ".join(email.recipients) if email.recipients else "None"}
Subject: {email.subject}
Received: {email.received_at.isoformat()}
Triage category: {triage_category}
Triage urgency: {triage_urgency}
Triage summary: {triage_summary}

Body:
---
{(email.body_text or email.body_preview)[:3000]}
---

Respond in JSON:
{{
  "is_calendar_related": true,
  "meeting_request_type": "new_request|reschedule|confirmation|fyi|unknown",
  "suggested_action": "offer_times|confirm_time|delegate_scheduling|decline|review_manually",
  "summary": "<1-2 sentence summary>",
  "proposed_time_phrases": ["<time phrase>"],
  "attendees_to_consider": ["<email or name>"],
  "draft_reply": {{
    "subject": "<reply subject>",
    "body": "<short scheduling reply>"
  }},
  "confidence": 0.0,
  "reasoning": "<brief explanation>"
}}"""


def assist_calendar_request(
    email: EmailMessage,
    triage: TriageResult | None = None,
    ai_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured meeting-assistant guidance with heuristic fallback."""
    text = " ".join(
        part for part in [email.subject, email.body_text, email.body_preview] if part
    )
    lower_text = text.lower()

    is_calendar_related = bool(MEETING_KEYWORDS.search(text))
    if triage and triage.category == EmailCategory.CALENDAR:
        is_calendar_related = True

    proposed_times = _extract_time_phrases(text)
    attendees = _extract_attendees(email)
    request_type = _infer_meeting_request_type(lower_text, proposed_times)
    if request_type != "unknown":
        is_calendar_related = True
    suggested_action = _infer_suggested_action(request_type, proposed_times)

    result = {
        "is_calendar_related": is_calendar_related,
        "meeting_request_type": request_type,
        "suggested_action": suggested_action,
        "summary": _default_calendar_summary(email, request_type, proposed_times),
        "proposed_time_phrases": proposed_times,
        "attendees_to_consider": attendees,
        "draft_reply": _default_draft_reply(email, request_type, proposed_times),
        "confidence": 0.55 if is_calendar_related else 0.2,
        "reasoning": _default_reasoning(request_type, proposed_times, is_calendar_related),
    }

    if ai_response:
        merged = dict(result)
        for key in [
            "is_calendar_related",
            "meeting_request_type",
            "suggested_action",
            "summary",
            "proposed_time_phrases",
            "attendees_to_consider",
            "draft_reply",
            "confidence",
            "reasoning",
        ]:
            if key in ai_response and ai_response[key] not in (None, ""):
                merged[key] = ai_response[key]
        return merged

    return result


def build_event_draft(
    email: EmailMessage,
    guidance: dict[str, Any],
    *,
    triage: TriageResult | None = None,
) -> dict[str, Any]:
    """Build a structured event draft payload from calendar guidance."""
    proposed_times = []
    for value in guidance.get("proposed_time_phrases", []):
        cleaned = _clean_time_phrase(str(value))
        if cleaned and cleaned not in proposed_times:
            proposed_times.append(cleaned)
    attendees = [
        str(value).strip()
        for value in guidance.get("attendees_to_consider", [])
        if str(value).strip()
    ]
    if email.sender and email.sender not in attendees:
        attendees.insert(0, email.sender)

    title = _event_title(email.subject)
    meeting_format = _infer_meeting_format(email)
    duration_minutes = _suggest_duration_minutes(email, guidance, triage)
    confidence = float(guidance.get("confidence", 0.0) or 0.0)
    summary = str(guidance.get("summary", "")).strip()

    return {
        "title": title,
        "attendees": attendees[:8],
        "candidate_time_phrases": proposed_times[:5],
        "duration_minutes": duration_minutes,
        "meeting_format": meeting_format,
        "location_hint": _location_hint(meeting_format),
        "summary": summary,
        "description": _build_event_description(email, guidance, triage),
        "source_message_id": email.message_id,
        "source_subject": email.subject,
        "suggested_action": str(guidance.get("suggested_action", "")).strip(),
        "needs_review": True,
        "confidence": confidence,
        "review_notes": _review_notes(guidance, proposed_times),
    }


def _extract_time_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    for match in TIME_PHRASE_PATTERN.finditer(text):
        phrase = _clean_time_phrase(match.group(0))
        if phrase and phrase not in phrases:
            phrases.append(phrase[:80])
    return phrases[:5]


def _extract_attendees(email: EmailMessage) -> list[str]:
    attendees: list[str] = []
    for candidate in [email.sender, *email.recipients]:
        candidate = candidate.strip()
        if candidate and candidate not in attendees:
            attendees.append(candidate)
    return attendees[:8]


def _infer_meeting_request_type(text: str, proposed_times: list[str]) -> str:
    if RESCHEDULE_KEYWORDS.search(text):
        return "reschedule"
    if CONFIRM_KEYWORDS.search(text) and proposed_times:
        return "confirmation"
    if SCHEDULING_REQUEST_KEYWORDS.search(text) or (proposed_times and MEETING_KEYWORDS.search(text)):
        return "new_request"
    return "unknown"


def _infer_suggested_action(request_type: str, proposed_times: list[str]) -> str:
    if request_type == "confirmation":
        return "confirm_time"
    if request_type == "reschedule":
        return "offer_times"
    if request_type == "new_request" and _has_concrete_time_slot(proposed_times):
        return "confirm_time"
    if request_type == "new_request":
        return "offer_times"
    return "review_manually"


def _default_calendar_summary(
    email: EmailMessage,
    request_type: str,
    proposed_times: list[str],
) -> str:
    if request_type == "reschedule":
        return "The email appears to request moving an existing meeting to a different time."
    if request_type == "confirmation":
        return "The email looks like a scheduling confirmation with a proposed meeting time."
    if request_type == "new_request" and proposed_times:
        return f"The sender appears to be requesting a meeting and mentioned {proposed_times[0]}."
    if request_type == "new_request":
        return "The sender appears to be asking to schedule time but did not provide a clear confirmed slot."
    if proposed_times:
        return f"The email references {proposed_times[0]}, but the scheduling intent still needs confirmation."
    return f"The email may be calendar-related, but the scheduling intent in '{email.subject}' needs review."


def _default_draft_reply(
    email: EmailMessage,
    request_type: str,
    proposed_times: list[str],
) -> dict[str, str]:
    has_concrete_time_slot = _has_concrete_time_slot(proposed_times)
    if request_type == "confirmation" and proposed_times:
        body = f"Thanks. {proposed_times[0]} works on my end. Please send the invite and I will watch for it."
    elif request_type == "reschedule":
        body = (
            "Thanks for the update. Please send a couple of alternate times that work, "
            "and we will confirm the best option."
        )
    elif request_type == "new_request" and has_concrete_time_slot:
        body = f"Thanks for reaching out. {proposed_times[0]} could work. Please send the invite and we will confirm."
    else:
        body = (
            "Thanks for reaching out. Please send a few time options that work for you, "
            "and we will coordinate from there."
        )

    return {"subject": f"Re: {email.subject}", "body": body}


def _default_reasoning(
    request_type: str,
    proposed_times: list[str],
    is_calendar_related: bool,
) -> str:
    if not is_calendar_related:
        return "No strong scheduling keywords or triage signals were detected."
    if request_type == "reschedule":
        return "Rescheduling language was detected in the email content."
    if request_type == "confirmation":
        return "Confirmation language and a candidate time phrase were detected."
    if proposed_times:
        return "Scheduling language and candidate time phrases were detected."
    return "Calendar-related keywords were detected, but the next step still needs manual review."


def _event_title(subject: str) -> str:
    cleaned = re.sub(r"(?i)^\s*(re|fw|fwd)\s*:\s*", "", subject or "").strip()
    return cleaned or "Scheduling follow-up"


def _infer_meeting_format(email: EmailMessage) -> str:
    text = " ".join(part for part in [email.subject, email.body_text, email.body_preview] if part).lower()
    if "teams" in text:
        return "teams"
    if "zoom" in text:
        return "zoom"
    if "phone" in text or "call" in text:
        return "phone"
    if "office" in text or "conference room" in text or "in person" in text:
        return "in_person"
    return "unspecified"


def _location_hint(meeting_format: str) -> str:
    hints = {
        "teams": "Microsoft Teams",
        "zoom": "Zoom",
        "phone": "Phone call",
        "in_person": "In person",
        "unspecified": "TBD",
    }
    return hints.get(meeting_format, "TBD")


def _suggest_duration_minutes(
    email: EmailMessage,
    guidance: dict[str, Any],
    triage: TriageResult | None = None,
) -> int:
    text = " ".join(part for part in [email.subject, email.body_text, email.body_preview] if part).lower()
    if "15 min" in text or "15-minute" in text or "quick" in text:
        return 15
    if "45 min" in text or "45-minute" in text:
        return 45
    if "hour" in text or "60 min" in text or "60-minute" in text:
        return 60
    if triage and triage.urgency.name == "HIGH_PRIORITY":
        return 30
    if guidance.get("meeting_request_type") == "confirmation":
        return 30
    return 30


def _build_event_description(
    email: EmailMessage,
    guidance: dict[str, Any],
    triage: TriageResult | None = None,
) -> str:
    lines = [
        f"Source email: {email.subject or 'Untitled'}",
        f"From: {email.sender_name or email.sender or 'Unknown sender'}",
    ]
    summary = str(guidance.get("summary", "")).strip()
    if summary:
        lines.append(f"Summary: {summary}")
    if triage and triage.summary:
        lines.append(f"Triage: {triage.summary}")
    if guidance.get("draft_reply", {}).get("body"):
        lines.append("Suggested reply:")
        lines.append(str(guidance["draft_reply"]["body"]).strip())
    return "\n".join(lines)


def _review_notes(guidance: dict[str, Any], proposed_times: list[str]) -> list[str]:
    notes: list[str] = []
    if not proposed_times:
        notes.append("No concrete time was parsed; choose or request a slot before creating the event.")
    if guidance.get("suggested_action") == "offer_times":
        notes.append("Offer alternate times before converting this into a live event.")
    if guidance.get("meeting_request_type") == "reschedule":
        notes.append("This looks like a reschedule; verify the prior event before sending a replacement.")
    return notes


def _clean_time_phrase(value: str) -> str:
    phrase = " ".join((value or "").split()).strip()
    if not phrase:
        return ""
    phrase = re.split(r"[?!.\n]", phrase, maxsplit=1)[0].strip(" ,;:-")
    phrase = re.sub(r"(?i)\b(works?|for|could|would|please|thanks)\b.*$", "", phrase).strip(" ,;:-")
    return phrase


def _has_concrete_time_slot(proposed_times: list[str]) -> bool:
    for phrase in proposed_times:
        candidate = (phrase or "").strip().lower()
        if not candidate:
            continue
        if re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", candidate):
            return True
        if re.search(r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b", candidate):
            return True
        if re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b", candidate):
            return True
    return False
