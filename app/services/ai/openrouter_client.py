from __future__ import annotations

from dataclasses import dataclass

from app.services.ai.config import DEFAULT_OPENROUTER_BASE_URL
from app.services.ai.errors import AIProviderError
from app.services.ai.http_client import post_chat_completion


@dataclass(frozen=True)
class OpenRouterClient:
    api_key: str
    model: str
    base_url: str = DEFAULT_OPENROUTER_BASE_URL
    site_url: str = "http://localhost:3000"
    app_name: str = "Groundwater Dashboard AI"
    timeout_seconds: int = 60

    @property
    def provider_name(self) -> str:
        return "openrouter"

    @staticmethod
    def _is_retryable_parameter_error(message: str) -> bool:
        normalized = (message or "").strip().lower()
        return any(
            pattern in normalized
            for pattern in (
                "response_format",
                "structured output",
                "structured_outputs",
                "json_object",
                "unsupported parameter",
                "another requested parameter",
                "provider returned a generic error",
            )
        )

    def _should_use_json_mode(self) -> bool:
        return self.model not in {"openrouter/free", "openrouter/auto"}

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        *,
        include_response_format: bool,
        include_temperature: bool = True,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
        }
        if include_temperature:
            payload["temperature"] = 0.2
        if include_response_format:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def complete(self, messages: list[dict[str, str]]) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            headers["X-Title"] = self.app_name
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        attempts = [
            self._build_payload(
                messages,
                include_response_format=self._should_use_json_mode(),
            ),
            self._build_payload(
                messages,
                include_response_format=False,
            ),
            self._build_payload(
                messages,
                include_response_format=False,
                include_temperature=False,
            ),
        ]
        seen_payloads: set[str] = set()
        last_error: AIProviderError | None = None
        for payload in attempts:
            payload_key = repr(payload)
            if payload_key in seen_payloads:
                continue
            seen_payloads.add(payload_key)
            try:
                return post_chat_completion(
                    provider=self.provider_name,
                    url=url,
                    headers=headers,
                    payload=payload,
                    timeout_seconds=self.timeout_seconds,
                )
            except AIProviderError as error:
                last_error = error
                if not self._is_retryable_parameter_error(error.message):
                    raise
        if last_error is not None:
            raise last_error
        raise AIProviderError(
            "openrouter request failed before a completion attempt was made.",
            self.provider_name,
        )
