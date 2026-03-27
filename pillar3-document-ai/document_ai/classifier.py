"""
Document classification engine.

Uses a two-tier approach:
  1. Rule-based pre-classifier: fast pattern matching on filename,
     extension, and known keywords to produce a candidate type.
  2. AI classifier: calls Azure OpenAI to analyze document content
     when rule-based confidence is below threshold.

The rule-based layer handles ~70% of documents (invoices, receipts,
field reports with predictable naming). AI handles the rest.
"""

from __future__ import annotations

import re
from typing import Optional

from .models import (
    ClassificationConfidence,
    ClassificationResult,
    DocumentType,
    ExtractedMetadata,
)


# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

HIGH_CONFIDENCE_THRESHOLD = 0.85
MEDIUM_CONFIDENCE_THRESHOLD = 0.60


def _confidence_level(score: float) -> ClassificationConfidence:
    if score >= HIGH_CONFIDENCE_THRESHOLD:
        return ClassificationConfidence.HIGH
    if score >= MEDIUM_CONFIDENCE_THRESHOLD:
        return ClassificationConfidence.MEDIUM
    return ClassificationConfidence.LOW


# ---------------------------------------------------------------------------
# Rule-based patterns
# ---------------------------------------------------------------------------

# (regex_pattern, document_type, confidence)
FILENAME_RULES: list[tuple[str, DocumentType, float]] = [
    # Finance
    (r"(?i)invoice[_\s\-]", DocumentType.INVOICE, 0.90),
    (r"(?i)payment[_\s\-]?schedule", DocumentType.PAYMENT_SCHEDULE, 0.92),
    (r"(?i)ach[_\s\-]?export", DocumentType.ACH_EXPORT, 0.95),
    (r"(?i)receipt", DocumentType.RECEIPT, 0.88),
    (r"(?i)expense[_\s\-]?report", DocumentType.EXPENSE_REPORT, 0.90),
    (r"(?i)(w[\-]?9|1099|w[\-]?2)", DocumentType.TAX_FORM, 0.92),
    # Legal — specific types BEFORE generic "contract/agreement"
    (r"(?i)amend(ment)?", DocumentType.AMENDMENT, 0.90),
    (r"(?i)nda|non[\-_]?disclosure", DocumentType.NDA, 0.92),
    (r"(?i)operating[\-_]?agreement", DocumentType.OPERATING_AGREEMENT, 0.92),
    (r"(?i)(psa|purchase[\-_\s]*(and[\-_\s]*)?sale[\-_\s]*agreement)", DocumentType.PSA, 0.90),
    (r"(?i)(contract|msa[\-_\s]|msa$)", DocumentType.CONTRACT, 0.85),
    (r"(?i)insurance|policy[\-_]?cert", DocumentType.INSURANCE_POLICY, 0.88),
    # Operations
    (r"(?i)field[\-_]?report|daily[\-_]?report", DocumentType.FIELD_REPORT, 0.88),
    (r"(?i)afe[\-_\s]|auth.*expenditure", DocumentType.AFE, 0.90),
    (r"(?i)run[\-_]?ticket", DocumentType.RUN_TICKET, 0.92),
    (r"(?i)decline[\-_]?curve", DocumentType.DECLINE_CURVE, 0.90),
    (r"(?i)(rrc|railroad[\-_]?comm|epa[\-_]?filing)", DocumentType.REGULATORY_FILING, 0.88),
    (r"(?i)(jsa|safety[\-_]?report|incident)", DocumentType.SAFETY_REPORT, 0.85),
    # Deals
    (r"(?i)(loi|letter[\-_]?of[\-_]?intent)", DocumentType.LOI, 0.90),
    (r"(?i)title[\-_]?opinion", DocumentType.TITLE_OPINION, 0.92),
    (r"(?i)due[\-_]?diligence", DocumentType.DUE_DILIGENCE, 0.85),
    # Governance
    (r"(?i)board[\-_]?minutes|meeting[\-_]?minutes", DocumentType.BOARD_MINUTES, 0.90),
    (r"(?i)resolution", DocumentType.RESOLUTION, 0.85),
    (r"(?i)audit[\-_]?report", DocumentType.AUDIT_REPORT, 0.88),
]

# Content-based keyword patterns (applied to extracted text)
CONTENT_RULES: list[tuple[str, DocumentType, float]] = [
    (r"(?i)invoice\s+(number|no|#)", DocumentType.INVOICE, 0.80),
    (r"(?i)authorization\s+for\s+expenditure", DocumentType.AFE, 0.85),
    (r"(?i)non[\-\s]?disclosure\s+agreement", DocumentType.NDA, 0.88),
    (r"(?i)purchase\s+and\s+sale\s+agreement", DocumentType.PSA, 0.85),
    (r"(?i)letter\s+of\s+intent", DocumentType.LOI, 0.85),
    (r"(?i)title\s+opinion", DocumentType.TITLE_OPINION, 0.88),
    (r"(?i)minutes\s+of\s+(the\s+)?board", DocumentType.BOARD_MINUTES, 0.88),
    (r"(?i)railroad\s+commission|rrc\s+form", DocumentType.REGULATORY_FILING, 0.85),
    (r"(?i)daily\s+(drilling|production)\s+report", DocumentType.FIELD_REPORT, 0.85),
    (r"(?i)decline\s+curve\s+analysis", DocumentType.DECLINE_CURVE, 0.82),
]

FINAL_VERSION_PATTERNS: list[str] = [
    r"(?i)(?:^|[_\-\s])vF(?:$|[_\-\s\.])",
    r"(?i)(?:^|[_\-\s])Executed(?:$|[_\-\s\.])",
    r"(?i)(?:^|[_\-\s])ExecutionVersion(?:$|[_\-\s\.])",
    r"(?i)\bfully\s+executed\b",
    r"(?i)\bexecution\s+version\b",
]

WIP_VERSION_PATTERNS: list[str] = [
    r"(?i)(?:^|[_\-\s])v\d{1,3}(?:$|[_\-\s\.])",
    r"(?i)\bdraft\b",
    r"(?i)\bwork[\-\s]?in[\-\s]?progress\b",
]


# ---------------------------------------------------------------------------
# Rule-based classifier
# ---------------------------------------------------------------------------

def classify_by_filename(filename: str) -> Optional[ClassificationResult]:
    """Classify a document based on filename patterns."""
    for pattern, doc_type, confidence in FILENAME_RULES:
        if re.search(pattern, filename):
            return ClassificationResult(
                document_type=doc_type,
                confidence=confidence,
                confidence_level=_confidence_level(confidence),
                reasoning=f"Filename matched pattern: {pattern}",
            )
    return None


def classify_by_content(text: str) -> Optional[ClassificationResult]:
    """Classify a document based on content keyword patterns."""
    best_match: Optional[ClassificationResult] = None
    best_confidence = 0.0

    for pattern, doc_type, confidence in CONTENT_RULES:
        if re.search(pattern, text) and confidence > best_confidence:
            best_confidence = confidence
            best_match = ClassificationResult(
                document_type=doc_type,
                confidence=confidence,
                confidence_level=_confidence_level(confidence),
                reasoning=f"Content matched pattern: {pattern}",
            )

    return best_match


# ---------------------------------------------------------------------------
# AI classifier (Azure OpenAI integration point)
# ---------------------------------------------------------------------------

def build_classification_prompt(filename: str, text_preview: str) -> str:
    """
    Build the prompt sent to Azure OpenAI for document classification.

    Returns the prompt string. The actual API call is handled by the
    Azure Function layer (which manages credentials and retry logic).
    """
    doc_types = ", ".join(dt.value for dt in DocumentType if dt != DocumentType.UNKNOWN)

    return f"""You are a document classification assistant for Peak 10 Energy,
an upstream oil & gas company in the Permian Basin.

Classify the following document into exactly one of these types:
{doc_types}

Also extract any metadata you can identify:
- vendor_name, counterparty, effective_date, expiration_date, amount
- well_name, lease_name, county, state, reference_number

Filename: {filename}

Document text (first 2000 chars):
---
{text_preview[:2000]}
---

Respond in JSON format:
{{
  "document_type": "<type>",
  "confidence": <0.0-1.0>,
  "reasoning": "<brief explanation>",
  "metadata": {{
    "vendor_name": "<or null>",
    "counterparty": "<or null>",
    "effective_date": "<YYYY-MM-DD or null>",
    "expiration_date": "<YYYY-MM-DD or null>",
    "amount": "<or null>",
    "well_name": "<or null>",
    "lease_name": "<or null>",
    "county": "<or null>",
    "state": "<or null>",
    "reference_number": "<or null>"
  }}
}}"""


def parse_ai_classification(ai_response: dict) -> ClassificationResult:
    """Parse the JSON response from Azure OpenAI into a ClassificationResult."""
    try:
        doc_type = DocumentType(ai_response.get("document_type", "unknown"))
    except ValueError:
        doc_type = DocumentType.UNKNOWN

    confidence = float(ai_response.get("confidence", 0.0))
    meta_raw = ai_response.get("metadata", {})

    metadata = ExtractedMetadata(
        vendor_name=meta_raw.get("vendor_name"),
        counterparty=meta_raw.get("counterparty"),
        effective_date=meta_raw.get("effective_date"),
        expiration_date=meta_raw.get("expiration_date"),
        amount=meta_raw.get("amount"),
        well_name=meta_raw.get("well_name"),
        lease_name=meta_raw.get("lease_name"),
        county=meta_raw.get("county"),
        state=meta_raw.get("state"),
        reference_number=meta_raw.get("reference_number"),
    )

    return ClassificationResult(
        document_type=doc_type,
        confidence=confidence,
        confidence_level=_confidence_level(confidence),
        metadata=metadata,
        reasoning=ai_response.get("reasoning", ""),
    )


# ---------------------------------------------------------------------------
# Unified classifier pipeline
# ---------------------------------------------------------------------------

def classify_document(
    filename: str,
    content_text: Optional[str] = None,
    ai_response: Optional[dict] = None,
) -> ClassificationResult:
    """
    Unified classification pipeline:
      1. Try filename rules (fast, high confidence for known patterns)
      2. Try content rules if text is available
      3. Use AI classification if provided
      4. Fall back to UNKNOWN

    The AI call itself is made externally (by the Azure Function) and
    passed in as ai_response. This keeps the classifier pure and testable.
    """
    result: Optional[ClassificationResult] = None

    # Tier 1: content keywords (content-first)
    if content_text:
        content_result = classify_by_content(content_text)
        if content_result:
            result = content_result
            if content_result.confidence >= HIGH_CONFIDENCE_THRESHOLD:
                return content_result

    # Tier 2: filename fallback
    filename_result = classify_by_filename(filename)
    if filename_result:
        if result and result.document_type == filename_result.document_type:
            boosted = min(max(result.confidence, filename_result.confidence) + 0.05, 1.0)
            return ClassificationResult(
                document_type=result.document_type,
                confidence=boosted,
                confidence_level=_confidence_level(boosted),
                reasoning=f"Content + filename match: {result.document_type.value}",
                metadata=result.metadata,
            )
        if not result:
            result = filename_result

    # Tier 3: AI classification
    if ai_response:
        ai_result = parse_ai_classification(ai_response)
        if not result or ai_result.confidence >= result.confidence:
            return ai_result

    # Return best result or unknown
    return result or ClassificationResult(
        document_type=DocumentType.UNKNOWN,
        confidence=0.0,
        confidence_level=ClassificationConfidence.LOW,
        reasoning="No classification rules matched",
    )


def infer_document_version_state(
    filename: str,
    content_text: Optional[str] = None,
) -> tuple[str, str]:
    """
    Infer version state:
      - final: execution/final markers
      - wip: draft or numeric revision markers (v1, v02, ...)
      - unknown: neither marker set

    Returns (status, evidence_pattern).
    """
    combined = filename
    if content_text:
        combined = f"{filename}\n{content_text[:2000]}"

    for pattern in FINAL_VERSION_PATTERNS:
        if re.search(pattern, combined):
            return ("final", pattern)

    for pattern in WIP_VERSION_PATTERNS:
        if re.search(pattern, combined):
            return ("wip", pattern)

    return ("unknown", "")
