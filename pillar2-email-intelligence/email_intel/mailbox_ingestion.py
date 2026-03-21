"""Helpers for translating Microsoft Graph payloads into local email models."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from .models import EmailMessage


@dataclass
class MailAttachment:
    attachment_id: str = ""
    name: str = ""
    content_type: str = ""
    content_bytes: bytes = b""
    is_inline: bool = False


def parse_graph_message(message: dict[str, Any]) -> EmailMessage:
    sender = message.get("from", {}).get("emailAddress", {})
    recipients = [
        recipient.get("emailAddress", {}).get("address", "")
        for recipient in message.get("toRecipients", [])
        if recipient.get("emailAddress", {}).get("address")
    ]
    attachment_names = [
        attachment.get("name", "")
        for attachment in message.get("attachments", [])
        if attachment.get("name")
    ]

    return EmailMessage(
        message_id=message.get("id", ""),
        subject=message.get("subject", ""),
        sender=sender.get("address", ""),
        sender_name=sender.get("name", ""),
        recipients=recipients,
        body_preview=message.get("bodyPreview", ""),
        body_text=message.get("body", {}).get("content", "") or message.get("bodyPreview", ""),
        has_attachments=bool(message.get("hasAttachments", False)),
        attachment_names=attachment_names,
        conversation_id=message.get("conversationId", ""),
    )


def parse_graph_attachment(attachment: dict[str, Any]) -> MailAttachment:
    content_bytes = attachment.get("contentBytes", "")
    decoded = base64.b64decode(content_bytes) if content_bytes else b""
    return MailAttachment(
        attachment_id=attachment.get("id", ""),
        name=attachment.get("name", ""),
        content_type=attachment.get("contentType", ""),
        content_bytes=decoded,
        is_inline=bool(attachment.get("isInline", False)),
    )
