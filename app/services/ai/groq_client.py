from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from app.services.ai.config import DEFAULT_GROQ_BASE_URL
from app.services.ai.errors import (
    AIForbiddenError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
)
from app.services.ai.http_client import post_chat_completion


@dataclass(frozen=True)
class GroqClient:
    api_key: str
    model: str
    base_url: str = DEFAULT_GROQ_BASE_URL
    timeout_seconds: int = 60

    @property
    def provider_name(self) -> str:
        return "groq"

    def _complete_with_openai_sdk(self, messages: list[dict[str, str]]) -> str:
        openai_sdk = importlib.import_module("openai")
        client = openai_sdk.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            max_retries=0,
        )
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
            )
        except Exception as error:
            status_code = getattr(error, "status_code", None)
            message = str(error) or f"{self.provider_name} API request failed."
            if status_code == 403 or error.__class__.__name__ == "PermissionDeniedError":
                raise AIForbiddenError(message, self.provider_name) from error
            if status_code == 429 or error.__class__.__name__ == "RateLimitError":
                raise AIRateLimitError(message, self.provider_name) from error
            if error.__class__.__name__ == "APITimeoutError":
                raise AITimeoutError(message, self.provider_name) from error
            if error.__class__.__name__ in {"APIConnectionError", "APIError", "APIStatusError"}:
                raise AIProviderError(message, self.provider_name) from error
            raise

        choices = getattr(response, "choices", None)
        if not choices:
            raise AIProviderError(
                f"{self.provider_name} returned no completion choices.",
                self.provider_name,
            )
        message = choices[0].message if hasattr(choices[0], "message") else None
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise AIProviderError(
                f"{self.provider_name} returned an empty completion.",
                self.provider_name,
            )
        return content.strip()

    def complete(self, messages: list[dict[str, str]]) -> str:
        try:
            return self._complete_with_openai_sdk(messages)
        except ImportError:
            pass
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        return post_chat_completion(
            provider=self.provider_name,
            url=f"{self.base_url.rstrip('/')}/chat/completions",
            headers=headers,
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
