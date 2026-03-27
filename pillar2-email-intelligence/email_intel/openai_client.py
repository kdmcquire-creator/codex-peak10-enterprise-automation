"""
Azure OpenAI SDK client wrapper for the Email Intelligence system.

Handles:
  - Email triage (classification, summary, deal signals, draft reply)
  - Document classification (type detection, metadata extraction)
  - Retry with exponential backoff
  - Token usage / cost tracking
  - Graceful fallback when credentials are not configured

Uses the openai Python SDK with Azure-specific configuration.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("email-intel.openai")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gpt-4o"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds
MAX_TOKENS_TRIAGE = 1500
MAX_TOKENS_CLASSIFICATION = 1000
TEMPERATURE = 0.1  # Low temperature for deterministic classification


@dataclass
class UsageRecord:
    """Tracks token usage for a single API call."""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: float = 0.0
    operation: str = ""
    timestamp: str = ""


@dataclass
class OpenAIClientConfig:
    """Configuration for the Azure OpenAI client."""
    endpoint: str = ""
    api_key: str = ""
    api_version: str = "2024-06-01"
    deployment_name: str = DEFAULT_MODEL
    use_managed_identity: bool = False


# ---------------------------------------------------------------------------
# Client wrapper
# ---------------------------------------------------------------------------

class AzureOpenAIClient:
    """
    Wrapper around the Azure OpenAI SDK.

    Falls back to returning None when credentials are not configured
    (local dev / testing without Azure access).
    """

    def __init__(self, config: Optional[OpenAIClientConfig] = None) -> None:
        self._config = config or self._load_config_from_env()
        self._client = None
        self._available = False
        self._usage_log: list[UsageRecord] = []

        self._init_client()

    def _load_config_from_env(self) -> OpenAIClientConfig:
        return OpenAIClientConfig(
            endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01"),
            deployment_name=os.environ.get("AZURE_OPENAI_DEPLOYMENT", DEFAULT_MODEL),
            use_managed_identity=os.environ.get("AZURE_OPENAI_USE_MI", "").lower() == "true",
        )

    def _init_client(self) -> None:
        if not self._config.endpoint:
            logger.info("No AZURE_OPENAI_ENDPOINT — OpenAI client unavailable")
            return

        try:
            from openai import AzureOpenAI

            if self._config.use_managed_identity:
                from azure.identity import DefaultAzureCredential
                credential = DefaultAzureCredential()
                token = credential.get_token("https://cognitiveservices.azure.com/.default")
                self._client = AzureOpenAI(
                    azure_endpoint=self._config.endpoint,
                    api_key=token.token,
                    api_version=self._config.api_version,
                )
            elif self._config.api_key:
                self._client = AzureOpenAI(
                    azure_endpoint=self._config.endpoint,
                    api_key=self._config.api_key,
                    api_version=self._config.api_version,
                )
            else:
                logger.warning("No API key or managed identity configured")
                return

            self._available = True
            logger.info("Azure OpenAI client initialized: %s", self._config.endpoint)
        except Exception as e:
            logger.warning("Azure OpenAI init failed: %s", e)

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def usage_log(self) -> list[UsageRecord]:
        return list(self._usage_log)

    @property
    def total_tokens_used(self) -> int:
        return sum(u.total_tokens for u in self._usage_log)

    # -- Core completion call with retry ------------------------------------

    def _call_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        operation: str,
    ) -> Optional[dict[str, Any]]:
        """
        Make an Azure OpenAI chat completion call with retry logic.

        Returns parsed JSON dict, or None if unavailable/failed.
        """
        if not self._available:
            logger.debug("OpenAI not available, skipping %s", operation)
            return None

        for attempt in range(MAX_RETRIES):
            try:
                start = time.time()
                response = self._client.chat.completions.create(
                    model=self._config.deployment_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=TEMPERATURE,
                    response_format={"type": "json_object"},
                )
                duration_ms = (time.time() - start) * 1000

                # Track usage
                usage = response.usage
                record = UsageRecord(
                    model=self._config.deployment_name,
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
                    duration_ms=duration_ms,
                    operation=operation,
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
                self._usage_log.append(record)

                # Parse response
                content = response.choices[0].message.content
                if content:
                    return json.loads(content)
                return None

            except json.JSONDecodeError as e:
                logger.warning("JSON parse error on attempt %d: %s", attempt + 1, e)
                return None  # Don't retry parse errors
            except Exception as e:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "OpenAI call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, MAX_RETRIES, e, delay,
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(delay)

        logger.error("OpenAI call failed after %d attempts for %s", MAX_RETRIES, operation)
        return None

    # -- Email triage -------------------------------------------------------

    def triage_email(self, prompt: str) -> Optional[dict[str, Any]]:
        """
        Send an email triage prompt to Azure OpenAI.

        The prompt is built by triage.build_triage_prompt().
        Returns the parsed JSON response dict, or None.
        """
        system = (
            "You are an executive email assistant for Peak 10 Energy. "
            "Respond only with valid JSON matching the requested schema."
        )
        return self._call_completion(
            system_prompt=system,
            user_prompt=prompt,
            max_tokens=MAX_TOKENS_TRIAGE,
            operation="email_triage",
        )

    # -- Document classification --------------------------------------------

    def classify_document(self, prompt: str) -> Optional[dict[str, Any]]:
        """
        Send a document classification prompt to Azure OpenAI.

        The prompt is built by classifier.build_classification_prompt().
        Returns the parsed JSON response dict, or None.
        """
        system = (
            "You are a document classification assistant for Peak 10 Energy, "
            "an upstream oil & gas company. Respond only with valid JSON matching "
            "the requested schema."
        )
        return self._call_completion(
            system_prompt=system,
            user_prompt=prompt,
            max_tokens=MAX_TOKENS_CLASSIFICATION,
            operation="document_classification",
        )

    # -- Draft reply generation ---------------------------------------------

    def generate_draft_reply(
        self,
        email_subject: str,
        email_body: str,
        sender_name: str,
        tone: str = "professional",
        context: str = "",
    ) -> Optional[dict[str, Any]]:
        """
        Generate a draft reply to an email.

        Returns dict with 'subject', 'body', 'tone', 'confidence'.
        """
        system = (
            "You are drafting a reply on behalf of K. McQuire, CEO of Peak 10 Energy. "
            "Write professionally but concisely. Respond with valid JSON."
        )
        user_prompt = f"""Draft a reply to this email.

From: {sender_name}
Subject: {email_subject}
Body:
---
{email_body[:2000]}
---

Tone: {tone}
{f'Additional context: {context}' if context else ''}

Respond in JSON:
{{
  "subject": "Re: <original subject>",
  "body": "<the draft reply>",
  "tone": "{tone}",
  "confidence": <0.0-1.0>
}}"""
        return self._call_completion(
            system_prompt=system,
            user_prompt=user_prompt,
            max_tokens=MAX_TOKENS_TRIAGE,
            operation="draft_reply",
        )

    def assist_calendar_request(self, prompt: str) -> Optional[dict[str, Any]]:
        """Generate structured meeting-assistant guidance for a calendar-related email."""
        system = (
            "You are an executive scheduling assistant for Peak 10 Energy. "
            "Extract scheduling intent conservatively and respond with valid JSON only."
        )
        return self._call_completion(
            system_prompt=system,
            user_prompt=prompt,
            max_tokens=MAX_TOKENS_TRIAGE,
            operation="calendar_assist",
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_client: Optional[AzureOpenAIClient] = None


def get_openai_client() -> AzureOpenAIClient:
    """Return the module-level AzureOpenAIClient singleton."""
    global _client
    if _client is None:
        _client = AzureOpenAIClient()
    return _client


def reset_openai_client() -> None:
    """Reset the singleton (for testing)."""
    global _client
    _client = None
