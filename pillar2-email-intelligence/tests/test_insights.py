"""Tests for bucketed growth-insight nudges."""

from __future__ import annotations

from datetime import datetime, timezone

from email_intel.insights import build_growth_nudges


def test_build_growth_nudges_emits_bucketed_relationship_and_reply_signals():
    insights = build_growth_nudges(
        [
            {
                "category": "deal_related",
                "urgency": 2,
                "email_subject": "Asset package intro",
                "email_sender": "contact@example.com",
                "saved_at": "2026-01-01T12:00:00+00:00",
                "summary": "They are interested in discussing a package.",
            },
            {
                "category": "deal_related",
                "urgency": 3,
                "email_subject": "Follow-up package discussion",
                "email_sender": "contact@example.com",
                "saved_at": "2026-01-15T12:00:00+00:00",
                "summary": "Timing may slip because of budget pressure.",
            },
            {
                "category": "calendar",
                "urgency": 3,
                "email_subject": "Can we meet next week?",
                "email_sender": "contact@example.com",
                "saved_at": "2026-02-01T12:00:00+00:00",
                "summary": "Can we meet next week?",
            },
            {
                "category": "unknown",
                "urgency": 3,
                "email_subject": "Need to delay this",
                "email_sender": "other@example.com",
                "saved_at": "2026-03-20T12:00:00+00:00",
                "summary": "We may need to delay.",
            },
            {
                "category": "unknown",
                "urgency": 3,
                "email_subject": "Could be interested",
                "email_sender": "third@example.com",
                "saved_at": "2026-03-21T12:00:00+00:00",
                "summary": "They might be interested in an intro.",
            },
        ],
        drafts=[
            {
                "draft_id": "draft-1",
                "subject": "Re: Asset package intro",
                "to_recipients": ["contact@example.com"],
                "sent": True,
                "sent_at": "2026-03-10T12:00:00+00:00",
            }
        ],
        draft_count=2,
        document_count=3,
        now=datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc),
    )

    nudge_types = {item["type"] for item in insights["nudges"]}

    assert insights["counts"]["total_messages"] == 5
    assert "relationship_drift" in insights["buckets"]
    assert "awaiting_response" in insights["buckets"]
    assert "intent_signal" in insights["buckets"]
    assert "coordination" in insights["buckets"]
    assert "relationship_drift" in nudge_types
    assert "awaiting_response" in nudge_types
    assert "hesitation_signal" in nudge_types or "opportunity_signal" in nudge_types
    assert "manual_review" in nudge_types
    assert "reply_backlog" in nudge_types
    assert "document_follow_through" in nudge_types


def test_build_growth_nudges_stays_quiet_for_small_batches():
    insights = build_growth_nudges(
        [{"category": "internal", "urgency": 4}],
        draft_count=0,
        document_count=0,
    )

    assert insights["counts"]["total_messages"] == 1
    assert insights["nudges"] == []
    assert all(bucket == [] for bucket in insights["buckets"].values())
