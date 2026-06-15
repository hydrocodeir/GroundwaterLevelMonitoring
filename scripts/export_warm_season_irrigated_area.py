#!/usr/bin/env python3
"""Estimate probable irrigated crop area during Solar Hijri months 3-6."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import ee
import jdatetime


LANDSAT_COLLECTION_IDS = (
    "LANDSAT/LC08/C02/T1_L2",
    "LANDSAT/LC09/C02/T1_L2",
)
LANDSAT_8_START_YEAR = 1392
WARM_MONTHS = (3, 4, 5, 6)
GFSAD_LGRIP30_ASSET_ID = "projects/sat-io/open-datasets/GFSAD/LGRIP30"
GFSAD_IRRIGATED_CROPLAND_CLASS = 2
RUN_METADATA_VERSION = 1
CSV_FIELDS = [
    "MAHDOUDE",
    "AQUIFER",
    "JALALI_YEAR",
    "PERIOD_START",
    "PERIOD_END_EXCLUSIVE",
    "PROBABLE_IRRIGATED_AREA_HA",
    "ANALYSIS_MASK_AREA_HA",
    "VALID_OBSERVATION_AREA_HA",
    "PROBABLE_PERCENT_OF_ANALYSIS",
    "VALID_PERCENT_OF_ANALYSIS",
]


@dataclass(frozen=True)
class WarmSeason:
    jalali_year: int
    start: date
    end: date

    @property
    def label(self) -> str:
        return str(self.jalali_year)

    @property
    def period_start(self) -> str:
        return f"{self.jalali_year:04d}-03-01"

    @property
    def period_end_exclusive(self) -> str:
        return f"{self.jalali_year:04d}-07-01"


def latest_complete_warm_season_year(today: date | None = None) -> int:
    current = jdatetime.date.fromgregorian(date=today or date.today())
    return current.year if current.month >= 7 else current.year - 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate probable irrigated crop area for Solar Hijri months "
            "3-6 using monthly Landsat NDVI persistence conditions."
        )
    )
    parser.add_argument(
        "--geojson",
        type=Path,
        default=Path("Data/AQUIFER.geojson"),
        help="Aquifer GeoJSON path (default: Data/AQUIFER.geojson)",
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path("ee-hydrocode.json"),
        help="Google service-account JSON path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("Data/Warm_Season_Irrigated_Area.csv"),
        help=(
            "Output CSV path "
            "(default: Data/Warm_Season_Irrigated_Area.csv)"
        ),
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=LANDSAT_8_START_YEAR,
        help="First Solar Hijri year to process (default: 1392)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=latest_complete_warm_season_year(),
        help="Last complete Solar Hijri warm season to process",
    )
    parser.add_argument(
        "--max-threshold",
        type=float,
        default=0.40,
        help="Required warm-season maximum NDVI (default: > 0.40)",
    )
    parser.add_argument(
        "--mean-threshold",
        type=float,
        default=0.30,
        help="Required warm-season mean NDVI (default: > 0.30)",
    )
    parser.add_argument(
        "--stability-threshold",
        type=float,
        default=0.35,
        help="Monthly NDVI threshold used for persistence (default: > 0.35)",
    )
    parser.add_argument(
        "--min-active-months",
        type=int,
        default=2,
        help="Minimum months above the stability threshold (default: 2)",
    )
    parser.add_argument(
        "--min-valid-months",
        type=int,
        default=4,
        help=(
            "Minimum monthly composites with valid pixels (default: 4). "
            "Lower values permit classification with incomplete observations."
        ),
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=30,
        help="Earth Engine reduction scale in meters (default: 30)",
    )
    parser.add_argument(
        "--tile-scale",
        type=float,
        default=4,
        help="Earth Engine aggregation tileScale (default: 4)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2,
        help="Solar Hijri years per Earth Engine request (default: 2)",
    )
    parser.add_argument(
        "--land-cover-mask",
        choices=("gfsad-irrigated", "none"),
        default="gfsad-irrigated",
        help=(
            "Analysis mask: GFSAD LGRIP30 class 2 or the full aquifer "
            "(default: gfsad-irrigated)"
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Discard an existing output instead of resuming it",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.start_year > args.end_year:
        raise ValueError("--start-year must not be later than --end-year")
    if args.batch_size < 1:
        raise ValueError("--batch-size must be at least 1")
    if args.scale <= 0:
        raise ValueError("--scale must be positive")
    if not 1 <= args.min_active_months <= len(WARM_MONTHS):
        raise ValueError("--min-active-months must be between 1 and 4")
    if not 1 <= args.min_valid_months <= len(WARM_MONTHS):
        raise ValueError("--min-valid-months must be between 1 and 4")
    for name in (
        "max_threshold",
        "mean_threshold",
        "stability_threshold",
    ):
        if not -1 <= getattr(args, name) <= 1:
            raise ValueError(f"--{name.replace('_', '-')} must be between -1 and 1")


def warm_season(jalali_year: int) -> WarmSeason:
    start = jdatetime.date(jalali_year, WARM_MONTHS[0], 1).togregorian()
    end = jdatetime.date(jalali_year, WARM_MONTHS[-1] + 1, 1).togregorian()
    return WarmSeason(jalali_year=jalali_year, start=start, end=end)


def warm_seasons(start_year: int, end_year: int) -> list[WarmSeason]:
    if start_year > end_year:
        raise ValueError("start_year must not be later than end_year")
    return [warm_season(year) for year in range(start_year, end_year + 1)]


def month_period(jalali_year: int, month: int) -> tuple[date, date]:
    if month not in WARM_MONTHS:
        raise ValueError("Warm-season month must be between 3 and 6")
    start = jdatetime.date(jalali_year, month, 1)
    end = (
        jdatetime.date(jalali_year, month + 1, 1)
        if month < 12
        else jdatetime.date(jalali_year + 1, 1, 1)
    )
    return start.togregorian(), end.togregorian()


def meets_irrigated_conditions(
    monthly_ndvi: list[float | None],
    max_threshold: float = 0.40,
    mean_threshold: float = 0.30,
    stability_threshold: float = 0.35,
    min_active_months: int = 2,
    min_valid_months: int = 4,
) -> bool:
    valid = [
        float(value)
        for value in monthly_ndvi
        if value is not None and math.isfinite(value)
    ]
    if len(valid) < min_valid_months:
        return False
    return (
        max(valid) > max_threshold
        and sum(valid) / len(valid) > mean_threshold
        and sum(value > stability_threshold for value in valid)
        >= min_active_months
    )


def load_aquifers(path: Path) -> tuple[ee.FeatureCollection, list[tuple[str, str]]]:
    with path.open(encoding="utf-8-sig") as source:
        geojson = json.load(source)

    if geojson.get("type") != "FeatureCollection":
        raise ValueError(f"{path} is not a GeoJSON FeatureCollection")

    ee_features = []
    identities = []
    for index, feature in enumerate(geojson.get("features", [])):
        properties = feature.get("properties") or {}
        mahdoude = properties.get("MAHDOUDE")
        aquifer = properties.get("AQUIFER")
        geometry = feature.get("geometry")
        if not mahdoude or not aquifer or not geometry:
            raise ValueError(
                f"Feature {index} must have geometry, MAHDOUDE, and AQUIFER"
            )
        identity = (str(mahdoude), str(aquifer))
        identities.append(identity)
        ee_features.append(
            ee.Feature(
                ee.Geometry(geometry),
                {"MAHDOUDE": identity[0], "AQUIFER": identity[1]},
            )
        )

    if not ee_features:
        raise ValueError(f"{path} contains no features")
    if len(set(identities)) != len(identities):
        raise ValueError("MAHDOUDE/AQUIFER pairs must be unique")
    return ee.FeatureCollection(ee_features), identities


def initialize_earth_engine(credentials_path: Path) -> None:
    with credentials_path.open(encoding="utf-8") as source:
        credentials_data = json.load(source)

    email = credentials_data.get("client_email")
    project = credentials_data.get("project_id")
    if not email or not project:
        raise ValueError(
            f"{credentials_path} does not contain client_email and project_id"
        )

    credentials = ee.ServiceAccountCredentials(email, str(credentials_path))
    try:
        ee.Initialize(credentials=credentials, project=project)
    except Exception as exc:
        message = str(exc)
        if "403" in message and "earthengine.googleapis.com" in message:
            raise RuntimeError(
                "Google Earth Engine returned HTTP 403 before authentication. "
                "Use a network that can reach earthengine.googleapis.com or "
                "configure HTTPS_PROXY."
            ) from exc
        raise


def mask_and_calculate_ndvi(image: ee.Image) -> ee.Image:
    qa_pixel = image.select("QA_PIXEL")
    clear = qa_pixel.bitwiseAnd(0b111111).eq(0)
    unsaturated = image.select("QA_RADSAT").eq(0)
    red = image.select("SR_B4").multiply(0.0000275).add(-0.2)
    nir = image.select("SR_B5").multiply(0.0000275).add(-0.2)
    valid_reflectance = red.gte(0).And(nir.gte(0))
    ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI")
    return ndvi.updateMask(clear.And(unsaturated).And(valid_reflectance))


def landsat_ndvi_collection(
    geometry: ee.Geometry,
    start: date,
    end: date,
) -> ee.ImageCollection:
    merged = ee.ImageCollection(LANDSAT_COLLECTION_IDS[0])
    for collection_id in LANDSAT_COLLECTION_IDS[1:]:
        merged = merged.merge(ee.ImageCollection(collection_id))
    return (
        merged
        .filterBounds(geometry)
        .filterDate(start.isoformat(), end.isoformat())
        .map(mask_and_calculate_ndvi)
    )


def monthly_median_ndvi(
    geometry: ee.Geometry,
    jalali_year: int,
    month: int,
) -> ee.Image:
    start, end = month_period(jalali_year, month)
    images = landsat_ndvi_collection(geometry, start, end)
    empty = (
        ee.Image.constant(0)
        .rename("NDVI")
        .updateMask(ee.Image.constant(0))
    )
    return ee.Image(
        ee.Algorithms.If(
            images.size().gt(0),
            images.median().rename("NDVI"),
            empty,
        )
    ).rename(f"NDVI_{month:02d}")


def build_analysis_mask(mask_name: str) -> ee.Image:
    if mask_name == "none":
        return ee.Image.constant(1).rename("analysis_mask")
    if mask_name == "gfsad-irrigated":
        return (
            ee.ImageCollection(GFSAD_LGRIP30_ASSET_ID)
            .mosaic()
            .select([0])
            .eq(GFSAD_IRRIGATED_CROPLAND_CLASS)
            .selfMask()
            .rename("analysis_mask")
        )
    raise ValueError(f"Unsupported land-cover mask: {mask_name}")


def classified_area_image(
    geometry: ee.Geometry,
    season: WarmSeason,
    analysis_mask: ee.Image,
    max_threshold: float,
    mean_threshold: float,
    stability_threshold: float,
    min_active_months: int,
    min_valid_months: int,
) -> ee.Image:
    monthly_images = [
        monthly_median_ndvi(geometry, season.jalali_year, month)
        for month in WARM_MONTHS
    ]
    stack = monthly_images[0]
    for image in monthly_images[1:]:
        stack = stack.addBands(image)

    valid_month_count = (
        stack.reduce(ee.Reducer.count())
        .unmask(0)
        .rename("VALID_MONTH_COUNT")
    )
    active_month_count = (
        stack.gt(stability_threshold)
        .unmask(0)
        .reduce(ee.Reducer.sum())
        .rename("ACTIVE_MONTH_COUNT")
    )
    warm_mean = stack.reduce(ee.Reducer.mean()).rename("WARM_NDVI_MEAN")
    warm_max = stack.reduce(ee.Reducer.max()).rename("WARM_NDVI_MAX")

    probable_irrigated = (
        warm_max.gt(max_threshold)
        .And(warm_mean.gt(mean_threshold))
        .And(active_month_count.gte(min_active_months))
        .And(valid_month_count.gte(min_valid_months))
        .updateMask(analysis_mask)
        .selfMask()
    )
    valid_observations = (
        valid_month_count.gte(min_valid_months)
        .updateMask(analysis_mask)
        .selfMask()
    )
    pixel_area_ha = ee.Image.pixelArea().divide(10_000)
    return (
        pixel_area_ha.multiply(probable_irrigated.unmask(0))
        .updateMask(analysis_mask)
        .rename("PROBABLE_IRRIGATED_AREA_HA")
        .addBands(
            pixel_area_ha.updateMask(analysis_mask)
            .rename("ANALYSIS_MASK_AREA_HA")
        )
        .addBands(
            pixel_area_ha.multiply(valid_observations.unmask(0))
            .updateMask(analysis_mask)
            .rename("VALID_OBSERVATION_AREA_HA")
        )
    )


def season_statistics_collection(
    aquifers: ee.FeatureCollection,
    season: WarmSeason,
    analysis_mask: ee.Image,
    max_threshold: float,
    mean_threshold: float,
    stability_threshold: float,
    min_active_months: int,
    min_valid_months: int,
    scale: float,
    tile_scale: float,
) -> ee.FeatureCollection:
    area_image = classified_area_image(
        aquifers.geometry(),
        season,
        analysis_mask,
        max_threshold,
        mean_threshold,
        stability_threshold,
        min_active_months,
        min_valid_months,
    )
    reduced = area_image.reduceRegions(
        collection=aquifers,
        reducer=ee.Reducer.sum(),
        scale=scale,
        tileScale=tile_scale,
    )
    return reduced.map(
        lambda feature: feature.set(
            {
                "JALALI_YEAR": season.label,
                "PERIOD_START": season.period_start,
                "PERIOD_END_EXCLUSIVE": season.period_end_exclusive,
            }
        )
    )


def batch_statistics(
    aquifers: ee.FeatureCollection,
    seasons: list[WarmSeason],
    analysis_mask: ee.Image,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    merged = ee.FeatureCollection([])
    for season in seasons:
        merged = merged.merge(
            season_statistics_collection(
                aquifers,
                season,
                analysis_mask,
                args.max_threshold,
                args.mean_threshold,
                args.stability_threshold,
                args.min_active_months,
                args.min_valid_months,
                args.scale,
                args.tile_scale,
            )
        )
    response = merged.getInfo()
    return [feature.get("properties", {}) for feature in response["features"]]


def fetch_with_retries(
    aquifers: ee.FeatureCollection,
    seasons: list[WarmSeason],
    analysis_mask: ee.Image,
    args: argparse.Namespace,
    attempts: int = 5,
) -> list[dict[str, Any]]:
    for attempt in range(1, attempts + 1):
        try:
            return batch_statistics(aquifers, seasons, analysis_mask, args)
        except Exception as exc:
            if attempt == attempts:
                raise
            wait_seconds = 2**attempt
            print(
                f"  Earth Engine request failed: {exc}; "
                f"retrying in {wait_seconds}s"
            )
            time.sleep(wait_seconds)
    raise RuntimeError("unreachable")


def finite_or_blank(value: Any, digits: int = 4) -> float | str:
    if value is None:
        return ""
    number = float(value)
    if not math.isfinite(number):
        return ""
    return round(number, digits)


def percentage_or_blank(numerator: Any, denominator: Any) -> float | str:
    if numerator is None or denominator is None:
        return ""
    numerator_value = float(numerator)
    denominator_value = float(denominator)
    if (
        not math.isfinite(numerator_value)
        or not math.isfinite(denominator_value)
        or denominator_value <= 0
    ):
        return ""
    return round(100 * numerator_value / denominator_value, 2)


def metadata_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".metadata.json")


def run_metadata(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "version": RUN_METADATA_VERSION,
        "landsat_collections": list(LANDSAT_COLLECTION_IDS),
        "calendar": "Solar Hijri",
        "warm_months": list(WARM_MONTHS),
        "monthly_composite": "median",
        "conditions": {
            "max_ndvi_greater_than": args.max_threshold,
            "mean_ndvi_greater_than": args.mean_threshold,
            "monthly_ndvi_greater_than": args.stability_threshold,
            "minimum_active_months": args.min_active_months,
            "minimum_valid_months": args.min_valid_months,
        },
        "land_cover_mask": args.land_cover_mask,
        "land_cover_asset": (
            GFSAD_LGRIP30_ASSET_ID
            if args.land_cover_mask == "gfsad-irrigated"
            else None
        ),
        "land_cover_class": (
            GFSAD_IRRIGATED_CROPLAND_CLASS
            if args.land_cover_mask == "gfsad-irrigated"
            else None
        ),
        "scale_meters": args.scale,
    }


def read_existing_rows(
    path: Path,
    overwrite: bool,
    expected_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    if overwrite or not path.exists():
        return []
    run_metadata_path = metadata_path(path)
    if not run_metadata_path.exists():
        raise ValueError(
            f"{path} has no run metadata; use --overwrite to recreate it"
        )
    with run_metadata_path.open(encoding="utf-8") as source:
        existing_metadata = json.load(source)
    if existing_metadata != expected_metadata:
        raise ValueError(
            f"{path} was created with different thresholds or settings; "
            "use --overwrite to replace it"
        )
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != CSV_FIELDS:
            raise ValueError(
                f"{path} has unexpected columns; use --overwrite to replace it"
            )
        return list(reader)


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row["JALALI_YEAR"]),
            row["MAHDOUDE"],
            row["AQUIFER"],
        ),
    )
    with temporary.open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)
    temporary.replace(path)


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    run_metadata_path = metadata_path(path)
    temporary = run_metadata_path.with_suffix(run_metadata_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as destination:
        json.dump(metadata, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    temporary.replace(run_metadata_path)


def output_row(item: dict[str, Any]) -> dict[str, Any]:
    probable = item.get("PROBABLE_IRRIGATED_AREA_HA")
    analysis = item.get("ANALYSIS_MASK_AREA_HA")
    valid = item.get("VALID_OBSERVATION_AREA_HA")
    return {
        "MAHDOUDE": item["MAHDOUDE"],
        "AQUIFER": item["AQUIFER"],
        "JALALI_YEAR": item["JALALI_YEAR"],
        "PERIOD_START": item["PERIOD_START"],
        "PERIOD_END_EXCLUSIVE": item["PERIOD_END_EXCLUSIVE"],
        "PROBABLE_IRRIGATED_AREA_HA": finite_or_blank(probable),
        "ANALYSIS_MASK_AREA_HA": finite_or_blank(analysis),
        "VALID_OBSERVATION_AREA_HA": finite_or_blank(valid),
        "PROBABLE_PERCENT_OF_ANALYSIS": percentage_or_blank(probable, analysis),
        "VALID_PERCENT_OF_ANALYSIS": percentage_or_blank(valid, analysis),
    }


def main() -> None:
    args = parse_args()
    validate_args(args)
    expected_metadata = run_metadata(args)
    rows = read_existing_rows(args.output, args.overwrite, expected_metadata)

    initialize_earth_engine(args.credentials)
    aquifers, identities = load_aquifers(args.geojson)
    analysis_mask = build_analysis_mask(args.land_cover_mask)
    seasons = warm_seasons(args.start_year, args.end_year)

    if args.overwrite:
        write_rows(args.output, [])
        write_metadata(args.output, expected_metadata)

    year_counts = Counter(row["JALALI_YEAR"] for row in rows)
    completed_years = {
        year
        for year, count in year_counts.items()
        if count == len(identities)
    }
    pending = [
        season for season in seasons if season.label not in completed_years
    ]
    skipped = len(seasons) - len(pending)
    if skipped:
        print(f"Skipping {skipped} complete Solar Hijri years already present")

    for offset in range(0, len(pending), args.batch_size):
        batch = pending[offset : offset + args.batch_size]
        print(
            f"[{offset + 1}-{offset + len(batch)}/{len(pending)}] "
            f"{batch[0].label} to {batch[-1].label}"
        )
        properties = fetch_with_retries(
            aquifers,
            batch,
            analysis_mask,
            args,
        )
        expected_features = len(batch) * len(identities)
        if len(properties) != expected_features:
            raise RuntimeError(
                f"Earth Engine returned {len(properties)} of "
                f"{expected_features} annual aquifer records"
            )

        batch_years = {season.label for season in batch}
        rows = [
            row for row in rows if row["JALALI_YEAR"] not in batch_years
        ]
        rows.extend(output_row(item) for item in properties)
        write_rows(args.output, rows)
        write_metadata(args.output, expected_metadata)

    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
