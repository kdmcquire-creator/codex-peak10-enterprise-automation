"""Tests for learning evidence evaluation helpers."""

from __future__ import annotations

from document_ai.learning_eval import build_learning_eval_report
from document_ai.models import DocumentType, LearningEvidence


def test_learning_eval_report_summarizes_review_and_apply_signals():
    records = [
        LearningEvidence(
            update_id="upd-1",
            document_id="doc-1",
            document_type=DocumentType.CONTRACT,
            target_table="legal_contracts",
            event_type="review",
            decision="approve",
            trust_score=0.91,
            proposed_field_updates={"counterparty": "A"},
            final_field_updates={"counterparty": "A"},
            edited_fields=[],
            actor="owner",
            outcome="approved_pending_apply",
        ),
        LearningEvidence(
            update_id="upd-2",
            document_id="doc-2",
            document_type=DocumentType.INVOICE,
            target_table="finance_ap_invoices",
            event_type="review",
            decision="reject",
            trust_score=0.62,
            proposed_field_updates={"vendor_name": "B"},
            final_field_updates={},
            edited_fields=[],
            actor="owner",
            outcome="rejected_by_owner",
        ),
        LearningEvidence(
            update_id="upd-1",
            document_id="doc-1",
            document_type=DocumentType.CONTRACT,
            target_table="legal_contracts",
            event_type="apply",
            decision="shadow_applied",
            trust_score=0.91,
            proposed_field_updates={"counterparty": "A"},
            final_field_updates={"counterparty": "A"},
            edited_fields=[],
            actor="applier",
            apply_mode="shadow",
            outcome="shadow_applied",
        ),
    ]

    report = build_learning_eval_report(records)

    assert report["total_records"] == 3
    assert report["review_records"] == 2
    assert report["apply_records"] == 1
    assert report["approval_rate"] == 0.5
    assert report["rejected_reviews"] == 1
    assert report["apply_outcomes"]["shadow_applied"] == 1
