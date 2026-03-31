"""Cross-pillar HTTP clients for Peak 10 backend integrations."""

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


logger = logging.getLogger("expense-hub.pillar-clients")


@dataclass
class AfaEngineClientConfig:
    base_url: str = ""
    function_key: str = ""
    timeout_seconds: float = 60.0
    max_attempts: int = 3
    retry_backoff_seconds: float = 1.0


class AfaEngineClient:
    """Minimal client for Pillar 1 invoice intake."""

    def __init__(self, config: Optional[AfaEngineClientConfig] = None) -> None:
        self._config = config or self._load_config_from_env()

    def _load_config_from_env(self) -> AfaEngineClientConfig:
        base_url = os.environ.get("PILLAR1_AFA_URL", "").strip()
        if not base_url:
            base_url = os.environ.get("PILLAR1_BASE_URL", "").strip()
        return AfaEngineClientConfig(
            base_url=base_url.rstrip("/"),
            function_key=os.environ.get("PILLAR1_AFA_KEY", "").strip(),
            timeout_seconds=float(os.environ.get("PILLAR1_AFA_TIMEOUT_SECONDS", "60")),
            max_attempts=max(1, int(os.environ.get("PILLAR1_AFA_MAX_ATTEMPTS", "3"))),
            retry_backoff_seconds=max(
                0.0,
                float(os.environ.get("PILLAR1_AFA_RETRY_BACKOFF_SECONDS", "1")),
            ),
        )

    @property
    def is_available(self) -> bool:
        return bool(self._config.base_url and self._config.function_key)

    def intake_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_available:
            return {}

        url = self._build_intake_url()
        request_body = json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None

        for attempt in range(1, self._config.max_attempts + 1):
            request = urllib.request.Request(
                url,
                data=request_body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                    raw = response.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
            except Exception as exc:
                last_error = exc
                if not self._should_retry(exc, attempt):
                    raise
                delay_seconds = self._retry_delay_seconds(attempt)
                logger.warning(
                    "Retrying Pillar 1 intake request after transient failure "
                    "(attempt %s/%s, delay=%ss): %s",
                    attempt,
                    self._config.max_attempts,
                    delay_seconds,
                    exc,
                )
                if delay_seconds > 0:
                    time.sleep(delay_seconds)

        assert last_error is not None
        raise last_error

    def _build_intake_url(self) -> str:
        url = f"{self._config.base_url}/api/invoices/intake"
        query = urllib.parse.urlencode({"code": self._config.function_key})
        return f"{url}?{query}"

    def _should_retry(self, exc: Exception, attempt: int) -> bool:
        if attempt >= self._config.max_attempts:
            return False
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code in {408, 429, 500, 502, 503, 504}
        if isinstance(exc, urllib.error.URLError):
            return True
        if isinstance(exc, TimeoutError):
            return True
        return False

    def _retry_delay_seconds(self, attempt: int) -> float:
        return self._config.retry_backoff_seconds * attempt


_afa_engine_client: AfaEngineClient | None = None


def get_afa_engine_client() -> AfaEngineClient:
    global _afa_engine_client
    if _afa_engine_client is None:
        _afa_engine_client = AfaEngineClient()
    return _afa_engine_client
