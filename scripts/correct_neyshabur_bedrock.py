"""Rebuild the shallow-boundary scenario in client-side Pyodide.

Execute aquifer3d_compute.py first in the same Python namespace, then call
correct_neyshabur_bedrock(source_csv, geojson_text, source_metadata_text,
                          locations_text, measurements_text).
The caller saves the returned CSV/metadata; no data is sent to a server.
"""

import hashlib


def correct_neyshabur_bedrock(source_csv, geojson_text, source_metadata_text,
                            locations_text, measurements_text):
    controls, existing_rule = _depth_points(source_csv)
    if existing_rule is not None:
        raise ValueError("Use the unchanged SOURCE CSV, not an already corrected file.")
    feature = next(feature for feature in json.loads(geojson_text)["features"]
                   if _normal(feature["properties"].get("AQUIFER")) == _normal("نیشابور")
                   and _normal(feature["properties"].get("MAHDOUDE")) == _normal("نیشابور"))
    polygons = _polygons(feature)
    west, south, east, north = _extent(polygons)
    center_lat = (south + north) / 2
    boundary = _boundary_index(polygons, center_lat)
    sx, sy = boundary[:2]
    rule = {"depth_m": 5.0, "width_m": 5000.0}
    deepest = {}
    for row in csv.DictReader(io.StringIO(measurements_text)):
        depth = _number(row.get("WATER_TABLE"))
        year, month = _number(row.get("YEAR_PERSIAN")), _number(row.get("MONTH_PERSIAN"))
        if depth is not None and depth >= 0 and year is not None and month is not None and (year, month) <= (CURRENT_YEAR, CURRENT_MONTH):
            key = _key(row)
            deepest[key] = max(depth, deepest.get(key, 0))
    guard_names = []
    guards = []
    for row in csv.DictReader(io.StringIO(locations_text)):
        key = _key(row)
        lon, lat = _number(row.get("X")), _number(row.get("Y"))
        if key[:2] != (_normal("نیشابور"), _normal("نیشابور")) or key not in deepest or None in (lon, lat):
            continue
        if not _contains(polygons, lon, lat):
            continue
        distance = _boundary_distance_m(boundary, lon, lat)
        if distance >= rule["width_m"]:
            continue
        # The support disk stays strictly inside both the aquifer and the
        # transition band. Thus neither the 5m edge nor the core is altered.
        radius = round(.95 * min(distance, rule["width_m"] - distance), 3)
        if radius <= 0:
            raise ValueError("A measured well lies on the boundary; the shallow-boundary assumption needs review.")
        guards.append((lon, lat, round(deepest[key] + 5.0, 3), radius))
        guard_names.append(row.get("LOCATION", ""))
    if guards:
        rule["guards"] = guards
    grid_spacing_m, boundary_spacing_m = 1000.0, 500.0
    rows, occupied = [], set()
    counts = defaultdict(int)
    adjusted_controls = preserved_controls = 0

    def append(lon, lat, depth, raw_depth, role, distance, minimum=None, radius=None, name=""):
        key = (round(lon, 9), round(lat, 9))
        if key in occupied and role != "well_minimum_constraint":
            return
        occupied.add(key)
        rows.append([f"{lon:.9f}", f"{lat:.9f}",
                     "" if depth is None else f"{depth:.3f}",
                     "" if raw_depth is None else f"{raw_depth:.3f}",
                     role, f"{distance:.3f}", "5", "5000",
                     "" if minimum is None else f"{minimum:.3f}",
                     "" if radius is None else f"{radius:.3f}", name])
        counts[role] += 1

    for lon, lat, raw_depth in controls:
        distance = _boundary_distance_m(boundary, lon, lat)
        inside = _contains(polygons, lon, lat)
        if inside:
            depth = _edge_depth(raw_depth, distance, rule, lon, lat, center_lat)
            adjusted_controls += distance < rule["width_m"]
            preserved_controls += distance >= rule["width_m"]
        else:
            # Preserve the georeferencing evidence, but publish no corrected
            # aquifer depth outside the supplied geometry.
            depth = None
        append(lon, lat, depth, raw_depth,
               "digitized_inside" if inside else "digitized_outside", distance)

    # Dense export samples support GIS use. The application reconstructs the
    # field analytically from original controls and the same taper rule.
    ncols = math.ceil((east - west) * sx / grid_spacing_m)
    nrows = math.ceil((north - south) * sy / grid_spacing_m)
    for row in range(nrows):
        lat = south + (row + .5) * grid_spacing_m / sy
        for col in range(ncols):
            lon = west + (col + .5) * grid_spacing_m / sx
            if not _contains(polygons, lon, lat):
                continue
            raw_depth = _contour_idw(controls, lon, lat, center_lat)
            distance = _boundary_distance_m(boundary, lon, lat)
            append(lon, lat, _edge_depth(raw_depth, distance, rule, lon, lat, center_lat), raw_depth,
                   "interpolated_surface", distance)

    for (lon, lat, minimum, radius), name in zip(guards, guard_names):
        raw_depth = _contour_idw(controls, lon, lat, center_lat)
        distance = _boundary_distance_m(boundary, lon, lat)
        depth = _edge_depth(raw_depth, distance, rule, lon, lat, center_lat)
        append(lon, lat, depth, raw_depth, "well_minimum_constraint", distance,
               minimum, radius, name)
        # Resolve small local supports in the exported CSV as well as in the
        # analytic browser model, even when a well lies close to the edge.
        for fraction in (.25, .5, .75, 1.0):
            for angle in range(0, 360, 45):
                x = lon + fraction * radius * math.cos(math.radians(angle)) / sx
                y = lat + fraction * radius * math.sin(math.radians(angle)) / sy
                raw_depth = _contour_idw(controls, x, y, center_lat)
                distance = _boundary_distance_m(boundary, x, y)
                append(x, y, _edge_depth(raw_depth, distance, rule, x, y, center_lat),
                       raw_depth, "interpolated_surface", distance)

    # Preserve every vertex, including holes and small disconnected polygons;
    # densify long segments rather than simplifying the supplied boundary.
    for polygon in polygons:
        for ring in polygon:
            previous = ring[-1]
            for current in ring:
                length = math.hypot((current[0] - previous[0]) * sx,
                                    (current[1] - previous[1]) * sy)
                steps = max(1, math.ceil(length / boundary_spacing_m))
                for step in range(steps):
                    fraction = step / steps
                    lon = previous[0] + fraction * (current[0] - previous[0])
                    lat = previous[1] + fraction * (current[1] - previous[1])
                    append(lon, lat, rule["depth_m"], None, "boundary_assumption", 0.0)
                previous = current

    columns = ["lon", "lat", "bedrock_depth_m", "source_depth_m", "point_role",
               "distance_to_boundary_m", "boundary_depth_m", "taper_width_m",
               "minimum_depth_m", "constraint_radius_m", "well_name"]
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(sorted(rows, key=lambda row: row[4] == "digitized_outside"))
    restored, restored_rule = _depth_points(output.getvalue())
    if sorted(restored) != sorted(controls) or restored_rule != rule:
        raise ValueError("Corrected export did not preserve the original contour controls and boundary rule.")
    depths = [float(row[2]) for row in rows if row[2]]
    metadata = json.loads(source_metadata_text)
    metadata.update({
        "dataset_type": "digitized source plus explicitly assumed shallow aquifer boundary",
        "quality": "Geometric scenario requested by user; the shallow boundary is not inferred from the paper or measured geology.",
        "original_source_csv": "NEYSHABUR_BEDROCK_DEPTH_SOURCE.csv",
        "source_csv_sha256": hashlib.sha256(source_csv.encode("utf-8")).hexdigest(),
        "aquifer_geometry_sha256": hashlib.sha256(json.dumps(feature["geometry"], sort_keys=True).encode("utf-8")).hexdigest(),
        "record_count": len(rows),
        "source_control_count": len(controls),
        "well_minimum_constraint_count": len(guards),
        "records_by_role": dict(counts),
        "corrected_depth_null_count": counts["digitized_outside"],
        "inside_source_controls_adjusted": adjusted_controls,
        "inside_source_controls_unchanged": preserved_controls,
        "depth_min_m": min(depths),
        "depth_max_m": max(depths),
        "csv_columns": columns,
        "boundary_correction": {
            "boundary_depth_m": rule["depth_m"],
            "taper_width_m": rule["width_m"],
            "formula": "D = 5 + (D_raw - 5) * t^2 * (3 - 2*t); t = min(max(distance/5000, 0), 1)",
            "well_lower_bound": "Final D is max(tapered D, each compact local constraint). At a well, minimum D = deepest observed WATER_TABLE through Shahrivar 1404 + 5m assumed saturated margin.",
            "well_constraint_formula": "B_i = 5 + (minimum_depth_i - 5) * (1 - (r/R_i)^2)^2 for r<R_i, else 5; R_i=0.95*min(distance_to_boundary_i,5000-distance_to_boundary_i). Supports cannot touch boundary or unchanged core.",
            "well_constraint_sources": ["LOCATION.csv", "DATA.csv"],
            "well_constraint_count": len(guards),
            "distance_method": "nearest segment across all exterior and hole rings; local equirectangular metre projection",
            "projection_latitude_deg": center_lat,
            "interior_rule": "At distance >= 5000m, preserve original contour-IDW depth exactly.",
            "source_interpolation": "IDW squared distance over the nearest point of each original contour depth, using four nearest depth groups",
            "grid_sample_spacing_m": grid_spacing_m,
            "maximum_boundary_sample_spacing_m": boundary_spacing_m,
            "boundary_vertices": "Every supplied ring vertex is preserved, including holes and small polygon parts.",
            "outside_controls": "Retain source_depth_m for original interpolation/provenance; bedrock_depth_m is blank outside aquifer.",
            "runtime": "Parse only digitized_inside/digitized_outside source_depth_m as original contours, then apply the analytic distance taper and well constraints once. Synthetic rows must not enter contour-IDW.",
            "sensitivity": "Change original interior depths +/-20m then apply the same taper and fixed well constraints, preserving the 5m boundary.",
            "execution": "Client-side Python in Pyodide; scripts/correct_neyshabur_bedrock.py with aquifer3d_compute.py helpers",
        },
    })
    metadata["known_limitations"] += [
        "The supplied aquifer boundary is assumed to be shallow everywhere, including holes; an administrative or groundwater-divide boundary need not be a bedrock outcrop.",
        "The 5m edge depth and 5km transition are explicit geometric assumptions, not field-calibrated values.",
        "Well constraints only enforce compatibility with observed water depths; the additional 5m saturated margin and compact support shape are assumptions, not measured bedrock depths.",
        "Synthetic boundary and grid samples are not independent observations and do not improve measured coverage.",
        "Shallow assumed bedrock may lie above interpolated water heads; model cells then have zero saturated thickness, not confirmed observed drying.",
        "CSV decimals encode a reproducible scenario and do not imply survey precision.",
    ]
    return {"csv": output.getvalue(), "metadata": metadata}
