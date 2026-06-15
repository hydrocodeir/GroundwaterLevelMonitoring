from __future__ import annotations

from dataclasses import dataclass

from app.services.ai.config import DEFAULT_GEMINI_BASE_URL
from app.services.ai.http_client import post_gemini_generation


@dataclass(frozen=True)
class GeminiClient:
    api_key: str
    model: str
    base_url: str = DEFAULT_GEMINI_BASE_URL
    timeout_seconds: int = 60

    @property
    def provider_name(self) -> str:
        return "gemini"

    def complete(self, messages: list[dict[str, str]]) -> str:
        system_text = "\n\n".join(
            message["content"]
            for message in messages
            if message.get("role") == "system"
        )
        contents = []
        for message in messages:
            role = message.get("role")
            if role == "system":
                continue
            contents.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": message.get("content", "")}],
                }
            )
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        if system_text:
            payload["systemInstruction"] = {
                "parts": [{"text": system_text}],
            }
        return post_gemini_generation(
            url=f"{self.base_url.rstrip('/')}/models/{self.model}:generateContent",
            api_key=self.api_key,
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
