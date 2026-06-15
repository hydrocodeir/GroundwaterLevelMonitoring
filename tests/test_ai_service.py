from __future__ import annotations

import asyncio
import json
import unittest
from io import BytesIO
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from app.main import ai_analyze
from app.services.ai.config import AIConfig
from app.services.ai.errors import AIValidationError
from app.services.ai.http_client import post_chat_completion
from app.services.ai.gemini_client import GeminiClient
from app.services.ai.schemas import AIAnalysisRequest, AIAnalysisResponse
from app.services.ai.service import (
    AIAnalysisService,
    calculate_precomputed_risk_level,
    get_ai_options,
)


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

    def test_service_builds_selected_provider_and_model(self) -> None:
        client = FakeClient(
            {
                "analysis": "Selected Groq model response.",
                "risk_level": "high",
                "key_findings": [],
                "recommendations": [],
                "uncertainty_note": "Summary data only.",
            }
        )
        client.provider_name = "groq"
        client.model = "openai/gpt-oss-20b"
        config = AIConfig(
            provider="openrouter",
            groq_api_key="groq-key",
            groq_model="llama-3.1-8b-instant",
            groq_base_url="https://api.groq.com/openai/v1",
            openrouter_api_key="openrouter-key",
            openrouter_model="openrouter/auto",
            openrouter_base_url="https://openrouter.ai/api/v1",
            openrouter_site_url="http://localhost:3000",
            openrouter_app_name="Groundwater Dashboard AI",
        )
        request = self.build_request(language="en").model_copy(
            update={"provider": "groq", "model": "openai/gpt-oss-20b"}
        )

        with patch.object(AIAnalysisService, "_build_client", return_value=client) as builder:
            result = AIAnalysisService(config=config).analyze(request)

        builder.assert_called_once_with(
            config,
            provider="groq",
            model="openai/gpt-oss-20b",
        )
        self.assertEqual(result.provider, "groq")
        self.assertEqual(result.model, "openai/gpt-oss-20b")

    def test_service_builds_selected_gemini_model(self) -> None:
        client = FakeClient(
            {
                "analysis": "Gemini response.",
                "risk_level": "high",
                "key_findings": [],
                "recommendations": [],
                "uncertainty_note": "Summary data only.",
            }
        )
        client.provider_name = "gemini"
        client.model = "gemini-3.5-flash"
        config = AIConfig(
            provider="openrouter",
            groq_api_key="",
            groq_model="llama-3.1-8b-instant",
            groq_base_url="https://api.groq.com/openai/v1",
            openrouter_api_key="openrouter-key",
            openrouter_model="openrouter/auto",
            openrouter_base_url="https://openrouter.ai/api/v1",
            openrouter_site_url="http://localhost:3000",
            openrouter_app_name="Groundwater Dashboard AI",
            gemini_api_key="gemini-key",
        )
        request = self.build_request(language="en").model_copy(
            update={"provider": "gemini", "model": "gemini-3.5-flash"}
        )

        with patch.object(AIAnalysisService, "_build_client", return_value=client) as builder:
            result = AIAnalysisService(config=config).analyze(request)

        builder.assert_called_once_with(
            config,
            provider="gemini",
            model="gemini-3.5-flash",
        )
        self.assertEqual(result.provider, "gemini")
        self.assertEqual(result.model, "gemini-3.5-flash")

    def test_gemini_client_uses_native_json_generation_contract(self) -> None:
        client = GeminiClient(
            api_key="gemini-key",
            model="gemini-3.5-flash",
        )
        with patch(
            "app.services.ai.gemini_client.post_gemini_generation",
            return_value='{"analysis":"ok"}',
        ) as complete:
            result = client.complete(
                [
                    {"role": "system", "content": "System instructions"},
                    {"role": "user", "content": "Analyze data"},
                    {"role": "assistant", "content": "Previous response"},
                    {"role": "user", "content": "Repair it"},
                ]
            )

        self.assertEqual(result, '{"analysis":"ok"}')
        call = complete.call_args.kwargs
        self.assertIn(
            "/models/gemini-3.5-flash:generateContent",
            call["url"],
        )
        self.assertEqual(
            call["payload"]["generationConfig"]["responseMimeType"],
            "application/json",
        )
        self.assertEqual(call["payload"]["contents"][1]["role"], "model")
        self.assertEqual(
            call["payload"]["systemInstruction"]["parts"][0]["text"],
            "System instructions",
        )

    def test_service_rejects_model_outside_server_allowlist(self) -> None:
        request = self.build_request().model_copy(
            update={"provider": "openrouter", "model": "paid/model"}
        )

        with self.assertRaises(AIValidationError):
            AIAnalysisService(
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
                )
            ).analyze(request)

    def test_ai_options_only_exposes_key_availability_and_allowed_models(self) -> None:
        options = get_ai_options(
            AIConfig(
                provider="openrouter",
                groq_api_key="groq-secret",
                groq_model="llama-3.1-8b-instant",
                groq_base_url="https://api.groq.com/openai/v1",
                openrouter_api_key="",
                openrouter_model="openrouter/auto",
                openrouter_base_url="https://openrouter.ai/api/v1",
                openrouter_site_url="http://localhost:3000",
                openrouter_app_name="Groundwater Dashboard AI",
                gemini_api_key="gemini-secret",
            )
        )

        providers = {provider["id"]: provider for provider in options["providers"]}
        self.assertFalse(providers["openrouter"]["enabled"])
        self.assertEqual(providers["openrouter"]["default_model"], "openrouter/free")
        self.assertTrue(providers["gemini"]["enabled"])
        self.assertEqual(providers["gemini"]["default_model"], "gemini-3.5-flash")
        self.assertTrue(providers["gemini"]["models"][0]["free"])
        self.assertTrue(providers["groq"]["enabled"])
        self.assertNotIn("groq-secret", json.dumps(options))
        self.assertNotIn("gemini-secret", json.dumps(options))
        self.assertTrue(providers["groq"]["models"])

    def test_generic_provider_forbidden_error_gets_actionable_message(self) -> None:
        from urllib.error import HTTPError

        error = HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=BytesIO(b'{"error":{"message":"Forbidden"}}'),
        )
        with patch(
            "app.services.ai.http_client.urlrequest.urlopen",
            side_effect=error,
        ):
            with self.assertRaisesRegex(
                Exception,
                "account or network location is not permitted",
            ):
                post_chat_completion(
                    provider="groq",
                    url="https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": "Bearer test"},
                    payload={"model": "llama-3.1-8b-instant", "messages": []},
                    timeout_seconds=5,
                )

    def test_gemini_html_forbidden_error_gets_actionable_message(self) -> None:
        from urllib.error import HTTPError

        error = HTTPError(
            url="https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=BytesIO(b"<html><title>Error 403 (Forbidden)</title></html>"),
        )
        with patch(
            "app.services.ai.http_client.urlrequest.urlopen",
            side_effect=error,
        ):
            with self.assertRaisesRegex(
                Exception,
                "project or network location is not permitted",
            ):
                from app.services.ai.http_client import post_gemini_generation

                post_gemini_generation(
                    url=error.url,
                    api_key="test",
                    payload={"contents": []},
                    timeout_seconds=5,
                )

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
            "provider": "openrouter",
            "model": "openrouter/auto",
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
        body = json.dumps(payload).encode("utf-8")

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/ai/analyze",
                "headers": [],
            },
            receive,
        )
        run_directly = AsyncMock(side_effect=lambda function, argument: function(argument))
        with (
            patch("app.main.get_ai_service", return_value=fake_service),
            patch("app.main.run_in_threadpool", run_directly),
        ):
            response = asyncio.run(ai_analyze(request))

        self.assertEqual(response.status_code, 200)
        response_body = json.loads(response.body)
        self.assertEqual(response_body["status"], "success")
        self.assertEqual(response_body["provider"], "openrouter")
        self.assertEqual(response_body["model"], "openrouter/auto")
        self.assertEqual(response_body["risk_level"], "high")
        self.assertEqual(response_body["precomputed_risk_level"], "high")
        self.assertIn("analysis", response_body)


if __name__ == "__main__":
    unittest.main()
