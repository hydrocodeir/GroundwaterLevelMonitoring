import unittest

from app.data_service import (
    DEFAULT_ANALYSIS_YEARS,
    MONTHS_PER_YEAR,
    NEAREST_PRECIPITATION_STATION_COUNT,
    WATER_YEAR_END_MONTH,
    WATER_YEAR_START_MONTH,
    GroundwaterData,
    normalize_name,
)


class GroundwaterDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = GroundwaterData()

    @staticmethod
    def year_month(month_index: int) -> tuple[int, int]:
        return (
            (month_index - 1) // MONTHS_PER_YEAR,
            (month_index - 1) % MONTHS_PER_YEAR + 1,
        )

    def group_with_span(self, minimum_months: int) -> tuple[str, int, int]:
        for group_id in self.service.groups:
            frame = self.service.monthly[
                self.service.monthly["_aquifer_id"] == group_id
            ]
            minimum = int(frame["_month_index"].min())
            maximum = int(frame["_month_index"].max())
            if maximum - minimum + 1 >= minimum_months:
                return group_id, minimum, maximum
        self.skipTest(f"هیچ آبخوانی با حداقل {minimum_months} ماه داده وجود ندارد")

    def test_all_groups_produce_dashboard_payloads(self) -> None:
        total_wells = 0
        for group_id, group in self.service.groups.items():
            payload = self.service.dashboard(group_id)
            self.assertEqual(len(payload["wells"]), group["well_count"])
            start_index = (
                payload["filters"]["start_year"] * MONTHS_PER_YEAR
                + payload["filters"]["start_month"]
            )
            end_index = (
                payload["filters"]["end_year"] * MONTHS_PER_YEAR
                + payload["filters"]["end_month"]
            )
            expected_months = end_index - start_index + 1
            self.assertEqual(
                len(payload["hydrographs"]["arithmetic"]),
                expected_months,
            )
            self.assertEqual(
                len(payload["hydrographs"]["thiessen"]),
                expected_months,
            )
            self.assertEqual(
                payload["stats"]["selected_wells"] + payload["stats"]["excluded_wells"],
                group["well_count"],
            )
            total_wells += len(payload["wells"])
        self.assertEqual(total_wells, len(self.service.locations))

    def test_default_period_uses_latest_group_data(self) -> None:
        group_id = next(iter(self.service.groups))
        frame = self.service.monthly[
            self.service.monthly["_aquifer_id"] == group_id
        ]
        minimum = int(frame["_month_index"].min())
        maximum = int(frame["_month_index"].max())
        expected_start = max(
            minimum,
            maximum - DEFAULT_ANALYSIS_YEARS * MONTHS_PER_YEAR,
        )
        payload = self.service.dashboard(group_id)
        start_year, start_month = self.year_month(expected_start)
        end_year, end_month = self.year_month(maximum)

        self.assertEqual(payload["filters"]["start_year"], start_year)
        self.assertEqual(payload["filters"]["start_month"], start_month)
        self.assertEqual(payload["filters"]["end_year"], end_year)
        self.assertEqual(payload["filters"]["end_month"], end_month)
        self.assertEqual(
            payload["stats"]["first_month"],
            f"{start_year}-{start_month:02d}",
        )
        self.assertEqual(
            payload["stats"]["last_month"],
            f"{end_year}-{end_month:02d}",
        )

    def test_default_trend_comparison_uses_latest_water_year(self) -> None:
        group_id = next(iter(self.service.groups))
        payload = self.service.dashboard(group_id)
        filters = payload["filters"]
        end_index = (
            filters["end_year"] * MONTHS_PER_YEAR + filters["end_month"]
        )
        expected_water_year = self.service._water_year_for_month(
            filters["end_year"],
            filters["end_month"],
        )
        group_frame = self.service.monthly[
            self.service.monthly["_aquifer_id"] == group_id
        ]
        minimum = int(group_frame["_month_index"].min())
        expected_start = max(
            minimum,
            expected_water_year * MONTHS_PER_YEAR + WATER_YEAR_START_MONTH,
        )
        start_year, start_month = self.year_month(expected_start)
        end_year, end_month = self.year_month(end_index)

        self.assertEqual(filters["comparison_start_year"], start_year)
        self.assertEqual(filters["comparison_start_month"], start_month)
        self.assertEqual(filters["comparison_end_year"], end_year)
        self.assertEqual(filters["comparison_end_month"], end_month)
        self.assertFalse(filters["comparison_enabled"])
        self.assertIsNone(
            payload["hydrographs"]["thiessen_comparison_trend"]
        )
        self.assertTrue(
            all(well["comparison_trend"] is None for well in payload["wells"])
        )

    def test_custom_trend_comparison_is_returned_for_aquifer_and_wells(self) -> None:
        group_id, minimum, maximum = self.group_with_span(24)
        analysis_start = minimum
        analysis_end = min(maximum, minimum + 23)
        comparison_start = analysis_end - 5
        start_year, start_month = self.year_month(analysis_start)
        end_year, end_month = self.year_month(analysis_end)
        comparison_start_year, comparison_start_month = self.year_month(
            comparison_start
        )
        payload = self.service.dashboard(
            group_id,
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
            comparison_start_year=comparison_start_year,
            comparison_start_month=comparison_start_month,
            comparison_end_year=end_year,
            comparison_end_month=end_month,
            comparison_enabled=True,
            continuous_only=False,
        )
        expected_labels = [
            label
            for _, label in self.service._period_months(
                comparison_start_year,
                comparison_start_month,
                end_year,
                end_month,
            )
        ]

        self.assertEqual(
            [
                item[0]
                for item in payload["hydrographs"][
                    "thiessen_comparison_trend"
                ]["series"]
            ],
            expected_labels,
        )
        self.assertTrue(
            all(
                well["comparison_trend"] is not None
                for well in payload["wells"]
            )
        )
        self.assertTrue(payload["filters"]["comparison_enabled"])

    def test_annual_changes_aggregate_water_year_metrics(self) -> None:
        payload = self.service.dashboard(next(iter(self.service.groups)))
        self.assertTrue(payload["annual_changes"])
        for row in payload["annual_changes"]:
            self.assertIn("arithmetic", row["decline"])
            self.assertIn("thiessen", row["decline"])
            self.assertLessEqual(
                row["selected_month_count"],
                MONTHS_PER_YEAR,
            )
            self.assertEqual(
                row["is_complete"],
                row["selected_month_count"] == MONTHS_PER_YEAR,
            )
            self.assertTrue(
                row["precipitation_total"] is None
                or row["precipitation_total"] >= 0
            )
            self.assertTrue(
                row["aet_total"] is None or row["aet_total"] >= 0
            )
            self.assertTrue(
                row["ndvi_mean"] is None
                or -1 <= row["ndvi_mean"] <= 1
            )
            self.assertTrue(
                row["ndvi_median"] is None
                or -1 <= row["ndvi_median"] <= 1
            )

    def test_partial_water_year_is_marked_incomplete(self) -> None:
        group_id, minimum, maximum = self.group_with_span(6)
        end_index = min(maximum, minimum + 5)
        start_year, start_month = self.year_month(minimum)
        end_year, end_month = self.year_month(end_index)
        payload = self.service.dashboard(
            group_id,
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
            continuous_only=False,
        )

        self.assertTrue(payload["annual_changes"])
        self.assertTrue(
            all(not row["is_complete"] for row in payload["annual_changes"])
        )

    def test_comparison_default_period_uses_full_dynamic_data_domain(self) -> None:
        payload = self.service.comparison()
        minimum = int(self.service.monthly["_month_index"].min())
        maximum = int(self.service.monthly["_month_index"].max())
        expected_start = max(
            minimum,
            maximum - DEFAULT_ANALYSIS_YEARS * MONTHS_PER_YEAR,
        )
        start_year, start_month = self.year_month(expected_start)
        end_year, end_month = self.year_month(maximum)

        self.assertEqual(payload["filters"]["minimum_year"], self.year_month(minimum)[0])
        self.assertEqual(payload["filters"]["minimum_month"], self.year_month(minimum)[1])
        self.assertEqual(payload["filters"]["start_year"], start_year)
        self.assertEqual(payload["filters"]["start_month"], start_month)
        self.assertEqual(payload["filters"]["end_year"], end_year)
        self.assertEqual(payload["filters"]["end_month"], end_month)
        self.assertEqual(len(payload["aquifers"]), len(self.service.groups))

    def test_comparison_uses_only_wells_covering_the_selected_period(self) -> None:
        payload = self.service.comparison()
        filters = payload["filters"]
        start_index = (
            filters["start_year"] * MONTHS_PER_YEAR + filters["start_month"]
        )
        end_index = filters["end_year"] * MONTHS_PER_YEAR + filters["end_month"]

        for aquifer in payload["aquifers"]:
            group_frame = self.service.monthly[
                self.service.monthly["_aquifer_id"] == aquifer["id"]
            ]
            expected = self.service._selected_join_keys(
                group_frame,
                start_index,
                end_index,
                continuous_only=True,
            )
            expected_wells = self.service.locations[
                (self.service.locations["_aquifer_id"] == aquifer["id"])
                & (self.service.locations["_join_key"].isin(expected))
            ]
            self.assertEqual(aquifer["selected_wells"], len(expected_wells))

    def test_comparison_metrics_match_single_aquifer_dashboard(self) -> None:
        comparison = self.service.comparison()
        filters = comparison["filters"]
        aquifer = next(
            item
            for item in comparison["aquifers"]
            if item["methods"]["thiessen"]["observed_decline"] is not None
        )
        dashboard = self.service.dashboard(
            aquifer["id"],
            start_year=filters["start_year"],
            start_month=filters["start_month"],
            end_year=filters["end_year"],
            end_month=filters["end_month"],
            continuous_only=True,
        )

        for method in ("thiessen", "arithmetic"):
            series = dict(dashboard["hydrographs"][method])
            start_label = dashboard["stats"]["first_month"]
            end_label = dashboard["stats"]["last_month"]
            expected_decline = series[start_label] - series[end_label]
            metrics = aquifer["methods"][method]
            self.assertAlmostEqual(
                metrics["observed_decline"],
                expected_decline,
                places=2,
            )
            self.assertEqual(
                metrics["trend_decline_per_year"],
                dashboard["hydrographs"][f"{method}_trend"]["decline_per_year"],
            )

    def test_precipitation_series_matches_hydrograph_period(self) -> None:
        payload = self.service.dashboard(next(iter(self.service.groups)))
        precipitation = payload["precipitation"]
        hydrograph_months = [item[0] for item in payload["hydrographs"]["thiessen"]]

        self.assertEqual(
            [item[0] for item in precipitation["series"]],
            hydrograph_months,
        )
        self.assertEqual(precipitation["unit"], "میلی‌متر در ماه")
        self.assertTrue(
            all(
                value is None or value >= 0
                for _, value in precipitation["series"]
            )
        )
        self.assertTrue(precipitation["stations"])
        for station in precipitation["stations"]:
            self.assertEqual(
                [item[0] for item in station["series"]],
                hydrograph_months,
            )
            self.assertTrue(
                all(
                    value is None or value >= 0
                    for _, value in station["series"]
                )
            )

    def test_ndvi_series_matches_hydrograph_period(self) -> None:
        payload = self.service.dashboard(next(iter(self.service.groups)))
        ndvi = payload["ndvi"]
        hydrograph_months = [
            item[0] for item in payload["hydrographs"]["thiessen"]
        ]

        self.assertEqual(ndvi["default_metric"], "median")
        self.assertEqual(set(ndvi["metrics"]), {"mean", "median", "max"})
        for series in ndvi["metrics"].values():
            self.assertEqual([item[0] for item in series], hydrograph_months)
            self.assertTrue(
                all(
                    value is None or -1 <= value <= 1
                    for _, value in series
                )
            )

    def test_aet_series_matches_hydrograph_period(self) -> None:
        payload = self.service.dashboard(next(iter(self.service.groups)))
        aet = payload["aet"]
        hydrograph_months = [
            item[0] for item in payload["hydrographs"]["thiessen"]
        ]

        self.assertEqual(aet["unit"], "میلی‌متر در ماه")
        self.assertEqual([item[0] for item in aet["series"]], hydrograph_months)
        self.assertTrue(
            all(
                value is None or value >= 0
                for _, value in aet["series"]
            )
        )

    def test_ndvi_matches_the_aquifer_boundary_names(self) -> None:
        group_id = next(
            group_id
            for group_id, group in self.service.groups.items()
            if group["aquifer_key"]
            != normalize_name(
                self.service.boundary_matches[group_id]["aquifer"].properties[
                    "AQUIFER"
                ]
            )
        )
        properties = self.service.boundary_matches[group_id][
            "aquifer"
        ].properties
        selected = self.service.ndvi[
            (
                self.service.ndvi["_mahdoude_key"]
                == normalize_name(properties["MAHDOUDE"])
            )
            & (
                self.service.ndvi["_aquifer_key"]
                == normalize_name(properties["AQUIFER"])
            )
        ].dropna(subset=["NDVI_MEAN", "NDVI_MEDIAN", "NDVI_MAX"], how="all")
        month_index = int(selected.iloc[0]["_month_index"])
        year, month = self.year_month(month_index)
        payload = self.service._ndvi_payload(
            group_id,
            [(month_index, f"{year}-{month:02d}")],
        )

        self.assertTrue(
            any(
                value is not None
                for series in payload["metrics"].values()
                for _, value in series
            )
        )

    def test_precipitation_uses_mean_of_all_stations_inside_mahdoude(self) -> None:
        group_id = next(
            group_id
            for group_id, selection in self.service.precipitation_selections.items()
            if selection["method"] == "inside_mahdoude"
        )
        payload = self.service.dashboard(group_id)
        precipitation = payload["precipitation"]
        station_ids = [station["id"] for station in precipitation["stations"]]
        month, actual = next(
            item for item in precipitation["series"] if item[1] is not None
        )
        expected = self.service.precipitation[
            self.service.precipitation["station_id"].isin(station_ids)
            & (self.service.precipitation["_month"] == month)
        ]["precip"].mean()

        self.assertEqual(precipitation["method"], "inside_mahdoude")
        self.assertGreaterEqual(precipitation["station_count"], 1)
        self.assertAlmostEqual(actual, expected, places=2)

    def test_precipitation_uses_three_nearest_stations_when_none_are_inside(self) -> None:
        group_id = next((
            group_id
            for group_id, selection in self.service.precipitation_selections.items()
            if selection["method"] == "nearest_available"
        ), None)
        if group_id is None:
            self.skipTest("همه محدوده‌ها ایستگاه بارش داخلی دارند")
        precipitation = self.service.dashboard(group_id)["precipitation"]
        distances = [
            station["distance_km"]
            for station in precipitation["stations"]
        ]

        expected_count = min(
            NEAREST_PRECIPITATION_STATION_COUNT,
            len(self.service.precipitation_stations),
        )
        self.assertEqual(precipitation["method"], "nearest_available")
        self.assertEqual(precipitation["station_count"], expected_count)
        self.assertEqual(distances, sorted(distances))
        self.assertTrue(all(distance > 0 for distance in distances))
        self.assertTrue(
            all(station["mahdoude"] for station in precipitation["stations"])
        )

    def test_dynamic_thiessen_weights_are_normalized(self) -> None:
        for group_id in self.service.groups:
            payload = self.service.dashboard(group_id)
            features = payload["thiessen_polygons"]["features"]
            if features:
                total = sum(feature["properties"]["weight"] for feature in features)
                self.assertAlmostEqual(total, 1.0, places=4)

    def test_spatial_navigation_contains_all_selectable_aquifers(self) -> None:
        navigation = self.service.spatial_navigation()
        self.assertEqual(
            len(navigation["aquifers"]["features"]),
            len(self.service.groups),
        )
        self.assertEqual(
            len(navigation["mahdoudes"]["features"]),
            len(self.service.mahdoude_features),
        )
        self.assertTrue(
            all(
                feature["properties"]["id"] in self.service.groups
                for feature in navigation["aquifers"]["features"]
            )
        )

    def test_disabling_full_range_filter_includes_at_least_as_many_wells(self) -> None:
        group_id = next(iter(self.service.groups))
        strict = self.service.dashboard(group_id, continuous_only=True)
        relaxed = self.service.dashboard(
            group_id,
            continuous_only=False,
        )
        self.assertGreaterEqual(
            relaxed["stats"]["selected_wells"],
            strict["stats"]["selected_wells"],
        )

    def test_manual_well_selection_rebuilds_calculations(self) -> None:
        group_id = next(iter(self.service.groups))
        automatic = self.service.dashboard(
            group_id,
            continuous_only=False,
        )
        selected_ids = [
            well["id"] for well in automatic["wells"] if well["has_range_data"]
        ][:2]
        manual = self.service.dashboard(
            group_id,
            start_year=automatic["filters"]["start_year"],
            start_month=automatic["filters"]["start_month"],
            end_year=automatic["filters"]["end_year"],
            end_month=automatic["filters"]["end_month"],
            manual_selection=True,
            selected_well_ids=selected_ids,
        )

        self.assertTrue(manual["filters"]["manual_selection"])
        self.assertEqual(set(manual["filters"]["selected_well_ids"]), set(selected_ids))
        self.assertEqual(manual["stats"]["selected_wells"], len(selected_ids))
        weights = [
            feature["properties"]["weight"]
            for feature in manual["thiessen_polygons"]["features"]
        ]
        self.assertAlmostEqual(sum(weights), 1.0, places=4)

    def test_manual_well_selection_requires_a_well(self) -> None:
        group_id = next(iter(self.service.groups))
        with self.assertRaisesRegex(ValueError, "حداقل یک چاه"):
            self.service.dashboard(
                group_id,
                manual_selection=True,
                selected_well_ids=[],
            )

    def test_each_selected_water_year_adds_twelve_months(self) -> None:
        selected_years = 3
        expected_months = selected_years * MONTHS_PER_YEAR
        group_id, minimum, maximum = self.group_with_span(expected_months)
        start_index = minimum
        end_index = start_index + expected_months - 1
        start_year, start_month = self.year_month(start_index)
        end_year, end_month = self.year_month(end_index)
        payload = self.service.dashboard(
            group_id,
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
        )
        self.assertEqual(
            len(payload["hydrographs"]["arithmetic"]),
            expected_months,
        )
        self.assertEqual(
            payload["stats"]["first_month"],
            f"{start_year}-{start_month:02d}",
        )
        self.assertEqual(
            payload["stats"]["last_month"],
            f"{end_year}-{end_month:02d}",
        )

    def test_annual_decline_uses_mehr_to_next_mehr(self) -> None:
        payload = next(
            payload
            for group_id in self.service.groups
            for payload in [self.service.dashboard(group_id)]
            if any(
                row["arithmetic"]["decline"] is not None
                for row in payload["annual_decline"]
            )
        )
        annual_row = next(
            row
            for row in payload["annual_decline"]
            if row["arithmetic"]["decline"] is not None
        )
        row = annual_row["arithmetic"]
        self.assertAlmostEqual(
            row["decline"],
            row["start_level"] - row["end_level"],
            places=2,
        )
        self.assertTrue(annual_row["start_month"].endswith(
            f"-{WATER_YEAR_START_MONTH:02d}"
        ))
        self.assertEqual(
            len(payload["wells"][0]["annual_decline"]),
            len(payload["annual_decline"]),
        )

    def test_annual_cumulative_decline_is_running_sum(self) -> None:
        base_year = 1
        rows = self.service._annual_decline_rows(
            {
                base_year * MONTHS_PER_YEAR + WATER_YEAR_START_MONTH: 100.0,
                (base_year + 1) * MONTHS_PER_YEAR
                + WATER_YEAR_START_MONTH: 98.5,
                (base_year + 2) * MONTHS_PER_YEAR
                + WATER_YEAR_START_MONTH: 97.0,
            },
            base_year,
            base_year + 1,
        )
        self.assertEqual(rows[0]["decline"], 1.5)
        self.assertEqual(rows[1]["decline"], 1.5)
        self.assertEqual(rows[1]["cumulative_decline"], 3.0)

    def test_exact_year_and_month_period(self) -> None:
        expected_months = 19
        group_id, minimum, maximum = self.group_with_span(expected_months)
        start_index = minimum
        end_index = start_index + expected_months - 1
        start_year, start_month = self.year_month(start_index)
        end_year, end_month = self.year_month(end_index)
        payload = self.service.dashboard(
            group_id,
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
        )
        self.assertEqual(
            payload["stats"]["first_month"],
            f"{start_year}-{start_month:02d}",
        )
        self.assertEqual(
            payload["stats"]["last_month"],
            f"{end_year}-{end_month:02d}",
        )
        self.assertEqual(
            len(payload["hydrographs"]["arithmetic"]),
            expected_months,
        )

    def test_trend_reports_annualized_decline(self) -> None:
        trend = self.service._trend(
            {
                100: 10.0,
                101: 9.0,
                102: 8.0,
            },
            [(100, "1-01"), (101, "1-02"), (102, "1-03")],
        )
        self.assertAlmostEqual(trend["slope_per_month"], -1.0, places=4)
        self.assertAlmostEqual(
            trend["decline_per_year"],
            float(MONTHS_PER_YEAR),
            places=3,
        )
        self.assertEqual(trend["direction"], "decline")

    def test_annual_decline_falls_back_to_shahrivar(self) -> None:
        base_year = 1
        rows = self.service._annual_decline_rows(
            {
                base_year * MONTHS_PER_YEAR + WATER_YEAR_START_MONTH: 100.0,
                (base_year + 1) * MONTHS_PER_YEAR
                + WATER_YEAR_END_MONTH: 98.0,
            },
            base_year,
            base_year,
        )
        self.assertEqual(
            rows[0]["end_month"],
            f"{base_year + 1}-{WATER_YEAR_END_MONTH:02d}",
        )
        self.assertEqual(rows[0]["decline"], 2.0)

    def test_final_incomplete_water_year_uses_latest_available_month(self) -> None:
        base_year = 1
        latest_month = 10
        rows = self.service._annual_decline_rows(
            {
                base_year * MONTHS_PER_YEAR + WATER_YEAR_START_MONTH: 100.0,
                base_year * MONTHS_PER_YEAR + latest_month: 98.5,
            },
            base_year,
            base_year,
        )

        self.assertEqual(rows[0]["end_month"], f"{base_year}-{latest_month:02d}")
        self.assertEqual(rows[0]["end_level"], 98.5)
        self.assertEqual(rows[0]["decline"], 1.5)

    def test_final_annual_decline_matches_selected_chart_period(self) -> None:
        payload = next(
            payload
            for group_id in self.service.groups
            for payload in [self.service.dashboard(group_id)]
            if any(
                row["arithmetic"]["decline"] is not None
                and row["thiessen"]["decline"] is not None
                for row in payload["annual_decline"]
            )
        )
        final_row = next(
            row
            for row in reversed(payload["annual_decline"])
            if row["arithmetic"]["decline"] is not None
            and row["thiessen"]["decline"] is not None
        )
        arithmetic = dict(payload["hydrographs"]["arithmetic"])
        thiessen = dict(payload["hydrographs"]["thiessen"])
        start_month = final_row["start_month"]
        arithmetic_end = final_row["arithmetic_end_month"]
        thiessen_end = final_row["thiessen_end_month"]

        self.assertEqual(
            final_row["arithmetic"]["end_level"],
            arithmetic[arithmetic_end],
        )
        self.assertEqual(
            final_row["thiessen"]["end_level"],
            thiessen[thiessen_end],
        )
        self.assertAlmostEqual(
            final_row["arithmetic"]["decline"],
            arithmetic[start_month] - arithmetic[arithmetic_end],
            places=2,
        )
        self.assertAlmostEqual(
            final_row["thiessen"]["decline"],
            thiessen[start_month] - thiessen[thiessen_end],
            places=2,
        )

    def test_water_level_is_elevation_minus_depth(self) -> None:
        first_measurement = self.service.measurements.iloc[0]
        location = (
            self.service.locations.drop_duplicates("_join_key")
            .set_index("_join_key")
            .loc[first_measurement["_join_key"]]
        )
        expected = float(location["LEVEL_MSL"]) - float(first_measurement["WATER_TABLE"])
        actual = self.service.monthly[
            (self.service.monthly["_join_key"] == first_measurement["_join_key"])
            & (self.service.monthly["_month"] == first_measurement["_month"])
        ].iloc[0]["level"]
        self.assertAlmostEqual(float(actual), expected, places=6)


if __name__ == "__main__":
    unittest.main()
