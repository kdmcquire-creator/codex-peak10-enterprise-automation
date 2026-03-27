"""Morning Brief assembly for Pillar 2."""

from __future__ import annotations

from collections import defaultdict
import hashlib
from datetime import datetime, time, timedelta, timezone
import re
from typing import Any

from email_intel.insights import build_growth_nudges


WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
RESOLVED_HINTS = [
    "resolved",
    "closed",
    "complete",
    "completed",
    "done",
    "all set",
    "no action needed",
]
PROJECT_STOP_WORDS = {
    "a",
    "an",
    "and",
    "follow",
    "for",
    "fw",
    "fwd",
    "in",
    "of",
    "on",
    "re",
    "regarding",
    "the",
    "this",
    "update",
}
GENERIC_ATTACHMENT_TOKENS = {"att", "attachment", "attachments", "doc", "document", "file", "files"}
STRATEGIC_PROJECT_CATEGORIES = {"deal_related", "calendar"}
LOW_SIGNAL_PROJECT_CATEGORIES = {"internal", "unknown"}
BRIEF_ITEM_STATE_LABELS = {
    "open": "Open",
    "resolved": "Resolved",
    "dismissed": "Dismissed",
}
BRIEF_ITEM_REASON_LABELS = {
    "handled_offline": "Handled offline",
    "replied": "Reply drafted or sent",
    "archived": "Archived in mailbox",
    "archive_fallback": "Marked read; archive move failed",
    "source_missing": "Source message no longer in mailbox",
    "delegated": "Delegated elsewhere",
    "no_longer_relevant": "No longer relevant",
    "monitor_only": "Monitor only",
}
CALENDAR_SIGNAL_PATTERN = re.compile(
    r"(?i)\b(meet|meeting|calendar|invite|schedul|availability|reschedul|call|zoom|teams|time option|find time)\b"
)


def build_morning_brief(
    triage_results: list[dict[str, Any]],
    *,
    drafts: list[dict[str, Any]] | None = None,
    calendar_items: list[dict[str, Any]] | None = None,
    personal_priorities: list[dict[str, Any]] | None = None,
    stored_brief_items: list[dict[str, Any]] | None = None,
    draft_count: int = 0,
    document_count: int = 0,
    now: datetime | None = None,
    lookback_days: int = 3,
    carry_over_days: int = 7,
) -> dict[str, Any]:
    """Build a morning brief from recent message activity and optional calendar input."""
    current_time = now or datetime.now(timezone.utc)
    drafts = drafts or []
    calendar_items = calendar_items or []
    personal_priorities = personal_priorities or []
    stored_brief_items = stored_brief_items or []

    insights = build_growth_nudges(
        triage_results,
        drafts=drafts,
        draft_count=draft_count,
        document_count=document_count,
        now=current_time,
    )
    stored_items_by_id = _index_stored_items(stored_brief_items)
    follow_ups = _prepare_brief_items(
        _build_follow_up_items(insights),
        item_kind="follow_up",
        current_time=current_time,
        stored_items_by_id=stored_items_by_id,
        carry_over_days=carry_over_days,
    )
    watchlist = _prepare_brief_items(
        _build_watchlist_items(insights),
        item_kind="watchlist",
        current_time=current_time,
        stored_items_by_id=stored_items_by_id,
        carry_over_days=carry_over_days,
    )
    ongoing_projects = _build_ongoing_projects(
        triage_results,
        drafts=drafts,
        current_time=current_time,
        lookback_days=lookback_days,
    )
    calendar_review = _build_calendar_review(calendar_items, current_time)
    protected_time = _build_protected_time_plan(
        personal_priorities,
        calendar_review=calendar_review,
        current_time=current_time,
        follow_up_count=len(follow_ups),
    )
    focus_blocks = _build_focus_block_suggestions(
        calendar_review=calendar_review,
        follow_up_count=len(follow_ups),
        watchlist_count=len(watchlist),
        protected_time=protected_time,
    )
    relationship_memory = _build_relationship_memory(triage_results, current_time)
    brief_item_records = [
        _serialize_brief_item_for_storage(item, current_time=current_time)
        for item in [*follow_ups, *watchlist]
    ]

    return {
        "brief_date": current_time.date().isoformat(),
        "overview": {
            "ongoing_project_count": len(ongoing_projects),
            "follow_up_count": len(follow_ups),
            "watchlist_count": len(watchlist),
            "carried_over_follow_up_count": sum(1 for item in follow_ups if item.get("carried_over")),
            "carried_over_watchlist_count": sum(1 for item in watchlist if item.get("carried_over")),
            "meeting_count": calendar_review["meeting_count"],
            "protected_time_conflicts": protected_time["conflict_count"],
            "relationship_memory_count": len(relationship_memory),
        },
        "labels": {
            "watchlist": "Watchlist",
            "follow_ups": "Follow-Ups",
        },
        "ongoing_projects": ongoing_projects,
        "follow_ups": follow_ups,
        "watchlist": watchlist,
        "calendar_review": calendar_review,
        "protected_time": protected_time,
        "suggested_focus_blocks": focus_blocks,
        "relationship_memory": relationship_memory,
        "raw_nudges": insights["nudges"],
        "brief_item_records": brief_item_records,
    }


def _build_follow_up_items(insights: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in insights.get("buckets", {}).get("awaiting_response", []):
        items.append(
            {
                "type": item.get("type", "awaiting_response"),
                "title": item.get("title", "Follow-up needed"),
                "message": item.get("message", ""),
                "suggested_action": item.get("suggested_action", ""),
                "contact": item.get("contact", ""),
                "recipient": item.get("recipient", ""),
                "thread_key": item.get("thread_key", ""),
                "priority": item.get("priority", "medium"),
                "source_bucket": "awaiting_response",
                **_brief_source_fields(item),
            }
        )

    for item in insights.get("buckets", {}).get("relationship_drift", []):
        items.append(
            {
                "type": item.get("type", "relationship_drift"),
                "title": item.get("title", "Relationship drift"),
                "message": item.get("message", ""),
                "suggested_action": item.get("suggested_action", ""),
                "contact": item.get("contact", ""),
                "recipient": item.get("recipient", ""),
                "thread_key": item.get("thread_key", ""),
                "priority": item.get("priority", "medium"),
                "source_bucket": "relationship_drift",
                "could_mean": item.get("could_mean", ""),
                **_brief_source_fields(item),
            }
        )

    for item in insights.get("buckets", {}).get("coordination", []):
        if item.get("type") not in {"reply_backlog", "manual_review", "calendar_load", "calendar_follow_up"}:
            continue
        items.append(
            {
                "type": item.get("type", "coordination"),
                "title": item.get("title", "Coordination follow-up"),
                "message": item.get("message", ""),
                "suggested_action": item.get("suggested_action", ""),
                "contact": item.get("contact", ""),
                "recipient": item.get("recipient", ""),
                "thread_key": item.get("thread_key", ""),
                "priority": item.get("priority", "low"),
                "source_bucket": "coordination",
                **_brief_source_fields(item),
            }
        )

    priority_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: (priority_order.get(str(item.get("priority")), 9), item["title"]))
    return items


def _build_watchlist_items(insights: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in insights.get("buckets", {}).get("intent_signal", []):
        items.append(
            {
                "type": item.get("type", "intent_signal"),
                "title": item.get("title", "Signal worth watching"),
                "message": item.get("message", ""),
                "could_mean": item.get("could_mean", ""),
                "suggested_action": item.get("suggested_action", ""),
                "contact": item.get("contact", ""),
                "recipient": item.get("recipient", ""),
                "thread_key": item.get("thread_key", ""),
                "priority": item.get("priority", "medium"),
                "source_bucket": "intent_signal",
                **_brief_source_fields(item),
            }
        )
    return items


def _brief_source_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_message_id": item.get("source_message_id", ""),
        "source_subject": item.get("source_subject", ""),
        "source_sender": item.get("contact", "") or item.get("source_sender", ""),
    }


def build_brief_item_id(item_kind: str, item: dict[str, Any]) -> str:
    fingerprint_parts = [
        item_kind,
        str(item.get("type", "")),
        str(item.get("title", "")),
        str(item.get("message", "")),
        str(item.get("suggested_action", "")),
        str(item.get("contact", "")),
        str(item.get("recipient", "")),
        str(item.get("thread_key", "")),
    ]
    fingerprint = "|".join(part.strip().lower() for part in fingerprint_parts)
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:20]


def _prepare_brief_items(
    current_items: list[dict[str, Any]],
    *,
    item_kind: str,
    current_time: datetime,
    stored_items_by_id: dict[str, dict[str, Any]],
    carry_over_days: int,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    current_ids: set[str] = set()

    for item in current_items:
        item_id = build_brief_item_id(item_kind, item)
        current_ids.add(item_id)
        existing = stored_items_by_id.get(item_id, {})
        state = str(existing.get("state", "open") or "open")
        if state in {"resolved", "dismissed"}:
            continue

        prepared.append(
            _decorate_brief_item(
                {
                    **item,
                    "item_id": item_id,
                    "item_kind": item_kind,
                    "state": "open",
                    "carried_over": False,
                    "first_seen_at": str(existing.get("first_seen_at") or current_time.isoformat()),
                    "last_seen_at": current_time.isoformat(),
                    "last_brief_date": current_time.date().isoformat(),
                }
            )
        )

    carry_over_cutoff = current_time - timedelta(days=carry_over_days)
    for item_id, stored in stored_items_by_id.items():
        if stored.get("item_kind") != item_kind or item_id in current_ids:
            continue
        if str(stored.get("state", "open") or "open") != "open":
            continue

        last_seen = _parse_iso_datetime(str(stored.get("last_seen_at", "")))
        if last_seen is None or last_seen < carry_over_cutoff:
            continue

        prepared.append(
            _decorate_brief_item(
                {
                    "item_id": item_id,
                    "item_kind": item_kind,
                    "type": str(stored.get("type", "")),
                    "title": str(stored.get("title", "")),
                    "message": str(stored.get("message", "")),
                    "suggested_action": str(stored.get("suggested_action", "")),
                    "priority": str(stored.get("priority", "medium")),
                    "source_bucket": str(stored.get("source_bucket", "")),
                    "could_mean": str(stored.get("could_mean", "")),
                    "contact": str(stored.get("contact", "")),
                    "recipient": str(stored.get("recipient", "")),
                    "thread_key": str(stored.get("thread_key", "")),
                    "source_message_id": str(stored.get("source_message_id", "")),
                    "source_subject": str(stored.get("source_subject", "")),
                    "source_sender": str(stored.get("source_sender", "")),
                    "state": "open",
                    "carried_over": True,
                    "first_seen_at": str(stored.get("first_seen_at") or last_seen.isoformat()),
                    "last_seen_at": str(stored.get("last_seen_at") or last_seen.isoformat()),
                    "last_brief_date": current_time.date().isoformat(),
                }
            )
        )

    priority_order = {"high": 0, "medium": 1, "low": 2}
    prepared.sort(
        key=lambda item: (
            priority_order.get(str(item.get("priority")), 9),
            0 if item.get("carried_over") else 1,
            str(item.get("title", "")),
        )
    )
    return prepared


def _serialize_brief_item_for_storage(item: dict[str, Any], *, current_time: datetime) -> dict[str, Any]:
    return {
        "id": item["item_id"],
        "item_id": item["item_id"],
        "item_kind": item["item_kind"],
        "type": item.get("type", ""),
        "title": item.get("title", ""),
        "message": item.get("message", ""),
        "suggested_action": item.get("suggested_action", ""),
        "priority": item.get("priority", "medium"),
        "source_bucket": item.get("source_bucket", ""),
        "could_mean": item.get("could_mean", ""),
        "contact": item.get("contact", ""),
        "recipient": item.get("recipient", ""),
        "thread_key": item.get("thread_key", ""),
        "source_message_id": item.get("source_message_id", ""),
        "source_subject": item.get("source_subject", ""),
        "source_sender": item.get("source_sender", ""),
        "state": item.get("state", "open"),
        "first_seen_at": item.get("first_seen_at", current_time.isoformat()),
        "last_seen_at": item.get("last_seen_at", current_time.isoformat()),
        "last_brief_date": item.get("last_brief_date", current_time.date().isoformat()),
        "carried_over": bool(item.get("carried_over", False)),
        "updated_at": current_time.isoformat(),
    }


def present_brief_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return a UI-friendly representation of a brief item without mutating the original."""
    return _decorate_brief_item(dict(item))


def _decorate_brief_item(item: dict[str, Any]) -> dict[str, Any]:
    state = str(item.get("state", "open") or "open").lower()
    if state not in BRIEF_ITEM_STATE_LABELS:
        state = "open"

    item["carried_over"] = bool(item.get("carried_over")) or _infer_carry_over(item)
    item["state"] = state
    item["state_label"] = BRIEF_ITEM_STATE_LABELS[state]
    item["ui_section"] = "follow_ups" if item.get("item_kind") == "follow_up" else "watchlist"
    item["is_actionable"] = state == "open"
    item["has_context"] = bool(
        item.get("source_message_id")
        or item.get("thread_key")
        or item.get("contact")
        or item.get("recipient")
    )
    item["carry_over_days"] = _compute_carry_over_days(item)
    item["carry_over_label"] = (
        f"Carried {item['carry_over_days']}d"
        if item.get("carried_over") and item["carry_over_days"] > 0
        else ""
    )
    item["available_actions"] = (
        [
            {"action": "resolve", "label": "Resolve"},
            {"action": "dismiss", "label": "Dismiss"},
        ]
        if state == "open"
        else [{"action": "open", "label": "Reopen"}]
    )
    item["available_quick_actions"] = (
        _build_quick_actions(item)
        if state == "open" and item.get("has_context")
        else []
    )
    item["reason_code"] = str(item.get("reason_code", "")).strip().lower()
    item["reason_label"] = BRIEF_ITEM_REASON_LABELS.get(item["reason_code"], "")
    item["reason_detail"] = str(item.get("reason_detail", "")).strip()
    return item


def _build_quick_actions(item: dict[str, Any]) -> list[dict[str, str]]:
    actions = [
        {"action": "archive", "label": "Archive"},
        {"action": "mark_read", "label": "Mark read"},
        {"action": "generate_reply_draft", "label": "Draft reply"},
    ]
    if _supports_event_draft(item):
        actions.append({"action": "generate_event_draft", "label": "Draft event"})
    return actions


def _supports_event_draft(item: dict[str, Any]) -> bool:
    item_type = str(item.get("type", "")).strip().lower()
    source_bucket = str(item.get("source_bucket", "")).strip().lower()
    if item_type.startswith("calendar") or source_bucket == "calendar":
        return True
    signal_text = " ".join(
        str(item.get(key, "") or "").strip()
        for key in ("title", "message", "suggested_action", "source_subject", "source_bucket", "type")
    )
    return bool(CALENDAR_SIGNAL_PATTERN.search(signal_text))


def _compute_carry_over_days(item: dict[str, Any]) -> int:
    if not item.get("carried_over"):
        return 0

    first_seen = _parse_iso_datetime(str(item.get("first_seen_at", "")))
    last_seen = _parse_iso_datetime(str(item.get("last_seen_at", "")))
    if first_seen is None or last_seen is None:
        return 1
    return max(1, (last_seen.date() - first_seen.date()).days + 1)


def _infer_carry_over(item: dict[str, Any]) -> bool:
    first_seen = _parse_iso_datetime(str(item.get("first_seen_at", "")))
    last_seen = _parse_iso_datetime(str(item.get("last_seen_at", "")))
    if first_seen is None or last_seen is None:
        return False
    return last_seen.date() > first_seen.date()


def _index_stored_items(stored_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in stored_items:
        item_id = str(item.get("item_id") or item.get("id") or "").strip()
        if item_id:
            indexed[item_id] = item
    return indexed


def _build_ongoing_projects(
    triage_results: list[dict[str, Any]],
    *,
    drafts: list[dict[str, Any]],
    current_time: datetime,
    lookback_days: int,
) -> list[dict[str, Any]]:
    window_start = current_time - timedelta(days=lookback_days)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in triage_results:
        timestamp = _get_timestamp(item)
        if timestamp is None or timestamp < window_start:
            continue

        key = _get_project_group_key(item)
        grouped[key].append(item)

    projects: list[dict[str, Any]] = []
    for items in _merge_project_groups(grouped.values()):
        ordered = sorted(
            items,
            key=lambda item: _get_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        latest = ordered[0]
        if _looks_resolved(latest):
            continue

        latest_timestamp = _get_timestamp(latest)
        subject = _get_subject(latest) or "Recent thread"
        sender = _get_sender(latest)
        categories = sorted(
            {
                str(item.get("category", "unknown")) or "unknown"
                for item in ordered
            }
        )
        highest_urgency = min(int(item.get("urgency", 5) or 5) for item in ordered)
        sent_follow_up = _find_sent_follow_up(drafts, sender=sender, after=latest_timestamp)
        message_count = len(ordered)

        if not _is_project_worth_surfacing(
            ordered,
            categories=categories,
            highest_urgency=highest_urgency,
            sent_follow_up=sent_follow_up,
        ):
            continue

        status = "awaiting_reply" if sent_follow_up else "active_thread"
        related_subjects = _collect_related_subjects(ordered)
        projects.append(
            {
                "thread_key": _get_conversation_key(latest),
                "project_key": _get_project_group_key(latest),
                "title": _project_display_title(
                    ordered,
                    sender=sender,
                    categories=categories,
                ),
                "contact": sender,
                "last_activity_at": latest_timestamp.isoformat() if latest_timestamp else "",
                "message_count": message_count,
                "categories": categories,
                "participants": sorted(
                    {
                        participant
                        for participant in [_get_sender(project_item) for project_item in ordered]
                        if participant
                    }
                ),
                "status": status,
                "status_label": "Awaiting reply" if sent_follow_up else "Active thread",
                "latest_direction": _project_latest_direction(
                    latest=latest,
                    categories=categories,
                    sent_follow_up=sent_follow_up,
                ),
                "next_decision": _project_next_decision(
                    categories=categories,
                    sent_follow_up=sent_follow_up,
                    highest_urgency=highest_urgency,
                ),
                "days_active": _project_days_active(ordered),
                "related_subjects": related_subjects,
                "summary": _summarize_project_thread(
                    ordered,
                    latest=latest,
                    categories=categories,
                    sent_follow_up=sent_follow_up,
                ),
                "suggested_action": _project_suggested_action(
                    categories=categories,
                    sent_follow_up=sent_follow_up,
                    highest_urgency=highest_urgency,
                ),
                "contact_memory": _summarize_contact_memory(
                    triage_results,
                    sender=sender,
                    current_time=current_time,
                ),
            }
        )

    projects.sort(
        key=lambda item: (
            0 if item["status"] == "awaiting_reply" else 1,
            -item["message_count"],
            item["title"],
        )
    )
    return projects[:6]


def _build_calendar_review(
    calendar_items: list[dict[str, Any]],
    current_time: datetime,
) -> dict[str, Any]:
    normalized = _normalize_calendar_items(calendar_items)
    tz = normalized[0]["start"].tzinfo if normalized else current_time.tzinfo or timezone.utc
    local_now = current_time.astimezone(tz)
    target_date = local_now.date()
    todays_items = [item for item in normalized if item["start"].date() == target_date]
    todays_items.sort(key=lambda item: item["start"])

    workday_start = datetime.combine(target_date, time(hour=8), tz)
    workday_end = datetime.combine(target_date, time(hour=18), tz)
    open_windows = _find_open_windows(todays_items, workday_start=workday_start, workday_end=workday_end)

    busy_minutes = sum(
        max(int((item["end"] - item["start"]).total_seconds() // 60), 0)
        for item in todays_items
    )
    meeting_count = len(todays_items)
    if meeting_count >= 6 or busy_minutes >= 300:
        load = "heavy"
    elif meeting_count >= 3 or busy_minutes >= 150:
        load = "moderate"
    else:
        load = "light"

    return {
        "date": target_date.isoformat(),
        "meeting_count": meeting_count,
        "busy_minutes": busy_minutes,
        "load": load,
        "meetings": [
            {
                "title": item["title"],
                "start": item["start"].isoformat(),
                "end": item["end"].isoformat(),
                "duration_minutes": int((item["end"] - item["start"]).total_seconds() // 60),
            }
            for item in todays_items
        ],
        "open_windows": open_windows,
    }


def _build_protected_time_plan(
    personal_priorities: list[dict[str, Any]],
    *,
    calendar_review: dict[str, Any],
    current_time: datetime,
    follow_up_count: int,
) -> dict[str, Any]:
    plans: list[dict[str, Any]] = []
    conflicts = 0
    today_code = WEEKDAY_CODES[current_time.weekday()]
    target_date = current_time.date()

    for raw in personal_priorities:
        name = str(raw.get("name", "Personal priority")).strip() or "Personal priority"
        preferred_days = _normalize_preferred_days(raw.get("preferred_days"))
        preferred_window = raw.get("preferred_window", {}) if isinstance(raw.get("preferred_window"), dict) else {}
        start_text = str(preferred_window.get("start") or raw.get("preferred_start") or "12:00")
        end_text = str(preferred_window.get("end") or raw.get("preferred_end") or "")
        duration_minutes = _safe_int(raw.get("duration_minutes"), default=60)

        if preferred_days and today_code not in preferred_days:
            plans.append(
                {
                    "name": name,
                    "status": "not_scheduled_today",
                    "target_days_per_week": _safe_int(raw.get("target_days_per_week"), default=3),
                    "preferred_days": preferred_days,
                }
            )
            continue

        preferred_start = _combine_date_time(target_date, start_text, current_time.tzinfo or timezone.utc)
        if preferred_start is None:
            continue

        if end_text:
            preferred_end = _combine_date_time(target_date, end_text, current_time.tzinfo or timezone.utc)
        else:
            preferred_end = None
        if preferred_end is None or preferred_end <= preferred_start:
            preferred_end = preferred_start + timedelta(minutes=duration_minutes)
        duration_minutes = int((preferred_end - preferred_start).total_seconds() // 60)

        overlapping = [
            item
            for item in calendar_review["meetings"]
            if _ranges_overlap(
                preferred_start,
                preferred_end,
                _parse_iso_datetime(item["start"]) or preferred_start,
                _parse_iso_datetime(item["end"]) or preferred_end,
            )
        ]

        if not overlapping:
            plans.append(
                {
                    "name": name,
                    "status": "clear",
                    "preferred_block": {
                        "start": preferred_start.isoformat(),
                        "end": preferred_end.isoformat(),
                        "duration_minutes": duration_minutes,
                    },
                    "guidance": "This block looks clear right now and is worth protecting.",
                }
            )
            continue

        conflicts += 1
        alternate_windows = _suggest_alternate_windows(
            calendar_review["open_windows"],
            desired_minutes=duration_minutes,
            follow_up_count=follow_up_count,
        )
        plans.append(
            {
                "name": name,
                "status": "conflict",
                "preferred_block": {
                    "start": preferred_start.isoformat(),
                    "end": preferred_end.isoformat(),
                    "duration_minutes": duration_minutes,
                },
                "conflicts": overlapping,
                "alternate_windows": alternate_windows,
                "guidance": _build_protected_time_guidance(
                    name,
                    alternate_windows=alternate_windows,
                    follow_up_count=follow_up_count,
                ),
            }
        )

    return {
        "priorities": plans,
        "conflict_count": conflicts,
    }


def _build_focus_block_suggestions(
    *,
    calendar_review: dict[str, Any],
    follow_up_count: int,
    watchlist_count: int,
    protected_time: dict[str, Any],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    windows = list(calendar_review.get("open_windows", []))

    if follow_up_count:
        follow_up_window = next((window for window in windows if window["duration_minutes"] >= 20), None)
        if follow_up_window:
            suggestions.append(
                {
                    "type": "follow_up_sweep",
                    "title": "Reserve a quick Follow-Ups sweep",
                    "window": follow_up_window,
                    "reason": (
                        f"You have {follow_up_count} carry-over Follow-Ups. "
                        "A short sweep could prevent them from rolling into tomorrow."
                    ),
                }
            )

    if watchlist_count:
        watchlist_window = next((window for window in windows if window["duration_minutes"] >= 15), None)
        if watchlist_window:
            suggestions.append(
                {
                    "type": "watchlist_review",
                    "title": "Reserve a brief Watchlist review",
                    "window": watchlist_window,
                    "reason": (
                        f"There are {watchlist_count} Watchlist item(s) worth a quick judgment pass."
                    ),
                }
            )

    for priority in protected_time.get("priorities", []):
        if priority.get("status") != "conflict":
            continue
        alternate_windows = priority.get("alternate_windows", [])
        if not alternate_windows:
            continue
        suggestions.append(
            {
                "type": "protected_time_recovery",
                "title": f"Protect {priority.get('name', 'personal priority')} another way",
                "window": alternate_windows[0],
                "reason": priority.get("guidance", ""),
            }
        )
        break

    return suggestions[:4]


def _normalize_calendar_items(calendar_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in calendar_items:
        start = _parse_iso_datetime(str(item.get("start", "")))
        end = _parse_iso_datetime(str(item.get("end", "")))
        if start is None or end is None or end <= start:
            continue
        title = str(item.get("title") or item.get("subject") or "Calendar item").strip() or "Calendar item"
        normalized.append({"title": title, "start": start, "end": end})
    normalized.sort(key=lambda entry: entry["start"])
    return normalized


def _find_open_windows(
    items: list[dict[str, Any]],
    *,
    workday_start: datetime,
    workday_end: datetime,
) -> list[dict[str, Any]]:
    open_windows: list[dict[str, Any]] = []
    cursor = workday_start

    for item in items:
        start = max(item["start"], workday_start)
        end = min(item["end"], workday_end)
        if end <= workday_start or start >= workday_end:
            continue
        if start > cursor:
            open_windows.append(_serialize_window(cursor, start))
        cursor = max(cursor, end)

    if cursor < workday_end:
        open_windows.append(_serialize_window(cursor, workday_end))

    return open_windows


def _serialize_window(start: datetime, end: datetime) -> dict[str, Any]:
    duration = max(int((end - start).total_seconds() // 60), 0)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_minutes": duration,
    }


def _suggest_alternate_windows(
    open_windows: list[dict[str, Any]],
    *,
    desired_minutes: int,
    follow_up_count: int,
) -> list[dict[str, Any]]:
    alternates: list[dict[str, Any]] = []
    minimum_partial = 25 if follow_up_count <= 2 else 35

    for window in open_windows:
        duration = int(window.get("duration_minutes", 0) or 0)
        if duration >= desired_minutes or duration >= minimum_partial:
            alternates.append(window)

    return alternates[:3]


def _build_protected_time_guidance(
    name: str,
    *,
    alternate_windows: list[dict[str, Any]],
    follow_up_count: int,
) -> str:
    if not alternate_windows:
        return (
            f"{name} is being squeezed today. Consider moving a lower-leverage meeting or protecting a shorter block."
        )

    first_window = alternate_windows[0]
    if follow_up_count <= 2:
        return (
            f"You seem to have a {first_window['duration_minutes']} minute window from "
            f"{first_window['start']} to {first_window['end']} and do not have a heavy Follow-Ups backlog. "
            "Perhaps shift a lower-leverage response or call and reclaim that time."
        )

    return (
        f"{name} is colliding with the calendar, but there is still a usable recovery window later in the day."
    )


def _find_sent_follow_up(
    drafts: list[dict[str, Any]],
    *,
    sender: str,
    after: datetime | None,
) -> dict[str, Any] | None:
    sender_lower = sender.lower()
    latest_match: tuple[datetime, dict[str, Any]] | None = None

    for draft in drafts:
        if not draft.get("sent") or not draft.get("sent_at"):
            continue
        sent_at = _parse_iso_datetime(str(draft.get("sent_at")))
        if sent_at is None or (after is not None and sent_at < after):
            continue

        recipients = _normalize_recipients(draft.get("to_recipients", []))
        if sender_lower not in recipients:
            continue

        if latest_match is None or sent_at > latest_match[0]:
            latest_match = (sent_at, draft)

    return latest_match[1] if latest_match else None


def _get_conversation_key(item: dict[str, Any]) -> str:
    email = item.get("email", {})
    if isinstance(email, dict) and email.get("conversation_id"):
        return str(email.get("conversation_id"))
    if item.get("conversation_id"):
        return str(item.get("conversation_id"))
    return f"{_get_sender(item).lower()}::{_normalize_subject(_get_subject(item))}"


def _get_project_group_key(item: dict[str, Any]) -> str:
    conversation_key = _get_conversation_key(item)
    if conversation_key and "::" not in conversation_key:
        return conversation_key

    sender = _get_sender(item).strip().lower()
    subject_family = _project_subject_family(_get_subject(item))
    if sender and subject_family:
        return f"{sender}::{subject_family}"
    return conversation_key


def _merge_project_groups(grouped_values: Any) -> list[list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for items in grouped_values:
        ordered = sorted(
            items,
            key=lambda item: _get_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        merge_key = _project_merge_key(ordered)
        merged[merge_key].extend(ordered)
    return list(merged.values())


def _project_merge_key(items: list[dict[str, Any]]) -> str:
    if not items:
        return "project::empty"

    sender = _get_sender(items[0]).strip().lower()
    subject_families = [
        family
        for family in (_project_subject_family(_get_subject(item)) for item in items)
        if family
    ]
    dominant_family = _most_common_value(subject_families)
    if sender and dominant_family:
        return f"{sender}::{dominant_family}"
    return _get_project_group_key(items[0])


def _looks_resolved(item: dict[str, Any]) -> bool:
    combined = " ".join(
        part
        for part in [
            _get_subject(item),
            _get_summary(item),
            str(item.get("reasoning", "")),
        ]
        if part
    ).lower()
    return any(hint in combined for hint in RESOLVED_HINTS)


def _normalize_subject(subject: str) -> str:
    normalized = (subject or "").strip().lower()
    for prefix in ("re:", "fw:", "fwd:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
    return " ".join(normalized.split())


def _project_subject_family(subject: str) -> str:
    normalized = _normalize_subject(subject)
    tokens = re.findall(r"[a-z0-9]+", normalized)
    significant = [token for token in tokens if token not in PROJECT_STOP_WORDS]
    if not significant:
        return ""

    first = significant[0]
    if first in GENERIC_ATTACHMENT_TOKENS:
        return "attachment-review"
    if first == "invoice":
        return "invoice-review"
    if first == "test":
        return "test"
    non_numeric = [token for token in significant if not token.isdigit()]
    if non_numeric:
        return "-".join(non_numeric[:2])
    return "-".join(significant[:2])


def _is_project_worth_surfacing(
    items: list[dict[str, Any]],
    *,
    categories: list[str],
    highest_urgency: int,
    sent_follow_up: dict[str, Any] | None,
) -> bool:
    message_count = len(items)
    project_family = _project_subject_family(_get_subject(items[0])) if items else ""
    meaningful_categories = [category for category in categories if category not in LOW_SIGNAL_PROJECT_CATEGORIES]

    if sent_follow_up:
        return True
    if any(category in STRATEGIC_PROJECT_CATEGORIES for category in categories):
        return True
    if project_family in {"attachment-review", "test"}:
        return message_count >= 3 or highest_urgency <= 2
    if not meaningful_categories:
        return message_count >= 4 and highest_urgency <= 2
    if "vendor_ap" in meaningful_categories:
        return message_count >= 3 or highest_urgency <= 2
    return message_count >= 2 or highest_urgency <= 2


def _get_sender(item: dict[str, Any]) -> str:
    email = item.get("email", {})
    if isinstance(email, dict) and email.get("sender"):
        return str(email.get("sender", "")).strip()
    return str(item.get("email_sender", "")).strip()


def _get_subject(item: dict[str, Any]) -> str:
    email = item.get("email", {})
    if isinstance(email, dict) and email.get("subject"):
        return str(email.get("subject", "")).strip()
    return str(item.get("email_subject", "")).strip()


def _get_message_id(item: dict[str, Any]) -> str:
    email = item.get("email", {})
    if isinstance(email, dict) and email.get("message_id"):
        return str(email.get("message_id", "")).strip()
    return str(item.get("message_id", "")).strip()


def _get_summary(item: dict[str, Any]) -> str:
    return str(item.get("summary", "")).strip()


def _collect_related_subjects(items: list[dict[str, Any]]) -> list[str]:
    subjects: list[str] = []
    for item in items:
        subject = _get_subject(item)
        if not subject:
            continue
        if subject not in subjects:
            subjects.append(subject)
    return subjects[:3]


def _summarize_project_thread(
    items: list[dict[str, Any]],
    *,
    latest: dict[str, Any],
    categories: list[str],
    sent_follow_up: dict[str, Any] | None,
) -> str:
    latest_summary = _get_summary(latest)
    touch_count = len(items)
    contact = _get_sender(latest) or "this contact"
    if sent_follow_up:
        return (
            f"{touch_count} recent touch{'es' if touch_count != 1 else ''} with {contact}. "
            f"{latest_summary or 'This thread is still active.'} "
            "A sent draft already went out, so this looks more like an awaiting-reply thread than a fresh action item."
        ).strip()
    if "calendar" in categories:
        return (
            f"{touch_count} recent touch{'es' if touch_count != 1 else ''} with {contact}. "
            f"{latest_summary or 'Scheduling is active in this thread.'} "
            "It looks like this project may need a calendar decision or a proposed time."
        ).strip()
    if "deal_related" in categories:
        return (
            f"{touch_count} recent touch{'es' if touch_count != 1 else ''} with {contact}. "
            f"{latest_summary or 'Deal momentum is still active in this thread.'} "
            "This appears to be part of an ongoing commercial thread that still needs a concrete next step."
        ).strip()
    if len(items) >= 3:
        return (
            f"{touch_count} recent touch{'es' if touch_count != 1 else ''} with {contact}. "
            f"{latest_summary or 'This thread has had multiple touches recently.'} "
            "The back-and-forth volume suggests it should stay visible until the next owner/action is clear."
        ).strip()
    return (
        f"{touch_count} recent touch{'es' if touch_count != 1 else ''} with {contact}. "
        f"{latest_summary or 'This thread is still active and likely needs a decision on the next step.'}"
    ).strip()


def _project_suggested_action(
    *,
    categories: list[str],
    sent_follow_up: dict[str, Any] | None,
    highest_urgency: int,
) -> str:
    if sent_follow_up:
        return "Check whether a follow-up bump is warranted or whether the thread can be closed."
    if "calendar" in categories:
        return "Decide whether to confirm a time, offer alternatives, or draft an event."
    if "vendor_ap" in categories:
        return "Confirm whether the thread needs a finance handoff or a quick operator decision."
    if highest_urgency <= 2:
        return "Prioritize the next owner and a concrete follow-up step while the thread is still warm."
    return "Keep momentum by deciding the next concrete step."


def _project_display_title(
    items: list[dict[str, Any]],
    *,
    sender: str,
    categories: list[str],
) -> str:
    latest_subject = _get_subject(items[0]) if items else ""
    family = _project_subject_family(latest_subject)
    sender_label = _project_sender_label(sender)

    if family == "attachment-review":
        if "vendor_ap" in categories:
            return f"{sender_label} invoice / attachment flow"
        return f"{sender_label} attachment flow"
    if family == "invoice-review":
        return f"{sender_label} invoice flow"
    if family == "test":
        return f"{sender_label} test thread"
    return latest_subject or (f"{sender_label} thread" if sender_label else "Recent thread")


def _project_sender_label(sender: str) -> str:
    normalized = (sender or "").strip()
    if not normalized:
        return "Recent"
    local_part = normalized.split("@", 1)[0].strip()
    local_part = local_part.replace(".", " ").replace("_", " ").replace("-", " ")
    words = [word.capitalize() for word in local_part.split() if word]
    label = " ".join(words).strip()
    return label or normalized


def _project_latest_direction(
    *,
    latest: dict[str, Any],
    categories: list[str],
    sent_follow_up: dict[str, Any] | None,
) -> str:
    latest_summary = _get_summary(latest)
    if sent_follow_up:
        return latest_summary or "A reply has already gone out, so the thread is now in wait-and-see mode."
    if "calendar" in categories:
        return latest_summary or "Scheduling is the main active thread direction right now."
    if "deal_related" in categories:
        return latest_summary or "Commercial motion is still active, but the next move is not settled yet."
    return latest_summary or "The thread is still open and likely needs a clearer next move."


def _project_next_decision(
    *,
    categories: list[str],
    sent_follow_up: dict[str, Any] | None,
    highest_urgency: int,
) -> str:
    if sent_follow_up:
        return "Decide whether to bump, wait, or close the loop."
    if "calendar" in categories:
        return "Decide whether to confirm a slot, offer alternatives, or draft an event."
    if "deal_related" in categories:
        return "Decide the narrowest concrete next step that keeps the thread moving."
    if highest_urgency <= 2:
        return "Decide who owns the next response and how quickly it needs to move."
    return "Decide whether this should stay visible or be downgraded."


def _project_days_active(items: list[dict[str, Any]]) -> int:
    timestamps = [
        timestamp
        for timestamp in (_get_timestamp(item) for item in items)
        if timestamp is not None
    ]
    if not timestamps:
        return 1
    return max(1, (max(timestamps).date() - min(timestamps).date()).days + 1)


def _build_relationship_memory(
    triage_results: list[dict[str, Any]],
    current_time: datetime,
) -> list[dict[str, Any]]:
    contacts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in triage_results:
        sender = _get_sender(item)
        if sender:
            contacts[sender].append(item)

    memories: list[dict[str, Any]] = []
    for sender, items in contacts.items():
        summary = _summarize_contact_memory(triage_results, sender=sender, current_time=current_time)
        if not summary or not _should_include_relationship_memory(summary):
            continue
        memories.append(summary)

    memories.sort(
        key=lambda item: (
            0 if item.get("status") == "watch" else 1,
            -_relationship_memory_priority(item),
            str(item.get("contact", "")),
        )
    )
    return memories[:5]


def _summarize_contact_memory(
    triage_results: list[dict[str, Any]],
    *,
    sender: str,
    current_time: datetime,
) -> dict[str, Any]:
    related = [
        item
        for item in triage_results
        if _get_sender(item).strip().lower() == sender.strip().lower()
    ]
    if not related:
        return {}

    ordered = sorted(
        related,
        key=lambda item: _get_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    timestamps = [
        timestamp
        for timestamp in (_get_timestamp(item) for item in ordered)
        if timestamp is not None
    ]
    last_contact_at = timestamps[0] if timestamps else current_time
    days_since_last = max((current_time - last_contact_at).days, 0)
    cadence_days = _average_gap_days(sorted(timestamps)) if len(timestamps) >= 2 else 0.0
    recent_subjects = _collect_related_subjects(ordered)
    categories = sorted(
        {
            str(item.get("category", "unknown")) or "unknown"
            for item in ordered[:5]
        }
    )
    status = "watch" if len(timestamps) >= 3 and days_since_last >= max(14, int(round(cadence_days * 1.5)) or 14) else "active"
    meaningful_categories = [category for category in categories if category not in {"internal", "unknown"}]
    if status == "watch":
        why_now = (
            f"It has been {days_since_last} day(s) since the last touch, which is slower than this relationship's usual cadence."
        )
    elif meaningful_categories:
        why_now = (
            f"Recent activity is tied to {', '.join(meaningful_categories[:2])}, so this contact still matters beyond inbox noise."
        )
    else:
        why_now = "Recent activity keeps this contact warm, but it may not deserve top-billing unless the pattern continues."
    return {
        "contact": sender,
        "touch_count": len(ordered),
        "days_since_last_contact": days_since_last,
        "typical_cadence_days": round(cadence_days, 1) if cadence_days else 0.0,
        "recent_subjects": recent_subjects,
        "categories": categories,
        "meaningful_categories": meaningful_categories,
        "status": status,
        "status_label": "Watch this relationship" if status == "watch" else "Recently active",
        "why_now": why_now,
        "latest_summary": _get_summary(ordered[0]),
        "source_message_id": _get_message_id(ordered[0]),
        "source_subject": _get_subject(ordered[0]),
    }


def _should_include_relationship_memory(summary: dict[str, Any]) -> bool:
    if summary.get("status") == "watch":
        return True
    if summary.get("meaningful_categories"):
        return True
    return int(summary.get("touch_count", 0) or 0) >= 4


def _relationship_memory_priority(summary: dict[str, Any]) -> int:
    score = int(summary.get("touch_count", 0) or 0)
    meaningful_categories = summary.get("meaningful_categories") or []
    score += len(meaningful_categories) * 2
    if summary.get("status") == "watch":
        score += 5
    days_since_last = int(summary.get("days_since_last_contact", 0) or 0)
    if summary.get("status") == "active":
        score += max(5 - min(days_since_last, 5), 0)
    return score


def _most_common_value(values: list[str]) -> str:
    if not values:
        return ""
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _average_gap_days(timestamps: list[datetime]) -> float:
    if len(timestamps) < 2:
        return 0.0

    ordered = sorted(timestamps)
    gaps = [
        max((current - previous).total_seconds() / 86400.0, 0.0)
        for previous, current in zip(ordered, ordered[1:])
    ]
    if not gaps:
        return 0.0
    return sum(gaps) / len(gaps)


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
        return parsed
    except ValueError:
        return None


def _combine_date_time(target_date, value: str, tzinfo) -> datetime | None:
    try:
        hour, minute = value.split(":", 1)
        return datetime.combine(
            target_date,
            time(hour=int(hour), minute=int(minute)),
            tzinfo or timezone.utc,
        )
    except (TypeError, ValueError):
        return None


def _normalize_preferred_days(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        token = item.strip().upper()[:2]
        if token in WEEKDAY_CODES and token not in normalized:
            normalized.append(token)
    return normalized


def _normalize_recipients(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []

    recipients: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip().lower()
        if item and item not in recipients:
            recipients.append(item)
    return recipients


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ranges_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a
