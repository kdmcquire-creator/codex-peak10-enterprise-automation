"""
Data models for the Employee Financial & Expense Hub.

Defines: transactions, classification buckets, expense claims,
and the Chinese Wall boundary enforcement.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional


def currency(value: Decimal | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Classification buckets
# ---------------------------------------------------------------------------

class ExpenseBucket(str, Enum):
    """Classification buckets for transactions."""
    PERSONAL = "personal"
    PEAK10 = "peak10"               # Peak 10 Energy reimbursable
    MOONSMOKE_LLC = "moonsmoke_llc"  # Moonsmoke LLC
    UNKNOWN = "unknown"


class TransactionStatus(str, Enum):
    PENDING = "pending"
    CLASSIFIED = "classified"
    CLAIMED = "claimed"       # Expense claim created, crossing the wall
    REIMBURSED = "reimbursed"


class ClaimStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PUSHED_TO_AP = "pushed_to_ap"  # Sent to Pillar 1
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

@dataclass
class BankTransaction:
    """
    A transaction from Plaid. Lives INSIDE the encrypted personal partition.
    Never crosses the Chinese Wall in raw form.
    """
    transaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    plaid_transaction_id: str = ""
    account_id: str = ""
    date: date = field(default_factory=date.today)
    merchant_name: str = ""
    amount: Decimal = Decimal("0.00")
    category: list[str] = field(default_factory=list)  # Plaid categories
    pending: bool = False

    # Classification
    bucket: ExpenseBucket = ExpenseBucket.UNKNOWN
    classification_rule: str = ""  # Which rule classified this
    classification_confidence: float = 0.0
    status: TransactionStatus = TransactionStatus.PENDING

    # Receipt attachment
    receipt_ref: Optional[str] = None  # Reference to receipt in Pillar 3


@dataclass
class ExpenseClaim:
    """
    Sanitized expense record that crosses the Chinese Wall.
    Contains ONLY: vendor, date, amount, description, receipt reference.
    No bank account info, no personal transaction details.
    """
    claim_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    employee_name: str = ""
    vendor_name: str = ""
    expense_date: date = field(default_factory=date.today)
    amount: Decimal = Decimal("0.00")
    description: str = ""
    receipt_ref: str = ""       # SharePoint document ID from Pillar 3
    bucket: ExpenseBucket = ExpenseBucket.PEAK10
    status: ClaimStatus = ClaimStatus.DRAFT
    created_at: datetime = field(default_factory=utc_now)

    # Tracking: which transactions sourced this (stays inside the wall)
    _source_transaction_ids: list[str] = field(default_factory=list, repr=False)


@dataclass
class Pillar1InvoicePayload:
    """
    The exact payload pushed to Pillar 1 AP queue.
    This is what crosses the Chinese Wall — nothing more.
    """
    invoice_id: str = ""
    vendor_id: str = ""
    vendor_name: str = ""
    vendor_priority: int = 2
    amount_due: str = "0.00"
    due_date: str = ""
    description: str = ""
    receipt_ref: str = ""
    source: str = "pillar4_expense"
