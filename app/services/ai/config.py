from __future__ import annotations

from dataclasses import dataclass
import os

from app.settings import load_environment


load_environment()

SUPPORTED_PROVIDERS = {"gemini", "groq", "nvidia", "openrouter"}
DEFAULT_NVIDIA_MODEL = "meta/llama-3.2-3b-instruct"
DEFAULT_NVIDIA_MODELS = (
    "meta/llama-3.2-3b-instruct",
)
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_GEMINI_MODELS = (
    "gemini-3.5-flash",
)
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"
DEFAULT_GROQ_MODELS = (
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
)
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_OPENROUTER_MODEL = "openrouter/free"
DEFAULT_OPENROUTER_MODELS = (
    "openrouter/free",
    "openrouter/auto",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "google/gemma-4-26b-a4b-it:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "google/gemma-4-31b-it:free",
    "nex-agi/nex-n2-pro:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-coder:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
)
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_SITE_URL = "http://localhost:3000"
DEFAULT_OPENROUTER_APP_NAME = "Groundwater Dashboard AI"
DEFAULT_AI_PROVIDER = "nvidia"


def _model_list_from_env(name: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return defaults
    models = tuple(model.strip() for model in raw.split(",") if model.strip())
    return models or defaults


def _unique_models(default_model: str, models: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((default_model, *models)))


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
    nvidia_api_key: str = ""
    nvidia_model: str = DEFAULT_NVIDIA_MODEL
    nvidia_base_url: str = DEFAULT_NVIDIA_BASE_URL
    gemini_api_key: str = ""
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_base_url: str = DEFAULT_GEMINI_BASE_URL
    timeout_seconds: int = 60
    max_request_bytes: int = 64_000
    nvidia_models: tuple[str, ...] = DEFAULT_NVIDIA_MODELS
    gemini_models: tuple[str, ...] = DEFAULT_GEMINI_MODELS
    groq_models: tuple[str, ...] = DEFAULT_GROQ_MODELS
    openrouter_models: tuple[str, ...] = DEFAULT_OPENROUTER_MODELS

    def default_model_for(self, provider: str) -> str:
        if provider == "nvidia":
            return self.nvidia_model
        if provider == "gemini":
            return self.gemini_model
        if provider == "groq":
            return self.groq_model
        return self.openrouter_model

    def allowed_models_for(self, provider: str) -> tuple[str, ...]:
        if provider == "nvidia":
            return _unique_models(self.nvidia_model, self.nvidia_models)
        if provider == "gemini":
            return _unique_models(self.gemini_model, self.gemini_models)
        if provider == "groq":
            return _unique_models(self.groq_model, self.groq_models)
        if provider == "openrouter":
            return _unique_models(self.openrouter_model, self.openrouter_models)
        return ()

    def has_api_key_for(self, provider: str) -> bool:
        if provider == "nvidia":
            return bool(self.nvidia_api_key)
        if provider == "gemini":
            return bool(self.gemini_api_key)
        if provider == "groq":
            return bool(self.groq_api_key)
        if provider == "openrouter":
            return bool(self.openrouter_api_key)
        return False

    @classmethod
    def from_env(cls) -> "AIConfig":
        provider = os.getenv("AI_PROVIDER", DEFAULT_AI_PROVIDER).strip().lower()
        nvidia_api_key = os.getenv("NVIDIA_API_KEY", "").strip()
        nvidia_model = os.getenv("NVIDIA_MODEL", DEFAULT_NVIDIA_MODEL).strip()
        nvidia_base_url = os.getenv(
            "NVIDIA_BASE_URL",
            DEFAULT_NVIDIA_BASE_URL,
        ).strip()
        gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        gemini_model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
        gemini_base_url = os.getenv(
            "GEMINI_BASE_URL",
            DEFAULT_GEMINI_BASE_URL,
        ).strip()
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
            nvidia_api_key=nvidia_api_key,
            nvidia_model=nvidia_model or DEFAULT_NVIDIA_MODEL,
            nvidia_base_url=nvidia_base_url or DEFAULT_NVIDIA_BASE_URL,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model or DEFAULT_GEMINI_MODEL,
            gemini_base_url=gemini_base_url or DEFAULT_GEMINI_BASE_URL,
            nvidia_models=_model_list_from_env(
                "NVIDIA_MODELS",
                DEFAULT_NVIDIA_MODELS,
            ),
            gemini_models=_model_list_from_env(
                "GEMINI_MODELS",
                DEFAULT_GEMINI_MODELS,
            ),
            groq_models=_model_list_from_env("GROQ_MODELS", DEFAULT_GROQ_MODELS),
            openrouter_models=_model_list_from_env(
                "OPENROUTER_MODELS",
                DEFAULT_OPENROUTER_MODELS,
            ),
        )
