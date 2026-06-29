from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from app.services.ai.config import DEFAULT_NVIDIA_BASE_URL
from app.services.ai.errors import (
    AIForbiddenError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
)


NVIDIA_MODEL_OPTIONS: dict[str, dict[str, object]] = {
    "openai/gpt-oss-120b": {
        "temperature": 1,
        "top_p": 1,
        "max_tokens": 4096,
    },
    "nvidia/nemotron-3-super-120b-a12b": {
        "temperature": 1,
        "top_p": 0.95,
        "max_tokens": 16384,
        "extra_body": {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": 16384,
        },
    },
    "z-ai/glm-5.1": {
        "temperature": 1,
        "top_p": 1,
        "max_tokens": 16384,
    },
    "qwen/qwen3-next-80b-a3b-instruct": {
        "temperature": 0.6,
        "top_p": 0.7,
        "max_tokens": 4096,
    },
    "qwen/qwen3.5-397b-a17b": {
        "temperature": 0.6,
        "top_p": 0.95,
        "max_tokens": 16384,
        "presence_penalty": 0,
        "extra_body": {
            "top_k": 20,
            "repetition_penalty": 1,
        },
    },
    "moonshotai/kimi-k2.6": {
        "temperature": 1,
        "top_p": 1,
        "max_tokens": 16384,
    },
    "minimaxai/minimax-m2.7": {
        "temperature": 1,
        "top_p": 0.95,
        "max_tokens": 8192,
    },
    "deepseek-ai/deepseek-v4-flash": {
        "temperature": 1,
        "top_p": 0.95,
        "max_tokens": 16384,
        "extra_body": {
            "chat_template_kwargs": {
                "thinking": True,
                "reasoning_effort": "high",
            },
        },
    },
    "google/gemma-4-31b-it": {
        "temperature": 1,
        "top_p": 0.95,
        "max_tokens": 16384,
        "extra_body": {
            "chat_template_kwargs": {"enable_thinking": True},
        },
    },
}


@dataclass(frozen=True)
class NvidiaClient:
    api_key: str
    model: str
    base_url: str = DEFAULT_NVIDIA_BASE_URL
    timeout_seconds: int = 60
    temperature: float = 0.2
    top_p: float = 0.7
    max_tokens: int = 1024

    @property
    def provider_name(self) -> str:
        return "nvidia"

    def _payload(self, messages: list[dict[str, str]]) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        model_options = NVIDIA_MODEL_OPTIONS.get(self.model, {})
        for key in ("temperature", "top_p", "max_tokens", "presence_penalty"):
            if key in model_options:
                payload[key] = model_options[key]
        extra_body = model_options.get("extra_body")
        if isinstance(extra_body, dict):
            payload["extra_body"] = extra_body
        return payload

    @staticmethod
    def _extract_content(response: Any) -> str:
        choices = getattr(response, "choices", None)
        if not choices and isinstance(response, dict):
            choices = response.get("choices")
        if not choices:
            raise AIProviderError(
                "nvidia returned no completion choices.",
                "nvidia",
            )
        first_choice = choices[0]
        message = (
            first_choice.message
            if hasattr(first_choice, "message")
            else first_choice.get("message")
            if isinstance(first_choice, dict)
            else None
        )
        content = (
            getattr(message, "content", None)
            if not isinstance(message, dict)
            else message.get("content")
        )
        if not isinstance(content, str) or not content.strip():
            raise AIProviderError(
                "nvidia returned an empty completion.",
                "nvidia",
            )
        return content.strip()

    @staticmethod
    def _forbidden_message(message: str) -> str:
        normalized = (message or "").strip()
        lowered = normalized.lower()
        if (
            not normalized
            or normalized == "Forbidden"
            or "<html" in lowered
            or "<h1>403 forbidden</h1>" in lowered
        ):
            return (
                "nvidia rejected access with HTTP 403. The NVIDIA API key, "
                "account, selected model, or current network location is not "
                "permitted to use NVIDIA API Catalog."
            )
        return normalized

    def complete(self, messages: list[dict[str, str]]) -> str:
        openai_sdk = importlib.import_module("openai")
        client = openai_sdk.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            max_retries=0,
        )
        try:
            response = client.chat.completions.create(**self._payload(messages))
        except Exception as error:
            status_code = getattr(error, "status_code", None)
            message = str(error) or f"{self.provider_name} API request failed."
            if status_code == 403 or error.__class__.__name__ == "PermissionDeniedError":
                raise AIForbiddenError(
                    self._forbidden_message(message),
                    self.provider_name,
                ) from error
            if status_code == 429 or error.__class__.__name__ == "RateLimitError":
                raise AIRateLimitError(message, self.provider_name) from error
            if error.__class__.__name__ == "APITimeoutError":
                raise AITimeoutError(message, self.provider_name) from error
            if error.__class__.__name__ in {"APIConnectionError", "APIError", "APIStatusError"}:
                raise AIProviderError(message, self.provider_name) from error
            raise

        return self._extract_content(response)
