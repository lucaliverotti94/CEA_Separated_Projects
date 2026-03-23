import json
import unittest
from pathlib import Path

from calibrate_twin import _load_case
from core.model import FLOWER_DENSITY_BY_FAMILY, HARD_STAGE_DAYS_BY_FAMILY


class CalibrationDatasetTemplateTests(unittest.TestCase):
    def test_template_cycles_are_family_coherent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        dataset_path = root / "calibration_dataset_template.json"
        raw = json.loads(dataset_path.read_text(encoding="utf-8"))
        rows = raw.get("cycles")
        self.assertIsInstance(rows, list)
        self.assertGreaterEqual(len(rows), 2)

        for idx, row in enumerate(rows, start=1):
            case = _load_case(item=row, i=idx, dataset_dir=dataset_path.parent, default_seed=2026)
            family = case.cultivar_family
            self.assertIn(family, ("indica_dominant", "sativa_dominant", "hybrid"))

            expected_days = int(sum(HARD_STAGE_DAYS_BY_FAMILY[family].values()))
            self.assertEqual(int(sum(case.profile.stage_days.values())), expected_days)

            expected_density = float(FLOWER_DENSITY_BY_FAMILY[family])
            observed_density = float(case.context.get("plant_density_pl_m2", expected_density))
            self.assertAlmostEqual(observed_density, expected_density, places=9)

            md = case.profile.metadata
            self.assertAlmostEqual(float(md["business_plan_seed_germination_days_min"]), 10.0, places=9)
            self.assertAlmostEqual(float(md["business_plan_seed_germination_days_max"]), 14.0, places=9)
            self.assertAlmostEqual(float(md["business_plan_seed_to_cutting_days_min"]), 27.0, places=9)
            self.assertAlmostEqual(float(md["business_plan_seed_to_cutting_days_max"]), 35.0, places=9)


if __name__ == "__main__":
    unittest.main()

