"""JSON serialization for Expense Hub models."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from .models import (
    BankTransaction,
    ClaimStatus,
    ExpenseBucket,
    ExpenseClaim,
    Pillar1InvoicePayload,
    TransactionStatus,
    currency,
)


def serialize_transaction(t: BankTransaction) -> dict[str, Any]:
    """Serialize a transaction — for internal use only, NEVER sent outside the wall."""
    return {
        "transaction_id": t.transaction_id,
        "date": t.date.isoformat(),
        "merchant_name": t.merchant_name,
        "amount": str(t.amount),
        "category": t.category,
        "bucket": t.bucket.value,
        "classification_rule": t.classification_rule,
        "classification_confidence": t.classification_confidence,
        "status": t.status.value,
        "has_receipt": t.receipt_ref is not None,
    }


def serialize_expense_claim(c: ExpenseClaim) -> dict[str, Any]:
    """Serialize a claim — safe to send across the wall."""
    return {
        "claim_id": c.claim_id,
        "employee_name": c.employee_name,
        "vendor_name": c.vendor_name,
        "expense_date": c.expense_date.isoformat(),
        "amount": str(c.amount),
        "description": c.description,
        "receipt_ref": c.receipt_ref,
        "bucket": c.bucket.value,
        "status": c.status.value,
        "created_at": c.created_at.isoformat(),
    }


def serialize_pillar1_payload(p: Pillar1InvoicePayload) -> dict[str, Any]:
    return {
        "invoice_id": p.invoice_id,
        "vendor_id": p.vendor_id,
        "vendor_name": p.vendor_name,
        "vendor_priority": p.vendor_priority,
        "amount_due": p.amount_due,
        "due_date": p.due_date,
        "description": p.description,
        "receipt_ref": p.receipt_ref,
        "source": p.source,
    }


def deserialize_transaction(data: dict[str, Any]) -> BankTransaction:
    return BankTransaction(
        transaction_id=data.get("transaction_id", ""),
        plaid_transaction_id=data.get("plaid_transaction_id", ""),
        account_id=data.get("account_id", ""),
        date=date.fromisoformat(data["date"]),
        merchant_name=data.get("merchant_name", ""),
        amount=currency(data.get("amount", "0.00")),
        category=data.get("category", []),
        pending=bool(data.get("pending", False)),
        bucket=ExpenseBucket(data.get("bucket", ExpenseBucket.UNKNOWN.value)),
        classification_rule=data.get("classification_rule", ""),
        classification_confidence=float(data.get("classification_confidence", 0.0)),
        status=TransactionStatus(data.get("status", TransactionStatus.PENDING.value)),
        receipt_ref=data.get("receipt_ref"),
    )


def deserialize_expense_claim(data: dict[str, Any]) -> ExpenseClaim:
    claim = ExpenseClaim(
        claim_id=data.get("claim_id", ""),
        employee_name=data.get("employee_name", ""),
        vendor_name=data.get("vendor_name", ""),
        expense_date=date.fromisoformat(data["expense_date"]),
        amount=currency(data.get("amount", "0.00")),
        description=data.get("description", ""),
        receipt_ref=data.get("receipt_ref", ""),
        bucket=ExpenseBucket(data.get("bucket", ExpenseBucket.PEAK10.value)),
        status=ClaimStatus(data.get("status", ClaimStatus.DRAFT.value)),
        created_at=datetime.fromisoformat(data["created_at"])
        if data.get("created_at")
        else datetime.now(timezone.utc),
    )
    claim._source_transaction_ids = data.get("_source_transaction_ids", [])
    return claim
