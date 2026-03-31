"""Tests for database update policy guardrails."""

from __future__ import annotations

from document_ai.database_update_policy import (
    evaluate_database_update_proposal,
    target_table_for_document_type,
)
from document_ai.models import DocumentType


def test_policy_allows_valid_final_contract_payload():
    table = target_table_for_document_type(DocumentType.CONTRACT)
    evaluation = evaluate_database_update_proposal(
        document_type=DocumentType.CONTRACT,
        target_table=table,
        version_status="final",
        proposed_updates={
            "counterparty": "DrillCo Services",
            "effective_date": "2026-03-27",
            "amount": "150000.00",
            "recommended_path": "01_CORPORATE/Legal/Contracts",
        },
        confidence=0.93,
        min_trust_score=0.7,
    )

    assert evaluation.allow_queue is True
    assert evaluation.violations == []
    assert evaluation.sanitized_updates["amount"] == "150000.00"


def test_policy_drops_fields_outside_allowlist():
    table = target_table_for_document_type(DocumentType.CONTRACT)
    evaluation = evaluate_database_update_proposal(
        document_type=DocumentType.CONTRACT,
        target_table=table,
        version_status="final",
        proposed_updates={
            "counterparty": "DrillCo Services",
            "effective_date": "2026-03-27",
            "bank_account_number": "123456789",
        },
        confidence=0.95,
        min_trust_score=0.7,
    )

    assert evaluation.allow_queue is True
    assert any(w.startswith("field_not_allowed:bank_account_number") for w in evaluation.warnings)
    assert "bank_account_number" not in evaluation.sanitized_updates


def test_policy_rejects_invalid_dates():
    table = target_table_for_document_type(DocumentType.CONTRACT)
    evaluation = evaluate_database_update_proposal(
        document_type=DocumentType.CONTRACT,
        target_table=table,
        version_status="final",
        proposed_updates={
            "counterparty": "DrillCo Services",
            "effective_date": "03/27/2026",
        },
        confidence=0.95,
        min_trust_score=0.7,
    )

    assert evaluation.allow_queue is False
    assert any(v.startswith("effective_date:invalid_date_format") for v in evaluation.violations)


def test_policy_blocks_low_trust_payload():
    table = target_table_for_document_type(DocumentType.INVOICE)
    evaluation = evaluate_database_update_proposal(
        document_type=DocumentType.INVOICE,
        target_table=table,
        version_status="final",
        proposed_updates={
            "vendor_name": "Vendor A",
            "amount": "100.00",
        },
        confidence=0.45,
        min_trust_score=0.8,
    )

    assert evaluation.allow_queue is False
    assert evaluation.trust_score < 0.8
