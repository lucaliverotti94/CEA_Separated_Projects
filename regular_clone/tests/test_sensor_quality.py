import unittest

from core.model import SensorState
from core.sensor_quality import evaluate_sensor_quality


def _sensor(**overrides) -> SensorState:
    base = {
        "t_air_c": 25.0,
        "rh_pct": 60.0,
        "co2_ppm": 800.0,
        "ppfd": 900.0,
        "t_solution_c": 20.0,
        "do_mg_l": 8.0,
        "ec_ms_cm": 1.8,
        "ph": 5.9,
        "dli_prev": 38.0,
        "transpiration_l_m2_day": 2.4,
        "vpd_kpa": 1.1,
        "disease_pressure": 0.0,
        "hlvd_pressure": 0.0,
    }
    base.update(overrides)
    return SensorState(**base)


class SensorQualityTests(unittest.TestCase):
    def test_hard_fault_out_of_range(self) -> None:
        report = evaluate_sensor_quality(_sensor(ph=10.0), prev_sensor=None)
        self.assertTrue(report.is_hard_fault)
        self.assertTrue(any("ph:out_of_range" in x for x in report.hard_faults))

    def test_hard_fault_large_jump(self) -> None:
        prev = _sensor(ppfd=500.0)
        now = _sensor(ppfd=1600.0)
        report = evaluate_sensor_quality(now, prev_sensor=prev)
        self.assertTrue(report.is_hard_fault)
        self.assertTrue(any("ppfd:hard_jump" in x for x in report.hard_faults))

    def test_warning_small_jump(self) -> None:
        prev = _sensor(co2_ppm=700.0)
        now = _sensor(co2_ppm=1100.0)
        report = evaluate_sensor_quality(now, prev_sensor=prev)
        self.assertFalse(report.is_hard_fault)
        self.assertTrue(any("co2_ppm:jump" in x for x in report.warnings))


if __name__ == "__main__":
    unittest.main()

