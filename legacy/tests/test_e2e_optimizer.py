import unittest
from types import SimpleNamespace

from optimizer_literature_best import run_mode


class OptimizerE2ETests(unittest.TestCase):
    def test_run_mode_max_yield_minimal_budget(self) -> None:
        args = SimpleNamespace(
            seed=2026,
            quality_y_min=900.0,
            n_init=4,
            n_iter=2,
            pool_size=120,
            yield_restarts=1,
            yield_robust_evals=2,
            quality_restarts=1,
            ensemble_evals=2,
            twin_calibration_json=None,
            genetic_profile="feminized_photoperiodic",
            cultivar_family="hybrid",
            cultivar_name="",
            energy_cap_kwh_m2=700.0,
        )
        res = run_mode(mode="max_yield", args=args)
        self.assertEqual(res["mode"], "max_yield")
        self.assertIn("profile", res)
        self.assertIn("outcome", res)
        self.assertIn("governance", res)
        self.assertGreater(float(res["outcome"]["dry_yield_g_m2"]), 0.0)

    def test_run_mode_max_quality_minimal_budget(self) -> None:
        args = SimpleNamespace(
            seed=2026,
            quality_y_min=600.0,
            n_init=6,
            n_iter=4,
            pool_size=300,
            yield_restarts=1,
            yield_robust_evals=2,
            quality_restarts=2,
            ensemble_evals=2,
            twin_calibration_json=None,
            genetic_profile="feminized_photoperiodic",
            cultivar_family="hybrid",
            cultivar_name="",
            energy_cap_kwh_m2=700.0,
        )
        res = run_mode(mode="max_quality", args=args)
        self.assertEqual(res["mode"], "max_quality")
        self.assertGreaterEqual(float(res["outcome"]["dry_yield_g_m2"]), 600.0)
        self.assertGreater(float(res["outcome"]["quality_index"]), 0.0)

    def test_run_mode_max_yield_energy_minimal_budget(self) -> None:
        energy_cap = 1200.0
        args = SimpleNamespace(
            seed=2026,
            quality_y_min=500.0,
            n_init=6,
            n_iter=4,
            pool_size=300,
            yield_restarts=1,
            yield_robust_evals=2,
            quality_restarts=1,
            ensemble_evals=1,
            twin_calibration_json=None,
            genetic_profile="feminized_photoperiodic",
            cultivar_family="hybrid",
            cultivar_name="",
            energy_cap_kwh_m2=energy_cap,
        )
        res = run_mode(mode="max_yield_energy", args=args)
        self.assertEqual(res["mode"], "max_yield_energy")
        self.assertLessEqual(float(res["outcome"]["energy_kwh_m2"]), energy_cap)

    def test_run_mode_max_quality_energy_minimal_budget(self) -> None:
        energy_cap = 1200.0
        args = SimpleNamespace(
            seed=2026,
            quality_y_min=500.0,
            n_init=6,
            n_iter=4,
            pool_size=300,
            yield_restarts=1,
            yield_robust_evals=2,
            quality_restarts=2,
            ensemble_evals=1,
            twin_calibration_json=None,
            genetic_profile="feminized_photoperiodic",
            cultivar_family="hybrid",
            cultivar_name="",
            energy_cap_kwh_m2=energy_cap,
        )
        res = run_mode(mode="max_quality_energy", args=args)
        self.assertEqual(res["mode"], "max_quality_energy")
        self.assertGreaterEqual(float(res["outcome"]["dry_yield_g_m2"]), 500.0)
        self.assertLessEqual(float(res["outcome"]["energy_kwh_m2"]), energy_cap)


if __name__ == "__main__":
    unittest.main()
