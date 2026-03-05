import unittest

from core.production_planner import PlannerInput, build_clone_logistics_plan


class ProductionPlannerTests(unittest.TestCase):
    def test_default_plan_matches_target_constraints(self) -> None:
        plan = build_clone_logistics_plan(PlannerInput())
        area = plan["area_plan_m2"]["capacity_with_margin"]
        weekly = plan["weekly_clone_plan"]["detached_cuttings_per_week"]

        self.assertAlmostEqual(float(area["flower"]), 63.41, places=2)
        self.assertAlmostEqual(float(area["propagation"]), 11.21, places=2)
        self.assertAlmostEqual(float(area["vegetative"]), 23.79, places=2)
        self.assertAlmostEqual(float(area["transition"]), 6.54, places=2)
        self.assertEqual(int(weekly["indica_dominant"]), 8)
        self.assertEqual(int(weekly["sativa_dominant"]), 4)
        self.assertEqual(int(weekly["total"]), 12)

    def test_scheduler_checks_are_respected(self) -> None:
        plan = build_clone_logistics_plan(PlannerInput())
        checks = plan["checks"]
        self.assertTrue(bool(checks["no_dedicated_mother_phase"]))
        self.assertTrue(bool(checks["max_cuttings_per_plant_enforced"]))
        self.assertTrue(bool(checks["weekly_cuttings_within_capacity"]))
        self.assertTrue(bool(checks["saturation_below_threshold"]))


if __name__ == "__main__":
    unittest.main()
