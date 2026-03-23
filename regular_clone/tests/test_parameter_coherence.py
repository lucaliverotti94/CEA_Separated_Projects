import json
import unittest
from pathlib import Path

from core import production_planner
from core.model import FLOWER_DENSITY_BY_FAMILY, HARD_STAGE_DAYS_BY_FAMILY
from core.realtime_io import DEFAULT_YIELD_CAP_ANNUAL_KG as RT_DEFAULT_YIELD_TARGET
from optimizer_literature_best import DEFAULT_YIELD_TARGET_ANNUAL_KG as OPT_DEFAULT_YIELD_TARGET


class ParameterCoherenceTests(unittest.TestCase):
    def test_indica_sativa_hard_days_are_aligned_between_model_and_planner(self) -> None:
        for family in ("indica_dominant", "sativa_dominant"):
            self.assertEqual(
                HARD_STAGE_DAYS_BY_FAMILY[family],
                production_planner.HARD_STAGE_DAYS[family],
            )

    def test_indica_sativa_hard_density_is_aligned_between_model_and_planner(self) -> None:
        for family in ("indica_dominant", "sativa_dominant"):
            self.assertAlmostEqual(
                float(FLOWER_DENSITY_BY_FAMILY[family]),
                float(production_planner.HARD_DENSITY_PL_M2[family]),
                places=9,
            )

    def test_genetic_profile_metadata_is_coherent_with_hard_cycle_constants(self) -> None:
        cfg_path = Path(__file__).resolve().parents[1] / "configs" / "genetic_profiles.json"
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        rows = {str(p["profile_id"]): p for p in raw.get("profiles", [])}
        regular = rows["regular_photoperiodic"]
        md = regular.get("metadata", {})

        self.assertAlmostEqual(float(md["seed_to_cutting_days_min"]), 27.0, places=9)
        self.assertAlmostEqual(float(md["seed_to_cutting_days_max"]), 35.0, places=9)
        self.assertAlmostEqual(
            float(md["clone_cycle_target_days_indica"]),
            float(sum(HARD_STAGE_DAYS_BY_FAMILY["indica_dominant"].values())),
            places=9,
        )
        self.assertAlmostEqual(
            float(md["clone_cycle_target_days_sativa"]),
            float(sum(HARD_STAGE_DAYS_BY_FAMILY["sativa_dominant"].values())),
            places=9,
        )

    def test_yield_target_default_is_parametric_and_consistent(self) -> None:
        self.assertAlmostEqual(float(RT_DEFAULT_YIELD_TARGET), 80.0, places=9)
        self.assertAlmostEqual(float(OPT_DEFAULT_YIELD_TARGET), 80.0, places=9)
        self.assertAlmostEqual(float(production_planner.PlannerInput().target_annual_kg), 80.0, places=9)


if __name__ == "__main__":
    unittest.main()
