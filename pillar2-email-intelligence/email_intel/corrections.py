"""
Correction logging for continuous learning — merged from Pillar 3.

Logs user overrides of AI classification/filing decisions.
Uses Cosmos DB when available, in-memory fallback otherwise.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .document_models import CorrectionLog, DocumentType


class CorrectionStore:
    """
    Correction store backed by Cosmos DB (via CosmosDataStore) or in-memory.

    Provides lookup of past corrections to boost classification confidence
    when similar documents are encountered.
    """

    def __init__(self) -> None:
        self._corrections: list[CorrectionLog] = []

    def log_correction(
        self,
        document_id: str,
        original_type: DocumentType,
        corrected_type: DocumentType,
        original_path: str,
        corrected_path: str,
        corrected_by: str = "user",
        notes: str = "",
    ) -> CorrectionLog:
        entry = CorrectionLog(
            document_id=document_id,
            original_type=original_type,
            corrected_type=corrected_type,
            original_path=original_path,
            corrected_path=corrected_path,
            corrected_by=corrected_by,
            corrected_at=datetime.now(timezone.utc),
            notes=notes,
        )
        self._corrections.append(entry)
        return entry

    def get_corrections_for_type(
        self, original_type: DocumentType
    ) -> list[CorrectionLog]:
        return [
            c for c in self._corrections
            if c.original_type == original_type
        ]

    def get_most_common_correction(
        self, original_type: DocumentType
    ) -> Optional[DocumentType]:
        corrections = self.get_corrections_for_type(original_type)
        if len(corrections) < 3:
            return None

        counts: dict[DocumentType, int] = {}
        for c in corrections:
            counts[c.corrected_type] = counts.get(c.corrected_type, 0) + 1

        most_common = max(counts, key=counts.get)  # type: ignore[arg-type]
        if counts[most_common] / len(corrections) > 0.5:
            return most_common
        return None

    @property
    def total_corrections(self) -> int:
        return len(self._corrections)

    @property
    def all_corrections(self) -> list[CorrectionLog]:
        return list(self._corrections)
