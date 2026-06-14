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
from pyproj import Transformer
from shapely import voronoi_polygons
from shapely.geometry import MultiPoint, Point, mapping, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "Data"
MONTHS_PER_YEAR = 12
WATER_YEAR_START_MONTH = 7
WATER_YEAR_END_MONTH = 6
DEFAULT_ANALYSIS_YEARS = 4
NEAREST_PRECIPITATION_STATION_COUNT = 3
COMPARISON_GEOMETRY_TOLERANCE = 0.001

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
            end_index = (
                next_mehr_index
                if values.get(next_mehr_index) is not None
                else shahrivar_index
            )
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
                        else f"{year + 1}-{WATER_YEAR_END_MONTH:02d}"
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
        selected_join_keys: set[str],
        continuous_only: bool,
        manual_selection: bool,
        start_water_year: int,
        end_water_year: int,
    ) -> list[dict[str, Any]]:
        locations = self.locations[self.locations["_aquifer_id"] == group_id]
        by_join_key = {
            key: group.sort_values("_month_index")
            for key, group in range_frame.groupby("_join_key", sort=False)
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
            selected_join_keys,
            continuous_only,
            manual_selection,
            start_water_year,
            annual_end_water_year,
        )
        precipitation = self._precipitation_payload(group_id, months)
        ndvi = self._ndvi_payload(group_id, months)
        aet = self._aet_payload(group_id, months)
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
            },
            "annual_decline": aquifer_annual_decline,
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
