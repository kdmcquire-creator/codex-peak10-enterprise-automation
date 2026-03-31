"""
Azure Functions HTTP triggers for the Expense Hub.

Endpoints:
  POST /api/transactions/classify  — Classify bank transactions
  POST /api/expenses/claim         — Create an expense claim (crosses the wall)
  POST /api/expenses/approve       — Approve a claim
  POST /api/expenses/push-to-ap    — Push approved claim to Pillar 1
  POST /api/expenses/attach-receipt — Attach a receipt from Pillar 2 email
  GET  /api/health                 — Health check
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import azure.functions as func

from expense_hub.classification_engine import ClassificationEngine
from expense_hub.chinese_wall import ChineseWall, ChineseWallViolation
from expense_hub.models import (
    BankTransaction,
    ClaimStatus,
    ExpenseBucket,
    ExpenseClaim,
)
from expense_hub.repository import get_repository
from expense_hub.pillar_clients import get_afa_engine_client
from expense_hub.serialization import (
    serialize_expense_claim,
    serialize_pillar1_payload,
    serialize_transaction,
)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
logger = logging.getLogger("expense-hub")

_engine = ClassificationEngine()
_wall = ChineseWall()
_repository = get_repository()


# ---------------------------------------------------------------------------
# POST /api/transactions/classify
# ---------------------------------------------------------------------------

@app.route(route="transactions/classify", methods=["POST"])
def classify_transactions(req: func.HttpRequest) -> func.HttpResponse:
    """
    Classify bank transactions from Plaid.

    Request body:
    {
      "transactions": [
        {"merchant_name": "Uber", "amount": "45.00", "date": "2026-03-14", "category": ["Travel"]}
      ]
    }
    """
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    raw_txns = body.get("transactions", [])
    if not raw_txns:
        return _error("'transactions' array is required", 400)

    transactions = []
    for t in raw_txns:
        try:
            txn = BankTransaction(
                plaid_transaction_id=t.get("plaid_transaction_id", ""),
                merchant_name=t.get("merchant_name", ""),
                amount=Decimal(str(t.get("amount", "0.00"))),
                date=date.fromisoformat(t["date"]) if "date" in t else date.today(),
                category=t.get("category", []),
            )
            transactions.append(txn)
        except (KeyError, ValueError, InvalidOperation) as e:
            return _error(f"Invalid transaction data: {e}", 400)

    classified = _engine.classify_batch(transactions)

    for txn in classified:
        _repository.save_transaction(txn)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "classified": [serialize_transaction(t) for t in classified],
            "summary": {
                "total": len(classified),
                "peak10": sum(1 for t in classified if t.bucket == ExpenseBucket.PEAK10),
                "personal": sum(1 for t in classified if t.bucket == ExpenseBucket.PERSONAL),
                "moonsmoke": sum(1 for t in classified if t.bucket == ExpenseBucket.MOONSMOKE_LLC),
                "unknown": sum(1 for t in classified if t.bucket == ExpenseBucket.UNKNOWN),
            },
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/expenses/claim
# ---------------------------------------------------------------------------

@app.route(route="expenses/claim", methods=["POST"])
def create_claim(req: func.HttpRequest) -> func.HttpResponse:
    """Create an expense claim from a classified transaction."""
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    txn_id = body.get("transaction_id")
    if not txn_id:
        return _error("'transaction_id' is required", 400)

    txn = _repository.get_transaction(txn_id)
    if not txn:
        return _error(f"Transaction '{txn_id}' not found", 404)

    try:
        claim = _wall.create_expense_claim(
            transaction=txn,
            employee_name=body.get("employee_name", "K. McQuire"),
            description=body.get("description", ""),
        )
    except ChineseWallViolation as e:
        return _error(str(e), 403)

    _repository.save_transaction(txn)
    _repository.save_claim(claim)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "claim": serialize_expense_claim(claim),
        }),
        mimetype="application/json",
        status_code=201,
    )


# ---------------------------------------------------------------------------
# POST /api/expenses/approve
# ---------------------------------------------------------------------------

@app.route(route="expenses/approve", methods=["POST"])
def approve_claim(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    claim_id = body.get("claim_id")
    claim = _repository.get_claim(claim_id)  # type: ignore[arg-type]
    if not claim:
        return _error(f"Claim '{claim_id}' not found", 404)

    if claim.status not in (ClaimStatus.DRAFT, ClaimStatus.SUBMITTED):
        return _error(f"Claim is '{claim.status.value}', cannot approve", 409)

    claim.status = ClaimStatus.APPROVED
    _repository.save_claim(claim)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "claim_id": claim_id,
            "status": "approved",
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/expenses/push-to-ap
# ---------------------------------------------------------------------------

@app.route(route="expenses/push-to-ap", methods=["POST"])
def push_to_ap(req: func.HttpRequest) -> func.HttpResponse:
    """Push an approved claim across the Chinese Wall to Pillar 1."""
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    claim_id = body.get("claim_id")
    claim = _repository.get_claim(claim_id)  # type: ignore[arg-type]
    if not claim:
        return _error(f"Claim '{claim_id}' not found", 404)

    try:
        payload = _wall.build_pillar1_payload(claim)
        _wall.validate_no_leak(payload)
    except ChineseWallViolation as e:
        return _error(str(e), 403)

    afa_engine = get_afa_engine_client()
    dispatch: dict[str, object]
    if not afa_engine.is_available:
        dispatch = {
            "attempted": False,
            "dispatched": False,
            "reason": "pillar1_not_configured",
        }
    else:
        try:
            response = afa_engine.intake_invoice(serialize_pillar1_payload(payload))
        except Exception as exc:
            logger.warning("Failed to dispatch claim %s to Pillar 1: %s", claim_id, exc)
            return _error(f"Failed to dispatch claim to Pillar 1: {exc}", 502)
        dispatch = {
            "attempted": True,
            "dispatched": bool(response.get("success", False)),
            "reason": "" if response.get("success", False) else "pillar1_intake_failed",
            "response": response,
        }
        if dispatch["dispatched"]:
            _wall.mark_pushed_to_pillar1(claim)
            _repository.save_claim(claim)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "claim_id": claim_id,
            "pillar1_payload": serialize_pillar1_payload(payload),
            "dispatch": dispatch,
            "audit_log_entries": len(_wall.audit_log),
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/expenses/attach-receipt
# ---------------------------------------------------------------------------

@app.route(route="expenses/attach-receipt", methods=["POST"])
def attach_receipt(req: func.HttpRequest) -> func.HttpResponse:
    """
    Attach a receipt from Pillar 2 (email) to a transaction.

    Request body:
    {
      "transaction_id": "...",
      "receipt_ref": "sharepoint-doc-id-123"
    }
    """
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    txn_id = body.get("transaction_id")
    receipt_ref = body.get("receipt_ref")

    if not txn_id or not receipt_ref:
        return _error("'transaction_id' and 'receipt_ref' are required", 400)

    txn = _repository.get_transaction(txn_id)
    if not txn:
        return _error(f"Transaction '{txn_id}' not found", 404)

    txn.receipt_ref = receipt_ref
    _repository.save_transaction(txn)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "transaction_id": txn_id,
            "receipt_ref": receipt_ref,
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps({
            "status": "healthy",
            "service": "expense-hub",
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "transactions_stored": _repository.count_transactions(),
            "claims_created": _repository.count_claims(),
            "wall_crossings": len(_wall.audit_log),
            "persistence": {
                "backend": "sqlite",
                "db_path": _repository.db_path,
            },
            "readiness": {
                "durable_storage_ready": True,
                "plaid_configured": bool(
                    os.environ.get("PLAID_CLIENT_ID") and os.environ.get("PLAID_SECRET")
                ),
                "receipt_routing_ready": bool(os.environ.get("PILLAR2_BASE_URL")),
                "pillar1_dispatch_ready": get_afa_engine_client().is_available,
            },
        }),
        mimetype="application/json",
        status_code=200,
    )


def _error(message: str, status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps({"success": False, "error": message}),
        mimetype="application/json",
        status_code=status_code,
    )
