from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.settings import load_environment
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.data_service import get_data_service
from app.services.ai import (
    AIAnalysisRequest,
    AIChatRequest,
    AIConfigurationError,
    AIForbiddenError,
    AIProviderError,
    AIRateLimitError,
    AIRemoteError,
    AITimeoutError,
    AIValidationError,
    build_aquifer_chat_context,
    get_ai_options,
    get_ai_service,
)


ROOT = Path(__file__).resolve().parents[1]

load_environment()

app = FastAPI(title="داشبورد پایش آب زیرزمینی")
app.mount("/assets", StaticFiles(directory=ROOT / "frontend" / "assets"), name="assets")
templates = Jinja2Templates(directory=ROOT / "frontend" / "templates")
templates.env.globals["asset_version"] = max(
    (ROOT / "frontend" / "assets" / "css" / "app.css").stat().st_mtime_ns,
    (ROOT / "frontend" / "assets" / "js" / "app.js").stat().st_mtime_ns,
    (ROOT / "frontend" / "assets" / "js" / "comparison.js").stat().st_mtime_ns,
)
AI_REQUEST_MAX_BYTES = 64_000


def _ai_error_response(message: str, provider: str | None = None, status_code: int = 500) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "message": message,
            "provider": provider,
        },
    )


@app.on_event("startup")
def warm_data_cache() -> None:
    get_data_service()


@app.middleware("http")
async def limit_ai_request_size(request: Request, call_next):
    if request.url.path in {"/api/ai/analyze", "/api/ai/chat"} and request.method.upper() == "POST":
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit():
            if int(content_length) > AI_REQUEST_MAX_BYTES:
                return _ai_error_response(
                    "Request body is too large.",
                    provider=None,
                    status_code=413,
                )
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    service = get_data_service()
    navigation = service.navigation()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "navigation": navigation,
            "group_count": len(service.groups),
        },
    )


@app.get("/comparison", response_class=HTMLResponse)
def comparison(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="comparison.html",
        context={},
    )


@app.get("/partials/aquifers", response_class=HTMLResponse)
def aquifer_options(
    request: Request,
    mahdoude: str = Query(...),
) -> HTMLResponse:
    aquifers = get_data_service().aquifers_for_mahdoude(mahdoude)
    return templates.TemplateResponse(
        request=request,
        name="partials/aquifer_options.html",
        context={"aquifers": aquifers},
    )


@app.get("/api/navigation-map")
def navigation_map() -> dict:
    return get_data_service().spatial_navigation()


@app.get("/partials/dashboard", response_class=HTMLResponse)
def dashboard_partial(
    request: Request,
    aquifer_id: str = Query(...),
) -> HTMLResponse:
    service = get_data_service()
    try:
        group = service.groups[aquifer_id]
    except KeyError as error:
        raise HTTPException(status_code=404, detail="آبخوان پیدا نشد") from error
    return templates.TemplateResponse(
        request=request,
        name="partials/dashboard.html",
        context={"group": group},
    )


def _dashboard_payload(
    aquifer_id: str,
    start_year: int | None = None,
    start_month: int | None = None,
    end_year: int | None = None,
    end_month: int | None = None,
    comparison_start_year: int | None = None,
    comparison_start_month: int | None = None,
    comparison_end_year: int | None = None,
    comparison_end_month: int | None = None,
    comparison_enabled: bool = False,
    continuous_only: bool = True,
    manual_selection: bool = False,
    selected_well_ids: list[str] | None = None,
    storage_coefficient: float | None = None,
    surface_interpolation_methods: list[str] | None = None,
    surface_interpolation_method: str = "idw",
) -> dict:
    return get_data_service().dashboard(
        aquifer_id,
        start_year=start_year,
        start_month=start_month,
        end_year=end_year,
        end_month=end_month,
        comparison_start_year=comparison_start_year,
        comparison_start_month=comparison_start_month,
        comparison_end_year=comparison_end_year,
        comparison_end_month=comparison_end_month,
        comparison_enabled=comparison_enabled,
        continuous_only=continuous_only,
        manual_selection=manual_selection,
        selected_well_ids=selected_well_ids,
        storage_coefficient=storage_coefficient,
        surface_interpolation_methods=surface_interpolation_methods,
        surface_interpolation_method=surface_interpolation_method,
    )


@app.get("/api/aquifers/{aquifer_id}")
def aquifer_data(
    aquifer_id: str,
    start_year: int | None = Query(default=None),
    start_month: int | None = Query(default=None),
    end_year: int | None = Query(default=None),
    end_month: int | None = Query(default=None),
    comparison_start_year: int | None = Query(default=None),
    comparison_start_month: int | None = Query(default=None),
    comparison_end_year: int | None = Query(default=None),
    comparison_end_month: int | None = Query(default=None),
    comparison_enabled: bool = Query(default=False),
    continuous_only: bool = Query(default=True),
    manual_selection: bool = Query(default=False),
    selected_well_ids: list[str] | None = Query(default=None),
    storage_coefficient: float = Query(..., gt=0),
    surface_interpolation_methods: list[str] | None = Query(default=None),
    surface_interpolation_method: str = Query(default="idw"),
) -> dict:
    try:
        return _dashboard_payload(
            aquifer_id,
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
            comparison_start_year=comparison_start_year,
            comparison_start_month=comparison_start_month,
            comparison_end_year=comparison_end_year,
            comparison_end_month=comparison_end_month,
            comparison_enabled=comparison_enabled,
            continuous_only=continuous_only,
            manual_selection=manual_selection,
            selected_well_ids=selected_well_ids,
            storage_coefficient=storage_coefficient,
            surface_interpolation_methods=surface_interpolation_methods,
            surface_interpolation_method=surface_interpolation_method,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="آبخوان پیدا نشد") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/reports/aquifer/{aquifer_id}", response_class=HTMLResponse)
def aquifer_report(
    request: Request,
    aquifer_id: str,
    start_year: int | None = Query(default=None),
    start_month: int | None = Query(default=None),
    end_year: int | None = Query(default=None),
    end_month: int | None = Query(default=None),
    comparison_start_year: int | None = Query(default=None),
    comparison_start_month: int | None = Query(default=None),
    comparison_end_year: int | None = Query(default=None),
    comparison_end_month: int | None = Query(default=None),
    comparison_enabled: bool = Query(default=False),
    continuous_only: bool = Query(default=True),
    manual_selection: bool = Query(default=False),
    selected_well_ids: list[str] | None = Query(default=None),
    storage_coefficient: float = Query(..., gt=0),
    surface_interpolation_methods: list[str] | None = Query(default=None),
    surface_interpolation_method: str = Query(default="idw"),
) -> HTMLResponse:
    try:
        payload = _dashboard_payload(
            aquifer_id,
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
            comparison_start_year=comparison_start_year,
            comparison_start_month=comparison_start_month,
            comparison_end_year=comparison_end_year,
            comparison_end_month=comparison_end_month,
            comparison_enabled=comparison_enabled,
            continuous_only=continuous_only,
            manual_selection=manual_selection,
            selected_well_ids=selected_well_ids,
            storage_coefficient=storage_coefficient,
            surface_interpolation_methods=surface_interpolation_methods,
            surface_interpolation_method=surface_interpolation_method,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="آبخوان پیدا نشد") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={"data": payload},
    )


@app.get("/api/comparison")
def comparison_data(
    start_year: int | None = Query(default=None),
    start_month: int | None = Query(default=None),
    end_year: int | None = Query(default=None),
    end_month: int | None = Query(default=None),
) -> dict:
    try:
        return get_data_service().comparison(
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/ai/analyze")
async def ai_analyze(request: Request) -> JSONResponse:
    body = await request.body()
    if len(body) > AI_REQUEST_MAX_BYTES:
        return _ai_error_response(
            "Request body is too large.",
            status_code=413,
        )
    try:
        payload = AIAnalysisRequest.model_validate_json(body)
    except ValidationError:
        return _ai_error_response(
            "Invalid request body.",
            provider=None,
            status_code=400,
        )

    service = get_ai_service()
    try:
        result = await run_in_threadpool(service.analyze, payload)
    except AIConfigurationError as error:
        return _ai_error_response(error.message, error.provider, 500)
    except AIForbiddenError as error:
        return _ai_error_response(error.message, error.provider, 403)
    except (AIProviderError, AIRateLimitError, AIRemoteError, AITimeoutError) as error:
        return _ai_error_response(error.message, error.provider, 502)
    except AIValidationError as error:
        return _ai_error_response(error.message, error.provider, 400)
    except Exception:
        return _ai_error_response(
            "AI analysis failed unexpectedly.",
            provider=getattr(service, "provider_name", None),
            status_code=500,
        )

    return JSONResponse(content=result.model_dump())


@app.post("/api/ai/chat")
async def ai_chat(request: Request) -> JSONResponse:
    body = await request.body()
    if len(body) > AI_REQUEST_MAX_BYTES:
        return _ai_error_response(
            "Request body is too large.",
            status_code=413,
        )
    try:
        payload = AIChatRequest.model_validate_json(body)
    except ValidationError:
        return _ai_error_response(
            "Invalid chat request body.",
            provider=None,
            status_code=400,
        )

    filters = payload.filters
    try:
        dashboard = await run_in_threadpool(
            get_data_service().dashboard,
            payload.aquifer_id,
            start_year=filters.start_year,
            start_month=filters.start_month,
            end_year=filters.end_year,
            end_month=filters.end_month,
            continuous_only=filters.continuous_only,
            manual_selection=filters.manual_selection,
            selected_well_ids=filters.selected_well_ids or None,
            storage_coefficient=filters.storage_coefficient,
            surface_interpolation_methods=filters.surface_interpolation_methods,
            surface_interpolation_method=filters.surface_interpolation_method,
        )
    except KeyError:
        return _ai_error_response(
            "Aquifer was not found.",
            provider=payload.provider,
            status_code=404,
        )
    except ValueError as error:
        return _ai_error_response(
            str(error),
            provider=payload.provider,
            status_code=400,
        )

    service = get_ai_service()
    context = build_aquifer_chat_context(dashboard)
    try:
        result = await run_in_threadpool(service.chat, payload, context)
    except AIConfigurationError as error:
        return _ai_error_response(error.message, error.provider, 500)
    except AIForbiddenError as error:
        return _ai_error_response(error.message, error.provider, 403)
    except (AIProviderError, AIRateLimitError, AIRemoteError, AITimeoutError) as error:
        return _ai_error_response(error.message, error.provider, 502)
    except AIValidationError as error:
        return _ai_error_response(error.message, error.provider, 400)
    except Exception:
        return _ai_error_response(
            "AI chat failed unexpectedly.",
            provider=getattr(service, "provider_name", None),
            status_code=500,
        )

    return JSONResponse(content=result.model_dump())


@app.get("/api/ai/options")
def ai_options() -> dict:
    return get_ai_options()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
