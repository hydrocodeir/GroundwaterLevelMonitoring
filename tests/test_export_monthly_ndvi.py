from datetime import date
import math
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.export_monthly_ndvi import (
    finite_or_blank,
    iter_jalali_months,
    read_existing_rows,
    run_metadata,
    write_metadata,
    write_rows,
)


class MonthlyNdviExportTests(unittest.TestCase):
    def test_month_boundaries_use_solar_hijri_calendar(self):
        periods = iter_jalali_months(date(2024, 3, 20), date(2024, 5, 21))

        self.assertEqual(
            periods,
            [
                (
                    "1403-01-01",
                    date(2024, 3, 20),
                    date(2024, 4, 20),
                    True,
                ),
                (
                    "1403-02-01",
                    date(2024, 4, 20),
                    date(2024, 5, 21),
                    True,
                ),
            ],
        )

    def test_partial_current_month_is_not_marked_complete(self):
        periods = iter_jalali_months(date(2026, 5, 22), date(2026, 6, 14))

        self.assertEqual(
            periods,
            [
                (
                    "1405-03-01",
                    date(2026, 5, 22),
                    date(2026, 6, 14),
                    False,
                )
            ],
        )

    def test_non_finite_values_are_written_as_blank(self):
        self.assertEqual(finite_or_blank(None), "")
        self.assertEqual(finite_or_blank(math.nan), "")
        self.assertEqual(finite_or_blank(0.12345678), 0.123457)

    def test_existing_csv_requires_matching_mask_metadata(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "ndvi.csv"
            write_rows(output, [])

            with self.assertRaisesRegex(ValueError, "no run metadata"):
                read_existing_rows(
                    output,
                    overwrite=False,
                    expected_metadata=run_metadata("worldcover"),
                )

            write_metadata(output, run_metadata("none"))
            with self.assertRaisesRegex(ValueError, "different mask settings"):
                read_existing_rows(
                    output,
                    overwrite=False,
                    expected_metadata=run_metadata("worldcover"),
                )

            write_metadata(output, run_metadata("worldcover"))
            self.assertEqual(
                read_existing_rows(
                    output,
                    overwrite=False,
                    expected_metadata=run_metadata("worldcover"),
                ),
                [],
            )


if __name__ == "__main__":
    unittest.main()
