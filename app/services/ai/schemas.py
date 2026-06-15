from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RiskLevel = Literal["low", "moderate", "high", "critical"]
ProviderName = Literal["gemini", "groq", "openrouter"]
LanguageCode = Literal["fa", "en"]


class AIAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: LanguageCode = "fa"
    provider: ProviderName | None = None
    model: str | None = Field(default=None, min_length=1, max_length=128)
    dataset_type: str = Field(default="groundwater_dashboard", min_length=1, max_length=64)
    water_year: str | None = Field(default=None, max_length=64)
    summary_data: dict[str, Any]

    @field_validator("summary_data")
    @classmethod
    def validate_summary_data(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("summary_data cannot be empty")
        return value

    @field_validator("water_year")
    @classmethod
    def normalize_water_year(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        return cleaned or None

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        return cleaned or None


class AIAnalysisResponse(BaseModel):
    status: Literal["success"] = "success"
    provider: ProviderName
    model: str
    analysis: str
    risk_level: RiskLevel
    precomputed_risk_level: RiskLevel
    key_findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    uncertainty_note: str


class LLMAnalysisPayload(BaseModel):
    analysis: str
    risk_level: str = ""
    key_findings: list[str] | str = Field(default_factory=list)
    recommendations: list[str] | str = Field(default_factory=list)
    uncertainty_note: str = ""
