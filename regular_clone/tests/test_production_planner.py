import unittest

from core.production_planner import PlannerInput, build_clone_logistics_plan


class ProductionPlannerTests(unittest.TestCase):
    def test_default_plan_matches_target_constraints(self) -> None:
        plan = build_clone_logistics_plan(PlannerInput())
        area = plan["area_plan_m2"]["capacity_with_margin"]
        weekly = plan["weekly_clone_plan"]["detached_cuttings_per_week"]

        self.assertAlmostEqual(float(area["flower"]), 84.54, places=2)
        self.assertAlmostEqual(float(area["propagation"]), 14.95, places=2)
        self.assertAlmostEqual(float(area["vegetative"]), 31.72, places=2)
        self.assertAlmostEqual(float(area["transition"]), 8.72, places=2)
        self.assertAlmostEqual(float(weekly["indica_dominant"]), 10.342599, places=6)
        self.assertAlmostEqual(float(weekly["sativa_dominant"]), 5.171299, places=6)
        self.assertAlmostEqual(float(weekly["total"]), 15.513898, places=6)
        self.assertAlmostEqual(
            float(plan["weekly_clone_plan"]["projected_annual_yield_kg_from_schedule"]),
            float(plan["annual_targets"]["total_kg"]) + 1e-9,
            places=6,
        )

    def test_scheduler_checks_are_respected(self) -> None:
        plan = build_clone_logistics_plan(PlannerInput())
        checks = plan["checks"]
        self.assertTrue(bool(checks["no_dedicated_mother_phase"]))
        self.assertTrue(bool(checks["max_cuttings_per_plant_enforced"]))
        self.assertTrue(bool(checks["weekly_cuttings_within_capacity"]))
        self.assertTrue(bool(checks["saturation_below_threshold"]))
        self.assertTrue(bool(checks["annual_yield_within_cap"]))
        self.assertTrue(bool(checks["annual_yield_exact_match"]))
        self.assertTrue(bool(checks["annual_yield_equals_target"]))


if __name__ == "__main__":
    unittest.main()
