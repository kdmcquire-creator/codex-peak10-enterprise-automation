"""Tests for Morning Brief assembly."""

from __future__ import annotations

from datetime import datetime, timezone

from email_intel.briefing import build_morning_brief


def test_build_morning_brief_surfaces_projects_follow_ups_and_protected_time():
    brief = build_morning_brief(
        [
            {
                "message_id": "thread-1-a",
                "conversation_id": "conv-1",
                "category": "deal_related",
                "urgency": 2,
                "email_subject": "Lease diligence follow-up",
                "email_sender": "owner@example.com",
                "saved_at": "2026-03-24T14:00:00+00:00",
                "summary": "We may need to delay diligence while budget is reviewed.",
            },
            {
                "message_id": "thread-1-b",
                "conversation_id": "conv-1",
                "category": "deal_related",
                "urgency": 2,
                "email_subject": "Re: Lease diligence follow-up",
                "email_sender": "owner@example.com",
                "saved_at": "2026-03-25T13:00:00+00:00",
                "summary": "Still waiting on a decision from their side.",
            },
            {
                "message_id": "rel-1",
                "category": "deal_related",
                "urgency": 3,
                "email_subject": "Intro call",
                "email_sender": "regular@example.com",
                "saved_at": "2026-01-01T12:00:00+00:00",
                "summary": "Initial outreach.",
            },
            {
                "message_id": "rel-2",
                "category": "deal_related",
                "urgency": 3,
                "email_subject": "Timing update",
                "email_sender": "regular@example.com",
                "saved_at": "2026-01-15T12:00:00+00:00",
                "summary": "Could be interested in moving forward.",
            },
            {
                "message_id": "rel-3",
                "category": "calendar",
                "urgency": 3,
                "email_subject": "Can we meet next week?",
                "email_sender": "regular@example.com",
                "saved_at": "2026-02-01T12:00:00+00:00",
                "summary": "Can we meet next week?",
            },
        ],
        drafts=[
            {
                "draft_id": "draft-1",
                "subject": "Re: Waiting on next steps",
                "to_recipients": ["silent@example.com"],
                "sent": True,
                "sent_at": "2026-03-20T12:00:00+00:00",
            }
        ],
        calendar_items=[
            {
                "title": "Lunch meeting",
                "start": "2026-03-25T12:00:00+00:00",
                "end": "2026-03-25T12:45:00+00:00",
            },
            {
                "title": "Ops check-in",
                "start": "2026-03-25T15:00:00+00:00",
                "end": "2026-03-25T15:30:00+00:00",
            },
        ],
        personal_priorities=[
            {
                "name": "Workout",
                "target_days_per_week": 4,
                "preferred_days": ["WE", "TH", "FR"],
                "preferred_window": {"start": "12:00", "end": "13:00"},
                "duration_minutes": 60,
            }
        ],
        draft_count=2,
        document_count=1,
        now=datetime(2026, 3, 25, 8, 0, tzinfo=timezone.utc),
    )

    assert brief["overview"]["ongoing_project_count"] >= 1
    assert brief["overview"]["follow_up_count"] >= 1
    assert brief["overview"]["watchlist_count"] >= 1
    assert brief["overview"]["relationship_memory_count"] == 2
    assert brief["ongoing_projects"][0]["title"] == "Re: Lease diligence follow-up"
    assert brief["ongoing_projects"][0]["status_label"] == "Active thread"
    assert brief["ongoing_projects"][0]["summary"].startswith("2 recent touches with owner@example.com.")
    assert "ongoing commercial thread" in brief["ongoing_projects"][0]["summary"]
    assert brief["ongoing_projects"][0]["latest_direction"] == "Still waiting on a decision from their side."
    assert brief["ongoing_projects"][0]["next_decision"] == "Decide the narrowest concrete next step that keeps the thread moving."
    assert brief["ongoing_projects"][0]["days_active"] == 2
    assert brief["ongoing_projects"][0]["contact_memory"]["contact"] == "owner@example.com"
    assert brief["ongoing_projects"][0]["related_subjects"]
    assert any(item["type"] == "relationship_drift" for item in brief["follow_ups"])
    calendar_item = next(item for item in brief["follow_ups"] if item["type"] == "calendar_follow_up")
    assert any(item["type"] == "hesitation_signal" for item in brief["watchlist"])
    assert brief["follow_ups"][0]["available_actions"]
    assert any(action["action"] == "generate_event_draft" for action in calendar_item["available_quick_actions"])
    assert brief["watchlist"][0]["state_label"] == "Open"
    assert any(item["contact"] == "regular@example.com" and item["status"] == "watch" for item in brief["relationship_memory"])
    assert any(item["contact"] == "owner@example.com" and item["status"] == "active" for item in brief["relationship_memory"])
    assert brief["calendar_review"]["meeting_count"] == 2
    assert brief["protected_time"]["priorities"][0]["status"] == "conflict"
    assert brief["protected_time"]["priorities"][0]["alternate_windows"]
    assert brief["suggested_focus_blocks"]


def test_build_morning_brief_marks_clear_personal_priority_when_calendar_allows():
    brief = build_morning_brief(
        [],
        calendar_items=[
            {
                "title": "Board prep",
                "start": "2026-03-25T09:00:00+00:00",
                "end": "2026-03-25T10:00:00+00:00",
            }
        ],
        personal_priorities=[
            {
                "name": "Workout",
                "preferred_window": {"start": "12:00", "end": "13:00"},
                "duration_minutes": 60,
            }
        ],
        now=datetime(2026, 3, 25, 8, 0, tzinfo=timezone.utc),
    )

    assert brief["protected_time"]["conflict_count"] == 0
    assert brief["protected_time"]["priorities"][0]["status"] == "clear"


def test_build_morning_brief_carries_open_items_and_filters_resolved_ones():
    brief = build_morning_brief(
        [],
        stored_brief_items=[
            {
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
            },
            {
                "id": "resolved-1",
                "item_id": "resolved-1",
                "item_kind": "watchlist",
                "type": "hesitation_signal",
                "title": "Budget hesitation",
                "message": "They may need to delay.",
                "suggested_action": "Hold until next week.",
                "priority": "medium",
                "state": "resolved",
                "first_seen_at": "2026-03-22T08:00:00+00:00",
                "last_seen_at": "2026-03-24T08:00:00+00:00",
            },
        ],
        now=datetime(2026, 3, 25, 8, 0, tzinfo=timezone.utc),
    )

    assert brief["follow_ups"][0]["item_id"] == "carry-1"
    assert brief["follow_ups"][0]["carried_over"] is True
    assert brief["follow_ups"][0]["state"] == "open"
    assert brief["watchlist"] == []
    assert any(record["item_id"] == "carry-1" for record in brief["brief_item_records"])


def test_build_morning_brief_groups_related_subject_families_into_one_project():
    brief = build_morning_brief(
        [
            {
                "message_id": "proj-1",
                "category": "deal_related",
                "urgency": 2,
                "email_subject": "Diligence review timing",
                "email_sender": "owner@example.com",
                "saved_at": "2026-03-24T10:00:00+00:00",
                "summary": "Need to revisit diligence timing.",
            },
            {
                "message_id": "proj-2",
                "category": "deal_related",
                "urgency": 2,
                "email_subject": "Re: Diligence review next steps",
                "email_sender": "owner@example.com",
                "saved_at": "2026-03-25T11:00:00+00:00",
                "summary": "Still waiting on next steps.",
            },
            {
                "message_id": "proj-3",
                "category": "deal_related",
                "urgency": 3,
                "email_subject": "Diligence review budget update",
                "email_sender": "owner@example.com",
                "saved_at": "2026-03-25T13:00:00+00:00",
                "summary": "Budget concerns are slowing the thread down.",
            },
        ],
        now=datetime(2026, 3, 25, 16, 0, tzinfo=timezone.utc),
    )

    assert len(brief["ongoing_projects"]) == 1
    assert brief["ongoing_projects"][0]["message_count"] == 3
    assert brief["ongoing_projects"][0]["participants"] == ["owner@example.com"]
    assert brief["ongoing_projects"][0]["days_active"] == 2
    assert "Decide the narrowest concrete next step" in brief["ongoing_projects"][0]["next_decision"]
    assert len(brief["ongoing_projects"][0]["related_subjects"]) >= 2


def test_build_morning_brief_merges_same_sender_subject_family_across_thread_keys():
    brief = build_morning_brief(
        [
            {
                "message_id": "merge-1",
                "conversation_id": "conv-a",
                "category": "vendor_ap",
                "urgency": 2,
                "email_subject": "Att. #1",
                "email_sender": "moonsmoke.contact@gmail.com",
                "saved_at": "2026-03-27T03:00:00+00:00",
                "summary": "Invoice attachment arrived.",
            },
            {
                "message_id": "merge-2",
                "category": "vendor_ap",
                "urgency": 2,
                "email_subject": "Att 1",
                "email_sender": "moonsmoke.contact@gmail.com",
                "saved_at": "2026-03-27T04:00:00+00:00",
                "summary": "A second attachment came through the same lane.",
            },
        ],
        now=datetime(2026, 3, 27, 6, 0, tzinfo=timezone.utc),
    )

    assert len(brief["ongoing_projects"]) == 1
    assert brief["ongoing_projects"][0]["message_count"] == 2
    assert brief["ongoing_projects"][0]["contact"] == "moonsmoke.contact@gmail.com"
    assert brief["ongoing_projects"][0]["title"] == "Moonsmoke Contact invoice / attachment flow"


def test_build_morning_brief_suppresses_low_signal_attachment_projects():
    brief = build_morning_brief(
        [
            {
                "message_id": "att-1",
                "category": "vendor_ap",
                "urgency": 3,
                "email_subject": "Att. #1",
                "email_sender": "moonsmoke.contact@gmail.com",
                "saved_at": "2026-03-24T12:58:12+00:00",
                "summary": "Invoice attachment came in.",
            },
            {
                "message_id": "att-2",
                "category": "unknown",
                "urgency": 5,
                "email_subject": "Att 3",
                "email_sender": "moonsmoke.contact@gmail.com",
                "saved_at": "2026-03-27T04:04:51+00:00",
                "summary": "Zip attachment came in.",
            },
        ],
        now=datetime(2026, 3, 27, 6, 0, tzinfo=timezone.utc),
    )

    assert brief["ongoing_projects"] == []


def test_build_morning_brief_filters_low_signal_relationship_memory():
    brief = build_morning_brief(
        [
            {
                "message_id": "mem-1",
                "category": "internal",
                "urgency": 4,
                "email_subject": "AutomationLab update",
                "email_sender": "AutomationLab@codexpeak10lab.onmicrosoft.com",
                "saved_at": "2026-03-26T12:00:00+00:00",
                "summary": "Routine internal group note.",
            },
            {
                "message_id": "mem-2",
                "category": "unknown",
                "urgency": 5,
                "email_subject": "TEST",
                "email_sender": "automation@codexpeak10lab.onmicrosoft.com",
                "saved_at": "2026-03-27T01:00:00+00:00",
                "summary": "Placeholder message.",
            },
            {
                "message_id": "mem-3",
                "category": "deal_related",
                "urgency": 3,
                "email_subject": "Need to delay this opportunity",
                "email_sender": "contact@example.com",
                "saved_at": "2026-03-26T20:00:00+00:00",
                "summary": "They may need to delay, but the opportunity is still active.",
            },
            {
                "message_id": "mem-4",
                "category": "deal_related",
                "urgency": 3,
                "email_subject": "Follow up call",
                "email_sender": "contact@example.com",
                "saved_at": "2026-03-27T02:00:00+00:00",
                "summary": "Following up while the context is still warm.",
            },
        ],
        now=datetime(2026, 3, 27, 6, 0, tzinfo=timezone.utc),
    )

    contacts = [item["contact"] for item in brief["relationship_memory"]]
    assert "contact@example.com" in contacts
    assert "AutomationLab@codexpeak10lab.onmicrosoft.com" not in contacts
    assert "automation@codexpeak10lab.onmicrosoft.com" not in contacts


def test_build_morning_brief_suppresses_low_signal_internal_projects():
    brief = build_morning_brief(
        [
            {
                "message_id": "internal-1",
                "category": "internal",
                "urgency": 4,
                "email_subject": "You've joined the AutomationLab group",
                "email_sender": "AutomationLab@codexpeak10lab.onmicrosoft.com",
                "saved_at": "2026-03-24T12:47:23+00:00",
                "summary": "Internal group message.",
            },
            {
                "message_id": "internal-2",
                "category": "internal",
                "urgency": 4,
                "email_subject": "You've joined the AutomationLab group",
                "email_sender": "AutomationLab@codexpeak10lab.onmicrosoft.com",
                "saved_at": "2026-03-27T04:04:53+00:00",
                "summary": "Internal group message again.",
            },
            {
                "message_id": "test-1",
                "category": "unknown",
                "urgency": 5,
                "email_subject": "TEST",
                "email_sender": "automation@codexpeak10lab.onmicrosoft.com",
                "saved_at": "2026-03-24T12:47:23+00:00",
                "summary": "Placeholder.",
            },
            {
                "message_id": "test-2",
                "category": "unknown",
                "urgency": 5,
                "email_subject": "TEST",
                "email_sender": "automation@codexpeak10lab.onmicrosoft.com",
                "saved_at": "2026-03-27T04:04:53+00:00",
                "summary": "Placeholder again.",
            },
        ],
        now=datetime(2026, 3, 27, 6, 0, tzinfo=timezone.utc),
    )

    assert brief["ongoing_projects"] == []


def test_build_morning_brief_keeps_subject_title_for_strategic_threads():
    brief = build_morning_brief(
        [
            {
                "message_id": "deal-1",
                "category": "deal_related",
                "urgency": 2,
                "email_subject": "Follow up call",
                "email_sender": "kdmcquire@gmail.com",
                "saved_at": "2026-03-27T04:04:50+00:00",
                "summary": "Potential deal follow-up.",
            }
        ],
        now=datetime(2026, 3, 27, 6, 0, tzinfo=timezone.utc),
    )

    assert brief["ongoing_projects"][0]["title"] == "Follow up call"
