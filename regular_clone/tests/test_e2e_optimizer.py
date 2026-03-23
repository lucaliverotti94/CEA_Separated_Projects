import unittest
from types import SimpleNamespace

from optimizer_literature_best import run_mode


class OptimizerE2ETests(unittest.TestCase):
    def _assert_extended_clone_metrics(self, res: dict) -> None:
        derived = res["outcome"]["derived_metrics"]
        cycle_days = float(derived["cycle_days"])
        density = float(derived["flower_density_pl_m2"])
        dry_yield_g_m2 = float(res["outcome"]["dry_yield_g_m2"])
        energy_kwh_m2 = float(res["outcome"]["energy_kwh_m2"])

        self.assertAlmostEqual(float(res["dry_yield_g_plant_est"]), float(derived["dry_yield_g_plant_cycle"]), places=9)
        self.assertAlmostEqual(float(res["clone_cycle_days"]), cycle_days, places=9)
        self.assertAlmostEqual(float(res["flower_density_pl_m2"]), density, places=9)
        self.assertAlmostEqual(float(res["energy_kwh_m2_cycle"]), energy_kwh_m2, places=9)

        self.assertAlmostEqual(float(derived["dry_yield_g_plant_cycle"]), dry_yield_g_m2 / density, places=6)
        self.assertAlmostEqual(float(derived["energy_kwh_m2_day_avg"]), energy_kwh_m2 / cycle_days, places=6)
        self.assertAlmostEqual(
            float(derived["dry_yield_kg_m2_year"]),
            (dry_yield_g_m2 / 1000.0) * (365.0 / cycle_days),
            places=6,
        )
        self.assertAlmostEqual(float(derived["energy_kwh_m2_year"]), energy_kwh_m2 * (365.0 / cycle_days), places=6)
        self.assertEqual(derived["units_version"], "v1")
        self.assertIn("projected_annual_yield_kg", derived)
        self.assertIn("yield_target_annual_kg", derived)
        self.assertIn("farm_active_area_m2_available", derived)
        self.assertIn("planned_active_area_m2_for_target", derived)
        self.assertTrue(bool(derived["yield_target_exact_match"]))
        self.assertAlmostEqual(
            float(derived["projected_annual_yield_kg"]),
            float(derived["yield_target_annual_kg"]),
            places=6,
        )
        self.assertLessEqual(
            float(derived["planned_active_area_m2_for_target"]),
            float(derived["farm_active_area_m2_available"]) + 1e-9,
        )

    def test_run_mode_max_yield_minimal_budget(self) -> None:
        args = SimpleNamespace(
            seed=2026,
            quality_y_min=900.0,
            quality_floor=62.0,
            n_init=4,
            n_iter=2,
            pool_size=120,
            yield_restarts=1,
            yield_robust_evals=2,
            quality_restarts=1,
            ensemble_evals=2,
            twin_calibration_json=None,
            genetic_profile="regular_photoperiodic",
            cultivar_family="hybrid",
            cultivar_name="",
            energy_cap_kwh_m2=700.0,
            yield_target_annual_kg=80.0,
            farm_active_area_m2=20.0,
        )
        res = run_mode(mode="max_yield", args=args)
        self.assertEqual(res["mode"], "max_yield")
        self.assertIn("profile", res)
        self.assertIn("outcome", res)
        self.assertIn("governance", res)
        self.assertGreater(float(res["outcome"]["dry_yield_g_m2"]), 0.0)
        self.assertGreaterEqual(float(res["outcome"]["quality_index"]), 62.0)
        self.assertAlmostEqual(float(res["constraints"]["quality_floor"]), 62.0, places=9)
        self._assert_extended_clone_metrics(res)

    def test_run_mode_max_quality_minimal_budget(self) -> None:
        args = SimpleNamespace(
            seed=2026,
            quality_y_min=600.0,
            quality_floor=62.0,
            n_init=6,
            n_iter=4,
            pool_size=300,
            yield_restarts=1,
            yield_robust_evals=2,
            quality_restarts=2,
            ensemble_evals=2,
            twin_calibration_json=None,
            genetic_profile="regular_photoperiodic",
            cultivar_family="hybrid",
            cultivar_name="",
            energy_cap_kwh_m2=700.0,
            yield_target_annual_kg=80.0,
            farm_active_area_m2=20.0,
        )
        res = run_mode(mode="max_quality", args=args)
        self.assertEqual(res["mode"], "max_quality")
        self.assertGreaterEqual(float(res["outcome"]["dry_yield_g_m2"]), 600.0)
        self.assertGreater(float(res["outcome"]["quality_index"]), 0.0)
        self._assert_extended_clone_metrics(res)

    def test_run_mode_max_yield_energy_minimal_budget(self) -> None:
        energy_cap = 1200.0
        args = SimpleNamespace(
            seed=2026,
            quality_y_min=500.0,
            quality_floor=62.0,
            n_init=6,
            n_iter=4,
            pool_size=300,
            yield_restarts=1,
            yield_robust_evals=2,
            quality_restarts=1,
            ensemble_evals=1,
            twin_calibration_json=None,
            genetic_profile="regular_photoperiodic",
            cultivar_family="hybrid",
            cultivar_name="",
            energy_cap_kwh_m2=energy_cap,
            yield_target_annual_kg=80.0,
            farm_active_area_m2=20.0,
        )
        res = run_mode(mode="max_yield_energy", args=args)
        self.assertEqual(res["mode"], "max_yield_energy")
        self.assertLessEqual(float(res["outcome"]["energy_kwh_m2"]), energy_cap)
        self.assertGreaterEqual(float(res["outcome"]["quality_index"]), 62.0)
        self.assertAlmostEqual(float(res["constraints"]["quality_floor"]), 62.0, places=9)
        self._assert_extended_clone_metrics(res)

    def test_run_mode_max_quality_energy_minimal_budget(self) -> None:
        energy_cap = 1200.0
        args = SimpleNamespace(
            seed=2026,
            quality_y_min=500.0,
            quality_floor=62.0,
            n_init=6,
            n_iter=4,
            pool_size=300,
            yield_restarts=1,
            yield_robust_evals=2,
            quality_restarts=2,
            ensemble_evals=1,
            twin_calibration_json=None,
            genetic_profile="regular_photoperiodic",
            cultivar_family="hybrid",
            cultivar_name="",
            energy_cap_kwh_m2=energy_cap,
            yield_target_annual_kg=80.0,
            farm_active_area_m2=20.0,
        )
        res = run_mode(mode="max_quality_energy", args=args)
        self.assertEqual(res["mode"], "max_quality_energy")
        self.assertGreaterEqual(float(res["outcome"]["dry_yield_g_m2"]), 500.0)
        self.assertLessEqual(float(res["outcome"]["energy_kwh_m2"]), energy_cap)
        self._assert_extended_clone_metrics(res)

    def test_run_mode_raises_when_annual_target_is_unfeasible_for_available_area(self) -> None:
        args = SimpleNamespace(
            seed=2026,
            quality_y_min=500.0,
            quality_floor=62.0,
            n_init=4,
            n_iter=2,
            pool_size=120,
            yield_restarts=1,
            yield_robust_evals=2,
            quality_restarts=1,
            ensemble_evals=0,
            twin_calibration_json=None,
            genetic_profile="regular_photoperiodic",
            cultivar_family="hybrid",
            cultivar_name="",
            energy_cap_kwh_m2=1200.0,
            yield_target_annual_kg=80.0,
            farm_active_area_m2=1.0,
        )
        with self.assertRaises(RuntimeError):
            run_mode(mode="max_yield", args=args)


if __name__ == "__main__":
    unittest.main()
