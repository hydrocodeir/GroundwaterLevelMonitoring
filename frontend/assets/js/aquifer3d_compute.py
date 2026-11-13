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
CURRENT_MONTH = 6
GRID_SIZE = 38
KARAT_MAX_BEDROCK_DEPTH_M = 300.0
_features = []
_locations = []
_readings = {}
_prepared = {}
_figure_depth = []
_figure_boundary_rule = None
_mashhad_bedrock_text = ""
_last_analysis = None


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


def initialize(geojson_text, locations_text, measurements_text, figure_depth_text="", mashhad_bedrock_text=""):
    global _features, _locations, _readings, _prepared, _figure_depth, _figure_boundary_rule
    global _mashhad_bedrock_text
    global _last_analysis
    _last_analysis = None
    _mashhad_bedrock_text = mashhad_bedrock_text
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
    keys = {well['key'] for well in wells}
    counts = defaultdict(int)
    for key, year, month in _readings:
        if key in keys and month == CURRENT_MONTH:
            counts[year] += 1
    current_year = max((year for year, count in counts.items() if count >= 3), default=0)
    current = {well["key"]: well for well in wells
               if (well["key"], current_year, CURRENT_MONTH) in _readings}
    years = sorted({year for (key, year, month) in _readings
                    if month == CURRENT_MONTH and year < current_year and key in current})
    available = []
    for year in years:
        count = sum((key, year, CURRENT_MONTH) in _readings for key in current)
        if count >= 3:
            available.append({"year": year, "common_wells": count,
                              "water_year": year - 1})
    summary = {"index": index, "name": feature["properties"].get("AQUIFER", ""),
               "mahdoude": feature["properties"].get("MAHDOUDE", ""),
               "well_count": len(wells), "current_count": len(current), "current_year":current_year or None,
               "years": available, "area_km2": round(_area(polygons) / 1e6, 2)}
    _prepared[index] = {"summary": summary, "polygons": polygons,
                        "extent": (west, south, east, north), "current": current,
                        "ground_points": [(w["lon"], w["lat"], w["ground"]) for w in wells]}
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


def _sy_points(text):
    """Strict WGS84 point input; never silently discard a bad coefficient."""
    if not text or not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    reader.fieldnames = [name.strip().lower() for name in (reader.fieldnames or [])]
    names = set(reader.fieldnames)
    lon_key = "longitude" if "longitude" in names else "lon"
    lat_key = "latitude" if "latitude" in names else "lat"
    if not {lon_key, lat_key, "sy"}.issubset(names):
        raise ValueError("فایل Sy باید ستون‌های longitude,latitude,Sy یا lon,lat,Sy داشته باشد.")
    points = {}
    for line, row in enumerate(reader, 2):
        lon, lat, value = (_number(row.get(key)) for key in (lon_key, lat_key, "sy"))
        if (None in (lon, lat, value) or not -180 <= lon <= 180
                or not -90 <= lat <= 90 or not 0 < value < 1):
            raise ValueError(f"ردیف {line} فایل Sy نامعتبر است؛ مختصات جغرافیایی و Sy بین صفر و یک لازم است.")
        if (lon, lat) in points and points[(lon, lat)] != value:
            raise ValueError(f"ردیف {line}: دو Sy متفاوت برای یک مختصات ثبت شده است.")
        points[(lon, lat)] = value
    result = [(lon, lat, value) for (lon, lat), value in points.items()]
    if len(_convex_hull(result)) < 3:
        raise ValueError("فایل Sy به دست‌کم سه نقطهٔ غیرهم‌خط نیاز دارد.")
    return result


def _pixel_grid_size(width_m=4000, height_m=4000):
    width, height = _number(width_m), _number(height_m)
    if any(isinstance(v, bool) for v in (width_m, height_m)) or any(v is None or not 0 < v <= 1e6 for v in (width, height)):
        raise ValueError('طول و عرض پیکسل باید عدد مثبت و حداکثر ۱٬۰۰۰٬۰۰۰ متر باشند.')
    return width, height


def _plan_maps(display, spatial_sy, coefficient, has_floor, cell_width_m=4000, cell_height_m=4000):
    """Physical floor/storage on clipped cells; nominal metres in the local metric."""
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    shape = unary_union([Polygon(p[0], p[1:]) for p in display['polygons']])
    west, south, east, north = shape.bounds
    sx, sy = 111320 * math.cos(math.radians((south+north)/2)), 111320
    width, height_m = _pixel_grid_size(cell_width_m, cell_height_m)
    dx, dy = width/sx, height_m/sy
    grid_cols, grid_rows = math.ceil((east-west)/dx), math.ceil((north-south)/dy)
    if grid_cols*grid_rows > 25000:
        raise ValueError('این ابعاد بیش از ۲۵٬۰۰۰ خانهٔ شبکه ایجاد می‌کند؛ برای محاسبه در مرورگر، طول یا عرض پیکسل را بزرگ‌تر انتخاب کنید.')
    points, cols, rows = display['points'], display['cols'], display['rows']
    x0, y0 = points[0][:2]
    x1, y1 = points[-1][:2]

    def height(lon, lat, column):
        x = max(0, min(cols-1-1e-8, (lon-x0)/(x1-x0)*(cols-1)))
        y = max(0, min(rows-1-1e-8, (lat-y0)/(y1-y0)*(rows-1)))
        i, j = int(x), int(y)
        u, v = x-i, y-j
        return (points[j*cols+i][column]*(1-u)*(1-v) + points[j*cols+i+1][column]*u*(1-v)
                + points[(j+1)*cols+i][column]*(1-u)*v + points[(j+1)*cols+i+1][column]*u*v)

    cells = []
    for j in range(grid_rows):
        for i in range(grid_cols):
            cell = shape.intersection(box(west+i*dx, south+j*dy, west+(i+1)*dx, south+(j+1)*dy))
            if cell.is_empty or cell.area < 1e-14:
                continue
            p = cell.representative_point()
            lon, lat = p.x, p.y
            before, after, bottom = [height(lon, lat, k) for k in (2,3,4)]
            value = _idw(spatial_sy, lon, lat, (south+north)/2) if spatial_sy else coefficient
            valid = has_floor and value is not None
            old = max(0, before-bottom)*value if valid else None
            now = max(0, after-bottom)*value if valid else None
            lost = max(0, old-now) if valid else None
            gained = max(0, now-old) if valid else None
            baseline_defined = valid and old > 1e-10  # numerical zero, in metres of equivalent water
            area = cell.area*sx*sy
            parts = [cell] if cell.geom_type == 'Polygon' else list(getattr(cell,'geoms',[]))
            rings = [[list(r.coords) for r in [part.exterior, *part.interiors]]
                     for part in parts if part.geom_type == 'Polygon']
            cells.append({'lon':lon, 'lat':lat, 'remaining_m':now, 'lost_m':lost,
                          'before_m':old, 'gained_m':gained,
                          'remaining_pct':100*now/old if baseline_defined else None,
                          'lost_pct':100*lost/old if baseline_defined else None,
                          'gained_pct':100*gained/old if baseline_defined else None,
                          'sy':value, 'before_msl':before, 'after_msl':after,
                          'bedrock_msl':bottom if has_floor else None,
                          'saturated_m':max(0,after-bottom) if has_floor else None,
                          'before_mcm':old*area/1e6 if valid else None,
                          'remaining_mcm':now*area/1e6 if valid else None,
                          'lost_mcm':lost*area/1e6 if valid else None,
                          'area_m2':area, 'polygons':rings, 'column':i, 'row':j})
    fields = {}
    for key, available in [('bedrock_msl', has_floor), ('sy', coefficient is not None or bool(spatial_sy))]:
        if not available:
            continue
        values = [(p[4] if key == 'bedrock_msl' else
                   _idw(spatial_sy, p[0], p[1], (south+north)/2) if spatial_sy else coefficient)
                  for p in points]
        cell_values = [c[key] for c in cells]
        fields[key] = {'min':min(cell_values), 'max':max(cell_values),
                       'contours':_surface_contours(points, cols, rows, values, shape)}
    return {'cells':cells, 'side_m':width if width == height_m else None, 'fields':fields,
            'cell_width_m':width, 'cell_height_m':height_m,
            'spacing_lon':dx, 'spacing_lat':dy, 'grid_cols':grid_cols, 'grid_rows':grid_rows,
            'metric_basis':'local equirectangular; nominal metres at polygon mean latitude',
            'reference_latitude':(south+north)/2,
            'polygons':display['polygons'], 'extent':[west,south,east,north],
            'percentage_reference':'baseline_storage', 'zero_baseline':'undefined'}


def _surface_contours(points, cols, rows, values, shape):
    """March triangles, then clip/merge isolines; levels follow the input range."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union, linemerge
    low, high = min(values), max(values)
    if math.isclose(low, high, rel_tol=1e-12, abs_tol=1e-14):
        return []
    raw = (high-low)/8
    magnitude = 10**math.floor(math.log10(raw))
    step = next(n for n in (1, 2, 2.5, 5, 10) if n*magnitude >= raw)*magnitude
    levels = [step*k for k in range(math.floor(low/step)+1, math.ceil(high/step))]
    contours = []
    for level in levels:
        segments = []
        for j in range(rows-1):
            for i in range(cols-1):
                a = j*cols+i
                for ids in ((a,a+1,a+cols+1), (a,a+cols+1,a+cols)):
                    hits = []
                    for u,v in zip(ids, (ids[1],ids[2],ids[0])):
                        if (values[u] <= level < values[v]) or (values[v] <= level < values[u]):
                            t = (level-values[u])/(values[v]-values[u])
                            hits.append(tuple(points[u][k]+t*(points[v][k]-points[u][k]) for k in (0,1)))
                    if len(hits) == 2 and hits[0] != hits[1]:
                        segments.append(LineString(hits))
        if not segments:
            continue
        lines = unary_union(segments).intersection(shape)
        if lines.is_empty:
            continue
        if lines.geom_type == 'MultiLineString':
            lines = linemerge(lines)
        def paths(geometry):
            if geometry.geom_type == 'LineString':
                return [list(geometry.coords)] if geometry.length > 0 else []
            return [path for part in getattr(geometry, 'geoms', []) for path in paths(part)]
        contours.append({'value':level, 'paths':paths(lines)})
    return contours


def _pixel_water_mesh(display, spatial_sy, coefficient, has_floor, plan_maps=None):
    """Use exactly the same physical cells as the 2D percentage maps."""
    if not has_floor or (coefficient is None and not spatial_sy):
        return None
    from shapely.geometry import Polygon
    from shapely.ops import triangulate
    plan_maps = plan_maps or _plan_maps(display, spatial_sy, coefficient, has_floor)
    shell = {'blue': [], 'red': [], 'green': [], 'floor': [], 'outlines': []}
    face_cells = {'blue': [], 'red': []}
    vertices, cells = [], plan_maps['cells']
    for cell_index, cell in enumerate(cells):
        lon,lat,now,lost = [cell[k] for k in ('lon','lat','remaining_m','lost_m')]
        vertices.append([lon,lat,0,0,0,0,now+lost])
        parts = [Polygon(p[0],p[1:]) for p in cell['polygons']]
        for part in parts:
            if part.geom_type != 'Polygon':
                continue
            for ring in [part.exterior, *part.interiors]:
                xy = list(ring.coords)
                for (ax,ay),(bx,by) in zip(xy,xy[1:]):
                    shell['outlines'].extend([[ax,ay,0],[bx,by,0]])
            # Clip boundary cells exactly; interior cells retain the chosen dimensions.
            tops = [t for t in triangulate(part) if part.covers(t)]
            for kind, low, high in [('blue',0,now), ('red',now,now+lost)]:
                if high-low < 1e-10:
                    continue
                first_face = len(shell[kind])
                for tri in tops:
                    xy = list(tri.exterior.coords)[:3]
                    shell[kind].append([[x,y,high]+([now] if kind=='red' else []) for x,y in xy])
                    shell[kind].append([[x,y,low]+([now] if kind=='red' else []) for x,y in reversed(xy)])
                for ring in [part.exterior, *part.interiors]:
                    xy = list(ring.coords)
                    for (ax,ay),(bx,by) in zip(xy,xy[1:]):
                        a,b,c,d = [ax,ay,low],[bx,by,low],[bx,by,high],[ax,ay,high]
                        if kind=='red':
                            for point in (a,b,c,d):
                                point.append(now)
                        shell[kind].extend([[a,b,c],[a,c,d]])
                        shell['outlines'].extend([[ax,ay,high],[bx,by,high]])
                face_cells[kind].extend([cell_index] * (len(shell[kind]) - first_face))
    # Extent includes cell corners rather than only their representative points.
    west,south,east,north = plan_maps['extent']
    vertices.extend([[west,south,0,0,0,0,0],[east,north,0,0,0,0,0]])
    return {'shell':shell, 'vertices':vertices, 'cells':cells, 'side_m':plan_maps['side_m'],
            'cell_width_m':plan_maps.get('cell_width_m',plan_maps['side_m']),
            'cell_height_m':plan_maps.get('cell_height_m',plan_maps['side_m']), 'face_cells':face_cells}


def _volume_mesh(display, spatial_sy, coefficient, has_floor):
    """Display mesh clipped to polygon rings; never changes analytical volumes.

    Heights are sampled from the original display grid. Near the rim, ONLY the
    geological view's floor approaches the baseline. Equivalent-water thickness
    uses the original floor and locally interpolated Sy, never the lifted floor.
    """
    from shapely.geometry import Polygon, MultiPoint, GeometryCollection, Point
    from shapely.ops import triangulate, unary_union
    polygons = [Polygon(p[0], p[1:]) for p in display["polygons"]]
    shape = unary_union(polygons)
    if not shape.is_valid:
        raise ValueError("مرز آبخوان برای ساخت حجم سه‌بعدی معتبر نیست.")
    points, cols, rows = display["points"], display["cols"], display["rows"]
    west, south = points[0][:2]
    east, north = points[-1][:2]
    center_lat = (south + north) / 2
    sx = 111320 * math.cos(math.radians(center_lat))
    sy_m = 111320
    # Simplification is bounded to about 5 metres and affects only rendering.
    tolerance = 5 / max(sx, sy_m)
    shape = shape.simplify(tolerance, preserve_topology=True)
    nodes = MultiPoint([p[:2] for p in points if shape.covers(Point(p[:2]))])
    source = GeometryCollection([shape.boundary, nodes])
    faces = []

    def add_clipped(piece, depth=0):
        if piece.is_empty or piece.area < 1e-16:
            return
        if piece.geom_type != "Polygon":
            for part in getattr(piece, "geoms", []):
                add_clipped(part, depth)
            return
        coords = list(piece.exterior.coords)[:-1]
        if len(coords) == 3 and not piece.interiors:
            faces.append(coords)
            return
        if depth > 8:
            raise ValueError("ساخت شبکهٔ بسته در مرز آبخوان ناموفق بود.")
        for triangle in triangulate(piece):
            if piece.covers(triangle):
                faces.append(list(triangle.exterior.coords)[:-1])
            elif triangle.intersects(piece):
                add_clipped(triangle.intersection(piece), depth + 1)

    for triangle in triangulate(source):
        if shape.covers(triangle):
            faces.append(list(triangle.exterior.coords)[:-1])
        elif shape.intersects(triangle):
            add_clipped(shape.intersection(triangle))
    area = sum(Polygon(face).area for face in faces)
    if not math.isclose(area, shape.area, rel_tol=1e-7, abs_tol=1e-12):
        raise ValueError("پوشش شبکهٔ سه‌بعدی با مرز آبخوان سازگار نیست.")
    # Use the simplified display rings for exact rim coincidence in both views.
    parts = [shape] if shape.geom_type == "Polygon" else list(shape.geoms)
    rings = [[list(r.coords) for r in [p.exterior, *p.interiors]] for p in parts]
    boundary = _boundary_index(rings, center_lat)
    transition_m = max((east-west)*sx/(cols-1), (north-south)*sy_m/(rows-1))

    def height(lon, lat, column):
        x = max(0, min(cols-1-1e-8, (lon-west)/(east-west)*(cols-1)))
        y = max(0, min(rows-1-1e-8, (lat-south)/(north-south)*(rows-1)))
        i, j = int(x), int(y)
        u, v = x-i, y-j
        return (points[j*cols+i][column]*(1-u)*(1-v) + points[j*cols+i+1][column]*u*(1-v)
                + points[(j+1)*cols+i][column]*(1-u)*v + points[(j+1)*cols+i+1][column]*u*v)

    vertices, lookup, triangles = [], {}, []
    for face in faces:
        indices = []
        for lon, lat in face:
            key = (round(lon, 11), round(lat, 11))
            if key not in lookup:
                before, after, original = [height(lon, lat, k) for k in (2, 3, 4)]
                distance = _boundary_distance_m(boundary, lon, lat)
                t = max(0, min(1, distance / transition_m))
                t = t*t*(3-2*t)
                # At the rim this equals baseline exactly. The adjustment fades
                # within one computational-cell width; no original row is edited.
                bottom = before + (original-before)*t
                value = _idw(spatial_sy, lon, lat, center_lat) if spatial_sy else coefficient
                old = max(0, before-original)*value if has_floor and value is not None else None
                now = max(0, after-original)*value if has_floor and value is not None else None
                lookup[key] = len(vertices)
                vertices.append([lon, lat, before, after, bottom, old, now])
            indices.append(lookup[key])
        triangles.append(indices)
    # Single-use edges are the actual outer/hole boundary, never cell walls.
    edges = {}
    for a, b, c in triangles:
        for u, v in [(a,b), (b,c), (c,a)]:
            key = tuple(sorted((u,v)))
            edges[key] = edges.get(key, 0) + 1
    if any(count > 2 for count in edges.values()):
        raise ValueError("لبهٔ نامعتبر در شبکهٔ سه‌بعدی.")
    boundary_edges = [list(edge) for edge, count in edges.items() if count == 1]
    return {"vertices": vertices, "triangles": triangles,
            "boundary": boundary_edges,
            "geology": _volume_shells(vertices, triangles, boundary_edges, False),
            "water": _volume_shells(vertices, triangles, boundary_edges, True),
            "transition_m": transition_m, "boundary_tolerance_m": 5}


def _volume_shells(vertices, triangles, boundary, equivalent):
    """Closed shells of retained, lost and gained water; no internal cell walls.

    Each base triangle is split at head/floor and gain/loss intersections before
    thickness clamping. Red and green must never occupy the same XY region.
    Rows are [lon, lat, floor, baseline, final]. Output triangles are XYZ only.
    """
    if equivalent and any(v[5] is None or v[6] is None for v in vertices):
        return None
    rows = [[v[0], v[1], 0, v[5], v[6]] if equivalent else
            [v[0], v[1], v[4], v[2], v[3]] for v in vertices]
    shells = {"blue": [], "red": [], "green": [], "floor": [], "outlines": []}
    planes = [lambda p: p[3]-p[2], lambda p: p[4]-p[2], lambda p: p[3]-p[4]]

    def mix(a, b, t):
        return [x + (y-x)*t for x, y in zip(a, b)]

    def clip(poly, gap, sign):
        result = []
        a = poly[-1]
        for b in poly:
            ga, gb = gap(a)*sign, gap(b)*sign
            if (ga >= 0) != (gb >= 0):
                result.append(mix(a, b, ga/(ga-gb)))
            if gb >= 0:
                result.append(b)
            a = b
        return result

    def heights(p):
        low, old, now = p[2], max(p[2],p[3]), max(p[2],p[4])
        return {"blue": (low, min(old,now)), "red": (now, max(old,now)),
                "green": (old, max(old,now))}

    def fan(poly, key, upper, reverse=False):
        layer = [[p[0],p[1],heights(p)[key][int(upper)]] + ([heights(p)[key][0]] if key=='red' else []) for p in poly]
        for i in range(1,len(layer)-1):
            tri = [layer[0],layer[i],layer[i+1]]
            shells[key].append(tri[::-1] if reverse else tri)

    for indices in triangles:
        tri = [rows[i] for i in indices]
        shells["floor"].append([[p[0],p[1],p[2]] for p in tri])
        parts = [tri]
        for gap in planes:
            split = []
            for poly in parts:
                values = [gap(p) for p in poly]
                if min(values) < -1e-9 and max(values) > 1e-9:
                    split.extend([clip(poly,gap,1),clip(poly,gap,-1)])
                else:
                    split.append(poly)
            parts = [p for p in split if len(p)>=3]
        for poly in parts:
            for key in ("blue","red","green"):
                if max(heights(p)[key][1]-heights(p)[key][0] for p in poly) < 1e-8:
                    continue
                fan(poly,key,True)
                fan(poly,key,False,True)
    for u,v in boundary:
        a,b=rows[u],rows[v]
        cuts={0.,1.}
        for gap in planes:
            ga,gb=gap(a),gap(b)
            if ga*gb < 0:
                cuts.add(ga/(ga-gb))
        cuts=sorted(cuts)
        for ta,tb in zip(cuts,cuts[1:]):
            p,q=mix(a,b,ta),mix(a,b,tb)
            for key in ("blue","red","green"):
                pl,ph=heights(p)[key]; ql,qh=heights(q)[key]
                if max(ph-pl,qh-ql)<1e-8:
                    continue
                x,y,z,w=[p[0],p[1],pl],[q[0],q[1],ql],[q[0],q[1],qh],[p[0],p[1],ph]
                if key=='red':
                    for point,anchor in [(x,pl),(y,ql),(z,ql),(w,pl)]:
                        point.append(anchor)
                shells[key].extend([[x,y,z],[x,z,w]])
            for k in (2,3,4):
                shells["outlines"].extend([[p[0],p[1],max(p[2],p[k])],[q[0],q[1],max(q[2],q[k])]])
    return shells


def analyze(feature_index, baseline_year, sy, bedrock_text="", karat_thickness_m=65.0, sy_text="", user_layers_only=True, cell_width_m=4000, cell_height_m=4000, spatial_method='idw', spline_smoothing=0):
    cell_width_m, cell_height_m = _pixel_grid_size(cell_width_m, cell_height_m)
    smoothing=_number(spline_smoothing)
    if spatial_method not in ('idw','spline','thiessen') or smoothing is None or smoothing<0:raise ValueError('روش مکانی یا هموارسازی معتبر نیست.')
    summary = prepare(feature_index)
    current_year = summary['current_year']
    year = int(baseline_year)
    if year not in {item["year"] for item in summary["years"]}:
        raise ValueError("برای شهریورِ سال انتخاب‌شده دست‌کم سه پیزومتر مشترک وجود ندارد.")
    spatial_sy = _sy_points(sy_text)
    coefficient = None if spatial_sy else _number(sy)
    if not spatial_sy and sy not in (None, "") and (coefficient is None or not 0 < coefficient < 1):
        raise ValueError("آبدهی ویژه باید عددی بین صفر و یک باشد.")
    prepared = _prepared[int(feature_index)]
    polygons, extent = prepared["polygons"], prepared["extent"]
    common = []
    for key, well in prepared["current"].items():
        before_depth = _readings.get((key, year, CURRENT_MONTH))
        after_depth = _readings.get((key, current_year, CURRENT_MONTH))
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
    builtin_mashhad = []
    if not user_layers_only and _normal(summary["name"]) == _normal("مشهد") and not uploaded_bedrock:
        builtin_mashhad = _bedrock_points(_mashhad_bedrock_text, polygons, extent)
    elevation_bedrock = uploaded_bedrock or builtin_mashhad
    is_neyshabur = (_normal(summary["name"]) == _normal("نیشابور") and
                    _normal(summary["mahdoude"]) == _normal("نیشابور"))
    is_karat = (_normal(summary["name"]) == _normal("کرات") and
                _normal(summary["mahdoude"]) == _normal("کرات"))
    figure_depth = _figure_depth if not user_layers_only and is_neyshabur and not uploaded_bedrock else []
    figure_rule = _figure_boundary_rule if figure_depth else None
    figure_boundary = _boundary_index(polygons, center_lat) if figure_rule else None
    scenario_thickness = None
    current_heads = []
    current_grounds = []
    if not user_layers_only and is_karat and not uploaded_bedrock:
        scenario_thickness = _number(karat_thickness_m)
        if scenario_thickness is None or not 20 <= scenario_thickness <= 300:
            raise ValueError("ضخامت فرضی کرات باید بین ۲۰ و ۳۰۰ متر باشد.")
        current_heads = [
            (well["lon"], well["lat"],
             well["ground"] - _readings[(key, current_year, CURRENT_MONTH)])
            for key, well in prepared["current"].items()
        ]
        current_grounds = [
            (well["lon"], well["lat"], well["ground"])
            for well in prepared["current"].values()
        ]
    bedrock_source = ("uploaded" if uploaded_bedrock else
                      "mashhad_msl" if builtin_mashhad else
                      "figure_s4" if figure_depth else
                      "karat_scenario" if scenario_thickness is not None else
                      "schematic")
    depth_hull = _convex_hull(figure_depth) if figure_depth else []
    hull = _convex_hull(elevation_bedrock) if elevation_bedrock else depth_hull
    sy_hull = _convex_hull(spatial_sy) if spatial_sy else []
    coefficients = []
    sy_supported = 0
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
            coefficients.append(_idw(spatial_sy, lon, lat, center_lat) if spatial_sy else coefficient)
            if sy_hull and _ring_contains(sy_hull, lon, lat):
                sy_supported += 1
            if elevation_bedrock:
                bottom = _idw(elevation_bedrock, lon, lat, center_lat)
            elif figure_depth:
                # Fixed ground reference, independent of the selected year and
                # common-well subset. This is an interpolated estimate, not DEM.
                ground = _idw(prepared["ground_points"], lon, lat, center_lat)
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
                # Latest supported September uses all current wells, including those absent
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
    if spatial_sy and sy_supported != len(sampled):
        raise ValueError("نقاط Sy کل شبکهٔ آبخوان را پوشش نمی‌دهند؛ نقاط پیرامون محدوده را هم وارد کنید.")
    coverage = supported / len(sampled) if hull else 0
    if elevation_bedrock and coverage < 0.98:
        raise ValueError("نقاط سنگ‌بستر کل آبخوان را پوشش نمی‌دهند؛ شبکه باید تا پیرامون مرز ادامه یابد.")
    schematic_base = min(min(a, b) for a, b, _ in sampled) - max(
        20.0, (max(max(a, b) for a, b, _ in sampled) -
               min(min(a, b) for a, b, _ in sampled)) * 0.22)
    if bedrock_source == "schematic":
        for point in points:
            if point[5]:
                point[4] = min(point[2],point[3]) if user_layers_only else schematic_base
    area_m2 = summary["area_km2"] * 1e6
    mean_before = sum(row[0] for row in sampled) / len(sampled)
    mean_after = sum(row[1] for row in sampled) / len(sampled)
    has_sy = coefficient is not None or bool(spatial_sy)
    cell_area_km2 = area_m2 / len(sampled) / 1e6
    change_mcm = (cell_area_km2 * sum((row[1] - row[0]) * value
                  for row, value in zip(sampled, coefficients)) if has_sy else None)
    volume_before = volume_after = None
    sensitivity_20m = None
    dry_cells = 0
    if bedrock_source != "schematic" and has_sy:
        volume_before = cell_area_km2 * sum(
            max(0.0, row[0] - row[2]) * value for row, value in zip(sampled, coefficients))
        volume_after = cell_area_km2 * sum(
            max(0.0, row[1] - row[2]) * value for row, value in zip(sampled, coefficients))
        dry_cells = sum(after <= bottom for _, after, bottom in sampled)
        change_mcm = volume_after - volume_before
    if bedrock_source != "schematic" and coefficient is not None:
        cell_scale = coefficient * cell_area_km2
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
    water_points, water_values = [], []
    sy_iter = iter(coefficients)
    for point in points:
        lon, lat, before, after, bottom, inside = point
        value = next(sy_iter) if inside else None
        valid = inside and has_sy and bedrock_source != "schematic"
        old = max(0, before - bottom) * value if valid else None
        now = max(0, after - bottom) * value if valid else None
        water_points.append([lon, lat, old, now, 0 if valid else None, bool(valid)])
        if valid:
            water_values.append((old, now))
    equivalent = None
    if water_values:
        equivalent = {
            "remaining_m": sum(b for a, b in water_values) / len(water_values),
            "lost_m": sum(max(0, a - b) for a, b in water_values) / len(water_values),
            "gained_m": sum(max(0, b - a) for a, b in water_values) / len(water_values),
        }
    # Display-only padding lets the renderer clip smooth surfaces at the actual
    # polygon, including holes, instead of erecting walls at occupied grid cells.
    # These extra samples never contribute to area, storage or coverage metrics.
    display_points = []
    for j in range(-1, GRID_SIZE + 1):
        lat = south + (j + .5) * (north - south) / GRID_SIZE
        for i in range(-1, GRID_SIZE + 1):
            lon = west + (i + .5) * (east - west) / GRID_SIZE
            point = points[j * GRID_SIZE + i] if 0 <= i < GRID_SIZE and 0 <= j < GRID_SIZE else None
            if point and point[5]:
                display_points.append(point[:5])
                continue
            before, after, ground = _common_surfaces(common, lon, lat, center_lat)
            if elevation_bedrock:
                bottom = _idw(elevation_bedrock, lon, lat, center_lat)
            elif figure_depth:
                ground = _idw(prepared["ground_points"], lon, lat, center_lat)
                depth = _contour_idw(figure_depth, lon, lat, center_lat)
                if figure_rule:
                    distance = _boundary_distance_m(figure_boundary, lon, lat)
                    depth = _edge_depth(depth, distance, figure_rule, lon, lat, center_lat)
                bottom = ground - depth
            elif scenario_thickness is not None:
                bottom = max(_idw(current_heads, lon, lat, center_lat) - scenario_thickness,
                             _idw(current_grounds, lon, lat, center_lat) - KARAT_MAX_BEDROCK_DEPTH_M)
            else:
                bottom = schematic_base
            display_points.append([lon, lat, before, after, bottom])
    water_balance = None
    if equivalent:
        retained = sum(min(a, b) for a, b in water_values) / len(water_values)
        water_balance = {
            "before_m": sum(a for a, b in water_values) / len(water_values),
            "after_m": equivalent["remaining_m"], "retained_m": retained,
            "lost_m": equivalent["lost_m"], "gained_m": equivalent["gained_m"],
            "lost_mcm": equivalent["lost_m"] * summary["area_km2"],
            "gained_mcm": equivalent["gained_m"] * summary["area_km2"],
        }
    display_grid = {"cols": GRID_SIZE + 2, "rows": GRID_SIZE + 2,
                    "points": display_points, "polygons": polygons}
    volume_mesh = _volume_mesh(display_grid, spatial_sy, coefficient, bedrock_source != "schematic")
    if user_layers_only and bedrock_source == 'schematic':
        # Two measured/interpolated head surfaces; no invented bedrock or volume.
        v=volume_mesh['vertices'];tri=volume_mesh['triangles']
        for point in v:point[4]=min(point[2],point[3])
        volume_mesh['geology']={'blue':[[[v[i][0],v[i][1],v[i][3]] for i in t] for t in tri],
            'red':[[[v[i][0],v[i][1],v[i][2],v[i][2]] for i in t] for t in tri],
            'green':[],'floor':[],'outlines':[]}
        volume_mesh['water']=None
        volume_mesh['heads_only']=True
    plan_maps = _plan_maps(display_grid, spatial_sy, coefficient, bedrock_source != "schematic", cell_width_m, cell_height_m)
    pixel_water = _pixel_water_mesh(display_grid, spatial_sy, coefficient, bedrock_source != "schematic", plan_maps)
    result = {
        "aquifer": {"name": summary["name"], "mahdoude": summary["mahdoude"],
                    "area_km2": summary["area_km2"]},
        "dates": {"before": f"{year}-06", "after": f"{current_year}-06",
                  "before_water_year": year - 1, "after_water_year": current_year-1},
        "wells": {"common": len(common), "declined": declines,
                  "points": [{"name": well["name"], "lon": well["lon"], "lat": well["lat"],
                              "before": well["ground"] - _readings[(key, year, CURRENT_MONTH)],
                              "after": well["ground"] - _readings[(key, current_year, CURRENT_MONTH)]}
                             for key, well in prepared["current"].items()
                             if (key, year, CURRENT_MONTH) in _readings],
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
                    "equivalent_water": equivalent,
                    "water_balance": water_balance,
                    "sy_mode": "spatial" if spatial_sy else "constant",
                    "sy_min": min(coefficients) if has_sy else None,
                    "sy_max": max(coefficients) if has_sy else None,
                    "sy": coefficient},
        "pixel_water": pixel_water,
        "plan_maps": plan_maps,
        "spatial": {"method":spatial_method,"spline_smoothing":smoothing,"coverage":"aquifer"},
        "water_grid": {"cols": GRID_SIZE, "rows": GRID_SIZE, "points": water_points,
                       "outlines": outlines, "bedrock_real": True,
                       "bedrock_source": "equivalent_water"},
        "display_grid": display_grid,
        "volume_mesh": volume_mesh,
        "grid": {"cols": GRID_SIZE, "rows": GRID_SIZE, "points": points,
                 "outlines": outlines,
                 "bedrock_real": bedrock_source in ("uploaded", "figure_s4", "mashhad_msl"),
                 "bedrock_source": bedrock_source},
        "method": ("IDW²، ۸ چاه نزدیک، پیزومترهای مشترک دو شهریور؛ شبکه ۳۸×۳۸" +
                   ("؛ عمق سنگ کفِ برگرفته از شکل S4 و ارتفاع زمین چاه‌ها درون‌یابی شده‌اند"
                    + ("؛ قید فرضی سنگ‌کف نزدیک سطح در مرز و گذار نرم به عمق داخلی" if figure_rule else "")
                    if bedrock_source == "figure_s4" else
                    f"؛ سنگ‌کف فرضی کرات از تراز آب درون‌یابی‌شدهٔ تمام چاه‌های شهریور {current_year} منهای ضخامت سناریویی ساخته می‌شود، عمق آن زیر زمین محلی حداکثر ۳۰۰ متر است و با سال مبنا ثابت می‌ماند"
                    if bedrock_source == "karat_scenario" else ""))
    }
    return result


def cross_section(start, end, count=241):
    """Sample the original input floor, preserving gaps outside polygon/holes."""
    if not _last_analysis:
        raise ValueError("ابتدا مدل آبخوان را محاسبه کنید.")
    if len(start) != 2 or len(end) != 2 or any(_number(v) is None for v in start+end):
        raise ValueError("مختصات خط مقطع معتبر نیست.")
    start,end=list(map(float,start)),list(map(float,end))
    data = _last_analysis
    grid = data['display_grid']
    points, cols, rows = grid['points'], grid['cols'], grid['rows']
    west,south = points[0][:2]
    east,north = points[-1][:2]
    if any(not (west <= p[0] <= east and south <= p[1] <= north) for p in [start,end]):
        raise ValueError("خط مقطع باید داخل کادر آبخوان باشد.")
    sx = 111320*math.cos(math.radians((start[1]+end[1])/2))
    length = math.hypot((end[0]-start[0])*sx,(end[1]-start[1])*111320)
    if length < 1:
        raise ValueError("طول مقطع باید دست‌کم یک متر باشد.")
    count=max(2,min(int(count),501))
    positions={i/(count-1) for i in range(count)}
    # Explicit crossing samples preserve even holes narrower than the regular spacing.
    from shapely.geometry import Polygon, LineString
    from shapely.ops import unary_union
    shape=unary_union([Polygon(p[0],p[1:]) for p in grid['polygons']])
    route=LineString([start,end])
    crossings=shape.boundary.intersection(route)
    def mark_crossings(geometry):
        if geometry.is_empty:
            return
        if hasattr(geometry,'geoms'):
            for part in geometry.geoms:
                mark_crossings(part)
        elif geometry.geom_type=='Point':
            t=route.project(geometry,normalized=True)
            positions.update(max(0,min(1,t+offset)) for offset in (-1e-7,0,1e-7))
        elif geometry.geom_type=='LineString':
            from shapely.geometry import Point
            for coord in [geometry.coords[0],geometry.coords[-1]]:
                mark_crossings(Point(coord))
    mark_crossings(crossings)
    result=[]
    for t in sorted(positions):
        lon,lat = [start[k]+(end[k]-start[k])*t for k in range(2)]
        values=None
        if _contains(grid['polygons'],lon,lat):
            x=max(0,min(cols-1-1e-8,(lon-west)/(east-west)*(cols-1)))
            y=max(0,min(rows-1-1e-8,(lat-south)/(north-south)*(rows-1)))
            i,j=int(x),int(y)
            u,v=x-i,y-j
            values=[sum(p[k]*weight for p,weight in [
                (points[j*cols+i],(1-u)*(1-v)),(points[j*cols+i+1],u*(1-v)),
                (points[(j+1)*cols+i],(1-u)*v),(points[(j+1)*cols+i+1],u*v)]) for k in (2,3,4)]
        result.append({'distance_m':length*t,'lon':lon,'lat':lat,'levels':values})
    return {'samples':result,'length_m':length,'bedrock_source':data['grid']['bedrock_source']}


def well_details(feature_index, name, lon, lat):
    prepare(feature_index)
    candidates=[w for w in _prepared[feature_index]['current'].values() if w['name']==name]
    if not candidates:
        raise ValueError("پیزومتر در آبخوان انتخابی پیدا نشد.")
    well=min(candidates,key=lambda w:(w['lon']-lon)**2+(w['lat']-lat)**2)
    records=sorted([{'year':y,'month':m,'water_year':y if m>=7 else y-1,
                     'level':well['ground']-depth,'depth':depth,'ordinal':y*12+m}
                    for (key,y,m),depth in _readings.items() if key==well['key']],
                   key=lambda r:r['ordinal'])
    annual=[]
    for wy in sorted({r['water_year'] for r in records}):
        months=[r for r in records if r['water_year']==wy]
        annual.append({'water_year':wy,'months':len(months),
                       'mean_msl':sum(r['level'] for r in months)/len(months),
                       'observed_decline_m':months[0]['level']-months[-1]['level'] if len(months)>1 else None})
    return {'name':well['name'],'ground_msl':well['ground'],'records':records,'annual':annual}


def urban_overlay(features):
    """Clip public city footprints to the selected aquifer and drape for display only."""
    if not _last_analysis:
        return []
    from shapely.geometry import shape, Polygon, Point
    from shapely.ops import unary_union
    data = _last_analysis
    boundary = unary_union([Polygon(p[0], p[1:]) for p in data['display_grid']['polygons']])
    mesh = data['volume_mesh']['vertices']
    pixels = [[c['lon'], c['lat'], c['remaining_m'] + c['lost_m']]
              for c in (data.get('pixel_water') or {}).get('cells', [])]
    center = boundary.centroid.y
    def position(coord):
        lon, lat = coord[:2]
        return [lon, lat, _idw(mesh, lon, lat, center),
                _idw(pixels, lon, lat, center) if pixels else 0]
    def parts(geometry):
        if geometry.is_empty:
            return
        if geometry.geom_type == 'Polygon':
            yield geometry
        elif hasattr(geometry, 'geoms'):
            for part in geometry.geoms:
                yield from parts(part)
    result = []
    for feature in features:
        city = shape(feature['geometry'])
        if not city.is_valid:
            city = city.buffer(0)
        clipped = city.intersection(boundary)
        if clipped.geom_type == 'Point' and not clipped.is_empty:
            result.append({'name': feature['properties']['name'],
                           'id': feature['properties']['id'],
                           'source': feature['properties'].get('source', ''),
                           'paths': [], 'label': position([clipped.x, clipped.y])})
            continue
        polygons = list(parts(clipped))
        if not polygons:
            continue
        point = max(polygons, key=lambda p: p.area).representative_point()
        label = feature['properties'].get('label')
        if label and clipped.covers(Point(label[:2])):
            point = Point(label[:2])
        paths = [list(ring.coords) for polygon in polygons
                 for ring in [polygon.exterior, *polygon.interiors]]
        result.append({'name': feature['properties']['name'],
                       'id': feature['properties']['id'],
                       'source': feature['properties'].get('source', ''),
                       'paths': [[position(p) for p in ring] for ring in paths],
                       'label': position([point.x, point.y])})
    return result


def call_json(command, argument_json="{}"):
    global _last_analysis
    arguments = json.loads(argument_json)
    if command == "catalog":
        result = catalog()
    elif command == "prepare":
        result = prepare(arguments["feature_index"])
    elif command == "analyze":
        result = analyze(arguments["feature_index"], arguments["baseline_year"],
                         arguments.get("sy"), arguments.get("bedrock_text", ""),
                         arguments.get("karat_thickness_m", 65.0), arguments.get("sy_text", ""),
                         cell_width_m=arguments.get('cell_width_m',4000), cell_height_m=arguments.get('cell_height_m',4000),
                         spatial_method=arguments.get('spatial_method','idw'), spline_smoothing=arguments.get('spline_smoothing',0))
        _last_analysis = result
    elif command == 'cross_section':
        result = cross_section(arguments['start'],arguments['end'])
    elif command == 'urban_overlay':
        result = urban_overlay(arguments.get('features', []))
    elif command == 'well_details':
        result = well_details(arguments['feature_index'],arguments['name'],arguments['lon'],arguments['lat'])
    else:
        raise ValueError("دستور ناشناخته است.")
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
