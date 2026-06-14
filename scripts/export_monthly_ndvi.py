#!/usr/bin/env python3
"""Export monthly Landsat 8 NDVI statistics for the aquifer polygons."""

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


COLLECTION_ID = "LANDSAT/LC08/C02/T1_L2"
GFSAD_LGRIP30_ASSET_ID = "projects/sat-io/open-datasets/GFSAD/LGRIP30"
GFSAD_IRRIGATED_CROPLAND_CLASS = 2
RUN_METADATA_VERSION = 2
CSV_FIELDS = [
    "MAHDOUDE",
    "AQUIFER",
    "DATE",
    "NDVI_MEAN",
    "NDVI_MEDIAN",
    "NDVI_MAX",
]


def parse_args() -> argparse.Namespace:
    today = date.today()
    parser = argparse.ArgumentParser(
        description=(
            "Calculate Landsat 8 monthly NDVI statistics inside each aquifer. "
            "DATE values are Solar Hijri month starts."
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
        default=Path("Data/Monthly_NDVI.csv"),
        help="Output CSV path (default: Data/Monthly_NDVI.csv)",
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=date(2013, 3, 18),
        help="Inclusive Gregorian start date (default: Landsat 8 availability)",
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
        default=6,
        help="Solar Hijri months per Earth Engine request (default: 6)",
    )
    parser.add_argument(
        "--land-cover-mask",
        choices=("gfsad-irrigated", "none"),
        default="gfsad-irrigated",
        help=(
            "Pixel mask applied before polygon statistics: gfsad-irrigated "
            "keeps only class 2 (irrigated croplands) from GFSAD LGRIP30; "
            "none keeps the full aquifer (default: gfsad-irrigated)"
        ),
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


def mask_and_calculate_ndvi(image: ee.Image) -> ee.Image:
    qa_pixel = image.select("QA_PIXEL")
    clear = qa_pixel.bitwiseAnd(0b111111).eq(0)
    unsaturated = image.select("QA_RADSAT").eq(0)

    red = image.select("SR_B4").multiply(0.0000275).add(-0.2)
    nir = image.select("SR_B5").multiply(0.0000275).add(-0.2)
    valid_reflectance = red.gte(0).And(nir.gte(0))
    ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI")
    return ndvi.updateMask(clear.And(unsaturated).And(valid_reflectance)).copyProperties(
        image, ["system:time_start"]
    )


def build_land_cover_mask(mask_name: str) -> ee.Image | None:
    if mask_name == "none":
        return None
    if mask_name == "gfsad-irrigated":
        return (
            ee.ImageCollection(GFSAD_LGRIP30_ASSET_ID)
            .mosaic()
            .select([0])
            .eq(GFSAD_IRRIGATED_CROPLAND_CLASS)
            .selfMask()
            .rename("irrigated_cropland")
        )
    raise ValueError(f"Unsupported land-cover mask: {mask_name}")


def monthly_statistics_collection(
    aquifers: ee.FeatureCollection,
    period_start: date,
    period_end: date,
    scale: float,
    tile_scale: float,
    land_cover_mask: ee.Image | None,
) -> ee.FeatureCollection:
    images = (
        ee.ImageCollection(COLLECTION_ID)
        .filterBounds(aquifers.geometry())
        .filterDate(period_start.isoformat(), period_end.isoformat())
        .map(mask_and_calculate_ndvi)
    )

    empty_mask = ee.Image.constant(0)
    empty = (
        ee.Image.constant([0, 0, 0])
        .rename(["NDVI_MEAN", "NDVI_MEDIAN", "NDVI_MAX"])
        .updateMask(empty_mask)
    )
    composites = (
        images.mean()
        .rename("NDVI_MEAN")
        .addBands(images.median().rename("NDVI_MEDIAN"))
        .addBands(images.max().rename("NDVI_MAX"))
    )
    monthly_images = ee.Image(
        ee.Algorithms.If(images.size().gt(0), composites, empty)
    )
    if land_cover_mask is not None:
        monthly_images = monthly_images.updateMask(land_cover_mask)
    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.median(), sharedInputs=False)
        .combine(ee.Reducer.max(), sharedInputs=False)
    )
    reduced = monthly_images.reduceRegions(
        collection=aquifers,
        reducer=reducer,
        scale=scale,
        tileScale=tile_scale,
    )
    return reduced


def finite_or_blank(value: Any) -> float | str:
    if value is None:
        return ""
    number = float(value)
    if not math.isfinite(number):
        return ""
    return round(number, 6)


def metadata_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".metadata.json")


def run_metadata(mask_name: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "version": RUN_METADATA_VERSION,
        "landsat_collection": COLLECTION_ID,
        "land_cover_mask": mask_name,
    }
    if mask_name == "gfsad-irrigated":
        metadata.update(
            {
                "land_cover_asset": GFSAD_LGRIP30_ASSET_ID,
                "land_cover_product": "LGRIP30",
                "cropland_class": GFSAD_IRRIGATED_CROPLAND_CLASS,
                "cropland_label": "Irrigated croplands",
            }
        )
    return metadata


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
            f"{path} has no run metadata and may contain full-aquifer NDVI. "
            "Use --overwrite to recalculate it with the selected land-cover mask."
        )
    with run_metadata_path.open(encoding="utf-8") as source:
        existing_metadata = json.load(source)
    if existing_metadata != expected_metadata:
        raise ValueError(
            f"{path} was created with different mask settings. "
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
    land_cover_mask: ee.Image | None,
) -> list[dict[str, Any]]:
    merged = ee.FeatureCollection([])
    for jalali_date, period_start, period_end, _ in periods:
        reduced = monthly_statistics_collection(
            aquifers,
            period_start,
            period_end,
            scale,
            tile_scale,
            land_cover_mask,
        ).map(lambda feature: feature.set("DATE", jalali_date))
        merged = merged.merge(reduced)

    response = merged.getInfo()
    return [feature.get("properties", {}) for feature in response["features"]]


def fetch_with_retries(
    aquifers: ee.FeatureCollection,
    periods: list[tuple[str, date, date, bool]],
    scale: float,
    tile_scale: float,
    land_cover_mask: ee.Image | None,
    attempts: int = 5,
) -> list[dict[str, Any]]:
    for attempt in range(1, attempts + 1):
        try:
            return batch_statistics(
                aquifers,
                periods,
                scale,
                tile_scale,
                land_cover_mask,
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

    expected_metadata = run_metadata(args.land_cover_mask)
    rows = read_existing_rows(
        args.output,
        args.overwrite,
        expected_metadata,
    )

    initialize_earth_engine(args.credentials)
    aquifers, identities = load_aquifers(args.geojson)
    land_cover_mask = build_land_cover_mask(args.land_cover_mask)
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
            land_cover_mask,
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
                    "NDVI_MEAN": finite_or_blank(item.get("mean")),
                    "NDVI_MEDIAN": finite_or_blank(item.get("median")),
                    "NDVI_MAX": finite_or_blank(item.get("max")),
                }
            )
        write_rows(args.output, rows)
        write_metadata(args.output, expected_metadata)

    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
