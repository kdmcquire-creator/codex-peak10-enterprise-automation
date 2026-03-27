"""Relationship and intent-oriented growth insights for Pillar 2."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any


INTENT_PATTERNS = [
    {
        "type": "hesitation_signal",
        "keywords": ["delay", "pause", "hold off", "not ready", "later", "timing"],
        "implication": "the thread may be losing momentum or facing internal hesitation",
        "suggested_action": "reach out with a lower-friction next step or a specific follow-up date",
    },
    {
        "type": "budget_signal",
        "keywords": ["budget", "cost", "pricing", "price", "expensive"],
        "implication": "budget sensitivity or scope pressure may be developing",
        "suggested_action": "clarify constraints early and offer a narrower or phased option",
    },
    {
        "type": "opportunity_signal",
        "keywords": ["available", "opportunity", "interested", "package", "intro", "introduce"],
        "implication": "there may be an opening for a proactive reach-out",
        "suggested_action": "follow up while the context is fresh and suggest a concrete next step",
    },
]


def build_growth_nudges(
    triage_results: list[dict[str, Any]],
    *,
    drafts: list[dict[str, Any]] | None = None,
    draft_count: int = 0,
    document_count: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Summarize recent activity and return bucketed nudges."""
    current_time = now or datetime.now(timezone.utc)
    drafts = drafts or []

    category_counts = Counter(
        str(item.get("category", "unknown")) or "unknown"
        for item in triage_results
    )
    urgency_counts = Counter(int(item.get("urgency", 3) or 3) for item in triage_results)

    buckets = {
        "relationship_drift": _build_relationship_drift_nudges(triage_results, current_time),
        "awaiting_response": _build_awaiting_response_nudges(triage_results, drafts, current_time),
        "intent_signal": _build_intent_signal_nudges(triage_results),
        "coordination": _build_coordination_nudges(
            triage_results,
            draft_count=draft_count,
            document_count=document_count,
        ),
    }

    flat_nudges = [
        nudge
        for bucket_name in buckets
        for nudge in buckets[bucket_name]
    ]

    return {
        "counts": {
            "total_messages": len(triage_results),
            "by_category": dict(category_counts),
            "by_urgency": {str(key): value for key, value in sorted(urgency_counts.items())},
            "draft_count": draft_count,
            "document_count": document_count,
        },
        "buckets": buckets,
        "nudges": flat_nudges,
    }


def _build_relationship_drift_nudges(
    triage_results: list[dict[str, Any]],
    current_time: datetime,
) -> list[dict[str, Any]]:
    contacts: dict[str, list[datetime]] = defaultdict(list)
    subjects: dict[str, str] = {}
    latest_items: dict[str, dict[str, Any]] = {}

    for item in triage_results:
        sender = _get_sender(item)
        timestamp = _get_timestamp(item)
        if not sender or not timestamp:
            continue
        contacts[sender].append(timestamp)
        subjects[sender] = _get_subject(item)
        existing = latest_items.get(sender)
        if existing is None or (_get_timestamp(existing) or datetime.min.replace(tzinfo=timezone.utc)) < timestamp:
            latest_items[sender] = item

    nudges: list[dict[str, Any]] = []
    for sender, timestamps in contacts.items():
        timestamps = sorted(timestamps)
        if len(timestamps) < 3:
            continue

        last_seen = timestamps[-1]
        cadence_days = _average_gap_days(timestamps)
        overdue_threshold = max(21, int(round(cadence_days * 1.75)) if cadence_days else 21)
        days_since_last = (current_time - last_seen).days
        if days_since_last < overdue_threshold:
            continue
        latest_item = latest_items.get(sender, {})

        nudges.append(
            {
                "type": "relationship_drift",
                "priority": "medium",
                "title": f"{sender} has gone quiet",
                "message": (
                    f"{sender} has shown up {len(timestamps)} times in recent history, "
                    f"but it has been {days_since_last} days since the last note."
                ),
                "why": (
                    f"The last recent message was '{subjects.get(sender, 'recent email')}', "
                    "and the gap is longer than their normal cadence."
                ),
                "could_mean": "the relationship is cooling off, waiting on you, or simply slipping off the radar",
                "suggested_action": "Consider a short proactive check-in or a specific follow-up question.",
                "contact": sender,
                "thread_key": _get_conversation_key(latest_item),
                "source_message_id": _get_message_id(latest_item),
                "source_subject": _get_subject(latest_item),
                "days_since_last_contact": days_since_last,
            }
        )

    nudges.sort(key=lambda item: item["days_since_last_contact"], reverse=True)
    return nudges[:3]


def _build_awaiting_response_nudges(
    triage_results: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
    current_time: datetime,
) -> list[dict[str, Any]]:
    latest_inbound_by_sender: dict[str, datetime] = {}
    for item in triage_results:
        sender = _get_sender(item).lower()
        timestamp = _get_timestamp(item)
        if sender and timestamp:
            latest_inbound_by_sender[sender] = max(
                latest_inbound_by_sender.get(sender, timestamp),
                timestamp,
            )

    nudges: list[dict[str, Any]] = []
    for draft in drafts:
        if not draft.get("sent") or not draft.get("sent_at"):
            continue
        sent_at = _parse_iso_datetime(str(draft.get("sent_at")))
        if sent_at is None:
            continue
        age_days = (current_time - sent_at).days
        if age_days < 3:
            continue

        recipients = _normalize_recipients(draft.get("to_recipients", []))
        if not recipients:
            continue

        if any(
            latest_inbound_by_sender.get(recipient, datetime.min.replace(tzinfo=timezone.utc)) > sent_at
            for recipient in recipients
        ):
            continue

        primary_recipient = recipients[0]
        nudges.append(
            {
                "type": "awaiting_response",
                "priority": "medium",
                "title": f"No reply yet from {primary_recipient}",
                "message": (
                    f"A sent reply to {primary_recipient} is now {age_days} days old with no newer inbound response detected."
                ),
                "why": f"The sent message subject was '{draft.get('subject', 'Re: follow-up')}'.",
                "could_mean": "the thread stalled, got buried, or needs a clearer next ask",
                "suggested_action": "Decide whether to send a polite bump or change the ask to something easier to answer.",
                "recipient": primary_recipient,
                "source_message_id": str(draft.get("message_id", "")),
                "source_subject": str(draft.get("subject", "")),
                "days_waiting": age_days,
            }
        )

    nudges.sort(key=lambda item: item["days_waiting"], reverse=True)
    return nudges[:3]


def _build_intent_signal_nudges(triage_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nudges: list[dict[str, Any]] = []

    for item in triage_results:
        combined_text = " ".join(
            part
            for part in [
                _get_subject(item),
                str(item.get("summary", "")),
                str(item.get("reasoning", "")),
            ]
            if part
        )
        lower_text = combined_text.lower()

        for pattern in INTENT_PATTERNS:
            matched_keyword = next(
                (keyword for keyword in pattern["keywords"] if keyword in lower_text),
                None,
            )
            if not matched_keyword:
                continue

            subject = _get_subject(item) or "recent email"
            nudges.append(
                {
                    "type": pattern["type"],
                    "priority": "medium",
                    "title": f"Possible signal in '{subject}'",
                    "message": (
                        f"Because '{matched_keyword}' showed up in '{subject}', "
                        f"which could mean {pattern['implication']}, you could then {pattern['suggested_action']}."
                    ),
                    "why": f"Matched keyword: {matched_keyword}",
                    "could_mean": pattern["implication"],
                    "suggested_action": pattern["suggested_action"].capitalize() + ".",
                    "subject": subject,
                    "evidence": matched_keyword,
                    "contact": _get_sender(item),
                    "thread_key": _get_conversation_key(item),
                    "source_message_id": _get_message_id(item),
                    "source_subject": subject,
                }
            )
            break

    return nudges[:4]


def _build_coordination_nudges(
    triage_results: list[dict[str, Any]],
    *,
    draft_count: int,
    document_count: int,
) -> list[dict[str, Any]]:
    category_counts = Counter(
        str(item.get("category", "unknown")) or "unknown"
        for item in triage_results
    )
    latest_by_category: dict[str, dict[str, Any]] = {}
    for item in triage_results:
        category = str(item.get("category", "unknown")) or "unknown"
        existing = latest_by_category.get(category)
        item_timestamp = _get_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc)
        existing_timestamp = _get_timestamp(existing) or datetime.min.replace(tzinfo=timezone.utc) if existing else datetime.min.replace(tzinfo=timezone.utc)
        if existing is None or item_timestamp >= existing_timestamp:
            latest_by_category[category] = item

    nudges: list[dict[str, Any]] = []

    if category_counts.get("calendar", 0) >= 1:
        latest_calendar = latest_by_category.get("calendar", {})
        calendar_count = category_counts["calendar"]
        nudges.append(
            {
                "type": "calendar_load" if calendar_count >= 2 else "calendar_follow_up",
                "priority": "low" if calendar_count >= 2 else "medium",
                "title": (
                    "Scheduling traffic is clustering"
                    if calendar_count >= 2
                    else "Scheduling thread needs a decision"
                ),
                "message": (
                    f"{calendar_count} calendar-related messages appeared in this slice. "
                    "Bundling scheduling decisions could reduce back-and-forth."
                    if calendar_count >= 2
                    else "A recent scheduling email still needs a decision on time, response, or event creation."
                ),
                "suggested_action": (
                    "Run calendar assist on the newest scheduling threads."
                    if calendar_count >= 2
                    else "Review the newest scheduling request and draft an event or reply."
                ),
                "contact": _get_sender(latest_calendar),
                "thread_key": _get_conversation_key(latest_calendar),
                "source_message_id": _get_message_id(latest_calendar),
                "source_subject": _get_subject(latest_calendar),
            }
        )

    if category_counts.get("unknown", 0) >= 2:
        latest_unknown = latest_by_category.get("unknown", {})
        nudges.append(
            {
                "type": "manual_review",
                "priority": "low",
                "title": "Ambiguous inbox items are accumulating",
                "message": (
                    f"{category_counts['unknown']} message(s) still landed as unknown, "
                    "so there may be hidden intent worth sorting manually."
                ),
                "suggested_action": "Review unknown items and tune routing where needed.",
                "contact": _get_sender(latest_unknown),
                "thread_key": _get_conversation_key(latest_unknown),
                "source_message_id": _get_message_id(latest_unknown),
                "source_subject": _get_subject(latest_unknown),
            }
        )

    if draft_count >= 2:
        nudges.append(
            {
                "type": "reply_backlog",
                "priority": "low",
                "title": "Reply backlog forming",
                "message": (
                    f"{draft_count} draft reply record(s) are stored right now. "
                    "A quick review cycle could close loops faster."
                ),
                "suggested_action": "Review draft replies and either send, revise, or discard them.",
            }
        )

    if document_count >= 3:
        nudges.append(
            {
                "type": "document_follow_through",
                "priority": "low",
                "title": "Document activity may need follow-through",
                "message": (
                    f"{document_count} document classification record(s) are stored. "
                    "There may be follow-up decisions hiding behind recently filed material."
                ),
                "suggested_action": "Check recently filed and staged documents for next actions.",
            }
        )

    return nudges


def _get_sender(item: dict[str, Any]) -> str:
    email = item.get("email", {})
    if isinstance(email, dict) and email.get("sender"):
        return str(email.get("sender", "")).strip()
    return str(item.get("email_sender", "")).strip()


def _get_message_id(item: dict[str, Any]) -> str:
    email = item.get("email", {})
    if isinstance(email, dict) and email.get("message_id"):
        return str(email.get("message_id", "")).strip()
    return str(item.get("message_id", "")).strip()


def _get_subject(item: dict[str, Any]) -> str:
    email = item.get("email", {})
    if isinstance(email, dict) and email.get("subject"):
        return str(email.get("subject", "")).strip()
    return str(item.get("email_subject", "")).strip()


def _get_conversation_key(item: dict[str, Any]) -> str:
    email = item.get("email", {})
    if isinstance(email, dict) and email.get("conversation_id"):
        return str(email.get("conversation_id", "")).strip()
    if item.get("conversation_id"):
        return str(item.get("conversation_id", "")).strip()
    sender = _get_sender(item)
    subject = _get_subject(item)
    if sender or subject:
        return f"{sender.lower()}::{subject.lower()}".strip(":")
    return ""


def _get_timestamp(item: dict[str, Any]) -> datetime | None:
    email = item.get("email", {})
    if isinstance(email, dict) and email.get("received_at"):
        parsed = _parse_iso_datetime(str(email.get("received_at")))
        if parsed:
            return parsed

    for field in ["received_at", "saved_at"]:
        if item.get(field):
            parsed = _parse_iso_datetime(str(item.get(field)))
            if parsed:
                return parsed
    return None


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _average_gap_days(timestamps: list[datetime]) -> float:
    if len(timestamps) < 2:
        return 0.0
    gaps = [
        max((later - earlier).days, 1)
        for earlier, later in zip(timestamps, timestamps[1:])
    ]
    return mean(gaps) if gaps else 0.0


def _normalize_recipients(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []

    recipients: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        address = value.strip().lower()
        if address and address not in recipients:
            recipients.append(address)
    return recipients
