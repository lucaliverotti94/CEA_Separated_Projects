from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import argparse
import json

import numpy as np
from scipy.stats import qmc
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

from core.genetics import (
    DEFAULT_GENETIC_PROFILE_ID,
    available_cultivar_families,
    available_genetic_profiles,
    cultivar_bound_overrides,
    cultivar_evidence_source_ids,
    cultivar_model_coefficients,
    default_genetic_profile_id,
    family_bound_overrides,
    family_model_coefficients,
    get_genetic_profile,
    profile_evidence_source_ids,
    resolve_cultivar,
    validate_profile_cultivar_args,
)
from core.literature import literature_sources_to_dict

STAGE_ORDER = (
    "propagation",
    "vegetative",
    "transition",
    "flower_early",
    "flower_late",
)

VPD_TARGETS = {
    "propagation": (0.40, 0.80),
    "vegetative": (0.80, 1.20),
    "transition": (1.00, 1.35),
    "flower_early": (1.10, 1.45),
    "flower_late": (1.00, 1.35),
}

YIELD_STAGE_WEIGHT = {
    "propagation": 0.06,
    "vegetative": 0.32,
    "transition": 0.78,
    "flower_early": 1.28,
    "flower_late": 1.06,
}

QUALITY_STAGE_WEIGHT = {
    "propagation": 0.00,
    "vegetative": 0.06,
    "transition": 0.20,
    "flower_early": 0.75,
    "flower_late": 1.15,
}

LAI_STAGE_DELTA = {
    "propagation": 0.015,
    "vegetative": 0.045,
    "transition": 0.026,
    "flower_early": 0.010,
    "flower_late": -0.004,
}


@dataclass
class Bounds:
    lo: float
    hi: float


@dataclass
class StageSetpoint:
    ppfd: float
    photoperiod_h: float
    t_air_c: float
    rh_pct: float
    co2_ppm: float
    t_solution_c: float
    do_mg_l: float
    ec_ms_cm: float
    ph: float
    n_mg_l: float
    p_mg_l: float
    k_mg_l: float
    blue_frac: float
    red_frac: float
    far_red_frac: float
    uvb_frac: float
    airflow_m_s: float


@dataclass
class SensorState:
    t_air_c: float
    rh_pct: float
    co2_ppm: float
    ppfd: float
    t_solution_c: float
    do_mg_l: float
    ec_ms_cm: float
    ph: float
    dli_prev: float
    transpiration_l_m2_day: float
    vpd_kpa: float
    disease_pressure: float
    hlvd_pressure: float


@dataclass
class DayLog:
    day: int
    stage: str
    dli_mol: float
    yield_gain_g_m2: float
    quality_gain_units: float
    energy_kwh_m2: float
    penalty: float
    vpd_kpa: float
    ec_ms_cm: float
    ph: float
    adjustments: List[str]


@dataclass
class CycleOutcome:
    mode: str
    dry_yield_g_m2: float
    quality_index: float
    energy_kwh_m2: float
    g_per_kwh: float
    penalty: float
    disease_pressure: float
    hlvd_pressure: float
    daily_logs: List[DayLog]


@dataclass
class TwinCalibration:
    # Daily process scalers.
    yield_gain_scale: float = 1.0
    quality_gain_scale: float = 1.0
    transpiration_scale: float = 1.0
    disease_inc_scale: float = 1.0
    hlvd_inc_scale: float = 1.0
    penalty_scale: float = 1.0
    energy_scale: float = 1.0
    # Cycle-level post scalers.
    yield_post_scale: float = 1.0
    quality_post_scale: float = 1.0
    quality_post_offset: float = 0.0


@dataclass
class StrategyProfile:
    stage_days: Dict[str, int]
    stage_setpoints: Dict[str, StageSetpoint]
    metadata: Dict[str, float | str | bool]

    def total_days(self) -> int:
        return int(sum(self.stage_days[s] for s in STAGE_ORDER))

    def stage_for_day(self, day_idx: int) -> str:
        cumsum = 0
        for stage in STAGE_ORDER:
            cumsum += self.stage_days[stage]
            if day_idx <= cumsum:
                return stage
        return STAGE_ORDER[-1]


@dataclass
class EvaluatedCandidate:
    x: np.ndarray
    params: Dict[str, float]
    profile: StrategyProfile
    outcome: CycleOutcome
    score: float


def _clamp(value: float, lo: float, hi: float) -> float:
    return float(min(max(value, lo), hi))


def _gaussian_response(value: float, optimum: float, sigma: float) -> float:
    if sigma <= 0:
        return 0.0
    return float(np.exp(-((value - optimum) ** 2) / (2.0 * sigma**2)))


def _logistic_response(value: float, center: float, slope: float) -> float:
    if slope == 0.0:
        return 0.5
    return float(1.0 / (1.0 + np.exp(-(value - center) / slope)))


def _vpd_kpa(t_air_c: float, rh_pct: float) -> float:
    es = 0.6108 * np.exp((17.27 * t_air_c) / (t_air_c + 237.3))
    ea = es * (rh_pct / 100.0)
    return float(max(es - ea, 0.0))


def _dli_mol(ppfd: float, photoperiod_h: float) -> float:
    return float(0.0036 * ppfd * photoperiod_h)


def _normalize_spectrum(blue_frac: float, red_frac: float, far_red_frac: float) -> Tuple[float, float, float]:
    blue_frac = max(0.0, blue_frac)
    red_frac = max(0.0, red_frac)
    far_red_frac = max(0.0, far_red_frac)
    total = blue_frac + red_frac + far_red_frac
    if total <= 1e-9:
        return 0.20, 0.75, 0.05
    if total > 0.95:
        scale = 0.95 / total
        blue_frac *= scale
        red_frac *= scale
        far_red_frac *= scale
    return float(blue_frac), float(red_frac), float(far_red_frac)


def _twin_calibration_bounds() -> Dict[str, Tuple[float, float]]:
    return {
        "yield_gain_scale": (0.60, 1.60),
        "quality_gain_scale": (0.60, 1.60),
        "transpiration_scale": (0.60, 1.60),
        "disease_inc_scale": (0.50, 2.00),
        "hlvd_inc_scale": (0.50, 2.00),
        "penalty_scale": (0.50, 2.50),
        "energy_scale": (0.60, 1.80),
        "yield_post_scale": (0.70, 1.30),
        "quality_post_scale": (0.70, 1.30),
        "quality_post_offset": (-20.0, 20.0),
    }


def clamp_twin_calibration(calibration: TwinCalibration) -> TwinCalibration:
    bounds = _twin_calibration_bounds()
    row = asdict(calibration)
    out: Dict[str, float] = {}
    for k, v in row.items():
        lo, hi = bounds[k]
        out[k] = float(min(max(float(v), lo), hi))
    return TwinCalibration(**out)


def twin_calibration_from_dict(data: Optional[Dict[str, float]]) -> TwinCalibration:
    if not data:
        return TwinCalibration()
    base = asdict(TwinCalibration())
    merged = {**base, **{k: float(v) for k, v in data.items() if k in base}}
    return clamp_twin_calibration(TwinCalibration(**merged))


def load_twin_calibration(path: Optional[str]) -> TwinCalibration:
    if not path:
        return TwinCalibration()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Twin calibration file not found: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "calibration" in raw and isinstance(raw["calibration"], dict):
        return twin_calibration_from_dict(raw["calibration"])
    if isinstance(raw, dict):
        return twin_calibration_from_dict(raw)
    raise ValueError(f"Invalid twin calibration JSON format: {p}")


def twin_calibration_to_dict(calibration: TwinCalibration) -> Dict[str, float]:
    return asdict(clamp_twin_calibration(calibration))


class ParameterSpace:
    def __init__(self, bounds: Dict[str, Bounds]):
        self.bounds = bounds
        self.names = list(bounds.keys())
        self._lo = np.array([self.bounds[k].lo for k in self.names], dtype=float)
        self._hi = np.array([self.bounds[k].hi for k in self.names], dtype=float)

    def sample_uniform(self, n: int, seed: int | None = None) -> np.ndarray:
        sampler = qmc.LatinHypercube(d=len(self.names), seed=seed)
        u = sampler.random(n=n)
        return self._lo + u * (self._hi - self._lo)

    def clip(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        return np.clip(x, self._lo, self._hi)

    def to_dict(self, x: np.ndarray) -> Dict[str, float]:
        return {name: float(x[idx]) for idx, name in enumerate(self.names)}

    @property
    def lo(self) -> np.ndarray:
        return self._lo

    @property
    def hi(self) -> np.ndarray:
        return self._hi


class StrategyBuilder:
    def __init__(
        self,
        genetic_profile_id: str = DEFAULT_GENETIC_PROFILE_ID,
        cultivar_family: str | None = None,
        cultivar_name: str = "",
    ):
        self.genetic_profile = get_genetic_profile(genetic_profile_id)
        resolved_family, prior = resolve_cultivar(
            profile=self.genetic_profile,
            cultivar_name=cultivar_name,
            cultivar_family=cultivar_family,
        )
        self.cultivar_family = resolved_family
        self.cultivar_prior = prior
        self.cultivar_name = prior.name if prior is not None else str(cultivar_name or "").strip()

    @staticmethod
    def base_parameter_bounds() -> Dict[str, Bounds]:
        return {
            "veg_ppfd": Bounds(320.0, 760.0),
            "flower_ppfd": Bounds(750.0, 1750.0),
            "flower_photoperiod_h": Bounds(11.8, 14.0),
            "co2_flower_ppm": Bounds(450.0, 1100.0),
            "air_temp_day_c": Bounds(23.0, 29.5),
            "rh_day_pct": Bounds(48.0, 72.0),
            "ec_veg": Bounds(1.20, 2.20),
            "ec_flower": Bounds(1.50, 3.00),
            "ph_target": Bounds(5.70, 6.20),
            "n_mg_l": Bounds(120.0, 240.0),
            "p_mg_l": Bounds(20.0, 80.0),
            "k_mg_l": Bounds(80.0, 260.0),
            "blue_flower_frac": Bounds(0.10, 0.30),
            "far_red_flower_frac": Bounds(0.02, 0.18),
            "uvb_late_frac": Bounds(0.00, 0.25),
            "veg_days": Bounds(18.0, 35.0),
            "flower_total_days": Bounds(49.0, 70.0),
            "flower_early_days": Bounds(21.0, 35.0),
        }

    def _with_genetic_bound_overrides(self, bounds: Dict[str, Bounds]) -> Dict[str, Bounds]:
        out = {k: Bounds(v.lo, v.hi) for k, v in bounds.items()}
        for name, override in self.genetic_profile.bound_overrides.items():
            if name not in out:
                continue
            lo = float(override[0])
            hi = float(override[1])
            if lo >= hi:
                raise ValueError(
                    f"Invalid bounds override for '{name}' in profile "
                    f"{self.genetic_profile.profile_id}: lo ({lo}) >= hi ({hi})"
                )
            out[name] = Bounds(lo=lo, hi=hi)
        return out

    def _with_family_bound_overrides(self, bounds: Dict[str, Bounds]) -> Dict[str, Bounds]:
        out = {k: Bounds(v.lo, v.hi) for k, v in bounds.items()}
        for name, override in family_bound_overrides(self.genetic_profile, self.cultivar_family).items():
            if name not in out:
                continue
            lo = float(override[0])
            hi = float(override[1])
            if lo >= hi:
                raise ValueError(
                    f"Invalid family bounds override for '{name}' in profile "
                    f"{self.genetic_profile.profile_id}/{self.cultivar_family}: lo ({lo}) >= hi ({hi})"
                )
            out[name] = Bounds(lo=lo, hi=hi)
        return out

    def _with_cultivar_bound_overrides(self, bounds: Dict[str, Bounds]) -> Dict[str, Bounds]:
        out = {k: Bounds(v.lo, v.hi) for k, v in bounds.items()}
        for name, override in cultivar_bound_overrides(self.cultivar_prior).items():
            if name not in out:
                continue
            lo = float(override[0])
            hi = float(override[1])
            if lo >= hi:
                raise ValueError(
                    f"Invalid cultivar bounds override for '{name}' in cultivar "
                    f"{self.cultivar_name or 'unknown'}: lo ({lo}) >= hi ({hi})"
                )
            out[name] = Bounds(lo=lo, hi=hi)
        return out

    def _family_coefficients(self) -> Dict[str, float]:
        return family_model_coefficients(self.genetic_profile, self.cultivar_family)

    def _cultivar_coefficients(self) -> Dict[str, float]:
        return cultivar_model_coefficients(self.cultivar_prior)

    def parameter_bounds(self) -> Dict[str, Bounds]:
        bounds = self._with_genetic_bound_overrides(self.base_parameter_bounds())
        bounds = self._with_family_bound_overrides(bounds)
        return self._with_cultivar_bound_overrides(bounds)

    def build(self, p: Dict[str, float], mode: str) -> StrategyProfile:
        if mode not in {"max_yield", "max_quality"}:
            raise ValueError("mode must be 'max_yield' or 'max_quality'")

        family_coeffs = self._family_coefficients()
        cultivar_coeffs = self._cultivar_coefficients()
        flower_duration_scale = _clamp(family_coeffs.get("flower_duration_scale", 1.0), 0.80, 1.30)
        dli_demand_scale = _clamp(family_coeffs.get("dli_demand_scale", 1.0), 0.85, 1.25)
        flower_duration_scale *= _clamp(cultivar_coeffs.get("flower_duration_scale", 1.0), 0.80, 1.30)
        dli_demand_scale *= _clamp(cultivar_coeffs.get("dli_demand_scale", 1.0), 0.85, 1.25)
        # Keep vegetative scaling mild to avoid unrealistic cycle inflation.
        veg_duration_scale = _clamp(1.0 + 0.35 * (flower_duration_scale - 1.0), 0.90, 1.15)

        veg_days = int(round(p["veg_days"] * veg_duration_scale))
        flower_total_days = int(round(p["flower_total_days"] * flower_duration_scale))
        flower_early_days = int(round(p["flower_early_days"] * flower_duration_scale))
        flower_early_days = int(_clamp(float(flower_early_days), 14.0, float(flower_total_days - 14)))
        flower_late_days = flower_total_days - flower_early_days

        flower_photo = p["flower_photoperiod_h"]
        blue_flower = p["blue_flower_frac"]
        far_red_flower = p["far_red_flower_frac"]
        uvb_late = p["uvb_late_frac"]

        if mode == "max_quality":
            blue_flower = max(blue_flower, 0.20)
            far_red_flower = _clamp(far_red_flower * 0.65, 0.02, 0.12)
            uvb_late = max(uvb_late, 0.05)
            flower_photo = _clamp(flower_photo, 11.9, 12.8)
        else:
            blue_flower = _clamp(blue_flower, 0.10, 0.20)
            far_red_flower = _clamp(far_red_flower + 0.02, 0.03, 0.16)
            uvb_late = _clamp(uvb_late, 0.0, 0.08)
            flower_photo = _clamp(flower_photo, 12.0, 13.8)

        stage_days = {
            "propagation": 15,
            "vegetative": veg_days,
            "transition": 7,
            "flower_early": flower_early_days,
            "flower_late": flower_late_days,
        }

        t_day = p["air_temp_day_c"]
        rh_day = p["rh_day_pct"]
        n_base = p["n_mg_l"]
        p_base = p["p_mg_l"]
        k_base = p["k_mg_l"]
        ph_target = p["ph_target"]
        flower_ppfd = _clamp(p["flower_ppfd"] * dli_demand_scale, 650.0, 1950.0)

        prop_blue, prop_red, prop_fr = _normalize_spectrum(0.26, 0.66, 0.03)
        veg_blue, veg_red, veg_fr = _normalize_spectrum(0.24, 0.69, 0.03)
        tr_blue, tr_red, tr_fr = _normalize_spectrum(0.18, 0.72, min(0.10, far_red_flower))
        flw_e_blue, flw_e_red, flw_e_fr = _normalize_spectrum(
            blue_flower - 0.02,
            0.80 - blue_flower - far_red_flower,
            far_red_flower,
        )
        flw_l_blue, flw_l_red, flw_l_fr = _normalize_spectrum(
            blue_flower + (0.03 if mode == "max_quality" else -0.02),
            0.82 - blue_flower - (far_red_flower * (0.7 if mode == "max_quality" else 1.1)),
            far_red_flower * (0.7 if mode == "max_quality" else 1.1),
        )

        setpoints = {
            "propagation": StageSetpoint(
                ppfd=_clamp(p["veg_ppfd"] * 0.55, 180.0, 450.0),
                photoperiod_h=18.0,
                t_air_c=_clamp(t_day + 1.0, 23.5, 28.0),
                rh_pct=_clamp(rh_day + 12.0, 66.0, 85.0),
                co2_ppm=500.0,
                t_solution_c=20.5,
                do_mg_l=8.6,
                ec_ms_cm=_clamp(p["ec_veg"] * 0.60, 0.8, 1.35),
                ph=ph_target,
                n_mg_l=n_base * 0.45,
                p_mg_l=p_base * 0.50,
                k_mg_l=k_base * 0.55,
                blue_frac=prop_blue,
                red_frac=prop_red,
                far_red_frac=prop_fr,
                uvb_frac=0.0,
                airflow_m_s=0.25,
            ),
            "vegetative": StageSetpoint(
                ppfd=p["veg_ppfd"],
                photoperiod_h=18.0,
                t_air_c=t_day,
                rh_pct=_clamp(rh_day + 6.0, 55.0, 78.0),
                co2_ppm=650.0,
                t_solution_c=20.0,
                do_mg_l=8.2,
                ec_ms_cm=p["ec_veg"],
                ph=ph_target,
                n_mg_l=n_base,
                p_mg_l=p_base,
                k_mg_l=k_base,
                blue_frac=veg_blue,
                red_frac=veg_red,
                far_red_frac=veg_fr,
                uvb_frac=0.0,
                airflow_m_s=0.45,
            ),
            "transition": StageSetpoint(
                ppfd=(p["veg_ppfd"] + flower_ppfd * 0.85) / 2.0,
                photoperiod_h=max(13.0, flower_photo),
                t_air_c=_clamp(t_day - 0.3, 22.5, 29.0),
                rh_pct=_clamp(rh_day + 1.0, 50.0, 72.0),
                co2_ppm=760.0,
                t_solution_c=20.0,
                do_mg_l=8.0,
                ec_ms_cm=(p["ec_veg"] + p["ec_flower"] * 0.90) / 2.0,
                ph=ph_target,
                n_mg_l=n_base * 0.95,
                p_mg_l=p_base * 1.05,
                k_mg_l=k_base * 1.00,
                blue_frac=tr_blue,
                red_frac=tr_red,
                far_red_frac=tr_fr,
                uvb_frac=0.0,
                airflow_m_s=0.65,
            ),
            "flower_early": StageSetpoint(
                ppfd=flower_ppfd * 0.90,
                photoperiod_h=flower_photo,
                t_air_c=_clamp(t_day - 0.7, 22.0, 28.5),
                rh_pct=_clamp(rh_day - 4.0, 45.0, 67.0),
                co2_ppm=p["co2_flower_ppm"],
                t_solution_c=19.8,
                do_mg_l=7.8,
                ec_ms_cm=p["ec_flower"] * 0.95,
                ph=ph_target,
                n_mg_l=n_base * 0.85,
                p_mg_l=p_base * 1.10,
                k_mg_l=k_base * 1.08,
                blue_frac=flw_e_blue,
                red_frac=flw_e_red,
                far_red_frac=flw_e_fr,
                uvb_frac=0.0,
                airflow_m_s=0.82,
            ),
            "flower_late": StageSetpoint(
                ppfd=flower_ppfd,
                photoperiod_h=flower_photo,
                t_air_c=_clamp(t_day - 1.5, 21.5, 27.8),
                rh_pct=_clamp(rh_day - 8.0, 42.0, 62.0),
                co2_ppm=p["co2_flower_ppm"] * (0.95 if mode == "max_quality" else 1.00),
                t_solution_c=19.5,
                do_mg_l=7.6,
                ec_ms_cm=p["ec_flower"],
                ph=ph_target,
                n_mg_l=n_base * 0.72,
                p_mg_l=p_base * 1.00,
                k_mg_l=k_base * 1.15,
                blue_frac=flw_l_blue,
                red_frac=flw_l_red,
                far_red_frac=flw_l_fr,
                uvb_frac=uvb_late,
                airflow_m_s=0.95,
            ),
        }

        metadata: Dict[str, float | str | bool] = {
            "source_context": "peer_reviewed_controlled_environment",
            "propagation_system": "DWC",
            "production_system": "NFT_recirculating",
            "veg_density_pl_m2": 15.0,
            "flower_density_pl_m2": 9.0,
            "business_plan_veg_days_target": 25.0,
            "business_plan_photoperiod_flower_h": 12.0,
            "genetic_profile_id": self.genetic_profile.profile_id,
            "genetic_profile_label": self.genetic_profile.label,
            "genetic_seed_category": self.genetic_profile.seed_category,
            "genetic_photoperiodic": bool(self.genetic_profile.photoperiodic),
            "genetic_notes": self.genetic_profile.notes,
            "cultivar_family": self.cultivar_family,
            "cultivar_name": self.cultivar_name or "unspecified",
            "cultivar_catalog_hit": bool(self.cultivar_prior is not None),
        }
        evidence_ids = list(self.genetic_profile.evidence_source_ids)
        evidence_ids.extend(cultivar_evidence_source_ids(self.cultivar_prior))
        metadata["evidence_source_ids"] = ";".join(sorted(set(evidence_ids)))
        for k, v in self.genetic_profile.model_coefficients.items():
            metadata[f"genetics_{k}"] = float(v)
        for k, v in family_coeffs.items():
            metadata[f"genetics_family_{k}"] = float(v)
        for k, v in cultivar_coeffs.items():
            metadata[f"genetics_cultivar_{k}"] = float(v)
        for k, v in self.genetic_profile.metadata.items():
            if isinstance(v, (int, float)):
                metadata[f"genetics_{k}"] = float(v)
            elif isinstance(v, bool):
                metadata[f"genetics_{k}"] = bool(v)
            else:
                metadata[f"genetics_{k}"] = str(v)
        if self.cultivar_prior is not None:
            metadata["cultivar_id"] = self.cultivar_prior.cultivar_id
            for k, v in self.cultivar_prior.metadata.items():
                if isinstance(v, (int, float)):
                    metadata[f"cultivar_{k}"] = float(v)
                elif isinstance(v, bool):
                    metadata[f"cultivar_{k}"] = bool(v)
                else:
                    metadata[f"cultivar_{k}"] = str(v)
        return StrategyProfile(stage_days=stage_days, stage_setpoints=setpoints, metadata=metadata)


class AdaptiveController:
    def __init__(self, mode: str):
        self.mode = mode

    def adjust(
        self,
        stage: str,
        baseline: StageSetpoint,
        sensor: SensorState,
    ) -> Tuple[StageSetpoint, List[str]]:
        low_vpd, high_vpd = VPD_TARGETS[stage]
        adj = replace(baseline)
        reasons: List[str] = []

        if sensor.vpd_kpa < low_vpd:
            delta = low_vpd - sensor.vpd_kpa
            adj.rh_pct = _clamp(adj.rh_pct - 18.0 * delta, 40.0, 85.0)
            adj.t_air_c = _clamp(adj.t_air_c + 1.8 * delta, 20.0, 31.0)
            reasons.append("raise_vpd")
        elif sensor.vpd_kpa > high_vpd:
            delta = sensor.vpd_kpa - high_vpd
            adj.rh_pct = _clamp(adj.rh_pct + 18.0 * delta, 40.0, 85.0)
            adj.t_air_c = _clamp(adj.t_air_c - 1.8 * delta, 20.0, 31.0)
            reasons.append("lower_vpd")

        target_dli = _dli_mol(baseline.ppfd, baseline.photoperiod_h)
        if sensor.dli_prev < 0.95 * target_dli:
            shortfall = target_dli - sensor.dli_prev
            d_ppfd = (shortfall / max(baseline.photoperiod_h, 0.1)) / 0.0036 * 0.60
            adj.ppfd = _clamp(adj.ppfd + d_ppfd, 180.0, 1800.0)
            if stage.startswith("flower") and adj.photoperiod_h < 13.6:
                adj.photoperiod_h = _clamp(adj.photoperiod_h + 0.20, 10.0, 14.0)
            reasons.append("dli_recovery")

        if sensor.ph < 5.55:
            adj.ph = _clamp(adj.ph + 0.12, 5.5, 6.5)
            reasons.append("raise_ph")
        elif sensor.ph > 6.35:
            adj.ph = _clamp(adj.ph - 0.12, 5.5, 6.5)
            reasons.append("lower_ph")

        if sensor.ec_ms_cm > baseline.ec_ms_cm + 0.25 and sensor.transpiration_l_m2_day < 2.4:
            adj.ec_ms_cm = _clamp(adj.ec_ms_cm - 0.12, 1.0, 3.2)
            reasons.append("lower_ec")
        elif sensor.ec_ms_cm < baseline.ec_ms_cm - 0.25 and sensor.transpiration_l_m2_day > 2.4:
            adj.ec_ms_cm = _clamp(adj.ec_ms_cm + 0.12, 1.0, 3.2)
            reasons.append("raise_ec")

        if sensor.transpiration_l_m2_day > 3.6:
            adj.n_mg_l = _clamp(adj.n_mg_l * 0.97, 60.0, 280.0)
            adj.k_mg_l = _clamp(adj.k_mg_l * 1.04, 50.0, 320.0)
            reasons.append("uptake_balance_high_transpiration")
        elif sensor.transpiration_l_m2_day < 1.6:
            adj.n_mg_l = _clamp(adj.n_mg_l * 1.03, 60.0, 280.0)
            reasons.append("uptake_balance_low_transpiration")

        if sensor.t_solution_c > 22.0:
            adj.t_solution_c = _clamp(adj.t_solution_c - 0.7, 16.0, 22.0)
            adj.airflow_m_s = _clamp(adj.airflow_m_s + 0.12, 0.15, 1.6)
            reasons.append("cool_root_zone")

        if sensor.do_mg_l < 7.2:
            adj.do_mg_l = _clamp(adj.do_mg_l + 0.30, 6.5, 11.5)
            adj.airflow_m_s = _clamp(adj.airflow_m_s + 0.10, 0.15, 1.6)
            reasons.append("raise_do")

        if stage == "flower_late":
            if self.mode == "max_quality":
                adj.blue_frac = _clamp(adj.blue_frac + 0.02, 0.05, 0.35)
                adj.far_red_frac = _clamp(adj.far_red_frac * 0.90, 0.01, 0.16)
                adj.uvb_frac = _clamp(adj.uvb_frac + 0.01, 0.0, 0.30)
                reasons.append("quality_spectral_shift")
            else:
                adj.red_frac = _clamp(adj.red_frac + 0.02, 0.40, 0.88)
                adj.far_red_frac = _clamp(adj.far_red_frac + 0.01, 0.01, 0.20)
                reasons.append("yield_spectral_shift")

        b, r, fr = _normalize_spectrum(adj.blue_frac, adj.red_frac, adj.far_red_frac)
        adj.blue_frac = b
        adj.red_frac = r
        adj.far_red_frac = fr
        return adj, reasons

class CEADigitalTwin:
    def __init__(
        self,
        random_seed: int,
        sanitation_level: float = 0.92,
        calibration: Optional[TwinCalibration] = None,
    ):
        self.rng = np.random.default_rng(random_seed)
        self.sanitation_level = _clamp(sanitation_level, 0.0, 1.0)
        self.calibration = clamp_twin_calibration(calibration or TwinCalibration())

    def _profile_model_coefficients(self, profile: StrategyProfile) -> Dict[str, float]:
        profile_id = str(profile.metadata.get("genetic_profile_id", DEFAULT_GENETIC_PROFILE_ID))
        try:
            genetics = get_genetic_profile(profile_id)
        except ValueError:
            genetics = get_genetic_profile(DEFAULT_GENETIC_PROFILE_ID)
        family = str(profile.metadata.get("cultivar_family", genetics.default_cultivar_family))
        try:
            fam_coeffs = family_model_coefficients(genetics, family)
        except ValueError:
            fam_coeffs = family_model_coefficients(genetics, genetics.default_cultivar_family)

        coeffs: Dict[str, float] = {}
        for key, default_base in genetics.model_coefficients.items():
            base_coeff = float(default_base)
            meta_key = f"genetics_{key}"
            if meta_key in profile.metadata:
                try:
                    base_coeff = float(profile.metadata[meta_key])
                except Exception:
                    pass

            family_coeff = float(fam_coeffs.get(key, 1.0))
            fam_meta_key = f"genetics_family_{key}"
            if fam_meta_key in profile.metadata:
                try:
                    family_coeff = float(profile.metadata[fam_meta_key])
                except Exception:
                    pass

            cultivar_coeff = 1.0
            cultivar_meta_key = f"genetics_cultivar_{key}"
            if cultivar_meta_key in profile.metadata:
                try:
                    cultivar_coeff = float(profile.metadata[cultivar_meta_key])
                except Exception:
                    pass

            coeffs[key] = base_coeff * family_coeff * cultivar_coeff

        coeffs["yield_potential_scale"] = _clamp(coeffs.get("yield_potential_scale", 1.0), 0.50, 1.80)
        coeffs["quality_potential_scale"] = _clamp(coeffs.get("quality_potential_scale", 1.0), 0.50, 1.80)
        coeffs["disease_pressure_scale"] = _clamp(coeffs.get("disease_pressure_scale", 1.0), 0.50, 2.00)
        coeffs["hlvd_pressure_scale"] = _clamp(coeffs.get("hlvd_pressure_scale", 1.0), 0.50, 2.00)
        coeffs["nutrient_window_scale"] = _clamp(coeffs.get("nutrient_window_scale", 1.0), 0.60, 1.60)
        return coeffs

    def simulate_cycle(self, profile: StrategyProfile, mode: str) -> CycleOutcome:
        controller = AdaptiveController(mode=mode)
        model_coeffs = self._profile_model_coefficients(profile)
        prop = profile.stage_setpoints["propagation"]
        sensor = SensorState(
            t_air_c=prop.t_air_c,
            rh_pct=prop.rh_pct,
            co2_ppm=prop.co2_ppm,
            ppfd=prop.ppfd,
            t_solution_c=prop.t_solution_c,
            do_mg_l=prop.do_mg_l,
            ec_ms_cm=prop.ec_ms_cm,
            ph=prop.ph,
            dli_prev=_dli_mol(prop.ppfd, prop.photoperiod_h),
            transpiration_l_m2_day=1.0,
            vpd_kpa=_vpd_kpa(prop.t_air_c, prop.rh_pct),
            disease_pressure=0.05,
            hlvd_pressure=(1.0 - self.sanitation_level) * 0.03,
        )

        lai = 0.45
        total_yield = 0.0
        quality_units = 0.0
        total_energy = 0.0
        total_penalty = 0.0
        logs: List[DayLog] = []

        for day in range(1, profile.total_days() + 1):
            stage = profile.stage_for_day(day)
            baseline = profile.stage_setpoints[stage]
            adjusted, reasons = controller.adjust(stage=stage, baseline=baseline, sensor=sensor)
            sensor, lai, y_gain, q_gain, e_day, p_day = self._advance_one_day(
                stage=stage,
                setpoint=adjusted,
                prev_sensor=sensor,
                prev_lai=lai,
                mode=mode,
                model_coefficients=model_coeffs,
            )
            total_yield += y_gain
            quality_units += q_gain
            total_energy += e_day
            total_penalty += p_day
            logs.append(
                DayLog(
                    day=day,
                    stage=stage,
                    dli_mol=sensor.dli_prev,
                    yield_gain_g_m2=y_gain,
                    quality_gain_units=q_gain,
                    energy_kwh_m2=e_day,
                    penalty=p_day,
                    vpd_kpa=sensor.vpd_kpa,
                    ec_ms_cm=sensor.ec_ms_cm,
                    ph=sensor.ph,
                    adjustments=reasons,
                )
            )

        disease_factor = 1.0 - 0.05 * min(sensor.disease_pressure, 6.0) / 6.0
        hlvd_factor = 1.0 - 0.22 * sensor.hlvd_pressure
        total_yield *= disease_factor * hlvd_factor
        total_yield *= self.calibration.yield_post_scale

        quality_signal = 16.0 + 1.05 * quality_units
        quality_yield_drag = 0.010 * max(total_yield - 1700.0, 0.0)
        quality_health_drag = 2.2 * sensor.disease_pressure + 18.0 * sensor.hlvd_pressure
        quality_index = quality_signal - quality_yield_drag - quality_health_drag
        quality_index = quality_index * self.calibration.quality_post_scale + self.calibration.quality_post_offset
        quality_index = _clamp(quality_index, 0.0, 100.0)

        g_per_kwh = total_yield / max(total_energy, 1e-9)
        return CycleOutcome(
            mode=mode,
            dry_yield_g_m2=total_yield,
            quality_index=quality_index,
            energy_kwh_m2=total_energy,
            g_per_kwh=g_per_kwh,
            penalty=total_penalty,
            disease_pressure=sensor.disease_pressure,
            hlvd_pressure=sensor.hlvd_pressure,
            daily_logs=logs,
        )

    def _advance_one_day(
        self,
        stage: str,
        setpoint: StageSetpoint,
        prev_sensor: SensorState,
        prev_lai: float,
        mode: str,
        model_coefficients: Dict[str, float],
    ) -> Tuple[SensorState, float, float, float, float, float]:
        def lag(prev: float, target: float, alpha: float, noise_sd: float) -> float:
            return float(prev + alpha * (target - prev) + self.rng.normal(0.0, noise_sd))

        t_air = _clamp(lag(prev_sensor.t_air_c, setpoint.t_air_c, 0.48, 0.35), 18.0, 33.0)
        rh = _clamp(lag(prev_sensor.rh_pct, setpoint.rh_pct, 0.50, 1.2), 35.0, 90.0)
        co2 = _clamp(lag(prev_sensor.co2_ppm, setpoint.co2_ppm, 0.40, 18.0), 380.0, 1300.0)
        ppfd = _clamp(lag(prev_sensor.ppfd, setpoint.ppfd, 0.40, 18.0), 120.0, 1900.0)
        t_sol = _clamp(lag(prev_sensor.t_solution_c, setpoint.t_solution_c, 0.35, 0.20), 15.0, 25.0)

        vpd = _vpd_kpa(t_air, rh)
        dli = _dli_mol(ppfd, setpoint.photoperiod_h)
        transp = _clamp(
            0.16 * dli * (0.65 + 0.45 * vpd) * (0.45 + 0.15 * prev_lai) * self.calibration.transpiration_scale,
            0.6,
            6.5,
        )

        ec = lag(prev_sensor.ec_ms_cm, setpoint.ec_ms_cm, 0.34, 0.04) + 0.03 * (transp - 2.4)
        ec = _clamp(ec, 0.8, 3.6)
        ph = lag(prev_sensor.ph, setpoint.ph, 0.30, 0.03) + 0.012 * (ec - 2.0)
        ph = _clamp(ph, 5.2, 6.8)
        do = lag(prev_sensor.do_mg_l, setpoint.do_mg_l, 0.36, 0.08) + 0.16 * (setpoint.airflow_m_s - 0.45) - 0.14 * max(t_sol - 21.0, 0.0)
        do = _clamp(do, 5.5, 11.5)

        low_vpd, high_vpd = VPD_TARGETS[stage]
        vpd_opt = 0.5 * (low_vpd + high_vpd)
        ec_opt = setpoint.ec_ms_cm
        t_opt = 26.0 if stage in {"vegetative", "transition"} else 25.0

        f_temp = _gaussian_response(t_air, t_opt, 3.0)
        f_vpd = _gaussian_response(vpd, vpd_opt, 0.33)
        f_co2 = _clamp(0.65 + 0.55 * (1.0 - np.exp(-(co2 - 380.0) / 450.0)), 0.55, 1.25)
        f_light = _clamp(1.0 - np.exp(-(dli - 6.0) / 24.0), 0.0, 1.25)
        nutrient_window = model_coefficients.get("nutrient_window_scale", 1.0)
        f_nutr = 0.55 * _gaussian_response(ec, ec_opt, 0.45 * nutrient_window) + 0.45 * _gaussian_response(
            ph,
            5.9,
            0.22 * nutrient_window,
        )
        f_root = _gaussian_response(t_sol, 20.0, 1.8) * _logistic_response(do, 7.1, 0.6)

        disease_inc = (
            0.020 * max(rh - 72.0, 0.0)
            + 0.090 * max(0.82 - vpd, 0.0)
            + 0.070 * max(t_sol - 22.0, 0.0)
            + 0.095 * max(7.0 - do, 0.0)
        )
        if stage.startswith("flower"):
            disease_inc *= 1.18
        disease_inc *= model_coefficients.get("disease_pressure_scale", 1.0)
        disease_inc *= self.calibration.disease_inc_scale
        disease = _clamp(prev_sensor.disease_pressure + disease_inc, 0.0, 10.0)

        hlvd_inc = (
            (0.0018 * (1.0 - self.sanitation_level) + 0.0008 * disease_inc)
            * model_coefficients.get("hlvd_pressure_scale", 1.0)
            * self.calibration.hlvd_inc_scale
        )
        hlvd = _clamp(prev_sensor.hlvd_pressure + hlvd_inc, 0.0, 1.0)

        health = _clamp(1.0 - 0.065 * disease - 0.23 * hlvd, 0.40, 1.10)
        canopy = _clamp(1.0 - np.exp(-0.58 * prev_lai), 0.18, 1.00)

        y_gain = (
            dli
            * 0.52
            * YIELD_STAGE_WEIGHT[stage]
            * canopy
            * (0.24 * f_light + 0.20 * f_temp + 0.20 * f_vpd + 0.16 * f_nutr + 0.10 * f_root + 0.10 * f_co2)
            * health
        )
        y_gain *= model_coefficients.get("yield_potential_scale", 1.0)
        y_gain = max(float(y_gain * self.calibration.yield_gain_scale), 0.0)

        if mode == "max_quality":
            q_blue_opt, q_fr_opt, q_uv_opt = 0.23, 0.04, 0.08
        else:
            q_blue_opt, q_fr_opt, q_uv_opt = 0.16, 0.09, 0.03

        spectrum_quality = (
            0.55 * _gaussian_response(setpoint.blue_frac, q_blue_opt, 0.08)
            + 0.25 * _gaussian_response(setpoint.far_red_frac, q_fr_opt, 0.05)
            + 0.20 * _gaussian_response(setpoint.uvb_frac, q_uv_opt, 0.05)
        )
        mild_stress = _gaussian_response(vpd, 1.20 if stage.startswith("flower") else 1.0, 0.30)
        q_gain = QUALITY_STAGE_WEIGHT[stage] * (0.50 * spectrum_quality + 0.20 * mild_stress + 0.15 * f_root + 0.15 * health)
        q_gain *= model_coefficients.get("quality_potential_scale", 1.0)
        q_gain = max(float(q_gain * self.calibration.quality_gain_scale), 0.0)

        led_kwh = (ppfd / 3.0) * setpoint.photoperiod_h / 1000.0
        hvac_kwh = (
            0.45
            + 0.020 * abs(t_air - 24.0)
            + 0.008 * max(rh - 60.0, 0.0)
            + 0.002 * max(co2 - 400.0, 0.0) / 10.0
        )
        energy = float((led_kwh + hvac_kwh) * self.calibration.energy_scale)

        penalty = 0.0
        if vpd < low_vpd:
            penalty += 8.0 * (low_vpd - vpd)
        if vpd > high_vpd:
            penalty += 8.0 * (vpd - high_vpd)
        if ph < 5.5:
            penalty += 14.0 * (5.5 - ph)
        if ph > 6.4:
            penalty += 14.0 * (ph - 6.4)
        if ec < 1.0:
            penalty += 8.0 * (1.0 - ec)
        if ec > 3.2:
            penalty += 8.0 * (ec - 3.2)
        if do < 7.0:
            penalty += 7.0 * (7.0 - do)
        if stage.startswith("flower") and rh > 82.0:
            penalty += 0.8 * (rh - 82.0)
        penalty *= self.calibration.penalty_scale

        lai = _clamp(
            prev_lai + LAI_STAGE_DELTA[stage] * (0.45 * f_light + 0.35 * f_nutr + 0.20 * f_temp),
            0.30,
            6.2,
        )

        new_sensor = SensorState(
            t_air_c=t_air,
            rh_pct=rh,
            co2_ppm=co2,
            ppfd=ppfd,
            t_solution_c=t_sol,
            do_mg_l=do,
            ec_ms_cm=ec,
            ph=ph,
            dli_prev=dli,
            transpiration_l_m2_day=transp,
            vpd_kpa=vpd,
            disease_pressure=disease,
            hlvd_pressure=hlvd,
        )
        return new_sensor, lai, y_gain, q_gain, energy, penalty

class BayesianStrategySearch:
    def __init__(
        self,
        mode: str,
        yield_floor_g_m2: float,
        seed: int = 2026,
        genetic_profile_id: str = DEFAULT_GENETIC_PROFILE_ID,
        cultivar_family: str | None = None,
        cultivar_name: str = "",
    ):
        if mode not in {"max_yield", "max_quality"}:
            raise ValueError("mode must be 'max_yield' or 'max_quality'")
        self.mode = mode
        self.yield_floor_g_m2 = float(yield_floor_g_m2)
        self.seed = seed
        self.builder = StrategyBuilder(
            genetic_profile_id=genetic_profile_id,
            cultivar_family=cultivar_family,
            cultivar_name=cultivar_name,
        )
        self.space = ParameterSpace(self.builder.parameter_bounds())
        self.records: List[EvaluatedCandidate] = []

    def _objective(self, outcome: CycleOutcome) -> float:
        if self.mode == "max_yield":
            return (
                outcome.dry_yield_g_m2
                - 0.12 * outcome.energy_kwh_m2
                - 16.0 * outcome.penalty
                + 0.25 * outcome.quality_index
            )
        score = (
            24.0 * outcome.quality_index
            + 0.12 * outcome.dry_yield_g_m2
            - 0.10 * outcome.energy_kwh_m2
            - 18.0 * outcome.penalty
        )
        if outcome.dry_yield_g_m2 < self.yield_floor_g_m2:
            score -= 2.8 * (self.yield_floor_g_m2 - outcome.dry_yield_g_m2)
        return score

    def _evaluate(self, x: np.ndarray, twin_seed: int) -> EvaluatedCandidate:
        x = self.space.clip(x)
        params = self.space.to_dict(x)
        profile = self.builder.build(p=params, mode=self.mode)
        twin = CEADigitalTwin(random_seed=twin_seed, sanitation_level=0.93)
        outcome = twin.simulate_cycle(profile=profile, mode=self.mode)
        score = self._objective(outcome)
        return EvaluatedCandidate(x=x, params=params, profile=profile, outcome=outcome, score=score)

    def search(self, n_init: int = 20, n_iter: int = 24, pool_size: int = 1800) -> EvaluatedCandidate:
        X0 = self.space.sample_uniform(n=n_init, seed=self.seed)
        for i, x in enumerate(X0):
            self.records.append(self._evaluate(x=x, twin_seed=self.seed + 37 * (i + 1)))

        kernel = ConstantKernel(1.0, (1e-3, 1e3)) * Matern(length_scale=1.0, nu=2.5) + WhiteKernel(
            noise_level=1e-3,
            noise_level_bounds=(1e-6, 1e-1),
        )

        for k in range(n_iter):
            X = np.vstack([r.x for r in self.records])
            y = np.array([r.score for r in self.records], dtype=float)
            gp = GaussianProcessRegressor(
                kernel=kernel,
                normalize_y=True,
                random_state=self.seed + 1000 + k,
            )
            gp.fit(X, y)

            pool = self.space.sample_uniform(n=pool_size, seed=self.seed + 2000 + k)
            mu, std = gp.predict(pool, return_std=True)
            beta = max(0.8, 2.2 - 0.05 * k)
            acq = mu + beta * std
            x_next = pool[int(np.argmax(acq))]

            best = max(self.records, key=lambda r: r.score)
            rng = np.random.default_rng(self.seed + 3000 + k)
            jitter = rng.normal(0.0, 0.03, size=x_next.shape[0]) * (self.space.hi - self.space.lo)
            x_local = self.space.clip(best.x + jitter)
            choose_local = bool((k % 3) == 2)
            chosen = x_local if choose_local else x_next

            self.records.append(self._evaluate(x=chosen, twin_seed=self.seed + 71 * (k + 1)))

        return max(self.records, key=lambda r: r.score)


def summarize_adjustments(logs: List[DayLog], top_n: int = 8) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for log in logs:
        for reason in log.adjustments:
            counts[reason] = counts.get(reason, 0) + 1
    pairs = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return {k: int(v) for k, v in pairs}


def profile_to_dict(profile: StrategyProfile) -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}
    for stage in STAGE_ORDER:
        sp = profile.stage_setpoints[stage]
        row = asdict(sp)
        row["days"] = int(profile.stage_days[stage])
        row["dli_mol_m2_day"] = _dli_mol(sp.ppfd, sp.photoperiod_h)
        row["vpd_target_kpa"] = list(VPD_TARGETS[stage])
        out[stage] = row
    out["_metadata"] = dict(profile.metadata)
    return out


def outcome_to_dict(outcome: CycleOutcome, logs_tail: int = 6) -> Dict:
    tail = outcome.daily_logs[-logs_tail:]
    return {
        "mode": outcome.mode,
        "dry_yield_g_m2": outcome.dry_yield_g_m2,
        "quality_index": outcome.quality_index,
        "energy_kwh_m2": outcome.energy_kwh_m2,
        "g_per_kwh": outcome.g_per_kwh,
        "penalty": outcome.penalty,
        "disease_pressure": outcome.disease_pressure,
        "hlvd_pressure": outcome.hlvd_pressure,
        "adjustment_summary": summarize_adjustments(outcome.daily_logs),
        "last_days": [asdict(d) for d in tail],
    }


def profile_literature_sources(profile: StrategyProfile) -> List[Dict[str, object]]:
    raw = profile.metadata.get("evidence_source_ids")
    source_ids: List[str]
    if isinstance(raw, str) and raw.strip():
        source_ids = [s.strip() for s in raw.split(";") if s.strip()]
    else:
        pid = str(profile.metadata.get("genetic_profile_id", DEFAULT_GENETIC_PROFILE_ID))
        source_ids = list(profile_evidence_source_ids(pid))
    return literature_sources_to_dict(source_ids)


def run_mode(mode: str, args: argparse.Namespace) -> Dict:
    search = BayesianStrategySearch(
        mode=mode,
        yield_floor_g_m2=args.quality_y_min,
        seed=args.seed + (0 if mode == "max_yield" else 100),
        genetic_profile_id=args.genetic_profile,
        cultivar_family=getattr(args, "cultivar_family", None),
        cultivar_name=str(getattr(args, "cultivar_name", "")),
    )
    best = search.search(n_init=args.n_init, n_iter=args.n_iter, pool_size=args.pool_size)

    density_flower = best.profile.metadata["flower_density_pl_m2"]
    per_plant = best.outcome.dry_yield_g_m2 / max(float(density_flower), 1e-9)

    return {
        "mode": mode,
        "score": best.score,
        "dry_yield_g_m2": best.outcome.dry_yield_g_m2,
        "dry_yield_g_plant_est": per_plant,
        "quality_index": best.outcome.quality_index,
        "energy_kwh_m2": best.outcome.energy_kwh_m2,
        "g_per_kwh": best.outcome.g_per_kwh,
        "penalty": best.outcome.penalty,
        "profile": profile_to_dict(best.profile),
        "metadata": best.profile.metadata,
        "literature_sources": profile_literature_sources(best.profile),
        "outcome": outcome_to_dict(best.outcome, logs_tail=6),
        "params": best.params,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "CEA multi-objective optimizer with sensor-adaptive control "
            "across phenological phases (yield and quality variants)."
        )
    )
    parser.add_argument("--mode", choices=["max_yield", "max_quality", "both"], default="both")
    parser.add_argument(
        "--quality-y-min",
        type=float,
        default=1300.0,
        help="Yield floor used by max_quality objective (g/m2).",
    )
    parser.add_argument("--n-init", type=int, default=20, help="Initial LHS evaluations.")
    parser.add_argument("--n-iter", type=int, default=24, help="Bayesian optimization iterations.")
    parser.add_argument("--pool-size", type=int, default=1800, help="Candidate pool size per BO step.")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument(
        "--genetic-profile",
        choices=available_genetic_profiles(),
        default=default_genetic_profile_id(),
        help="Genetic profile used to customize bounds and twin coefficients.",
    )
    parser.add_argument(
        "--cultivar-family",
        choices=available_cultivar_families(),
        default=None,
        help="Optional cultivar family prior (hybrid/sativa_dominant/indica_dominant).",
    )
    parser.add_argument(
        "--cultivar-name",
        default="",
        help="Optional cultivar tag stored in profile metadata.",
    )
    parser.add_argument("--json-only", action="store_true", help="Print only JSON payload.")
    args = parser.parse_args()
    try:
        norm_profile, norm_family, prior = validate_profile_cultivar_args(
            profile_id=args.genetic_profile,
            cultivar_family=args.cultivar_family,
            cultivar_name=args.cultivar_name,
        )
    except ValueError as exc:
        parser.error(str(exc))
    args.genetic_profile = norm_profile
    args.cultivar_family = norm_family
    if prior is not None and not str(args.cultivar_name).strip():
        args.cultivar_name = prior.name

    modes = [args.mode] if args.mode != "both" else ["max_yield", "max_quality"]
    payload = {"results": [run_mode(mode=m, args=args) for m in modes]}

    if args.json_only:
        print(json.dumps(payload, indent=2))
        return

    for item in payload["results"]:    
        print(f"\n=== {item['mode']} ===")
        print(f"Score:                 {item['score']:.2f}")
        print(f"Dry yield (g/m2):      {item['dry_yield_g_m2']:.2f}")
        print(f"Dry yield (g/plant):   {item['dry_yield_g_plant_est']:.2f}")
        print(f"Quality index:         {item['quality_index']:.2f}")
        print(f"Energy (kWh/m2):       {item['energy_kwh_m2']:.2f}")
        print(f"Energy efficiency:     {item['g_per_kwh']:.3f} g/kWh")
        print(f"Constraint penalty:    {item['penalty']:.2f}")
        print("Top adaptive actions:")
        print(json.dumps(item["outcome"]["adjustment_summary"], indent=2))
        print("Recommended stage profile:")
        print(json.dumps(item["profile"], indent=2))

    print("\nFull payload:")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
