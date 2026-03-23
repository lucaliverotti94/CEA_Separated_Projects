from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
import argparse
import json

import numpy as np
from scipy.stats import norm
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

from core.genetics import (
    DEFAULT_GENETIC_PROFILE_ID,
    available_cultivar_families,
    available_genetic_profiles,
    default_genetic_profile_id,
    validate_profile_cultivar_args,
)
from core.governance import dict_signature, git_commit_short, new_run_id
from core.model import (
    Bounds,
    CEADigitalTwin,
    CycleOutcome,
    ParameterSpace,
    StrategyBuilder,
    StrategyProfile,
    TwinCalibration,
    load_twin_calibration,
    outcome_to_dict,
    clone_cycle_derived_metrics,
    profile_literature_sources,
    reference_audit_summary,
    profile_to_dict,
    twin_calibration_to_dict,
)
from core.storage import init_storage, store_optimizer_run


BASE_MODES = {"max_yield", "max_quality"}
ENERGY_CONSTRAINED_MODES = {"max_yield_energy", "max_quality_energy"}
ALL_MODES = BASE_MODES | ENERGY_CONSTRAINED_MODES
MODE_BASE = {
    "max_yield": "max_yield",
    "max_quality": "max_quality",
    "max_yield_energy": "max_yield",
    "max_quality_energy": "max_quality",
}
DEFAULT_ENERGY_CAP_KWH_M2 = 700.0
DEFAULT_YIELD_CAP_ANNUAL_KG = 80.0
DEFAULT_FARM_ACTIVE_AREA_M2 = 1.0


def _base_mode(mode: str) -> str:
    if mode not in ALL_MODES:
        raise ValueError(
            "mode must be one of: max_yield, max_quality, max_yield_energy, max_quality_energy"
        )
    return MODE_BASE[mode]


def _is_energy_constrained_mode(mode: str) -> bool:
    return mode in ENERGY_CONSTRAINED_MODES


@dataclass
class SearchRecord:
    x: np.ndarray
    params: Dict[str, float]
    profile: StrategyProfile
    objective: float
    feasibility_violation: float
    penalty: float
    disease_pressure: float
    hlvd_pressure: float
    dry_yield_g_m2: float
    quality_index: float
    energy_kwh_m2: float
    outcome_dict: Dict


class CannabisYieldLiteratureBuilder(StrategyBuilder):
    """Bound piu` stringenti su cannabis, coerenti con studi agronomici recenti."""

    def __init__(
        self,
        genetic_profile_id: str = DEFAULT_GENETIC_PROFILE_ID,
        cultivar_family: str | None = None,
        cultivar_name: str = "",
    ):
        super().__init__(
            genetic_profile_id=genetic_profile_id,
            cultivar_family=cultivar_family,
            cultivar_name=cultivar_name,
        )

    @staticmethod
    def _literature_bounds() -> Dict[str, Bounds]:
        return {
            "veg_ppfd": Bounds(360.0, 850.0),
            "flower_ppfd": Bounds(900.0, 1800.0),
            "flower_photoperiod_h": Bounds(12.0, 14.0),
            "co2_flower_ppm": Bounds(450.0, 1200.0),
            "air_temp_day_c": Bounds(23.0, 29.0),
            "rh_day_pct": Bounds(50.0, 70.0),
            "ec_veg": Bounds(1.4, 2.4),
            "ec_flower": Bounds(1.8, 3.0),
            "ph_target": Bounds(5.7, 6.2),
            "n_mg_l": Bounds(140.0, 240.0),
            "p_mg_l": Bounds(15.0, 60.0),
            "k_mg_l": Bounds(60.0, 240.0),
            "blue_flower_frac": Bounds(0.10, 0.28),
            "far_red_flower_frac": Bounds(0.02, 0.14),
            "uvb_late_frac": Bounds(0.00, 0.10),
        }

    def parameter_bounds(self) -> Dict[str, Bounds]:
        return self._with_family_bound_overrides(self._with_genetic_bound_overrides(self._literature_bounds()))


class ConstrainedYieldBO:
    def __init__(
        self,
        mode: str,
        yield_floor_g_m2: float,
        energy_cap_kwh_m2: float = DEFAULT_ENERGY_CAP_KWH_M2,
        yield_cap_kg_m2_year: Optional[float] = None,
        seed: int = 2026,
        twin_calibration: Optional[TwinCalibration] = None,
        genetic_profile_id: str = DEFAULT_GENETIC_PROFILE_ID,
        cultivar_family: str | None = None,
        cultivar_name: str = "",
    ):
        self.mode = mode
        self.base_mode = _base_mode(mode)
        self.energy_cap_kwh_m2 = float(energy_cap_kwh_m2)
        if self.energy_cap_kwh_m2 <= 0.0:
            raise ValueError("energy_cap_kwh_m2 must be > 0")
        self.energy_constraint_active = _is_energy_constrained_mode(mode)
        self.seed = int(seed)
        self.yield_floor_g_m2 = float(yield_floor_g_m2)
        self.twin_calibration = twin_calibration
        self.builder = CannabisYieldLiteratureBuilder(
            genetic_profile_id=genetic_profile_id,
            cultivar_family=cultivar_family,
            cultivar_name=cultivar_name,
        )
        bounds = self.builder.parameter_bounds()
        self.space = ParameterSpace(bounds)
        self.records: List[SearchRecord] = []
        self.yield_cap_kg_m2_year: Optional[float] = None
        self.yield_cap_g_m2_cycle: Optional[float] = None
        self.yield_cap_active = bool(yield_cap_kg_m2_year is not None)
        if self.yield_cap_active:
            cap_kg_m2_year = float(yield_cap_kg_m2_year)
            if cap_kg_m2_year <= 0.0:
                raise ValueError("yield_cap_kg_m2_year must be > 0")
            midpoint_params = {k: (b.lo + b.hi) / 2.0 for k, b in bounds.items()}
            ref_profile = self.builder.build(p=midpoint_params, mode=self.base_mode)
            cycle_days = max(float(sum(ref_profile.stage_days.values())), 1e-9)
            cycles_per_year = 365.0 / cycle_days
            self.yield_cap_kg_m2_year = cap_kg_m2_year
            self.yield_cap_g_m2_cycle = (cap_kg_m2_year * 1000.0) / cycles_per_year

        kernel = ConstantKernel(1.0, (1e-3, 1e3)) * Matern(length_scale=1.0, nu=2.5) + WhiteKernel(
            noise_level=1e-3,
            noise_level_bounds=(1e-6, 1e-1),
        )
        self.gp_obj = GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=self.seed + 11)
        self.gp_yield = GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=self.seed + 12)
        self.gp_violation = GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=self.seed + 13)
        self.gp_penalty = GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=self.seed + 17)
        self.gp_disease = GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=self.seed + 19)
        self.gp_hlvd = GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=self.seed + 23)
        self.gp_energy = GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=self.seed + 29)

    def _objective(self, outcome: CycleOutcome) -> float:
        if self.base_mode == "max_yield":
            # Nessun termine energia: ottimizzazione pura della resa.
            return float(outcome.dry_yield_g_m2)

        # Modalita` qualita`: quality pura (nessun termine resa/energia nell'obiettivo).
        return float(outcome.quality_index)

    def _literature_violation(self, params: Dict[str, float], outcome: Dict) -> float:
        """0.0 = piena aderenza; valori alti = soluzione meno credibile/robusta."""
        v = 0.0

        veg_ppfd = params["veg_ppfd"]
        flower_ppfd = params["flower_ppfd"]
        flower_photo = params["flower_photoperiod_h"]
        p_mg_l = params["p_mg_l"]
        ec_flower = params["ec_flower"]

        # Penalizza profili con fioritura sottodimensionata vs fase vegetativa.
        v += max(0.0, (veg_ppfd + 120.0 - flower_ppfd) / 100.0)

        # Finestra fotoperiodo fioritura conservativa (12-14h).
        v += max(0.0, 12.0 - flower_photo) * 4.0
        v += max(0.0, flower_photo - 14.0) * 4.0

        # Eccessi P/EC in genere poco produttivi su cannabis.
        v += max(0.0, p_mg_l - 60.0) / 8.0
        v += max(0.0, ec_flower - 3.0) * 2.0

        # Vincoli di processo e fitosanitari.
        v += max(0.0, float(outcome["penalty"]) - 12.0) / 8.0
        v += max(0.0, float(outcome["disease_pressure"]) - 2.5) * 0.6
        v += max(0.0, float(outcome["hlvd_pressure"]) - 0.05) * 8.0

        return float(v)

    def _evaluate(self, x: np.ndarray, twin_seed: int) -> SearchRecord:
        x = self.space.clip(x)
        params = self.space.to_dict(x)
        profile = self.builder.build(p=params, mode=self.base_mode)

        twin = CEADigitalTwin(
            random_seed=twin_seed,
            sanitation_level=0.94,
            calibration=self.twin_calibration,
        )
        outcome = twin.simulate_cycle(profile=profile, mode=self.base_mode)

        out = {
            "dry_yield_g_m2": outcome.dry_yield_g_m2,
            "quality_index": outcome.quality_index,
            "energy_kwh_m2": outcome.energy_kwh_m2,
            "g_per_kwh": outcome.g_per_kwh,
            "penalty": outcome.penalty,
            "disease_pressure": outcome.disease_pressure,
            "hlvd_pressure": outcome.hlvd_pressure,
        }

        objective = self._objective(outcome)
        violation = self._literature_violation(params=params, outcome=out)

        return SearchRecord(
            x=x,
            params=params,
            profile=profile,
            objective=objective,
            feasibility_violation=violation,
            penalty=out["penalty"],
            disease_pressure=out["disease_pressure"],
            hlvd_pressure=out["hlvd_pressure"],
            dry_yield_g_m2=out["dry_yield_g_m2"],
            quality_index=out["quality_index"],
            energy_kwh_m2=out["energy_kwh_m2"],
            outcome_dict=outcome_to_dict(outcome, logs_tail=6),
        )

    def _fit_models(self) -> None:
        X = np.vstack([r.x for r in self.records])
        y_obj = np.array([r.objective for r in self.records], dtype=float)
        y_yield = np.array([r.dry_yield_g_m2 for r in self.records], dtype=float)
        y_vio = np.array([r.feasibility_violation for r in self.records], dtype=float)
        y_pen = np.array([r.penalty for r in self.records], dtype=float)
        y_dis = np.array([r.disease_pressure for r in self.records], dtype=float)
        y_hlv = np.array([r.hlvd_pressure for r in self.records], dtype=float)
        y_energy = np.array([r.energy_kwh_m2 for r in self.records], dtype=float)

        self.gp_obj.fit(X, y_obj)
        self.gp_yield.fit(X, y_yield)
        self.gp_violation.fit(X, y_vio)
        self.gp_penalty.fit(X, y_pen)
        self.gp_disease.fit(X, y_dis)
        self.gp_hlvd.fit(X, y_hlv)
        self.gp_energy.fit(X, y_energy)

    @staticmethod
    def _normal_cdf(x: np.ndarray) -> np.ndarray:
        return norm.cdf(x)

    @staticmethod
    def _normal_pdf(x: np.ndarray) -> np.ndarray:
        return norm.pdf(x)

    def _acquisition(self, xcand: np.ndarray) -> np.ndarray:
        mu, std = self.gp_obj.predict(xcand, return_std=True)
        std = np.maximum(std, 1e-9)

        best = max(r.objective for r in self.records)
        z = (mu - best) / std
        ei = (mu - best) * self._normal_cdf(z) + std * self._normal_pdf(z)
        ei = np.maximum(ei, 0.0)

        mu_v, std_v = self.gp_violation.predict(xcand, return_std=True)
        mu_p, std_p = self.gp_penalty.predict(xcand, return_std=True)
        mu_d, std_d = self.gp_disease.predict(xcand, return_std=True)
        mu_h, std_h = self.gp_hlvd.predict(xcand, return_std=True)
        mu_e, std_e = self.gp_energy.predict(xcand, return_std=True)

        std_v = np.maximum(std_v, 1e-9)
        std_p = np.maximum(std_p, 1e-9)
        std_d = np.maximum(std_d, 1e-9)
        std_h = np.maximum(std_h, 1e-9)
        std_e = np.maximum(std_e, 1e-9)

        p_v = self._normal_cdf((0.50 - mu_v) / std_v)
        p_p = self._normal_cdf((15.0 - mu_p) / std_p)
        p_d = self._normal_cdf((3.0 - mu_d) / std_d)
        p_h = self._normal_cdf((0.08 - mu_h) / std_h)
        p_feas = p_v * p_p * p_d * p_h

        if self.energy_constraint_active:
            p_energy = self._normal_cdf((self.energy_cap_kwh_m2 - mu_e) / std_e)
            p_feas *= p_energy

        if self.base_mode == "max_quality" or self.yield_cap_active:
            y_mu, y_std = self.gp_yield.predict(xcand, return_std=True)
            y_std = np.maximum(y_std, 1e-9)

        if self.yield_cap_active and self.yield_cap_g_m2_cycle is not None:
            p_yield_cap = self._normal_cdf((self.yield_cap_g_m2_cycle - y_mu) / y_std)
            p_feas *= p_yield_cap

        if self.base_mode == "max_quality":
            p_floor = self._normal_cdf((y_mu - self.yield_floor_g_m2) / y_std)
            p_feas *= p_floor

        return ei * p_feas

    def search(self, n_init: int = 24, n_iter: int = 30, pool_size: int = 2500) -> SearchRecord:
        x0 = self.space.sample_uniform(n=n_init, seed=self.seed)
        for i, x in enumerate(x0):
            self.records.append(self._evaluate(x=x, twin_seed=self.seed + 101 * (i + 1)))

        rng = np.random.default_rng(self.seed + 4000)
        for k in range(n_iter):
            self._fit_models()
            pool = self.space.sample_uniform(n=pool_size, seed=self.seed + 5000 + k)
            acq = self._acquisition(pool)
            x_next = pool[int(np.argmax(acq))]

            if (k % 3) == 2:
                best = max(self.records, key=lambda r: r.objective - 20.0 * r.feasibility_violation)
                jitter = rng.normal(0.0, 0.02, size=x_next.shape[0]) * (self.space.hi - self.space.lo)
                x_next = self.space.clip(best.x + jitter)

            self.records.append(self._evaluate(x=x_next, twin_seed=self.seed + 137 * (k + 1)))

        feasible = [
            r
            for r in self.records
            if r.feasibility_violation <= 0.50
            and r.penalty <= 15.0
            and r.disease_pressure <= 3.0
            and r.hlvd_pressure <= 0.08
            and (not self.energy_constraint_active or r.energy_kwh_m2 <= self.energy_cap_kwh_m2)
            and (self.base_mode != "max_quality" or r.dry_yield_g_m2 >= self.yield_floor_g_m2)
            and (not self.yield_cap_active or (self.yield_cap_g_m2_cycle is not None and r.dry_yield_g_m2 <= self.yield_cap_g_m2_cycle))
        ]
        if feasible:
            # In max_quality, a parita` di quality usa la resa come tie-break.
            if self.base_mode == "max_quality":
                return max(feasible, key=lambda r: (r.objective, r.dry_yield_g_m2))
            return max(feasible, key=lambda r: r.objective)
        if self.base_mode == "max_quality":
            details: List[str] = []
            details.append(f"hard yield floor >= {self.yield_floor_g_m2:.1f} g/m2")
            if self.energy_constraint_active:
                details.append(f"energy <= {self.energy_cap_kwh_m2:.1f} kWh/m2")
            if self.yield_cap_active and self.yield_cap_kg_m2_year is not None:
                details.append(f"yield <= {self.yield_cap_kg_m2_year:.3f} kg/m2/year")
            detail_txt = " and ".join(details)
            raise RuntimeError(
                f"No feasible candidate found for {self.mode} with {detail_txt}."
            )
        if self.energy_constraint_active or self.yield_cap_active:
            hard_candidates = [
                r
                for r in self.records
                if (not self.energy_constraint_active or r.energy_kwh_m2 <= self.energy_cap_kwh_m2)
                and (not self.yield_cap_active or (self.yield_cap_g_m2_cycle is not None and r.dry_yield_g_m2 <= self.yield_cap_g_m2_cycle))
            ]
            if hard_candidates:
                return max(hard_candidates, key=lambda r: r.objective - 20.0 * r.feasibility_violation)
            details = []
            if self.energy_constraint_active:
                details.append(f"energy <= {self.energy_cap_kwh_m2:.1f} kWh/m2")
            if self.yield_cap_active and self.yield_cap_kg_m2_year is not None:
                details.append(f"yield <= {self.yield_cap_kg_m2_year:.3f} kg/m2/year")
            raise RuntimeError(f"No candidate found for {self.mode} with {' and '.join(details)}.")
        return max(self.records, key=lambda r: r.objective - 20.0 * r.feasibility_violation)


def _robust_yield_score(
    profile: StrategyProfile,
    eval_runs: int,
    eval_seed: int,
    twin_calibration: Optional[TwinCalibration],
    energy_cap_kwh_m2: Optional[float] = None,
    yield_cap_kg_m2_year: Optional[float] = None,
) -> Dict[str, float]:
    yields: List[float] = []
    penalties: List[float] = []
    diseases: List[float] = []
    hlvds: List[float] = []
    energies: List[float] = []
    feasible_count = 0
    yield_cap_g_m2_cycle: Optional[float] = None
    if yield_cap_kg_m2_year is not None:
        cycle_days = max(float(sum(profile.stage_days.values())), 1e-9)
        yield_cap_g_m2_cycle = (float(yield_cap_kg_m2_year) * 1000.0) / (365.0 / cycle_days)

    for k in range(eval_runs):
        twin = CEADigitalTwin(
            random_seed=eval_seed + k,
            sanitation_level=0.94,
            calibration=twin_calibration,
        )
        out = twin.simulate_cycle(profile=profile, mode="max_yield")
        y = float(out.dry_yield_g_m2)
        p = float(out.penalty)
        d = float(out.disease_pressure)
        h = float(out.hlvd_pressure)
        e = float(out.energy_kwh_m2)
        yields.append(y)
        penalties.append(p)
        diseases.append(d)
        hlvds.append(h)
        energies.append(e)
        energy_ok = energy_cap_kwh_m2 is None or e <= float(energy_cap_kwh_m2)
        yield_ok = yield_cap_g_m2_cycle is None or y <= float(yield_cap_g_m2_cycle)
        feasible_count += int((p <= 15.0) and (d <= 3.0) and (h <= 0.08) and energy_ok and yield_ok)

    mean_y = float(np.mean(yields))
    p10_y = float(np.percentile(np.asarray(yields, dtype=float), 10))
    std_y = float(np.std(np.asarray(yields, dtype=float)))
    mean_p = float(np.mean(penalties))
    mean_d = float(np.mean(diseases))
    mean_h = float(np.mean(hlvds))
    mean_e = float(np.mean(energies))
    feas_rate = float(feasible_count / max(eval_runs, 1))
    excess_energy = 0.0
    if energy_cap_kwh_m2 is not None:
        excess_energy = max(0.0, mean_e - float(energy_cap_kwh_m2))
    excess_yield_cap = 0.0
    if yield_cap_g_m2_cycle is not None:
        excess_yield_cap = max(0.0, mean_y - float(yield_cap_g_m2_cycle))

    score = (
        1.00 * mean_y
        + 0.55 * p10_y
        - 0.20 * std_y
        + 420.0 * feas_rate
        - 22.0 * mean_p
        - 70.0 * mean_d
        - 1800.0 * mean_h
        - 7.5 * excess_energy
        - 8.0 * excess_yield_cap
    )
    return {
        "robust_yield_score": float(score),
        "robust_mean_yield_g_m2": mean_y,
        "robust_p10_yield_g_m2": p10_y,
        "robust_std_yield_g_m2": std_y,
        "robust_feasible_rate": feas_rate,
        "robust_mean_penalty": mean_p,
        "robust_mean_disease_pressure": mean_d,
        "robust_mean_hlvd_pressure": mean_h,
        "robust_mean_energy_kwh_m2": mean_e,
        "robust_mean_yield_excess_vs_cap_g_m2": float(excess_yield_cap),
    }


def _summary_stats(values: List[float]) -> Dict[str, float]:
    arr = np.asarray(values, dtype=float)
    return {
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "p05": float(np.percentile(arr, 5)),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
    }


def _ensemble_uncertainty(
    profile: StrategyProfile,
    mode: str,
    eval_runs: int,
    eval_seed: int,
    twin_calibration: Optional[TwinCalibration],
    energy_cap_kwh_m2: Optional[float] = None,
    yield_cap_kg_m2_year: Optional[float] = None,
) -> Dict[str, Dict[str, float] | float]:
    yields: List[float] = []
    quality: List[float] = []
    penalty: List[float] = []
    disease: List[float] = []
    hlvd: List[float] = []
    energy: List[float] = []
    feasible_count = 0
    yield_cap_g_m2_cycle: Optional[float] = None
    if yield_cap_kg_m2_year is not None:
        cycle_days = max(float(sum(profile.stage_days.values())), 1e-9)
        yield_cap_g_m2_cycle = (float(yield_cap_kg_m2_year) * 1000.0) / (365.0 / cycle_days)

    for k in range(eval_runs):
        twin = CEADigitalTwin(
            random_seed=eval_seed + 17 * k,
            sanitation_level=0.94,
            calibration=twin_calibration,
        )
        out = twin.simulate_cycle(profile=profile, mode=mode)
        yields.append(float(out.dry_yield_g_m2))
        quality.append(float(out.quality_index))
        penalty.append(float(out.penalty))
        disease.append(float(out.disease_pressure))
        hlvd.append(float(out.hlvd_pressure))
        energy.append(float(out.energy_kwh_m2))
        energy_ok = energy_cap_kwh_m2 is None or float(out.energy_kwh_m2) <= float(energy_cap_kwh_m2)
        yield_ok = yield_cap_g_m2_cycle is None or float(out.dry_yield_g_m2) <= float(yield_cap_g_m2_cycle)
        feasible_count += int((out.penalty <= 15.0) and (out.disease_pressure <= 3.0) and (out.hlvd_pressure <= 0.08) and energy_ok and yield_ok)

    return {
        "n_eval": int(eval_runs),
        "feasible_rate": float(feasible_count / max(eval_runs, 1)),
        "dry_yield_g_m2": _summary_stats(yields),
        "quality_index": _summary_stats(quality),
        "penalty": _summary_stats(penalty),
        "disease_pressure": _summary_stats(disease),
        "hlvd_pressure": _summary_stats(hlvd),
        "energy_kwh_m2": _summary_stats(energy),
    }


def _resolve_twin_calibration(args: argparse.Namespace) -> TwinCalibration:
    cached = getattr(args, "_twin_calibration", None)
    if isinstance(cached, TwinCalibration):
        return cached
    path = getattr(args, "twin_calibration_json", None)
    calibration = load_twin_calibration(path)
    try:
        setattr(args, "_twin_calibration", calibration)
    except Exception:
        pass
    return calibration


def _resolve_yield_cap(args: argparse.Namespace) -> tuple[float, float, float]:
    yield_cap_annual_kg = float(getattr(args, "yield_cap_annual_kg", DEFAULT_YIELD_CAP_ANNUAL_KG))
    farm_active_area_m2 = float(getattr(args, "farm_active_area_m2", DEFAULT_FARM_ACTIVE_AREA_M2))
    if yield_cap_annual_kg <= 0.0:
        raise ValueError("yield_cap_annual_kg must be > 0")
    if farm_active_area_m2 <= 0.0:
        raise ValueError("farm_active_area_m2 must be > 0")
    return yield_cap_annual_kg, farm_active_area_m2, (yield_cap_annual_kg / farm_active_area_m2)


def run_mode(mode: str, args: argparse.Namespace) -> Dict:
    mode_base = _base_mode(mode)
    energy_cap_kwh_m2 = float(getattr(args, "energy_cap_kwh_m2", DEFAULT_ENERGY_CAP_KWH_M2))
    if energy_cap_kwh_m2 <= 0.0:
        raise ValueError("energy_cap_kwh_m2 must be > 0")
    yield_cap_annual_kg, farm_active_area_m2, yield_cap_kg_m2_year = _resolve_yield_cap(args)

    # Stesso seed base fra modalita` per confronto piu` fair.
    base_seed = int(getattr(args, "seed", 2026))
    quality_y_min = float(getattr(args, "quality_y_min", 1300.0))
    n_init = int(getattr(args, "n_init", 24))
    n_iter = int(getattr(args, "n_iter", 30))
    pool_size = int(getattr(args, "pool_size", 2500))
    yield_restarts = int(getattr(args, "yield_restarts", 4))
    yield_robust_evals = int(getattr(args, "yield_robust_evals", 8))
    quality_restarts = int(getattr(args, "quality_restarts", 4))
    ensemble_evals = int(getattr(args, "ensemble_evals", 16))
    genetic_profile = str(getattr(args, "genetic_profile", default_genetic_profile_id()))
    cultivar_family = getattr(args, "cultivar_family", None)
    cultivar_name = str(getattr(args, "cultivar_name", ""))
    twin_calibration = _resolve_twin_calibration(args)
    run_id = new_run_id(f"opt_{mode}")

    if mode_base == "max_yield":
        candidates = []
        for r in range(yield_restarts):
            restart_seed = base_seed + 1009 * r
            opt = ConstrainedYieldBO(
                mode=mode,
                yield_floor_g_m2=quality_y_min,
                energy_cap_kwh_m2=energy_cap_kwh_m2,
                yield_cap_kg_m2_year=yield_cap_kg_m2_year,
                seed=restart_seed,
                twin_calibration=twin_calibration,
                genetic_profile_id=genetic_profile,
                cultivar_family=cultivar_family,
                cultivar_name=cultivar_name,
            )
            cand = opt.search(n_init=n_init, n_iter=n_iter, pool_size=pool_size)
            robust = _robust_yield_score(
                profile=cand.profile,
                eval_runs=yield_robust_evals,
                eval_seed=base_seed + 50000 + 100 * r,
                twin_calibration=twin_calibration,
                energy_cap_kwh_m2=(energy_cap_kwh_m2 if _is_energy_constrained_mode(mode) else None),
                yield_cap_kg_m2_year=yield_cap_kg_m2_year,
            )
            candidates.append((cand, robust, restart_seed))

        best_cand, best_robust, best_seed = max(candidates, key=lambda item: item[1]["robust_yield_score"])
        best = best_cand
        extra = {
            "restart_seed": int(best_seed),
            "yield_restarts": int(yield_restarts),
            "yield_robust_evals": int(yield_robust_evals),
            **best_robust,
        }
    else:
        quality_candidates = []
        last_error = None
        for r in range(quality_restarts):
            restart_seed = base_seed + 1009 * r
            opt = ConstrainedYieldBO(
                mode=mode,
                yield_floor_g_m2=quality_y_min,
                energy_cap_kwh_m2=energy_cap_kwh_m2,
                yield_cap_kg_m2_year=yield_cap_kg_m2_year,
                seed=restart_seed,
                twin_calibration=twin_calibration,
                genetic_profile_id=genetic_profile,
                cultivar_family=cultivar_family,
                cultivar_name=cultivar_name,
            )
            try:
                cand = opt.search(n_init=n_init, n_iter=n_iter, pool_size=pool_size)
                quality_candidates.append((cand, restart_seed))
            except RuntimeError as exc:
                last_error = exc
                continue

        if not quality_candidates:
            quality_constraints = [f"hard yield floor >= {quality_y_min:.1f} g/m2"]
            if _is_energy_constrained_mode(mode):
                quality_constraints.append(f"energy <= {energy_cap_kwh_m2:.1f} kWh/m2")
            quality_constraints.append(f"yield <= {yield_cap_kg_m2_year:.3f} kg/m2/year")
            tips = ["increasing --n-init/--n-iter/--pool-size"]
            if mode_base == "max_quality":
                tips.append("lowering --quality-y-min")
            if _is_energy_constrained_mode(mode):
                tips.append("raising --energy-cap-kwh-m2")
            tips.append("raising --yield-cap-annual-kg")
            tips.append("reducing --farm-active-area-m2")
            raise RuntimeError(
                f"{mode} failed after {quality_restarts} restarts with {' and '.join(quality_constraints)}. "
                f"Try {', '.join(tips)}."
            ) from last_error

        best, best_seed = max(quality_candidates, key=lambda item: (item[0].objective, item[0].dry_yield_g_m2))
        extra = {
            "restart_seed": int(best_seed),
            "quality_restarts": int(quality_restarts),
        }

    extra["energy_constraint_active"] = bool(_is_energy_constrained_mode(mode))
    if _is_energy_constrained_mode(mode):
        extra["energy_cap_kwh_m2"] = float(energy_cap_kwh_m2)
    extra["yield_cap_annual_kg"] = float(yield_cap_annual_kg)
    extra["farm_active_area_m2"] = float(farm_active_area_m2)
    extra["yield_cap_kg_m2_year"] = float(yield_cap_kg_m2_year)

    uncertainty = (
        _ensemble_uncertainty(
            profile=best.profile,
            mode=mode_base,
            eval_runs=ensemble_evals,
            eval_seed=base_seed + 90000 + (0 if mode_base == "max_yield" else 3000),
            twin_calibration=twin_calibration,
            energy_cap_kwh_m2=(energy_cap_kwh_m2 if _is_energy_constrained_mode(mode) else None),
            yield_cap_kg_m2_year=yield_cap_kg_m2_year,
        )
        if ensemble_evals > 0
        else {}
    )

    profile_dict = profile_to_dict(best.profile)
    calibration_dict = twin_calibration_to_dict(twin_calibration)
    derived = clone_cycle_derived_metrics(
        profile=best.profile,
        dry_yield_g_m2=best.dry_yield_g_m2,
        energy_kwh_m2=best.energy_kwh_m2,
    )
    projected_annual_yield_kg = float(derived["dry_yield_kg_m2_year"]) * float(farm_active_area_m2)
    if projected_annual_yield_kg > float(yield_cap_annual_kg) + 1e-9:
        raise RuntimeError(
            "Generated profile violates hard annual yield cap: "
            f"{projected_annual_yield_kg:.3f} kg/year > {yield_cap_annual_kg:.3f} kg/year."
        )
    derived["farm_active_area_m2"] = float(farm_active_area_m2)
    derived["projected_annual_yield_kg"] = float(projected_annual_yield_kg)
    derived["yield_cap_annual_kg"] = float(yield_cap_annual_kg)
    derived["yield_cap_respected"] = bool(projected_annual_yield_kg <= float(yield_cap_annual_kg) + 1e-9)
    outcome_dict = dict(best.outcome_dict)
    outcome_dict["derived_metrics"] = derived
    governance = {
        "run_id": run_id,
        "git_commit": git_commit_short(),
        "profile_signature": dict_signature(profile_dict),
        "calibration_signature": dict_signature(calibration_dict),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seed": int(base_seed),
        "n_init": int(n_init),
        "n_iter": int(n_iter),
        "pool_size": int(pool_size),
    }

    lit_sources = profile_literature_sources(best.profile)
    return {
        "mode": mode,
        "objective_value": best.objective,
        "feasibility_violation": best.feasibility_violation,
        "dry_yield_g_plant_est": float(derived["dry_yield_g_plant_cycle"]),
        "clone_cycle_days": float(derived["cycle_days"]),
        "flower_density_pl_m2": float(derived["flower_density_pl_m2"]),
        "energy_kwh_m2_cycle": float(derived["energy_kwh_m2_cycle"]),
        "profile": profile_dict,
        "metadata": best.profile.metadata,
        "params": best.params,
        "outcome": outcome_dict,
        "search_meta": extra,
        "genetic_profile": genetic_profile,
        "cultivar_family": str(best.profile.metadata.get("cultivar_family", "")),
        "cultivar_name": str(best.profile.metadata.get("cultivar_name", "")),
        "literature_sources": lit_sources,
        "reference_audit_summary": reference_audit_summary(lit_sources),
        "uncertainty": uncertainty,
        "constraints": {
            "yield_floor_g_m2": float(quality_y_min) if mode_base == "max_quality" else None,
            "energy_cap_kwh_m2": float(energy_cap_kwh_m2) if _is_energy_constrained_mode(mode) else None,
            "yield_cap_annual_kg": float(yield_cap_annual_kg),
            "farm_active_area_m2": float(farm_active_area_m2),
            "yield_cap_kg_m2_year": float(yield_cap_kg_m2_year),
        },
        "governance": governance,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Cannabis literature-driven optimizer (yield-first) with constrained BO. "
            "Energy can be optionally constrained with dedicated modes."
        )
    )
    parser.add_argument(
        "--mode",
        choices=[
            "max_yield",
            "max_quality",
            "max_yield_energy",
            "max_quality_energy",
            "both",
            "both_energy",
            "all",
        ],
        default="both",
    )
    parser.add_argument(
        "--quality-y-min",
        type=float,
        default=1300.0,
        help="Yield floor for max_quality/max_quality_energy modes.",
    )
    parser.add_argument(
        "--energy-cap-kwh-m2",
        type=float,
        default=DEFAULT_ENERGY_CAP_KWH_M2,
        help="Hard energy cap (kWh/m2 per cycle) used by *_energy modes.",
    )
    parser.add_argument(
        "--yield-cap-annual-kg",
        type=float,
        default=DEFAULT_YIELD_CAP_ANNUAL_KG,
        help="Hard annual yield cap (kg/year) at farm level.",
    )
    parser.add_argument(
        "--farm-active-area-m2",
        type=float,
        default=DEFAULT_FARM_ACTIVE_AREA_M2,
        help="Active productive farm area (m2) used to convert annual cap into kg/m2/year.",
    )
    parser.add_argument("--n-init", type=int, default=24)
    parser.add_argument("--n-iter", type=int, default=30)
    parser.add_argument("--pool-size", type=int, default=2500)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument(
        "--genetic-profile",
        choices=available_genetic_profiles(),
        default=default_genetic_profile_id(),
        help="Genetic profile for bounds/model customization.",
    )
    parser.add_argument(
        "--cultivar-family",
        choices=available_cultivar_families(),
        default=None,
        help="Optional cultivar family prior (hybrid/sativa_dominant/indica_dominant).",
    )
    parser.add_argument("--cultivar-name", default="", help="Optional cultivar tag stored in profile metadata.")
    parser.add_argument("--yield-restarts", type=int, default=4, help="Only for max_yield: BO restarts, best robust profile is selected.")
    parser.add_argument("--yield-robust-evals", type=int, default=8, help="Only for max_yield: Monte Carlo evals used to choose best restart.")
    parser.add_argument(
        "--quality-restarts",
        type=int,
        default=4,
        help="Only for max_quality/max_quality_energy: restart attempts to satisfy hard constraints.",
    )
    parser.add_argument("--ensemble-evals", type=int, default=16, help="Uncertainty estimation runs on final profile (0 disables).")
    parser.add_argument("--twin-calibration-json", default=None, help="Optional twin calibration JSON produced by calibrate_twin.py.")
    parser.add_argument("--store-db", default=None, help="Optional SQLite path for persistent telemetry storage.")
    parser.add_argument("--json-only", action="store_true")
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

    if args.mode == "both":
        modes = ["max_yield", "max_quality"]
    elif args.mode == "both_energy":
        modes = ["max_yield_energy", "max_quality_energy"]
    elif args.mode == "all":
        modes = ["max_yield", "max_quality", "max_yield_energy", "max_quality_energy"]
    else:
        modes = [args.mode]
    payload = {"results": [run_mode(mode=m, args=args) for m in modes]}

    if args.store_db:
        init_storage(args.store_db)
        ts = datetime.now().isoformat(timespec="seconds")
        for r in payload["results"]:
            store_optimizer_run(db_path=args.store_db, result=r, ts=ts)

    if args.json_only:
        print(json.dumps(payload, indent=2))
        return

    for r in payload["results"]:
        o = r["outcome"]
        energy_constrained = bool((r.get("search_meta") or {}).get("energy_constraint_active", False))
        mode_note = "literature-driven, no energy objective"
        if energy_constrained:
            cap = float((r.get("search_meta") or {}).get("energy_cap_kwh_m2", DEFAULT_ENERGY_CAP_KWH_M2))
            mode_note = f"literature-driven, hard energy cap <= {cap:.1f} kWh/m2"
        print(f"\n=== {r['mode']} ({mode_note}) ===")
        print(f"Objective value:        {r['objective_value']:.2f}")
        print(f"Feasibility violation:  {r['feasibility_violation']:.3f}")
        print(f"Dry yield (g/m2):       {o['dry_yield_g_m2']:.2f}")
        dm = o.get("derived_metrics", {})
        if dm:
            print(f"Projected annual yield: {dm.get('projected_annual_yield_kg', 0.0):.2f} kg/year")
            print(f"Yield cap annual:       {dm.get('yield_cap_annual_kg', 0.0):.2f} kg/year")
        print(f"Quality index:          {o['quality_index']:.2f}")
        print(f"Energy (kWh/m2):        {o['energy_kwh_m2']:.2f}")
        print(f"Penalty:                {o['penalty']:.2f}")
        print(f"Disease pressure:       {o['disease_pressure']:.3f}")
        u = r.get("uncertainty", {})
        if u:
            y_u = u.get("dry_yield_g_m2", {})
            print(
                "Uncertainty yield (p05/p50/p95): "
                f"{y_u.get('p05', 0.0):.1f} / {y_u.get('p50', 0.0):.1f} / {y_u.get('p95', 0.0):.1f}"
            )
        print("Top adaptive actions:")
        print(json.dumps(o["adjustment_summary"], indent=2))

    print("\nFull payload:")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
