from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, cast

import numpy as np
from pydantic import ValidationError

from app.services.ai.config import AIConfig, SUPPORTED_PROVIDERS
from app.services.ai.errors import (
    AIConfigurationError,
    AIProviderError,
    AIRateLimitError,
    AIRemoteError,
    AITimeoutError,
    AIValidationError,
)
from app.services.ai.groq_client import GroqClient
from app.services.ai.gemini_client import GeminiClient
from app.services.ai.openrouter_client import OpenRouterClient
from app.services.ai.prompts import build_system_prompt, build_user_prompt
from app.services.ai.schemas import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    LLMAnalysisPayload,
    RiskLevel,
    ProviderName,
)


LOGGER = logging.getLogger(__name__)


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if np.isfinite(number):
            return number
    except Exception:
        return None
    return None


def _normalize_risk_level(value: Any) -> RiskLevel | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"low", "moderate", "high", "critical"}:
        return normalized  # type: ignore[return-value]
    return None


def _ensure_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    return []


def _first_nonempty_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_llm_payload(
    payload: dict[str, Any],
    *,
    language: str,
    precomputed_risk_level: RiskLevel,
) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["analysis"] = _first_nonempty_string(
        normalized,
        (
            "analysis",
            "summary",
            "interpretation",
            "assessment",
            "response",
            "تحلیل",
            "خلاصه",
        ),
    )
    normalized["risk_level"] = (
        _first_nonempty_string(normalized, ("risk_level", "risk", "severity"))
        or precomputed_risk_level
    )
    if "key_findings" not in normalized:
        normalized["key_findings"] = normalized.get("findings", [])
    if "recommendations" not in normalized:
        normalized["recommendations"] = normalized.get("actions", [])
    if not _first_nonempty_string(
        normalized,
        ("uncertainty_note", "uncertainty", "limitations"),
    ):
        normalized["uncertainty_note"] = (
            "این تفسیر فقط بر پایه داده‌های خلاصه‌شده داشبورد است."
            if language == "fa"
            else "This interpretation is based only on the summarized dashboard data."
        )
    else:
        normalized["uncertainty_note"] = _first_nonempty_string(
            normalized,
            ("uncertainty_note", "uncertainty", "limitations"),
        )
    return normalized


def _build_repair_messages(
    messages: list[dict[str, str]],
    raw_content: str,
    precomputed_risk_level: RiskLevel,
) -> list[dict[str, str]]:
    return [
        *messages,
        {"role": "assistant", "content": raw_content},
        {
            "role": "user",
            "content": (
                "Your previous response did not match the required schema. "
                "Return one JSON object only, using the exact keys analysis, "
                "risk_level, key_findings, recommendations, and uncertainty_note. "
                "analysis and uncertainty_note must be non-empty strings; "
                "key_findings and recommendations must be arrays of strings. "
                f"Use risk_level={precomputed_risk_level!r}. Do not use Markdown."
            ),
        },
    ]


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
    first = candidate.find("{")
    last = candidate.rfind("}")
    if first >= 0 and last > first:
        candidate = candidate[first:last + 1]
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("LLM output was not a JSON object.")
    return parsed


def calculate_precomputed_risk_level(summary_data: dict[str, Any]) -> RiskLevel:
    groundwater_change = _coerce_float(summary_data.get("groundwater_level_change_m"))
    precipitation_anomaly = _coerce_float(summary_data.get("precipitation_anomaly_percent"))
    ndvi_change = _coerce_float(summary_data.get("ndvi_change"))
    critical_wells = _coerce_float(summary_data.get("critical_wells_count"))
    total_wells = _coerce_float(summary_data.get("total_wells_count"))
    critical_ratio = (
        critical_wells / total_wells
        if critical_wells is not None and total_wells and total_wells > 0
        else None
    )

    if (
        (groundwater_change is not None and groundwater_change <= -2.5)
        or (critical_ratio is not None and critical_ratio >= 0.5)
    ):
        return "critical"
    if (
        (groundwater_change is not None and groundwater_change <= -1.5)
        or (precipitation_anomaly is not None and precipitation_anomaly <= -25)
        or (critical_ratio is not None and critical_ratio >= 0.3)
    ):
        return "high"
    if (
        (groundwater_change is not None and groundwater_change <= -0.5)
        or (precipitation_anomaly is not None and precipitation_anomaly <= -10)
        or (ndvi_change is not None and ndvi_change <= -0.08)
    ):
        return "moderate"
    return "low"


class AIAnalysisService:
    def __init__(self, config: AIConfig | None = None, client: Any | None = None) -> None:
        self.config = config or AIConfig.from_env()
        self.client = client

    @staticmethod
    def _build_client(
        config: AIConfig,
        provider: str | None = None,
        model: str | None = None,
    ) -> Any:
        provider = provider or config.provider
        model = model or config.default_model_for(provider)
        if provider not in SUPPORTED_PROVIDERS:
            raise AIConfigurationError(
                f"Invalid AI_PROVIDER '{provider}'. Supported providers are gemini, groq, and openrouter.",
                provider,
            )
        if provider == "gemini":
            if not config.gemini_api_key:
                raise AIConfigurationError("GEMINI_API_KEY is missing.", provider)
            return GeminiClient(
                api_key=config.gemini_api_key,
                model=model,
                base_url=config.gemini_base_url,
                timeout_seconds=config.timeout_seconds,
            )
        if provider == "groq":
            if not config.groq_api_key:
                raise AIConfigurationError("GROQ_API_KEY is missing.", provider)
            return GroqClient(
                api_key=config.groq_api_key,
                model=model,
                base_url=config.groq_base_url,
                timeout_seconds=config.timeout_seconds,
            )
        if not config.openrouter_api_key:
            raise AIConfigurationError("OPENROUTER_API_KEY is missing.", provider)
        return OpenRouterClient(
            api_key=config.openrouter_api_key,
            model=model,
            base_url=config.openrouter_base_url,
            site_url=config.openrouter_site_url,
            app_name=config.openrouter_app_name,
            timeout_seconds=config.timeout_seconds,
        )

    @property
    def provider_name(self) -> str:
        return getattr(self.client, "provider_name", self.config.provider)

    @property
    def model_name(self) -> str:
        return getattr(
            self.client,
            "model",
            self.config.default_model_for(self.config.provider),
        )

    def _client_for_request(self, request: AIAnalysisRequest) -> Any:
        if self.client is not None:
            return self.client
        provider = request.provider or self.config.provider
        model = request.model or self.config.default_model_for(provider)
        if model not in self.config.allowed_models_for(provider):
            raise AIValidationError(
                f"Model '{model}' is not enabled for {provider}.",
                provider,
            )
        return self._build_client(self.config, provider=provider, model=model)

    def analyze(self, request: AIAnalysisRequest) -> AIAnalysisResponse:
        if not request.summary_data:
            raise AIValidationError("summary_data cannot be empty.", self.provider_name)

        client = self._client_for_request(request)
        provider_name = getattr(client, "provider_name", request.provider or self.config.provider)
        model_name = getattr(
            client,
            "model",
            request.model or self.config.default_model_for(provider_name),
        )
        precomputed_risk_level = calculate_precomputed_risk_level(request.summary_data)
        messages = [
            {"role": "system", "content": build_system_prompt(request.language)},
            {
                "role": "user",
                "content": build_user_prompt(
                    language=request.language,
                    dataset_type=request.dataset_type,
                    water_year=request.water_year,
                    summary_data=request.summary_data,
                    precomputed_risk_level=precomputed_risk_level,
                ),
            },
        ]

        try:
            raw_content = client.complete(messages)
        except AIConfigurationError:
            raise
        except AIRateLimitError:
            raise
        except AITimeoutError:
            raise
        except AIRemoteError:
            raise
        except Exception as error:
            LOGGER.exception(
                "Unexpected AI provider failure for provider=%s model=%s",
                provider_name,
                model_name,
            )
            raise AIProviderError(
                "AI provider request failed unexpectedly.",
                provider_name,
            ) from error

        try:
            parsed = _extract_json_object(raw_content)
        except Exception as error:
            raise AIProviderError(
                "LLM returned invalid JSON.",
                provider_name,
            ) from error

        normalized = _normalize_llm_payload(
            parsed,
            language=request.language,
            precomputed_risk_level=precomputed_risk_level,
        )
        try:
            llm_output = LLMAnalysisPayload.model_validate(normalized)
            if not llm_output.analysis.strip():
                raise ValueError("LLM response did not contain analysis text.")
        except (ValidationError, ValueError):
            LOGGER.warning(
                "LLM response did not match the analysis schema for provider=%s model=%s; retrying once.",
                provider_name,
                model_name,
            )
            repair_messages = _build_repair_messages(
                messages,
                raw_content,
                precomputed_risk_level,
            )
            try:
                repaired_content = client.complete(repair_messages)
                repaired = _extract_json_object(repaired_content)
                normalized = _normalize_llm_payload(
                    repaired,
                    language=request.language,
                    precomputed_risk_level=precomputed_risk_level,
                )
                llm_output = LLMAnalysisPayload.model_validate(normalized)
                if not llm_output.analysis.strip():
                    raise ValueError("LLM response did not contain analysis text.")
            except Exception as error:
                raise AIProviderError(
                    "LLM returned an incomplete analysis response.",
                    provider_name,
                ) from error

        parsed_risk_level = _normalize_risk_level(llm_output.risk_level)
        if parsed_risk_level and parsed_risk_level != precomputed_risk_level:
            LOGGER.info(
                "LLM risk level (%s) differs from precomputed risk level (%s); using backend value.",
                parsed_risk_level,
                precomputed_risk_level,
            )
        final_risk_level = precomputed_risk_level
        response_provider = cast(ProviderName, provider_name)

        return AIAnalysisResponse(
            provider=response_provider,
            model=model_name,
            analysis=llm_output.analysis.strip(),
            risk_level=final_risk_level,
            precomputed_risk_level=precomputed_risk_level,
            key_findings=_ensure_string_list(llm_output.key_findings),
            recommendations=_ensure_string_list(llm_output.recommendations),
            uncertainty_note=llm_output.uncertainty_note.strip(),
        )


@lru_cache(maxsize=1)
def get_ai_service() -> AIAnalysisService:
    return AIAnalysisService()


def get_ai_options(config: AIConfig | None = None) -> dict[str, Any]:
    config = config or AIConfig.from_env()
    labels = {
        "openrouter": "OpenRouter",
        "groq": "Groq",
        "gemini": "Gemini",
    }
    providers = []
    for provider in ("openrouter", "gemini", "groq"):
        models = []
        for model in config.allowed_models_for(provider):
            is_free = (
                provider in {"gemini", "groq"}
                or model == "openrouter/free"
                or model.endswith(":free")
            )
            models.append(
                {
                    "id": model,
                    "label": model,
                    "free": is_free,
                }
            )
        default_model = config.default_model_for(provider)
        if provider == "openrouter":
            default_is_free = (
                default_model == "openrouter/free"
                or default_model.endswith(":free")
            )
            if not default_is_free:
                free_model = next((model["id"] for model in models if model["free"]), None)
                default_model = free_model or default_model
        providers.append(
            {
                "id": provider,
                "label": labels[provider],
                "enabled": config.has_api_key_for(provider),
                "default_model": default_model,
                "models": models,
            }
        )
    return {
        "status": "success",
        "default_provider": config.provider,
        "providers": providers,
    }
