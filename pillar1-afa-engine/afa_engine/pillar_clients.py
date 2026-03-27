"""Cross-pillar HTTP clients for Peak 10 backend integrations."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class DocumentAiClientConfig:
    base_url: str = ""
    function_key: str = ""


class DocumentAiClient:
    """Minimal client for Pillar 3 Document AI staging."""

    def __init__(self, config: Optional[DocumentAiClientConfig] = None) -> None:
        self._config = config or self._load_config_from_env()

    def _load_config_from_env(self) -> DocumentAiClientConfig:
        base_url = os.environ.get("PILLAR3_DOCUMENT_AI_URL", "").strip()
        if not base_url:
            base_url = os.environ.get("PILLAR3_BASE_URL", "").strip()
        return DocumentAiClientConfig(
            base_url=base_url.rstrip("/"),
            function_key=os.environ.get("PILLAR3_DOCUMENT_AI_KEY", ""),
        )

    @property
    def is_available(self) -> bool:
        return bool(self._config.base_url)

    def stage_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_available:
            return {}

        url = f"{self._config.base_url}/api/documents/stage"
        if self._config.function_key:
            query = urllib.parse.urlencode({"code": self._config.function_key})
            url = f"{url}?{query}"

        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))


_document_ai_client: DocumentAiClient | None = None


def get_document_ai_client() -> DocumentAiClient:
    global _document_ai_client
    if _document_ai_client is None:
        _document_ai_client = DocumentAiClient()
    return _document_ai_client
