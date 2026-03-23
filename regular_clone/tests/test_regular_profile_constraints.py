import unittest

from core.model import StrategyBuilder


def _midpoint_params(builder: StrategyBuilder) -> dict[str, float]:
    return {k: (b.lo + b.hi) / 2.0 for k, b in builder.parameter_bounds().items()}


class RegularProfileConstraintTests(unittest.TestCase):
    def test_seed_to_cutting_hard_windows_are_exported(self) -> None:
        builder = StrategyBuilder(
            genetic_profile_id="regular_photoperiodic",
            cultivar_family="indica_dominant",
        )
        profile = builder.build(p=_midpoint_params(builder), mode="max_yield")
        self.assertAlmostEqual(float(profile.metadata["business_plan_seed_germination_days_min"]), 10.0, places=9)
        self.assertAlmostEqual(float(profile.metadata["business_plan_seed_germination_days_max"]), 14.0, places=9)
        self.assertAlmostEqual(float(profile.metadata["business_plan_seed_to_cutting_days_min"]), 27.0, places=9)
        self.assertAlmostEqual(float(profile.metadata["business_plan_seed_to_cutting_days_max"]), 35.0, places=9)

    def test_indica_cycle_and_density_targets(self) -> None:
        builder = StrategyBuilder(
            genetic_profile_id="regular_photoperiodic",
            cultivar_family="indica_dominant",
        )
        profile = builder.build(p=_midpoint_params(builder), mode="max_yield")
        self.assertEqual(sum(profile.stage_days.values()), 105)
        self.assertAlmostEqual(float(profile.metadata["flower_density_pl_m2"]), 4.0, places=9)

    def test_sativa_cycle_and_cloning_method_targets(self) -> None:
        builder = StrategyBuilder(
            genetic_profile_id="regular_photoperiodic",
            cultivar_family="sativa_dominant",
        )
        profile = builder.build(p=_midpoint_params(builder), mode="max_yield")
        self.assertEqual(sum(profile.stage_days.values()), 120)
        self.assertAlmostEqual(float(profile.metadata["flower_density_pl_m2"]), 2.0, places=9)
        self.assertAlmostEqual(float(profile.metadata["business_plan_cuttings_per_plant"]), 5.0, places=9)
        self.assertTrue(bool(profile.metadata["business_plan_no_dedicated_mother_plants"]))

    def test_hybrid_cycle_and_density_targets(self) -> None:
        builder = StrategyBuilder(
            genetic_profile_id="regular_photoperiodic",
            cultivar_family="hybrid",
        )
        profile = builder.build(p=_midpoint_params(builder), mode="max_yield")
        self.assertEqual(sum(profile.stage_days.values()), 112)
        self.assertAlmostEqual(float(profile.metadata["flower_density_pl_m2"]), 3.0, places=9)


if __name__ == "__main__":
    unittest.main()
