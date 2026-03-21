"""
Document classification models — merged from Pillar 3.

Contains: DocumentType enum, folder hierarchy, filing map,
classification/filing result models, correction log model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Governed folder hierarchy
# ---------------------------------------------------------------------------

class TopLevelFolder(str, Enum):
    STAGING = "00_STAGING"
    CORPORATE = "01_CORPORATE"
    OPERATIONS = "02_OPERATIONS"
    DEALS = "03_DEALS"
    GOVERNANCE = "04_GOVERNANCE"


FOLDER_HIERARCHY: dict[TopLevelFolder, list[str]] = {
    TopLevelFolder.STAGING: [
        "Inbox",
        "Processing",
        "Errors",
    ],
    TopLevelFolder.CORPORATE: [
        "Legal",
        "Legal/Contracts",
        "Legal/Amendments",
        "Legal/NDAs",
        "Finance",
        "Finance/AP",
        "Finance/AR",
        "Finance/Tax",
        "Finance/Audit",
        "Insurance",
        "HR",
        "HR/Policies",
        "HR/Benefits",
    ],
    TopLevelFolder.OPERATIONS: [
        "Field_Reports",
        "Field_Reports/Daily",
        "Field_Reports/Weekly",
        "Well_Files",
        "AFEs",
        "Production",
        "Production/Decline_Curves",
        "Production/Run_Tickets",
        "Regulatory",
        "Regulatory/RRC",
        "Regulatory/EPA",
        "Vendor_Contracts",
        "Safety",
        "Safety/JSAs",
        "Safety/Incidents",
    ],
    TopLevelFolder.DEALS: [
        "Active",
        "Active/LOIs",
        "Active/PSAs",
        "Active/Due_Diligence",
        "Active/Title",
        "Closed",
        "Passed",
        "Pipeline",
    ],
    TopLevelFolder.GOVERNANCE: [
        "Board_Minutes",
        "Operating_Agreements",
        "Bylaws",
        "Resolutions",
        "Compliance",
        "Audit_Reports",
    ],
}


# ---------------------------------------------------------------------------
# Document types
# ---------------------------------------------------------------------------

class DocumentType(str, Enum):
    # Corporate / Legal
    CONTRACT = "contract"
    AMENDMENT = "amendment"
    NDA = "nda"
    INSURANCE_POLICY = "insurance_policy"
    # Finance
    INVOICE = "invoice"
    PAYMENT_SCHEDULE = "payment_schedule"
    ACH_EXPORT = "ach_export"
    TAX_FORM = "tax_form"
    AUDIT_REPORT = "audit_report"
    # Operations
    FIELD_REPORT = "field_report"
    AFE = "afe"
    RUN_TICKET = "run_ticket"
    DECLINE_CURVE = "decline_curve"
    REGULATORY_FILING = "regulatory_filing"
    SAFETY_REPORT = "safety_report"
    # Deals
    LOI = "loi"
    PSA = "psa"
    TITLE_OPINION = "title_opinion"
    DUE_DILIGENCE = "due_diligence"
    # Governance
    BOARD_MINUTES = "board_minutes"
    OPERATING_AGREEMENT = "operating_agreement"
    RESOLUTION = "resolution"
    # Expenses
    RECEIPT = "receipt"
    EXPENSE_REPORT = "expense_report"
    # Generic
    CORRESPONDENCE = "correspondence"
    UNKNOWN = "unknown"


DOCUMENT_FILING_MAP: dict[DocumentType, str] = {
    DocumentType.CONTRACT: "01_CORPORATE/Legal/Contracts",
    DocumentType.AMENDMENT: "01_CORPORATE/Legal/Amendments",
    DocumentType.NDA: "01_CORPORATE/Legal/NDAs",
    DocumentType.INSURANCE_POLICY: "01_CORPORATE/Insurance",
    DocumentType.INVOICE: "01_CORPORATE/Finance/AP",
    DocumentType.PAYMENT_SCHEDULE: "01_CORPORATE/Finance/AP",
    DocumentType.ACH_EXPORT: "01_CORPORATE/Finance/AP",
    DocumentType.TAX_FORM: "01_CORPORATE/Finance/Tax",
    DocumentType.AUDIT_REPORT: "01_CORPORATE/Finance/Audit",
    DocumentType.FIELD_REPORT: "02_OPERATIONS/Field_Reports",
    DocumentType.AFE: "02_OPERATIONS/AFEs",
    DocumentType.RUN_TICKET: "02_OPERATIONS/Production/Run_Tickets",
    DocumentType.DECLINE_CURVE: "02_OPERATIONS/Production/Decline_Curves",
    DocumentType.REGULATORY_FILING: "02_OPERATIONS/Regulatory",
    DocumentType.SAFETY_REPORT: "02_OPERATIONS/Safety",
    DocumentType.LOI: "03_DEALS/Active/LOIs",
    DocumentType.PSA: "03_DEALS/Active/PSAs",
    DocumentType.TITLE_OPINION: "03_DEALS/Active/Title",
    DocumentType.DUE_DILIGENCE: "03_DEALS/Active/Due_Diligence",
    DocumentType.BOARD_MINUTES: "04_GOVERNANCE/Board_Minutes",
    DocumentType.OPERATING_AGREEMENT: "04_GOVERNANCE/Operating_Agreements",
    DocumentType.RESOLUTION: "04_GOVERNANCE/Resolutions",
    DocumentType.RECEIPT: "01_CORPORATE/Finance/AP",
    DocumentType.EXPENSE_REPORT: "01_CORPORATE/Finance/AP",
    DocumentType.CORRESPONDENCE: "01_CORPORATE/Legal",
    DocumentType.UNKNOWN: "00_STAGING/Errors",
}


# ---------------------------------------------------------------------------
# Classification models
# ---------------------------------------------------------------------------

class ClassificationConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ExtractedMetadata:
    vendor_name: Optional[str] = None
    counterparty: Optional[str] = None
    effective_date: Optional[str] = None
    expiration_date: Optional[str] = None
    amount: Optional[str] = None
    well_name: Optional[str] = None
    lease_name: Optional[str] = None
    county: Optional[str] = None
    state: Optional[str] = None
    reference_number: Optional[str] = None
    custom_fields: dict[str, str] = field(default_factory=dict)


@dataclass
class ClassificationResult:
    document_type: DocumentType = DocumentType.UNKNOWN
    confidence: float = 0.0
    confidence_level: ClassificationConfidence = ClassificationConfidence.LOW
    metadata: ExtractedMetadata = field(default_factory=ExtractedMetadata)
    reasoning: str = ""


@dataclass
class FilingRecommendation:
    recommended_path: str = ""
    standardized_name: str = ""
    document_type: DocumentType = DocumentType.UNKNOWN
    confidence_level: ClassificationConfidence = ClassificationConfidence.LOW
    requires_review: bool = True
    alternative_paths: list[str] = field(default_factory=list)


@dataclass
class StagedDocument:
    document_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    original_filename: str = ""
    file_extension: str = ""
    source: str = "upload"
    source_detail: str = ""
    staged_at: datetime = field(default_factory=utc_now)
    file_size_bytes: int = 0
    content_hash: str = ""
    status: str = "pending"
    classification: Optional[ClassificationResult] = None
    filing: Optional[FilingRecommendation] = None


@dataclass
class CorrectionLog:
    correction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""
    original_type: DocumentType = DocumentType.UNKNOWN
    corrected_type: DocumentType = DocumentType.UNKNOWN
    original_path: str = ""
    corrected_path: str = ""
    corrected_by: str = ""
    corrected_at: datetime = field(default_factory=utc_now)
    notes: str = ""
