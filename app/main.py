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
    AIConfigurationError,
    AIForbiddenError,
    AIProviderError,
    AIRateLimitError,
    AIRemoteError,
    AITimeoutError,
    AIValidationError,
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
    if request.url.path == "/api/ai/analyze" and request.method.upper() == "POST":
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
) -> dict:
    try:
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
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="آبخوان پیدا نشد") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


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


@app.get("/api/ai/options")
def ai_options() -> dict:
    return get_ai_options()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
