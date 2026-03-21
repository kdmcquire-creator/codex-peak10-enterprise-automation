"""
Azure Document Intelligence (Form Recognizer) client wrapper.

Extracts text content from documents (PDF, DOCX, images) for
classification by the rule-based + AI pipeline.

Falls back to filename-only classification when credentials
are not configured (local dev / testing).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("email-intel.doc-intelligence")


INVOICE_FILENAME_PATTERNS = [
    r"(?i)invoice",
    r"(?i)\bap\b",
    r"(?i)statement",
]

RECEIPT_FILENAME_PATTERNS = [
    r"(?i)receipt",
    r"(?i)itinerary",
    r"(?i)booking",
    r"(?i)confirmation",
]


@dataclass
class ExtractionResult:
    """Result of text extraction from a document."""
    text: str = ""
    page_count: int = 0
    language: str = ""
    confidence: float = 0.0
    tables_found: int = 0
    key_value_pairs: dict[str, str] | None = None


def suggest_extraction_mode(filename: str) -> str:
    """Suggest the best Document Intelligence model for a filename."""
    for pattern in INVOICE_FILENAME_PATTERNS:
        if re.search(pattern, filename):
            return "invoice"

    for pattern in RECEIPT_FILENAME_PATTERNS:
        if re.search(pattern, filename):
            return "receipt"

    return "text"


class DocumentIntelligenceClient:
    """
    Wrapper around Azure AI Document Intelligence SDK.

    Uses the prebuilt-read model for general text extraction and
    prebuilt-invoice/receipt for structured extraction.

    Falls back gracefully when not configured.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._endpoint = endpoint or os.environ.get("AZURE_DI_ENDPOINT", "")
        self._api_key = api_key or os.environ.get("AZURE_DI_KEY", "")
        self._client = None
        self._available = False

        self._init_client()

    def _init_client(self) -> None:
        if not self._endpoint:
            logger.info("No AZURE_DI_ENDPOINT — Document Intelligence unavailable")
            return
        if not self._api_key:
            logger.info("No AZURE_DI_KEY - Document Intelligence unavailable")
            return

        try:
            from azure.ai.documentintelligence import DocumentIntelligenceClient as DIClient
            from azure.core.credentials import AzureKeyCredential

            self._client = DIClient(
                endpoint=self._endpoint,
                credential=AzureKeyCredential(self._api_key),
            )
            self._available = True
            logger.info("Document Intelligence client initialized: %s", self._endpoint)
        except Exception as e:
            logger.warning("Document Intelligence init failed: %s", e)

    @property
    def is_available(self) -> bool:
        return self._available

    def extract_text(self, file_bytes: bytes, content_type: str = "application/pdf") -> ExtractionResult:
        """
        Extract text from a document using the prebuilt-read model.

        Args:
            file_bytes: Raw document bytes
            content_type: MIME type of the document

        Returns:
            ExtractionResult with extracted text and metadata
        """
        if not self._available:
            logger.debug("Document Intelligence not available, returning empty extraction")
            return ExtractionResult()

        try:
            poller = self._client.begin_analyze_document(
                "prebuilt-read",
                body=file_bytes,
                content_type=content_type,
            )
            result = poller.result()

            text_parts = []
            page_count = 0
            if result.pages:
                page_count = len(result.pages)
                for page in result.pages:
                    if page.lines:
                        for line in page.lines:
                            text_parts.append(line.content)

            return ExtractionResult(
                text="\n".join(text_parts),
                page_count=page_count,
                language=result.languages[0].locale if result.languages else "",
                confidence=result.pages[0].lines[0].confidence if result.pages and result.pages[0].lines else 0.0,
            )
        except Exception as e:
            logger.error("Text extraction failed: %s", e)
            return ExtractionResult()

    def extract_invoice(self, file_bytes: bytes) -> ExtractionResult:
        """Extract structured data from an invoice using prebuilt-invoice model."""
        if not self._available:
            return ExtractionResult()

        try:
            poller = self._client.begin_analyze_document(
                "prebuilt-invoice",
                body=file_bytes,
                content_type="application/pdf",
            )
            result = poller.result()

            kv_pairs = {}
            text_parts = []

            if result.documents:
                doc = result.documents[0]
                fields = doc.fields or {}
                for key, val in fields.items():
                    if val and val.content:
                        kv_pairs[key] = val.content
                        text_parts.append(f"{key}: {val.content}")

            return ExtractionResult(
                text="\n".join(text_parts),
                page_count=len(result.pages) if result.pages else 0,
                confidence=doc.confidence if result.documents else 0.0,
                key_value_pairs=kv_pairs,
            )
        except Exception as e:
            logger.error("Invoice extraction failed: %s", e)
            return ExtractionResult()

    def extract_receipt(self, file_bytes: bytes) -> ExtractionResult:
        """Extract structured data from a receipt using prebuilt-receipt model."""
        if not self._available:
            return ExtractionResult()

        try:
            poller = self._client.begin_analyze_document(
                "prebuilt-receipt",
                body=file_bytes,
                content_type="application/pdf",
            )
            result = poller.result()

            kv_pairs = {}
            text_parts = []

            if result.documents:
                doc = result.documents[0]
                fields = doc.fields or {}
                for key, val in fields.items():
                    if val and val.content:
                        kv_pairs[key] = val.content
                        text_parts.append(f"{key}: {val.content}")

            return ExtractionResult(
                text="\n".join(text_parts),
                page_count=len(result.pages) if result.pages else 0,
                confidence=doc.confidence if result.documents else 0.0,
                key_value_pairs=kv_pairs,
            )
        except Exception as e:
            logger.error("Receipt extraction failed: %s", e)
            return ExtractionResult()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_client: Optional[DocumentIntelligenceClient] = None


def get_doc_intelligence_client() -> DocumentIntelligenceClient:
    """Return the module-level DocumentIntelligenceClient singleton."""
    global _client
    if _client is None:
        _client = DocumentIntelligenceClient()
    return _client


def reset_doc_intelligence_client() -> None:
    """Reset the singleton (for testing)."""
    global _client
    _client = None
