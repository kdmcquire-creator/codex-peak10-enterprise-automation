"""Tests for AFA repository persistence."""

from __future__ import annotations

from pathlib import Path
import uuid
from datetime import date
from decimal import Decimal

from afa_engine.models import AllocationResult, AllocationRunStatus, BudgetConstraint, Invoice, VendorPriority
from afa_engine.repository import AllocationRunRepository


def test_save_and_get_allocation_run():
    base_dir = Path.cwd() / ".pytest-tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    repo = AllocationRunRepository(db_path=str(base_dir / f"afa-{uuid.uuid4().hex}.db"))
    result = AllocationResult(
        run_id="run-123",
        status=AllocationRunStatus.PENDING_APPROVAL,
        budget=BudgetConstraint(
            total_budget=Decimal("1000.00"),
            reserved_amount=Decimal("100.00"),
        ),
        total_allocated=Decimal("750.00"),
        total_deferred=Decimal("50.00"),
        budget_remaining=Decimal("150.00"),
    )

    repo.save(result)
    loaded = repo.get("run-123")

    assert loaded is not None
    assert loaded.run_id == "run-123"
    assert loaded.status == AllocationRunStatus.PENDING_APPROVAL
    assert loaded.budget.total_budget == Decimal("1000.00")
    assert loaded.total_allocated == Decimal("750.00")


def test_save_and_list_intake_invoice():
    base_dir = Path.cwd() / ".pytest-tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    repo = AllocationRunRepository(db_path=str(base_dir / f"afa-{uuid.uuid4().hex}.db"))
    invoice = Invoice(
        invoice_id="claim-123",
        vendor_id="emp-smoke-test-user",
        vendor_name="Uber",
        vendor_priority=VendorPriority.HIGH,
        amount_due=Decimal("35.00"),
        due_date=date(2026, 3, 29),
        description="Expense reimbursement",
        source="pillar4_expense",
    )

    repo.save_intake_invoice(invoice)
    loaded = repo.get_intake_invoice("claim-123")
    queued = repo.list_intake_invoices(source="pillar4_expense")

    assert loaded is not None
    assert loaded.invoice_id == "claim-123"
    assert loaded.vendor_name == "Uber"
    assert repo.count_intake_invoices() == 1
    assert len(queued) == 1
    assert queued[0].source == "pillar4_expense"
