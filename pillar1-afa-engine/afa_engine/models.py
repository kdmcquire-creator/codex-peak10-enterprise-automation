"""
Data models for the AFA Engine.

Defines the core domain objects: vendors, invoices, budgets,
allocation results, and ACH export records.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class VendorPriority(int, Enum):
    """Vendor priority tiers (1 = highest)."""
    CRITICAL = 1       # Royalty owners, regulatory, lien holders
    HIGH = 2           # Key service providers, rig contractors
    STANDARD = 3       # Routine vendors
    DEFERRABLE = 4     # Low-urgency, can be pushed to next cycle


class InvoiceStatus(str, Enum):
    PENDING = "pending"
    ALLOCATED = "allocated"
    PARTIALLY_ALLOCATED = "partially_allocated"
    DEFERRED = "deferred"
    APPROVED = "approved"
    EXPORTED = "exported"


class AllocationRunStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXPORTED = "exported"


# ---------------------------------------------------------------------------
# Currency helper
# ---------------------------------------------------------------------------

def currency(value: Decimal | float | str) -> Decimal:
    """Normalize a value to 2-decimal-place currency."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

@dataclass
class Vendor:
    vendor_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    priority: VendorPriority = VendorPriority.STANDARD
    payment_terms_days: int = 30
    ach_routing_number: Optional[str] = None
    ach_account_number: Optional[str] = None
    is_active: bool = True


@dataclass
class Invoice:
    invoice_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    vendor_id: str = ""
    vendor_name: str = ""
    vendor_priority: VendorPriority = VendorPriority.STANDARD
    amount_due: Decimal = Decimal("0.00")
    amount_allocated: Decimal = Decimal("0.00")
    due_date: date = field(default_factory=date.today)
    description: str = ""
    status: InvoiceStatus = InvoiceStatus.PENDING
    source: str = "manual"  # "manual" | "pillar4_expense"

    @property
    def amount_remaining(self) -> Decimal:
        return currency(self.amount_due - self.amount_allocated)

    @property
    def is_fully_allocated(self) -> bool:
        return self.amount_remaining <= Decimal("0.00")

    @property
    def days_until_due(self) -> int:
        return (self.due_date - date.today()).days


@dataclass
class BudgetConstraint:
    total_budget: Decimal = Decimal("0.00")
    reserved_amount: Decimal = Decimal("0.00")  # held back for critical ops

    @property
    def allocatable_budget(self) -> Decimal:
        return currency(self.total_budget - self.reserved_amount)


@dataclass
class AllocationLineItem:
    invoice_id: str = ""
    vendor_id: str = ""
    vendor_name: str = ""
    vendor_priority: VendorPriority = VendorPriority.STANDARD
    invoice_amount: Decimal = Decimal("0.00")
    allocated_amount: Decimal = Decimal("0.00")
    allocation_pass: int = 0  # which pass allocated this (1-4)
    is_partial: bool = False
    notes: str = ""


@dataclass
class AllocationResult:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: AllocationRunStatus = AllocationRunStatus.DRAFT
    budget: BudgetConstraint = field(default_factory=BudgetConstraint)
    total_allocated: Decimal = Decimal("0.00")
    total_deferred: Decimal = Decimal("0.00")
    budget_remaining: Decimal = Decimal("0.00")
    line_items: list[AllocationLineItem] = field(default_factory=list)
    deferred_items: list[AllocationLineItem] = field(default_factory=list)
    pass_summaries: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)

    @property
    def utilization_pct(self) -> Decimal:
        if self.budget.allocatable_budget == 0:
            return Decimal("0.00")
        return currency(
            (self.total_allocated / self.budget.allocatable_budget) * 100
        )


@dataclass
class ACHRecord:
    """Single ACH payment record for bank export."""
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    vendor_name: str = ""
    routing_number: str = ""
    account_number: str = ""
    amount: Decimal = Decimal("0.00")
    invoice_ids: list[str] = field(default_factory=list)
    payment_date: date = field(default_factory=date.today)
