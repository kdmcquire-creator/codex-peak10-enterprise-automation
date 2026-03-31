"""JSON serialization for Document AI models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import (
    ClassificationConfidence,
    ClassificationResult,
    CorrectionLog,
    DatabaseUpdateApplyState,
    DatabaseUpdateProposal,
    DatabaseUpdateStatus,
    DocumentType,
    ExtractedMetadata,
    FilingRecommendation,
    LearningEvidence,
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
        "source_metadata": d.source_metadata,
        "staged_at": d.staged_at.isoformat(),
        "file_size_bytes": d.file_size_bytes,
        "content_hash": d.content_hash,
        "content_type": d.content_type,
        "binary_available": d.binary_available,
        "storage_backend": d.storage_backend,
        "storage_reference": d.storage_reference,
        "status": d.status,
        "extraction": d.extraction,
        "filed_at": d.filed_at,
        "filing_backend": d.filing_backend,
        "filing_reference": d.filing_reference,
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


def serialize_database_update_proposal(p: DatabaseUpdateProposal) -> dict[str, Any]:
    return {
        "update_id": p.update_id,
        "document_id": p.document_id,
        "document_type": p.document_type.value,
        "version_status": p.version_status,
        "target_table": p.target_table,
        "operation": p.operation,
        "proposed_field_updates": p.proposed_field_updates,
        "approved_field_updates": p.approved_field_updates,
        "effective_field_updates": p.effective_field_updates,
        "confidence": p.confidence,
        "trust_score": p.trust_score,
        "policy_checks": p.policy_checks,
        "status": p.status.value,
        "apply_state": p.apply_state.value,
        "apply_mode": p.apply_mode,
        "applied_at": p.applied_at,
        "apply_reference": p.apply_reference,
        "apply_error": p.apply_error,
        "proposed_at": p.proposed_at.isoformat(),
        "reviewed_at": p.reviewed_at,
        "reviewed_by": p.reviewed_by,
        "review_notes": p.review_notes,
        "source_summary": p.source_summary,
    }


def serialize_learning_evidence(e: LearningEvidence) -> dict[str, Any]:
    return {
        "evidence_id": e.evidence_id,
        "update_id": e.update_id,
        "document_id": e.document_id,
        "document_type": e.document_type.value,
        "target_table": e.target_table,
        "event_type": e.event_type,
        "decision": e.decision,
        "trust_score": e.trust_score,
        "proposed_field_updates": e.proposed_field_updates,
        "final_field_updates": e.final_field_updates,
        "edited_fields": e.edited_fields,
        "actor": e.actor,
        "notes": e.notes,
        "apply_mode": e.apply_mode,
        "outcome": e.outcome,
        "captured_at": e.captured_at.isoformat(),
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
        source_metadata=data.get("source_metadata", {}),
        staged_at=datetime.fromisoformat(data["staged_at"])
        if data.get("staged_at")
        else datetime.now(timezone.utc),
        file_size_bytes=int(data.get("file_size_bytes", 0)),
        content_hash=data.get("content_hash", ""),
        content_type=data.get("content_type", ""),
        binary_available=bool(data.get("binary_available", False)),
        storage_backend=data.get("storage_backend", "metadata_only"),
        storage_reference=data.get("storage_reference", ""),
        status=data.get("status", "pending"),
        extraction=data.get("extraction", {}),
        filed_at=data.get("filed_at"),
        filing_backend=data.get("filing_backend", ""),
        filing_reference=data.get("filing_reference", ""),
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


def deserialize_database_update_proposal(data: dict[str, Any]) -> DatabaseUpdateProposal:
    try:
        doc_type = DocumentType(data.get("document_type", DocumentType.UNKNOWN.value))
    except ValueError:
        doc_type = DocumentType.UNKNOWN

    try:
        status = DatabaseUpdateStatus(
            data.get("status", DatabaseUpdateStatus.PENDING_APPROVAL.value)
        )
    except ValueError:
        status = DatabaseUpdateStatus.PENDING_APPROVAL

    try:
        apply_state = DatabaseUpdateApplyState(
            data.get("apply_state", DatabaseUpdateApplyState.PENDING.value)
        )
    except ValueError:
        apply_state = DatabaseUpdateApplyState.PENDING

    return DatabaseUpdateProposal(
        update_id=data.get("update_id", ""),
        document_id=data.get("document_id", ""),
        document_type=doc_type,
        version_status=str(data.get("version_status", "unknown")),
        target_table=str(data.get("target_table", "document_registry")),
        operation=str(data.get("operation", "upsert")),
        proposed_field_updates=data.get("proposed_field_updates", {}),
        approved_field_updates=data.get("approved_field_updates", {}),
        confidence=float(data.get("confidence", 0.0)),
        trust_score=float(data.get("trust_score", 0.0)),
        policy_checks=data.get("policy_checks", {}),
        status=status,
        apply_state=apply_state,
        apply_mode=str(data.get("apply_mode", "shadow")),
        applied_at=data.get("applied_at"),
        apply_reference=str(data.get("apply_reference", "")),
        apply_error=str(data.get("apply_error", "")),
        proposed_at=datetime.fromisoformat(data["proposed_at"])
        if data.get("proposed_at")
        else datetime.now(timezone.utc),
        reviewed_at=data.get("reviewed_at"),
        reviewed_by=data.get("reviewed_by", ""),
        review_notes=data.get("review_notes", ""),
        source_summary=data.get("source_summary", {}),
    )


def deserialize_learning_evidence(data: dict[str, Any]) -> LearningEvidence:
    try:
        doc_type = DocumentType(data.get("document_type", DocumentType.UNKNOWN.value))
    except ValueError:
        doc_type = DocumentType.UNKNOWN

    return LearningEvidence(
        evidence_id=data.get("evidence_id", ""),
        update_id=data.get("update_id", ""),
        document_id=data.get("document_id", ""),
        document_type=doc_type,
        target_table=data.get("target_table", ""),
        event_type=data.get("event_type", "review"),
        decision=data.get("decision", ""),
        trust_score=float(data.get("trust_score", 0.0)),
        proposed_field_updates=data.get("proposed_field_updates", {}),
        final_field_updates=data.get("final_field_updates", {}),
        edited_fields=[str(item) for item in data.get("edited_fields", [])],
        actor=data.get("actor", ""),
        notes=data.get("notes", ""),
        apply_mode=data.get("apply_mode", ""),
        outcome=data.get("outcome", ""),
        captured_at=datetime.fromisoformat(data["captured_at"])
        if data.get("captured_at")
        else datetime.now(timezone.utc),
    )
