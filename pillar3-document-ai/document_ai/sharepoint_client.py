"""Minimal SharePoint upload client for Pillar 3 filing operations."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


@dataclass
class SharePointClientConfig:
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    sharepoint_site_id: str = ""
    sharepoint_drive_id: str = ""
    graph_base_url: str = GRAPH_BASE_URL


class SharePointClient:
    """Client-credentials SharePoint file uploader."""

    def __init__(self, config: SharePointClientConfig | None = None) -> None:
        self._config = config or self._load_config_from_env()
        self._access_token = ""
        self._access_token_expires_at = 0.0

    def _load_config_from_env(self) -> SharePointClientConfig:
        return SharePointClientConfig(
            tenant_id=os.environ.get("GRAPH_TENANT_ID", ""),
            client_id=os.environ.get("GRAPH_CLIENT_ID", ""),
            client_secret=os.environ.get("GRAPH_CLIENT_SECRET", ""),
            sharepoint_site_id=os.environ.get("GRAPH_SHAREPOINT_SITE_ID", ""),
            sharepoint_drive_id=os.environ.get("GRAPH_SHAREPOINT_DRIVE_ID", ""),
        )

    @property
    def is_available(self) -> bool:
        return all(
            [
                self._config.tenant_id,
                self._config.client_id,
                self._config.client_secret,
                self._config.sharepoint_site_id,
                self._config.sharepoint_drive_id,
            ]
        )

    def upload_file(self, filename: str, file_bytes: bytes, *, folder_path: str = "") -> dict[str, object]:
        if not self.is_available:
            return {}

        normalized_folder = folder_path.strip("/")
        item_path = f"{normalized_folder}/{filename}" if normalized_folder else filename
        url = (
            f"{self._config.graph_base_url}/sites/{self._config.sharepoint_site_id}"
            f"/drives/{self._config.sharepoint_drive_id}/root:/"
            f"{urllib.parse.quote(item_path, safe='/')}:/content"
        )
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
        payload: bytes | dict[str, object] | None = None,
        content_type: str = "application/json",
    ) -> dict[str, object]:
        token = self._get_access_token()
        data = None
        if isinstance(payload, dict):
            data = json.dumps(payload).encode("utf-8")
        elif isinstance(payload, bytes):
            data = payload

        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))


_client: SharePointClient | None = None


def get_sharepoint_client() -> SharePointClient:
    global _client
    if _client is None:
        _client = SharePointClient()
    return _client

