"""
Correction logging for the continuous learning loop.

When a user overrides an AI classification or filing location,
the correction is logged. These logs serve as a RAG knowledge base
for improving future classifications — not model fine-tuning.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .models import CorrectionLog, DocumentType


class CorrectionStore:
    """
    In-memory correction store. Production: Azure Table Storage or Cosmos DB.

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
        """Find all corrections where this type was the AI's original guess."""
        return [
            c for c in self._corrections
            if c.original_type == original_type
        ]

    def get_most_common_correction(
        self, original_type: DocumentType
    ) -> Optional[DocumentType]:
        """
        If the AI consistently misclassifies a type, return what users
        typically correct it to.
        """
        corrections = self.get_corrections_for_type(original_type)
        if len(corrections) < 3:
            return None

        # Count corrected types
        counts: dict[DocumentType, int] = {}
        for c in corrections:
            counts[c.corrected_type] = counts.get(c.corrected_type, 0) + 1

        most_common = max(counts, key=counts.get)  # type: ignore[arg-type]
        # Only return if it's a clear pattern (>50% of corrections)
        if counts[most_common] / len(corrections) > 0.5:
            return most_common
        return None

    @property
    def total_corrections(self) -> int:
        return len(self._corrections)

    @property
    def all_corrections(self) -> list[CorrectionLog]:
        return list(self._corrections)
