"""Minimal Microsoft Graph client wrapper for Pillar 2 integrations."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


logger = logging.getLogger("email-intel.graph")

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


@dataclass
class GraphClientConfig:
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    mailbox_address: str = ""
    sharepoint_site_id: str = ""
    sharepoint_drive_id: str = ""
    graph_base_url: str = GRAPH_BASE_URL


class GraphClient:
    """Client-credentials Graph wrapper with offline-friendly behavior."""

    def __init__(self, config: Optional[GraphClientConfig] = None) -> None:
        self._config = config or self._load_config_from_env()
        self._access_token = ""
        self._access_token_expires_at = 0.0

    def _load_config_from_env(self) -> GraphClientConfig:
        return GraphClientConfig(
            tenant_id=os.environ.get("GRAPH_TENANT_ID", ""),
            client_id=os.environ.get("GRAPH_CLIENT_ID", ""),
            client_secret=os.environ.get("GRAPH_CLIENT_SECRET", ""),
            mailbox_address=os.environ.get("GRAPH_MAILBOX_ADDRESS", ""),
            sharepoint_site_id=os.environ.get("GRAPH_SHAREPOINT_SITE_ID", ""),
            sharepoint_drive_id=os.environ.get("GRAPH_SHAREPOINT_DRIVE_ID", ""),
        )

    @property
    def is_available(self) -> bool:
        return self.mailbox_available

    @property
    def mailbox_available(self) -> bool:
        return all(
            [
                self._config.tenant_id,
                self._config.client_id,
                self._config.client_secret,
                self._config.mailbox_address,
            ]
        )

    @property
    def sharepoint_available(self) -> bool:
        return all(
            [
                self._config.tenant_id,
                self._config.client_id,
                self._config.client_secret,
                self._config.sharepoint_site_id,
                self._config.sharepoint_drive_id,
            ]
        )

    def build_messages_url(self, *, top: int = 25, unread_only: bool = True) -> str:
        params = {
            "$top": top,
            "$select": ",".join(
                [
                    "id",
                    "subject",
                    "from",
                    "toRecipients",
                    "bodyPreview",
                    "body",
                    "hasAttachments",
                    "receivedDateTime",
                    "conversationId",
                    "isRead",
                ]
            ),
            "$orderby": "receivedDateTime desc",
        }
        if unread_only:
            params["$filter"] = "isRead eq false"

        query = urllib.parse.urlencode(params, safe=",$ ")
        return (
            f"{self._config.graph_base_url}/users/"
            f"{urllib.parse.quote(self._config.mailbox_address)}/messages?{query}"
        )

    def build_attachments_url(self, message_id: str) -> str:
        return (
            f"{self._config.graph_base_url}/users/"
            f"{urllib.parse.quote(self._config.mailbox_address)}/messages/"
            f"{urllib.parse.quote(message_id)}/attachments"
        )

    def build_upload_url(self, filename: str, folder_path: str = "") -> str:
        if not self.sharepoint_available:
            raise ValueError("SharePoint site/drive configuration is required")

        normalized_folder = folder_path.strip("/")
        if normalized_folder:
            item_path = f"{normalized_folder}/{filename}"
        else:
            item_path = filename

        return (
            f"{self._config.graph_base_url}/sites/{self._config.sharepoint_site_id}"
            f"/drives/{self._config.sharepoint_drive_id}/root:/"
            f"{urllib.parse.quote(item_path, safe='/')}:/content"
        )

    def list_inbox_messages(self, *, top: int = 25, unread_only: bool = True) -> list[dict[str, Any]]:
        if not self.is_available:
            return []
        data = self._request_json("GET", self.build_messages_url(top=top, unread_only=unread_only))
        return data.get("value", [])

    def get_message_attachments(self, message_id: str) -> list[dict[str, Any]]:
        if not self.is_available:
            return []
        data = self._request_json("GET", self.build_attachments_url(message_id))
        return data.get("value", [])

    def mark_message_processed(self, message_id: str, *, category: str = "Peak10Processed") -> dict[str, Any]:
        if not self.is_available:
            return {}
        url = (
            f"{self._config.graph_base_url}/users/"
            f"{urllib.parse.quote(self._config.mailbox_address)}/messages/"
            f"{urllib.parse.quote(message_id)}"
        )
        payload = {"isRead": True, "categories": [category]}
        return self._request_json("PATCH", url, payload=payload)

    def upload_file(self, filename: str, file_bytes: bytes, *, folder_path: str = "") -> dict[str, Any]:
        if not self.sharepoint_available:
            return {}
        url = self.build_upload_url(filename, folder_path=folder_path)
        return self._request_json(
            "PUT",
            url,
            payload=file_bytes,
            content_type="application/octet-stream",
        )

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._access_token_expires_at:
            return self._access_token

        token_url = (
            f"https://login.microsoftonline.com/{self._config.tenant_id}/oauth2/v2.0/token"
        )
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "scope": "https://graph.microsoft.com/.default",
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            token_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._access_token_expires_at = time.time() + max(expires_in - 60, 60)
        return self._access_token

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Any = None,
        content_type: str = "application/json",
    ) -> dict[str, Any]:
        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        data: Optional[bytes] = None

        if payload is not None:
            if isinstance(payload, bytes):
                data = payload
            else:
                data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = content_type

        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers=headers,
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()

        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))


_client: Optional[GraphClient] = None


def get_graph_client() -> GraphClient:
    global _client
    if _client is None:
        _client = GraphClient()
    return _client


def reset_graph_client() -> None:
    global _client
    _client = None
