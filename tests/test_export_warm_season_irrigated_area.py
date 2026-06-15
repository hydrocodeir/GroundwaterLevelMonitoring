import argparse
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.export_warm_season_irrigated_area import (
    CSV_FIELDS,
    latest_complete_warm_season_year,
    meets_irrigated_conditions,
    month_period,
    output_row,
    read_existing_rows,
    run_metadata,
    validate_args,
    warm_season,
    write_metadata,
    write_rows,
)


def arguments(**overrides):
    values = {
        "start_year": 1402,
        "end_year": 1403,
        "batch_size": 2,
        "scale": 30,
        "max_threshold": 0.40,
        "mean_threshold": 0.30,
        "stability_threshold": 0.35,
        "min_active_months": 2,
        "min_valid_months": 4,
        "land_cover_mask": "gfsad-irrigated",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class WarmSeasonIrrigatedAreaExportTests(unittest.TestCase):
    def test_warm_season_uses_solar_hijri_months_three_through_six(self):
        season = warm_season(1403)

        self.assertEqual(season.start, date(2024, 5, 21))
        self.assertEqual(season.end, date(2024, 9, 22))
        self.assertEqual(season.period_start, "1403-03-01")
        self.assertEqual(season.period_end_exclusive, "1403-07-01")

    def test_each_month_uses_exact_solar_hijri_boundaries(self):
        self.assertEqual(
            month_period(1403, 3),
            (date(2024, 5, 21), date(2024, 6, 21)),
        )
        self.assertEqual(
            month_period(1403, 6),
            (date(2024, 8, 22), date(2024, 9, 22)),
        )

    def test_current_incomplete_warm_season_is_excluded_by_default(self):
        self.assertEqual(
            latest_complete_warm_season_year(date(2026, 6, 15)),
            1404,
        )
        self.assertEqual(
            latest_complete_warm_season_year(date(2026, 9, 23)),
            1405,
        )

    def test_threshold_arguments_are_validated(self):
        validate_args(arguments())
        with self.assertRaisesRegex(ValueError, "min-active-months"):
            validate_args(arguments(min_active_months=5))
        with self.assertRaisesRegex(ValueError, "max-threshold"):
            validate_args(arguments(max_threshold=1.1))

    def test_all_three_irrigated_conditions_must_pass(self):
        self.assertTrue(
            meets_irrigated_conditions([0.25, 0.36, 0.41, 0.38])
        )
        self.assertFalse(
            meets_irrigated_conditions([0.39, 0.38, 0.37, 0.36])
        )
        self.assertFalse(
            meets_irrigated_conditions([0.20, 0.25, 0.41, 0.34])
        )
        self.assertFalse(
            meets_irrigated_conditions([0.30, 0.34, 0.41, 0.33])
        )
        self.assertFalse(
            meets_irrigated_conditions([0.36, 0.41, None, 0.38])
        )

    def test_output_row_calculates_area_percentages(self):
        row = output_row(
            {
                "MAHDOUDE": "test",
                "AQUIFER": "aquifer",
                "JALALI_YEAR": "1403",
                "PERIOD_START": "1403-03-01",
                "PERIOD_END_EXCLUSIVE": "1403-07-01",
                "PROBABLE_IRRIGATED_AREA_HA": 250,
                "ANALYSIS_MASK_AREA_HA": 1000,
                "VALID_OBSERVATION_AREA_HA": 900,
            }
        )

        self.assertEqual(list(row), CSV_FIELDS)
        self.assertEqual(row["PROBABLE_PERCENT_OF_ANALYSIS"], 25)
        self.assertEqual(row["VALID_PERCENT_OF_ANALYSIS"], 90)

    def test_existing_csv_requires_matching_threshold_metadata(self):
        args = arguments()
        with TemporaryDirectory() as directory:
            output = Path(directory) / "area.csv"
            write_rows(output, [])
            write_metadata(output, run_metadata(args))

            self.assertEqual(
                read_existing_rows(output, False, run_metadata(args)),
                [],
            )
            changed = arguments(max_threshold=0.45)
            with self.assertRaisesRegex(ValueError, "different thresholds"):
                read_existing_rows(output, False, run_metadata(changed))


if __name__ == "__main__":
    unittest.main()
