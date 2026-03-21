"""Tests for Graph mailbox payload translation helpers."""

from __future__ import annotations

import base64

from email_intel.mailbox_ingestion import parse_graph_attachment, parse_graph_message


def test_parse_graph_message_maps_core_fields():
    email = parse_graph_message(
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
            "attachments": [{"name": "Invoice_123.pdf"}],
            "conversationId": "conv-1",
        }
    )

    assert email.message_id == "msg-1"
    assert email.sender == "billing@vendor.com"
    assert email.sender_name == "Vendor Billing"
    assert email.attachment_names == ["Invoice_123.pdf"]
    assert email.has_attachments is True


def test_parse_graph_attachment_decodes_content_bytes():
    attachment = parse_graph_attachment(
        {
            "id": "att-1",
            "name": "receipt.pdf",
            "contentType": "application/pdf",
            "contentBytes": base64.b64encode(b"pdf-bytes").decode("ascii"),
            "isInline": False,
        }
    )

    assert attachment.attachment_id == "att-1"
    assert attachment.name == "receipt.pdf"
    assert attachment.content_bytes == b"pdf-bytes"
