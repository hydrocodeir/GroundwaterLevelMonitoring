from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.ai.config import AIConfig
from app.services.ai.schemas import AIAnalysisRequest, AIAnalysisResponse
from app.services.ai.service import AIAnalysisService, calculate_precomputed_risk_level


class FakeClient:
    provider_name = "openrouter"
    model = "openrouter/auto"

    def __init__(
        self,
        response: dict[str, object] | list[dict[str, object]],
    ) -> None:
        self.responses = response if isinstance(response, list) else [response]
        self.messages = None
        self.calls = []

    def complete(self, messages):
        self.messages = messages
        self.calls.append(messages)
        response_index = min(len(self.calls) - 1, len(self.responses) - 1)
        return json.dumps(self.responses[response_index], ensure_ascii=False)


class AIServiceTests(unittest.TestCase):
    def build_service(self, client: FakeClient) -> AIAnalysisService:
        return AIAnalysisService(
            config=AIConfig(
                provider="openrouter",
                groq_api_key="",
                groq_model="llama-3.1-8b-instant",
                groq_base_url="https://api.groq.com/openai/v1",
                openrouter_api_key="test-key",
                openrouter_model="openrouter/auto",
                openrouter_base_url="https://openrouter.ai/api/v1",
                openrouter_site_url="http://localhost:3000",
                openrouter_app_name="Groundwater Dashboard AI",
            ),
            client=client,
        )

    def build_request(self, language: str = "fa") -> AIAnalysisRequest:
        return AIAnalysisRequest.model_validate(
            {
                "language": language,
                "dataset_type": "groundwater_dashboard",
                "water_year": "1402-1403",
                "summary_data": {
                    "groundwater_level_change_m": -1.8,
                    "precipitation_anomaly_percent": -24,
                    "ndvi_change": -0.12,
                    "aet_change_percent": -8,
                    "critical_wells_count": 12,
                    "total_wells_count": 45,
                },
            }
        )

    def test_precomputed_risk_level_uses_backend_rules(self) -> None:
        self.assertEqual(
            calculate_precomputed_risk_level(
                {
                    "groundwater_level_change_m": -1.8,
                    "precipitation_anomaly_percent": -24,
                    "ndvi_change": -0.12,
                    "aet_change_percent": -8,
                    "critical_wells_count": 12,
                    "total_wells_count": 45,
                }
            ),
            "high",
        )

    def test_service_parses_llm_json_and_preserves_provider_metadata(self) -> None:
        client = FakeClient(
            {
                "analysis": "تحلیل آزمایشی",
                "risk_level": "high",
                "key_findings": ["افت آب زیرزمینی ثبت شد."],
                "recommendations": ["کنترل برداشت را بررسی کنید."],
                "uncertainty_note": "داده‌ها برای نتیجه‌گیری قطعی محدود هستند.",
            }
        )
        service = self.build_service(client)
        request = self.build_request()
        result = service.analyze(request)

        self.assertEqual(result.provider, "openrouter")
        self.assertEqual(result.model, "openrouter/auto")
        self.assertEqual(result.precomputed_risk_level, "high")
        self.assertEqual(result.risk_level, "high")
        self.assertEqual(client.messages[0]["role"], "system")
        self.assertIsInstance(result, AIAnalysisResponse)

    def test_service_supplies_safe_defaults_for_omitted_secondary_fields(self) -> None:
        client = FakeClient(
            {
                "analysis": "افت آب زیرزمینی در دوره انتخابی مشاهده می‌شود.",
                "key_findings": "روند تراز آب زیرزمینی کاهشی است.",
                "recommendations": ["برداشت چاه‌ها پایش شود."],
            }
        )

        result = self.build_service(client).analyze(self.build_request())

        self.assertEqual(result.risk_level, "high")
        self.assertEqual(result.key_findings, ["روند تراز آب زیرزمینی کاهشی است."])
        self.assertTrue(result.uncertainty_note)
        self.assertEqual(len(client.calls), 1)

    def test_service_repairs_response_when_analysis_text_is_missing(self) -> None:
        client = FakeClient(
            [
                {
                    "risk_level": "high",
                    "key_findings": ["افت تراز مشاهده شد."],
                },
                {
                    "analysis": "افت تراز آب زیرزمینی نیازمند مدیریت برداشت است.",
                    "risk_level": "high",
                    "key_findings": ["افت تراز مشاهده شد."],
                    "recommendations": ["برداشت کنترل شود."],
                    "uncertainty_note": "تحلیل بر داده‌های خلاصه متکی است.",
                },
            ]
        )

        result = self.build_service(client).analyze(self.build_request())

        self.assertIn("مدیریت برداشت", result.analysis)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1][-1]["role"], "user")

    def test_ai_endpoint_returns_structured_response(self) -> None:
        client = FakeClient(
            {
                "analysis": "Groundwater is declining.",
                "risk_level": "moderate",
                "key_findings": ["Decline is visible."],
                "recommendations": ["Investigate pumping pressure."],
                "uncertainty_note": "Summary-only analysis.",
            }
        )
        fake_service = self.build_service(client)
        payload = {
            "language": "en",
            "dataset_type": "groundwater_dashboard",
            "water_year": "1402-1403",
            "summary_data": {
                "groundwater_level_change_m": -1.8,
                "precipitation_anomaly_percent": -24,
                "ndvi_change": -0.12,
                "aet_change_percent": -8,
                "critical_wells_count": 12,
                "total_wells_count": 45,
            },
        }
        with patch("app.main.get_ai_service", return_value=fake_service):
            response = TestClient(app).post("/api/ai/analyze", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["provider"], "openrouter")
        self.assertEqual(body["model"], "openrouter/auto")
        self.assertEqual(body["risk_level"], "high")
        self.assertEqual(body["precomputed_risk_level"], "high")
        self.assertIn("analysis", body)


if __name__ == "__main__":
    unittest.main()
