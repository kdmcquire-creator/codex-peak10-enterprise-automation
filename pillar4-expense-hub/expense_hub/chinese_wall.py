"""
Chinese Wall enforcement layer.

This is the most critical architectural constraint in the system.
Personal financial data lives inside an encrypted boundary. Only
explicitly approved, sanitized expense claim records can cross.

This module enforces:
  1. BankTransaction objects NEVER leave the personal partition
  2. Only ExpenseClaim records (vendor, date, amount, receipt) cross
  3. The Pillar1InvoicePayload is the exact shape pushed to the AP queue
  4. All crossings are logged for audit
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from .models import (
    BankTransaction,
    ClaimStatus,
    ExpenseBucket,
    ExpenseClaim,
    Pillar1InvoicePayload,
    TransactionStatus,
    currency,
)


class ChineseWallViolation(Exception):
    """Raised when an operation would breach the Chinese Wall."""
    pass


class AuditEntry:
    """Log entry for wall crossings."""
    def __init__(self, claim_id: str, action: str, timestamp: datetime | None = None):
        self.claim_id = claim_id
        self.action = action
        self.timestamp = timestamp or datetime.now(timezone.utc)

    def __repr__(self) -> str:
        return f"AuditEntry({self.action}, claim={self.claim_id}, at={self.timestamp.isoformat()})"


class ChineseWall:
    """
    Enforces the data boundary between personal financial data
    and the Peak 10 corporate AP system.
    """

    def __init__(self) -> None:
        self._audit_log: list[AuditEntry] = []

    def create_expense_claim(
        self,
        transaction: BankTransaction,
        employee_name: str,
        description: str = "",
    ) -> ExpenseClaim:
        """
        Create a sanitized expense claim from a classified transaction.

        Only PEAK10-classified transactions can generate claims.
        The claim contains NO bank account data.
        """
        if transaction.bucket != ExpenseBucket.PEAK10:
            raise ChineseWallViolation(
                f"Cannot create expense claim: transaction is classified as "
                f"'{transaction.bucket.value}', must be 'peak10'"
            )

        if transaction.status == TransactionStatus.PENDING:
            raise ChineseWallViolation(
                "Cannot create claim from unclassified transaction"
            )

        claim = ExpenseClaim(
            employee_name=employee_name,
            vendor_name=transaction.merchant_name,
            expense_date=transaction.date,
            amount=currency(transaction.amount),
            description=description or f"Business expense: {transaction.merchant_name}",
            receipt_ref=transaction.receipt_ref or "",
            bucket=ExpenseBucket.PEAK10,
            status=ClaimStatus.DRAFT,
            _source_transaction_ids=[transaction.transaction_id],
        )

        self._audit_log.append(AuditEntry(claim.claim_id, "claim_created"))
        transaction.status = TransactionStatus.CLAIMED

        return claim

    def push_to_pillar1(self, claim: ExpenseClaim) -> Pillar1InvoicePayload:
        """
        Generate the sanitized payload that crosses the wall to Pillar 1.

        Only APPROVED claims can be pushed.
        """
        if claim.status != ClaimStatus.APPROVED:
            raise ChineseWallViolation(
                f"Cannot push to AP: claim is '{claim.status.value}', must be 'approved'"
            )

        payload = Pillar1InvoicePayload(
            vendor_id=f"emp-{claim.employee_name.lower().replace(' ', '-')}",
            vendor_name=claim.vendor_name,
            amount_due=str(claim.amount),
            due_date=date.today().isoformat(),
            description=claim.description,
            receipt_ref=claim.receipt_ref,
            source="pillar4_expense",
        )

        claim.status = ClaimStatus.PUSHED_TO_AP
        self._audit_log.append(AuditEntry(claim.claim_id, "pushed_to_pillar1"))

        return payload

    def validate_no_leak(self, payload: Pillar1InvoicePayload) -> bool:
        """
        Final validation: ensure the payload contains NO personal data.
        Returns True if clean, raises ChineseWallViolation if not.
        """
        # The payload should never contain bank account info
        sensitive_patterns = [
            "account", "routing", "plaid", "bank", "ssn", "social",
        ]
        payload_str = (
            f"{payload.vendor_id} {payload.vendor_name} {payload.description}"
        ).lower()

        for pattern in sensitive_patterns:
            if pattern in payload_str:
                raise ChineseWallViolation(
                    f"Payload contains potentially sensitive data: '{pattern}' found"
                )

        return True

    @property
    def audit_log(self) -> list[AuditEntry]:
        return list(self._audit_log)
