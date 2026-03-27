"""Tests for AFA Engine function app endpoints and cross-pillar wiring."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import uuid

from afa_engine.models import (
    AllocationLineItem,
    AllocationResult,
    AllocationRunStatus,
    BudgetConstraint,
    VendorPriority,
)
from afa_engine.repository import AllocationRunRepository
from function_app import export_allocation, health_check


class FakeRequest:
    def __init__(self, body: dict | None = None) -> None:
        self._body = body
        self.params = {}
        self.route_params = {}

    def get_json(self):
        if self._body is None:
            raise ValueError("No JSON body")
        return self._body


class FakeDocumentAiClient:
    def __init__(self, *, available: bool = True, raise_error: Exception | None = None) -> None:
        self.is_available = available
        self.raise_error = raise_error
        self.calls: list[dict[str, object]] = []

    def stage_document(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        if self.raise_error is not None:
            raise self.raise_error
        return {
            "success": True,
            "document": {
                "document_id": payload.get("document_id", ""),
                "status": "classified",
            },
        }


def _seed_approved_run(repo: AllocationRunRepository, run_id: str = "run-123") -> AllocationResult:
    result = AllocationResult(
        run_id=run_id,
        status=AllocationRunStatus.APPROVED,
        budget=BudgetConstraint(
            total_budget=Decimal("1000.00"),
            reserved_amount=Decimal("100.00"),
        ),
        total_allocated=Decimal("500.00"),
        total_deferred=Decimal("0.00"),
        budget_remaining=Decimal("400.00"),
        created_at=datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc),
        line_items=[
            AllocationLineItem(
                invoice_id="inv-1",
                vendor_id="v-1",
                vendor_name="Vendor One",
                vendor_priority=VendorPriority.HIGH,
                invoice_amount=Decimal("500.00"),
                allocated_amount=Decimal("500.00"),
                allocation_pass=1,
                is_partial=False,
            )
        ],
    )
    repo.save(result)
    return result


def _export_body(run_id: str = "run-123") -> dict[str, object]:
    return {
        "run_id": run_id,
        "vendors": [
            {
                "vendor_id": "v-1",
                "name": "Vendor One",
                "priority": 2,
                "ach_routing_number": "111000025",
                "ach_account_number": "1234567890",
            }
        ],
    }


def _build_repo() -> AllocationRunRepository:
    base_dir = Path.cwd() / ".pytest-tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    return AllocationRunRepository(db_path=str(base_dir / f"afa-{uuid.uuid4().hex}.db"))


def test_export_allocation_dispatches_ach_and_schedule_to_pillar3(monkeypatch):
    repo = _build_repo()
    _seed_approved_run(repo)
    document_ai = FakeDocumentAiClient(available=True)

    monkeypatch.setattr("function_app._repository", repo)
    monkeypatch.setattr("function_app.get_document_ai_client", lambda: document_ai)

    response = export_allocation(FakeRequest(_export_body()))
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["export_complete"] is True
    assert payload["allocation_status"] == "exported"
    assert payload["pillar3_stage"]["attempted"] is True
    assert payload["pillar3_stage"]["dispatched"] is True
    assert len(document_ai.calls) == 2
    saved = repo.get("run-123")
    assert saved is not None
    assert saved.status == AllocationRunStatus.EXPORTED

    staged_types = {
        str(call["classification"]["document_type"])  # type: ignore[index]
        for call in document_ai.calls
    }
    assert staged_types == {"ach_export", "payment_schedule"}
    assert {str(call["document_id"]) for call in document_ai.calls} == {
        "run-123:ach_export",
        "run-123:payment_schedule",
    }
    assert all(isinstance(call.get("file_bytes_base64"), str) for call in document_ai.calls)


def test_export_allocation_skips_pillar3_when_not_configured(monkeypatch):
    repo = _build_repo()
    _seed_approved_run(repo)
    document_ai = FakeDocumentAiClient(available=False)

    monkeypatch.setattr("function_app._repository", repo)
    monkeypatch.setattr("function_app.get_document_ai_client", lambda: document_ai)

    response = export_allocation(FakeRequest(_export_body()))
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["export_complete"] is False
    assert payload["allocation_status"] == "approved"
    assert payload["pillar3_stage"]["attempted"] is False
    assert payload["pillar3_stage"]["reason"] == "pillar3_not_configured"
    assert document_ai.calls == []
    saved = repo.get("run-123")
    assert saved is not None
    assert saved.status == AllocationRunStatus.APPROVED


def test_export_allocation_records_pillar3_failures_without_blocking_export(monkeypatch):
    repo = _build_repo()
    _seed_approved_run(repo)
    document_ai = FakeDocumentAiClient(
        available=True,
        raise_error=RuntimeError("stage unavailable"),
    )

    monkeypatch.setattr("function_app._repository", repo)
    monkeypatch.setattr("function_app.get_document_ai_client", lambda: document_ai)

    response = export_allocation(FakeRequest(_export_body()))
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["export_complete"] is False
    assert payload["allocation_status"] == "approved"
    assert payload["pillar3_stage"]["attempted"] is True
    assert payload["pillar3_stage"]["dispatched"] is False
    assert payload["pillar3_stage"]["reason"] == "pillar3_stage_failed"
    assert len(payload["pillar3_stage"]["artifacts"]) == 2
    assert all(
        artifact["reason"] == "pillar3_stage_failed"
        for artifact in payload["pillar3_stage"]["artifacts"]
    )
    saved = repo.get("run-123")
    assert saved is not None
    assert saved.status == AllocationRunStatus.APPROVED


def test_health_check_uses_document_ai_client_readiness(monkeypatch):
    monkeypatch.setattr(
        "function_app.get_document_ai_client",
        lambda: FakeDocumentAiClient(available=True),
    )
    response = health_check(FakeRequest({}))
    payload = json.loads(response.get_body().decode("utf-8"))
    assert response.status_code == 200
    assert payload["readiness"]["cross_pillar_filing_ready"] is True
