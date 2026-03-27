"""Tests for mailbox ingestion orchestration."""

from __future__ import annotations

import base64

from email_intel.ingestion_service import MailboxIngestionService


class FakeGraphClient:
    is_available = True
    mailbox_available = True
    sharepoint_available = False

    def __init__(self) -> None:
        self.marked_messages: list[str] = []

    def list_inbox_messages(self, *, top: int = 25, unread_only: bool = True):
        return [
            {
                "id": "msg-1",
                "subject": "Invoice #123",
                "from": {
                    "emailAddress": {
                        "address": "billing@vendor.com",
                        "name": "Vendor Billing",
                    }
                },
                "toRecipients": [
                    {"emailAddress": {"address": "kmcquire@peak10energy.com"}}
                ],
                "bodyPreview": "Please see attached.",
                "body": {"content": "Please see attached invoice."},
                "hasAttachments": True,
                "conversationId": "conv-1",
            }
        ]

    def get_message_attachments(self, message_id: str):
        return [
            {
                "id": "att-1",
                "name": "Invoice_123.pdf",
                "contentType": "application/pdf",
                "contentBytes": base64.b64encode(b"pdf-bytes").decode("ascii"),
                "isInline": False,
            }
        ]

    def mark_message_processed(self, message_id: str, *, category: str = "Peak10Processed"):
        self.marked_messages.append(message_id)
        return {"id": message_id, "categories": [category]}


class FakeOpenAIClient:
    is_available = False


class FakeDocClient:
    is_available = False


class FailingGraphClient(FakeGraphClient):
    def mark_message_processed(self, message_id: str, *, category: str = "Peak10Processed"):
        raise RuntimeError("graph write failed")


class ExplodingAttachmentGraphClient(FakeGraphClient):
    def get_message_attachments(self, message_id: str):
        raise RuntimeError("attachments endpoint failed")


class InvalidAttachmentPayloadGraphClient(FakeGraphClient):
    def get_message_attachments(self, message_id: str):
        return [
            {
                "id": "att-1",
                "name": "Invoice_123.pdf",
                "contentType": "application/pdf",
                "contentBytes": "%%%not-base64%%%",
                "isInline": False,
            }
        ]


def test_fetch_unread_messages_builds_local_models():
    service = MailboxIngestionService(graph_client=FakeGraphClient())

    results = service.fetch_unread_messages()

    assert len(results) == 1
    assert results[0].email.subject == "Invoice #123"
    assert results[0].email.attachment_names == ["Invoice_123.pdf"]
    assert len(results[0].attachments) == 1
    assert results[0].attachments[0].content_bytes == b"pdf-bytes"


def test_process_unread_messages_processes_attachments_and_marks_messages():
    graph_client = FakeGraphClient()
    service = MailboxIngestionService(graph_client=graph_client)

    results = service.process_unread_messages(
        mark_processed=True,
        openai_client=FakeOpenAIClient(),
        doc_intelligence_client=FakeDocClient(),
    )

    assert len(results) == 1
    assert results[0].triage.category.value == "vendor_ap"
    assert len(results[0].attachments) == 1
    assert results[0].attachments[0].sharepoint_target["folder_path"] == "01_CORPORATE/Finance/AP"
    assert results[0].attachments[0].upload_result["attempted"] is False
    assert results[0].marked_processed is True
    assert graph_client.marked_messages == ["msg-1"]


def test_process_unread_messages_records_mark_processed_warning():
    service = MailboxIngestionService(graph_client=FailingGraphClient())

    results = service.process_unread_messages(
        mark_processed=True,
        openai_client=FakeOpenAIClient(),
        doc_intelligence_client=FakeDocClient(),
    )

    assert len(results) == 1
    assert results[0].marked_processed is False
    assert any("mark_processed_failed" in warning for warning in results[0].warnings)


def test_fetch_unread_messages_records_attachment_fetch_warning():
    service = MailboxIngestionService(graph_client=ExplodingAttachmentGraphClient())

    results = service.fetch_unread_messages()

    assert len(results) == 1
    assert results[0].attachments == []
    assert any("attachment_fetch_failed" in warning for warning in results[0].warnings)


def test_fetch_unread_messages_skips_invalid_attachment_payloads():
    service = MailboxIngestionService(graph_client=InvalidAttachmentPayloadGraphClient())

    results = service.fetch_unread_messages()

    assert len(results) == 1
    assert results[0].attachments == []
    assert any("attachment_parse_failed" in warning for warning in results[0].warnings)
