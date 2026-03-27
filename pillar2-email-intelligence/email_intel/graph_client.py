"""Minimal Microsoft Graph client wrapper for Pillar 2 integrations."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


logger = logging.getLogger("email-intel.graph")

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
MAIL_FOLDER_SELECT_FIELDS = ["id", "displayName", "wellKnownName"]


class GraphRequestError(RuntimeError):
    """Represents a failed Microsoft Graph request with parsed error detail."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str = "",
        message: str = "",
        url: str = "",
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.url = url
        detail = message or "Request failed"
        if code:
            detail = f"{code}: {detail}"
        super().__init__(detail)


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

    def build_message_url(self, message_id: str, *, select_fields: Optional[list[str]] = None) -> str:
        params = {}
        if select_fields:
            params["$select"] = ",".join(select_fields)

        query = urllib.parse.urlencode(params, safe=",$ ") if params else ""
        base_url = (
            f"{self._config.graph_base_url}/users/"
            f"{urllib.parse.quote(self._config.mailbox_address)}/messages/"
            f"{urllib.parse.quote(message_id)}"
        )
        if not query:
            return base_url
        return f"{base_url}?{query}"

    def build_mail_folders_url(
        self,
        *,
        parent_folder_id: str = "",
        select_fields: Optional[list[str]] = None,
        top: int = 200,
        include_hidden_folders: bool = False,
    ) -> str:
        params = {"$top": top}
        if select_fields:
            params["$select"] = ",".join(select_fields)
        if include_hidden_folders:
            params["includeHiddenFolders"] = "true"

        query = urllib.parse.urlencode(params, safe=",$ ")
        if parent_folder_id:
            return (
                f"{self._config.graph_base_url}/users/"
                f"{urllib.parse.quote(self._config.mailbox_address)}/mailFolders/"
                f"{urllib.parse.quote(parent_folder_id)}/childFolders?{query}"
            )
        return (
            f"{self._config.graph_base_url}/users/"
            f"{urllib.parse.quote(self._config.mailbox_address)}/mailFolders?{query}"
        )

    def build_mail_folder_url(
        self,
        folder_id: str,
        *,
        select_fields: Optional[list[str]] = None,
    ) -> str:
        params = {}
        if select_fields:
            params["$select"] = ",".join(select_fields)

        query = urllib.parse.urlencode(params, safe=",$ ") if params else ""
        base_url = (
            f"{self._config.graph_base_url}/users/"
            f"{urllib.parse.quote(self._config.mailbox_address)}/mailFolders/"
            f"{urllib.parse.quote(folder_id)}"
        )
        if not query:
            return base_url
        return f"{base_url}?{query}"

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

    def get_message(
        self,
        message_id: str,
        *,
        select_fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        if not self.is_available:
            return {}
        return self._request_json(
            "GET",
            self.build_message_url(message_id, select_fields=select_fields),
        )

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

    def update_message(self, message_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        if not self.is_available:
            return {}
        url = self.build_message_url(message_id)
        return self._request_json("PATCH", url, payload=updates)

    def move_message(self, message_id: str, destination_id: str) -> dict[str, Any]:
        if not self.is_available:
            return {}
        url = f"{self.build_message_url(message_id)}/move"
        last_error: Optional[GraphRequestError] = None
        for candidate in self._move_destination_candidates(destination_id):
            try:
                return self._request_json("POST", url, payload={"destinationId": candidate})
            except GraphRequestError as exc:
                last_error = exc
                if exc.status_code != 404:
                    raise
        if last_error is not None:
            raise last_error
        return self._request_json("POST", url, payload={"destinationId": destination_id})

    def list_mail_folders(
        self,
        *,
        parent_folder_id: str = "",
        select_fields: Optional[list[str]] = None,
        top: int = 200,
        include_hidden_folders: bool = False,
    ) -> list[dict[str, Any]]:
        if not self.is_available:
            return []
        data = self._request_json(
            "GET",
            self.build_mail_folders_url(
                parent_folder_id=parent_folder_id,
                select_fields=select_fields,
                top=top,
                include_hidden_folders=include_hidden_folders,
            ),
        )
        return data.get("value", [])

    def get_mail_folder(
        self,
        folder_id: str,
        *,
        select_fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        if not self.is_available:
            return {}
        return self._request_json(
            "GET",
            self.build_mail_folder_url(folder_id, select_fields=select_fields),
        )

    def resolve_mail_folder_id(self, destination: str) -> str:
        normalized = destination.strip().strip("/")
        if not normalized or not self.is_available:
            return normalized

        path_segments = [segment.strip() for segment in normalized.split("/") if segment.strip()]
        parent_folder_id = ""
        for index, segment in enumerate(path_segments):
            resolved = self._resolve_mail_folder_segment(segment, parent_folder_id=parent_folder_id)
            if not resolved:
                if len(path_segments) == 1:
                    return normalized
                raise ValueError(f"Unable to resolve mailbox folder path '{normalized}'")
            parent_folder_id = resolved
            if index == len(path_segments) - 1:
                return resolved

        return normalized

    def _resolve_mail_folder_segment(self, segment: str, *, parent_folder_id: str = "") -> str:
        # Well-known names and folder IDs can usually be dereferenced directly at the root.
        if not parent_folder_id:
            try:
                folder = self.get_mail_folder(segment, select_fields=MAIL_FOLDER_SELECT_FIELDS)
            except (GraphRequestError, urllib.error.HTTPError) as exc:
                status_code = exc.status_code if isinstance(exc, GraphRequestError) else exc.code
                if status_code != 404:
                    raise
            else:
                folder_id = folder.get("id")
                if isinstance(folder_id, str) and folder_id.strip():
                    return folder_id

        folders = self.list_mail_folders(
            parent_folder_id=parent_folder_id,
            select_fields=MAIL_FOLDER_SELECT_FIELDS,
            top=200,
            include_hidden_folders=True,
        )
        for folder in folders:
            for key in ("displayName", "wellKnownName", "id"):
                value = folder.get(key)
                if isinstance(value, str) and value.strip().lower() == segment.lower():
                    folder_id = folder.get("id")
                    if isinstance(folder_id, str) and folder_id.strip():
                        return folder_id
        return ""

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

    def send_mail(
        self,
        *,
        to_recipients: list[str],
        subject: str,
        body: str,
        cc_recipients: Optional[list[str]] = None,
        content_type: str = "Text",
    ) -> dict[str, Any]:
        if not self.is_available:
            return {}

        def _graph_recipient(address: str) -> dict[str, Any]:
            return {"emailAddress": {"address": address}}

        url = (
            f"{self._config.graph_base_url}/users/"
            f"{urllib.parse.quote(self._config.mailbox_address)}/sendMail"
        )
        payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": content_type,
                    "content": body,
                },
                "toRecipients": [_graph_recipient(address) for address in to_recipients],
                "ccRecipients": [
                    _graph_recipient(address)
                    for address in (cc_recipients or [])
                ],
            },
            "saveToSentItems": True,
        }
        return self._request_json("POST", url, payload=payload)

    def create_calendar_event(
        self,
        *,
        subject: str,
        body: str,
        attendees: list[str],
        start_iso: str,
        end_iso: str,
        location_display_name: str = "",
        timezone_name: str = "UTC",
    ) -> dict[str, Any]:
        if not self.is_available:
            return {}

        def _graph_recipient(address: str) -> dict[str, Any]:
            return {"emailAddress": {"address": address}, "type": "required"}

        url = (
            f"{self._config.graph_base_url}/users/"
            f"{urllib.parse.quote(self._config.mailbox_address)}/events"
        )
        payload: dict[str, Any] = {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body,
            },
            "start": {
                "dateTime": start_iso,
                "timeZone": timezone_name,
            },
            "end": {
                "dateTime": end_iso,
                "timeZone": timezone_name,
            },
            "attendees": [_graph_recipient(address) for address in attendees if address],
        }
        if location_display_name:
            payload["location"] = {"displayName": location_display_name}
        return self._request_json("POST", url, payload=payload)

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

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            graph_code = ""
            graph_message = exc.reason if isinstance(exc.reason, str) else ""
            if raw:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    payload = {}
                error_payload = payload.get("error", {}) if isinstance(payload, dict) else {}
                if isinstance(error_payload, dict):
                    graph_code = str(error_payload.get("code", "")).strip()
                    graph_message = str(error_payload.get("message", graph_message)).strip()
            raise GraphRequestError(
                status_code=exc.code,
                code=graph_code,
                message=graph_message or f"HTTP {exc.code}",
                url=url,
            ) from exc

        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _move_destination_candidates(self, destination_id: str) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()

        def _add(value: str) -> None:
            normalized = value.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                candidates.append(normalized)

        try:
            _add(self.resolve_mail_folder_id(destination_id))
        except Exception:
            logger.debug("Unable to pre-resolve mail folder destination '%s'", destination_id, exc_info=True)
        _add(destination_id)
        return candidates


_client: Optional[GraphClient] = None


def get_graph_client() -> GraphClient:
    global _client
    if _client is None:
        _client = GraphClient()
    return _client


def reset_graph_client() -> None:
    global _client
    _client = None
