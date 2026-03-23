from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Tuple

import numpy as np

from core.model import (
    QUALITY_STAGE_WEIGHT,
    VPD_TARGETS,
    YIELD_STAGE_WEIGHT,
    SensorState,
    StageSetpoint,
    _clamp,
    _dli_mol,
    _gaussian_response,
    _logistic_response,
    _normalize_spectrum,
    _vpd_kpa,
)


_HARD_LIMITS: Dict[str, Tuple[float, float]] = {
    "ppfd": (180.0, 1800.0),
    "photoperiod_h": (10.0, 18.0),
    "t_air_c": (20.0, 31.0),
    "rh_pct": (40.0, 85.0),
    "co2_ppm": (380.0, 1200.0),
    "t_solution_c": (16.0, 22.5),
    "do_mg_l": (6.6, 11.5),
    "ec_ms_cm": (1.0, 3.2),
    "ph": (5.5, 6.4),
    "n_mg_l": (60.0, 280.0),
    "p_mg_l": (10.0, 80.0),
    "k_mg_l": (50.0, 320.0),
    "uvb_frac": (0.0, 0.30),
    "airflow_m_s": (0.15, 1.6),
}

_RATE_LIMITS: Dict[str, float] = {
    "ppfd": 160.0,
    "t_air_c": 1.0,
    "rh_pct": 6.0,
    "co2_ppm": 180.0,
    "t_solution_c": 0.6,
    "do_mg_l": 0.35,
    "ec_ms_cm": 0.25,
    "ph": 0.15,
}

_DELTA_OPTIONS: Dict[str, Tuple[float, ...]] = {
    "ppfd": (-120.0, -60.0, 0.0, 60.0, 120.0),
    "t_air_c": (-0.8, -0.4, 0.0, 0.4, 0.8),
    "rh_pct": (-4.0, -2.0, 0.0, 2.0, 4.0),
    "co2_ppm": (-120.0, -60.0, 0.0, 60.0, 120.0),
    "t_solution_c": (-0.4, -0.2, 0.0, 0.2, 0.4),
    "do_mg_l": (-0.2, -0.1, 0.0, 0.1, 0.2),
    "ec_ms_cm": (-0.2, -0.1, 0.0, 0.1, 0.2),
    "ph": (-0.1, -0.05, 0.0, 0.05, 0.1),
}

_MODE_BASE = {
    "max_yield": "max_yield",
    "max_quality": "max_quality",
    "max_yield_energy": "max_yield",
    "max_quality_energy": "max_quality",
}


def enforce_setpoint_limits(candidate: StageSetpoint, sensor: SensorState) -> StageSetpoint:
    c = replace(candidate)
    for key, (lo, hi) in _HARD_LIMITS.items():
        setattr(c, key, _clamp(float(getattr(c, key)), lo, hi))

    for key, delta in _RATE_LIMITS.items():
        current = float(getattr(sensor, key))
        lo = current - delta
        hi = current + delta
        setattr(c, key, _clamp(float(getattr(c, key)), lo, hi))
        hard_lo, hard_hi = _HARD_LIMITS[key]
        setattr(c, key, _clamp(float(getattr(c, key)), hard_lo, hard_hi))

    blue, red, fr = _normalize_spectrum(c.blue_frac, c.red_frac, c.far_red_frac)
    c.blue_frac = blue
    c.red_frac = red
    c.far_red_frac = fr
    c.uvb_frac = _clamp(c.uvb_frac, _HARD_LIMITS["uvb_frac"][0], _HARD_LIMITS["uvb_frac"][1])
    return c


@dataclass
class MPCConfig:
    horizon_steps: int = 6
    candidate_samples: int = 96
    random_seed: int = 2026
    vpd_soft_margin: float = 0.15


class MPCSupervisor:
    def __init__(self, mode: str, config: MPCConfig | None = None):
        if mode not in _MODE_BASE:
            raise ValueError(
                "mode must be one of: max_yield, max_quality, max_yield_energy, max_quality_energy"
            )
        self.mode = _MODE_BASE[mode]
        self.mode_requested = mode
        self.config = config or MPCConfig()
        self.rng = np.random.default_rng(self.config.random_seed)

    def optimize(
        self,
        stage: str,
        baseline: StageSetpoint,
        heuristic: StageSetpoint,
        sensor: SensorState,
    ) -> Tuple[StageSetpoint, Dict[str, float | int | str | bool]]:
        candidates = [self._enforce_limits(heuristic, sensor)]
        for _ in range(max(self.config.candidate_samples - 1, 0)):
            candidates.append(self._sample_candidate(heuristic=heuristic, sensor=sensor))

        best = candidates[0]
        best_score = -1e18
        best_violation = 1e18
        feasible_count = 0

        for candidate in candidates:
            score, violation = self._rollout_score(
                stage=stage,
                baseline=baseline,
                candidate=candidate,
                sensor=sensor,
            )
            if violation <= 1e-9:
                feasible_count += 1
            if (violation < best_violation - 1e-9) or (abs(violation - best_violation) <= 1e-9 and score > best_score):
                best = candidate
                best_score = score
                best_violation = violation

        diagnostics: Dict[str, float | int | str | bool] = {
            "enabled": True,
            "horizon_steps": int(self.config.horizon_steps),
            "candidate_samples": int(len(candidates)),
            "feasible_candidates": int(feasible_count),
            "selected_score": float(best_score),
            "selected_violation": float(best_violation),
            "selected_source": "mpc" if best_violation <= 1e-9 else "mpc_feasibility_relaxation",
        }
        return best, diagnostics

    def _sample_candidate(self, heuristic: StageSetpoint, sensor: SensorState) -> StageSetpoint:
        c = replace(heuristic)
        for key, options in _DELTA_OPTIONS.items():
            delta = float(self.rng.choice(np.array(options, dtype=float)))
            base_value = float(getattr(c, key))
            setattr(c, key, base_value + delta)
        return self._enforce_limits(c, sensor)

    def _enforce_limits(self, candidate: StageSetpoint, sensor: SensorState) -> StageSetpoint:
        return enforce_setpoint_limits(candidate=candidate, sensor=sensor)

    def _rollout_score(
        self,
        stage: str,
        baseline: StageSetpoint,
        candidate: StageSetpoint,
        sensor: SensorState,
    ) -> Tuple[float, float]:
        low_vpd, high_vpd = VPD_TARGETS[stage]
        vpd_opt = 0.5 * (low_vpd + high_vpd)
        t_opt = 26.0 if stage in {"vegetative", "transition"} else 25.0

        t_air = sensor.t_air_c
        rh = sensor.rh_pct
        co2 = sensor.co2_ppm
        ppfd = sensor.ppfd
        t_sol = sensor.t_solution_c
        do = sensor.do_mg_l
        ec = sensor.ec_ms_cm
        ph = sensor.ph

        yield_proxy = 0.0
        quality_proxy = 0.0
        tracking_cost = 0.0
        disease_proxy = 0.0
        feasibility_violation = 0.0

        for _ in range(self.config.horizon_steps):
            t_air = _clamp(t_air + 0.50 * (candidate.t_air_c - t_air), 18.0, 33.0)
            rh = _clamp(rh + 0.52 * (candidate.rh_pct - rh), 35.0, 90.0)
            co2 = _clamp(co2 + 0.45 * (candidate.co2_ppm - co2), 380.0, 1300.0)
            ppfd = _clamp(ppfd + 0.50 * (candidate.ppfd - ppfd), 120.0, 1900.0)
            t_sol = _clamp(t_sol + 0.40 * (candidate.t_solution_c - t_sol), 15.0, 25.0)
            do = _clamp(do + 0.42 * (candidate.do_mg_l - do), 5.5, 11.5)
            ec = _clamp(ec + 0.36 * (candidate.ec_ms_cm - ec), 0.8, 3.6)
            ph = _clamp(ph + 0.34 * (candidate.ph - ph), 5.2, 6.8)

            vpd = _vpd_kpa(t_air, rh)
            dli = _dli_mol(ppfd, candidate.photoperiod_h)

            if vpd < low_vpd - self.config.vpd_soft_margin:
                feasibility_violation += (low_vpd - self.config.vpd_soft_margin - vpd)
            if vpd > high_vpd + self.config.vpd_soft_margin:
                feasibility_violation += (vpd - high_vpd - self.config.vpd_soft_margin)
            if ph < 5.5:
                feasibility_violation += (5.5 - ph)
            if ph > 6.4:
                feasibility_violation += (ph - 6.4)
            if ec < 1.0:
                feasibility_violation += (1.0 - ec)
            if ec > 3.2:
                feasibility_violation += (ec - 3.2)
            if do < 7.0:
                feasibility_violation += (7.0 - do)

            f_temp = _gaussian_response(t_air, t_opt, 3.0)
            f_vpd = _gaussian_response(vpd, vpd_opt, 0.33)
            f_co2 = _clamp(0.65 + 0.55 * (1.0 - np.exp(-(co2 - 380.0) / 450.0)), 0.55, 1.25)
            f_light = _clamp(1.0 - np.exp(-(dli - 6.0) / 24.0), 0.0, 1.25)
            f_nutr = 0.55 * _gaussian_response(ec, candidate.ec_ms_cm, 0.45) + 0.45 * _gaussian_response(ph, 5.9, 0.22)
            f_root = _gaussian_response(t_sol, 20.0, 1.8) * _logistic_response(do, 7.1, 0.6)

            disease_proxy += (
                0.020 * max(rh - 72.0, 0.0)
                + 0.090 * max(0.82 - vpd, 0.0)
                + 0.070 * max(t_sol - 22.0, 0.0)
                + 0.095 * max(7.0 - do, 0.0)
            )

            growth = YIELD_STAGE_WEIGHT[stage] * (
                0.24 * f_light + 0.20 * f_temp + 0.20 * f_vpd + 0.16 * f_nutr + 0.10 * f_root + 0.10 * f_co2
            )
            quality = QUALITY_STAGE_WEIGHT[stage] * (
                0.55 * _gaussian_response(candidate.blue_frac, 0.23 if self.mode == "max_quality" else 0.16, 0.08)
                + 0.25 * _gaussian_response(candidate.far_red_frac, 0.04 if self.mode == "max_quality" else 0.09, 0.05)
                + 0.20 * _gaussian_response(candidate.uvb_frac, 0.08 if self.mode == "max_quality" else 0.03, 0.05)
            )

            yield_proxy += growth * dli
            quality_proxy += quality

            tracking_cost += (
                0.012 * (t_air - baseline.t_air_c) ** 2
                + 0.004 * (rh - baseline.rh_pct) ** 2
                + 0.0004 * (co2 - baseline.co2_ppm) ** 2
                + 0.00005 * (ppfd - baseline.ppfd) ** 2
                + 0.10 * (t_sol - baseline.t_solution_c) ** 2
                + 0.45 * (ec - baseline.ec_ms_cm) ** 2
                + 0.95 * (ph - baseline.ph) ** 2
            )

        if self.mode == "max_quality":
            score = 3.5 * quality_proxy + 0.20 * yield_proxy - 6.5 * disease_proxy - tracking_cost
        else:
            score = 0.32 * yield_proxy + 0.35 * quality_proxy - 5.2 * disease_proxy - tracking_cost
        score -= 1500.0 * feasibility_violation
        return float(score), float(feasibility_violation)
