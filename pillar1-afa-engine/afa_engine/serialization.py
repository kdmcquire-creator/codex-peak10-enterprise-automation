"""
JSON serialization / deserialization for AFA Engine models.

Converts between domain objects and JSON-safe dicts for API transport.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from .models import (
    ACHRecord,
    AllocationLineItem,
    AllocationResult,
    AllocationRunStatus,
    BudgetConstraint,
    Invoice,
    InvoiceStatus,
    Vendor,
    VendorPriority,
    currency,
)


# ---------------------------------------------------------------------------
# Serializers (model → dict)
# ---------------------------------------------------------------------------

def serialize_vendor(v: Vendor) -> dict[str, Any]:
    return {
        "vendor_id": v.vendor_id,
        "name": v.name,
        "priority": v.priority.value,
        "priority_label": v.priority.name,
        "payment_terms_days": v.payment_terms_days,
        "is_active": v.is_active,
    }


def serialize_invoice(inv: Invoice) -> dict[str, Any]:
    return {
        "invoice_id": inv.invoice_id,
        "vendor_id": inv.vendor_id,
        "vendor_name": inv.vendor_name,
        "vendor_priority": inv.vendor_priority.value,
        "amount_due": str(inv.amount_due),
        "amount_allocated": str(inv.amount_allocated),
        "amount_remaining": str(inv.amount_remaining),
        "due_date": inv.due_date.isoformat(),
        "description": inv.description,
        "status": inv.status.value,
        "source": inv.source,
    }


def serialize_line_item(item: AllocationLineItem) -> dict[str, Any]:
    return {
        "invoice_id": item.invoice_id,
        "vendor_id": item.vendor_id,
        "vendor_name": item.vendor_name,
        "vendor_priority": item.vendor_priority.value,
        "invoice_amount": str(item.invoice_amount),
        "allocated_amount": str(item.allocated_amount),
        "allocation_pass": item.allocation_pass,
        "is_partial": item.is_partial,
        "notes": item.notes,
    }


def serialize_allocation_result(r: AllocationResult) -> dict[str, Any]:
    return {
        "run_id": r.run_id,
        "status": r.status.value,
        "budget": {
            "total_budget": str(r.budget.total_budget),
            "reserved_amount": str(r.budget.reserved_amount),
            "allocatable_budget": str(r.budget.allocatable_budget),
        },
        "total_allocated": str(r.total_allocated),
        "total_deferred": str(r.total_deferred),
        "budget_remaining": str(r.budget_remaining),
        "utilization_pct": str(r.utilization_pct),
        "line_items": [serialize_line_item(i) for i in r.line_items],
        "deferred_items": [serialize_line_item(i) for i in r.deferred_items],
        "pass_summaries": r.pass_summaries,
        "created_at": r.created_at.isoformat(),
    }


def serialize_ach_record(r: ACHRecord) -> dict[str, Any]:
    masked_acct = (
        "****" + r.account_number[-4:]
        if len(r.account_number) >= 4
        else r.account_number
    )
    return {
        "record_id": r.record_id,
        "vendor_name": r.vendor_name,
        "routing_number": r.routing_number,
        "account_number_masked": masked_acct,
        "amount": str(r.amount),
        "invoice_ids": r.invoice_ids,
        "payment_date": r.payment_date.isoformat(),
    }


# ---------------------------------------------------------------------------
# Deserializers (dict → model)
# ---------------------------------------------------------------------------

def deserialize_vendor(data: dict[str, Any]) -> Vendor:
    return Vendor(
        vendor_id=data.get("vendor_id", ""),
        name=data["name"],
        priority=VendorPriority(data["priority"]),
        payment_terms_days=data.get("payment_terms_days", 30),
        ach_routing_number=data.get("ach_routing_number"),
        ach_account_number=data.get("ach_account_number"),
        is_active=data.get("is_active", True),
    )


def deserialize_invoice(data: dict[str, Any]) -> Invoice:
    return Invoice(
        invoice_id=data.get("invoice_id", ""),
        vendor_id=data["vendor_id"],
        vendor_name=data.get("vendor_name", ""),
        vendor_priority=VendorPriority(data["vendor_priority"]),
        amount_due=currency(data["amount_due"]),
        amount_allocated=currency(data.get("amount_allocated", "0.00")),
        due_date=date.fromisoformat(data["due_date"]),
        description=data.get("description", ""),
        status=InvoiceStatus(data.get("status", "pending")),
        source=data.get("source", "manual"),
    )


def deserialize_budget(data: dict[str, Any]) -> BudgetConstraint:
    return BudgetConstraint(
        total_budget=currency(data["total_budget"]),
        reserved_amount=currency(data.get("reserved_amount", "0.00")),
    )


def deserialize_line_item(data: dict[str, Any]) -> AllocationLineItem:
    return AllocationLineItem(
        invoice_id=data.get("invoice_id", ""),
        vendor_id=data.get("vendor_id", ""),
        vendor_name=data.get("vendor_name", ""),
        vendor_priority=VendorPriority(data.get("vendor_priority", VendorPriority.STANDARD.value)),
        invoice_amount=currency(data.get("invoice_amount", "0.00")),
        allocated_amount=currency(data.get("allocated_amount", "0.00")),
        allocation_pass=int(data.get("allocation_pass", 0)),
        is_partial=bool(data.get("is_partial", False)),
        notes=data.get("notes", ""),
    )


def deserialize_allocation_result(data: dict[str, Any]) -> AllocationResult:
    budget_data = data.get("budget", {})
    return AllocationResult(
        run_id=data.get("run_id", ""),
        status=AllocationRunStatus(data.get("status", AllocationRunStatus.DRAFT.value)),
        budget=deserialize_budget(budget_data),
        total_allocated=currency(data.get("total_allocated", "0.00")),
        total_deferred=currency(data.get("total_deferred", "0.00")),
        budget_remaining=currency(data.get("budget_remaining", "0.00")),
        line_items=[
            deserialize_line_item(item)
            for item in data.get("line_items", [])
        ],
        deferred_items=[
            deserialize_line_item(item)
            for item in data.get("deferred_items", [])
        ],
        pass_summaries=data.get("pass_summaries", []),
        created_at=datetime.fromisoformat(data["created_at"])
        if data.get("created_at")
        else datetime.now(timezone.utc),
    )
