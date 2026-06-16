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
from scipy.stats import kendalltau, pearsonr, spearmanr, theilslopes
from pyproj import Transformer
from shapely import voronoi_polygons
from shapely.geometry import MultiPoint, Point, mapping, shape
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
                    "groundwater_decline_m": row.get("decline", {}).get("thiessen"),
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
                    "groundwater_method": "thiessen",
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
                "groundwater_method": "thiessen",
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
        start_year: int,
        end_year: int,
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
        rows = []
        for arithmetic, thiessen in zip(arithmetic_rows, thiessen_rows):
            rows.append(
                {
                    "water_year": arithmetic["water_year"],
                    "arithmetic": {
                        key: value
                        for key, value in arithmetic.items()
                        if key not in {"water_year", "start_month", "end_month"}
                    },
                    "thiessen": {
                        key: value
                        for key, value in thiessen.items()
                        if key not in {"water_year", "start_month", "end_month"}
                    },
                    "start_month": arithmetic["start_month"],
                    "arithmetic_end_month": arithmetic["end_month"],
                    "thiessen_end_month": thiessen["end_month"],
                }
            )
        return rows

    def _annual_change_rows(
        self,
        months: list[tuple[int, str]],
        annual_decline: list[dict[str, Any]],
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
            warm_season_year = water_year + 1
            irrigated_area = warm_season_irrigated_area.get(
                warm_season_year,
                {},
            )
            rows.append({
                "water_year": water_year_label,
                "is_complete": len(indexes) == MONTHS_PER_YEAR,
                "selected_month_count": len(indexes),
                "precipitation_month_count": len(precipitation_items),
                "aet_month_count": len(aet_items),
                "ndvi_mean_month_count": len(ndvi_mean_items),
                "ndvi_median_month_count": len(ndvi_median_items),
                "decline": {
                    "arithmetic": decline.get("arithmetic", {}).get("decline"),
                    "thiessen": decline.get("thiessen", {}).get("decline"),
                },
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
    ) -> tuple[list[list[Any]], list[list[Any]], dict[int, float], dict[int, float]]:
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
        return (
            arithmetic_series,
            thiessen_series,
            arithmetic_values,
            thiessen_values,
        )

    def _well_payload(
        self,
        group_id: str,
        range_frame: pd.DataFrame,
        months: list[tuple[int, str]],
        comparison_frame: pd.DataFrame,
        comparison_months: list[tuple[int, str]],
        selected_join_keys: set[str],
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
        all_data_keys = set(
            self.monthly[self.monthly["_aquifer_id"] == group_id]["_join_key"].unique()
        )
        month_indexes = [index for index, _ in months]
        month_labels = dict(months)
        wells: list[dict[str, Any]] = []
        duplicate_counter: dict[str, int] = {}
        for _, row in locations.iterrows():
            join_key = row["_join_key"]
            duplicate_counter[join_key] = duplicate_counter.get(join_key, 0) + 1
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
            included = join_key in selected_join_keys
            if not has_any_data:
                status = "no_data"
                exclusion_reason = "فاقد هرگونه داده اندازه‌گیری"
            elif included:
                status = "included"
                exclusion_reason = None
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
                    "included": included,
                    "status": status,
                    "exclusion_reason": exclusion_reason,
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
    ) -> dict[str, Any]:
        if group_id not in self.groups:
            raise KeyError(group_id)
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
        (
            arithmetic,
            thiessen,
            arithmetic_values,
            thiessen_values,
        ) = self._hydrographs(display_calculation_frame, months, weights)
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
            start_water_year,
            annual_end_water_year,
        )
        wells = self._well_payload(
            group_id,
            display_frame,
            months,
            comparison_frame,
            comparison_months,
            selected_join_keys,
            continuous_only,
            manual_selection,
            comparison_enabled,
            start_water_year,
            annual_end_water_year,
        )
        precipitation = self._precipitation_payload(group_id, months)
        ndvi = self._ndvi_payload(group_id, months)
        aet = self._aet_payload(group_id, months)
        warm_season_irrigated_area = (
            self._warm_season_irrigated_area_payload(group_id)
        )
        annual_changes = self._annual_change_rows(
            months,
            aquifer_annual_decline,
            precipitation,
            aet,
            ndvi,
            warm_season_irrigated_area,
        )
        time_series_analysis = self._time_series_analysis(annual_changes)
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
                "selected_well_ids": [
                    well["id"] for well in wells if well["included"]
                ],
            },
            "calendar": {
                "months_per_year": MONTHS_PER_YEAR,
                "water_year_start_month": WATER_YEAR_START_MONTH,
                "water_year_end_month": WATER_YEAR_END_MONTH,
                "default_analysis_years": DEFAULT_ANALYSIS_YEARS,
            },
            "boundaries": {
                "mahdoude": self._feature_json(self.boundary_matches[group_id]["mahdoude"]),
                "aquifer": self._feature_json(self.boundary_matches[group_id]["aquifer"]),
            },
            "thiessen_polygons": thiessen_polygons,
            "hydrographs": {
                "arithmetic": arithmetic,
                "thiessen": thiessen,
                "arithmetic_trend": self._trend(arithmetic_values, months),
                "thiessen_trend": self._trend(thiessen_values, months),
                "arithmetic_comparison_trend": (
                    self._trend(comparison_arithmetic_values, comparison_months)
                    if comparison_enabled
                    else None
                ),
                "thiessen_comparison_trend": (
                    self._trend(comparison_thiessen_values, comparison_months)
                    if comparison_enabled
                    else None
                ),
            },
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
        start_index = months[0][0]
        end_index = months[-1][0]
        minimum, maximum = self._comparison_period_bounds()
        aquifers = []

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

            aquifers.append(
                {
                    "id": group_id,
                    "mahdoude": group["mahdoude"],
                    "aquifer": group["aquifer"],
                    "total_wells": group["well_count"],
                    "selected_wells": selected_well_count,
                    "selected_sites": len(weights),
                    "methods": {
                        "thiessen": method_metrics(thiessen_values),
                        "arithmetic": method_metrics(arithmetic_values),
                    },
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
                    for method in ("thiessen", "arithmetic")
                },
            },
            "aquifers": aquifers,
        }


@lru_cache(maxsize=1)
def get_data_service() -> GroundwaterData:
    return GroundwaterData()
