"""
Tests for Chinese Wall enforcement.

Covers:
  - Only PEAK10 transactions can generate claims
  - Only APPROVED claims can cross the wall
  - No sensitive data leaks in the payload
  - Audit logging
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from expense_hub.chinese_wall import ChineseWall, ChineseWallViolation
from expense_hub.models import (
    BankTransaction,
    ClaimStatus,
    ExpenseBucket,
    TransactionStatus,
)


def make_classified_txn(
    bucket: ExpenseBucket = ExpenseBucket.PEAK10,
    merchant: str = "Uber",
    amount: str = "45.00",
) -> BankTransaction:
    return BankTransaction(
        merchant_name=merchant,
        amount=Decimal(amount),
        bucket=bucket,
        status=TransactionStatus.CLASSIFIED,
        classification_rule="test-rule",
        classification_confidence=0.95,
    )


class TestCreateExpenseClaim:
    def test_peak10_transaction_creates_claim(self):
        wall = ChineseWall()
        txn = make_classified_txn(ExpenseBucket.PEAK10, "Marriott", "189.00")
        claim = wall.create_expense_claim(txn, "K. McQuire")

        assert claim.vendor_name == "Marriott"
        assert claim.amount == Decimal("189.00")
        assert claim.employee_name == "K. McQuire"
        assert claim.status == ClaimStatus.DRAFT
        assert txn.status == TransactionStatus.CLAIMED

    def test_personal_transaction_blocked(self):
        wall = ChineseWall()
        txn = make_classified_txn(ExpenseBucket.PERSONAL, "Netflix")
        with pytest.raises(ChineseWallViolation, match="personal"):
            wall.create_expense_claim(txn, "K. McQuire")

    def test_moonsmoke_transaction_blocked(self):
        wall = ChineseWall()
        txn = make_classified_txn(ExpenseBucket.MOONSMOKE_LLC, "DistroKid")
        with pytest.raises(ChineseWallViolation, match="moonsmoke_llc"):
            wall.create_expense_claim(txn, "K. McQuire")

    def test_unknown_transaction_blocked(self):
        wall = ChineseWall()
        txn = make_classified_txn(ExpenseBucket.UNKNOWN, "Mystery Store")
        with pytest.raises(ChineseWallViolation):
            wall.create_expense_claim(txn, "K. McQuire")

    def test_unclassified_transaction_blocked(self):
        wall = ChineseWall()
        txn = BankTransaction(
            merchant_name="Uber",
            amount=Decimal("45.00"),
            bucket=ExpenseBucket.PEAK10,
            status=TransactionStatus.PENDING,
        )
        with pytest.raises(ChineseWallViolation, match="unclassified"):
            wall.create_expense_claim(txn, "K. McQuire")


class TestPushToPillar1:
    def test_approved_claim_crosses_wall(self):
        wall = ChineseWall()
        txn = make_classified_txn(ExpenseBucket.PEAK10, "Halliburton", "5000.00")
        claim = wall.create_expense_claim(txn, "K. McQuire")
        claim.status = ClaimStatus.APPROVED

        payload = wall.push_to_pillar1(claim)
        assert payload.invoice_id == claim.claim_id
        assert payload.vendor_name == "Halliburton"
        assert payload.vendor_priority == 2
        assert payload.amount_due == "5000.00"
        assert payload.source == "pillar4_expense"
        assert claim.status == ClaimStatus.PUSHED_TO_AP

    def test_draft_claim_blocked(self):
        wall = ChineseWall()
        txn = make_classified_txn(ExpenseBucket.PEAK10)
        claim = wall.create_expense_claim(txn, "K. McQuire")
        # claim is still DRAFT
        with pytest.raises(ChineseWallViolation, match="approved"):
            wall.push_to_pillar1(claim)

    def test_payload_no_bank_data(self):
        wall = ChineseWall()
        txn = make_classified_txn(ExpenseBucket.PEAK10, "FedEx", "25.00")
        claim = wall.create_expense_claim(txn, "K. McQuire")
        claim.status = ClaimStatus.APPROVED

        payload = wall.push_to_pillar1(claim)
        assert wall.validate_no_leak(payload) is True

        # Verify the payload has no bank fields
        payload_dict = {
            "vendor_id": payload.vendor_id,
            "vendor_name": payload.vendor_name,
            "amount_due": payload.amount_due,
            "description": payload.description,
        }
        for value in payload_dict.values():
            assert "account" not in str(value).lower()
            assert "routing" not in str(value).lower()
            assert "plaid" not in str(value).lower()


class TestAuditLog:
    def test_audit_entries_created(self):
        wall = ChineseWall()
        txn = make_classified_txn(ExpenseBucket.PEAK10, "Uber", "45.00")
        claim = wall.create_expense_claim(txn, "K. McQuire")
        claim.status = ClaimStatus.APPROVED
        wall.push_to_pillar1(claim)

        assert len(wall.audit_log) == 2
        assert wall.audit_log[0].action == "claim_created"
        assert wall.audit_log[1].action == "pushed_to_pillar1"
