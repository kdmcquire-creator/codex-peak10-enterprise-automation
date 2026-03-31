"""Evaluation helpers for controlled learning signals."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .models import LearningEvidence


def build_learning_eval_report(evidence_records: list[LearningEvidence]) -> dict[str, Any]:
    total_records = len(evidence_records)
    review_records = [record for record in evidence_records if record.event_type == "review"]
    apply_records = [record for record in evidence_records if record.event_type == "apply"]

    approved_reviews = [record for record in review_records if record.decision == "approve"]
    rejected_reviews = [record for record in review_records if record.decision == "reject"]
    edited_approvals = [record for record in approved_reviews if record.edited_fields]

    approval_rate = (
        (len(approved_reviews) / len(review_records))
        if review_records
        else 0.0
    )
    edit_rate = (
        (len(edited_approvals) / len(approved_reviews))
        if approved_reviews
        else 0.0
    )
    avg_trust_approved = _avg([record.trust_score for record in approved_reviews])
    avg_trust_rejected = _avg([record.trust_score for record in rejected_reviews])

    rejection_by_table: dict[str, int] = defaultdict(int)
    edited_field_counter: Counter[str] = Counter()
    low_trust_approved = 0
    for record in review_records:
        if record.decision == "reject":
            rejection_by_table[record.target_table] += 1
        if record.decision == "approve" and record.trust_score < 0.7:
            low_trust_approved += 1
        for field_name in record.edited_fields:
            edited_field_counter[field_name] += 1

    apply_outcomes: Counter[str] = Counter()
    for record in apply_records:
        apply_outcomes[record.outcome or record.decision or "unknown"] += 1

    alerts: list[str] = []
    if review_records and approval_rate < 0.5:
        alerts.append("approval_rate_low")
    if review_records and approval_rate > 0.95:
        alerts.append("approval_rate_high_check_for_false_positives")
    if low_trust_approved > 0:
        alerts.append("approved_low_trust_records_present")
    if edited_approvals and edit_rate > 0.4:
        alerts.append("high_edit_rate_revisit_extraction_rules")

    return {
        "total_records": total_records,
        "review_records": len(review_records),
        "apply_records": len(apply_records),
        "approved_reviews": len(approved_reviews),
        "rejected_reviews": len(rejected_reviews),
        "approval_rate": round(approval_rate, 4),
        "edit_rate_on_approvals": round(edit_rate, 4),
        "avg_trust_score_approved": round(avg_trust_approved, 4),
        "avg_trust_score_rejected": round(avg_trust_rejected, 4),
        "approved_low_trust_count": low_trust_approved,
        "rejections_by_table": dict(sorted(rejection_by_table.items())),
        "most_edited_fields": [field for field, _ in edited_field_counter.most_common(10)],
        "apply_outcomes": dict(apply_outcomes),
        "alerts": alerts,
    }


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
