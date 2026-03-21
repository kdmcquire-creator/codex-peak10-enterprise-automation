"""Attachment extraction, classification, and SharePoint filing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .classifier import HIGH_CONFIDENCE_THRESHOLD, build_classification_prompt, classify_document
from .doc_intelligence import (
    DocumentIntelligenceClient,
    suggest_extraction_mode,
    get_doc_intelligence_client,
)
from .document_models import ClassificationResult, DocumentType, FilingRecommendation
from .graph_client import GraphClient
from .mailbox_ingestion import MailAttachment
from .naming import recommend_filing
from .openai_client import AzureOpenAIClient, get_openai_client


SUPPORTED_SHAREPOINT_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".txt",
    ".xls",
    ".xlsx",
}


@dataclass
class ProcessedAttachment:
    attachment: MailAttachment
    classification: ClassificationResult
    filing: FilingRecommendation
    extraction_text: str = ""
    extraction_summary: dict[str, object] = field(default_factory=dict)
    sharepoint_target: dict[str, object] = field(default_factory=dict)
    upload_result: dict[str, object] = field(default_factory=dict)


def extract_document_text_from_bytes(
    filename: str,
    file_bytes: bytes,
    *,
    content_type: str,
    doc_intelligence_client: DocumentIntelligenceClient | None = None,
) -> tuple[str, dict[str, object]]:
    client = doc_intelligence_client or get_doc_intelligence_client()
    mode = suggest_extraction_mode(filename)

    summary: dict[str, object] = {
        "used_document_intelligence": client.is_available,
        "mode": mode,
        "content_type": content_type,
        "page_count": 0,
        "confidence": 0.0,
        "text_length": 0,
    }

    if not client.is_available:
        return "", summary

    if mode == "invoice":
        extraction = client.extract_invoice(file_bytes)
        if not extraction.text:
            extraction = client.extract_text(file_bytes, content_type=content_type)
    elif mode == "receipt":
        extraction = client.extract_receipt(file_bytes)
        if not extraction.text:
            extraction = client.extract_text(file_bytes, content_type=content_type)
    else:
        extraction = client.extract_text(file_bytes, content_type=content_type)

    summary["page_count"] = extraction.page_count
    summary["confidence"] = extraction.confidence
    summary["text_length"] = len(extraction.text)

    return extraction.text, summary


def resolve_sharepoint_target(
    original_filename: str,
    classification: ClassificationResult,
    filing: FilingRecommendation,
) -> dict[str, object]:
    suffix = Path(original_filename).suffix.lower()

    if suffix not in SUPPORTED_SHAREPOINT_EXTENSIONS:
        folder_path = "00_STAGING/Errors"
        target_filename = original_filename
        disposition = "unsupported"
        reason = "unsupported_extension"
    elif filing.requires_review or classification.document_type == DocumentType.UNKNOWN:
        folder_path = "00_STAGING/Inbox"
        target_filename = original_filename
        disposition = "staged_for_review"
        reason = "low_confidence_classification"
    else:
        folder_path = filing.recommended_path
        target_filename = filing.standardized_name or original_filename
        disposition = "filed"
        reason = "governed_filing"

    return {
        "disposition": disposition,
        "folder_path": folder_path,
        "filename": target_filename,
        "full_path": f"{folder_path}/{target_filename}",
        "reason": reason,
    }


def process_attachment(
    attachment: MailAttachment,
    *,
    graph_client: GraphClient | None = None,
    openai_client: AzureOpenAIClient | None = None,
    doc_intelligence_client: DocumentIntelligenceClient | None = None,
) -> ProcessedAttachment:
    oai = openai_client or get_openai_client()
    content_type = attachment.content_type or "application/octet-stream"
    extraction_text, extraction_summary = extract_document_text_from_bytes(
        attachment.name,
        attachment.content_bytes,
        content_type=content_type,
        doc_intelligence_client=doc_intelligence_client,
    )

    classification = classify_document(
        attachment.name,
        extraction_text or None,
    )
    if classification.confidence < HIGH_CONFIDENCE_THRESHOLD and oai.is_available:
        prompt = build_classification_prompt(attachment.name, extraction_text)
        ai_response = oai.classify_document(prompt)
        if ai_response:
            classification = classify_document(
                attachment.name,
                extraction_text or None,
                ai_response,
            )

    extension = attachment.name.rsplit(".", 1)[-1] if "." in attachment.name else ""
    filing = recommend_filing(classification, attachment.name, extension or "bin")
    sharepoint_target = resolve_sharepoint_target(
        attachment.name,
        classification,
        filing,
    )

    upload_result: dict[str, object] = {
        "attempted": False,
        "uploaded": False,
        "backend": "sharepoint" if graph_client and graph_client.sharepoint_available else "offline",
    }
    if not attachment.content_bytes:
        upload_result["reason"] = "attachment_empty"
    elif graph_client and graph_client.sharepoint_available:
        response = graph_client.upload_file(
            str(sharepoint_target["filename"]),
            attachment.content_bytes,
            folder_path=str(sharepoint_target["folder_path"]),
        )
        upload_result.update(
            {
                "attempted": True,
                "uploaded": bool(response),
                "item_id": response.get("id", ""),
                "web_url": response.get("webUrl", ""),
            }
        )
    else:
        upload_result["reason"] = "sharepoint_unavailable"

    return ProcessedAttachment(
        attachment=attachment,
        classification=classification,
        filing=filing,
        extraction_text=extraction_text,
        extraction_summary=extraction_summary,
        sharepoint_target=sharepoint_target,
        upload_result=upload_result,
    )
