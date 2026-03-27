"""Mailbox ingestion orchestration built on top of the Graph client."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from .attachment_processing import ProcessedAttachment, process_attachment
from .doc_intelligence import DocumentIntelligenceClient, get_doc_intelligence_client
from .graph_client import GraphClient, get_graph_client
from .mailbox_ingestion import MailAttachment, parse_graph_attachment, parse_graph_message
from .models import EmailMessage, TriageResult
from .openai_client import AzureOpenAIClient, get_openai_client
from .triage import build_triage_prompt, triage_email


TRIAGE_AI_THRESHOLD = 0.85
logger = logging.getLogger("email-intel.ingestion")


@dataclass
class IngestedEmail:
    email: EmailMessage
    attachments: list[MailAttachment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ProcessedEmail:
    email: EmailMessage
    triage: TriageResult
    attachments: list[ProcessedAttachment] = field(default_factory=list)
    ai_used: bool = False
    marked_processed: bool = False
    warnings: list[str] = field(default_factory=list)


class MailboxIngestionService:
    """Fetches unread mailbox items and converts them into local models."""

    def __init__(self, graph_client: GraphClient | None = None) -> None:
        self._graph_client = graph_client or get_graph_client()

    @property
    def is_available(self) -> bool:
        return self._graph_client.is_available

    def fetch_unread_messages(self, *, top: int = 25) -> list[IngestedEmail]:
        messages = self._graph_client.list_inbox_messages(top=top, unread_only=True)
        ingested: list[IngestedEmail] = []

        for message in messages:
            attachments: list[MailAttachment] = []
            warnings: list[str] = []
            if message.get("hasAttachments"):
                try:
                    raw_attachments = self._graph_client.get_message_attachments(
                        message.get("id", "")
                    )
                    for item in raw_attachments:
                        if not item.get("name"):
                            continue
                        try:
                            attachments.append(parse_graph_attachment(item))
                        except Exception as exc:
                            attachment_name = item.get("name", "<unknown>")
                            logger.warning(
                                "Attachment parse failed for %s/%s: %s",
                                message.get("id", ""),
                                attachment_name,
                                exc,
                            )
                            warnings.append(
                                f"attachment_parse_failed:{attachment_name}: {exc}"
                            )
                except Exception as exc:
                    logger.warning(
                        "Attachment fetch failed for %s: %s",
                        message.get("id", ""),
                        exc,
                    )
                    warnings.append(f"attachment_fetch_failed: {exc}")
                message = dict(message)
                message["attachments"] = [{"name": item.name} for item in attachments]

            ingested.append(
                IngestedEmail(
                    email=parse_graph_message(message),
                    attachments=attachments,
                    warnings=warnings,
                )
            )

        return ingested

    def process_unread_messages(
        self,
        *,
        top: int = 25,
        mark_processed: bool = False,
        openai_client: AzureOpenAIClient | None = None,
        doc_intelligence_client: DocumentIntelligenceClient | None = None,
    ) -> list[ProcessedEmail]:
        oai = openai_client or get_openai_client()
        doc_client = doc_intelligence_client or get_doc_intelligence_client()
        processed: list[ProcessedEmail] = []

        for ingested in self.fetch_unread_messages(top=top):
            triage = triage_email(ingested.email)
            ai_used = False
            warnings = list(ingested.warnings)

            if triage.confidence < TRIAGE_AI_THRESHOLD and oai.is_available:
                try:
                    prompt = build_triage_prompt(ingested.email)
                    ai_response = oai.triage_email(prompt)
                    if ai_response:
                        triage = triage_email(ingested.email, ai_response=ai_response)
                        ai_used = True
                except Exception as exc:
                    logger.warning(
                        "Email AI triage failed for %s: %s",
                        ingested.email.message_id,
                        exc,
                    )
                    warnings.append(f"triage_ai_failed: {exc}")

            processed_attachments: list[ProcessedAttachment] = []
            for attachment in ingested.attachments:
                try:
                    processed_attachments.append(
                        process_attachment(
                            attachment,
                            graph_client=self._graph_client,
                            openai_client=oai,
                            doc_intelligence_client=doc_client,
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "Attachment processing failed for %s/%s: %s",
                        ingested.email.message_id,
                        attachment.name,
                        exc,
                    )
                    warnings.append(
                        f"attachment_processing_failed:{attachment.name}: {exc}"
                    )

            marked = False
            if mark_processed and ingested.email.message_id and self._graph_client.mailbox_available:
                try:
                    self._graph_client.mark_message_processed(ingested.email.message_id)
                    marked = True
                except Exception as exc:
                    logger.warning(
                        "Mark processed failed for %s: %s",
                        ingested.email.message_id,
                        exc,
                    )
                    warnings.append(f"mark_processed_failed: {exc}")

            processed.append(
                ProcessedEmail(
                    email=ingested.email,
                    triage=triage,
                    attachments=processed_attachments,
                    ai_used=ai_used,
                    marked_processed=marked,
                    warnings=warnings,
                )
            )

        return processed
