from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Dict, List, Optional

from core.model import SensorState


HARD_RANGES: Dict[str, tuple[float, float]] = {
    "t_air_c": (10.0, 45.0),
    "rh_pct": (0.0, 100.0),
    "co2_ppm": (250.0, 5000.0),
    "ppfd": (0.0, 2500.0),
    "t_solution_c": (5.0, 35.0),
    "do_mg_l": (0.0, 20.0),
    "ec_ms_cm": (0.0, 8.0),
    "ph": (3.0, 9.0),
}

WARN_JUMP_LIMITS: Dict[str, float] = {
    "t_air_c": 2.0,
    "rh_pct": 10.0,
    "co2_ppm": 350.0,
    "ppfd": 350.0,
    "t_solution_c": 1.0,
    "do_mg_l": 0.8,
    "ec_ms_cm": 0.35,
    "ph": 0.30,
}

HARD_JUMP_LIMITS: Dict[str, float] = {
    "t_air_c": 6.0,
    "rh_pct": 30.0,
    "co2_ppm": 1000.0,
    "ppfd": 900.0,
    "t_solution_c": 3.0,
    "do_mg_l": 3.0,
    "ec_ms_cm": 1.2,
    "ph": 0.8,
}


@dataclass
class SensorQualityReport:
    hard_faults: List[str]
    warnings: List[str]
    score: float

    @property
    def is_hard_fault(self) -> bool:
        return len(self.hard_faults) > 0


def _state_value(sensor: SensorState, key: str) -> float:
    return float(getattr(sensor, key))


def evaluate_sensor_quality(sensor: SensorState, prev_sensor: Optional[SensorState]) -> SensorQualityReport:
    hard_faults: List[str] = []
    warnings: List[str] = []

    for key, (lo, hi) in HARD_RANGES.items():
        val = _state_value(sensor, key)
        if not isfinite(val):
            hard_faults.append(f"{key}:not_finite")
            continue
        if val < lo or val > hi:
            hard_faults.append(f"{key}:out_of_range[{lo},{hi}]")
            continue

        width = max(hi - lo, 1e-9)
        margin = 0.05 * width
        if (val - lo) <= margin:
            warnings.append(f"{key}:near_low_limit")
        if (hi - val) <= margin:
            warnings.append(f"{key}:near_high_limit")

    if prev_sensor is not None:
        for key, warn_delta in WARN_JUMP_LIMITS.items():
            now = _state_value(sensor, key)
            prev = _state_value(prev_sensor, key)
            delta = abs(now - prev)
            hard_delta = float(HARD_JUMP_LIMITS[key])
            if delta > hard_delta:
                hard_faults.append(f"{key}:hard_jump>{hard_delta}")
            elif delta > float(warn_delta):
                warnings.append(f"{key}:jump>{warn_delta}")

    score = 100.0
    score -= 35.0 * len(hard_faults)
    score -= 6.0 * len(warnings)
    if score < 0.0:
        score = 0.0
    return SensorQualityReport(hard_faults=hard_faults, warnings=warnings, score=float(score))

