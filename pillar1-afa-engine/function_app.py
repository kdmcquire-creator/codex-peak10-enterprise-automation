"""
Azure Functions HTTP triggers for the AFA Engine.

Endpoints:
  POST /api/allocations/run       — Execute an allocation run
  POST /api/allocations/approve   — Approve a pending allocation
  POST /api/allocations/export    — Export approved allocation as ACH
  GET  /api/health                — Health check
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from decimal import InvalidOperation

import azure.functions as func

from afa_engine.allocation_engine import AllocationEngine
from afa_engine.ach_export import build_ach_records, render_nacha_flat, ACHExportError
from afa_engine.models import (
    ACHRecord,
    AllocationResult,
    AllocationRunStatus,
)
from afa_engine.pillar_clients import get_document_ai_client
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
    pillar3_stage = _stage_export_artifacts_in_pillar3(
        result=result,
        ach_records=ach_records,
        nacha_text=nacha_text,
    )

    return func.HttpResponse(
        body=json.dumps({
            "success": True,
            "run_id": run_id,
            "ach_records": [serialize_ach_record(r) for r in ach_records],
            "nacha_flat": nacha_text,
            "pillar3_stage": pillar3_stage,
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    document_ai = get_document_ai_client()
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
                "cross_pillar_filing_ready": document_ai.is_available,
            },
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stage_export_artifacts_in_pillar3(
    *,
    result: AllocationResult,
    ach_records: list[ACHRecord],
    nacha_text: str,
) -> dict[str, object]:
    client = get_document_ai_client()
    if not client.is_available:
        return {
            "attempted": False,
            "dispatched": False,
            "reason": "pillar3_not_configured",
            "artifacts": [],
        }

    created_on = result.created_at.date().isoformat()
    ach_filename = f"{created_on}_AP_ACH_Export_{result.run_id}.txt"
    schedule_filename = f"{created_on}_AP_PaymentSchedule_{result.run_id}.csv"
    payment_schedule_csv = _render_payment_schedule_csv(ach_records)

    artifact_specs = [
        {
            "document_id": f"{result.run_id}:ach_export",
            "document_type": "ach_export",
            "filename": ach_filename,
            "content_type": "text/plain",
            "content_bytes": nacha_text.encode("utf-8"),
            "source_metadata": {"artifact_type": "ach_export"},
        },
        {
            "document_id": f"{result.run_id}:payment_schedule",
            "document_type": "payment_schedule",
            "filename": schedule_filename,
            "content_type": "text/csv",
            "content_bytes": payment_schedule_csv.encode("utf-8"),
            "source_metadata": {"artifact_type": "payment_schedule"},
        },
    ]

    staged_artifacts: list[dict[str, object]] = []
    failed_count = 0
    for spec in artifact_specs:
        payload = _build_pillar3_stage_payload(
            result=result,
            ach_records=ach_records,
            document_id=str(spec["document_id"]),
            document_type=str(spec["document_type"]),
            filename=str(spec["filename"]),
            content_type=str(spec["content_type"]),
            content_bytes=spec["content_bytes"],  # type: ignore[arg-type]
            source_metadata=spec["source_metadata"],  # type: ignore[arg-type]
        )
        try:
            response = client.stage_document(payload)
            if isinstance(response, dict):
                document = response.get("document", {})
                success = bool(response.get("success", False))
            else:
                document = {}
                success = False
            if not success:
                failed_count += 1
            staged_artifacts.append(
                {
                    "document_type": spec["document_type"],
                    "attempted": True,
                    "dispatched": success,
                    "reason": "" if success else "pillar3_empty_response",
                    "document_id": str(document.get("document_id", payload["document_id"])),
                    "status": str(document.get("status", "")),
                }
            )
        except Exception as exc:
            failed_count += 1
            logger.warning(
                "Pillar 3 staging failed for run %s artifact %s: %s",
                result.run_id,
                spec["document_type"],
                exc,
            )
            staged_artifacts.append(
                {
                    "document_type": spec["document_type"],
                    "attempted": True,
                    "dispatched": False,
                    "reason": "pillar3_stage_failed",
                    "error": str(exc),
                }
            )

    return {
        "attempted": True,
        "dispatched": failed_count == 0,
        "partial": 0 < failed_count < len(artifact_specs),
        "reason": "" if failed_count == 0 else "pillar3_stage_failed",
        "artifacts": staged_artifacts,
    }


def _build_pillar3_stage_payload(
    *,
    result: AllocationResult,
    ach_records: list[ACHRecord],
    document_id: str,
    document_type: str,
    filename: str,
    content_type: str,
    content_bytes: bytes,
    source_metadata: dict[str, str],
) -> dict[str, object]:
    encoded = base64.b64encode(content_bytes).decode("utf-8")
    content_hash = f"sha256:{hashlib.sha256(content_bytes).hexdigest()}"
    classification = {
        "document_type": document_type,
        "confidence": 0.99,
        "confidence_level": "high",
        "metadata": {
            "reference_number": result.run_id,
            "custom_fields": {
                "run_id": result.run_id,
                "vendor_count": str(len(ach_records)),
                "record_count": str(len(ach_records)),
            },
        },
        "reasoning": "Generated by AFA Engine export workflow.",
    }
    filing = {
        "recommended_path": "01_CORPORATE/Finance/AP",
        "standardized_name": filename,
        "document_type": document_type,
        "confidence_level": "high",
        "requires_review": False,
        "alternative_paths": [],
    }
    extraction = {
        "run_id": result.run_id,
        "total_allocated": str(result.total_allocated),
        "record_count": len(ach_records),
        "vendor_count": len(ach_records),
    }
    return {
        "document_id": document_id,
        "filename": filename,
        "source": "pillar1",
        "source_detail": result.run_id,
        "source_metadata": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "run_status": result.status.value,
            "total_allocated": str(result.total_allocated),
            **source_metadata,
        },
        "content_type": content_type,
        "file_size_bytes": len(content_bytes),
        "content_hash": content_hash,
        "file_bytes_base64": encoded,
        "classification": classification,
        "filing": filing,
        "extraction": extraction,
    }


def _render_payment_schedule_csv(ach_records: list[ACHRecord]) -> str:
    rows = ["vendor_name,routing_number,account_number_masked,amount,payment_date,invoice_ids"]
    for record in ach_records:
        masked_account = (
            "****" + record.account_number[-4:]
            if len(record.account_number) >= 4
            else record.account_number
        )
        vendor_name = record.vendor_name.replace('"', '""')
        invoice_ids = ";".join(record.invoice_ids).replace('"', '""')
        rows.append(
            f'"{vendor_name}",{record.routing_number},"{masked_account}",'
            f"{record.amount},{record.payment_date.isoformat()},\"{invoice_ids}\""
        )
    return "\n".join(rows)


def _error(message: str, status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps({"success": False, "error": message}),
        mimetype="application/json",
        status_code=status_code,
    )
