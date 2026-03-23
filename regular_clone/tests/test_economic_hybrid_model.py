import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "economics"))
import cea_economic_analysis as econ


class EconomicHybridModelTests(unittest.TestCase):
    def test_energy_baseline_is_700_kwh_m2_cycle(self) -> None:
        c = econ.case(80.0, 4.0, "hybrid", "base")
        self.assertAlmostEqual(c["e_m2_cycle"], 700.0, places=6)
        self.assertAlmostEqual(c["e_total_annual"], c["e_total_cycle"] * c["n_cycles"], places=6)

    def test_hybrid_energy_split_consistency(self) -> None:
        c = econ.case(80.0, 4.0, "hybrid", "base")
        self.assertAlmostEqual(c["e_total_annual"], c["e_pv_self_annual"] + c["e_grid_import_annual"], places=6)
        self.assertLessEqual(c["e_pv_self_annual"], c["e_total_annual"] + 1e-9)
        self.assertGreaterEqual(c["e_grid_import_annual"], 0.0)
        self.assertGreaterEqual(c["e_curtail_annual"], 0.0)

    def test_capex_includes_power_hybrid_block(self) -> None:
        c = econ.case(80.0, 4.0, "hybrid", "base")
        self.assertGreater(c["c_power_hybrid"], 0.0)
        expected_install = econ.HYBRID_K["cost_install_power_pct"] * (c["c_pv"] + c["c_battery"] + c["c_inverter"] + c["c_switchgear"])
        self.assertAlmostEqual(c["c_install_power"], expected_install, places=6)
        self.assertAlmostEqual(c["capex_total"], c["capex_subtotal"] + c["c_contingency"], places=6)

    def test_opex_includes_replacement_annual(self) -> None:
        c = econ.case(80.0, 4.0, "hybrid", "base")
        expected = (
            c["opex_energy"]
            + c["opex_water"]
            + c["opex_nutrients"]
            + c["opex_labor"]
            + c["opex_maintenance"]
            + c["opex_ro_membranes"]
            + c["opex_replacement_annual"]
        )
        self.assertAlmostEqual(c["opex_total_annual"], expected, places=6)

    def test_c_auto_is_bom_based(self) -> None:
        c = econ.case(80.0, 4.0, "hybrid", "base")
        self.assertAlmostEqual(c["c_auto"], c["c_auto_sensors"] + c["c_control_core"] + c["c_actuation_interfaces"], places=6)
        self.assertAlmostEqual(c["c_auto_sensors"], 6205.0, places=6)

    def test_case_exposes_investor_kpis(self) -> None:
        c = econ.case(80.0, 4.0, "hybrid", "base")
        self.assertIn("annual_revenue_eur", c)
        self.assertIn("ebitda_annual_eur", c)
        self.assertIn("roi_annual_pct", c)
        self.assertIn("simple_payback_years", c)
        self.assertIn("break_even_yield_kg_year", c)
        self.assertGreater(float(c["annual_revenue_eur"]), 0.0)
        self.assertGreater(float(c["break_even_yield_kg_year"]), 0.0)

    def test_project_case_is_aligned_with_target_and_returns_core_kpis(self) -> None:
        c = econ.project_case(
            target_annual_kg=80.0,
            price_eur_g=4.0,
            mix_indica=0.5,
            mix_sativa=0.5,
            target_yield_kg_m2_cycle=0.35,
            energy_cap_kwh_m2_cycle=700.0,
        )
        self.assertAlmostEqual(float(c["target_annual_kg"]), 80.0, places=9)
        self.assertTrue(bool(c["plan_checks"]["annual_yield_within_cap"]))
        self.assertIn("annual_revenue_eur", c)
        self.assertIn("ebitda_annual_eur", c)
        self.assertIn("roi_annual_pct", c)
        self.assertIn("simple_payback_years", c)
        self.assertGreater(float(c["annual_revenue_eur"]), 0.0)


if __name__ == "__main__":
    unittest.main()
