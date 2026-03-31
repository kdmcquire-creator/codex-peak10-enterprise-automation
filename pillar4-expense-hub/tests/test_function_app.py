"""Tests for Expense Hub function endpoints."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from expense_hub.repository import ExpenseHubRepository
from function_app import (
    approve_claim,
    classify_transactions,
    create_claim,
    health_check,
    push_to_ap,
)


class FakeRequest:
    def __init__(self, body: dict | None = None) -> None:
        self._body = body
        self.params = {}
        self.route_params = {}

    def get_json(self):
        if self._body is None:
            raise ValueError("No JSON body")
        return self._body


class FakeAfaEngineClient:
    def __init__(self, *, available: bool = True, raise_error: Exception | None = None) -> None:
        self.is_available = available
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def intake_invoice(self, payload: dict) -> dict:
        self.calls.append(payload)
        if self.raise_error is not None:
            raise self.raise_error
        return {
            "success": True,
            "invoice": payload,
            "queue_count": 1,
        }


def _build_repo() -> ExpenseHubRepository:
    base_dir = Path.cwd() / ".pytest-tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    return ExpenseHubRepository(db_path=str(base_dir / f"expense-{uuid.uuid4().hex}.db"))


def test_expense_flow_push_to_ap_returns_sanitized_payload(monkeypatch):
    repo = _build_repo()
    monkeypatch.setattr("function_app._repository", repo)
    afa_engine = FakeAfaEngineClient(available=True)
    monkeypatch.setattr("function_app.get_afa_engine_client", lambda: afa_engine)

    classify_response = classify_transactions(
        FakeRequest(
            {
                "transactions": [
                    {
                        "merchant_name": "Uber",
                        "amount": "35.00",
                        "date": "2026-03-29",
                        "category": ["Travel"],
                    }
                ]
            }
        )
    )
    classify_payload = json.loads(classify_response.get_body().decode("utf-8"))
    transaction_id = classify_payload["classified"][0]["transaction_id"]
    assert classify_payload["classified"][0]["bucket"] == "peak10"

    claim_response = create_claim(
        FakeRequest(
            {
                "transaction_id": transaction_id,
                "employee_name": "Smoke Test User",
                "description": "Automated test expense",
            }
        )
    )
    claim_payload = json.loads(claim_response.get_body().decode("utf-8"))
    claim_id = claim_payload["claim"]["claim_id"]

    approve_response = approve_claim(FakeRequest({"claim_id": claim_id}))
    approve_payload = json.loads(approve_response.get_body().decode("utf-8"))
    assert approve_payload["status"] == "approved"

    push_response = push_to_ap(FakeRequest({"claim_id": claim_id}))
    push_payload = json.loads(push_response.get_body().decode("utf-8"))

    assert push_response.status_code == 200
    assert push_payload["success"] is True
    assert push_payload["claim_id"] == claim_id
    assert push_payload["pillar1_payload"]["invoice_id"] == claim_id
    assert push_payload["pillar1_payload"]["source"] == "pillar4_expense"
    assert push_payload["pillar1_payload"]["vendor_name"] == "Uber"
    assert push_payload["pillar1_payload"]["amount_due"] == "35.00"
    assert push_payload["dispatch"]["attempted"] is True
    assert push_payload["dispatch"]["dispatched"] is True
    assert len(afa_engine.calls) == 1
    assert push_payload["audit_log_entries"] == 2


def test_push_to_ap_leaves_claim_approved_when_pillar1_not_configured(monkeypatch):
    repo = _build_repo()
    monkeypatch.setattr("function_app._repository", repo)
    monkeypatch.setattr(
        "function_app.get_afa_engine_client",
        lambda: FakeAfaEngineClient(available=False),
    )

    classify_payload = json.loads(
        classify_transactions(
            FakeRequest(
                {
                    "transactions": [
                        {
                            "merchant_name": "Uber",
                            "amount": "35.00",
                            "date": "2026-03-29",
                            "category": ["Travel"],
                        }
                    ]
                }
            )
        ).get_body().decode("utf-8")
    )
    transaction_id = classify_payload["classified"][0]["transaction_id"]
    claim_payload = json.loads(
        create_claim(
            FakeRequest(
                {
                    "transaction_id": transaction_id,
                    "employee_name": "Smoke Test User",
                    "description": "Automated test expense",
                }
            )
        ).get_body().decode("utf-8")
    )
    claim_id = claim_payload["claim"]["claim_id"]
    approve_claim(FakeRequest({"claim_id": claim_id}))

    response = push_to_ap(FakeRequest({"claim_id": claim_id}))
    payload = json.loads(response.get_body().decode("utf-8"))
    stored = repo.get_claim(claim_id)

    assert response.status_code == 200
    assert payload["dispatch"]["attempted"] is False
    assert payload["dispatch"]["reason"] == "pillar1_not_configured"
    assert stored is not None
    assert stored.status.value == "approved"


def test_health_check_reports_repository_state(monkeypatch):
    repo = _build_repo()
    monkeypatch.setattr("function_app._repository", repo)
    monkeypatch.setattr("function_app.get_afa_engine_client", lambda: FakeAfaEngineClient(available=True))

    response = health_check(FakeRequest({}))
    payload = json.loads(response.get_body().decode("utf-8"))

    assert response.status_code == 200
    assert payload["status"] == "healthy"
    assert payload["transactions_stored"] == 0
    assert payload["claims_created"] == 0
    assert payload["persistence"]["backend"] == "sqlite"
    assert payload["readiness"]["pillar1_dispatch_ready"] is True
