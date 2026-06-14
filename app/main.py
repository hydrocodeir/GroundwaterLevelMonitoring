from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.data_service import get_data_service


ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(title="داشبورد پایش آب زیرزمینی")
app.mount("/assets", StaticFiles(directory=ROOT / "frontend" / "assets"), name="assets")
templates = Jinja2Templates(directory=ROOT / "frontend" / "templates")
templates.env.globals["asset_version"] = max(
    (ROOT / "frontend" / "assets" / "css" / "app.css").stat().st_mtime_ns,
    (ROOT / "frontend" / "assets" / "js" / "app.js").stat().st_mtime_ns,
    (ROOT / "frontend" / "assets" / "js" / "comparison.js").stat().st_mtime_ns,
)


@app.on_event("startup")
def warm_data_cache() -> None:
    get_data_service()


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
