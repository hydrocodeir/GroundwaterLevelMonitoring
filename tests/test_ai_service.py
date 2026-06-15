from __future__ import annotations

import asyncio
import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from app.main import ai_analyze, ai_chat
from app.services.ai.config import AIConfig
from app.services.ai.errors import AIForbiddenError, AIProviderError, AIValidationError
from app.services.ai.groq_client import GroqClient
from app.services.ai.http_client import post_chat_completion
from app.services.ai.gemini_client import GeminiClient
from app.services.ai.openrouter_client import OpenRouterClient
from app.services.ai.schemas import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    AIChatRequest,
    AIChatResponse,
)
from app.services.ai.service import (
    AIAnalysisService,
    build_aquifer_chat_context,
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

    def test_chat_uses_history_and_returns_provider_metadata(self) -> None:
        client = FakeClient({"answer": "پیزومتر نمونه روند کاهشی دارد."})
        service = self.build_service(client)
        request = AIChatRequest.model_validate(
            {
                "aquifer_id": "aquifer-id",
                "provider": "openrouter",
                "model": "openrouter/auto",
                "question": "کدام پیزومتر افت دارد؟",
                "history": [
                    {"role": "user", "content": "درباره چاه‌ها توضیح بده."},
                    {"role": "assistant", "content": "نام چاه را مشخص کنید."},
                ],
            }
        )

        result = service.chat(
            request,
            {
                "aquifer": {"name": "آبخوان نمونه"},
                "piezometers": [{"name": "پیزومتر نمونه"}],
            },
        )

        self.assertIsInstance(result, AIChatResponse)
        self.assertEqual(result.provider, "openrouter")
        self.assertIn("روند کاهشی", result.answer)
        self.assertEqual(client.messages[1]["role"], "user")
        self.assertIn("آبخوان نمونه", client.messages[-1]["content"])
        self.assertIn("کدام پیزومتر", client.messages[-1]["content"])

    def test_chat_repairs_response_without_answer_field(self) -> None:
        client = FakeClient(
            [
                {"message": "پاسخ با کلید اشتباه"},
                {"answer": "پاسخ اصلاح‌شده"},
            ]
        )
        service = self.build_service(client)
        request = AIChatRequest(
            aquifer_id="aquifer-id",
            question="وضعیت چیست؟",
        )

        result = service.chat(request, {"aquifer": {"name": "نمونه"}})

        self.assertEqual(result.answer, "پاسخ اصلاح‌شده")
        self.assertEqual(len(client.calls), 2)

    def test_chat_context_keeps_full_series_and_station_data(self) -> None:
        context = build_aquifer_chat_context(
            {
                "id": "a1",
                "aquifer": "آبخوان نمونه",
                "mahdoude": "محدوده نمونه",
                "stats": {"total_wells": 1},
                "filters": {
                    "start_year": 1402,
                    "start_month": 7,
                    "end_year": 1403,
                    "end_month": 6,
                    "start_water_year": 1402,
                    "end_water_year": 1402,
                },
                "boundaries": {"aquifer": {"type": "Feature"}},
                "thiessen_polygons": [{"id": "poly-1"}],
                "hydrographs": {
                    "thiessen": [["1402-07-01", 10.0]],
                    "thiessen_trend": {"direction": "decline", "slope": -0.2},
                },
                "annual_decline": [{"water_year": "1402-1403"}],
                "annual_changes": [{"water_year": "1402-1403"}],
                "time_series_analysis": {
                    "period": {"start_water_year": "1402-1403"},
                    "trend_statistics": {"groundwater": {"slope": -0.2}},
                    "correlations": {"precipitation": {"r": 0.5}},
                    "lag_analysis": {"precipitation": {"lag": 1}},
                    "stress_indicators": {"declining_year_count": 1},
                    "llm_input": {"trend_statistics": {"groundwater": {"slope": -0.2}}},
                    "agricultural_pressure": {"irrigated_area_trend": {"direction": "rise"}},
                    "driver_classification": {"label": "Mixed Influence"},
                },
                "precipitation": {
                    "series": [["1402-07-01", 12.0]],
                    "method": "inside",
                    "stations": [
                        {
                            "id": "st1",
                            "name": "بارانسنج 1",
                            "series": [["1402-07-01", 11.5]],
                        }
                    ],
                },
                "ndvi": {"metrics": {"median": []}, "default_metric": "median"},
                "aet": {"series": [["1402-07-01", 50.0]], "source": "WaPOR"},
                "wells": [
                    {
                        "id": "w1",
                        "name": "پیزومتر نمونه",
                        "included": True,
                        "status": "included",
                        "elevation": 1000,
                        "series": [["1402-07-01", 20.0], ["1402-08-01", 19.5]],
                        "trend": {"direction": "decline", "slope": -0.5},
                        "annual_decline": [],
                    }
                ],
            }
        )

        serialized = json.dumps(context, ensure_ascii=False)
        self.assertIn("پیزومتر نمونه", serialized)
        self.assertIn('"series"', serialized)
        self.assertEqual(context["hydrographs"]["thiessen"][0][1], 10.0)
        self.assertEqual(context["precipitation"]["stations"][0]["series"][0][1], 11.5)
        self.assertEqual(context["piezometers"][0]["series"][1][1], 19.5)

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

    def test_groq_403_with_non_forbidden_body_gets_forbidden_error(self) -> None:
        from urllib.error import HTTPError

        error = HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=BytesIO(b'{"error":{"message":"Access denied"}}'),
        )
        with patch(
            "app.services.ai.http_client.urlrequest.urlopen",
            side_effect=error,
        ):
            with self.assertRaises(AIForbiddenError) as ctx:
                post_chat_completion(
                    provider="groq",
                    url="https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": "Bearer test"},
                    payload={"model": "llama-3.1-8b-instant", "messages": []},
                    timeout_seconds=5,
                )
        self.assertIn("groq rejected access with HTTP 403", str(ctx.exception))
        self.assertIn("Access denied", str(ctx.exception))

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

    def test_groq_client_uses_openai_sdk_payload_without_response_format(self) -> None:
        captured: dict[str, object] = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='{"analysis":"ok"}'
                            )
                        )
                    ]
                )

        class FakeOpenAIClient:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs
                self.chat = SimpleNamespace(completions=FakeCompletions())

        fake_module = SimpleNamespace(OpenAI=FakeOpenAIClient)

        with patch("app.services.ai.groq_client.importlib.import_module", return_value=fake_module):
            client = GroqClient(
                api_key="test-key",
                model="llama-3.1-8b-instant",
                base_url="https://api.groq.com/openai/v1",
                timeout_seconds=15,
            )
            content = client.complete([{"role": "user", "content": "Hello"}])

        self.assertEqual(content, '{"analysis":"ok"}')
        self.assertEqual(captured["client_kwargs"]["api_key"], "test-key")
        self.assertEqual(captured["client_kwargs"]["base_url"], "https://api.groq.com/openai/v1")
        self.assertEqual(captured["client_kwargs"]["timeout"], 15)
        self.assertEqual(captured["client_kwargs"]["max_retries"], 0)
        self.assertEqual(captured["model"], "llama-3.1-8b-instant")
        self.assertEqual(captured["temperature"], 0.2)
        self.assertNotIn("response_format", captured)

    def test_openrouter_client_uses_json_mode_when_supported(self) -> None:
        with patch(
            "app.services.ai.openrouter_client.post_chat_completion",
            return_value='{"answer":"ok"}',
        ) as complete:
            client = OpenRouterClient(
                api_key="test-key",
                model="google/gemma-4-31b-it:free",
            )
            content = client.complete([{"role": "user", "content": "Hello"}])

        self.assertEqual(content, '{"answer":"ok"}')
        payload = complete.call_args.kwargs["payload"]
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_openrouter_client_retries_without_json_mode_when_model_rejects_it(self) -> None:
        with patch(
            "app.services.ai.openrouter_client.post_chat_completion",
            side_effect=[
                AIProviderError(
                    "This model does not support response_format json_object.",
                    "openrouter",
                ),
                '{"answer":"ok"}',
            ],
        ) as complete:
            client = OpenRouterClient(
                api_key="test-key",
                model="openai/gpt-oss-20b:free",
            )
            content = client.complete([{"role": "user", "content": "Hello"}])

        self.assertEqual(content, '{"answer":"ok"}')
        first_payload = complete.call_args_list[0].kwargs["payload"]
        second_payload = complete.call_args_list[1].kwargs["payload"]
        self.assertEqual(first_payload["response_format"], {"type": "json_object"})
        self.assertNotIn("response_format", second_payload)

    def test_openrouter_generic_provider_error_gets_actionable_message(self) -> None:
        from urllib.error import HTTPError

        error = HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"error":{"message":"Provider returned error"}}'),
        )
        with patch(
            "app.services.ai.http_client.urlrequest.urlopen",
            side_effect=error,
        ):
            with self.assertRaisesRegex(
                Exception,
                "may not support response_format=json_object",
            ):
                post_chat_completion(
                    provider="openrouter",
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": "Bearer test"},
                    payload={"model": "openai/gpt-oss-20b:free", "messages": []},
                    timeout_seconds=5,
                )

    def test_analysis_falls_back_from_forbidden_groq_to_next_provider(self) -> None:
        service = AIAnalysisService(
            config=AIConfig(
                provider="groq",
                groq_api_key="groq-key",
                groq_model="llama-3.1-8b-instant",
                groq_base_url="https://api.groq.com/openai/v1",
                openrouter_api_key="openrouter-key",
                openrouter_model="openrouter/auto",
                openrouter_base_url="https://openrouter.ai/api/v1",
                openrouter_site_url="http://localhost:3000",
                openrouter_app_name="Groundwater Dashboard AI",
                gemini_api_key="gemini-key",
            )
        )
        request = self.build_request().model_copy(
            update={"provider": "groq", "model": "llama-3.1-8b-instant"}
        )

        def fake_analyze_once(current_request):
            if current_request.provider == "groq":
                raise AIForbiddenError("groq rejected access with HTTP 403.", "groq")
            return AIAnalysisResponse(
                provider=current_request.provider or "openrouter",
                model=current_request.model or "openrouter/auto",
                analysis="fallback works",
                risk_level="high",
                precomputed_risk_level="high",
                key_findings=["fallback"],
                recommendations=["fallback"],
                uncertainty_note="ok",
            )

        with patch.object(service, "_analyze_once", side_effect=fake_analyze_once):
            result = service.analyze(request)

        self.assertEqual(result.provider, "openrouter")
        self.assertEqual(result.model, "openrouter/auto")
        self.assertEqual(result.analysis, "fallback works")

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

    def test_ai_chat_endpoint_builds_server_side_aquifer_context(self) -> None:
        class FakeDataService:
            def dashboard(self, aquifer_id, **filters):
                self.aquifer_id = aquifer_id
                self.filters = filters
                return {
                    "id": aquifer_id,
                    "aquifer": "آبخوان نمونه",
                    "mahdoude": "محدوده نمونه",
                    "stats": {"total_wells": 0},
                    "filters": {
                        "start_year": 1402,
                        "start_month": 7,
                        "end_year": 1403,
                        "end_month": 6,
                        "start_water_year": 1402,
                        "end_water_year": 1402,
                    },
                    "hydrographs": {},
                    "annual_decline": [],
                    "annual_changes": [],
                    "time_series_analysis": {},
                    "precipitation": {},
                    "ndvi": {},
                    "aet": {},
                    "wells": [],
                }

        class FakeChatService:
            provider_name = "openrouter"

            def chat(self, request, context):
                self.request = request
                self.context = context
                return AIChatResponse(
                    provider="openrouter",
                    model="openrouter/free",
                    answer="پاسخ آزمایشی",
                )

        payload = {
            "aquifer_id": "aquifer-id",
            "provider": "openrouter",
            "model": "openrouter/free",
            "question": "وضعیت آبخوان چیست؟",
            "history": [],
            "filters": {
                "start_year": 1402,
                "start_month": 7,
                "end_year": 1403,
                "end_month": 6,
            },
        }
        body = json.dumps(payload).encode("utf-8")

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/ai/chat",
                "headers": [],
            },
            receive,
        )
        data_service = FakeDataService()
        chat_service = FakeChatService()

        async def run_directly(function, *args, **kwargs):
            return function(*args, **kwargs)

        with (
            patch("app.main.get_data_service", return_value=data_service),
            patch("app.main.get_ai_service", return_value=chat_service),
            patch("app.main.run_in_threadpool", side_effect=run_directly),
        ):
            response = asyncio.run(ai_chat(request))

        self.assertEqual(response.status_code, 200)
        response_body = json.loads(response.body)
        self.assertEqual(response_body["answer"], "پاسخ آزمایشی")
        self.assertEqual(data_service.aquifer_id, "aquifer-id")
        self.assertEqual(chat_service.context["aquifer"]["name"], "آبخوان نمونه")


if __name__ == "__main__":
    unittest.main()
