#!/usr/bin/env python3
"""Export Solar Hijri monthly WaPOR actual evapotranspiration by aquifer."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import ee
import jdatetime


COLLECTION_ID = "FAO/WAPOR/3/L1_AETI_D"
BAND_NAME = "L1-AETI-D"
BAND_SCALE_FACTOR = 0.1
DATASET_START = date(2018, 1, 1)
RUN_METADATA_VERSION = 1
CSV_FIELDS = ["MAHDOUDE", "AQUIFER", "DATE", "AET"]


def parse_args() -> argparse.Namespace:
    today = date.today()
    parser = argparse.ArgumentParser(
        description=(
            "Calculate mean monthly actual evapotranspiration and interception "
            "inside each aquifer. DATE values are Solar Hijri month starts."
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
        default=Path("Data/Monthly_AET.csv"),
        help="Output CSV path (default: Data/Monthly_AET.csv)",
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=DATASET_START,
        help="Inclusive Gregorian start date (default: 2018-01-01)",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=today + timedelta(days=1),
        help="Exclusive Gregorian end date (default: tomorrow)",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=250,
        help="Earth Engine reduction scale in meters (default: 250)",
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
        default=12,
        help="Solar Hijri months per Earth Engine request (default: 12)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Discard an existing output instead of resuming it",
    )
    return parser.parse_args()


def next_jalali_month(value: jdatetime.date) -> jdatetime.date:
    if value.month == 12:
        return jdatetime.date(value.year + 1, 1, 1)
    return jdatetime.date(value.year, value.month + 1, 1)


def iter_jalali_months(
    start: date, end: date
) -> list[tuple[str, date, date, bool]]:
    if end <= start:
        raise ValueError("--end must be later than --start")

    current_jalali = jdatetime.date.fromgregorian(date=start).replace(day=1)
    periods: list[tuple[str, date, date, bool]] = []
    while True:
        following_jalali = next_jalali_month(current_jalali)
        month_start = current_jalali.togregorian()
        month_end = following_jalali.togregorian()
        clipped_start = max(start, month_start)
        clipped_end = min(end, month_end)
        if clipped_start < clipped_end:
            periods.append(
                (
                    f"{current_jalali.year:04d}-{current_jalali.month:02d}-01",
                    clipped_start,
                    clipped_end,
                    clipped_start == month_start and clipped_end == month_end,
                )
            )
        if month_end >= end:
            break
        current_jalali = following_jalali
    return periods


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

        identities.append((str(mahdoude), str(aquifer)))
        ee_features.append(
            ee.Feature(
                ee.Geometry(geometry),
                {
                    "MAHDOUDE": str(mahdoude),
                    "AQUIFER": str(aquifer),
                },
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
                "Run through a network/VPN that can reach "
                "earthengine.googleapis.com, or configure HTTPS_PROXY."
            ) from exc
        raise


def dekad_end(image_start: ee.Date) -> ee.Date:
    day_of_month = ee.Number.parse(image_start.format("d"))
    month_start = ee.Date.fromYMD(
        image_start.get("year"),
        image_start.get("month"),
        1,
    )
    return ee.Date(
        ee.Algorithms.If(
            day_of_month.lt(21),
            image_start.advance(10, "day"),
            month_start.advance(1, "month"),
        )
    )


def monthly_contribution(
    image: ee.Image,
    period_start: ee.Date,
    period_end: ee.Date,
) -> ee.Image:
    image_start = ee.Date(image.get("system:time_start"))
    fallback_end = dekad_end(image_start)
    image_end = ee.Date(
        ee.Algorithms.If(
            image.propertyNames().contains("system:time_end"),
            image.get("system:time_end"),
            fallback_end.millis(),
        )
    )
    overlap_start = ee.Date(
        ee.Number(image_start.millis()).max(period_start.millis())
    )
    overlap_end = ee.Date(
        ee.Number(image_end.millis()).min(period_end.millis())
    )
    overlap_days = ee.Number(overlap_end.difference(overlap_start, "day")).max(0)
    contribution = (
        image.select(BAND_NAME)
        .multiply(BAND_SCALE_FACTOR)
        .multiply(overlap_days)
        .rename("AET")
        .toFloat()
    )
    return contribution.set("_overlap_days", overlap_days)


def monthly_statistics_collection(
    aquifers: ee.FeatureCollection,
    period_start: date,
    period_end: date,
    scale: float,
    tile_scale: float,
) -> ee.FeatureCollection:
    start = ee.Date(period_start.isoformat())
    end = ee.Date(period_end.isoformat())
    contributions = (
        ee.ImageCollection(COLLECTION_ID)
        .filterBounds(aquifers.geometry())
        .filterDate(start.advance(-11, "day"), end)
        .map(lambda image: monthly_contribution(image, start, end))
        .filter(ee.Filter.gt("_overlap_days", 0))
    )
    empty = (
        ee.Image.constant(0)
        .rename("AET")
        .toFloat()
        .updateMask(ee.Image.constant(0))
    )
    monthly_total = ee.Image(
        ee.Algorithms.If(
            contributions.size().gt(0),
            contributions.sum().rename("AET"),
            empty,
        )
    )
    return monthly_total.reduceRegions(
        collection=aquifers,
        reducer=ee.Reducer.mean(),
        scale=scale,
        tileScale=tile_scale,
    )


def finite_or_blank(value: Any) -> float | str:
    if value is None:
        return ""
    number = float(value)
    if not math.isfinite(number):
        return ""
    return round(number, 3)


def metadata_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".metadata.json")


def run_metadata() -> dict[str, Any]:
    return {
        "version": RUN_METADATA_VERSION,
        "collection": COLLECTION_ID,
        "band": BAND_NAME,
        "source_unit": "mm/day",
        "output_unit": "mm/month",
        "scale_factor": BAND_SCALE_FACTOR,
        "temporal_aggregation": "sum_daily_rate_weighted_by_solar_month_overlap",
        "spatial_aggregation": "mean_inside_aquifer",
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
            f"{path} has no run metadata. Use --overwrite to recalculate it."
        )
    with run_metadata_path.open(encoding="utf-8") as source:
        existing_metadata = json.load(source)
    if existing_metadata != expected_metadata:
        raise ValueError(
            f"{path} was created with different settings. "
            "Use --overwrite to replace it."
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
        key=lambda row: (row["MAHDOUDE"], row["AQUIFER"], row["DATE"]),
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


def batch_statistics(
    aquifers: ee.FeatureCollection,
    periods: list[tuple[str, date, date, bool]],
    scale: float,
    tile_scale: float,
) -> list[dict[str, Any]]:
    merged = ee.FeatureCollection([])
    for jalali_date, period_start, period_end, _ in periods:
        reduced = monthly_statistics_collection(
            aquifers,
            period_start,
            period_end,
            scale,
            tile_scale,
        ).map(lambda feature: feature.set("DATE", jalali_date))
        merged = merged.merge(reduced)

    response = merged.getInfo()
    return [feature.get("properties", {}) for feature in response["features"]]


def fetch_with_retries(
    aquifers: ee.FeatureCollection,
    periods: list[tuple[str, date, date, bool]],
    scale: float,
    tile_scale: float,
    attempts: int = 5,
) -> list[dict[str, Any]]:
    for attempt in range(1, attempts + 1):
        try:
            return batch_statistics(
                aquifers,
                periods,
                scale,
                tile_scale,
            )
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


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("--batch-size must be at least 1")
    if args.start < DATASET_START:
        raise ValueError(
            f"WaPOR 3.0 starts on {DATASET_START.isoformat()}; "
            "choose a later --start date"
        )

    expected_metadata = run_metadata()
    rows = read_existing_rows(
        args.output,
        args.overwrite,
        expected_metadata,
    )

    initialize_earth_engine(args.credentials)
    aquifers, identities = load_aquifers(args.geojson)
    periods = iter_jalali_months(args.start, args.end)

    if args.overwrite:
        write_rows(args.output, [])
        write_metadata(args.output, expected_metadata)
    date_counts = Counter(row["DATE"] for row in rows)
    completed_dates = {
        output_date
        for output_date, count in date_counts.items()
        if count == len(identities)
    }
    pending = [
        period
        for period in periods
        if not (period[3] and period[0] in completed_dates)
    ]
    skipped = len(periods) - len(pending)
    if skipped:
        print(f"Skipping {skipped} complete months already present in the CSV")

    for offset in range(0, len(pending), args.batch_size):
        batch = pending[offset : offset + args.batch_size]
        dates = [period[0] for period in batch]
        print(
            f"[{offset + 1}-{offset + len(batch)}/{len(pending)}] "
            f"{dates[0]} to {dates[-1]}"
        )
        properties = fetch_with_retries(
            aquifers,
            batch,
            args.scale,
            args.tile_scale,
        )
        expected_features = len(batch) * len(identities)
        if len(properties) != expected_features:
            raise RuntimeError(
                f"Earth Engine returned {len(properties)} of "
                f"{expected_features} monthly aquifer records"
            )

        batch_dates = set(dates)
        rows = [row for row in rows if row["DATE"] not in batch_dates]
        for item in properties:
            rows.append(
                {
                    "MAHDOUDE": item["MAHDOUDE"],
                    "AQUIFER": item["AQUIFER"],
                    "DATE": item["DATE"],
                    "AET": finite_or_blank(item.get("mean")),
                }
            )
        write_rows(args.output, rows)
        write_metadata(args.output, expected_metadata)

    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
