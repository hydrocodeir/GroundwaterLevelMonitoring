"""Fast setup metadata using only Python's standard library in the browser."""
import csv
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

_CHARACTERS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "ؤ": "و", "أ": "ا", "إ": "ا"})
_SPACES = re.compile(r"[\s\u200c\u200d\u200e\u200f\u2066-\u2069_-]+")


def _name(value):
    return _SPACES.sub("", unicodedata.normalize("NFKC", str(value)).translate(_CHARACTERS)).strip()


def _join(row):
    return "|".join(_name(row[column]) for column in ("MAHDOUDE", "AQUIFER", "LOCATION"))


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _date(index):
    return (index - 1) // 12, (index - 1) % 12 + 1


class DashboardCatalog:
    def __init__(self, data_dir="/Data"):
        self.groups = {}
        self.months = {}
        self.bounds = {}
        self.elevations = {}
        with (Path(data_dir) / "LOCATION.csv").open(encoding="utf-8-sig", newline="") as handle:
            counters = {}
            for index, row in enumerate(csv.DictReader(handle)):
                key = _join(row)
                group_id = hashlib.sha1("|".join(key.split("|")[:2]).encode()).hexdigest()[:12]
                counters[key] = counters.get(key, 0) + 1
                elevation = _number(row["LEVEL_MSL"])
                self.elevations.setdefault(key, elevation)
                self.groups.setdefault(group_id, []).append({
                    "id": hashlib.sha1(f"{key}|{index}".encode()).hexdigest()[:12],
                    "name": row["LOCATION"], "name_suffix": counters[key],
                    "longitude": _number(row["X"]), "latitude": _number(row["Y"]),
                    "elevation": elevation, "_join": key,
                })
        with (Path(data_dir) / "DATA.csv").open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = _join(row)
                if self.elevations.get(key) is None or _number(row["WATER_TABLE"]) is None:
                    continue
                try:
                    year, month = int(float(row["YEAR_PERSIAN"])), int(float(row["MONTH_PERSIAN"]))
                except (ValueError, TypeError):
                    continue
                if 1 <= month <= 12:
                    self.months.setdefault(key, set()).add(year * 12 + month)

    def preview(self, group_id):
        if group_id not in self.groups:
            raise ValueError("آبخوان انتخاب‌شده پیدا نشد")
        available = set().union(*(self.months.get(well["_join"], set()) for well in self.groups[group_id]))
        if not available:
            raise ValueError("برای این آبخوان داده اندازه‌گیری موجود نیست")
        minimum, maximum = min(available), max(available)
        start = max(minimum, maximum - 48)
        start_year, start_month = _date(start)
        end_year, end_month = _date(maximum)
        comparison_start = max(start, maximum - 11)
        comparison_year, comparison_month = _date(comparison_start)
        wells = []
        for well in self.groups[group_id]:
            indexes = sorted(self.months.get(well["_join"], set()))
            count = sum(start <= index <= maximum for index in indexes)
            wells.append({
                **{key: value for key, value in well.items() if not key.startswith("_")},
                "available_month_indexes": indexes,
                "has_data": bool(indexes), "has_range_data": count > 0,
                "has_complete_range_data": count == maximum - start + 1,
                "observed_month_count": count, "selected": False, "included": False,
            })
        return {
            "id": group_id, "preview": True, "wells": wells,
            "filters": {
                "minimum_year": _date(minimum)[0], "minimum_month": _date(minimum)[1],
                "maximum_year": end_year, "maximum_month": end_month,
                "start_year": start_year, "start_month": start_month,
                "end_year": end_year, "end_month": end_month,
                "comparison_start_year": comparison_year, "comparison_start_month": comparison_month,
                "comparison_end_year": end_year, "comparison_end_month": end_month,
                "comparison_enabled": False, "manual_selection": True,
                "selected_well_ids": [], "well_tail_settings": {},
                "base_hydrograph_methods": ["thiessen"],
                "surface_interpolation_methods": ["idw"], "surface_interpolation_method": "idw",
                "corrected_support_method": "none", "storage_coefficient": None,
            },
            "calendar": {
                "months_per_year": 12, "water_year_start_month": 7, "water_year_end_month": 6,
                "timeline_months": [{"index": index, "label": f"{_date(index)[0]}-{_date(index)[1]:02d}"}
                                    for index in range(minimum, maximum + 1)],
            },
        }
