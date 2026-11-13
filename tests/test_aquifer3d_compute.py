from functools import partial
"""Physical checks for the Python model executed by the Pyodide worker."""

import importlib.util
import json
import math
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "frontend/assets/js/aquifer3d_compute.py"


def _model(name="نمونه", figure_depth="", grounds=None, fifth_current_only=False):
    spec = importlib.util.spec_from_file_location("aquifer3d_compute", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    square = [[[0, 0], [0.02, 0], [0.02, 0.02], [0, 0.02], [0, 0]]]
    geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"AQUIFER": name, "MAHDOUDE": name},
        "geometry": {"type": "Polygon", "coordinates": square}
    }]}
    wells = [("الف", .002, .002), ("ب", .018, .002),
             ("پ", .018, .018), ("ت", .002, .018)]
    if fifth_current_only:
        wells.append(("ث", .01, .01))
    grounds = grounds or [100] * len(wells)
    locations = "MAHDOUDE,AQUIFER,LOCATION,X,Y,LEVEL_MSL\n" + "".join(
        f"{name},{name},{well_name},{lon},{lat},{ground}\n"
        for (well_name, lon, lat), ground in zip(wells, grounds))
    measurements = ("MAHDOUDE,AQUIFER,LOCATION,WATER_TABLE,YEAR_PERSIAN,MONTH_PERSIAN\n" +
                    "".join(f"{name},{name},{well_name},{depth},{year},6\n"
                            for well_name, _, _ in wells
                            for year, depth in (
                                ([(1389, 10), (1404, 50)] if well_name == "ث" else
                                 [(1381, 10), (1389, 10), (1404, 20)])
                                if fifth_current_only else [(1381, 10), (1404, 20)])))
    module.initialize(json.dumps(geojson), locations, measurements, figure_depth)
    return module


def _corrected_figure():
    """Export values differ from the original contours to detect double tapering."""
    controls = [(-.001, -.001), (.021, -.001), (.021, .021), (-.001, .021),
                (.01, -.001), (.021, .01), (.01, .021), (-.001, .01)]
    csv = "lon,lat,bedrock_depth_m,source_depth_m,point_role,boundary_depth_m,taper_width_m\n"
    csv += "".join(
        f"{lon},{lat},5,60,{role},5,5000\n"
        for index, (lon, lat) in enumerate(controls)
        for role in ["digitized_inside" if index % 2 else "digitized_outside"])
    csv += ".01,.01,900,900,interpolated_surface,5,5000\n"
    csv += "0,0,5,900,boundary_assumption,5,5000\n"
    return csv


class Aquifer3DComputeTests(unittest.TestCase):
    def test_boundary_distance_uses_segments_including_holes_and_concavities(self):
        model = _model()
        metres_per_degree = math.pi * model.RADIUS_M / 180

        def ring(coordinates):
            return [[x / metres_per_degree, y / metres_per_degree]
                    for x, y in coordinates]

        outer = ring([(0, 0), (20000, 0), (20000, 20000), (0, 20000), (0, 0)])
        hole = ring([(4000, 4000), (6000, 4000), (6000, 6000), (4000, 6000),
                     (4000, 4000)])
        index = model._boundary_index([[outer, hole]], 0)
        for x, y, expected in [(5000, 0, 0), (100, 5000, 100),
                               (7000, 5000, 1000), (10000, 15000, 5000)]:
            with self.subTest(x=x, y=y):
                self.assertAlmostEqual(model._boundary_distance_m(
                    index, x / metres_per_degree, y / metres_per_degree), expected)

        concave = ring([(0, 0), (10000, 0), (10000, 3000), (3000, 3000),
                        (3000, 10000), (0, 10000), (0, 0)])
        index = model._boundary_index([[concave]], 0)
        self.assertAlmostEqual(model._boundary_distance_m(
            index, 5000 / metres_per_degree, 5000 / metres_per_degree), 2000)
        self.assertAlmostEqual(model._boundary_distance_m(
            index, 12000 / metres_per_degree, 5000 / metres_per_degree),
            math.sqrt(2000 ** 2 + 2000 ** 2))

    def test_shallow_edge_rule_preserves_interior_contour_depth(self):
        model = _model()
        rule = {"depth_m": 5, "width_m": 5000}
        self.assertEqual(model._edge_depth(205, 0, rule), 5)
        self.assertEqual(model._edge_depth(205, 2500, rule), 105)
        self.assertEqual(model._edge_depth(205, 5000, rule), 205)
        self.assertEqual(model._edge_depth(205, 9000, rule), 205)

    def test_corrected_csv_uses_raw_contours_and_ignores_synthetic_samples(self):
        model = _model()
        points, rule = model._depth_points(_corrected_figure())
        self.assertEqual(len(points), 8)
        self.assertEqual({point[2] for point in points}, {60})
        self.assertEqual(rule, {"depth_m": 5, "width_m": 5000})

    def test_well_minimum_constraint_is_local_and_preserves_edge_and_core(self):
        model = _model()
        latitude = 35
        metres_per_lon_degree = (math.pi * model.RADIUS_M / 180 *
                                  math.cos(math.radians(latitude)))
        guard_radius = 2375  # 95% of the 2500 m distance to either limit.
        rule = {"depth_m": 5, "width_m": 5000,
                "guards": [(2500 / metres_per_lon_degree, latitude, 100, guard_radius)]}
        plain_rule = {"depth_m": 5, "width_m": 5000}

        def depth(x, raw=10):
            return model._edge_depth(raw, x, rule, x / metres_per_lon_degree,
                                     latitude, latitude)

        self.assertAlmostEqual(depth(2500), 100)
        half_support = 2500 + guard_radius / 2
        self.assertGreater(depth(half_support),
                           model._edge_depth(10, half_support, plain_rule))
        self.assertLess(depth(half_support), depth(2500))
        self.assertAlmostEqual(depth(4999), model._edge_depth(10, 4999, plain_rule))
        self.assertEqual(depth(0), 5)
        self.assertEqual(depth(5000), 10)
        self.assertEqual(depth(6000), 10)
        # A minimum-depth guard must never lift a floor already deeper than it.
        self.assertEqual(depth(2500, raw=205), 105)

    def test_corrected_csv_reads_well_guard_without_treating_it_as_contour(self):
        model = _model()
        lines = _corrected_figure().splitlines()
        guarded_csv = (lines[0] + ",minimum_depth_m,constraint_radius_m\n" +
                       "".join(line + ",,\n" for line in lines[1:]) +
                       ".005,.01,5,900,well_minimum_constraint,5,5000,50,500\n")
        points, rule = model._depth_points(guarded_csv)
        self.assertEqual(len(points), 8)
        self.assertEqual({point[2] for point in points}, {60})
        self.assertEqual(rule["depth_m"], 5)
        self.assertEqual(rule["width_m"], 5000)
        self.assertEqual(len(rule["guards"]), 1)
        self.assertEqual(tuple(rule["guards"][0]), (.005, .01, 50, 500))

    def test_neyshabur_corrected_surface_and_sensitivity_keep_shallow_margin(self):
        model = _model("نیشابور", _corrected_figure())
        model.analyze = partial(model.analyze,user_layers_only=False)  # Explicit archival converter test.
        result = model.analyze(0, 1381, .1)
        metrics = result["metrics"]
        points = result["grid"]["points"]
        self.assertTrue(metrics["neyshabur_boundary_assumption"])
        self.assertEqual(metrics["neyshabur_boundary_depth_m"], 5)
        self.assertEqual(metrics["neyshabur_taper_width_m"], 5000)
        self.assertAlmostEqual(metrics["neyshabur_boundary_adjusted_cell_pct"], 100)
        # This 2.2 km wide basin is entirely within the transition. The first
        # grid cell is ~29 m from the edge; the centre is ~1.08 km from it.
        edge_depth = 100 - points[0][4]
        centre_depth = 100 - points[19 * 38 + 19][4]
        self.assertGreaterEqual(edge_depth, 5)
        self.assertLess(edge_depth, 5.02)
        self.assertGreater(centre_depth, 10)
        self.assertLess(centre_depth, 15)
        self.assertGreater(metrics["drainable_before_mcm"], 0)
        self.assertEqual(metrics["drainable_after_mcm"], 0)
        # Deepening the original contours by 20 m still leaves this narrow
        # basin dry at a 20 m water depth, because the edge stays at 5 m.
        sensitivity = metrics["sensitivity_20m"]
        self.assertEqual(sensitivity["after_plus_mcm"], 0)
        self.assertGreater(sensitivity["before_plus_mcm"],
                           metrics["drainable_before_mcm"])

        upload = "lon,lat,bedrock_msl\n" + "".join(
            f"{lon},{lat},30\n" for lon, lat, _ in model._figure_depth)
        overridden = model.analyze(0, 1381, .1, upload)
        self.assertEqual(overridden["grid"]["bedrock_source"], "uploaded")
        self.assertFalse(overridden["metrics"]["neyshabur_boundary_assumption"])
        self.assertIsNone(overridden["metrics"]["sensitivity_20m"])
        self.assertAlmostEqual(overridden["grid"]["points"][0][4], 30)
        self.assertAlmostEqual(overridden["metrics"]["drainable_after_mcm"],
                               5 * overridden["aquifer"]["area_km2"])

    def test_digitized_contours_are_not_weighted_by_pixel_sample_count(self):
        model = _model()
        contours = [(0, step / 100, 20) for step in range(-50, 51)]
        contours.append((1, 0, 80))
        self.assertAlmostEqual(model._contour_idw(contours, .5, 0, 0), 50)

    def test_relative_storage_uses_common_wells_and_persian_water_year(self):
        model = _model()
        result = model.analyze(0, 1381, .1)
        area = result["aquifer"]["area_km2"]
        self.assertEqual(result["dates"]["after_water_year"], 1403)
        self.assertEqual(result["wells"]["common"], 4)
        self.assertAlmostEqual(result["metrics"]["mean_head_decline_m"], 10)
        self.assertAlmostEqual(result["metrics"]["storage_change_mcm"], -area)
        self.assertIsNone(result["metrics"]["drainable_before_mcm"])
        self.assertFalse(result["grid"]["bedrock_real"])

    def test_absolute_drainable_volume_requires_and_uses_bedrock_elevations(self):
        model = _model()
        bedrock = "lon,lat,bedrock_msl\n" + "".join(
            f"{lon},{lat},40\n" for lon, lat in [
                (-.001, -.001), (.021, -.001), (.021, .021), (-.001, .021),
                (.01, -.001), (.021, .01), (.01, .021), (-.001, .01)
            ])
        result = model.analyze(0, 1381, .1, bedrock)
        area = result["aquifer"]["area_km2"]
        self.assertTrue(result["grid"]["bedrock_real"])
        self.assertAlmostEqual(result["metrics"]["drainable_before_mcm"], 5 * area)
        self.assertAlmostEqual(result["metrics"]["drainable_after_mcm"], 4 * area)
        self.assertAlmostEqual(result["metrics"]["storage_change_mcm"], -area)

    def test_neyshabur_figure_depth_uses_ground_elevation_and_uploaded_csv_overrides(self):
        figure = "lon,lat,bedrock_depth_m\n" + "".join(
            f"{lon},{lat},60\n" for lon, lat in [
                (-.001, -.001), (.021, -.001), (.021, .021), (-.001, .021),
                (.01, -.001), (.021, .01), (.01, .021), (-.001, .01)
            ])
        model = _model("نیشابور", figure, [80, 100, 120, 140])
        model.analyze = partial(model.analyze,user_layers_only=False)  # Explicit archival converter test.
        result = model.analyze(0, 1381, .1)
        area = result["aquifer"]["area_km2"]
        self.assertEqual(result["grid"]["bedrock_source"], "figure_s4")
        for point in result["grid"]["points"]:
            if point[5]:
                self.assertAlmostEqual(point[2] - point[4], 50)
        self.assertAlmostEqual(result["metrics"]["drainable_before_mcm"], 5 * area)
        self.assertAlmostEqual(result["metrics"]["drainable_after_mcm"], 4 * area)
        sensitivity = result["metrics"]["sensitivity_20m"]
        self.assertAlmostEqual(sensitivity["before_minus_mcm"], 3 * area)
        self.assertAlmostEqual(sensitivity["before_plus_mcm"], 7 * area)
        self.assertAlmostEqual(sensitivity["after_minus_mcm"], 2 * area)
        self.assertAlmostEqual(sensitivity["after_plus_mcm"], 6 * area)
        upload = "lon,lat,bedrock_msl\n" + "".join(
            f"{lon},{lat},30\n" for lon, lat in [
                (-.001, -.001), (.021, -.001), (.021, .021), (-.001, .021),
                (.01, -.001), (.021, .01), (.01, .021), (-.001, .01)
            ])
        overridden = model.analyze(0, 1381, .1, upload)
        self.assertEqual(overridden["grid"]["bedrock_source"], "uploaded")
        self.assertAlmostEqual(overridden["grid"]["points"][19 * 38 + 19][4], 30)
        self.assertGreater(overridden["metrics"]["drainable_before_mcm"],
                           result["metrics"]["drainable_before_mcm"])

    def test_karat_scenario_has_explicit_assumed_thickness_and_sensitivity(self):
        model = _model("کرات")
        model.analyze = partial(model.analyze,user_layers_only=False)  # Explicit archival converter test.
        result = model.analyze(0, 1381, .1, karat_thickness_m=65)
        area = result["aquifer"]["area_km2"]
        metrics = result["metrics"]
        self.assertEqual(result["grid"]["bedrock_source"], "karat_scenario")
        self.assertFalse(result["grid"]["bedrock_real"])
        self.assertIsNone(metrics["bedrock_coverage_pct"])
        self.assertEqual(metrics["karat_thickness_m"], 65)
        self.assertEqual(metrics["karat_max_bedrock_depth_m"], 300)
        self.assertEqual(metrics["karat_capped_cell_count"], 0)
        self.assertAlmostEqual(metrics["drainable_before_mcm"], 7.5 * area)
        self.assertAlmostEqual(metrics["drainable_after_mcm"], 6.5 * area)
        self.assertAlmostEqual(metrics["storage_change_mcm"], -area)
        self.assertAlmostEqual(metrics["sensitivity_20m"]["after_minus_mcm"], 4.5 * area)
        self.assertAlmostEqual(metrics["sensitivity_20m"]["after_plus_mcm"], 8.5 * area)
        for point in result["grid"]["points"]:
            if point[5]:
                self.assertAlmostEqual(point[3] - point[4], 65)

    def test_karat_floor_uses_all_current_wells_and_stays_fixed_across_baselines(self):
        model = _model("کرات", fifth_current_only=True)
        model.analyze = partial(model.analyze,user_layers_only=False)  # Explicit archival converter test.
        early = model.analyze(0, 1381, .1)
        later = model.analyze(0, 1389, .1)
        self.assertEqual(early["wells"]["common"], 4)
        self.assertEqual(later["wells"]["common"], 5)
        self.assertEqual(early["metrics"]["karat_current_wells"], 5)
        self.assertLess(early["metrics"]["well_coverage_pct"], 100)
        for first, second in zip(early["grid"]["points"], later["grid"]["points"]):
            self.assertEqual(first[4], second[4])
        self.assertGreater(early["metrics"]["drainable_after_mcm"],
                           later["metrics"]["drainable_after_mcm"])
        self.assertAlmostEqual(later["metrics"]["drainable_after_mcm"],
                               6.5 * later["aquifer"]["area_km2"])

    def test_karat_bedrock_depth_is_capped_at_300m_below_fixed_ground(self):
        model = _model("کرات", grounds=[100, 120, 140, 160, 180],
                       fifth_current_only=True)
        model.analyze = partial(model.analyze,user_layers_only=False)  # Explicit archival converter test.
        early = model.analyze(0, 1381, .1, karat_thickness_m=270)
        later = model.analyze(0, 1389, .1, karat_thickness_m=270)
        points = [point for point in later["grid"]["points"] if point[5]]
        metrics = later["metrics"]
        self.assertGreater(metrics["karat_capped_cell_count"], 0)
        self.assertLess(metrics["karat_capped_cell_count"], len(points))
        self.assertAlmostEqual(metrics["karat_actual_max_bedrock_depth_m"], 300)
        ground_points = [(well["lon"], well["lat"], well["ground"])
                         for well in model._locations]
        ground_at = lambda point: model._idw(
            ground_points, point[0], point[1], .01)
        self.assertTrue(all(ground_at(point) - point[4] <= 300 + 1e-9
                            for point in points))
        for first, second in zip(early["grid"]["points"], later["grid"]["points"]):
            self.assertEqual(first[4], second[4])
        cell_scale = .1 * later["aquifer"]["area_km2"] / len(points)
        expected_after_plus = cell_scale * sum(
            max(0, point[3] - max(point[3] - 290, ground_at(point) - 300))
            for point in points)
        self.assertAlmostEqual(metrics["sensitivity_20m"]["after_plus_mcm"],
                               expected_after_plus)
        with self.assertRaises(ValueError):
            model.analyze(0, 1389, .1, karat_thickness_m=301)
        upload = "lon,lat,bedrock_msl\n" + "".join(
            f"{lon},{lat},-250\n" for lon, lat in [
                (-.001, -.001), (.021, -.001), (.021, .021), (-.001, .021),
                (.01, -.001), (.021, .01), (.01, .021), (-.001, .01)
            ])
        uploaded = model.analyze(0, 1389, .1, upload, karat_thickness_m=301)
        self.assertEqual(uploaded["grid"]["bedrock_source"], "uploaded")
        self.assertIsNone(uploaded["metrics"]["karat_max_bedrock_depth_m"])
        self.assertAlmostEqual(uploaded["grid"]["points"][19 * 38 + 19][4], -250)
