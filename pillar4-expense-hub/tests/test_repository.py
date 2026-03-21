"""Tests for Expense Hub repository persistence."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from expense_hub.models import (
    BankTransaction,
    ClaimStatus,
    ExpenseBucket,
    ExpenseClaim,
    TransactionStatus,
)
from expense_hub.repository import ExpenseHubRepository


def test_save_and_get_transaction(tmp_path):
    repo = ExpenseHubRepository(db_path=str(tmp_path / "expense.db"))
    txn = BankTransaction(
        transaction_id="txn-123",
        plaid_transaction_id="plaid-123",
        account_id="acct-1",
        date=date(2026, 3, 21),
        merchant_name="Uber",
        amount=Decimal("45.00"),
        category=["Travel"],
        bucket=ExpenseBucket.PEAK10,
        classification_rule="p10-uber",
        classification_confidence=0.90,
        status=TransactionStatus.CLASSIFIED,
        receipt_ref="doc-1",
    )

    repo.save_transaction(txn)
    loaded = repo.get_transaction("txn-123")

    assert loaded is not None
    assert loaded.transaction_id == "txn-123"
    assert loaded.plaid_transaction_id == "plaid-123"
    assert loaded.bucket == ExpenseBucket.PEAK10
    assert loaded.receipt_ref == "doc-1"


def test_save_and_get_claim(tmp_path):
    repo = ExpenseHubRepository(db_path=str(tmp_path / "expense.db"))
    claim = ExpenseClaim(
        claim_id="claim-123",
        employee_name="K. McQuire",
        vendor_name="Marriott",
        amount=Decimal("189.00"),
        description="Hotel",
        receipt_ref="doc-2",
        status=ClaimStatus.APPROVED,
    )
    claim._source_transaction_ids = ["txn-123"]

    repo.save_claim(claim)
    loaded = repo.get_claim("claim-123")

    assert loaded is not None
    assert loaded.claim_id == "claim-123"
    assert loaded.status == ClaimStatus.APPROVED
    assert loaded.receipt_ref == "doc-2"
    assert loaded._source_transaction_ids == ["txn-123"]
