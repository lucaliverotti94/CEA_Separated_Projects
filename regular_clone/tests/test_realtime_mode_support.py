import sys
import unittest
from unittest.mock import patch

from core.mpc_supervisor import MPCSupervisor
from core.model import StrategyBuilder
from core.realtime_io import (
    _extract_profile_dict,
    resolve_profile_energy_kwh_m2_cycle,
    resolve_runtime_energy_cap,
    runtime_base_mode,
)
from controller_literature_realtime import _runtime_base_mode, _validate_profile_quality_floor, parse_args


def _profile_stub() -> dict:
    return {
        "propagation": {"days": 12},
        "vegetative": {"days": 24},
        "transition": {"days": 7},
        "flower_early": {"days": 32},
        "flower_late": {"days": 30},
    }


class RealtimeModeSupportTests(unittest.TestCase):
    def test_profile_json_quality_floor_is_validated_for_max_yield(self) -> None:
        builder = StrategyBuilder()
        bounds = builder.parameter_bounds()
        params = {k: (v.lo + v.hi) / 2.0 for k, v in bounds.items()}
        profile = builder.build(p=params, mode="max_yield")

        quality = _validate_profile_quality_floor(profile=profile, control_mode="max_yield", quality_floor=62.0)
        self.assertIsNotNone(quality)
        self.assertGreaterEqual(float(quality), 62.0)

        with self.assertRaises(ValueError):
            _validate_profile_quality_floor(profile=profile, control_mode="max_yield", quality_floor=99.0)

    def test_runtime_base_mode_mapping_is_consistent(self) -> None:
        self.assertEqual(runtime_base_mode("max_yield"), "max_yield")
        self.assertEqual(runtime_base_mode("max_quality"), "max_quality")
        self.assertEqual(runtime_base_mode("max_yield_energy"), "max_yield")
        self.assertEqual(runtime_base_mode("max_quality_energy"), "max_quality")
        self.assertEqual(_runtime_base_mode("max_yield_energy"), "max_yield")
        self.assertEqual(_runtime_base_mode("max_quality_energy"), "max_quality")

    def test_extract_profile_falls_back_to_base_mode_for_energy_requests(self) -> None:
        raw = {"results": [{"mode": "max_quality", "profile": _profile_stub()}]}
        out = _extract_profile_dict(raw=raw, mode="max_quality_energy")
        self.assertIn("flower_late", out)
        self.assertEqual(int(out["flower_late"]["days"]), 30)

    def test_mpc_supervisor_accepts_energy_modes(self) -> None:
        mpc_y = MPCSupervisor(mode="max_yield_energy")
        mpc_q = MPCSupervisor(mode="max_quality_energy")
        self.assertEqual(mpc_y.mode, "max_yield")
        self.assertEqual(mpc_q.mode, "max_quality")

    def test_controller_parse_args_accepts_energy_mode_and_cap(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "controller_literature_realtime.py",
                "--mode",
                "max_yield_energy",
                "--energy-cap-kwh-m2",
                "640",
                "--quality-floor",
                "63",
                "--yield-target-annual-kg",
                "80",
                "--farm-active-area-m2",
                "120",
            ],
        ):
            args = parse_args()
        self.assertEqual(args.mode, "max_yield_energy")
        self.assertAlmostEqual(float(args.energy_cap_kwh_m2), 640.0, places=9)
        self.assertAlmostEqual(float(args.quality_floor), 63.0, places=9)
        self.assertAlmostEqual(float(args.yield_target_annual_kg), 80.0, places=9)
        self.assertAlmostEqual(float(args.farm_active_area_m2), 120.0, places=9)

    def test_runtime_energy_cap_resolution(self) -> None:
        constrained, cap = resolve_runtime_energy_cap(mode="max_quality_energy", energy_cap_kwh_m2=610.0)
        self.assertTrue(constrained)
        self.assertAlmostEqual(cap, 610.0, places=9)
        constrained_base, _ = resolve_runtime_energy_cap(mode="max_quality", energy_cap_kwh_m2=610.0)
        self.assertFalse(constrained_base)
        with self.assertRaises(ValueError):
            resolve_runtime_energy_cap(mode="max_yield_energy", energy_cap_kwh_m2=0.0)

    def test_profile_energy_extraction_from_derived_metrics(self) -> None:
        energy = resolve_profile_energy_kwh_m2_cycle({"energy_kwh_m2_cycle": 642.5})
        self.assertAlmostEqual(energy, 642.5, places=9)
        with self.assertRaises(ValueError):
            resolve_profile_energy_kwh_m2_cycle({})


if __name__ == "__main__":
    unittest.main()
