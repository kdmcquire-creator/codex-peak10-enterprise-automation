"""
Azure Functions HTTP triggers for the AFA Engine.

Endpoints:
  POST /api/allocations/run       — Execute an allocation run
  POST /api/allocations/approve   — Approve a pending allocation
  POST /api/allocations/export    — Export approved allocation as ACH
  GET  /api/health                — Health check
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import azure.functions as func

from afa_engine.allocation_engine import AllocationEngine
from afa_engine.ach_export import build_ach_records, render_nacha_flat, ACHExportError
from afa_engine.models import (
    AllocationResult,
    AllocationRunStatus,
    BudgetConstraint,
    Vendor,
    currency,
)
from afa_engine.repository import get_repository
from afa_engine.serialization import (
    deserialize_budget,
    deserialize_invoice,
    deserialize_vendor,
    serialize_allocation_result,
    serialize_ach_record,
)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
logger = logging.getLogger("afa-engine")


_repository = get_repository()


# ---------------------------------------------------------------------------
# POST /api/allocations/run
# ---------------------------------------------------------------------------

@app.route(route="allocations/run", methods=["POST"])
def run_allocation(req: func.HttpRequest) -> func.HttpResponse:
    """
    Execute a new allocation run.

    Request body:
    {
      "budget": {"total_budget": "500000.00", "reserved_amount": "25000.00"},
      "invoices": [ ... ]
    }
    """
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON in request body", 400)

    if "budget" not in body or "invoices" not in body:
        return _error("Request must include 'budget' and 'invoices'", 400)

    try:
        budget = deserialize_budget(body["budget"])
        invoices = [deserialize_invoice(inv) for inv in body["invoices"]]
    except (KeyError, ValueError, InvalidOperation) as e:
        return _error(f"Invalid input data: {e}", 400)

    if not invoices:
        return _error("At least one invoice is required", 400)

    engine = AllocationEngine(budget=budget, invoices=invoices)
    result = engine.run()

    _repository.save(result)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "allocation": serialize_allocation_result(result),
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/allocations/approve
# ---------------------------------------------------------------------------

@app.route(route="allocations/approve", methods=["POST"])
def approve_allocation(req: func.HttpRequest) -> func.HttpResponse:
    """
    Approve a pending allocation run.

    Request body: {"run_id": "..."}
    """
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    run_id = body.get("run_id")
    if not run_id:
        return _error("'run_id' is required", 400)

    result = _repository.get(run_id)
    if not result:
        return _error(f"Allocation run '{run_id}' not found", 404)

    if result.status != AllocationRunStatus.PENDING_APPROVAL:
        return _error(
            f"Run is '{result.status.value}', must be 'pending_approval'", 409
        )

    result.status = AllocationRunStatus.APPROVED
    _repository.save(result)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "run_id": run_id,
            "status": result.status.value,
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# POST /api/allocations/export
# ---------------------------------------------------------------------------

@app.route(route="allocations/export", methods=["POST"])
def export_allocation(req: func.HttpRequest) -> func.HttpResponse:
    """
    Export an approved allocation as ACH records.

    Request body: {"run_id": "...", "vendors": [...]}
    """
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON", 400)

    run_id = body.get("run_id")
    if not run_id:
        return _error("'run_id' is required", 400)

    result = _repository.get(run_id)
    if not result:
        return _error(f"Allocation run '{run_id}' not found", 404)

    vendor_list = body.get("vendors", [])
    if not vendor_list:
        return _error("'vendors' array is required for ACH export", 400)

    try:
        vendors = {v["vendor_id"]: deserialize_vendor(v) for v in vendor_list}
        for v_data in vendor_list:
            vid = v_data["vendor_id"]
            vendors[vid].ach_routing_number = v_data.get("ach_routing_number")
            vendors[vid].ach_account_number = v_data.get("ach_account_number")
    except (KeyError, ValueError) as e:
        return _error(f"Invalid vendor data: {e}", 400)

    try:
        ach_records = build_ach_records(result, vendors)
    except ACHExportError as e:
        return _error(str(e), 409)

    result.status = AllocationRunStatus.EXPORTED
    nacha_text = render_nacha_flat(ach_records)
    _repository.save(result)

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "run_id": run_id,
            "ach_records": [serialize_ach_record(r) for r in ach_records],
            "nacha_flat": nacha_text,
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
            "service": "afa-engine",
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "persistence": {
                "backend": "sqlite",
                "db_path": _repository.db_path,
                "allocation_runs_stored": _repository.count_runs(),
            },
            "readiness": {
                "durable_storage_ready": True,
                "approval_workflow_ready": False,
                "cross_pillar_filing_ready": bool(os.environ.get("PILLAR3_BASE_URL")),
            },
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error(message: str, status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps({"success": False, "error": message}),
        mimetype="application/json",
        status_code=status_code,
    )
