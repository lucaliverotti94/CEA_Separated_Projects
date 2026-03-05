import io
import unittest
from contextlib import redirect_stdout

from core.model import SensorState, StageSetpoint
from core.mpc_supervisor import enforce_setpoint_limits
from core.realtime_io import emit_safe_fallback_tick, safe_fallback_setpoint


def _baseline_setpoint() -> StageSetpoint:
    return StageSetpoint(
        ppfd=900.0,
        photoperiod_h=12.0,
        t_air_c=28.5,
        rh_pct=52.0,
        co2_ppm=900.0,
        t_solution_c=22.4,
        do_mg_l=6.2,
        ec_ms_cm=3.1,
        ph=6.35,
        n_mg_l=180.0,
        p_mg_l=40.0,
        k_mg_l=220.0,
        blue_frac=0.2,
        red_frac=0.7,
        far_red_frac=0.08,
        uvb_frac=0.03,
        airflow_m_s=0.35,
    )


def _sensor_state() -> SensorState:
    return SensorState(
        t_air_c=25.0,
        rh_pct=62.0,
        co2_ppm=700.0,
        ppfd=800.0,
        t_solution_c=20.0,
        do_mg_l=8.0,
        ec_ms_cm=1.8,
        ph=5.9,
        dli_prev=34.0,
        transpiration_l_m2_day=2.5,
        vpd_kpa=1.1,
        disease_pressure=0.0,
        hlvd_pressure=0.0,
    )


class RealtimeSafetyTests(unittest.TestCase):
    def test_safe_fallback_setpoint_clamps_expected_fields(self) -> None:
        baseline = _baseline_setpoint()
        safe = safe_fallback_setpoint(baseline)

        self.assertLessEqual(safe.ppfd, 600.0)
        self.assertGreaterEqual(safe.t_air_c, 22.0)
        self.assertLessEqual(safe.t_air_c, 26.0)
        self.assertGreaterEqual(safe.rh_pct, 55.0)
        self.assertLessEqual(safe.rh_pct, 68.0)
        self.assertGreaterEqual(safe.do_mg_l, 7.5)
        self.assertGreaterEqual(safe.ec_ms_cm, 1.2)
        self.assertLessEqual(safe.ec_ms_cm, 2.0)
        self.assertGreaterEqual(safe.airflow_m_s, 0.45)
        self.assertEqual(safe.photoperiod_h, baseline.photoperiod_h)

    def test_emit_safe_fallback_tick_returns_payload(self) -> None:
        baseline = _baseline_setpoint()
        out = io.StringIO()
        with redirect_stdout(out):
            payload = emit_safe_fallback_tick(
                mode="max_yield",
                day_idx=3,
                stage="vegetative",
                baseline=baseline,
                reason="safe_fallback_watchdog_timeout",
                fault={"kind": "idle", "elapsed_s": 6.0},
                out_jsonl=None,
                actuator_post_url=None,
                actuator_serial_sink=None,
            )

        self.assertEqual(payload["event"], "control_tick")
        self.assertEqual(payload["actions"][0], "safe_fallback_watchdog_timeout")
        self.assertEqual(payload["actions"][1], "safe_fallback_recipe")
        self.assertIn("recommended_setpoint", payload)
        self.assertIn("fault", payload)
        self.assertGreater(len(out.getvalue().strip()), 0)

    def test_enforce_setpoint_limits_respects_hard_and_rate_limits(self) -> None:
        sensor = _sensor_state()
        candidate = StageSetpoint(
            ppfd=2200.0,
            photoperiod_h=20.0,
            t_air_c=35.0,
            rh_pct=20.0,
            co2_ppm=2000.0,
            t_solution_c=30.0,
            do_mg_l=2.0,
            ec_ms_cm=5.0,
            ph=7.2,
            n_mg_l=400.0,
            p_mg_l=120.0,
            k_mg_l=500.0,
            blue_frac=0.8,
            red_frac=0.8,
            far_red_frac=0.8,
            uvb_frac=0.8,
            airflow_m_s=2.0,
        )

        limited = enforce_setpoint_limits(candidate=candidate, sensor=sensor)

        self.assertLessEqual(abs(limited.ppfd - sensor.ppfd), 160.0 + 1e-9)
        self.assertLessEqual(abs(limited.t_air_c - sensor.t_air_c), 1.0 + 1e-9)
        self.assertLessEqual(abs(limited.rh_pct - sensor.rh_pct), 6.0 + 1e-9)
        self.assertLessEqual(abs(limited.co2_ppm - sensor.co2_ppm), 180.0 + 1e-9)
        self.assertLessEqual(abs(limited.ph - sensor.ph), 0.15 + 1e-9)
        self.assertGreaterEqual(limited.ppfd, 180.0)
        self.assertLessEqual(limited.ppfd, 1800.0)
        self.assertGreaterEqual(limited.ph, 5.5)
        self.assertLessEqual(limited.ph, 6.4)
        self.assertGreaterEqual(limited.blue_frac, 0.0)
        self.assertGreaterEqual(limited.red_frac, 0.0)
        self.assertGreaterEqual(limited.far_red_frac, 0.0)
        self.assertLessEqual(limited.blue_frac + limited.red_frac + limited.far_red_frac, 0.95 + 1e-9)


if __name__ == "__main__":
    unittest.main()
