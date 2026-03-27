"""Tests for AFA repository persistence."""

from __future__ import annotations

from pathlib import Path
import uuid
from datetime import date
from decimal import Decimal

from afa_engine.models import (
    AllocationResult,
    AllocationRunStatus,
    BudgetConstraint,
)
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
