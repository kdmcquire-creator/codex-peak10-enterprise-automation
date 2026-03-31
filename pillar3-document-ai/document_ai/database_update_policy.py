"""Policy and validation guardrails for database update proposals."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import DocumentType


DOCUMENT_TARGET_TABLE_MAP: dict[DocumentType, str] = {
    DocumentType.CONTRACT: "legal_contracts",
    DocumentType.AMENDMENT: "legal_contracts",
    DocumentType.NDA: "legal_contracts",
    DocumentType.PSA: "legal_contracts",
    DocumentType.LOI: "deal_pipeline",
    DocumentType.TITLE_OPINION: "deal_pipeline",
    DocumentType.DUE_DILIGENCE: "deal_pipeline",
    DocumentType.OPERATING_AGREEMENT: "governance_records",
    DocumentType.RESOLUTION: "governance_records",
    DocumentType.BOARD_MINUTES: "governance_records",
    DocumentType.INVOICE: "finance_ap_invoices",
    DocumentType.PAYMENT_SCHEDULE: "finance_ap_schedule",
    DocumentType.ACH_EXPORT: "finance_ap_schedule",
    DocumentType.TAX_FORM: "finance_tax_records",
    DocumentType.AUDIT_REPORT: "finance_audit_records",
    DocumentType.FIELD_REPORT: "operations_field_reports",
    DocumentType.AFE: "operations_afe_register",
    DocumentType.RUN_TICKET: "operations_run_tickets",
    DocumentType.DECLINE_CURVE: "operations_decline_curves",
    DocumentType.REGULATORY_FILING: "operations_regulatory",
    DocumentType.SAFETY_REPORT: "operations_safety",
    DocumentType.RECEIPT: "finance_receipts",
    DocumentType.EXPENSE_REPORT: "finance_receipts",
    DocumentType.CORRESPONDENCE: "document_registry",
    DocumentType.UNKNOWN: "document_registry",
}

COMMON_ALLOWED_FIELDS = {
    "document_type",
    "recommended_path",
    "standardized_name",
    "reference_number",
    "run_id",
    "content_hash",
    "state",
    "county",
    "notes",
}

ALLOWED_FIELDS_BY_TABLE: dict[str, set[str]] = {
    "legal_contracts": COMMON_ALLOWED_FIELDS
    | {
        "counterparty",
        "vendor_name",
        "effective_date",
        "expiration_date",
        "amount",
        "lease_name",
        "well_name",
    },
    "deal_pipeline": COMMON_ALLOWED_FIELDS
    | {
        "counterparty",
        "effective_date",
        "expiration_date",
        "amount",
        "lease_name",
        "well_name",
    },
    "governance_records": COMMON_ALLOWED_FIELDS
    | {
        "counterparty",
        "effective_date",
        "expiration_date",
    },
    "finance_ap_invoices": COMMON_ALLOWED_FIELDS
    | {
        "vendor_name",
        "counterparty",
        "amount",
        "effective_date",
        "payment_date",
        "invoice_number",
        "total_allocated",
    },
    "finance_ap_schedule": COMMON_ALLOWED_FIELDS
    | {
        "vendor_name",
        "amount",
        "effective_date",
        "payment_date",
        "record_count",
        "vendor_count",
        "total_allocated",
    },
    "finance_tax_records": COMMON_ALLOWED_FIELDS | {"vendor_name", "effective_date"},
    "finance_audit_records": COMMON_ALLOWED_FIELDS | {"counterparty", "effective_date"},
    "finance_receipts": COMMON_ALLOWED_FIELDS | {"vendor_name", "amount", "effective_date"},
    "operations_field_reports": COMMON_ALLOWED_FIELDS
    | {"well_name", "lease_name", "effective_date"},
    "operations_afe_register": COMMON_ALLOWED_FIELDS
    | {"well_name", "lease_name", "effective_date", "amount"},
    "operations_run_tickets": COMMON_ALLOWED_FIELDS | {"well_name", "effective_date", "amount"},
    "operations_decline_curves": COMMON_ALLOWED_FIELDS | {"well_name", "effective_date"},
    "operations_regulatory": COMMON_ALLOWED_FIELDS
    | {"well_name", "effective_date", "expiration_date"},
    "operations_safety": COMMON_ALLOWED_FIELDS | {"well_name", "effective_date"},
    "document_registry": COMMON_ALLOWED_FIELDS
    | {
        "vendor_name",
        "counterparty",
        "effective_date",
        "expiration_date",
        "amount",
        "well_name",
        "lease_name",
    },
}

REQUIRED_FIELDS_BY_TABLE: dict[str, set[str]] = {
    "legal_contracts": {"counterparty", "effective_date"},
    "deal_pipeline": {"counterparty"},
    "finance_ap_invoices": {"vendor_name", "amount"},
    "finance_ap_schedule": {"amount"},
    "finance_receipts": {"vendor_name", "amount"},
    "operations_afe_register": {"well_name"},
}

DATE_FIELD_NAMES = {"effective_date", "expiration_date", "payment_date"}
NUMERIC_FIELD_NAMES = {"amount", "total_allocated"}
COUNT_FIELD_NAMES = {"record_count", "vendor_count"}

MAX_TEXT_LEN = 400
SAFE_FIELD_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class PolicyEvaluation:
    target_table: str
    sanitized_updates: dict[str, Any] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trust_score: float = 0.0
    min_trust_score: float = 0.7
    allow_queue: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_table": self.target_table,
            "sanitized_updates": self.sanitized_updates,
            "violations": self.violations,
            "warnings": self.warnings,
            "trust_score": self.trust_score,
            "min_trust_score": self.min_trust_score,
            "allow_queue": self.allow_queue,
        }


def target_table_for_document_type(document_type: DocumentType) -> str:
    return DOCUMENT_TARGET_TABLE_MAP.get(document_type, "document_registry")


def evaluate_database_update_proposal(
    *,
    document_type: DocumentType,
    target_table: str,
    version_status: str,
    proposed_updates: dict[str, Any],
    confidence: float,
    min_trust_score: float = 0.7,
) -> PolicyEvaluation:
    allowed_fields = ALLOWED_FIELDS_BY_TABLE.get(target_table, COMMON_ALLOWED_FIELDS)
    required_fields = REQUIRED_FIELDS_BY_TABLE.get(target_table, set())
    evaluation = PolicyEvaluation(
        target_table=target_table,
        min_trust_score=max(0.0, min(min_trust_score, 1.0)),
    )

    if version_status != "final":
        evaluation.violations.append("version_status_must_be_final")

    sanitized: dict[str, Any] = {}
    for field_name, raw_value in proposed_updates.items():
        if not SAFE_FIELD_PATTERN.fullmatch(str(field_name)):
            evaluation.violations.append(f"invalid_field_name:{field_name}")
            continue
        if field_name not in allowed_fields:
            evaluation.warnings.append(f"field_not_allowed:{field_name}")
            continue

        normalized, field_error, field_warning = _normalize_and_validate_value(
            field_name,
            raw_value,
        )
        if field_error:
            evaluation.violations.append(f"{field_name}:{field_error}")
            continue
        if field_warning:
            evaluation.warnings.append(f"{field_name}:{field_warning}")
        if normalized is not None:
            sanitized[field_name] = normalized

    if not sanitized:
        evaluation.violations.append("no_valid_fields")

    missing_required = [name for name in sorted(required_fields) if name not in sanitized]
    for field_name in missing_required:
        evaluation.violations.append(f"missing_required:{field_name}")

    if confidence < 0.8:
        evaluation.warnings.append("low_classification_confidence")

    required_ratio = 1.0
    if required_fields:
        found_required = sum(1 for name in required_fields if name in sanitized)
        required_ratio = found_required / len(required_fields)

    richness_denominator = max(len(required_fields), 3)
    richness_ratio = min(len(sanitized) / richness_denominator, 1.0)
    version_bonus = 0.1 if version_status == "final" else -0.2

    score = (
        (max(0.0, min(confidence, 1.0)) * 0.55)
        + (required_ratio * 0.25)
        + (richness_ratio * 0.10)
        + version_bonus
        - (len(evaluation.warnings) * 0.05)
        - (len(evaluation.violations) * 0.20)
    )
    evaluation.trust_score = max(0.0, min(score, 1.0))
    evaluation.sanitized_updates = sanitized
    evaluation.allow_queue = (
        not evaluation.violations
        and bool(evaluation.sanitized_updates)
        and evaluation.trust_score >= evaluation.min_trust_score
    )
    return evaluation


def _normalize_and_validate_value(
    field_name: str,
    value: Any,
) -> tuple[Any | None, str, str]:
    if value is None:
        return None, "empty_value", ""

    if field_name in DATE_FIELD_NAMES:
        date_text = str(value).strip()
        if not DATE_PATTERN.fullmatch(date_text):
            return None, "invalid_date_format", ""
        return date_text, "", ""

    if field_name in NUMERIC_FIELD_NAMES:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None, "invalid_numeric_value", ""
        if amount < Decimal("0"):
            return None, "negative_numeric_value", ""
        return f"{amount:.2f}", "", ""

    if field_name in COUNT_FIELD_NAMES:
        try:
            count_value = int(value)
        except (TypeError, ValueError):
            return None, "invalid_integer_value", ""
        if count_value < 0:
            return None, "negative_integer_value", ""
        return count_value, "", ""

    if field_name in {"run_id", "reference_number", "content_hash"}:
        text = str(value).strip()
        if not SAFE_ID_PATTERN.fullmatch(text):
            return None, "unsafe_identifier_value", ""
        return text, "", ""

    if isinstance(value, (bool, int, float)):
        return value, "", ""

    text_value = str(value).strip()
    if not text_value:
        return None, "empty_value", ""
    if len(text_value) > MAX_TEXT_LEN:
        return text_value[:MAX_TEXT_LEN], "", "truncated_text"
    return text_value, "", ""
