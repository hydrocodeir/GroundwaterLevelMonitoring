from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.interpolate import (
    LinearNDInterpolator,
    NearestNDInterpolator,
    RBFInterpolator,
)
from scipy.optimize import curve_fit
from scipy.stats import kendalltau, pearsonr, spearmanr, theilslopes
from pyproj import Transformer
from shapely import voronoi_polygons
from shapely.geometry import MultiPoint, Point, box, mapping, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "Data"
MONTHS_PER_YEAR = 12
WATER_YEAR_START_MONTH = 7
WATER_YEAR_END_MONTH = 6
NDVI_WARM_MONTHS = frozenset(range(3, 7))
DEFAULT_ANALYSIS_YEARS = 4
NEAREST_PRECIPITATION_STATION_COUNT = 3
COMPARISON_GEOMETRY_TOLERANCE = 0.001
PIEZOMETRIC_SURFACE_GRID_SIZE = 48
IDW_POWER = 2.0
SURFACE_INTERPOLATION_METHODS = frozenset(
    {
        "idw",
        "natural_neighbor",
        "ordinary_kriging",
        "universal_kriging",
        "regression_kriging",
        "spline",
    }
)
SURFACE_INTERPOLATION_METHOD_ORDER = (
    "idw",
    "natural_neighbor",
    "ordinary_kriging",
    "universal_kriging",
    "regression_kriging",
    "spline",
)
SURFACE_INTERPOLATION_LABELS = {
    "idw": "IDW",
    "natural_neighbor": "Natural Neighbor / TIN",
    "ordinary_kriging": "Ordinary Kriging",
    "universal_kriging": "Universal Kriging",
    "regression_kriging": "Regression Kriging",
    "spline": "Thin Plate Spline",
}
CORRECTED_SUPPORT_METHODS = frozenset(
    {"fixed_thiessen", "fixed_arithmetic", "fixed_median", "fixed_grid", "none"}
)
CORRECTED_SUPPORT_LABELS = {
    "fixed_thiessen": "پشتیبان ثابت تیسن",
    "fixed_arithmetic": "پشتیبان ثابت چاه‌ها",
    "fixed_median": "میانه ثابت چاه‌ها",
    "fixed_grid": "شبکه ثابت آبخوان",
    "none": "بدون اصلاح",
}
TREND_STRONG_THRESHOLD = 0.6
TREND_WEAK_THRESHOLD = 0.3
DECLINE_ANOMALY_Z_THRESHOLD = 1.5

CHAR_TRANSLATION = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
        "ؤ": "و",
        "أ": "ا",
        "إ": "ا",
    }
)
SPACE_PATTERN = re.compile(r"[\s\u200c\u200d\u200e\u200f\u2066-\u2069_-]+")


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).translate(CHAR_TRANSLATION)
    return SPACE_PATTERN.sub("", text).strip()


def aquifer_id(mahdoude_key: str, aquifer_key: str) -> str:
    raw = f"{mahdoude_key}|{aquifer_key}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def finite_or_none(value: Any, digits: int = 2) -> float | None:
    if value is None or pd.isna(value) or not np.isfinite(value):
        return None
    return round(float(value), digits)


@dataclass(frozen=True)
class BoundaryFeature:
    properties: dict[str, Any]
    geometry: Any


class GroundwaterData:
    def __init__(self) -> None:
        self.locations = self._load_locations()
        self.measurements = self._load_measurements()
        self.aquifer_features = self._load_features("AQUIFER.geojson")
        self.mahdoude_features = self._load_features("MAHDOUDE.geojson")
        self.groups = self._build_groups()
        self.boundary_matches = self._match_boundaries()
        self.ndvi = self._load_ndvi()
        self.aet = self._load_aet()
        self.warm_season_irrigated_area = (
            self._load_warm_season_irrigated_area()
        )
        self.precipitation = self._load_precipitation()
        self.precipitation_stations = self._precipitation_station_metadata()
        self.precipitation_selections = {
            group_id: self._select_precipitation_stations(group_id)
            for group_id in self.groups
        }
        self.monthly = self._prepare_monthly_measurements()
        self.water_years = self._available_water_years()

    @staticmethod
    def _load_features(filename: str) -> list[BoundaryFeature]:
        with (DATA_DIR / filename).open(encoding="utf-8") as handle:
            collection = json.load(handle)
        return [
            BoundaryFeature(feature.get("properties", {}), shape(feature["geometry"]))
            for feature in collection["features"]
        ]

    @staticmethod
    def _load_locations() -> pd.DataFrame:
        frame = pd.read_csv(DATA_DIR / "LOCATION.csv", encoding="utf-8-sig")
        frame["_mahdoude_key"] = frame["MAHDOUDE"].map(normalize_name)
        frame["_aquifer_key"] = frame["AQUIFER"].map(normalize_name)
        frame["_location_key"] = frame["LOCATION"].map(normalize_name)
        frame["_join_key"] = (
            frame["_mahdoude_key"] + "|" + frame["_aquifer_key"] + "|" + frame["_location_key"]
        )
        frame["_aquifer_id"] = [
            aquifer_id(m, a) for m, a in zip(frame["_mahdoude_key"], frame["_aquifer_key"])
        ]
        frame["_well_id"] = [
            hashlib.sha1(f"{key}|{index}".encode("utf-8")).hexdigest()[:12]
            for index, key in enumerate(frame["_join_key"])
        ]
        frame["_site_key"] = frame["X"].round(6).astype(str) + "|" + frame["Y"].round(6).astype(str)
        return frame

    @staticmethod
    def _load_measurements() -> pd.DataFrame:
        frame = pd.read_csv(DATA_DIR / "DATA.csv", encoding="utf-8-sig")
        frame["_mahdoude_key"] = frame["MAHDOUDE"].map(normalize_name)
        frame["_aquifer_key"] = frame["AQUIFER"].map(normalize_name)
        frame["_location_key"] = frame["LOCATION"].map(normalize_name)
        frame["_join_key"] = (
            frame["_mahdoude_key"] + "|" + frame["_aquifer_key"] + "|" + frame["_location_key"]
        )
        frame["_aquifer_id"] = [
            aquifer_id(m, a) for m, a in zip(frame["_mahdoude_key"], frame["_aquifer_key"])
        ]
        frame["_month"] = (
            frame["YEAR_PERSIAN"].astype(int).astype(str)
            + "-"
            + frame["MONTH_PERSIAN"].astype(int).astype(str).str.zfill(2)
        )
        frame["_month_index"] = (
            frame["YEAR_PERSIAN"].astype(int) * MONTHS_PER_YEAR
            + frame["MONTH_PERSIAN"].astype(int)
        )
        return frame

    @staticmethod
    def _load_precipitation() -> pd.DataFrame:
        frame = pd.read_csv(
            DATA_DIR / "Monthly_Precipitation.csv",
            encoding="utf-8-sig",
            dtype={"station_id": str},
        )
        required = {
            "station_id",
            "station_name",
            "lat",
            "lon",
            "elev",
            "date",
            "precip",
        }
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(
                f"ستون‌های فایل بارش کامل نیستند: {', '.join(sorted(missing))}"
            )
        date_parts = frame["date"].astype(str).str.extract(
            r"^(?P<year>\d{4})-(?P<month>\d{1,2})-\d{1,2}$"
        )
        frame["_year"] = pd.to_numeric(date_parts["year"], errors="coerce")
        frame["_month_number"] = pd.to_numeric(date_parts["month"], errors="coerce")
        for column in ("lat", "lon", "elev", "precip"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(
            subset=[
                "station_id",
                "station_name",
                "lat",
                "lon",
                "precip",
                "_year",
                "_month_number",
            ]
        ).copy()
        frame = frame[
            frame["_month_number"].between(1, MONTHS_PER_YEAR)
            & frame["precip"].ge(0)
        ].copy()
        frame["_year"] = frame["_year"].astype(int)
        frame["_month_number"] = frame["_month_number"].astype(int)
        frame["_month_index"] = (
            frame["_year"] * MONTHS_PER_YEAR + frame["_month_number"]
        )
        frame["_month"] = (
            frame["_year"].astype(str)
            + "-"
            + frame["_month_number"].astype(str).str.zfill(2)
        )
        return (
            frame.groupby(
                [
                    "station_id",
                    "station_name",
                    "lat",
                    "lon",
                    "elev",
                    "_month_index",
                    "_month",
                ],
                as_index=False,
                dropna=False,
            )
            .agg(precip=("precip", "mean"))
            .sort_values(["station_id", "_month_index"])
        )

    @staticmethod
    def _load_ndvi() -> pd.DataFrame:
        frame = pd.read_csv(
            DATA_DIR / "Monthly_NDVI.csv",
            encoding="utf-8-sig",
        )
        value_columns = ["NDVI_MEAN", "NDVI_MEDIAN", "NDVI_MAX"]
        required = {"MAHDOUDE", "AQUIFER", "DATE", *value_columns}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(
                f"ستون‌های فایل NDVI کامل نیستند: {', '.join(sorted(missing))}"
            )

        date_parts = frame["DATE"].astype(str).str.extract(
            r"^(?P<year>\d{4})-(?P<month>\d{1,2})-\d{1,2}$"
        )
        frame["_year"] = pd.to_numeric(date_parts["year"], errors="coerce")
        frame["_month_number"] = pd.to_numeric(
            date_parts["month"],
            errors="coerce",
        )
        for column in value_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(
            subset=["MAHDOUDE", "AQUIFER", "_year", "_month_number"]
        ).copy()
        frame = frame[frame["_month_number"].between(1, MONTHS_PER_YEAR)].copy()
        frame["_year"] = frame["_year"].astype(int)
        frame["_month_number"] = frame["_month_number"].astype(int)
        frame["_month_index"] = (
            frame["_year"] * MONTHS_PER_YEAR + frame["_month_number"]
        )
        frame["_mahdoude_key"] = frame["MAHDOUDE"].map(normalize_name)
        frame["_aquifer_key"] = frame["AQUIFER"].map(normalize_name)
        return (
            frame.groupby(
                ["_mahdoude_key", "_aquifer_key", "_month_index"],
                as_index=False,
            )[value_columns]
            .mean()
            .sort_values(
                ["_mahdoude_key", "_aquifer_key", "_month_index"]
            )
        )

    @staticmethod
    def _load_aet() -> pd.DataFrame:
        path = DATA_DIR / "Monthly_AET.csv"
        result_columns = [
            "_mahdoude_key",
            "_aquifer_key",
            "_month_index",
            "AET",
        ]
        if not path.exists():
            return pd.DataFrame(columns=result_columns)

        frame = pd.read_csv(path, encoding="utf-8-sig")
        required = {"MAHDOUDE", "AQUIFER", "DATE", "AET"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(
                f"ستون‌های فایل AET کامل نیستند: {', '.join(sorted(missing))}"
            )

        date_parts = frame["DATE"].astype(str).str.extract(
            r"^(?P<year>\d{4})-(?P<month>\d{1,2})-\d{1,2}$"
        )
        frame["_year"] = pd.to_numeric(date_parts["year"], errors="coerce")
        frame["_month_number"] = pd.to_numeric(
            date_parts["month"],
            errors="coerce",
        )
        frame["AET"] = pd.to_numeric(frame["AET"], errors="coerce")
        frame = frame.dropna(
            subset=["MAHDOUDE", "AQUIFER", "_year", "_month_number"]
        ).copy()
        frame = frame[
            frame["_month_number"].between(1, MONTHS_PER_YEAR)
            & (frame["AET"].isna() | frame["AET"].ge(0))
        ].copy()
        frame["_year"] = frame["_year"].astype(int)
        frame["_month_number"] = frame["_month_number"].astype(int)
        frame["_month_index"] = (
            frame["_year"] * MONTHS_PER_YEAR + frame["_month_number"]
        )
        frame["_mahdoude_key"] = frame["MAHDOUDE"].map(normalize_name)
        frame["_aquifer_key"] = frame["AQUIFER"].map(normalize_name)
        return (
            frame.groupby(
                ["_mahdoude_key", "_aquifer_key", "_month_index"],
                as_index=False,
            )[["AET"]]
            .mean()
            .sort_values(
                ["_mahdoude_key", "_aquifer_key", "_month_index"]
            )
        )

    @staticmethod
    def _load_warm_season_irrigated_area() -> pd.DataFrame:
        path = DATA_DIR / "Warm_Season_Irrigated_Area.csv"
        value_columns = [
            "PROBABLE_IRRIGATED_AREA_HA",
            "ANALYSIS_MASK_AREA_HA",
            "VALID_OBSERVATION_AREA_HA",
            "PROBABLE_PERCENT_OF_ANALYSIS",
            "VALID_PERCENT_OF_ANALYSIS",
        ]
        result_columns = [
            "_mahdoude_key",
            "_aquifer_key",
            "JALALI_YEAR",
            *value_columns,
        ]
        if not path.exists():
            return pd.DataFrame(columns=result_columns)

        frame = pd.read_csv(path, encoding="utf-8-sig")
        required = {"MAHDOUDE", "AQUIFER", "JALALI_YEAR", *value_columns}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(
                "ستون‌های فایل مساحت کشت آبی کامل نیستند: "
                f"{', '.join(sorted(missing))}"
            )

        frame["JALALI_YEAR"] = pd.to_numeric(
            frame["JALALI_YEAR"],
            errors="coerce",
        )
        for column in value_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(
            subset=["MAHDOUDE", "AQUIFER", "JALALI_YEAR"]
        ).copy()
        frame = frame[
            (
                frame[
                    [
                        "PROBABLE_IRRIGATED_AREA_HA",
                        "ANALYSIS_MASK_AREA_HA",
                        "VALID_OBSERVATION_AREA_HA",
                    ]
                ].isna()
                | frame[
                    [
                        "PROBABLE_IRRIGATED_AREA_HA",
                        "ANALYSIS_MASK_AREA_HA",
                        "VALID_OBSERVATION_AREA_HA",
                    ]
                ].ge(0)
            ).all(axis=1)
        ].copy()
        frame["JALALI_YEAR"] = frame["JALALI_YEAR"].astype(int)
        frame["_mahdoude_key"] = frame["MAHDOUDE"].map(normalize_name)
        frame["_aquifer_key"] = frame["AQUIFER"].map(normalize_name)
        return (
            frame.groupby(
                ["_mahdoude_key", "_aquifer_key", "JALALI_YEAR"],
                as_index=False,
            )[value_columns]
            .mean()
            .sort_values(
                ["_mahdoude_key", "_aquifer_key", "JALALI_YEAR"]
            )
        )

    def _station_mahdoude_name(self, point: Point) -> str | None:
        matches = [
            feature.properties.get("MAHDOUDE", "")
            for feature in self.mahdoude_features
            if feature.geometry.covers(point)
        ]
        return matches[0] if matches else None

    def _precipitation_station_metadata(self) -> pd.DataFrame:
        stations = (
            self.precipitation.groupby("station_id", as_index=False)
            .agg(
                station_name=("station_name", "first"),
                lat=("lat", "mean"),
                lon=("lon", "mean"),
                elev=("elev", "mean"),
            )
        )
        stations["_point"] = [
            Point(float(lon), float(lat))
            for lon, lat in zip(stations["lon"], stations["lat"])
        ]
        stations["_mahdoude"] = [
            self._station_mahdoude_name(point)
            for point in stations["_point"]
        ]
        return stations.reset_index(drop=True)

    def _select_precipitation_stations(
        self,
        group_id: str,
    ) -> dict[str, Any]:
        boundary = self.boundary_matches[group_id]["mahdoude"].geometry
        stations = self.precipitation_stations.copy()
        inside_mask = stations["_point"].map(boundary.covers)
        if inside_mask.any():
            selected = stations[inside_mask].copy()
            selected["_distance_km"] = 0.0
            method = "inside_mahdoude"
            method_label = "میانگین ایستگاه‌های داخل محدوده"
        else:
            longitude = float(boundary.centroid.x)
            latitude = float(boundary.centroid.y)
            projected_crs = f"EPSG:{self._utm_epsg(longitude, latitude)}"
            forward = Transformer.from_crs(
                "EPSG:4326",
                projected_crs,
                always_xy=True,
            )
            projected_boundary = transform(forward.transform, boundary)
            stations["_distance_km"] = stations["_point"].map(
                lambda point: projected_boundary.distance(
                    Point(*forward.transform(point.x, point.y))
                )
                / 1000
            )
            station_count = min(
                NEAREST_PRECIPITATION_STATION_COUNT,
                len(stations),
            )
            selected = stations.nsmallest(station_count, "_distance_km").copy()
            method = "nearest_available"
            method_label = (
                f"میانگین {station_count} ایستگاه نزدیک محدوده‌های مجاور"
            )
        selected = selected.sort_values(["_distance_km", "station_name"])
        return {
            "method": method,
            "method_label": method_label,
            "station_ids": selected["station_id"].tolist(),
            "stations": [
                {
                    "id": row["station_id"],
                    "name": row["station_name"],
                    "latitude": finite_or_none(row["lat"], 6),
                    "longitude": finite_or_none(row["lon"], 6),
                    "elevation": finite_or_none(row["elev"]),
                    "mahdoude": row["_mahdoude"],
                    "distance_km": finite_or_none(row["_distance_km"], 1),
                }
                for row in selected.to_dict("records")
            ],
        }

    def _precipitation_payload(
        self,
        group_id: str,
        months: list[tuple[int, str]],
    ) -> dict[str, Any]:
        selection = self.precipitation_selections[group_id]
        selected = self.precipitation[
            self.precipitation["station_id"].isin(selection["station_ids"])
        ]
        monthly_values = selected.groupby("_month_index")["precip"].mean().to_dict()
        stations = []
        for station in selection["stations"]:
            station_values = (
                selected[selected["station_id"] == station["id"]]
                .groupby("_month_index")["precip"]
                .mean()
                .to_dict()
            )
            stations.append({
                **station,
                "series": [
                    [label, finite_or_none(station_values.get(index))]
                    for index, label in months
                ],
            })
        return {
            "unit": "میلی‌متر در ماه",
            "method": selection["method"],
            "method_label": selection["method_label"],
            "station_count": len(selection["station_ids"]),
            "stations": stations,
            "series": [
                [label, finite_or_none(monthly_values.get(index))]
                for index, label in months
            ],
        }

    def _ndvi_payload(
        self,
        group_id: str,
        months: list[tuple[int, str]],
    ) -> dict[str, Any]:
        properties = self.boundary_matches[group_id]["aquifer"].properties
        mahdoude_key = normalize_name(properties.get("MAHDOUDE", ""))
        aquifer_key = normalize_name(properties.get("AQUIFER", ""))
        selected = self.ndvi[
            (self.ndvi["_mahdoude_key"] == mahdoude_key)
            & (self.ndvi["_aquifer_key"] == aquifer_key)
        ].set_index("_month_index")
        metric_columns = {
            "mean": "NDVI_MEAN",
            "median": "NDVI_MEDIAN",
            "max": "NDVI_MAX",
        }
        return {
            "unit": "NDVI",
            "default_metric": "median",
            "metrics": {
                metric: [
                    [
                        label,
                        finite_or_none(
                            selected.at[index, column]
                            if index in selected.index
                            else None,
                            4,
                        ),
                    ]
                    for index, label in months
                ]
                for metric, column in metric_columns.items()
            },
        }

    def _aet_payload(
        self,
        group_id: str,
        months: list[tuple[int, str]],
    ) -> dict[str, Any]:
        properties = self.boundary_matches[group_id]["aquifer"].properties
        mahdoude_key = normalize_name(properties.get("MAHDOUDE", ""))
        aquifer_key = normalize_name(properties.get("AQUIFER", ""))
        selected = self.aet[
            (self.aet["_mahdoude_key"] == mahdoude_key)
            & (self.aet["_aquifer_key"] == aquifer_key)
        ].set_index("_month_index")
        return {
            "unit": "میلی‌متر در ماه",
            "series": [
                [
                    label,
                    finite_or_none(
                        selected.at[index, "AET"]
                        if index in selected.index
                        else None,
                        2,
                    ),
                ]
                for index, label in months
            ],
        }

    def _warm_season_irrigated_area_payload(
        self,
        group_id: str,
    ) -> dict[int, dict[str, float | bool | None]]:
        properties = self.boundary_matches[group_id]["aquifer"].properties
        mahdoude_key = normalize_name(properties.get("MAHDOUDE", ""))
        aquifer_key = normalize_name(properties.get("AQUIFER", ""))
        selected = self.warm_season_irrigated_area[
            (
                self.warm_season_irrigated_area["_mahdoude_key"]
                == mahdoude_key
            )
            & (
                self.warm_season_irrigated_area["_aquifer_key"]
                == aquifer_key
            )
        ]
        result: dict[int, dict[str, float | bool | None]] = {}
        for row in selected.itertuples(index=False):
            valid_observation_area = finite_or_none(
                row.VALID_OBSERVATION_AREA_HA,
                2,
            )
            has_valid_observations = (
                valid_observation_area is not None
                and valid_observation_area > 0
            )
            result[int(row.JALALI_YEAR)] = {
                "probable_area_ha": (
                    finite_or_none(row.PROBABLE_IRRIGATED_AREA_HA, 2)
                    if has_valid_observations
                    else None
                ),
                "analysis_area_ha": finite_or_none(
                    row.ANALYSIS_MASK_AREA_HA,
                    2,
                ),
                "valid_observation_area_ha": valid_observation_area,
                "probable_percent": (
                    finite_or_none(
                        row.PROBABLE_PERCENT_OF_ANALYSIS,
                        2,
                    )
                    if has_valid_observations
                    else None
                ),
                "valid_percent": finite_or_none(
                    row.VALID_PERCENT_OF_ANALYSIS,
                    2,
                ),
                "has_valid_observations": has_valid_observations,
            }
        return result

    def _build_groups(self) -> dict[str, dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for group_id, frame in self.locations.groupby("_aquifer_id", sort=False):
            first = frame.iloc[0]
            groups[group_id] = {
                "id": group_id,
                "mahdoude": first["MAHDOUDE"],
                "mahdoude_key": first["_mahdoude_key"],
                "aquifer": first["AQUIFER"],
                "aquifer_key": first["_aquifer_key"],
                "well_count": int(len(frame)),
            }
        return groups

    @staticmethod
    def _boundary_score(
        points: list[Point],
        center: Point,
        feature: BoundaryFeature,
        mahdoude_key: str,
        aquifer_key: str | None,
    ) -> tuple[float, ...]:
        geometry = feature.geometry
        raw = sum(geometry.covers(point) for point in points)
        nearby = sum(geometry.distance(point) <= 0.015 for point in points)
        feature_mahdoude = normalize_name(feature.properties.get("MAHDOUDE", ""))
        feature_aquifer = normalize_name(feature.properties.get("AQUIFER", ""))
        aquifer_match = int(aquifer_key is not None and feature_aquifer == aquifer_key)
        mahdoude_match = int(feature_mahdoude == mahdoude_key)
        return (
            float(raw),
            float(nearby),
            float(aquifer_match),
            float(mahdoude_match),
            -float(geometry.distance(center)),
        )

    def _best_boundary(
        self,
        frame: pd.DataFrame,
        features: list[BoundaryFeature],
        aquifer: bool,
    ) -> BoundaryFeature:
        points = [Point(x, y) for x, y in zip(frame["X"], frame["Y"])]
        center = MultiPoint(points).centroid
        first = frame.iloc[0]
        mahdoude_key = first["_mahdoude_key"]
        aquifer_key = first["_aquifer_key"] if aquifer else None
        exact = [
            feature
            for feature in features
            if normalize_name(feature.properties.get("MAHDOUDE", "")) == mahdoude_key
            and (
                not aquifer
                or normalize_name(feature.properties.get("AQUIFER", "")) == aquifer_key
            )
        ]
        if exact:
            return max(
                exact,
                key=lambda feature: sum(feature.geometry.covers(point) for point in points),
            )

        same_mahdoude = [
            feature
            for feature in features
            if normalize_name(feature.properties.get("MAHDOUDE", "")) == mahdoude_key
        ]
        candidates = same_mahdoude or features
        return max(
            candidates,
            key=lambda feature: self._boundary_score(
                points,
                center,
                feature,
                mahdoude_key,
                aquifer_key,
            ),
        )

    def _match_boundaries(self) -> dict[str, dict[str, BoundaryFeature]]:
        matches: dict[str, dict[str, BoundaryFeature]] = {}
        for group_id, frame in self.locations.groupby("_aquifer_id", sort=False):
            matches[group_id] = {
                "aquifer": self._best_boundary(frame, self.aquifer_features, aquifer=True),
                "mahdoude": self._best_boundary(frame, self.mahdoude_features, aquifer=False),
            }
        return matches

    @staticmethod
    def _utm_epsg(longitude: float, latitude: float) -> int:
        zone = int((longitude + 180) // 6) + 1
        return (32600 if latitude >= 0 else 32700) + zone

    def _calculate_thiessen(
        self,
        group_id: str,
        sites: pd.DataFrame,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        boundary = self.boundary_matches[group_id]["aquifer"].geometry
        if sites.empty:
            return {}, {"type": "FeatureCollection", "features": []}

        sites = sites.sort_values("_site_key").reset_index(drop=True)
        if len(sites) == 1:
            site = sites.iloc[0]
            weights = {site["_site_key"]: 1.0}
            feature = {
                "type": "Feature",
                "properties": {
                    "site_key": site["_site_key"],
                    "weight": 1.0,
                    "well_names": site["well_names"],
                },
                "geometry": mapping(boundary),
            }
            return weights, {"type": "FeatureCollection", "features": [feature]}

        longitude = float(sites["X"].mean())
        latitude = float(sites["Y"].mean())
        projected_crs = f"EPSG:{self._utm_epsg(longitude, latitude)}"
        forward = Transformer.from_crs(
            "EPSG:4326", projected_crs, always_xy=True
        )
        inverse = Transformer.from_crs(
            projected_crs, "EPSG:4326", always_xy=True
        )
        projected_boundary = transform(forward.transform, boundary)
        projected_points = [
            Point(*forward.transform(float(row.X), float(row.Y)))
            for row in sites.itertuples()
        ]

        cells = voronoi_polygons(
            MultiPoint(projected_points),
            extend_to=projected_boundary.envelope,
            ordered=True,
        )
        areas = np.array(
            [max(cell.intersection(projected_boundary).area, 0.0) for cell in cells.geoms],
            dtype=float,
        )
        if not np.isfinite(areas).all() or areas.sum() <= 0:
            areas = np.ones(len(sites), dtype=float)
        weights = areas / areas.sum()
        weight_map = dict(zip(sites["_site_key"], weights.astype(float)))
        features = []
        for index, cell in enumerate(cells.geoms):
            clipped = cell.intersection(projected_boundary)
            if clipped.is_empty:
                continue
            site = sites.iloc[index]
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "site_key": site["_site_key"],
                        "weight": finite_or_none(weights[index], 6),
                        "well_names": site["well_names"],
                    },
                    "geometry": mapping(transform(inverse.transform, clipped)),
                }
            )
        return weight_map, {"type": "FeatureCollection", "features": features}

    def _projected_boundary(
        self,
        group_id: str,
        sites: pd.DataFrame,
    ) -> tuple[Any, Transformer]:
        boundary = self.boundary_matches[group_id]["aquifer"].geometry
        if sites.empty:
            centroid = boundary.centroid
            longitude = float(centroid.x)
            latitude = float(centroid.y)
        else:
            longitude = float(sites["X"].mean())
            latitude = float(sites["Y"].mean())
        projected_crs = f"EPSG:{self._utm_epsg(longitude, latitude)}"
        forward = Transformer.from_crs(
            "EPSG:4326", projected_crs, always_xy=True
        )
        return transform(forward.transform, boundary), forward

    @staticmethod
    def _surface_sample_cells(projected_boundary: Any) -> tuple[np.ndarray, np.ndarray]:
        minx, miny, maxx, maxy = projected_boundary.bounds
        width = max(maxx - minx, 1.0)
        height = max(maxy - miny, 1.0)
        aspect = width / height
        columns = max(8, int(round(PIEZOMETRIC_SURFACE_GRID_SIZE * np.sqrt(aspect))))
        rows = max(8, int(round(PIEZOMETRIC_SURFACE_GRID_SIZE / np.sqrt(aspect))))
        dx = width / columns
        dy = height / rows
        points: list[tuple[float, float]] = []
        weights: list[float] = []
        for row in range(rows):
            y0 = miny + row * dy
            for column in range(columns):
                x0 = minx + column * dx
                cell = box(x0, y0, x0 + dx, y0 + dy)
                intersection_area = cell.intersection(projected_boundary).area
                if intersection_area <= 0:
                    continue
                points.append((x0 + dx / 2, y0 + dy / 2))
                weights.append(float(intersection_area))
        if not points:
            representative = projected_boundary.representative_point()
            points = [(float(representative.x), float(representative.y))]
            weights = [float(projected_boundary.area)]
        return np.array(points, dtype=float), np.array(weights, dtype=float)

    @staticmethod
    def _idw_values(
        samples_xy: np.ndarray,
        point_xy: np.ndarray,
        point_values: np.ndarray,
    ) -> np.ndarray:
        if len(point_values) == 1:
            return np.full(len(samples_xy), float(point_values[0]), dtype=float)
        dx = samples_xy[:, None, 0] - point_xy[None, :, 0]
        dy = samples_xy[:, None, 1] - point_xy[None, :, 1]
        distance_squared = dx * dx + dy * dy
        exact = distance_squared <= 1e-12
        weights = 1.0 / np.maximum(distance_squared, 1e-12) ** (IDW_POWER / 2)
        interpolated = (weights @ point_values) / weights.sum(axis=1)
        exact_rows = exact.any(axis=1)
        if exact_rows.any():
            exact_columns = exact[exact_rows].argmax(axis=1)
            interpolated[exact_rows] = point_values[exact_columns]
        return interpolated

    @staticmethod
    def _spherical_variogram(
        distances: np.ndarray,
        nugget: float,
        sill: float,
        variogram_range: float,
    ) -> np.ndarray:
        distances = np.asarray(distances, dtype=float)
        safe_range = max(float(variogram_range), 1e-9)
        ratio = np.clip(distances / safe_range, 0.0, 1.0)
        structure = np.where(
            distances < safe_range,
            1.5 * ratio - 0.5 * ratio**3,
            1.0,
        )
        return float(nugget) + float(sill) * structure

    @classmethod
    def _fit_spherical_variogram(
        cls,
        point_xy: np.ndarray,
        point_values: np.ndarray,
    ) -> tuple[float, float, float] | None:
        if len(point_values) < 3 or np.nanstd(point_values) <= 1e-9:
            return None
        dx = point_xy[:, None, 0] - point_xy[None, :, 0]
        dy = point_xy[:, None, 1] - point_xy[None, :, 1]
        distances = np.sqrt(dx * dx + dy * dy)
        value_diff = point_values[:, None] - point_values[None, :]
        semivariances = 0.5 * value_diff * value_diff
        upper = np.triu_indices(len(point_values), k=1)
        h = distances[upper]
        gamma = semivariances[upper]
        valid = np.isfinite(h) & np.isfinite(gamma) & (h > 0)
        h = h[valid]
        gamma = gamma[valid]
        if len(h) < 3 or np.nanmax(h) <= 0:
            return None
        max_distance = float(np.nanmax(h))
        max_gamma = float(max(np.nanmax(gamma), np.nanvar(point_values), 1e-9))
        try:
            parameters, _ = curve_fit(
                cls._spherical_variogram,
                h,
                gamma,
                p0=(0.0, max_gamma, max_distance / 2),
                bounds=(
                    (0.0, 1e-12, max_distance * 0.05),
                    (max_gamma, max_gamma * 5, max_distance * 3),
                ),
                maxfev=5000,
            )
        except (RuntimeError, ValueError, FloatingPointError):
            return None
        nugget, sill, variogram_range = (float(value) for value in parameters)
        if not all(np.isfinite([nugget, sill, variogram_range])):
            return None
        return nugget, sill, variogram_range

    @classmethod
    def _ordinary_kriging_values(
        cls,
        samples_xy: np.ndarray,
        point_xy: np.ndarray,
        point_values: np.ndarray,
    ) -> np.ndarray | None:
        parameters = cls._fit_spherical_variogram(point_xy, point_values)
        if parameters is None:
            return None
        n_points = len(point_values)
        dx = point_xy[:, None, 0] - point_xy[None, :, 0]
        dy = point_xy[:, None, 1] - point_xy[None, :, 1]
        point_distances = np.sqrt(dx * dx + dy * dy)
        gamma_matrix = cls._spherical_variogram(point_distances, *parameters)
        np.fill_diagonal(gamma_matrix, 0.0)

        system = np.empty((n_points + 1, n_points + 1), dtype=float)
        system[:n_points, :n_points] = gamma_matrix
        system[:n_points, n_points] = 1.0
        system[n_points, :n_points] = 1.0
        system[n_points, n_points] = 0.0

        dx0 = point_xy[:, None, 0] - samples_xy[None, :, 0]
        dy0 = point_xy[:, None, 1] - samples_xy[None, :, 1]
        sample_distances = np.sqrt(dx0 * dx0 + dy0 * dy0)
        rhs = np.vstack(
            [
                cls._spherical_variogram(sample_distances, *parameters),
                np.ones(len(samples_xy), dtype=float),
            ]
        )
        try:
            solution = np.linalg.solve(system, rhs)
        except np.linalg.LinAlgError:
            try:
                solution = np.linalg.lstsq(system, rhs, rcond=None)[0]
            except np.linalg.LinAlgError:
                return None
        interpolated = point_values @ solution[:n_points, :]
        return interpolated.astype(float)

    @staticmethod
    def _natural_neighbor_values(
        samples_xy: np.ndarray,
        point_xy: np.ndarray,
        point_values: np.ndarray,
    ) -> np.ndarray | None:
        if len(point_values) < 3:
            return None
        try:
            linear = LinearNDInterpolator(point_xy, point_values, fill_value=np.nan)
            nearest = NearestNDInterpolator(point_xy, point_values)
            interpolated = np.asarray(linear(samples_xy), dtype=float)
            missing = ~np.isfinite(interpolated)
            if missing.any():
                interpolated[missing] = np.asarray(nearest(samples_xy[missing]), dtype=float)
        except (ValueError, np.linalg.LinAlgError):
            return None
        return interpolated

    @staticmethod
    def _trend_feature_matrix(point_xy: np.ndarray, degree: str) -> np.ndarray:
        x = point_xy[:, 0].astype(float)
        y = point_xy[:, 1].astype(float)
        if degree == "quadratic":
            return np.column_stack([np.ones(len(point_xy)), x, y, x * y, x * x, y * y])
        return np.column_stack([np.ones(len(point_xy)), x, y])

    @classmethod
    def _trend_kriging_values(
        cls,
        samples_xy: np.ndarray,
        point_xy: np.ndarray,
        point_values: np.ndarray,
        degree: str,
    ) -> np.ndarray | None:
        if len(point_values) < 4:
            return None
        point_features = cls._trend_feature_matrix(point_xy, degree)
        try:
            coefficients, *_ = np.linalg.lstsq(point_features, point_values, rcond=None)
        except np.linalg.LinAlgError:
            return None
        residuals = point_values - point_features @ coefficients
        residual_surface = cls._ordinary_kriging_values(samples_xy, point_xy, residuals)
        if residual_surface is None:
            return None
        sample_features = cls._trend_feature_matrix(samples_xy, degree)
        trend_surface = sample_features @ coefficients
        return np.asarray(trend_surface + residual_surface, dtype=float)

    @classmethod
    def _universal_kriging_values(
        cls,
        samples_xy: np.ndarray,
        point_xy: np.ndarray,
        point_values: np.ndarray,
    ) -> np.ndarray | None:
        return cls._trend_kriging_values(
            samples_xy,
            point_xy,
            point_values,
            "linear",
        )

    @classmethod
    def _regression_kriging_values(
        cls,
        samples_xy: np.ndarray,
        point_xy: np.ndarray,
        point_values: np.ndarray,
    ) -> np.ndarray | None:
        return cls._trend_kriging_values(
            samples_xy,
            point_xy,
            point_values,
            "quadratic",
        )

    @staticmethod
    def _spline_values(
        samples_xy: np.ndarray,
        point_xy: np.ndarray,
        point_values: np.ndarray,
    ) -> np.ndarray | None:
        if len(point_values) < 3:
            return None
        smoothing = max(float(np.nanstd(point_values)) * 0.01, 0.0)
        try:
            interpolator = RBFInterpolator(
                point_xy,
                point_values,
                kernel="thin_plate_spline",
                smoothing=smoothing,
            )
            interpolated = interpolator(samples_xy)
        except (ValueError, np.linalg.LinAlgError):
            return None
        return np.asarray(interpolated, dtype=float)

    @classmethod
    def _surface_interpolation_values(
        cls,
        method: str,
        samples_xy: np.ndarray,
        point_xy: np.ndarray,
        point_values: np.ndarray,
    ) -> tuple[np.ndarray, str]:
        if len(point_values) <= 1 or method == "idw":
            return cls._idw_values(samples_xy, point_xy, point_values), "idw"
        if method == "natural_neighbor":
            natural_neighbor_values = cls._natural_neighbor_values(
                samples_xy,
                point_xy,
                point_values,
            )
            if natural_neighbor_values is not None and np.isfinite(natural_neighbor_values).all():
                return natural_neighbor_values, "natural_neighbor"
            return cls._idw_values(samples_xy, point_xy, point_values), "idw"
        if method == "ordinary_kriging":
            kriging_values = cls._ordinary_kriging_values(
                samples_xy,
                point_xy,
                point_values,
            )
            if kriging_values is not None and np.isfinite(kriging_values).all():
                return kriging_values, "ordinary_kriging"
            return cls._idw_values(samples_xy, point_xy, point_values), "idw"
        if method == "universal_kriging":
            kriging_values = cls._universal_kriging_values(
                samples_xy,
                point_xy,
                point_values,
            )
            if kriging_values is not None and np.isfinite(kriging_values).all():
                return kriging_values, "universal_kriging"
            return cls._idw_values(samples_xy, point_xy, point_values), "idw"
        if method == "regression_kriging":
            kriging_values = cls._regression_kriging_values(
                samples_xy,
                point_xy,
                point_values,
            )
            if kriging_values is not None and np.isfinite(kriging_values).all():
                return kriging_values, "regression_kriging"
            return cls._idw_values(samples_xy, point_xy, point_values), "idw"
        if method == "spline":
            spline_values = cls._spline_values(samples_xy, point_xy, point_values)
            if spline_values is not None and np.isfinite(spline_values).all():
                return spline_values, "spline"
        return cls._idw_values(samples_xy, point_xy, point_values), "idw"

    @staticmethod
    def _surface_method_metadata(method: str) -> dict[str, str]:
        label = SURFACE_INTERPOLATION_LABELS.get(
            method,
            SURFACE_INTERPOLATION_LABELS["idw"],
        )
        return {
            "method": method,
            "method_label": f"میانگین مساحتی سطح پیزومتریک ماهانه ({label})",
            "short_label": f"سطح پیزومتریک {label}",
        }

    @staticmethod
    def _normalize_surface_methods(
        methods: list[str] | None,
        primary_method: str | None = None,
    ) -> list[str]:
        requested = []
        if primary_method:
            requested.append(primary_method)
        requested.extend(methods or [])
        normalized: list[str] = []
        for method in requested:
            if method in SURFACE_INTERPOLATION_METHODS and method not in normalized:
                normalized.append(method)
        if "idw" not in normalized:
            normalized.append("idw")
        if not normalized:
            normalized = ["idw"]
        ordered_remaining = [
            method
            for method in SURFACE_INTERPOLATION_METHOD_ORDER
            if method in normalized
        ]
        return [
            method
            for method in normalized
            if method in ordered_remaining
        ]

    @staticmethod
    def _series_from_values(
        months: list[tuple[int, str]],
        values: dict[int, float],
    ) -> list[list[Any]]:
        month_labels = dict(months)
        return [
            [month_labels[index], finite_or_none(values.get(index))]
            for index, _ in months
        ]

    @staticmethod
    def _apply_storage_to_annual_rows(
        rows: list[dict[str, Any]],
        storage_coefficient: float | None,
        aquifer_area_m2: float | None,
    ) -> list[dict[str, Any]]:
        can_calculate_storage = (
            storage_coefficient is not None
            and aquifer_area_m2 is not None
            and np.isfinite(storage_coefficient)
            and np.isfinite(aquifer_area_m2)
        )

        def with_storage(row: dict[str, Any]) -> dict[str, Any]:
            result = dict(row)
            decline = result.get("decline")
            cumulative_decline = result.get("cumulative_decline")
            result["storage_change_mcm"] = (
                finite_or_none(
                    float(decline) * float(storage_coefficient) * float(aquifer_area_m2)
                    / 1_000_000,
                    3,
                )
                if can_calculate_storage
                and decline is not None
                and np.isfinite(decline)
                else None
            )
            result["cumulative_storage_change_mcm"] = (
                finite_or_none(
                    float(cumulative_decline)
                    * float(storage_coefficient)
                    * float(aquifer_area_m2)
                    / 1_000_000,
                    3,
                )
                if can_calculate_storage
                and cumulative_decline is not None
                and np.isfinite(cumulative_decline)
                else None
            )
            return result

        return [with_storage(row) for row in rows]

    def _piezometric_surface_value_map(
        self,
        group_id: str,
        frame: pd.DataFrame,
        selected_sites: pd.DataFrame,
        interpolation_method: str,
    ) -> tuple[dict[int, float], dict[str, Any]]:
        values: dict[int, float] = {}
        boundary_area_m2 = None
        metadata = self._surface_method_metadata(interpolation_method)
        if frame.empty or selected_sites.empty:
            return values, {
                **metadata,
                "grid_size": PIEZOMETRIC_SURFACE_GRID_SIZE,
                "area_m2": None,
                "area_km2": None,
                "fallback_month_count": 0,
            }

        projected_boundary, forward = self._projected_boundary(group_id, selected_sites)
        boundary_area_m2 = float(projected_boundary.area)
        samples_xy, sample_weights = self._surface_sample_cells(projected_boundary)
        projected_sites = selected_sites.copy()
        projected_coordinates = [
            forward.transform(float(row.X), float(row.Y))
            for row in projected_sites.itertuples()
        ]
        projected_sites["_px"] = [coordinate[0] for coordinate in projected_coordinates]
        projected_sites["_py"] = [coordinate[1] for coordinate in projected_coordinates]
        site_coordinates = projected_sites.set_index("_site_key")[["_px", "_py"]]
        site_month = (
            frame.groupby(["_month_index", "_site_key"], as_index=False)
            .agg(level=("level", "mean"))
            .join(site_coordinates, on="_site_key", how="inner")
            .dropna(subset=["level", "_px", "_py"])
        )
        for month_index, month_frame in site_month.groupby("_month_index", sort=True):
            point_xy = month_frame[["_px", "_py"]].to_numpy(dtype=float)
            point_values = month_frame["level"].to_numpy(dtype=float)
            if not len(point_values):
                continue
            interpolated, actual_method = self._surface_interpolation_values(
                interpolation_method,
                samples_xy,
                point_xy,
                point_values,
            )
            if actual_method != interpolation_method:
                metadata["fallback_month_count"] = str(
                    int(metadata.get("fallback_month_count", "0")) + 1
                )
            values[int(month_index)] = float(
                np.average(interpolated, weights=sample_weights)
            )
        return values, {
            **metadata,
            "grid_size": PIEZOMETRIC_SURFACE_GRID_SIZE,
            "area_m2": finite_or_none(boundary_area_m2, 2),
            "area_km2": finite_or_none(boundary_area_m2 / 1_000_000, 3),
            "fallback_method": "idw",
            "fallback_month_count": int(metadata.get("fallback_month_count", "0")),
        }

    @staticmethod
    def _regional_prediction(
        regional_values: dict[int, float],
        month_index: int,
    ) -> float | None:
        if month_index in regional_values and np.isfinite(regional_values[month_index]):
            return float(regional_values[month_index])
        valid = sorted(
            (int(index), float(value))
            for index, value in regional_values.items()
            if value is not None and np.isfinite(value)
        )
        if not valid:
            return None
        if len(valid) == 1:
            return valid[0][1]
        x = np.array([item[0] for item in valid], dtype=float)
        y = np.array([item[1] for item in valid], dtype=float)
        return float(np.interp(float(month_index), x, y))

    @staticmethod
    def _status_count_row(
        month_label: str,
        frame: pd.DataFrame,
    ) -> dict[str, Any]:
        status_counts = frame["status"].value_counts().to_dict()
        imputed_count = int(frame["is_imputed"].sum()) if "is_imputed" in frame else 0
        return {
            "date": month_label,
            "measured_count": int(status_counts.get("measured", 0)),
            "missing_count": int(status_counts.get("missing", 0)),
            "out_of_range_count": int(
                status_counts.get("out_of_range_censored", 0)
            ),
            "retired_count": int(
                status_counts.get("retired_no_longer_measurable", 0)
            ),
            "new_well_count": int(status_counts.get("new_well_added", 0)),
            "imputed_count": imputed_count,
        }

    def _corrected_well_month_frame(
        self,
        group_id: str,
        months: list[tuple[int, str]],
        manual_selection: bool,
        selected_join_keys: set[str],
    ) -> tuple[pd.DataFrame, set[str], list[dict[str, Any]]]:
        group_monthly = self.monthly[self.monthly["_aquifer_id"] == group_id]
        locations = self.locations[self.locations["_aquifer_id"] == group_id]
        if manual_selection:
            group_monthly = group_monthly[
                group_monthly["_join_key"].isin(selected_join_keys)
            ]
            locations = locations[
                locations["_join_key"].isin(selected_join_keys)
            ]
        month_indexes = [index for index, _ in months]
        month_labels = dict(months)
        start_index = month_indexes[0]
        end_index = month_indexes[-1]
        regional_values = group_monthly.groupby("_month_index")["level"].mean().to_dict()
        history_by_key = {
            key: dict(
                frame.sort_values("_month_index")[
                    ["_month_index", "level"]
                ].itertuples(index=False, name=None)
            )
            for key, frame in group_monthly.groupby("_join_key", sort=False)
        }

        support_join_keys: set[str] = set()
        well_offsets: dict[str, float] = {}
        well_limits: dict[str, float] = {}
        well_first_last: dict[str, tuple[int, int]] = {}
        for join_key, values in history_by_key.items():
            valid_indexes = sorted(
                int(index)
                for index, value in values.items()
                if value is not None and np.isfinite(value)
            )
            if not valid_indexes:
                continue
            first_index = valid_indexes[0]
            last_index = valid_indexes[-1]
            well_first_last[join_key] = (first_index, last_index)
            well_limits[join_key] = float(values[last_index])
            residuals = []
            for index in valid_indexes:
                regional = self._regional_prediction(regional_values, index)
                if regional is not None and np.isfinite(regional):
                    residuals.append(float(values[index]) - regional)
            well_offsets[join_key] = float(np.mean(residuals)) if residuals else 0.0
            if first_index <= start_index:
                support_join_keys.add(join_key)

        if manual_selection:
            support_join_keys &= selected_join_keys
        if not support_join_keys:
            fallback_keys = {
                key
                for key, (first_index, _) in well_first_last.items()
                if first_index <= end_index
            }
            support_join_keys = fallback_keys & selected_join_keys if manual_selection else fallback_keys

        rows: list[dict[str, Any]] = []
        transitions: list[dict[str, Any]] = []
        for _, location in locations.iterrows():
            join_key = location["_join_key"]
            values = history_by_key.get(join_key, {})
            first_last = well_first_last.get(join_key)
            first_index = first_last[0] if first_last else None
            last_index = first_last[1] if first_last else None
            measurement_limit = well_limits.get(join_key)
            offset = well_offsets.get(join_key, 0.0)
            on_fixed_support = join_key in support_join_keys

            if first_index is not None and start_index <= first_index <= end_index:
                transitions.append(
                    {
                        "date": month_labels[first_index],
                        "well_id": location["_well_id"],
                        "event_type": "new_well_added",
                        "old_status": "inactive",
                        "new_status": "new_well_added",
                        "possible_replacement_well": None,
                        "estimated_offset": finite_or_none(offset, 3),
                    }
                )
            if last_index is not None and last_index < end_index:
                retired_index = max(last_index + 1, start_index)
                if retired_index <= end_index:
                    transitions.append(
                        {
                            "date": month_labels[retired_index],
                            "well_id": location["_well_id"],
                            "event_type": "retired_no_longer_measurable",
                            "old_status": "measured",
                            "new_status": "retired_no_longer_measurable",
                            "possible_replacement_well": None,
                            "estimated_offset": finite_or_none(offset, 3),
                        }
                    )

            for month_index, month_label in months:
                observed = values.get(month_index)
                observed_valid = observed is not None and np.isfinite(observed)
                status = "inactive"
                corrected_value: float | None = None
                is_imputed = False
                uncertainty: float | None = None
                row_limit = None

                if observed_valid:
                    corrected_value = float(observed)
                    status = (
                        "new_well_added"
                        if first_index == month_index and month_index > start_index
                        else "measured"
                    )
                elif first_index is None or month_index < first_index:
                    status = "inactive"
                else:
                    regional = self._regional_prediction(regional_values, month_index)
                    prediction = (
                        regional + offset
                        if regional is not None and np.isfinite(regional)
                        else None
                    )
                    if last_index is not None and month_index > last_index:
                        status = "retired_no_longer_measurable"
                        row_limit = measurement_limit
                        if prediction is not None:
                            corrected_value = (
                                min(float(prediction), float(measurement_limit))
                                if measurement_limit is not None
                                else float(prediction)
                            )
                            is_imputed = True
                    else:
                        status = "imputed" if prediction is not None else "missing"
                        if prediction is not None:
                            corrected_value = float(prediction)
                            is_imputed = True

                    if corrected_value is not None and regional is not None:
                        uncertainty = abs(float(corrected_value) - float(regional))

                rows.append(
                    {
                        "_aquifer_id": group_id,
                        "_join_key": join_key,
                        "_well_id": location["_well_id"],
                        "_site_key": location["_site_key"],
                        "_month_index": month_index,
                        "_month": month_label,
                        "observed_value": float(observed) if observed_valid else np.nan,
                        "corrected_value": corrected_value,
                        "level": corrected_value,
                        "status": status,
                        "measurement_limit": row_limit,
                        "is_measured": status == "measured",
                        "is_out_of_range": status == "out_of_range_censored",
                        "is_retired": status == "retired_no_longer_measurable",
                        "is_new_well": status == "new_well_added",
                        "is_imputed": is_imputed,
                        "on_fixed_support": on_fixed_support,
                        "uncertainty": uncertainty,
                    }
                )

        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame, support_join_keys, transitions
        frame = frame.sort_values(["_month_index", "_join_key"]).reset_index(drop=True)
        return frame, support_join_keys, sorted(
            transitions,
            key=lambda item: (item["date"], item["well_id"], item["event_type"]),
        )

    @staticmethod
    def _corrected_well_month_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        records = []
        for row in frame.to_dict("records"):
            records.append(
                {
                    "well_id": row["_well_id"],
                    "date": row["_month"],
                    "observed_value": finite_or_none(row["observed_value"]),
                    "corrected_value": finite_or_none(row["corrected_value"]),
                    "status": row["status"],
                    "measurement_limit": finite_or_none(row["measurement_limit"]),
                    "is_measured": bool(row["is_measured"]),
                    "is_out_of_range": bool(row["is_out_of_range"]),
                    "is_retired": bool(row["is_retired"]),
                    "is_new_well": bool(row["is_new_well"]),
                    "is_imputed": bool(row["is_imputed"]),
                    "uncertainty": finite_or_none(row["uncertainty"]),
                }
            )
        return records

    def _corrected_validation(
        self,
        months: list[tuple[int, str]],
        raw_values: dict[int, float],
        corrected_values: dict[int, float],
        corrected_well_month: pd.DataFrame,
        network_transitions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        retired_rows = corrected_well_month[
            corrected_well_month["status"] == "retired_no_longer_measurable"
        ]
        retired_limit_violations = int(
            (
                retired_rows["corrected_value"].notna()
                & retired_rows["measurement_limit"].notna()
                & (retired_rows["corrected_value"] > retired_rows["measurement_limit"] + 1e-9)
            ).sum()
        )
        transition_dates = {item["date"] for item in network_transitions}
        differences = []
        previous_raw = None
        previous_corrected = None
        raw_deltas: list[float] = []
        corrected_deltas: list[float] = []
        for _, label in months:
            raw = raw_values.get(_)
            corrected = corrected_values.get(_)
            raw_delta = (
                float(raw) - previous_raw
                if raw is not None
                and np.isfinite(raw)
                and previous_raw is not None
                else None
            )
            corrected_delta = (
                float(corrected) - previous_corrected
                if corrected is not None
                and np.isfinite(corrected)
                and previous_corrected is not None
                else None
            )
            if raw_delta is not None:
                raw_deltas.append(abs(raw_delta))
            if corrected_delta is not None:
                corrected_deltas.append(abs(corrected_delta))
            differences.append((label, raw_delta, corrected_delta))
            if raw is not None and np.isfinite(raw):
                previous_raw = float(raw)
            if corrected is not None and np.isfinite(corrected):
                previous_corrected = float(corrected)

        all_deltas = raw_deltas + corrected_deltas
        spike_threshold = (
            float(np.nanmedian(all_deltas) + 3 * np.nanstd(all_deltas))
            if all_deltas
            else None
        )
        network_event_spikes = []
        if spike_threshold is not None and np.isfinite(spike_threshold):
            for label, raw_delta, corrected_delta in differences:
                if label not in transition_dates:
                    continue
                raw_abs = abs(raw_delta) if raw_delta is not None else 0.0
                corrected_abs = (
                    abs(corrected_delta) if corrected_delta is not None else 0.0
                )
                if max(raw_abs, corrected_abs) > spike_threshold:
                    network_event_spikes.append(
                        {
                            "date": label,
                            "raw_first_difference": finite_or_none(raw_delta, 3),
                            "corrected_first_difference": finite_or_none(
                                corrected_delta,
                                3,
                            ),
                            "threshold": finite_or_none(spike_threshold, 3),
                        }
                    )

        return {
            "head_limit_violations": retired_limit_violations,
            "depth_limit_violations": 0,
            "network_event_spikes": network_event_spikes,
            "raw_vs_corrected_first_differences": [
                {
                    "date": label,
                    "raw": finite_or_none(raw_delta, 3),
                    "corrected": finite_or_none(corrected_delta, 3),
                }
                for label, raw_delta, corrected_delta in differences
            ],
            "cross_validation": None,
        }

    def _corrected_analysis_payload(
        self,
        group_id: str,
        months: list[tuple[int, str]],
        raw_frame: pd.DataFrame,
        selected_join_keys: set[str],
        manual_selection: bool,
        raw_weights: dict[str, float],
        raw_arithmetic_values: dict[int, float],
        raw_thiessen_values: dict[int, float],
        surface_methods: dict[str, dict[str, Any]],
        primary_surface_method: str,
        corrected_support_method: str,
        start_water_year: int,
        annual_end_water_year: int,
        storage_coefficient: float | None,
        aquifer_area_m2: float | None,
    ) -> dict[str, Any]:
        if corrected_support_method == "none":
            status_counts = []
            for month_index, month_label in months:
                month_frame = raw_frame[raw_frame["_month_index"] == month_index]
                measured_count = int(month_frame["_join_key"].nunique())
                missing_count = max(len(selected_join_keys) - measured_count, 0)
                status_counts.append(
                    {
                        "date": month_label,
                        "measured_count": measured_count,
                        "missing_count": missing_count,
                        "out_of_range_count": 0,
                        "retired_count": 0,
                        "new_well_count": 0,
                        "imputed_count": 0,
                    }
                )
            corrected_hydrograph = [
                {
                    "date": month_label,
                    "method": "raw_passthrough",
                    "raw_hydrograph": finite_or_none(raw_thiessen_values.get(month_index)),
                    "corrected_hydrograph": finite_or_none(raw_thiessen_values.get(month_index)),
                    "corrected_lower_band": None,
                    "corrected_upper_band": None,
                    **{
                        key: count_row[key]
                        for key in (
                            "measured_count",
                            "out_of_range_count",
                            "retired_count",
                            "new_well_count",
                            "imputed_count",
                        )
                    },
                }
                for (month_index, month_label), count_row in zip(months, status_counts)
            ]
            raw_arithmetic_series = self._series_from_values(months, raw_arithmetic_values)
            raw_thiessen_series = self._series_from_values(months, raw_thiessen_values)
            raw_median_values = self._median_hydrograph_value_map(raw_frame)
            raw_median_series = self._series_from_values(months, raw_median_values)
            corrected_annual_decline = {
                "corrected_arithmetic": self._apply_storage_to_annual_rows(
                    self._annual_decline_rows(
                        raw_arithmetic_values,
                        start_water_year,
                        annual_end_water_year,
                    ),
                    storage_coefficient,
                    aquifer_area_m2,
                ),
                "corrected_thiessen": self._apply_storage_to_annual_rows(
                    self._annual_decline_rows(
                        raw_thiessen_values,
                        start_water_year,
                        annual_end_water_year,
                    ),
                    storage_coefficient,
                    aquifer_area_m2,
                ),
                "corrected_median": self._apply_storage_to_annual_rows(
                    self._annual_decline_rows(
                        raw_median_values,
                        start_water_year,
                        annual_end_water_year,
                    ),
                    storage_coefficient,
                    aquifer_area_m2,
                ),
            }
            return {
                "support_method": corrected_support_method,
                "support_label": CORRECTED_SUPPORT_LABELS[corrected_support_method],
                "support_options": CORRECTED_SUPPORT_LABELS,
                "fixed_support_well_count": len(selected_join_keys),
                "fixed_support_site_count": len(raw_weights),
                "status_counts": status_counts,
                "raw_status_counts": status_counts,
                "corrected_hydrograph": corrected_hydrograph,
                "corrected_well_month": [],
                "network_transitions": [],
                "surface_methods": {},
                "annual_decline": corrected_annual_decline,
                "hydrographs": {
                    "raw_arithmetic": raw_arithmetic_series,
                    "raw_thiessen": raw_thiessen_series,
                    "raw_median": raw_median_series,
                    "corrected_arithmetic": raw_arithmetic_series,
                    "corrected_thiessen": raw_thiessen_series,
                    "corrected_median": raw_median_series,
                    "corrected_arithmetic_trend": self._trend(raw_arithmetic_values, months),
                    "corrected_thiessen_trend": self._trend(raw_thiessen_values, months),
                    "corrected_median_trend": self._trend(raw_median_values, months),
                    "primary_corrected": raw_thiessen_series,
                    "primary_corrected_trend": self._trend(raw_thiessen_values, months),
                    "raw_minus_corrected": [
                        [month_label, 0.0]
                        for _, month_label in months
                    ],
                },
                "value_maps": {
                    "corrected_arithmetic": raw_arithmetic_values,
                    "corrected_thiessen": raw_thiessen_values,
                    "corrected_median": raw_median_values,
                },
                "validation": {
                    "head_limit_violations": [],
                    "depth_limit_violations": 0,
                    "network_event_spikes": [],
                    "raw_vs_corrected_first_differences": [],
                    "cross_validation": None,
                },
                "note": "در این حالت هیچ اصلاحی اعمال نشده و خروجی اصلاحی برابر سری خام است.",
            }

        corrected_frame, support_join_keys, network_transitions = (
            self._corrected_well_month_frame(
                group_id,
                months,
                manual_selection,
                selected_join_keys,
            )
        )
        month_labels = dict(months)
        if corrected_frame.empty:
            return {
                "support_method": corrected_support_method,
                "support_label": CORRECTED_SUPPORT_LABELS[corrected_support_method],
                "support_options": CORRECTED_SUPPORT_LABELS,
                "fixed_support_well_count": 0,
                "fixed_support_site_count": 0,
                "status_counts": [],
                "corrected_hydrograph": [],
                "corrected_well_month": [],
                "network_transitions": [],
                "hydrographs": {},
                "annual_decline": {},
                "validation": {},
                "note": "داده‌ای برای ساخت هیدروگراف اصلاح‌شده وجود ندارد.",
            }

        support_frame = corrected_frame[
            corrected_frame["on_fixed_support"]
            & corrected_frame["corrected_value"].notna()
        ].copy()
        fixed_sites = self._selected_sites(group_id, support_join_keys)
        fixed_weights, _ = self._calculate_thiessen(group_id, fixed_sites)
        corrected_arithmetic_values, corrected_thiessen_values = (
            self._hydrograph_value_maps(support_frame, fixed_weights)
        )
        corrected_median_values = self._median_hydrograph_value_map(support_frame)
        raw_median_values = self._median_hydrograph_value_map(raw_frame)
        corrected_surface_methods: dict[str, dict[str, Any]] = {}
        for method in SURFACE_INTERPOLATION_METHOD_ORDER:
            method_values, method_metadata = self._piezometric_surface_value_map(
                group_id,
                support_frame,
                fixed_sites,
                method,
            )
            corrected_surface_methods[method] = {
                "metadata": {
                    **method_metadata,
                    "method": f"corrected_{method}",
                    "method_label": (
                        f"میانگین مساحتی اصلاح‌شده سطح پیزومتریک ماهانه "
                        f"({SURFACE_INTERPOLATION_LABELS[method]})"
                    ),
                    "short_label": (
                        f"اصلاح‌شده {SURFACE_INTERPOLATION_LABELS[method]}"
                    ),
                },
                "values": method_values,
                "series": self._series_from_values(months, method_values),
                "trend": self._trend(method_values, months),
            }

        primary_corrected_surface = corrected_surface_methods[
            primary_surface_method
        ]["values"]
        if corrected_support_method == "fixed_arithmetic":
            primary_corrected_values = corrected_arithmetic_values
            primary_raw_values = raw_arithmetic_values
            primary_method = "corrected_arithmetic"
        elif corrected_support_method == "fixed_median":
            primary_corrected_values = corrected_median_values
            primary_raw_values = raw_median_values
            primary_method = "corrected_median"
        elif corrected_support_method == "fixed_grid":
            primary_corrected_values = primary_corrected_surface
            primary_raw_values = surface_methods[primary_surface_method]["values"]
            primary_method = f"corrected_{primary_surface_method}"
        else:
            primary_corrected_values = corrected_thiessen_values
            primary_raw_values = raw_thiessen_values
            primary_method = "corrected_thiessen"

        status_counts = [
            self._status_count_row(
                month_label,
                corrected_frame[corrected_frame["_month_index"] == month_index],
            )
            for month_index, month_label in months
        ]
        count_by_label = {row["date"]: row for row in status_counts}
        corrected_hydrograph = []
        for month_index, month_label in months:
            raw_value = primary_raw_values.get(month_index)
            corrected_value = primary_corrected_values.get(month_index)
            counts = count_by_label[month_label]
            corrected_hydrograph.append(
                {
                    "date": month_label,
                    "method": primary_method,
                    "raw_hydrograph": finite_or_none(raw_value),
                    "corrected_hydrograph": finite_or_none(corrected_value),
                    "corrected_lower_band": None,
                    "corrected_upper_band": None,
                    **{
                        key: counts[key]
                        for key in (
                            "measured_count",
                            "out_of_range_count",
                            "retired_count",
                            "new_well_count",
                            "imputed_count",
                        )
                    },
                }
            )

        validation = self._corrected_validation(
            months,
            primary_raw_values,
            primary_corrected_values,
            corrected_frame,
            network_transitions,
        )
        hydrographs = {
            "raw_arithmetic": self._series_from_values(months, raw_arithmetic_values),
            "raw_thiessen": self._series_from_values(months, raw_thiessen_values),
            "raw_median": self._series_from_values(months, raw_median_values),
            "corrected_arithmetic": self._series_from_values(
                months,
                corrected_arithmetic_values,
            ),
            "corrected_thiessen": self._series_from_values(
                months,
                corrected_thiessen_values,
            ),
            "corrected_median": self._series_from_values(
                months,
                corrected_median_values,
            ),
            "corrected_arithmetic_trend": self._trend(
                corrected_arithmetic_values,
                months,
            ),
            "corrected_thiessen_trend": self._trend(
                corrected_thiessen_values,
                months,
            ),
            "corrected_median_trend": self._trend(
                corrected_median_values,
                months,
            ),
            "primary_corrected": self._series_from_values(
                months,
                primary_corrected_values,
            ),
            "primary_corrected_trend": self._trend(primary_corrected_values, months),
            "raw_minus_corrected": [
                [
                    month_label,
                    finite_or_none(
                        (
                            primary_raw_values.get(month_index)
                            - primary_corrected_values.get(month_index)
                        )
                        if primary_raw_values.get(month_index) is not None
                        and primary_corrected_values.get(month_index) is not None
                        else None,
                    ),
                ]
                for month_index, month_label in months
            ],
        }
        for method, payload in corrected_surface_methods.items():
            hydrographs[f"corrected_{method}"] = payload["series"]
            hydrographs[f"corrected_{method}_trend"] = payload["trend"]

        corrected_annual_decline = {
            "corrected_arithmetic": self._apply_storage_to_annual_rows(
                self._annual_decline_rows(
                    corrected_arithmetic_values,
                    start_water_year,
                    annual_end_water_year,
                ),
                storage_coefficient,
                aquifer_area_m2,
            ),
            "corrected_thiessen": self._apply_storage_to_annual_rows(
                self._annual_decline_rows(
                    corrected_thiessen_values,
                    start_water_year,
                    annual_end_water_year,
                ),
                storage_coefficient,
                aquifer_area_m2,
            ),
            "corrected_median": self._apply_storage_to_annual_rows(
                self._annual_decline_rows(
                    corrected_median_values,
                    start_water_year,
                    annual_end_water_year,
                ),
                storage_coefficient,
                aquifer_area_m2,
            ),
        }
        for method, payload in corrected_surface_methods.items():
            corrected_annual_decline[f"corrected_{method}"] = (
                self._apply_storage_to_annual_rows(
                    self._annual_decline_rows(
                        payload["values"],
                        start_water_year,
                        annual_end_water_year,
                    ),
                    storage_coefficient,
                    aquifer_area_m2,
                )
            )

        raw_status_counts = []
        for month_index, month_label in months:
            month_frame = raw_frame[raw_frame["_month_index"] == month_index]
            raw_status_counts.append(
                {
                    "date": month_label,
                    "measured_count": int(month_frame["_join_key"].nunique()),
                    "missing_count": max(
                        len(support_join_keys) - int(month_frame["_join_key"].nunique()),
                        0,
                    ),
                    "out_of_range_count": 0,
                    "retired_count": count_by_label[month_label]["retired_count"],
                    "new_well_count": count_by_label[month_label]["new_well_count"],
                }
            )

        return {
            "support_method": corrected_support_method,
            "support_label": CORRECTED_SUPPORT_LABELS[corrected_support_method],
            "support_options": CORRECTED_SUPPORT_LABELS,
            "fixed_support_well_count": len(support_join_keys),
            "fixed_support_site_count": len(fixed_weights),
            "status_counts": status_counts,
            "raw_status_counts": raw_status_counts,
            "corrected_hydrograph": corrected_hydrograph,
            "corrected_well_month": self._corrected_well_month_records(
                corrected_frame
            ),
            "network_transitions": network_transitions,
            "surface_methods": corrected_surface_methods,
            "annual_decline": corrected_annual_decline,
            "hydrographs": hydrographs,
            "value_maps": {
                "corrected_arithmetic": corrected_arithmetic_values,
                "corrected_thiessen": corrected_thiessen_values,
                "corrected_median": corrected_median_values,
                **{
                    f"corrected_{method}": payload["values"]
                    for method, payload in corrected_surface_methods.items()
                },
            },
            "validation": validation,
            "note": (
                "روش‌های اصلاحی از پشتیبان مکانی ثابت استفاده می‌کنند. "
                "ماه‌های پس از آخرین برداشت هر پیزومتر بازنشسته/دیگر قابل اندازه‌گیری "
                "در نظر گرفته شده‌اند و مقدار تراز اصلاحی از حد آخرین برداشت بالاتر نمی‌رود."
            ),
        }

    def _prepare_monthly_measurements(self) -> pd.DataFrame:
        location_lookup = (
            self.locations.drop_duplicates("_join_key")
            .set_index("_join_key")[["LEVEL_MSL", "X", "Y", "_site_key", "_well_id"]]
        )
        frame = self.measurements.join(location_lookup, on="_join_key", how="left")
        frame = frame.dropna(subset=["LEVEL_MSL", "WATER_TABLE", "_site_key"])
        frame["_level"] = frame["LEVEL_MSL"].astype(float) - frame["WATER_TABLE"].astype(float)
        return (
            frame.groupby(
                [
                    "_aquifer_id",
                    "_join_key",
                    "_well_id",
                    "_site_key",
                    "_month_index",
                    "_month",
                ],
                as_index=False,
            )
            .agg(level=("_level", "mean"))
            .sort_values(["_aquifer_id", "_month_index"])
        )

    def _available_water_years(self) -> list[int]:
        minimum = int(self.monthly["_month_index"].min())
        maximum = int(self.monthly["_month_index"].max())
        first_candidate = (minimum - 1) // MONTHS_PER_YEAR - 1
        last_candidate = (maximum - 1) // MONTHS_PER_YEAR
        return [
            year
            for year in range(first_candidate, last_candidate + 1)
            if (
                year * MONTHS_PER_YEAR + WATER_YEAR_START_MONTH >= minimum
                and (year + 1) * MONTHS_PER_YEAR + WATER_YEAR_END_MONTH <= maximum
            )
        ]

    def navigation(self) -> list[dict[str, Any]]:
        mahdoudes: dict[str, dict[str, Any]] = {}
        for group in self.groups.values():
            entry = mahdoudes.setdefault(
                group["mahdoude_key"],
                {"key": group["mahdoude_key"], "name": group["mahdoude"], "aquifers": []},
            )
            entry["aquifers"].append(
                {
                    "id": group["id"],
                    "name": group["aquifer"],
                    "well_count": group["well_count"],
                }
            )
        result = sorted(mahdoudes.values(), key=lambda item: item["name"])
        for item in result:
            item["aquifers"].sort(key=lambda aquifer: aquifer["name"])
        return result

    def aquifers_for_mahdoude(self, mahdoude_key: str) -> list[dict[str, Any]]:
        for mahdoude in self.navigation():
            if mahdoude["key"] == mahdoude_key:
                return mahdoude["aquifers"]
        return []

    def spatial_navigation(self) -> dict[str, Any]:
        overview_tolerance = 0.002
        mahdoude_features = [
            {
                "type": "Feature",
                "properties": {
                    "name": feature.properties.get("MAHDOUDE", ""),
                },
                "geometry": mapping(
                    feature.geometry.simplify(
                        overview_tolerance,
                        preserve_topology=True,
                    )
                ),
            }
            for feature in self.mahdoude_features
        ]
        aquifer_features = [
            {
                "type": "Feature",
                "properties": {
                    "id": group_id,
                    "mahdoude": group["mahdoude"],
                    "aquifer": group["aquifer"],
                    "well_count": group["well_count"],
                },
                "geometry": mapping(
                    self.boundary_matches[group_id]["aquifer"].geometry.simplify(
                        overview_tolerance,
                        preserve_topology=True,
                    )
                ),
            }
            for group_id, group in self.groups.items()
        ]
        return {
            "mahdoudes": {
                "type": "FeatureCollection",
                "features": mahdoude_features,
            },
            "aquifers": {
                "type": "FeatureCollection",
                "features": aquifer_features,
            },
        }

    @staticmethod
    def _feature_json(feature: BoundaryFeature) -> dict[str, Any]:
        return {
            "type": "Feature",
            "properties": feature.properties,
            "geometry": mapping(feature.geometry),
        }

    @staticmethod
    def _period_months(
        start_year: int,
        start_month: int,
        end_year: int,
        end_month: int,
    ) -> list[tuple[int, str]]:
        start_index = start_year * MONTHS_PER_YEAR + start_month
        end_index = end_year * MONTHS_PER_YEAR + end_month
        return [
            (
                index,
                f"{(index - 1) // MONTHS_PER_YEAR}-"
                f"{((index - 1) % MONTHS_PER_YEAR) + 1:02d}",
            )
            for index in range(start_index, end_index + 1)
        ]

    def _validate_period(
        self,
        group_id: str,
        start_year: int | None,
        start_month: int | None,
        end_year: int | None,
        end_month: int | None,
    ) -> tuple[int, int, int, int]:
        group_monthly = self.monthly[self.monthly["_aquifer_id"] == group_id]
        if group_monthly.empty:
            raise ValueError("برای این آبخوان داده اندازه‌گیری موجود نیست")
        minimum = int(group_monthly["_month_index"].min())
        maximum = int(group_monthly["_month_index"].max())
        default_start = max(
            minimum,
            maximum - DEFAULT_ANALYSIS_YEARS * MONTHS_PER_YEAR,
        )
        default_start_year = (default_start - 1) // MONTHS_PER_YEAR
        default_start_month = (default_start - 1) % MONTHS_PER_YEAR + 1
        default_end_year = (maximum - 1) // MONTHS_PER_YEAR
        default_end_month = (maximum - 1) % MONTHS_PER_YEAR + 1
        start_year_value = (
            default_start_year if start_year is None else int(start_year)
        )
        start_month_value = (
            default_start_month if start_month is None else int(start_month)
        )
        end_year_value = default_end_year if end_year is None else int(end_year)
        end_month_value = default_end_month if end_month is None else int(end_month)
        if (
            not 1 <= start_month_value <= MONTHS_PER_YEAR
            or not 1 <= end_month_value <= MONTHS_PER_YEAR
        ):
            raise ValueError("ماه باید عددی بین ۱ تا ۱۲ باشد")

        start_index = start_year_value * MONTHS_PER_YEAR + start_month_value
        end_index = end_year_value * MONTHS_PER_YEAR + end_month_value
        if start_index < minimum or end_index > maximum:
            raise ValueError("بازه انتخابی خارج از محدوده داده‌ها است")
        if start_index > end_index:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان باشد")
        return (
            start_year_value,
            start_month_value,
            end_year_value,
            end_month_value,
        )

    def _validate_trend_comparison_period(
        self,
        group_id: str,
        analysis_start_index: int,
        analysis_end_index: int,
        start_year: int | None,
        start_month: int | None,
        end_year: int | None,
        end_month: int | None,
    ) -> tuple[int, int, int, int]:
        group_monthly = self.monthly[self.monthly["_aquifer_id"] == group_id]
        minimum = int(group_monthly["_month_index"].min())
        maximum = int(group_monthly["_month_index"].max())
        analysis_end_year = (analysis_end_index - 1) // MONTHS_PER_YEAR
        analysis_end_month = (analysis_end_index - 1) % MONTHS_PER_YEAR + 1
        default_water_year = self._water_year_for_month(
            analysis_end_year,
            analysis_end_month,
        )
        default_start_index = max(
            minimum,
            default_water_year * MONTHS_PER_YEAR + WATER_YEAR_START_MONTH,
        )
        default_start_year = (default_start_index - 1) // MONTHS_PER_YEAR
        default_start_month = (default_start_index - 1) % MONTHS_PER_YEAR + 1
        default_end_year = analysis_end_year
        default_end_month = analysis_end_month
        start_year_value = (
            default_start_year if start_year is None else int(start_year)
        )
        start_month_value = (
            default_start_month if start_month is None else int(start_month)
        )
        end_year_value = default_end_year if end_year is None else int(end_year)
        end_month_value = default_end_month if end_month is None else int(end_month)
        if (
            not 1 <= start_month_value <= MONTHS_PER_YEAR
            or not 1 <= end_month_value <= MONTHS_PER_YEAR
        ):
            raise ValueError("ماه بازه مقایسه باید عددی بین ۱ تا ۱۲ باشد")

        start_index = start_year_value * MONTHS_PER_YEAR + start_month_value
        end_index = end_year_value * MONTHS_PER_YEAR + end_month_value
        if start_index < minimum or end_index > maximum:
            raise ValueError("بازه مقایسه شیب خارج از محدوده داده‌ها است")
        if start_index > end_index:
            raise ValueError("تاریخ شروع بازه مقایسه باید قبل از تاریخ پایان باشد")
        if end_index < analysis_start_index or start_index > analysis_end_index:
            raise ValueError("بازه مقایسه شیب باید با بازه تحلیل هم‌پوشانی داشته باشد")
        return (
            start_year_value,
            start_month_value,
            end_year_value,
            end_month_value,
        )

    def _comparison_period_bounds(self) -> tuple[int, int]:
        if self.monthly.empty:
            raise ValueError("هیچ داده‌ای برای مقایسه آبخوان‌ها وجود ندارد")
        return (
            int(self.monthly["_month_index"].min()),
            int(self.monthly["_month_index"].max()),
        )

    def _validate_comparison_period(
        self,
        start_year: int | None,
        start_month: int | None,
        end_year: int | None,
        end_month: int | None,
    ) -> tuple[int, int, int, int]:
        minimum, maximum = self._comparison_period_bounds()
        default_start = max(
            minimum,
            maximum - DEFAULT_ANALYSIS_YEARS * MONTHS_PER_YEAR,
        )
        default_start_year = (default_start - 1) // MONTHS_PER_YEAR
        default_start_month = (default_start - 1) % MONTHS_PER_YEAR + 1
        default_end_year = (maximum - 1) // MONTHS_PER_YEAR
        default_end_month = (maximum - 1) % MONTHS_PER_YEAR + 1
        start_year_value = (
            default_start_year if start_year is None else int(start_year)
        )
        start_month_value = (
            default_start_month if start_month is None else int(start_month)
        )
        end_year_value = default_end_year if end_year is None else int(end_year)
        end_month_value = default_end_month if end_month is None else int(end_month)
        if (
            not 1 <= start_month_value <= MONTHS_PER_YEAR
            or not 1 <= end_month_value <= MONTHS_PER_YEAR
        ):
            raise ValueError("ماه باید عددی بین ۱ تا ۱۲ باشد")

        start_index = start_year_value * MONTHS_PER_YEAR + start_month_value
        end_index = end_year_value * MONTHS_PER_YEAR + end_month_value
        if start_index < minimum or end_index > maximum:
            raise ValueError("بازه انتخابی خارج از محدوده داده‌ها است")
        if start_index > end_index:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان باشد")
        return (
            start_year_value,
            start_month_value,
            end_year_value,
            end_month_value,
        )

    @staticmethod
    def _water_year_for_month(year: int, month: int) -> int:
        return year if month >= WATER_YEAR_START_MONTH else year - 1

    def _selected_join_keys(
        self,
        group_frame: pd.DataFrame,
        start_index: int,
        end_index: int,
        continuous_only: bool,
    ) -> set[str]:
        if group_frame.empty:
            return set()
        spans = group_frame.groupby("_join_key")["_month_index"].agg(["min", "max"])
        range_keys = set(
            group_frame[
                (group_frame["_month_index"] >= start_index)
                & (group_frame["_month_index"] <= end_index)
            ]["_join_key"].unique()
        )
        if continuous_only:
            selected = spans[(spans["min"] <= start_index) & (spans["max"] >= end_index)]
        else:
            selected = spans[(spans["max"] >= start_index) & (spans["min"] <= end_index)]
        return set(selected.index) & range_keys

    def _manual_selected_join_keys(
        self,
        group_id: str,
        display_frame: pd.DataFrame,
        selected_well_ids: list[str] | None,
    ) -> set[str]:
        requested_ids = set(selected_well_ids or [])
        if not requested_ids:
            raise ValueError("در حالت انتخاب دستی، حداقل یک چاه را انتخاب کنید")

        locations = self.locations[self.locations["_aquifer_id"] == group_id]
        id_to_join_key = dict(
            locations[["_well_id", "_join_key"]].itertuples(index=False, name=None)
        )
        range_join_keys = set(display_frame["_join_key"].unique())
        selected_join_keys = {
            id_to_join_key[well_id]
            for well_id in requested_ids
            if well_id in id_to_join_key and id_to_join_key[well_id] in range_join_keys
        }
        if not selected_join_keys:
            raise ValueError("چاه‌های انتخاب‌شده در بازه زمانی مورد نظر داده‌ای ندارند")
        return selected_join_keys

    @staticmethod
    def _timeline_months(minimum: int, maximum: int) -> list[dict[str, Any]]:
        return [
            {
                "index": index,
                "label": f"{(index - 1) // MONTHS_PER_YEAR}-{((index - 1) % MONTHS_PER_YEAR) + 1:02d}",
            }
            for index in range(minimum, maximum + 1)
        ]

    def _selected_sites(
        self,
        group_id: str,
        selected_join_keys: set[str],
    ) -> pd.DataFrame:
        locations = self.locations[
            (self.locations["_aquifer_id"] == group_id)
            & (self.locations["_join_key"].isin(selected_join_keys))
        ].copy()
        if locations.empty:
            return pd.DataFrame(columns=["_site_key", "X", "Y", "well_names"])
        return (
            locations.groupby("_site_key", as_index=False)
            .agg(
                X=("X", "mean"),
                Y=("Y", "mean"),
                well_names=("LOCATION", lambda values: "، ".join(dict.fromkeys(values))),
            )
        )

    @staticmethod
    def _hydrograph_value_maps(
        frame: pd.DataFrame,
        weights: dict[str, float],
    ) -> tuple[dict[int, float], dict[int, float]]:
        arithmetic_values: dict[int, float] = {}
        thiessen_values: dict[int, float] = {}
        if frame.empty:
            return arithmetic_values, thiessen_values

        arithmetic_values = (
            frame.groupby("_month_index")["level"].mean().to_dict()
        )
        site_month = (
            frame.groupby(["_month_index", "_site_key"], as_index=False)
            .agg(level=("level", "mean"))
        )
        site_month["weight"] = site_month["_site_key"].map(weights).fillna(0.0)
        site_month["weighted"] = site_month["level"] * site_month["weight"]
        thiessen = site_month.groupby("_month_index").agg(
            weighted=("weighted", "sum"),
            available_weight=("weight", "sum"),
        )
        thiessen["value"] = np.where(
            thiessen["available_weight"] > 0,
            thiessen["weighted"] / thiessen["available_weight"],
            np.nan,
        )
        thiessen_values = thiessen["value"].to_dict()
        return arithmetic_values, thiessen_values

    @staticmethod
    def _median_hydrograph_value_map(frame: pd.DataFrame) -> dict[int, float]:
        if frame.empty:
            return {}
        return frame.groupby("_month_index")["level"].median().to_dict()

    @staticmethod
    def _annual_decline_rows(
        values: dict[int, float],
        start_year: int,
        end_year: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cumulative = 0.0
        has_cumulative = False
        for year in range(start_year, end_year + 1):
            start_index = year * MONTHS_PER_YEAR + WATER_YEAR_START_MONTH
            next_mehr_index = (
                (year + 1) * MONTHS_PER_YEAR + WATER_YEAR_START_MONTH
            )
            shahrivar_index = (
                (year + 1) * MONTHS_PER_YEAR + WATER_YEAR_END_MONTH
            )
            start_level = values.get(start_index)
            if values.get(next_mehr_index) is not None:
                end_index = next_mehr_index
            elif year == end_year:
                fallback_indexes = [
                    index
                    for index, value in values.items()
                    if start_index < index <= shahrivar_index
                    and value is not None
                    and np.isfinite(value)
                ]
                end_index = max(fallback_indexes, default=shahrivar_index)
            else:
                end_index = shahrivar_index
            end_level = values.get(end_index)
            displayed_start_level = finite_or_none(start_level)
            displayed_end_level = finite_or_none(end_level)
            decline = (
                displayed_start_level - displayed_end_level
                if displayed_start_level is not None
                and displayed_end_level is not None
                else None
            )
            decline = finite_or_none(decline)
            if decline is not None:
                cumulative += decline
                has_cumulative = True
            rows.append(
                {
                    "water_year": f"{year}-{year + 1}",
                    "start_month": f"{year}-{WATER_YEAR_START_MONTH:02d}",
                    "end_month": (
                        f"{year + 1}-{WATER_YEAR_START_MONTH:02d}"
                        if end_index == next_mehr_index
                        else (
                            f"{(end_index - 1) // MONTHS_PER_YEAR}-"
                            f"{((end_index - 1) % MONTHS_PER_YEAR) + 1:02d}"
                        )
                    ),
                    "start_level": displayed_start_level,
                    "end_level": displayed_end_level,
                    "decline": decline,
                    "cumulative_decline": finite_or_none(cumulative)
                    if has_cumulative
                    else None,
                }
            )
        return rows

    @staticmethod
    def _trend(
        values: dict[int, float],
        months: list[tuple[int, str]],
    ) -> dict[str, Any]:
        valid = [
            (index, float(values[index]))
            for index, _ in months
            if index in values and np.isfinite(values[index])
        ]
        if len(valid) < 2:
            return {
                "slope_per_month": None,
                "slope_per_year": None,
                "decline_per_year": None,
                "direction": "insufficient",
                "series": [[label, None] for _, label in months],
            }

        origin = valid[0][0]
        x = np.array([index - origin for index, _ in valid], dtype=float)
        y = np.array([value for _, value in valid], dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        slope_per_year = float(slope * MONTHS_PER_YEAR)
        decline_per_year = -slope_per_year
        tolerance = 1e-9
        direction = (
            "decline"
            if decline_per_year > tolerance
            else "rise"
            if decline_per_year < -tolerance
            else "stable"
        )
        return {
            "slope_per_month": finite_or_none(slope, 4),
            "slope_per_year": finite_or_none(slope_per_year, 3),
            "decline_per_year": finite_or_none(decline_per_year, 3),
            "direction": direction,
            "series": [
                [label, finite_or_none(intercept + slope * (index - origin))]
                for index, label in months
            ],
        }

    def _five_year_scenario(
        self,
        values: dict[int, float],
        months: list[tuple[int, str]],
        trend: dict[str, Any],
        method: str,
    ) -> dict[str, Any]:
        observed = [
            (index, float(values[index]))
            for index, _ in months
            if index in values
            and values[index] is not None
            and np.isfinite(values[index])
        ]
        decline_per_year = trend.get("decline_per_year")
        if not observed or decline_per_year is None or not np.isfinite(decline_per_year):
            return {
                "method": method,
                "forecast_years": 5,
                "status": "insufficient",
                "baseline_month": None,
                "baseline_level_m": None,
                "decline_per_year_m": None,
                "direction": "insufficient",
                "series": [],
                "note": (
                    "Scenario requires a valid current trend and at least one "
                    "observed groundwater level."
                ),
            }

        last_index, baseline_level = observed[-1]
        baseline_year = (last_index - 1) // MONTHS_PER_YEAR
        baseline_month = (last_index - 1) % MONTHS_PER_YEAR + 1
        baseline_water_year = self._water_year_for_month(
            baseline_year,
            baseline_month,
        )
        decline_value = float(decline_per_year)
        series = []
        for horizon in range(1, 6):
            projected_level = baseline_level - decline_value * horizon
            series.append(
                {
                    "horizon_year": horizon,
                    "water_year": self._water_year_label(
                        baseline_water_year + horizon
                    ),
                    "projected_level_m": finite_or_none(projected_level, 3),
                    "cumulative_decline_m": finite_or_none(
                        decline_value * horizon,
                        3,
                    ),
                }
            )

        return {
            "method": method,
            "forecast_years": 5,
            "status": "ok",
            "baseline_month": f"{baseline_year}-{baseline_month:02d}",
            "baseline_water_year": self._water_year_label(baseline_water_year),
            "baseline_level_m": finite_or_none(baseline_level, 3),
            "decline_per_year_m": finite_or_none(decline_value, 3),
            "direction": trend.get("direction"),
            "series": series,
            "note": (
                "Linear continuation of the selected-period representative "
                "groundwater trend. Positive cumulative decline means lower "
                "groundwater level."
            ),
        }

    @staticmethod
    def _trend_statistics(
        years: list[int],
        values: list[float | None],
    ) -> dict[str, Any]:
        pairs = [
            (int(year), float(value))
            for year, value in zip(years, values, strict=False)
            if value is not None and np.isfinite(value)
        ]
        if len(pairs) < 2:
            return {
                "n": len(pairs),
                "valid_years": [year for year, _ in pairs],
                "mann_kendall": {
                    "tau": None,
                    "p_value": None,
                    "trend": "insufficient",
                },
                "sen_slope": {
                    "slope_per_year": None,
                    "intercept": None,
                },
                "linear_trend": {
                    "slope_per_year": None,
                    "intercept": None,
                },
                "percentage_change": None,
                "start_value": pairs[0][1] if pairs else None,
                "end_value": pairs[-1][1] if pairs else None,
                "direction": "insufficient",
            }

        x = np.array([year for year, _ in pairs], dtype=float)
        y = np.array([value for _, value in pairs], dtype=float)
        x_relative = x - x[0]

        try:
            mk = kendalltau(x, y, nan_policy="omit")
            mk_tau = finite_or_none(mk.statistic, 4)
            mk_p = finite_or_none(mk.pvalue, 4)
        except Exception:
            mk_tau = None
            mk_p = None

        try:
            sen_slope, sen_intercept, _, _ = theilslopes(y, x_relative)
        except Exception:
            sen_slope = None
            sen_intercept = None

        try:
            linear_slope, linear_intercept = np.polyfit(x_relative, y, 1)
        except Exception:
            linear_slope = None
            linear_intercept = None

        start_value = float(y[0])
        end_value = float(y[-1])
        percentage_change = (
            None
            if abs(start_value) < 1e-12
            else ((end_value - start_value) / abs(start_value)) * 100
        )

        slope_value = linear_slope if linear_slope is not None else sen_slope
        tolerance = 1e-9
        direction = (
            "decline"
            if slope_value is not None and slope_value < -tolerance
            else "rise"
            if slope_value is not None and slope_value > tolerance
            else "stable"
        )
        mk_direction = (
            "decline"
            if mk_tau is not None and mk_tau < -tolerance
            else "rise"
            if mk_tau is not None and mk_tau > tolerance
            else "stable"
        )

        return {
            "n": len(pairs),
            "valid_years": [year for year, _ in pairs],
            "mann_kendall": {
                "tau": mk_tau,
                "p_value": mk_p,
                "trend": mk_direction,
            },
            "sen_slope": {
                "slope_per_year": finite_or_none(sen_slope, 4),
                "intercept": finite_or_none(sen_intercept, 4),
            },
            "linear_trend": {
                "slope_per_year": finite_or_none(linear_slope, 4),
                "intercept": finite_or_none(linear_intercept, 4),
            },
            "percentage_change": finite_or_none(percentage_change, 2),
            "start_value": finite_or_none(start_value, 4),
            "end_value": finite_or_none(end_value, 4),
            "direction": direction,
        }

    @staticmethod
    def _safe_pearson(x: list[float], y: list[float]) -> tuple[float | None, float | None]:
        if len(x) < 2 or len(y) < 2:
            return None, None
        if np.allclose(x, x[0]) or np.allclose(y, y[0]):
            return None, None
        try:
            result = pearsonr(x, y)
        except Exception:
            return None, None
        return finite_or_none(result.statistic, 4), finite_or_none(result.pvalue, 4)

    @staticmethod
    def _safe_spearman(
        x: list[float],
        y: list[float],
    ) -> tuple[float | None, float | None]:
        if len(x) < 2 or len(y) < 2:
            return None, None
        if np.allclose(x, x[0]) or np.allclose(y, y[0]):
            return None, None
        try:
            result = spearmanr(x, y)
        except Exception:
            return None, None
        statistic = getattr(result, "statistic", result[0])
        pvalue = getattr(result, "pvalue", result[1])
        return finite_or_none(statistic, 4), finite_or_none(pvalue, 4)

    @classmethod
    def _association_statistics(
        cls,
        x_years: list[int],
        x_values: list[float | None],
        y_years: list[int],
        y_values: list[float | None],
        lag: int = 0,
    ) -> dict[str, Any]:
        x_map = {
            int(year): float(value)
            for year, value in zip(x_years, x_values, strict=False)
            if value is not None and np.isfinite(value)
        }
        y_map = {
            int(year): float(value)
            for year, value in zip(y_years, y_values, strict=False)
            if value is not None and np.isfinite(value)
        }
        pairs = []
        for year, value in x_map.items():
            if lag:
                matched = y_map.get(year - lag)
            else:
                matched = y_map.get(year)
            if matched is not None:
                pairs.append((value, matched))
        if len(pairs) < 2:
            return {
                "n": len(pairs),
                "pearson": {"coefficient": None, "p_value": None},
                "spearman": {"coefficient": None, "p_value": None},
            }
        x_series = [item[0] for item in pairs]
        y_series = [item[1] for item in pairs]
        pearson, pearson_p = cls._safe_pearson(x_series, y_series)
        spearman, spearman_p = cls._safe_spearman(x_series, y_series)
        return {
            "n": len(pairs),
            "pearson": {
                "coefficient": pearson,
                "p_value": pearson_p,
            },
            "spearman": {
                "coefficient": spearman,
                "p_value": spearman_p,
            },
        }

    @staticmethod
    def _decline_periods(
        years: list[int],
        values: list[float | None],
    ) -> list[dict[str, Any]]:
        periods: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        previous_year: int | None = None
        for year, value in zip(years, values, strict=False):
            if value is None or not np.isfinite(value) or value <= 0:
                if current is not None:
                    periods.append(current)
                    current = None
                previous_year = None
                continue
            if current is None or previous_year is None or year != previous_year + 1:
                if current is not None:
                    periods.append(current)
                current = {
                    "start_water_year": f"{year}-{year + 1}",
                    "end_water_year": f"{year}-{year + 1}",
                    "years": [f"{year}-{year + 1}"],
                    "length_years": 1,
                    "total_decline_m": finite_or_none(value, 3),
                    "mean_decline_m": finite_or_none(value, 3),
                    "max_decline_m": finite_or_none(value, 3),
                }
            else:
                current["end_water_year"] = f"{year}-{year + 1}"
                current["years"].append(f"{year}-{year + 1}")
                current["length_years"] += 1
                current["total_decline_m"] = finite_or_none(
                    (current["total_decline_m"] or 0) + value,
                    3,
                )
                current["mean_decline_m"] = finite_or_none(
                    current["total_decline_m"] / current["length_years"],
                    3,
                )
                current["max_decline_m"] = finite_or_none(
                    max(current["max_decline_m"] or value, value),
                    3,
                )
            previous_year = year
        if current is not None:
            periods.append(current)
        return periods

    @staticmethod
    def _decline_anomalies(
        years: list[int],
        values: list[float | None],
    ) -> list[dict[str, Any]]:
        pairs = [
            (year, float(value))
            for year, value in zip(years, values, strict=False)
            if value is not None and np.isfinite(value)
        ]
        if len(pairs) < 3:
            return []
        values_array = np.array([value for _, value in pairs], dtype=float)
        median = float(np.median(values_array))
        mad = float(np.median(np.abs(values_array - median)))
        if mad > 0:
            z_scores = 0.6745 * (values_array - median) / mad
        else:
            mean = float(np.mean(values_array))
            std = float(np.std(values_array))
            if std == 0:
                return []
            z_scores = (values_array - mean) / std
        anomalies = []
        for (year, value), z_score in zip(pairs, z_scores, strict=False):
            if z_score >= DECLINE_ANOMALY_Z_THRESHOLD:
                anomalies.append(
                    {
                        "water_year": f"{year}-{year + 1}",
                        "value_m": finite_or_none(value, 3),
                        "z_score": finite_or_none(float(z_score), 3),
                    }
                )
        return anomalies

    @staticmethod
    def _water_year_label(year: int) -> str:
        return f"{year}-{year + 1}"

    def _time_series_analysis(
        self,
        annual_changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        def empty_risk_assessment() -> dict[str, Any]:
            return {
                "score": None,
                "level": "insufficient",
                "label": "Insufficient Data",
                "confidence": "low",
                "confidence_score": 0.0,
                "factors": {
                    "decline_persistence": {
                        "score": None,
                        "value": None,
                        "declining_year_count": 0,
                        "water_year_count": 0,
                    },
                    "mean_decline": {
                        "score": None,
                        "value_m": None,
                    },
                    "max_decline": {
                        "score": None,
                        "value_m": None,
                    },
                    "anomaly_frequency": {
                        "score": None,
                        "count": 0,
                        "years": [],
                    },
                    "agricultural_pressure": {
                        "score": None,
                        "simultaneous_pressure_year_count": 0,
                        "years": [],
                    },
                },
                "evidence": [],
            }

        frame = pd.DataFrame(
            [
                {
                    "water_year": int(str(row["water_year"]).split("-", 1)[0]),
                    "water_year_label": str(row["water_year"]),
                    "is_complete": bool(row.get("is_complete")),
                    "selected_month_count": int(row.get("selected_month_count", 0)),
                    "precipitation_total": row.get("precipitation_total"),
                    "aet_total": row.get("aet_total"),
                    "irrigated_area_ha": (
                        row.get("warm_season_irrigated_area", {})
                        .get("probable_area_ha")
                    ),
                    "ndvi_mean": (
                        row.get("ndvi_periods", {})
                        .get("warm_months", {})
                        .get("mean")
                    ),
                    "groundwater_decline_m": (
                        row.get("decline", {}).get("piezometric_surface")
                        if row.get("decline", {}).get("piezometric_surface") is not None
                        else row.get("decline", {}).get("thiessen")
                    ),
                }
                for row in annual_changes
            ]
        )
        if frame.empty:
            return {
                "period": {
                    "water_year_count": 0,
                    "complete_year_count": 0,
                    "partial_year_count": 0,
                    "groundwater_method": "piezometric_surface_idw",
                    "ndvi_window": "khordad-shahrivar",
                },
                "trend_statistics": {},
                "correlations": {},
                "lag_analysis": {},
                "stress_indicators": {},
                "agricultural_pressure": {},
                "risk_assessment": empty_risk_assessment(),
                "driver_classification": {
                    "label": "Mixed Influence",
                    "confidence": "low",
                    "confidence_score": 0.0,
                    "reason": "No annual data available for the selected period.",
                },
                "llm_input": {
                    "trend_statistics": {},
                    "correlations": {},
                    "lag_analysis": {},
                    "stress_indicators": {},
                    "risk_assessment": empty_risk_assessment(),
                    "anomaly_years": [],
                },
            }

        frame = frame.sort_values("water_year").reset_index(drop=True)
        years = frame["water_year"].tolist()
        water_year_labels = frame["water_year_label"].tolist()
        precipitation_values = frame["precipitation_total"].tolist()
        aet_values = frame["aet_total"].tolist()
        irrigated_area_values = frame["irrigated_area_ha"].tolist()
        ndvi_values = frame["ndvi_mean"].tolist()
        groundwater_values = frame["groundwater_decline_m"].tolist()
        complete_years = int(frame["is_complete"].sum())
        partial_years = int(len(frame) - complete_years)

        trends = {
            "precipitation": self._trend_statistics(years, precipitation_values),
            "aet": self._trend_statistics(years, aet_values),
            "irrigated_area": self._trend_statistics(years, irrigated_area_values),
            "ndvi": self._trend_statistics(years, ndvi_values),
            "groundwater_level_change": self._trend_statistics(
                years,
                groundwater_values,
            ),
        }
        correlations = {
            "precipitation": self._association_statistics(
                years,
                precipitation_values,
                years,
                groundwater_values,
            ),
            "aet": self._association_statistics(
                years,
                aet_values,
                years,
                groundwater_values,
            ),
            "irrigated_area": self._association_statistics(
                years,
                irrigated_area_values,
                years,
                groundwater_values,
            ),
            "ndvi": self._association_statistics(
                years,
                ndvi_values,
                years,
                groundwater_values,
            ),
        }
        lag_analysis = {
            "lag_1": self._association_statistics(
                years,
                precipitation_values,
                years,
                groundwater_values,
                lag=1,
            ),
            "lag_2": self._association_statistics(
                years,
                precipitation_values,
                years,
                groundwater_values,
                lag=2,
            ),
        }
        groundwater_decline_values = [
            float(value) if value is not None and np.isfinite(value) else None
            for value in groundwater_values
        ]
        stress_indicators = {
            "mean_annual_groundwater_decline_m": finite_or_none(
                np.mean([
                    value
                    for value in groundwater_decline_values
                    if value is not None
                ])
                if any(value is not None for value in groundwater_decline_values)
                else None,
                3,
            ),
            "max_annual_groundwater_decline_m": finite_or_none(
                max(
                    [
                        value
                        for value in groundwater_decline_values
                        if value is not None and value > 0
                    ],
                    default=None,
                ),
                3,
            ),
            "declining_year_count": sum(
                1
                for value in groundwater_decline_values
                if value is not None and value > 0
            ),
            "consecutive_decline_periods": self._decline_periods(
                years,
                groundwater_decline_values,
            ),
            "groundwater_decline_anomaly_years": self._decline_anomalies(
                years,
                groundwater_decline_values,
            ),
        }

        area_map = {
            year: float(value)
            for year, value in zip(years, irrigated_area_values, strict=False)
            if value is not None and np.isfinite(value)
        }
        ndvi_map = {
            year: float(value)
            for year, value in zip(years, ndvi_values, strict=False)
            if value is not None and np.isfinite(value)
        }
        groundwater_map = {
            year: float(value)
            for year, value in zip(years, groundwater_values, strict=False)
            if value is not None and np.isfinite(value)
        }
        growth_pairs: list[tuple[int, float, float]] = []
        for year in years[1:]:
            if (
                year in area_map
                and year - 1 in area_map
                and year in ndvi_map
                and year - 1 in ndvi_map
            ):
                area_change = area_map[year] - area_map[year - 1]
                ndvi_change = ndvi_map[year] - ndvi_map[year - 1]
                growth_pairs.append((year, area_change, ndvi_change))

        if growth_pairs:
            area_changes = np.array([item[1] for item in growth_pairs], dtype=float)
            ndvi_changes = np.array([item[2] for item in growth_pairs], dtype=float)
            area_std = float(np.std(area_changes))
            ndvi_std = float(np.std(ndvi_changes))
            area_center = float(np.mean(area_changes))
            ndvi_center = float(np.mean(ndvi_changes))
            if area_std > 0:
                area_z = (area_changes - area_center) / area_std
            else:
                area_z = np.zeros_like(area_changes)
            if ndvi_std > 0:
                ndvi_z = (ndvi_changes - ndvi_center) / ndvi_std
            else:
                ndvi_z = np.zeros_like(ndvi_changes)
            joint_index = (area_z + ndvi_z) / 2
            simultaneous_pressure_years = []
            for (year, area_change, ndvi_change), index in zip(
                growth_pairs,
                joint_index,
                strict=False,
            ):
                groundwater_decline = groundwater_map.get(year)
                if (
                    area_change > 0
                    and ndvi_change > 0
                    and groundwater_decline is not None
                    and groundwater_decline > 0
                ):
                    simultaneous_pressure_years.append(
                        {
                            "water_year": self._water_year_label(year),
                            "irrigated_area_change_ha": finite_or_none(area_change, 3),
                            "ndvi_change": finite_or_none(ndvi_change, 4),
                            "groundwater_decline_m": finite_or_none(
                                groundwater_decline,
                                3,
                            ),
                            "joint_growth_index": finite_or_none(float(index), 3),
                        }
                    )
            joint_summary = {
                "definition": "mean(z(irrigated_area_year_over_year_change), z(ndvi_year_over_year_change)) / 2",
                "mean": finite_or_none(float(np.mean(joint_index)), 3),
                "max": finite_or_none(float(np.max(joint_index)), 3),
                "min": finite_or_none(float(np.min(joint_index)), 3),
                "positive_year_count": int(np.sum(joint_index > 0)),
                "simultaneous_pressure_years": simultaneous_pressure_years,
            }
        else:
            joint_summary = {
                "definition": "mean(z(irrigated_area_year_over_year_change), z(ndvi_year_over_year_change)) / 2",
                "mean": None,
                "max": None,
                "min": None,
                "positive_year_count": 0,
                "simultaneous_pressure_years": [],
            }

        irrigated_area_trend = trends["irrigated_area"]
        ndvi_trend = trends["ndvi"]
        precip_corr = correlations["precipitation"]
        lag_1_corr = lag_analysis["lag_1"]
        lag_2_corr = lag_analysis["lag_2"]
        precip_strength = max(
            abs(precip_corr["pearson"]["coefficient"] or 0),
            abs(precip_corr["spearman"]["coefficient"] or 0),
            abs(lag_1_corr["pearson"]["coefficient"] or 0),
            abs(lag_2_corr["pearson"]["coefficient"] or 0),
        )
        ag_trend_strength = sum(
            1
            for trend in (irrigated_area_trend, ndvi_trend)
            if (trend.get("direction") == "rise")
        )
        decline_persistence = (
            stress_indicators["declining_year_count"] / len(years)
            if years
            else 0
        )
        climate_score = float(np.clip((precip_strength - TREND_WEAK_THRESHOLD) / 0.4, 0, 1))
        human_score = float(
            np.clip(
                (
                    decline_persistence
                    + (1 if irrigated_area_trend.get("direction") == "rise" else 0)
                    + (1 if ndvi_trend.get("direction") == "rise" else 0)
                )
                / 3,
                0,
                1,
            )
            * (1 - precip_strength)
        )
        if climate_score >= 0.7 and human_score < 0.5:
            driver_label = "Climate Dominated"
            driver_reason = (
                "groundwater responds strongly to precipitation while agricultural "
                "signals remain weak."
            )
        elif human_score >= 0.7 and precip_strength < TREND_STRONG_THRESHOLD:
            driver_label = "Human Dominated"
            driver_reason = (
                "groundwater decline is persistent and agricultural indicators rise "
                "while precipitation linkage stays weak."
            )
        else:
            driver_label = "Mixed Influence"
            driver_reason = (
                "climate and agricultural signals both contribute to groundwater "
                "change."
            )

        confidence_base = min(1.0, len(years) / 6)
        confidence_score = float(
            np.clip(
                confidence_base * (1 - 0.15 * partial_years) * max(climate_score, human_score, 0.25),
                0,
                1,
            )
        )
        confidence = (
            "high"
            if confidence_score >= 0.75
            else "medium"
            if confidence_score >= 0.5
            else "low"
        )
        rationale = [
            f"{len(years)} water years were analyzed.",
            (
                f"Precipitation relationship strength is {precip_strength:.2f}."
                if precip_strength
                else "Precipitation relationship is weak or insufficient."
            ),
            (
                f"{stress_indicators['declining_year_count']} years show groundwater decline."
            ),
        ]
        anomaly_years = stress_indicators["groundwater_decline_anomaly_years"]
        simultaneous_pressure_years = joint_summary[
            "simultaneous_pressure_years"
        ]
        year_count = len(years)
        mean_decline = (
            stress_indicators["mean_annual_groundwater_decline_m"] or 0
        )
        max_decline = (
            stress_indicators["max_annual_groundwater_decline_m"] or 0
        )
        persistence_score = float(np.clip(decline_persistence, 0, 1))
        mean_decline_score = float(np.clip(max(mean_decline, 0) / 1.0, 0, 1))
        max_decline_score = float(np.clip(max(max_decline, 0) / 2.0, 0, 1))
        anomaly_score = float(
            np.clip((len(anomaly_years) / max(year_count, 1)) * 3, 0, 1)
        )
        pressure_score = float(
            np.clip(
                max(
                    human_score,
                    (
                        len(simultaneous_pressure_years)
                        / max(year_count - 1, 1)
                    )
                    * 2,
                ),
                0,
                1,
            )
        )
        risk_score = (
            0.40 * persistence_score
            + 0.25 * mean_decline_score
            + 0.15 * max_decline_score
            + 0.10 * anomaly_score
            + 0.10 * pressure_score
        ) * 100
        risk_level = (
            "critical"
            if risk_score >= 75
            else "high"
            if risk_score >= 55
            else "moderate"
            if risk_score >= 30
            else "low"
        )
        risk_assessment = {
            "score": finite_or_none(risk_score, 1),
            "level": risk_level,
            "label": {
                "low": "Low",
                "moderate": "Moderate",
                "high": "High",
                "critical": "Critical",
            }[risk_level],
            "confidence": confidence,
            "confidence_score": finite_or_none(confidence_score, 2),
            "factors": {
                "decline_persistence": {
                    "score": finite_or_none(persistence_score * 100, 1),
                    "value": finite_or_none(decline_persistence, 3),
                    "declining_year_count": stress_indicators[
                        "declining_year_count"
                    ],
                    "water_year_count": year_count,
                },
                "mean_decline": {
                    "score": finite_or_none(mean_decline_score * 100, 1),
                    "value_m": finite_or_none(mean_decline, 3),
                },
                "max_decline": {
                    "score": finite_or_none(max_decline_score * 100, 1),
                    "value_m": finite_or_none(max_decline, 3),
                },
                "anomaly_frequency": {
                    "score": finite_or_none(anomaly_score * 100, 1),
                    "count": len(anomaly_years),
                    "years": anomaly_years,
                },
                "agricultural_pressure": {
                    "score": finite_or_none(pressure_score * 100, 1),
                    "simultaneous_pressure_year_count": len(
                        simultaneous_pressure_years
                    ),
                    "years": simultaneous_pressure_years,
                },
            },
            "evidence": [
                f"{stress_indicators['declining_year_count']} of {year_count} water years show decline.",
                f"Mean annual groundwater decline is {mean_decline:.2f} m.",
                f"{len(anomaly_years)} anomalous decline years were detected.",
                f"{len(simultaneous_pressure_years)} years combine agricultural growth signals with groundwater decline.",
            ],
        }

        return {
            "period": {
                "start_water_year": self._water_year_label(years[0]),
                "end_water_year": self._water_year_label(years[-1]),
                "water_year_count": len(years),
                "complete_year_count": complete_years,
                "partial_year_count": partial_years,
                "groundwater_method": "piezometric_surface_idw",
                "ndvi_window": "khordad-shahrivar",
                "water_year_labels": water_year_labels,
            },
            "trend_statistics": trends,
            "correlations": correlations,
            "lag_analysis": lag_analysis,
            "stress_indicators": stress_indicators,
            "agricultural_pressure": {
                "irrigated_area_trend": irrigated_area_trend,
                "ndvi_trend": ndvi_trend,
                "joint_growth_index": joint_summary,
            },
            "risk_assessment": risk_assessment,
            "driver_classification": {
                "label": driver_label,
                "confidence": confidence,
                "confidence_score": finite_or_none(confidence_score, 2),
                "climate_score": finite_or_none(climate_score, 2),
                "human_score": finite_or_none(human_score, 2),
                "reason": driver_reason,
                "rationale": rationale,
                "signals": {
                    "precipitation_strength": finite_or_none(precip_strength, 2),
                    "agricultural_trend_strength": ag_trend_strength,
                    "decline_persistence": finite_or_none(decline_persistence, 2),
                    "simultaneous_pressure_years": joint_summary[
                        "simultaneous_pressure_years"
                    ],
                },
            },
            "llm_input": {
                "trend_statistics": trends,
                "correlations": correlations,
                "lag_analysis": lag_analysis,
                "stress_indicators": stress_indicators,
                "risk_assessment": risk_assessment,
                "anomaly_years": stress_indicators[
                    "groundwater_decline_anomaly_years"
                ],
            },
        }

    def _aquifer_annual_rows(
        self,
        arithmetic_values: dict[int, float],
        thiessen_values: dict[int, float],
        piezometric_surface_values: dict[int, float],
        start_year: int,
        end_year: int,
        storage_coefficient: float | None = None,
        aquifer_area_m2: float | None = None,
    ) -> list[dict[str, Any]]:
        arithmetic_rows = self._annual_decline_rows(
            arithmetic_values,
            start_year,
            end_year,
        )
        thiessen_rows = self._annual_decline_rows(
            thiessen_values,
            start_year,
            end_year,
        )
        piezometric_surface_rows = self._annual_decline_rows(
            piezometric_surface_values,
            start_year,
            end_year,
        )

        def with_storage(row: dict[str, Any]) -> dict[str, Any]:
            result = {
                key: value
                for key, value in row.items()
                if key not in {"water_year", "start_month", "end_month"}
            }
            decline = result.get("decline")
            cumulative_decline = result.get("cumulative_decline")
            can_calculate_storage = (
                storage_coefficient is not None
                and aquifer_area_m2 is not None
                and np.isfinite(storage_coefficient)
                and np.isfinite(aquifer_area_m2)
            )
            result["storage_change_mcm"] = (
                finite_or_none(
                    float(decline) * float(storage_coefficient) * float(aquifer_area_m2)
                    / 1_000_000,
                    3,
                )
                if can_calculate_storage
                and decline is not None
                and np.isfinite(decline)
                else None
            )
            result["cumulative_storage_change_mcm"] = (
                finite_or_none(
                    float(cumulative_decline)
                    * float(storage_coefficient)
                    * float(aquifer_area_m2)
                    / 1_000_000,
                    3,
                )
                if can_calculate_storage
                and cumulative_decline is not None
                and np.isfinite(cumulative_decline)
                else None
            )
            return result

        rows = []
        for arithmetic, thiessen, piezometric_surface in zip(
            arithmetic_rows,
            thiessen_rows,
            piezometric_surface_rows,
        ):
            rows.append(
                {
                    "water_year": arithmetic["water_year"],
                    "arithmetic": with_storage(arithmetic),
                    "thiessen": with_storage(thiessen),
                    "piezometric_surface": with_storage(piezometric_surface),
                    "start_month": arithmetic["start_month"],
                    "arithmetic_end_month": arithmetic["end_month"],
                    "thiessen_end_month": thiessen["end_month"],
                    "piezometric_surface_end_month": piezometric_surface["end_month"],
                }
            )
        return rows

    def _annual_change_rows(
        self,
        months: list[tuple[int, str]],
        annual_decline: list[dict[str, Any]],
        surface_method_annual_decline: dict[str, list[dict[str, Any]]] | None,
        precipitation: dict[str, Any],
        aet: dict[str, Any],
        ndvi: dict[str, Any],
        warm_season_irrigated_area: dict[
            int,
            dict[str, float | bool | None],
        ],
    ) -> list[dict[str, Any]]:
        month_indexes = {label: index for index, label in months}
        selected_indexes = set(month_indexes.values())
        precipitation_values = dict(precipitation["series"])
        aet_values = dict(aet["series"])
        ndvi_mean_values = dict(ndvi["metrics"]["mean"])
        ndvi_median_values = dict(ndvi["metrics"]["median"])
        decline_by_year = {
            row["water_year"]: row
            for row in annual_decline
        }
        surface_decline_by_method = {
            method: {
                row["water_year"]: row
                for row in rows
                if row.get("water_year")
            }
            for method, rows in (surface_method_annual_decline or {}).items()
        }
        water_years = sorted({
            self._water_year_for_month(
                (index - 1) // MONTHS_PER_YEAR,
                (index - 1) % MONTHS_PER_YEAR + 1,
            )
            for index in selected_indexes
        })
        rows: list[dict[str, Any]] = []
        for water_year in water_years:
            expected_indexes = set(range(
                water_year * MONTHS_PER_YEAR + WATER_YEAR_START_MONTH,
                (water_year + 1) * MONTHS_PER_YEAR + WATER_YEAR_END_MONTH + 1,
            ))
            indexes = sorted(selected_indexes & expected_indexes)
            labels = [
                f"{(index - 1) // MONTHS_PER_YEAR}-"
                f"{((index - 1) % MONTHS_PER_YEAR) + 1:02d}"
                for index in indexes
            ]
            warm_month_labels = [
                label
                for index, label in zip(indexes, labels)
                if ((index - 1) % MONTHS_PER_YEAR) + 1 in NDVI_WARM_MONTHS
            ]

            def valid_values(
                series: dict[str, Any],
                selected_labels: list[str] = labels,
            ) -> list[float]:
                return [
                    float(series[label])
                    for label in selected_labels
                    if series.get(label) is not None
                    and np.isfinite(series[label])
                ]

            precipitation_items = valid_values(precipitation_values)
            aet_items = valid_values(aet_values)
            ndvi_mean_items = valid_values(ndvi_mean_values)
            ndvi_median_items = valid_values(ndvi_median_values)
            warm_ndvi_mean_items = valid_values(
                ndvi_mean_values,
                warm_month_labels,
            )
            warm_ndvi_median_items = valid_values(
                ndvi_median_values,
                warm_month_labels,
            )
            water_year_label = f"{water_year}-{water_year + 1}"
            decline = decline_by_year.get(water_year_label, {})
            method_decline = {
                method: rows.get(water_year_label, {})
                for method, rows in surface_decline_by_method.items()
            }
            warm_season_year = water_year + 1
            irrigated_area = warm_season_irrigated_area.get(
                warm_season_year,
                {},
            )
            decline_values = {
                "arithmetic": decline.get("arithmetic", {}).get("decline"),
                "thiessen": decline.get("thiessen", {}).get("decline"),
                "piezometric_surface": decline.get(
                    "piezometric_surface",
                    {},
                ).get("decline"),
            }
            storage_values = {
                "arithmetic": decline.get("arithmetic", {}).get(
                    "storage_change_mcm"
                ),
                "thiessen": decline.get("thiessen", {}).get(
                    "storage_change_mcm"
                ),
                "piezometric_surface": decline.get(
                    "piezometric_surface",
                    {},
                ).get("storage_change_mcm"),
            }
            for method, method_row in method_decline.items():
                decline_values[method] = method_row.get("decline")
                storage_values[method] = method_row.get("storage_change_mcm")
            rows.append({
                "water_year": water_year_label,
                "is_complete": len(indexes) == MONTHS_PER_YEAR,
                "selected_month_count": len(indexes),
                "precipitation_month_count": len(precipitation_items),
                "aet_month_count": len(aet_items),
                "ndvi_mean_month_count": len(ndvi_mean_items),
                "ndvi_median_month_count": len(ndvi_median_items),
                "decline": decline_values,
                "storage_change_mcm": storage_values,
                "precipitation_total": finite_or_none(
                    sum(precipitation_items)
                    if precipitation_items
                    else None,
                ),
                "aet_total": finite_or_none(
                    sum(aet_items) if aet_items else None,
                ),
                "warm_season_irrigated_area": {
                    "jalali_year": warm_season_year,
                    "probable_area_ha": irrigated_area.get(
                        "probable_area_ha"
                    ),
                    "analysis_area_ha": irrigated_area.get(
                        "analysis_area_ha"
                    ),
                    "valid_observation_area_ha": irrigated_area.get(
                        "valid_observation_area_ha"
                    ),
                    "probable_percent": irrigated_area.get(
                        "probable_percent"
                    ),
                    "valid_percent": irrigated_area.get("valid_percent"),
                    "has_valid_observations": irrigated_area.get(
                        "has_valid_observations",
                        False,
                    ),
                },
                "ndvi_mean": finite_or_none(
                    np.mean(ndvi_mean_items) if ndvi_mean_items else None,
                    4,
                ),
                "ndvi_median": finite_or_none(
                    np.mean(ndvi_median_items) if ndvi_median_items else None,
                    4,
                ),
                "ndvi_periods": {
                    "warm_months": {
                        "expected_month_count": len(NDVI_WARM_MONTHS),
                        "selected_month_count": len(warm_month_labels),
                        "is_complete": (
                            len(warm_month_labels) == len(NDVI_WARM_MONTHS)
                        ),
                        "mean_month_count": len(warm_ndvi_mean_items),
                        "median_month_count": len(warm_ndvi_median_items),
                        "mean": finite_or_none(
                            np.mean(warm_ndvi_mean_items)
                            if warm_ndvi_mean_items
                            else None,
                            4,
                        ),
                        "median": finite_or_none(
                            np.mean(warm_ndvi_median_items)
                            if warm_ndvi_median_items
                            else None,
                            4,
                        ),
                    },
                    "full_year": {
                        "expected_month_count": MONTHS_PER_YEAR,
                        "selected_month_count": len(labels),
                        "is_complete": len(labels) == MONTHS_PER_YEAR,
                        "mean_month_count": len(ndvi_mean_items),
                        "median_month_count": len(ndvi_median_items),
                        "mean": finite_or_none(
                            np.mean(ndvi_mean_items)
                            if ndvi_mean_items
                            else None,
                            4,
                        ),
                        "median": finite_or_none(
                            np.mean(ndvi_median_items)
                            if ndvi_median_items
                            else None,
                            4,
                        ),
                    },
                },
            })
        return rows

    def _hydrographs(
        self,
        frame: pd.DataFrame,
        months: list[tuple[int, str]],
        weights: dict[str, float],
        piezometric_surface_values: dict[int, float],
    ) -> tuple[
        list[list[Any]],
        list[list[Any]],
        list[list[Any]],
        dict[int, float],
        dict[int, float],
        dict[int, float],
    ]:
        month_labels = dict(months)
        arithmetic_values, thiessen_values = self._hydrograph_value_maps(
            frame,
            weights,
        )

        arithmetic_series = [
            [month_labels[index], finite_or_none(arithmetic_values.get(index))]
            for index, _ in months
        ]
        thiessen_series = [
            [month_labels[index], finite_or_none(thiessen_values.get(index))]
            for index, _ in months
        ]
        piezometric_surface_series = [
            [
                month_labels[index],
                finite_or_none(piezometric_surface_values.get(index)),
            ]
            for index, _ in months
        ]
        return (
            arithmetic_series,
            thiessen_series,
            piezometric_surface_series,
            arithmetic_values,
            thiessen_values,
            piezometric_surface_values,
        )

    def _well_payload(
        self,
        group_id: str,
        group_monthly: pd.DataFrame,
        range_frame: pd.DataFrame,
        months: list[tuple[int, str]],
        comparison_frame: pd.DataFrame,
        comparison_months: list[tuple[int, str]],
        selected_join_keys: set[str],
        requested_well_ids: set[str],
        continuous_only: bool,
        manual_selection: bool,
        comparison_enabled: bool,
        start_water_year: int,
        end_water_year: int,
    ) -> list[dict[str, Any]]:
        locations = self.locations[self.locations["_aquifer_id"] == group_id]
        by_join_key = {
            key: group.sort_values("_month_index")
            for key, group in range_frame.groupby("_join_key", sort=False)
        }
        comparison_by_join_key = {
            key: group.sort_values("_month_index")
            for key, group in comparison_frame.groupby("_join_key", sort=False)
        }
        all_group_monthly = {
            key: group.sort_values("_month_index")
            for key, group in group_monthly.groupby("_join_key", sort=False)
        }
        all_data_keys = set(all_group_monthly)
        month_indexes = [index for index, _ in months]
        month_labels = dict(months)
        wells: list[dict[str, Any]] = []
        duplicate_counter: dict[str, int] = {}
        for _, row in locations.iterrows():
            join_key = row["_join_key"]
            duplicate_counter[join_key] = duplicate_counter.get(join_key, 0) + 1
            full_series_frame = all_group_monthly.get(join_key)
            all_values = (
                dict(
                    full_series_frame[["_month_index", "level"]].itertuples(
                        index=False, name=None
                    )
                )
                if full_series_frame is not None
                else {}
            )
            series_frame = by_join_key.get(join_key)
            values = (
                dict(
                    series_frame[["_month_index", "level"]].itertuples(
                        index=False, name=None
                    )
                )
                if series_frame is not None
                else {}
            )
            display_values = {
                index: value for index, value in values.items() if index in month_indexes
            }
            observed_month_count = sum(
                1
                for value in display_values.values()
                if value is not None and np.isfinite(value)
            )
            expected_month_count = len(month_indexes)
            has_complete_range_data = (
                expected_month_count > 0
                and observed_month_count == expected_month_count
            )
            comparison_series_frame = comparison_by_join_key.get(join_key)
            comparison_values = (
                dict(
                    comparison_series_frame[["_month_index", "level"]].itertuples(
                        index=False, name=None
                    )
                )
                if comparison_series_frame is not None
                else {}
            )
            series = [
                [month_labels[index], finite_or_none(display_values.get(index))]
                for index in month_indexes
            ]
            has_any_data = join_key in all_data_keys
            has_range_data = bool(display_values)
            selected = row["_well_id"] in requested_well_ids if manual_selection else False
            included = join_key in selected_join_keys
            if not has_any_data:
                status = "no_data"
                exclusion_reason = "فاقد هرگونه داده اندازه‌گیری"
            elif included:
                status = "included"
                exclusion_reason = None
            elif manual_selection and selected and not has_range_data:
                status = "excluded"
                exclusion_reason = "انتخاب شده، اما در بازه انتخابی داده‌ای ندارد"
            elif manual_selection and has_range_data:
                status = "excluded"
                exclusion_reason = "در انتخاب دستی محاسبات آبخوان قرار نگرفته است"
            elif continuous_only and has_range_data:
                status = "excluded"
                exclusion_reason = "پوشش داده، کل بازه انتخابی را در بر نمی‌گیرد"
            else:
                status = "excluded"
                exclusion_reason = "در بازه انتخابی داده‌ای ندارد"
            wells.append(
                {
                    "id": row["_well_id"],
                    "name": row["LOCATION"],
                    "name_suffix": duplicate_counter[join_key],
                    "longitude": finite_or_none(row["X"], 6),
                    "latitude": finite_or_none(row["Y"], 6),
                    "elevation": finite_or_none(row["LEVEL_MSL"]),
                    "has_data": has_any_data,
                    "has_range_data": has_range_data,
                    "has_complete_range_data": has_complete_range_data,
                    "observed_month_count": observed_month_count,
                    "expected_month_count": expected_month_count,
                    "selected": selected or included,
                    "included": included,
                    "status": status,
                    "exclusion_reason": exclusion_reason,
                    "available_month_indexes": sorted(
                        int(index)
                        for index, value in all_values.items()
                        if value is not None and np.isfinite(value)
                    ),
                    "series": series,
                    "trend": self._trend(display_values, months),
                    "comparison_trend": (
                        self._trend(comparison_values, comparison_months)
                        if comparison_enabled
                        else None
                    ),
                    "annual_decline": self._annual_decline_rows(
                        values,
                        start_water_year,
                        end_water_year,
                    ),
                }
            )
        return wells

    def dashboard(
        self,
        group_id: str,
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
        corrected_support_method: str = "fixed_thiessen",
    ) -> dict[str, Any]:
        if group_id not in self.groups:
            raise KeyError(group_id)
        if storage_coefficient is not None and (
            not np.isfinite(storage_coefficient) or storage_coefficient <= 0
        ):
            raise ValueError("ضریب ذخیره/آبدهی ویژه باید عددی مثبت باشد")
        if surface_interpolation_method not in SURFACE_INTERPOLATION_METHODS:
            raise ValueError("روش درون‌یابی سطح پیزومتریک معتبر نیست")
        if corrected_support_method not in CORRECTED_SUPPORT_METHODS:
            raise ValueError("روش پشتیبان ثابت اصلاح هیدروگراف معتبر نیست")
        selected_surface_methods = self._normalize_surface_methods(
            surface_interpolation_methods,
            surface_interpolation_method,
        )
        primary_surface_method = selected_surface_methods[0]
        (
            start_year_value,
            start_month_value,
            end_year_value,
            end_month_value,
        ) = self._validate_period(
            group_id,
            start_year,
            start_month,
            end_year,
            end_month,
        )
        months = self._period_months(
            start_year_value,
            start_month_value,
            end_year_value,
            end_month_value,
        )
        start_index = months[0][0]
        end_index = months[-1][0]
        (
            comparison_start_year_value,
            comparison_start_month_value,
            comparison_end_year_value,
            comparison_end_month_value,
        ) = self._validate_trend_comparison_period(
            group_id,
            start_index,
            end_index,
            comparison_start_year,
            comparison_start_month,
            comparison_end_year,
            comparison_end_month,
        )
        comparison_months = self._period_months(
            comparison_start_year_value,
            comparison_start_month_value,
            comparison_end_year_value,
            comparison_end_month_value,
        )
        comparison_start_index = comparison_months[0][0]
        comparison_end_index = comparison_months[-1][0]
        start_water_year = self._water_year_for_month(
            start_year_value,
            start_month_value,
        )
        end_water_year = self._water_year_for_month(
            end_year_value,
            end_month_value,
        )
        annual_end_water_year = (
            end_water_year - 1
            if end_month_value == WATER_YEAR_START_MONTH
            else end_water_year
        )
        group = self.groups[group_id]
        group_monthly = self.monthly[self.monthly["_aquifer_id"] == group_id]
        requested_well_ids = set(selected_well_ids or [])
        display_frame = group_monthly[
            (group_monthly["_month_index"] >= start_index)
            & (group_monthly["_month_index"] <= end_index)
        ]
        selected_join_keys = (
            self._manual_selected_join_keys(
                group_id,
                display_frame,
                selected_well_ids,
            )
            if manual_selection
            else self._selected_join_keys(
                group_monthly,
                start_index,
                end_index,
                continuous_only,
            )
        )
        display_calculation_frame = display_frame[
            display_frame["_join_key"].isin(selected_join_keys)
        ]
        comparison_frame = group_monthly[
            (group_monthly["_month_index"] >= comparison_start_index)
            & (group_monthly["_month_index"] <= comparison_end_index)
        ]
        comparison_calculation_frame = comparison_frame[
            comparison_frame["_join_key"].isin(selected_join_keys)
        ]
        selected_sites = self._selected_sites(group_id, selected_join_keys)
        weights, thiessen_polygons = self._calculate_thiessen(
            group_id,
            selected_sites,
        )
        surface_methods: dict[str, dict[str, Any]] = {}
        piezometric_surface_values: dict[int, float] = {}
        piezometric_surface_metadata: dict[str, Any] = {}
        comparison_piezometric_surface_values: dict[int, float] = {}
        for method in selected_surface_methods:
            method_values, method_metadata = self._piezometric_surface_value_map(
                group_id,
                display_calculation_frame,
                selected_sites,
                method,
            )
            method_comparison_values: dict[int, float] = {}
            if comparison_enabled:
                method_comparison_values, _ = self._piezometric_surface_value_map(
                    group_id,
                    comparison_calculation_frame,
                    selected_sites,
                    method,
                )
            method_trend = self._trend(method_values, months)
            method_comparison_trend = (
                self._trend(method_comparison_values, comparison_months)
                if comparison_enabled
                else None
            )
            method_annual_decline = self._apply_storage_to_annual_rows(
                self._annual_decline_rows(
                    method_values,
                    start_water_year,
                    annual_end_water_year,
                ),
                storage_coefficient,
                method_metadata["area_m2"],
            )
            surface_methods[method] = {
                "metadata": method_metadata,
                "series": self._series_from_values(months, method_values),
                "values": method_values,
                "trend": method_trend,
                "comparison_trend": method_comparison_trend,
                "annual_decline": method_annual_decline,
                "five_year_scenario": self._five_year_scenario(
                    method_values,
                    months,
                    method_trend,
                    method,
                ),
            }
            if method == primary_surface_method:
                piezometric_surface_values = method_values
                piezometric_surface_metadata = method_metadata
                comparison_piezometric_surface_values = method_comparison_values
        (
            arithmetic,
            thiessen,
            piezometric_surface,
            arithmetic_values,
            thiessen_values,
            piezometric_surface_values,
        ) = self._hydrographs(
            display_calculation_frame,
            months,
            weights,
            piezometric_surface_values,
        )
        corrected_analysis = self._corrected_analysis_payload(
            group_id,
            months,
            display_calculation_frame,
            selected_join_keys,
            manual_selection,
            weights,
            arithmetic_values,
            thiessen_values,
            surface_methods,
            primary_surface_method,
            corrected_support_method,
            start_water_year,
            annual_end_water_year,
            storage_coefficient,
            piezometric_surface_metadata["area_m2"],
        )
        (
            comparison_arithmetic_values,
            comparison_thiessen_values,
        ) = self._hydrograph_value_maps(
            comparison_calculation_frame,
            weights,
        )
        aquifer_annual_decline = self._aquifer_annual_rows(
            arithmetic_values,
            thiessen_values,
            piezometric_surface_values,
            start_water_year,
            annual_end_water_year,
            storage_coefficient=storage_coefficient,
            aquifer_area_m2=piezometric_surface_metadata["area_m2"],
        )
        wells = self._well_payload(
            group_id,
            group_monthly,
            display_frame,
            months,
            comparison_frame,
            comparison_months,
            selected_join_keys,
            requested_well_ids,
            continuous_only,
            manual_selection,
            comparison_enabled,
            start_water_year,
            annual_end_water_year,
        )
        latest_corrected_status: dict[str, dict[str, Any]] = {}
        for row in corrected_analysis["corrected_well_month"]:
            latest_corrected_status[row["well_id"]] = row
        for well in wells:
            latest = latest_corrected_status.get(well["id"], {})
            well["monitoring_status"] = latest.get("status", well["status"])
            well["latest_corrected_value"] = latest.get("corrected_value")
            well["latest_measurement_limit"] = latest.get("measurement_limit")
            well["latest_uncertainty"] = latest.get("uncertainty")
        precipitation = self._precipitation_payload(group_id, months)
        ndvi = self._ndvi_payload(group_id, months)
        aet = self._aet_payload(group_id, months)
        warm_season_irrigated_area = (
            self._warm_season_irrigated_area_payload(group_id)
        )
        annual_changes = self._annual_change_rows(
            months,
            aquifer_annual_decline,
            {
                method: payload["annual_decline"]
                for method, payload in surface_methods.items()
            },
            precipitation,
            aet,
            ndvi,
            warm_season_irrigated_area,
        )
        time_series_analysis = self._time_series_analysis(annual_changes)
        arithmetic_trend = self._trend(arithmetic_values, months)
        thiessen_trend = self._trend(thiessen_values, months)
        piezometric_surface_trend = self._trend(
            piezometric_surface_values,
            months,
        )
        arithmetic_comparison_trend = (
            self._trend(comparison_arithmetic_values, comparison_months)
            if comparison_enabled
            else None
        )
        thiessen_comparison_trend = (
            self._trend(comparison_thiessen_values, comparison_months)
            if comparison_enabled
            else None
        )
        piezometric_surface_comparison_trend = (
            self._trend(comparison_piezometric_surface_values, comparison_months)
            if comparison_enabled
            else None
        )
        five_year_scenario = {
            "arithmetic": self._five_year_scenario(
                arithmetic_values,
                months,
                arithmetic_trend,
                "arithmetic",
            ),
            "thiessen": self._five_year_scenario(
                thiessen_values,
                months,
                thiessen_trend,
                "thiessen",
            ),
            "piezometric_surface": self._five_year_scenario(
                piezometric_surface_values,
                months,
                piezometric_surface_trend,
                "piezometric_surface",
            ),
        }
        group_minimum = int(group_monthly["_month_index"].min())
        group_maximum = int(group_monthly["_month_index"].max())
        active_wells = sum(well["has_range_data"] for well in wells)
        selected_wells = sum(well["included"] for well in wells)
        arithmetic_observations = [item[1] for item in arithmetic if item[1] is not None]
        change = (
            finite_or_none(arithmetic_observations[-1] - arithmetic_observations[0])
            if len(arithmetic_observations) > 1
            else None
        )
        primary_surface_payload = surface_methods[primary_surface_method]
        return {
            "id": group_id,
            "mahdoude": group["mahdoude"],
            "aquifer": group["aquifer"],
            "stats": {
                "total_wells": len(wells),
                "active_wells": active_wells,
                "inactive_wells": len(wells) - active_wells,
                "selected_wells": selected_wells,
                "excluded_wells": len(wells) - selected_wells,
                "selected_sites": len(weights),
                "first_month": months[0][1],
                "last_month": months[-1][1],
                "change": change,
            },
            "filters": {
                "minimum_year": int(
                    (group_minimum - 1) // MONTHS_PER_YEAR
                ),
                "minimum_month": int(
                    (group_minimum - 1) % MONTHS_PER_YEAR + 1
                ),
                "maximum_year": int(
                    (group_maximum - 1) // MONTHS_PER_YEAR
                ),
                "maximum_month": int(
                    (group_maximum - 1) % MONTHS_PER_YEAR + 1
                ),
                "start_year": start_year_value,
                "start_month": start_month_value,
                "end_year": end_year_value,
                "end_month": end_month_value,
                "comparison_start_year": comparison_start_year_value,
                "comparison_start_month": comparison_start_month_value,
                "comparison_end_year": comparison_end_year_value,
                "comparison_end_month": comparison_end_month_value,
                "comparison_enabled": comparison_enabled,
                "start_water_year": start_water_year,
                "end_water_year": end_water_year,
                "continuous_only": continuous_only,
                "manual_selection": manual_selection,
                "selected_well_ids": (
                    sorted(requested_well_ids)
                    if manual_selection
                    else [well["id"] for well in wells if well["included"]]
                ),
                "storage_coefficient": storage_coefficient,
                "surface_interpolation_method": primary_surface_method,
                "surface_interpolation_methods": selected_surface_methods,
                "corrected_support_method": corrected_support_method,
            },
            "calendar": {
                "months_per_year": MONTHS_PER_YEAR,
                "water_year_start_month": WATER_YEAR_START_MONTH,
                "water_year_end_month": WATER_YEAR_END_MONTH,
                "default_analysis_years": DEFAULT_ANALYSIS_YEARS,
                "timeline_months": self._timeline_months(group_minimum, group_maximum),
            },
            "boundaries": {
                "mahdoude": self._feature_json(self.boundary_matches[group_id]["mahdoude"]),
                "aquifer": self._feature_json(self.boundary_matches[group_id]["aquifer"]),
            },
            "thiessen_polygons": thiessen_polygons,
            "hydrographs": {
                "arithmetic": arithmetic,
                "thiessen": thiessen,
                "piezometric_surface": piezometric_surface,
                "arithmetic_trend": arithmetic_trend,
                "thiessen_trend": thiessen_trend,
                "piezometric_surface_trend": piezometric_surface_trend,
                "arithmetic_comparison_trend": arithmetic_comparison_trend,
                "thiessen_comparison_trend": thiessen_comparison_trend,
                "piezometric_surface_comparison_trend": (
                    piezometric_surface_comparison_trend
                ),
            },
            "corrected": corrected_analysis,
            "corrected_hydrograph": corrected_analysis["corrected_hydrograph"],
            "corrected_well_month": corrected_analysis["corrected_well_month"],
            "network_transitions": corrected_analysis["network_transitions"],
            "piezometric_surface": primary_surface_payload["metadata"],
            "surface_methods": {
                method: {
                    "metadata": payload["metadata"],
                    "series": payload["series"],
                    "trend": payload["trend"],
                    "comparison_trend": payload["comparison_trend"],
                    "annual_decline": payload["annual_decline"],
                    "five_year_scenario": payload["five_year_scenario"],
                }
                for method, payload in surface_methods.items()
            },
            "storage": {
                "coefficient": storage_coefficient,
                "area_m2": primary_surface_payload["metadata"]["area_m2"],
                "area_km2": primary_surface_payload["metadata"]["area_km2"],
                "unit": "میلیون مترمکعب",
                "formula": "ΔS = Sy × Area × ΔH",
            },
            "five_year_scenario": five_year_scenario,
            "annual_decline": aquifer_annual_decline,
            "annual_changes": annual_changes,
            "time_series_analysis": time_series_analysis,
            "precipitation": precipitation,
            "ndvi": ndvi,
            "aet": aet,
            "wells": wells,
        }

    def comparison(
        self,
        start_year: int | None = None,
        start_month: int | None = None,
        end_year: int | None = None,
        end_month: int | None = None,
        corrected_support_method: str = "fixed_thiessen",
    ) -> dict[str, Any]:
        (
            start_year_value,
            start_month_value,
            end_year_value,
            end_month_value,
        ) = self._validate_comparison_period(
            start_year,
            start_month,
            end_year,
            end_month,
        )
        months = self._period_months(
            start_year_value,
            start_month_value,
            end_year_value,
            end_month_value,
        )
        start_water_year = self._water_year_for_month(
            start_year_value,
            start_month_value,
        )
        end_water_year = self._water_year_for_month(
            end_year_value,
            end_month_value,
        )
        annual_end_water_year = (
            end_water_year - 1
            if end_month_value == WATER_YEAR_START_MONTH
            else end_water_year
        )
        start_index = months[0][0]
        end_index = months[-1][0]
        minimum, maximum = self._comparison_period_bounds()
        aquifers = []
        method_order = [
            "thiessen",
            "arithmetic",
            *SURFACE_INTERPOLATION_METHOD_ORDER,
            "corrected_thiessen",
            "corrected_arithmetic",
            *[
                f"corrected_{method}"
                for method in SURFACE_INTERPOLATION_METHOD_ORDER
            ],
        ]
        method_labels = {
            "thiessen": "تیسن",
            "arithmetic": "حسابی",
            **{
                method: SURFACE_INTERPOLATION_LABELS[method]
                for method in SURFACE_INTERPOLATION_METHOD_ORDER
            },
            "corrected_thiessen": "اصلاح‌شده تیسن",
            "corrected_arithmetic": "اصلاح‌شده حسابی",
            **{
                f"corrected_{method}": (
                    f"اصلاح‌شده {SURFACE_INTERPOLATION_LABELS[method]}"
                )
                for method in SURFACE_INTERPOLATION_METHOD_ORDER
            },
        }

        for group_id, group in self.groups.items():
            group_frame = self.monthly[self.monthly["_aquifer_id"] == group_id]
            selected_join_keys = self._selected_join_keys(
                group_frame,
                start_index,
                end_index,
                continuous_only=True,
            )
            display_frame = group_frame[
                (group_frame["_month_index"] >= start_index)
                & (group_frame["_month_index"] <= end_index)
                & (group_frame["_join_key"].isin(selected_join_keys))
            ]
            selected_sites = self._selected_sites(group_id, selected_join_keys)
            weights, _ = self._calculate_thiessen(group_id, selected_sites)
            selected_well_count = int(
                len(
                    self.locations[
                        (self.locations["_aquifer_id"] == group_id)
                        & (self.locations["_join_key"].isin(selected_join_keys))
                    ]
                )
            )
            arithmetic_values, thiessen_values = self._hydrograph_value_maps(
                display_frame,
                weights,
            )
            surface_methods: dict[str, dict[str, Any]] = {}
            primary_surface_method = SURFACE_INTERPOLATION_METHOD_ORDER[0]
            for method in SURFACE_INTERPOLATION_METHOD_ORDER:
                method_values, method_metadata = self._piezometric_surface_value_map(
                    group_id,
                    display_frame,
                    selected_sites,
                    method,
                )
                surface_methods[method] = {
                    "values": method_values,
                    "metadata": method_metadata,
                }
            corrected_analysis = self._corrected_analysis_payload(
                group_id,
                months,
                display_frame,
                selected_join_keys,
                False,
                weights,
                arithmetic_values,
                thiessen_values,
                surface_methods,
                primary_surface_method,
                corrected_support_method,
                start_water_year,
                annual_end_water_year,
                None,
                surface_methods[primary_surface_method]["metadata"]["area_m2"],
            )

            def method_metrics(values: dict[int, float]) -> dict[str, Any]:
                start_level = finite_or_none(values.get(start_index))
                end_level = finite_or_none(values.get(end_index))
                observed_decline = (
                    finite_or_none(start_level - end_level)
                    if start_level is not None and end_level is not None
                    else None
                )
                trend = self._trend(values, months)
                return {
                    "start_level": start_level,
                    "end_level": end_level,
                    "observed_decline": observed_decline,
                    "trend_decline_per_year": trend["decline_per_year"],
                    "trend_direction": trend["direction"],
                }
            methods = {
                "thiessen": method_metrics(thiessen_values),
                "arithmetic": method_metrics(arithmetic_values),
                **{
                    method: method_metrics(payload["values"])
                    for method, payload in surface_methods.items()
                },
                **{
                    method: method_metrics(values)
                    for method, values in corrected_analysis.get(
                        "value_maps",
                        {},
                    ).items()
                },
            }

            aquifers.append(
                {
                    "id": group_id,
                    "mahdoude": group["mahdoude"],
                    "aquifer": group["aquifer"],
                    "total_wells": group["well_count"],
                    "selected_wells": selected_well_count,
                    "selected_sites": len(weights),
                    "methods": methods,
                    "geometry": mapping(
                        self.boundary_matches[group_id]["aquifer"].geometry.simplify(
                            COMPARISON_GEOMETRY_TOLERANCE,
                            preserve_topology=True,
                        )
                    ),
                }
            )

        aquifers.sort(key=lambda item: (item["mahdoude"], item["aquifer"]))
        return {
            "filters": {
                "minimum_year": (minimum - 1) // MONTHS_PER_YEAR,
                "minimum_month": (minimum - 1) % MONTHS_PER_YEAR + 1,
                "maximum_year": (maximum - 1) // MONTHS_PER_YEAR,
                "maximum_month": (maximum - 1) % MONTHS_PER_YEAR + 1,
                "start_year": start_year_value,
                "start_month": start_month_value,
                "end_year": end_year_value,
                "end_month": end_month_value,
                "continuous_only": True,
                "selected_methods": method_order,
                "map_method": method_order[0],
                "corrected_support_method": corrected_support_method,
            },
            "calendar": {
                "months_per_year": MONTHS_PER_YEAR,
                "water_year_start_month": WATER_YEAR_START_MONTH,
                "water_year_end_month": WATER_YEAR_END_MONTH,
                "default_analysis_years": DEFAULT_ANALYSIS_YEARS,
            },
            "stats": {
                "aquifer_count": len(aquifers),
                "available_aquifers": {
                    method: {
                        metric: sum(
                            item["methods"][method][metric] is not None
                            for item in aquifers
                        )
                        for metric in (
                            "observed_decline",
                            "trend_decline_per_year",
                        )
                    }
                    for method in method_order
                },
            },
            "method_order": method_order,
            "method_labels": method_labels,
            "aquifers": aquifers,
        }


@lru_cache(maxsize=1)
def get_data_service() -> GroundwaterData:
    return GroundwaterData()
