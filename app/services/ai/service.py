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
        self.client = client or self._build_client(self.config)

    @staticmethod
    def _build_client(config: AIConfig) -> Any:
        provider = config.provider
        if provider not in SUPPORTED_PROVIDERS:
            raise AIConfigurationError(
                f"Invalid AI_PROVIDER '{provider}'. Supported providers are groq and openrouter.",
                provider,
            )
        if provider == "groq":
            if not config.groq_api_key:
                raise AIConfigurationError("GROQ_API_KEY is missing.", provider)
            return GroqClient(
                api_key=config.groq_api_key,
                model=config.groq_model,
                base_url=config.groq_base_url,
                timeout_seconds=config.timeout_seconds,
            )
        if not config.openrouter_api_key:
            raise AIConfigurationError("OPENROUTER_API_KEY is missing.", provider)
        return OpenRouterClient(
            api_key=config.openrouter_api_key,
            model=config.openrouter_model,
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
        return getattr(self.client, "model", "")

    def analyze(self, request: AIAnalysisRequest) -> AIAnalysisResponse:
        if not request.summary_data:
            raise AIValidationError("summary_data cannot be empty.", self.provider_name)

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
            raw_content = self.client.complete(messages)
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
                self.provider_name,
                self.model_name,
            )
            raise AIProviderError(
                "AI provider request failed unexpectedly.",
                self.provider_name,
            ) from error

        try:
            parsed = _extract_json_object(raw_content)
        except Exception as error:
            raise AIProviderError(
                "LLM returned invalid JSON.",
                self.provider_name,
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
                self.provider_name,
                self.model_name,
            )
            repair_messages = _build_repair_messages(
                messages,
                raw_content,
                precomputed_risk_level,
            )
            try:
                repaired_content = self.client.complete(repair_messages)
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
                    self.provider_name,
                ) from error

        parsed_risk_level = _normalize_risk_level(llm_output.risk_level)
        if parsed_risk_level and parsed_risk_level != precomputed_risk_level:
            LOGGER.info(
                "LLM risk level (%s) differs from precomputed risk level (%s); using backend value.",
                parsed_risk_level,
                precomputed_risk_level,
            )
        final_risk_level = precomputed_risk_level
        provider_name = cast(ProviderName, self.provider_name)

        return AIAnalysisResponse(
            provider=provider_name,
            model=self.model_name,
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
