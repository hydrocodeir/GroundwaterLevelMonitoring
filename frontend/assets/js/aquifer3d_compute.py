"""Client-side aquifer sections. Executed only by the Pyodide web worker.

Input measurements are depths below each well's recorded ground elevation.
The two dates always use the same wells so changes are not driven by a
changing monitoring network. Neyshabur's built-in bedrock depths are
digitized estimates from a published contour figure, not sounding data.
"""

import csv
import heapq
import io
import json
import math
import unicodedata
from collections import defaultdict


RADIUS_M = 6371008.8
CURRENT_YEAR = 1404
CURRENT_MONTH = 6
GRID_SIZE = 38
KARAT_MAX_BEDROCK_DEPTH_M = 300.0
_features = []
_locations = []
_readings = {}
_prepared = {}
_figure_depth = []
_figure_boundary_rule = None


def _normal(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه"}))
    return "".join(char for char in value if not char.isspace() and char not in "_-\u200c")


def _key(row):
    return (_normal(row.get("MAHDOUDE")), _normal(row.get("AQUIFER")), _normal(row.get("LOCATION")))


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def initialize(geojson_text, locations_text, measurements_text, figure_depth_text=""):
    global _features, _locations, _readings, _prepared, _figure_depth, _figure_boundary_rule
    _features = json.loads(geojson_text)["features"]
    _locations = []
    for row in csv.DictReader(io.StringIO(locations_text)):
        lon, lat, ground = (_number(row.get(item)) for item in ("X", "Y", "LEVEL_MSL"))
        if None in (lon, lat, ground):
            continue
        _locations.append({"key": _key(row), "lon": lon, "lat": lat, "ground": ground,
                           "name": row.get("LOCATION", "")})
    sums = defaultdict(lambda: [0.0, 0])
    for row in csv.DictReader(io.StringIO(measurements_text)):
        depth = _number(row.get("WATER_TABLE"))
        try:
            year, month = int(row["YEAR_PERSIAN"]), int(row["MONTH_PERSIAN"])
        except (KeyError, TypeError, ValueError):
            continue
        if depth is None or not 1 <= month <= 12:
            continue
        entry = sums[(_key(row), year, month)]
        entry[0] += depth
        entry[1] += 1
    _readings = {key: total / count for key, (total, count) in sums.items()}
    _figure_depth, _figure_boundary_rule = _depth_points(figure_depth_text)
    _prepared = {}
    return catalog()


def catalog():
    result = []
    for index, feature in enumerate(_features):
        summary = prepare(index)
        result.append({
            "index": index,
            "name": feature["properties"].get("AQUIFER", ""),
            "mahdoude": feature["properties"].get("MAHDOUDE", ""),
            "can_compare": bool(summary["years"]),
        })
    return result


def _polygons(feature):
    geometry = feature["geometry"]
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    raise ValueError("هندسه آبخوان باید Polygon یا MultiPolygon باشد.")


def _ring_contains(ring, x, y):
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous[:2]
        x2, y2 = current[:2]
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def _contains(polygons, lon, lat):
    for polygon in polygons:
        if _ring_contains(polygon[0], lon, lat) and not any(
            _ring_contains(hole, lon, lat) for hole in polygon[1:]
        ):
            return True
    return False


def _ring_area(ring):
    # Equal-area spherical approximation; coordinates are geographic degrees.
    result = 0.0
    previous = ring[-1]
    for current in ring:
        dlon = math.radians(current[0] - previous[0])
        result += dlon * (math.sin(math.radians(previous[1])) +
                          math.sin(math.radians(current[1])))
        previous = current
    return abs(result) * RADIUS_M * RADIUS_M / 2


def _area(polygons):
    return sum(max(0.0, _ring_area(polygon[0]) -
                   sum(_ring_area(hole) for hole in polygon[1:]))
               for polygon in polygons)


def _extent(polygons):
    coords = [point for polygon in polygons for ring in polygon for point in ring]
    return (min(p[0] for p in coords), min(p[1] for p in coords),
            max(p[0] for p in coords), max(p[1] for p in coords))


def prepare(feature_index):
    index = int(feature_index)
    if index in _prepared:
        return _prepared[index]["summary"]
    if not 0 <= index < len(_features):
        raise ValueError("آبخوان انتخاب‌شده پیدا نشد.")
    feature = _features[index]
    polygons = _polygons(feature)
    west, south, east, north = _extent(polygons)
    wells = [well for well in _locations
             if west <= well["lon"] <= east and south <= well["lat"] <= north
             and _contains(polygons, well["lon"], well["lat"])]
    current = {well["key"]: well for well in wells
               if (well["key"], CURRENT_YEAR, CURRENT_MONTH) in _readings}
    years = sorted({year for (key, year, month) in _readings
                    if month == CURRENT_MONTH and year < CURRENT_YEAR and key in current})
    available = []
    for year in years:
        count = sum((key, year, CURRENT_MONTH) in _readings for key in current)
        if count >= 3:
            available.append({"year": year, "common_wells": count,
                              "water_year": year - 1})
    summary = {"index": index, "name": feature["properties"].get("AQUIFER", ""),
               "mahdoude": feature["properties"].get("MAHDOUDE", ""),
               "well_count": len(wells), "current_count": len(current),
               "years": available, "area_km2": round(_area(polygons) / 1e6, 2)}
    _prepared[index] = {"summary": summary, "polygons": polygons,
                        "extent": (west, south, east, north), "current": current}
    return summary


def _idw(points, lon, lat, latitude_center, value_at=2):
    scale = math.cos(math.radians(latitude_center))
    nearest = heapq.nsmallest(
        8, (((lon - p[0]) ** 2 * scale * scale + (lat - p[1]) ** 2, p[value_at])
            for p in points))
    if not nearest:
        return None
    if nearest[0][0] < 1e-14:
        return nearest[0][1]
    weighted = [(1.0 / distance, value) for distance, value in nearest]
    return sum(weight * value for weight, value in weighted) / sum(weight for weight, _ in weighted)


def _contour_idw(points, lon, lat, latitude_center):
    """Interpolate contour depths without bias from uneven line sampling density.

    Each printed contour contributes only its nearest sampled point. Otherwise
    eight adjacent pixels on one contour can drown out the next contour line.
    """
    scale = math.cos(math.radians(latitude_center))
    closest_by_depth = {}
    for x, y, depth in points:
        distance = (lon - x) ** 2 * scale * scale + (lat - y) ** 2
        previous = closest_by_depth.get(depth)
        if previous is None or distance < previous:
            closest_by_depth[depth] = distance
    nearest = heapq.nsmallest(4, ((distance, depth) for depth, distance in
                                   closest_by_depth.items()))
    if not nearest:
        return None
    if nearest[0][0] < 1e-14:
        return nearest[0][1]
    weighted = [(1.0 / distance, depth) for distance, depth in nearest]
    return sum(weight * depth for weight, depth in weighted) / sum(weight for weight, _ in weighted)


def _common_surfaces(wells, lon, lat, latitude_center):
    """Use one set of spatial weights for ground and both measured depths."""
    scale = math.cos(math.radians(latitude_center))
    nearest = heapq.nsmallest(
        8, (((lon - row[0]) ** 2 * scale * scale + (lat - row[1]) ** 2,
             index, row) for index, row in enumerate(wells)))
    if nearest[0][0] < 1e-14:
        row = nearest[0][2]
        ground = row[2] + row[4]
        return ground - row[4], ground - row[5], ground
    total = sum(1.0 / distance for distance, _, _ in nearest)
    ground = sum((row[2] + row[4]) / distance for distance, _, row in nearest) / total
    before_depth = sum(row[4] / distance for distance, _, row in nearest) / total
    after_depth = sum(row[5] / distance for distance, _, row in nearest) / total
    return ground - before_depth, ground - after_depth, ground


def _bedrock_points(text, polygons, extent):
    if not text or not text.strip():
        return []
    rows = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    columns = set(rows.fieldnames or [])
    if not {"lon", "lat", "bedrock_msl"}.issubset(columns):
        raise ValueError("فایل سنگ‌بستر باید ستون‌های lon,lat,bedrock_msl داشته باشد.")
    points = []
    west, south, east, north = extent
    for row in rows:
        lon, lat, elevation = (_number(row.get(item)) for item in
                               ("lon", "lat", "bedrock_msl"))
        if None in (lon, lat, elevation):
            continue
        if west - 0.1 <= lon <= east + 0.1 and south - 0.1 <= lat <= north + 0.1:
            points.append((lon, lat, elevation))
    if len(points) < 8:
        raise ValueError("برای سطح سنگ‌بستر دست‌کم ۸ نقطه با پوشش مکانی آبخوان لازم است.")
    return points


def _depth_points(text):
    """Read raw contour controls and an optional explicit shallow-edge rule.

    Synthetic surface/boundary rows are export samples, not independent source
    controls. Reading source_depth_m prevents applying the taper twice.
    """
    if not text or not text.strip():
        return [], None
    rows = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not {"lon", "lat", "bedrock_depth_m"}.issubset(rows.fieldnames or []):
        raise ValueError("دادهٔ شکل S4 باید ستون‌های lon,lat,bedrock_depth_m داشته باشد.")
    points = []
    corrected = {"source_depth_m", "point_role", "boundary_depth_m", "taper_width_m"}.issubset(rows.fieldnames or [])
    rule = None
    guards = []
    for row in rows:
        if corrected:
            edge, width = (_number(row.get(key)) for key in ("boundary_depth_m", "taper_width_m"))
            if edge is None or width is None or edge < 0 or width <= 0:
                raise ValueError("پارامترهای اصلاح مرز سنگ‌کف معتبر نیستند.")
            candidate = {"depth_m": edge, "width_m": width}
            if rule is not None and rule != candidate:
                raise ValueError("پارامترهای اصلاح مرز در ردیف‌های فایل یکسان نیستند.")
            rule = candidate
            if row.get("point_role") == "well_minimum_constraint":
                guard = tuple(_number(row.get(key)) for key in
                              ("lon", "lat", "minimum_depth_m", "constraint_radius_m"))
                if None in guard or guard[2] < edge or guard[3] <= 0:
                    raise ValueError("قید حداقل عمق در محل پیزومتر معتبر نیست.")
                guards.append(guard)
            if row.get("point_role") not in ("digitized_inside", "digitized_outside"):
                continue
        lon, lat, depth = (_number(row.get(item)) for item in
                           ("lon", "lat", "source_depth_m" if corrected else "bedrock_depth_m"))
        if None in (lon, lat, depth) or not 0 <= depth <= 1000:
            continue
        points.append((lon, lat, depth))
    if len(points) < 8:
        raise ValueError("دادهٔ استخراج‌شده از شکل S4 نقاط کافی برای درون‌یابی ندارد.")
    if len(_convex_hull(points)) < 3:
        raise ValueError("نقاط شکل S4 در سطح آبخوان پراکندگی مکانی کافی ندارند.")
    if guards:
        rule["guards"] = guards
    return points, rule


def _boundary_index(polygons, latitude_center, cell_m=5000.0):
    """Index every outer/hole segment in a local metre projection.

    This projection is sufficient for an explicitly kilometre-scale scenario;
    it is not a surveyed distance or a substitute for geological mapping.
    """
    sx = math.pi * RADIUS_M / 180 * math.cos(math.radians(latitude_center))
    sy = math.pi * RADIUS_M / 180
    segments, bins = [], defaultdict(list)
    for polygon in polygons:
        for ring in polygon:
            previous = ring[-1]
            for point in ring:
                ax, ay = previous[0] * sx, previous[1] * sy
                bx, by = point[0] * sx, point[1] * sy
                previous = point
                dx, dy = bx - ax, by - ay
                length2 = dx * dx + dy * dy
                if not length2:
                    continue
                index = len(segments)
                segments.append((ax, ay, dx, dy, length2))
                for ix in range(math.floor(min(ax, bx) / cell_m), math.floor(max(ax, bx) / cell_m) + 1):
                    for iy in range(math.floor(min(ay, by) / cell_m), math.floor(max(ay, by) / cell_m) + 1):
                        bins[(ix, iy)].append(index)
    if not segments:
        raise ValueError("مرز آبخوان برای محاسبهٔ فاصله معتبر نیست.")
    return (sx, sy, cell_m, segments, bins)


def _boundary_distance_m(index, lon, lat):
    sx, sy, cell, segments, bins = index
    x, y = lon * sx, lat * sy
    cx, cy = math.floor(x / cell), math.floor(y / cell)
    best2, seen, radius = math.inf, set(), 0
    while True:
        for ix in range(cx - radius, cx + radius + 1):
            for iy in range(cy - radius, cy + radius + 1):
                if radius and abs(ix - cx) != radius and abs(iy - cy) != radius:
                    continue
                for segment_id in bins.get((ix, iy), ()):
                    if segment_id in seen:
                        continue
                    seen.add(segment_id)
                    ax, ay, dx, dy, length2 = segments[segment_id]
                    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length2))
                    distance2 = (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2
                    best2 = min(best2, distance2)
        # Any unvisited segment lies beyond this searched square.
        lower_bound = min(x - (cx - radius) * cell,
                          (cx + radius + 1) * cell - x,
                          y - (cy - radius) * cell,
                          (cy + radius + 1) * cell - y)
        if best2 <= lower_bound * lower_bound:
            return math.sqrt(best2)
        radius += 1


def _edge_weight(distance_m, width_m):
    t = max(0.0, min(1.0, distance_m / width_m))
    return t * t * (3.0 - 2.0 * t)


def _edge_depth(raw_depth, distance_m, rule, lon=None, lat=None, latitude_center=None):
    weight = _edge_weight(distance_m, rule["width_m"])
    depth = rule["depth_m"] + (raw_depth - rule["depth_m"]) * weight
    if rule.get("guards"):
        if lon is None or lat is None or latitude_center is None:
            raise ValueError("مختصات برای اعمال قید پیزومتر لازم است.")
        sx = math.pi * RADIUS_M / 180 * math.cos(math.radians(latitude_center))
        sy = math.pi * RADIUS_M / 180
        for x, y, minimum_depth, radius in rule["guards"]:
            ratio2 = (((lon - x) * sx) ** 2 + ((lat - y) * sy) ** 2) / (radius * radius)
            if ratio2 < 1:
                # Compact smooth support is entirely inside the boundary band.
                # Groundwater observations constrain a minimum bedrock depth;
                # the 5m margin is an explicit scenario, not a measured bottom.
                lower_bound = rule["depth_m"] + (minimum_depth - rule["depth_m"]) * (1 - ratio2) ** 2
                depth = max(depth, lower_bound)
    return depth


def _convex_hull(points):
    ordered = sorted(set((p[0], p[1]) for p in points))
    if len(ordered) < 3:
        return []
    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    lower = []
    for p in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def analyze(feature_index, baseline_year, sy, bedrock_text="", karat_thickness_m=65.0):
    summary = prepare(feature_index)
    year = int(baseline_year)
    if year not in {item["year"] for item in summary["years"]}:
        raise ValueError("برای شهریورِ سال انتخاب‌شده دست‌کم سه پیزومتر مشترک وجود ندارد.")
    coefficient = _number(sy)
    if coefficient is not None and not 0 < coefficient < 1:
        raise ValueError("آبدهی ویژه باید عددی بین صفر و یک باشد.")
    prepared = _prepared[int(feature_index)]
    polygons, extent = prepared["polygons"], prepared["extent"]
    common = []
    for key, well in prepared["current"].items():
        before_depth = _readings.get((key, year, CURRENT_MONTH))
        after_depth = _readings.get((key, CURRENT_YEAR, CURRENT_MONTH))
        if before_depth is not None and after_depth is not None:
            common.append((well["lon"], well["lat"],
                           well["ground"] - before_depth,
                           well["ground"] - after_depth,
                           before_depth, after_depth))
    if len(common) < 3:
        raise ValueError("پیزومتر مشترک کافی برای برآورد سطح آب وجود ندارد.")
    west, south, east, north = extent
    center_lat = (south + north) / 2
    uploaded_bedrock = _bedrock_points(bedrock_text, polygons, extent)
    is_neyshabur = (_normal(summary["name"]) == _normal("نیشابور") and
                    _normal(summary["mahdoude"]) == _normal("نیشابور"))
    is_karat = (_normal(summary["name"]) == _normal("کرات") and
                _normal(summary["mahdoude"]) == _normal("کرات"))
    figure_depth = _figure_depth if is_neyshabur and not uploaded_bedrock else []
    figure_rule = _figure_boundary_rule if figure_depth else None
    figure_boundary = _boundary_index(polygons, center_lat) if figure_rule else None
    scenario_thickness = None
    current_heads = []
    current_grounds = []
    if is_karat and not uploaded_bedrock:
        scenario_thickness = _number(karat_thickness_m)
        if scenario_thickness is None or not 20 <= scenario_thickness <= 300:
            raise ValueError("ضخامت فرضی کرات باید بین ۲۰ و ۳۰۰ متر باشد.")
        current_heads = [
            (well["lon"], well["lat"],
             well["ground"] - _readings[(key, CURRENT_YEAR, CURRENT_MONTH)])
            for key, well in prepared["current"].items()
        ]
        current_grounds = [
            (well["lon"], well["lat"], well["ground"])
            for well in prepared["current"].values()
        ]
    bedrock_source = ("uploaded" if uploaded_bedrock else
                      "figure_s4" if figure_depth else
                      "karat_scenario" if scenario_thickness is not None else
                      "schematic")
    depth_hull = _convex_hull(figure_depth) if figure_depth else []
    hull = _convex_hull(uploaded_bedrock) if uploaded_bedrock else depth_hull
    well_hull = _convex_hull(common)
    points = []
    sampled = []
    figure_references = []
    boundary_adjusted_cells = 0
    scenario_references = []
    supported = 0
    well_supported = 0
    capped_cells = 0
    actual_max_bedrock_depth = 0.0
    for j in range(GRID_SIZE):
        lat = south + (j + 0.5) * (north - south) / GRID_SIZE
        for i in range(GRID_SIZE):
            lon = west + (i + 0.5) * (east - west) / GRID_SIZE
            inside = _contains(polygons, lon, lat)
            if not inside:
                points.append([lon, lat, None, None, None, False])
                continue
            before, after, ground = _common_surfaces(common, lon, lat, center_lat)
            if uploaded_bedrock:
                bottom = _idw(uploaded_bedrock, lon, lat, center_lat)
            elif figure_depth:
                raw_depth = _contour_idw(figure_depth, lon, lat, center_lat)
                depth = raw_depth
                if figure_rule:
                    distance = _boundary_distance_m(figure_boundary, lon, lat)
                    depth = _edge_depth(raw_depth, distance, figure_rule, lon, lat, center_lat)
                    boundary_adjusted_cells += distance < figure_rule["width_m"]
                    figure_references.append((before, after, ground, raw_depth, distance, lon, lat))
                bottom = ground - depth
            elif scenario_thickness is not None:
                # One fixed hypothetical floor for every baseline year: the
                # 1404 surface uses all current wells, including those absent
                # from a selected historical comparison. The cap is depth
                # below the same fixed, all-current-well ground surface.
                current_head = _idw(current_heads, lon, lat, center_lat)
                current_ground = _idw(current_grounds, lon, lat, center_lat)
                uncapped_bottom = current_head - scenario_thickness
                lowest_bottom = current_ground - KARAT_MAX_BEDROCK_DEPTH_M
                bottom = max(uncapped_bottom, lowest_bottom)
                if uncapped_bottom < lowest_bottom:
                    capped_cells += 1
                actual_max_bedrock_depth = max(
                    actual_max_bedrock_depth, current_ground - bottom)
                scenario_references.append((before, after, current_head, current_ground))
            else:
                bottom = None
            if hull and _ring_contains(hull, lon, lat):
                supported += 1
            if well_hull and _ring_contains(well_hull, lon, lat):
                well_supported += 1
            points.append([lon, lat, before, after, bottom, True])
            sampled.append((before, after, bottom))
    if not sampled:
        raise ValueError("شبکه محاسباتی داخل مرز آبخوان قرار نگرفت.")
    coverage = supported / len(sampled) if hull else 0
    if uploaded_bedrock and coverage < 0.98:
        raise ValueError("نقاط سنگ‌بستر کل آبخوان را پوشش نمی‌دهند؛ شبکه باید تا پیرامون مرز ادامه یابد.")
    schematic_base = min(min(a, b) for a, b, _ in sampled) - max(
        20.0, (max(max(a, b) for a, b, _ in sampled) -
               min(min(a, b) for a, b, _ in sampled)) * 0.22)
    if bedrock_source == "schematic":
        for point in points:
            if point[5]:
                point[4] = schematic_base
    area_m2 = summary["area_km2"] * 1e6
    mean_before = sum(row[0] for row in sampled) / len(sampled)
    mean_after = sum(row[1] for row in sampled) / len(sampled)
    change_mcm = ((mean_after - mean_before) * coefficient * area_m2 / 1e6
                  if coefficient is not None else None)
    volume_before = volume_after = None
    sensitivity_20m = None
    dry_cells = 0
    if bedrock_source != "schematic" and coefficient is not None:
        cell_scale = coefficient * area_m2 / len(sampled) / 1e6
        volume_before = cell_scale * sum(
            max(0.0, before - bottom) for before, _, bottom in sampled)
        volume_after = cell_scale * sum(
            max(0.0, after - bottom) for _, after, bottom in sampled)
        dry_cells = sum(after <= bottom for _, after, bottom in sampled)
        change_mcm = volume_after - volume_before
        if bedrock_source == "karat_scenario":
            def scenario_volume(thickness, phase_index):
                return cell_scale * sum(
                    max(0.0, row[phase_index] - max(
                        row[2] - thickness,
                        row[3] - KARAT_MAX_BEDROCK_DEPTH_M))
                    for row in scenario_references)

            sensitivity_20m = {
                "before_minus_mcm": scenario_volume(scenario_thickness - 20, 0),
                "before_plus_mcm": scenario_volume(scenario_thickness + 20, 0),
                "after_minus_mcm": scenario_volume(scenario_thickness - 20, 1),
                "after_plus_mcm": scenario_volume(scenario_thickness + 20, 1),
            }
        elif bedrock_source == "figure_s4" and figure_rule:
            def figure_volume(offset, phase_index):
                return cell_scale * sum(
                    max(0.0, row[phase_index] - row[2] + _edge_depth(
                        max(figure_rule["depth_m"], row[3] + offset), row[4], figure_rule,
                        row[5], row[6], center_lat))
                    for row in figure_references)

            sensitivity_20m = {
                "before_minus_mcm": figure_volume(-20, 0),
                "before_plus_mcm": figure_volume(20, 0),
                "after_minus_mcm": figure_volume(-20, 1),
                "after_plus_mcm": figure_volume(20, 1),
            }
        elif bedrock_source == "figure_s4":
            sensitivity_20m = {
                "before_minus_mcm": cell_scale * sum(max(0.0, before - bottom - 20.0)
                                                       for before, _, bottom in sampled),
                "before_plus_mcm": cell_scale * sum(max(0.0, before - bottom + 20.0)
                                                      for before, _, bottom in sampled),
                "after_minus_mcm": cell_scale * sum(max(0.0, after - bottom - 20.0)
                                                      for _, after, bottom in sampled),
                "after_plus_mcm": cell_scale * sum(max(0.0, after - bottom + 20.0)
                                                     for _, after, bottom in sampled),
            }
    outlines = []
    for polygon in polygons:
        ring = polygon[0]
        step = max(1, math.ceil(len(ring) / 260))
        outlines.append([[p[0], p[1]] for p in ring[::step]])
    declines = sum(after < before for _, _, before, after, _, _ in common)
    result = {
        "aquifer": {"name": summary["name"], "mahdoude": summary["mahdoude"],
                    "area_km2": summary["area_km2"]},
        "dates": {"before": f"{year}-06", "after": "1404-06",
                  "before_water_year": year - 1, "after_water_year": 1403},
        "wells": {"common": len(common), "declined": declines,
                  "before_mean_depth_m": sum(row[4] for row in common) / len(common),
                  "after_mean_depth_m": sum(row[5] for row in common) / len(common)},
        "metrics": {"mean_head_decline_m": mean_before - mean_after,
                    "storage_change_mcm": change_mcm,
                    "drainable_before_mcm": volume_before,
                    "drainable_after_mcm": volume_after,
                    "bedrock_coverage_pct": coverage * 100 if hull else None,
                    "well_coverage_pct": well_supported / len(sampled) * 100,
                    "bedrock_source": bedrock_source,
                    "neyshabur_boundary_assumption": bool(figure_rule),
                    "neyshabur_boundary_depth_m": figure_rule["depth_m"] if figure_rule else None,
                    "neyshabur_taper_width_m": figure_rule["width_m"] if figure_rule else None,
                    "neyshabur_well_constraint_count": len(figure_rule.get("guards", [])) if figure_rule else 0,
                    "neyshabur_boundary_adjusted_cell_pct": (
                        boundary_adjusted_cells / len(sampled) * 100 if figure_rule else None),
                    "karat_thickness_m": scenario_thickness,
                    "karat_current_wells": len(current_heads) if current_heads else None,
                    "karat_max_bedrock_depth_m": (
                        KARAT_MAX_BEDROCK_DEPTH_M if scenario_thickness is not None else None),
                    "karat_actual_max_bedrock_depth_m": (
                        actual_max_bedrock_depth if scenario_thickness is not None else None),
                    "karat_capped_cell_count": (
                        capped_cells if scenario_thickness is not None else None),
                    "karat_capped_cell_pct": (
                        capped_cells / len(sampled) * 100 if scenario_thickness is not None else None),
                    "sensitivity_20m": sensitivity_20m,
                    "dry_cell_count": dry_cells,
                    "sy": coefficient},
        "grid": {"cols": GRID_SIZE, "rows": GRID_SIZE, "points": points,
                 "outlines": outlines,
                 "bedrock_real": bedrock_source in ("uploaded", "figure_s4"),
                 "bedrock_source": bedrock_source},
        "method": ("IDW²، ۸ چاه نزدیک، پیزومترهای مشترک دو شهریور؛ شبکه ۳۸×۳۸" +
                   ("؛ عمق سنگ کفِ برگرفته از شکل S4 و ارتفاع زمین چاه‌ها درون‌یابی شده‌اند"
                    + ("؛ قید فرضی سنگ‌کف نزدیک سطح در مرز و گذار نرم به عمق داخلی" if figure_rule else "")
                    if bedrock_source == "figure_s4" else
                    "؛ سنگ‌کف فرضی کرات از تراز آب درون‌یابی‌شدهٔ تمام چاه‌های شهریور ۱۴۰۴ منهای ضخامت سناریویی ساخته می‌شود، عمق آن زیر زمین محلی حداکثر ۳۰۰ متر است و با سال مبنا ثابت می‌ماند"
                    if bedrock_source == "karat_scenario" else ""))
    }
    return result


def call_json(command, argument_json="{}"):
    arguments = json.loads(argument_json)
    if command == "catalog":
        result = catalog()
    elif command == "prepare":
        result = prepare(arguments["feature_index"])
    elif command == "analyze":
        result = analyze(arguments["feature_index"], arguments["baseline_year"],
                         arguments.get("sy"), arguments.get("bedrock_text", ""),
                         arguments.get("karat_thickness_m", 65.0))
    else:
        raise ValueError("دستور ناشناخته است.")
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
