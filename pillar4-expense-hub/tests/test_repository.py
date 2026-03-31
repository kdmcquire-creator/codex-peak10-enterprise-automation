"""Tests for Expense Hub repository persistence."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import uuid

from expense_hub.models import (
    BankTransaction,
    ClaimStatus,
    ExpenseBucket,
    ExpenseClaim,
    TransactionStatus,
)
from expense_hub.repository import ExpenseHubRepository


def _build_repo() -> ExpenseHubRepository:
    base_dir = Path.cwd() / ".pytest-tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    return ExpenseHubRepository(db_path=str(base_dir / f"expense-{uuid.uuid4().hex}.db"))


def test_save_and_get_transaction():
    repo = _build_repo()
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


def test_save_and_get_claim():
    repo = _build_repo()
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


def test_default_db_path_falls_back_when_repo_data_dir_not_writable(monkeypatch):
    repo_root = Path.cwd() / ".pytest-tmp" / f"expense-fallback-{uuid.uuid4().hex}"
    repo_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("expense_hub.repository._preferred_data_dir", lambda: repo_root / ".data")
    monkeypatch.setattr("expense_hub.repository._fallback_data_dir", lambda: repo_root / "fallback")
    monkeypatch.setattr("expense_hub.repository._ensure_writable_dir", lambda path: False)

    from expense_hub.repository import _default_db_path

    db_path = Path(_default_db_path())

    assert db_path.parent == repo_root / "fallback"
    assert db_path.name == "expense-hub.db"
