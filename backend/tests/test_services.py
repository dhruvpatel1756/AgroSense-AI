import os
import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from app.ml.feature_engineering import add_vegetation_indices
from app.ml import crop_training
from app.gee import service as gee_service
from app.main import AnalyzeRequest, analyze, map_layer, study_areas
from app.services.advisory import build_advisory
from app.services.data_service import get_observations, mode


class DemoModeTestCase(unittest.TestCase):
    def setUp(self):
        self.demo_mode = patch.dict(os.environ, {"DATA_MODE": "DEMO"})
        self.demo_mode.start()
        self.addCleanup(self.demo_mode.stop)


class DemoDataTests(DemoModeTestCase):
    def test_real_data_is_the_default_mode(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mode(), "REAL")

    def test_demo_observations_are_labeled_and_date_filterable(self):
        observations = get_observations(date(2026, 9, 1), date(2026, 10, 2))
        self.assertEqual(len(observations), 5)
        self.assertTrue(all(row["data_mode"] == "DEMO" for row in observations))
        self.assertTrue(all("not a real observation" in row["source"] for row in observations))

    def test_missing_date_is_not_filled_with_sample_data(self):
        observations = get_observations(date(2025, 1, 1), date(2025, 1, 2))
        self.assertEqual(observations, [])

    def test_real_mode_without_earth_engine_configuration_fails_explicitly(self):
        with patch.dict(os.environ, {"DATA_MODE": "REAL", "GOOGLE_EARTH_ENGINE_PROJECT": ""}):
            with self.assertRaisesRegex(RuntimeError, "Earth Engine is not configured"):
                get_observations(date(2026, 10, 1), date(2026, 10, 2))


class LatestSmapCacheTests(unittest.TestCase):
    def test_latest_observation_cache_expires_after_fifteen_minutes(self):
        class FakeClock:
            current = 0.0

            def __call__(self):
                return self.current

        clock = FakeClock()
        first = {"date": "2026-10-01", "soil_moisture": 0.2}
        refreshed = {"date": "2026-10-02", "soil_moisture": 0.21}
        with (
            patch.object(gee_service, "_latest_smap_cache", None),
            patch.object(
                gee_service,
                "_fetch_latest_smap_observation",
                side_effect=[first, refreshed],
            ) as fetch,
            patch.object(gee_service, "monotonic", clock),
        ):
            result = gee_service.get_latest_smap_observation()
            result["soil_moisture"] = 0.99
            self.assertEqual(gee_service.get_latest_smap_observation(), first)
            fetch.assert_called_once()

            clock.current += gee_service.LATEST_SMAP_CACHE_TTL_SECONDS
            self.assertEqual(gee_service.get_latest_smap_observation(), refreshed)
            self.assertEqual(fetch.call_count, 2)


class AdvisoryTests(unittest.TestCase):
    def test_advisory_with_missing_inputs_requires_field_verification(self):
        result = build_advisory({"soil_moisture": None, "rainfall_mm": 2.0})
        self.assertEqual(result["status"], "Field verification recommended")
        self.assertIsNone(result["confidence"])

    def test_thresholds_are_configurable_and_ordered(self):
        row = {"soil_moisture": 0.19, "rainfall_mm": 0, "data_mode": "DEMO"}
        with patch.dict(os.environ, {
            "IRRIGATION_STRESS_THRESHOLD": "0.10",
            "IRRIGATION_WATCH_THRESHOLD": "0.20",
        }):
            result = build_advisory(row)
        self.assertEqual(result["thresholds"]["stress_m3_m3"], 0.10)
        self.assertEqual(result["thresholds"]["watch_m3_m3"], 0.20)

    def test_invalid_threshold_configuration_fails_explicitly(self):
        with patch.dict(os.environ, {
            "IRRIGATION_STRESS_THRESHOLD": "0.30",
            "IRRIGATION_WATCH_THRESHOLD": "0.20",
        }):
            with self.assertRaises(RuntimeError):
                build_advisory({"soil_moisture": 0.25, "rainfall_mm": 0})


class FeatureEngineeringTests(unittest.TestCase):
    def test_sentinel_reflectance_indices_are_derived(self):
        frame = pd.DataFrame({
            "B2": [1000], "B3": [2000], "B4": [2000],
            "B8": [6000], "B11": [3000],
        })
        result = add_vegetation_indices(frame)
        self.assertAlmostEqual(result.loc[0, "ndvi"], 0.5)
        self.assertAlmostEqual(result.loc[0, "ndmi"], 1 / 3)
        self.assertAlmostEqual(result.loc[0, "ndwi"], -0.5)

    def test_missing_reflectance_bands_are_rejected(self):
        with self.assertRaises(ValueError):
            add_vegetation_indices(pd.DataFrame({"B4": [1]}))


class CropTrainingTests(unittest.TestCase):
    @staticmethod
    def polygon(crop_type: str) -> dict:
        return {
            "type": "Feature",
            "properties": {"crop_type": crop_type},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[72.3, 23.5], [72.31, 23.5], [72.31, 23.51], [72.3, 23.5]]],
            },
        }

    def test_crop_label_geojson_requires_multiple_classes_and_three_polygons_each(self):
        payload = {
            "type": "FeatureCollection",
            "features": [self.polygon("Cotton")] * 3 + [self.polygon("Wheat")] * 3,
        }
        labels, classes = crop_training.validate_crop_labels(payload)
        self.assertEqual(len(labels), 6)
        self.assertEqual(classes, ["Cotton", "Wheat"])

        with self.assertRaisesRegex(ValueError, "At least two"):
            crop_training.validate_crop_labels({
                "type": "FeatureCollection",
                "features": [self.polygon("Cotton")] * 3,
            })
        with self.assertRaisesRegex(ValueError, "at least 3 labeled polygons"):
            crop_training.validate_crop_labels({
                "type": "FeatureCollection",
                "features": [self.polygon("Cotton")] * 2 + [self.polygon("Wheat")] * 3,
            })

    def test_crop_labels_reject_non_polygon_geometry_and_invalid_coordinates(self):
        point = self.polygon("Cotton")
        point["geometry"] = {"type": "Point", "coordinates": [72.3, 23.5]}
        with self.assertRaisesRegex(ValueError, "Polygon or MultiPolygon"):
            crop_training.validate_crop_labels({
                "type": "FeatureCollection",
                "features": [point] * 3 + [self.polygon("Wheat")] * 3,
            })

        invalid = self.polygon("Cotton")
        invalid["geometry"]["coordinates"] = [[[200, 23.5], [72.31, 23.5], [72.31, 23.51], [200, 23.5]]]
        with self.assertRaisesRegex(ValueError, "invalid WGS84"):
            crop_training.validate_crop_labels({
                "type": "FeatureCollection",
                "features": [invalid] * 3 + [self.polygon("Wheat")] * 3,
            })

    def test_crop_classifier_status_does_not_claim_untrained_classes(self):
        with patch.object(crop_training, "_trained_model", None):
            result = crop_training.crop_model_status()
        self.assertFalse(result["model_available"])
        self.assertTrue(result["dataset_available"])
        self.assertEqual(result["dataset_rows"], 97)
        self.assertEqual(result["classes"], [])
        self.assertIn("datasets are ready", result["message"])

    def test_crop_training_rejects_short_windows_before_satellite_access(self):
        labels = {
            "type": "FeatureCollection",
            "features": [self.polygon("Cotton")] * 3 + [self.polygon("Wheat")] * 3,
        }
        with patch.object(crop_training, "_earth_engine") as earth_engine:
            with self.assertRaisesRegex(ValueError, "at least 30 days"):
                crop_training.train_crop_classifier(labels, date(2026, 1, 1), date(2026, 1, 20))
        earth_engine.assert_not_called()

    def test_bundled_crop_feature_datasets_load_and_evaluate(self):
        dataset = crop_training.load_bundled_crop_dataset()
        frame = dataset["frame"]
        self.assertEqual(len(frame), 97)
        self.assertEqual(dataset["classes"], ["Fennel", "Cotton"])
        self.assertEqual(frame["crop_type"].value_counts().to_dict(), {"Cotton": 50, "Fennel": 47})
        self.assertTrue(all(band in frame.columns for band in crop_training.CROP_FEATURE_BANDS))

        validation = crop_training._evaluate_crop_dataset(frame, dataset["classes"])
        self.assertEqual(sum(sum(row) for row in validation["confusion_matrix"]), len(frame))
        self.assertEqual(validation["method"], "5-fold stratified cross-validation (random record splits)")
        self.assertAlmostEqual(validation["baseline_accuracy"], 50 / 97)
        self.assertLessEqual(validation["accuracy"], validation["baseline_accuracy"])


class ApiBehaviorTests(DemoModeTestCase):
    def test_study_area_includes_attributed_district_boundary(self):
        result = study_areas()
        self.assertEqual(result["data_mode"], "DEMO")
        area = result["study_areas"][0]
        self.assertTrue(area["boundary_available"])
        self.assertEqual(area["center"], [23.59, 72.37])
        self.assertEqual(area["boundary"]["type"], "Feature")
        self.assertIn("Census 2011", area["boundary_source"])

    def test_insight_reports_a_dated_change_from_available_rows(self):
        result = analyze(AnalyzeRequest(
            question="How has soil moisture changed?",
            start_date=date(2026, 9, 11),
            end_date=date(2026, 10, 2),
        ))
        self.assertIn("-0.010", result.answer)
        self.assertIn("2026-09-11", result.answer)

    def test_insight_does_not_fill_an_unobserved_date_range(self):
        result = analyze(AnalyzeRequest(
            question="How has soil moisture changed?",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
        ))
        self.assertIn("don't have sufficient", result.answer)
        self.assertEqual(result.evidence, [])

    def test_demo_map_never_returns_a_synthetic_raster(self):
        result = map_layer("ndvi", date(2026, 10, 2))
        self.assertFalse(result["available"])
        self.assertEqual(result["data_mode"], "DEMO")

    def test_crop_map_does_not_claim_classification_without_a_model(self):
        with patch.dict(os.environ, {"DATA_MODE": "REAL", "GOOGLE_EARTH_ENGINE_PROJECT": ""}):
            result = map_layer("crop_type", date(2026, 10, 2))
        self.assertFalse(result["available"])
        self.assertFalse(result["model_available"])
        self.assertIn("datasets are ready", result["message"])


if __name__ == "__main__":
    unittest.main()
