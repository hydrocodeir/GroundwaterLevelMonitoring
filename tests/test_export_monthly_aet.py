from datetime import date
import math
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.export_monthly_aet import (
    CSV_FIELDS,
    finite_or_blank,
    iter_jalali_months,
    read_existing_rows,
    run_metadata,
    write_metadata,
    write_rows,
)


class MonthlyAetExportTests(unittest.TestCase):
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

    def test_non_finite_values_are_written_as_blank(self):
        self.assertEqual(finite_or_blank(None), "")
        self.assertEqual(finite_or_blank(math.nan), "")
        self.assertEqual(finite_or_blank(123.4567), 123.457)

    def test_dataset_start_produces_an_incomplete_first_solar_month(self):
        first_period = iter_jalali_months(
            date(2018, 1, 1),
            date(2018, 1, 21),
        )[0]

        self.assertEqual(first_period[0], "1396-10-01")
        self.assertFalse(first_period[3])

    def test_output_columns_and_metadata_are_stable(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "aet.csv"
            write_rows(output, [])
            write_metadata(output, run_metadata())

            self.assertEqual(
                read_existing_rows(
                    output,
                    overwrite=False,
                    expected_metadata=run_metadata(),
                ),
                [],
            )
            self.assertEqual(CSV_FIELDS, ["MAHDOUDE", "AQUIFER", "DATE", "AET"])


if __name__ == "__main__":
    unittest.main()
