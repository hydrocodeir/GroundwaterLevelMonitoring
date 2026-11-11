import importlib.util
from pathlib import Path
import unittest

from app.data_service import GroundwaterData


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dashboard_catalog", ROOT / "frontend/assets/js/dashboard_catalog.py")
catalog_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog_module)


class DashboardCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = catalog_module.DashboardCatalog(ROOT / "Data")
        cls.service = GroundwaterData()

    def test_setup_ids_and_observation_months_match_the_analysis_engine(self):
        monthly = {
            key: sorted(int(index) for index in group["_month_index"].unique())
            for key, group in self.service.monthly.groupby("_join_key")
        }
        for group_id in self.service.groups:
            preview = self.catalog.preview(group_id)
            locations = self.service.locations[self.service.locations["_aquifer_id"] == group_id]
            self.assertEqual([well["id"] for well in preview["wells"]], locations["_well_id"].tolist())
            for well, (_, location) in zip(preview["wells"], locations.iterrows()):
                self.assertEqual(well["available_month_indexes"], monthly.get(location["_join_key"], []))

    def test_default_dates_match_the_engine_without_computing_a_hydrograph(self):
        for group_id in self.service.groups:
            preview = self.catalog.preview(group_id)
            filters = preview["filters"]
            self.assertEqual(
                tuple(filters[key] for key in ("start_year", "start_month", "end_year", "end_month")),
                self.service._validate_period(group_id, None, None, None, None),
            )
            self.assertEqual(filters["selected_well_ids"], [])
            self.assertIsNone(filters["storage_coefficient"])
            self.assertNotIn("hydrographs", preview)
            self.assertTrue(preview["preview"])

    def test_unknown_aquifer_has_an_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "آبخوان"):
            self.catalog.preview("missing")
