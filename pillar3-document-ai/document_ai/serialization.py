"""JSON serialization for Document AI models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import (
    ClassificationConfidence,
    ClassificationResult,
    CorrectionLog,
    DocumentType,
    ExtractedMetadata,
    FilingRecommendation,
    StagedDocument,
)


def serialize_metadata(m: ExtractedMetadata) -> dict[str, Any]:
    return {
        "vendor_name": m.vendor_name,
        "counterparty": m.counterparty,
        "effective_date": m.effective_date,
        "expiration_date": m.expiration_date,
        "amount": m.amount,
        "well_name": m.well_name,
        "lease_name": m.lease_name,
        "county": m.county,
        "state": m.state,
        "reference_number": m.reference_number,
        "custom_fields": m.custom_fields,
    }


def serialize_classification(c: ClassificationResult) -> dict[str, Any]:
    return {
        "document_type": c.document_type.value,
        "confidence": c.confidence,
        "confidence_level": c.confidence_level.value,
        "metadata": serialize_metadata(c.metadata),
        "reasoning": c.reasoning,
    }


def serialize_filing(f: FilingRecommendation) -> dict[str, Any]:
    return {
        "recommended_path": f.recommended_path,
        "standardized_name": f.standardized_name,
        "document_type": f.document_type.value,
        "confidence_level": f.confidence_level.value,
        "requires_review": f.requires_review,
        "alternative_paths": f.alternative_paths,
    }


def serialize_staged_document(d: StagedDocument) -> dict[str, Any]:
    result: dict[str, Any] = {
        "document_id": d.document_id,
        "original_filename": d.original_filename,
        "file_extension": d.file_extension,
        "source": d.source,
        "source_detail": d.source_detail,
        "staged_at": d.staged_at.isoformat(),
        "file_size_bytes": d.file_size_bytes,
        "status": d.status,
    }
    if d.classification:
        result["classification"] = serialize_classification(d.classification)
    if d.filing:
        result["filing"] = serialize_filing(d.filing)
    return result


def serialize_correction(c: CorrectionLog) -> dict[str, Any]:
    return {
        "correction_id": c.correction_id,
        "document_id": c.document_id,
        "original_type": c.original_type.value,
        "corrected_type": c.corrected_type.value,
        "original_path": c.original_path,
        "corrected_path": c.corrected_path,
        "corrected_by": c.corrected_by,
        "corrected_at": c.corrected_at.isoformat(),
        "notes": c.notes,
    }


def deserialize_metadata(data: dict[str, Any]) -> ExtractedMetadata:
    return ExtractedMetadata(
        vendor_name=data.get("vendor_name"),
        counterparty=data.get("counterparty"),
        effective_date=data.get("effective_date"),
        expiration_date=data.get("expiration_date"),
        amount=data.get("amount"),
        well_name=data.get("well_name"),
        lease_name=data.get("lease_name"),
        county=data.get("county"),
        state=data.get("state"),
        reference_number=data.get("reference_number"),
        custom_fields=data.get("custom_fields", {}),
    )


def deserialize_classification(data: dict[str, Any]) -> ClassificationResult:
    return ClassificationResult(
        document_type=DocumentType(data.get("document_type", DocumentType.UNKNOWN.value)),
        confidence=float(data.get("confidence", 0.0)),
        confidence_level=ClassificationConfidence(
            data.get("confidence_level", ClassificationConfidence.LOW.value)
        ),
        metadata=deserialize_metadata(data.get("metadata", {})),
        reasoning=data.get("reasoning", ""),
    )


def deserialize_filing(data: dict[str, Any]) -> FilingRecommendation:
    return FilingRecommendation(
        recommended_path=data.get("recommended_path", ""),
        standardized_name=data.get("standardized_name", ""),
        document_type=DocumentType(data.get("document_type", DocumentType.UNKNOWN.value)),
        confidence_level=ClassificationConfidence(
            data.get("confidence_level", ClassificationConfidence.LOW.value)
        ),
        requires_review=bool(data.get("requires_review", True)),
        alternative_paths=data.get("alternative_paths", []),
    )


def deserialize_staged_document(data: dict[str, Any]) -> StagedDocument:
    document = StagedDocument(
        document_id=data.get("document_id", ""),
        original_filename=data.get("original_filename", ""),
        file_extension=data.get("file_extension", ""),
        source=data.get("source", "upload"),
        source_detail=data.get("source_detail", ""),
        staged_at=datetime.fromisoformat(data["staged_at"])
        if data.get("staged_at")
        else datetime.now(timezone.utc),
        file_size_bytes=int(data.get("file_size_bytes", 0)),
        content_hash=data.get("content_hash", ""),
        status=data.get("status", "pending"),
    )
    if data.get("classification"):
        document.classification = deserialize_classification(data["classification"])
    if data.get("filing"):
        document.filing = deserialize_filing(data["filing"])
    return document


def deserialize_correction(data: dict[str, Any]) -> CorrectionLog:
    return CorrectionLog(
        correction_id=data.get("correction_id", ""),
        document_id=data.get("document_id", ""),
        original_type=DocumentType(data.get("original_type", DocumentType.UNKNOWN.value)),
        corrected_type=DocumentType(data.get("corrected_type", DocumentType.UNKNOWN.value)),
        original_path=data.get("original_path", ""),
        corrected_path=data.get("corrected_path", ""),
        corrected_by=data.get("corrected_by", "user"),
        corrected_at=datetime.fromisoformat(data["corrected_at"])
        if data.get("corrected_at")
        else datetime.now(timezone.utc),
        notes=data.get("notes", ""),
    )
