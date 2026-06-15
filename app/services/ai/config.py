from __future__ import annotations

from dataclasses import dataclass
import os

from app.settings import load_environment


load_environment()

SUPPORTED_PROVIDERS = {"groq", "openrouter"}
DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_OPENROUTER_MODEL = "openrouter/auto"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_SITE_URL = "http://localhost:3000"
DEFAULT_OPENROUTER_APP_NAME = "Groundwater Dashboard AI"
DEFAULT_AI_PROVIDER = "openrouter"


@dataclass(frozen=True)
class AIConfig:
    provider: str
    groq_api_key: str
    groq_model: str
    groq_base_url: str
    openrouter_api_key: str
    openrouter_model: str
    openrouter_base_url: str
    openrouter_site_url: str
    openrouter_app_name: str
    timeout_seconds: int = 60
    max_request_bytes: int = 64_000

    @classmethod
    def from_env(cls) -> "AIConfig":
        provider = os.getenv("AI_PROVIDER", DEFAULT_AI_PROVIDER).strip().lower()
        groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        groq_model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip()
        groq_base_url = os.getenv("GROQ_BASE_URL", DEFAULT_GROQ_BASE_URL).strip()
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        openrouter_model = os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip()
        openrouter_base_url = os.getenv(
            "OPENROUTER_BASE_URL",
            DEFAULT_OPENROUTER_BASE_URL,
        ).strip()
        openrouter_site_url = os.getenv(
            "OPENROUTER_SITE_URL",
            DEFAULT_OPENROUTER_SITE_URL,
        ).strip()
        openrouter_app_name = os.getenv(
            "OPENROUTER_APP_NAME",
            DEFAULT_OPENROUTER_APP_NAME,
        ).strip()
        return cls(
            provider=provider,
            groq_api_key=groq_api_key,
            groq_model=groq_model or DEFAULT_GROQ_MODEL,
            groq_base_url=groq_base_url or DEFAULT_GROQ_BASE_URL,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=openrouter_model or DEFAULT_OPENROUTER_MODEL,
            openrouter_base_url=openrouter_base_url or DEFAULT_OPENROUTER_BASE_URL,
            openrouter_site_url=openrouter_site_url or DEFAULT_OPENROUTER_SITE_URL,
            openrouter_app_name=openrouter_app_name or DEFAULT_OPENROUTER_APP_NAME,
        )
