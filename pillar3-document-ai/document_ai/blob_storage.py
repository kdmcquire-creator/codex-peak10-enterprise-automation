"""Azure Blob staging support for Pillar 3 document intake."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from azure.storage.blob import BlobServiceClient
except Exception:  # pragma: no cover - optional dependency in local/dev
    BlobServiceClient = None


DEFAULT_CONTAINER_NAME = "staging-documents"


@dataclass
class BlobStagingConfig:
    connection_string: str = ""
    container_name: str = DEFAULT_CONTAINER_NAME


class BlobStagingClient:
    """Simple blob wrapper with offline-friendly behavior."""

    def __init__(self, config: BlobStagingConfig | None = None) -> None:
        self._config = config or self._load_config_from_env()
        self._service_client = None
        self._container_client = None

        if self.is_available:
            self._service_client = BlobServiceClient.from_connection_string(
                self._config.connection_string
            )
            self._container_client = self._service_client.get_container_client(
                self._config.container_name
            )
            try:
                self._container_client.create_container()
            except Exception:
                pass

    def _load_config_from_env(self) -> BlobStagingConfig:
        return BlobStagingConfig(
            connection_string=(
                os.environ.get("DOCUMENT_AI_BLOB_CONNECTION_STRING", "")
                or os.environ.get("AzureWebJobsStorage", "")
            ),
            container_name=os.environ.get(
                "DOCUMENT_AI_STAGING_CONTAINER",
                DEFAULT_CONTAINER_NAME,
            ),
        )

    @property
    def is_available(self) -> bool:
        return bool(self._config.connection_string and BlobServiceClient is not None)

    def upload_bytes(self, document_id: str, file_bytes: bytes, *, content_type: str = "") -> str:
        if not self.is_available or self._container_client is None:
            return ""

        blob_name = document_id
        blob_client = self._container_client.get_blob_client(blob_name)
        content_settings = None
        if content_type:
            try:
                from azure.storage.blob import ContentSettings
                content_settings = ContentSettings(content_type=content_type)
            except Exception:
                content_settings = None
        blob_client.upload_blob(
            file_bytes,
            overwrite=True,
            content_settings=content_settings,
        )
        return blob_client.url

    def download_bytes(self, document_id: str) -> bytes | None:
        if not self.is_available or self._container_client is None:
            return None
        blob_client = self._container_client.get_blob_client(document_id)
        try:
            return blob_client.download_blob().readall()
        except Exception:
            return None

    def has_bytes(self, document_id: str) -> bool:
        if not self.is_available or self._container_client is None:
            return False
        blob_client = self._container_client.get_blob_client(document_id)
        try:
            return blob_client.exists()
        except Exception:
            return False


_client: BlobStagingClient | None = None


def get_blob_staging_client() -> BlobStagingClient:
    global _client
    if _client is None:
        _client = BlobStagingClient()
    return _client
