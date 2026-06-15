from __future__ import annotations

from dataclasses import dataclass

from app.services.ai.config import DEFAULT_GROQ_BASE_URL
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

    def complete(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
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
