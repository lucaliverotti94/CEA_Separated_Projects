from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
import argparse
import json

import numpy as np
from scipy.optimize import minimize

from core.genetics import (
    available_cultivar_families,
    default_cultivar_family,
    validate_profile_cultivar_args,
)
from core.governance import dict_signature, file_signature, git_commit_short, new_run_id
from core.model import (
    CEADigitalTwin,
    StrategyProfile,
    TwinCalibration,
    clamp_twin_calibration,
    twin_calibration_to_dict,
)
from core.realtime_io import _profile_from_export_dict, load_profile
from core.storage import init_storage, store_twin_calibration


METRIC_WEIGHTS = {
    "dry_yield_g_m2": 4.0,
    "quality_index": 2.0,
    "penalty": 1.5,
    "disease_pressure": 1.3,
    "hlvd_pressure": 1.3,
    "energy_kwh_m2": 0.8,
}


@dataclass
class CycleCase:
    case_id: str
    mode: str
    profile: StrategyProfile
    observed: Dict[str, float]
    seed: int
    sanitation_level: float
    cultivar_family: str
    cultivar_name: str
    context: Dict[str, str | float | bool]


PARAM_NAMES = [
    "yield_gain_scale",
    "quality_gain_scale",
    "transpiration_scale",
    "disease_inc_scale",
    "hlvd_inc_scale",
    "penalty_scale",
    "energy_scale",
    "yield_post_scale",
    "quality_post_scale",
    "quality_post_offset",
]

PARAM_BOUNDS = [
    (0.60, 1.60),
    (0.60, 1.60),
    (0.60, 1.60),
    (0.50, 2.00),
    (0.50, 2.00),
    (0.50, 2.50),
    (0.60, 1.80),
    (0.70, 1.30),
    (0.70, 1.30),
    (-20.0, 20.0),
]

FAMILY_NAMES = available_cultivar_families()
FAMILY_PARAM_KEYS = [
    "yield_potential_scale",
    "quality_potential_scale",
    "disease_pressure_scale",
    "hlvd_pressure_scale",
    "nutrient_window_scale",
    "flower_duration_scale",
    "dli_demand_scale",
]
FAMILY_PARAM_BOUNDS = {
    "yield_potential_scale": (0.80, 1.25),
    "quality_potential_scale": (0.80, 1.25),
    "disease_pressure_scale": (0.75, 1.35),
    "hlvd_pressure_scale": (0.75, 1.35),
    "nutrient_window_scale": (0.75, 1.35),
    "flower_duration_scale": (0.85, 1.20),
    "dli_demand_scale": (0.85, 1.20),
}


def _family_param_names() -> List[str]:
    names: List[str] = []
    for fam in FAMILY_NAMES:
        for key in FAMILY_PARAM_KEYS:
            names.append(f"family__{fam}__{key}")
    return names


def _family_param_bounds() -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for _fam in FAMILY_NAMES:
        for key in FAMILY_PARAM_KEYS:
            out.append(FAMILY_PARAM_BOUNDS[key])
    return out


def _calibration_from_x(x: np.ndarray) -> TwinCalibration:
    row = {k: float(x[i]) for i, k in enumerate(PARAM_NAMES)}
    return clamp_twin_calibration(TwinCalibration(**row))


def _x_from_calibration(cal: TwinCalibration) -> np.ndarray:
    row = twin_calibration_to_dict(cal)
    return np.asarray([float(row[k]) for k in PARAM_NAMES], dtype=float)


def _family_scaling_from_x(x: np.ndarray) -> Dict[str, Dict[str, float]]:
    names = _family_param_names()
    if len(x) != len(names):
        raise ValueError(f"Invalid family scaling vector length: {len(x)} expected {len(names)}")
    out: Dict[str, Dict[str, float]] = {fam: {} for fam in FAMILY_NAMES}
    for i, full_name in enumerate(names):
        _, fam, key = full_name.split("__", 2)
        out[fam][key] = float(x[i])
    return out


def _flatten_family_scaling(scaling: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    flat: Dict[str, float] = {}
    for fam in FAMILY_NAMES:
        row = scaling.get(fam, {})
        for key in FAMILY_PARAM_KEYS:
            flat[f"family__{fam}__{key}"] = float(row.get(key, 1.0))
    return flat


def _profile_with_family_scaling(
    profile: StrategyProfile,
    cultivar_family: str,
    scaling: Dict[str, Dict[str, float]] | None,
) -> StrategyProfile:
    if not scaling:
        return profile
    family_scale = scaling.get(cultivar_family, {})
    if not family_scale:
        return profile

    metadata = dict(profile.metadata)
    for key in FAMILY_PARAM_KEYS:
        scale = float(family_scale.get(key, 1.0))
        meta_key = f"genetics_family_{key}"
        current = float(metadata.get(meta_key, 1.0))
        metadata[meta_key] = current * scale
    metadata["calibration_family_scaling"] = True
    return StrategyProfile(
        stage_days=dict(profile.stage_days),
        stage_setpoints=dict(profile.stage_setpoints),
        metadata=metadata,
    )


def _extract_metrics(outcome) -> Dict[str, float]:
    return {
        "dry_yield_g_m2": float(outcome.dry_yield_g_m2),
        "quality_index": float(outcome.quality_index),
        "penalty": float(outcome.penalty),
        "disease_pressure": float(outcome.disease_pressure),
        "hlvd_pressure": float(outcome.hlvd_pressure),
        "energy_kwh_m2": float(outcome.energy_kwh_m2),
    }


def _case_loss(pred: Dict[str, float], obs: Dict[str, float]) -> float:
    weighted = 0.0
    total_w = 0.0
    for k, w in METRIC_WEIGHTS.items():
        if k not in obs:
            continue
        y = float(obs[k])
        yhat = float(pred[k])
        denom = max(abs(y), 1.0)
        e = (yhat - y) / denom
        weighted += w * (e * e)
        total_w += w
    if total_w <= 0.0:
        return 0.0
    return float(weighted / total_w)


def _evaluate_cases(
    calibration: TwinCalibration,
    cases: List[CycleCase],
    family_scaling: Dict[str, Dict[str, float]] | None = None,
) -> Tuple[float, List[Dict]]:
    losses: List[float] = []
    details: List[Dict] = []
    for c in cases:
        profile = _profile_with_family_scaling(
            profile=c.profile,
            cultivar_family=c.cultivar_family,
            scaling=family_scaling,
        )
        twin = CEADigitalTwin(
            random_seed=c.seed,
            sanitation_level=c.sanitation_level,
            calibration=calibration,
        )
        out = twin.simulate_cycle(profile=profile, mode=c.mode)
        pred = _extract_metrics(out)
        loss = _case_loss(pred=pred, obs=c.observed)
        losses.append(loss)
        details.append(
            {
                "case_id": c.case_id,
                "mode": c.mode,
                "seed": c.seed,
                "sanitation_level": c.sanitation_level,
                "cultivar_family": c.cultivar_family,
                "cultivar_name": c.cultivar_name,
                "context": c.context,
                "loss": loss,
                "observed": c.observed,
                "predicted": pred,
            }
        )
    mean_loss = float(np.mean(losses)) if losses else 0.0
    return mean_loss, details


def _metric_stats_from_details(details: List[Dict]) -> Dict[str, Dict[str, float | None]]:
    metrics = list(METRIC_WEIGHTS.keys())
    out: Dict[str, Dict[str, float | None]] = {}
    for m in metrics:
        obs_vals: List[float] = []
        pred_vals: List[float] = []
        for row in details:
            obs = row.get("observed", {})
            pred = row.get("predicted", {})
            if m in obs and m in pred:
                obs_vals.append(float(obs[m]))
                pred_vals.append(float(pred[m]))
        n = len(obs_vals)
        if n == 0:
            out[m] = {
                "n": 0.0,
                "mae": None,
                "rmse": None,
                "mape_pct": None,
                "bias": None,
                "r2": None,
            }
            continue
        obs_arr = np.asarray(obs_vals, dtype=float)
        pred_arr = np.asarray(pred_vals, dtype=float)
        err = pred_arr - obs_arr
        mae = float(np.mean(np.abs(err)))
        rmse = float(np.sqrt(np.mean(err * err)))
        denom = np.maximum(np.abs(obs_arr), 1e-9)
        mape = float(np.mean(np.abs(err) / denom) * 100.0)
        bias = float(np.mean(err))
        ss_res = float(np.sum(err * err))
        ss_tot = float(np.sum((obs_arr - np.mean(obs_arr)) ** 2))
        r2 = None if ss_tot <= 1e-12 else float(1.0 - ss_res / ss_tot)
        out[m] = {
            "n": float(n),
            "mae": mae,
            "rmse": rmse,
            "mape_pct": mape,
            "bias": bias,
            "r2": r2,
        }
    return out


def _bootstrap_ci_mean(values: List[float], n_resamples: int, seed: int) -> Dict[str, float] | None:
    if len(values) < 2 or n_resamples <= 0:
        return None
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    samples = []
    n = len(arr)
    for _ in range(int(n_resamples)):
        idx = rng.integers(0, n, size=n)
        samples.append(float(np.mean(arr[idx])))
    q = np.percentile(np.asarray(samples, dtype=float), [2.5, 50.0, 97.5])
    return {"p02_5": float(q[0]), "p50": float(q[1]), "p97_5": float(q[2])}


def _split_loss_values(details: List[Dict]) -> List[float]:
    out: List[float] = []
    for row in details:
        if "loss" in row:
            out.append(float(row["loss"]))
    return out


def _split_cases(cases: List[CycleCase], val_ratio: float, seed: int) -> Tuple[List[CycleCase], List[CycleCase]]:
    n = len(cases)
    if n <= 1 or val_ratio <= 0.0:
        return cases, []
    idx = np.arange(n, dtype=int)
    rng = np.random.default_rng(seed)
    rng.shuffle(idx)
    val_n = int(round(n * val_ratio))
    val_n = min(max(val_n, 1), max(n - 1, 1))
    val_idx = set(int(i) for i in idx[:val_n])
    train = [c for j, c in enumerate(cases) if j not in val_idx]
    val = [c for j, c in enumerate(cases) if j in val_idx]
    return train, val


def _load_case(item: Dict, i: int, dataset_dir: Path, default_seed: int) -> CycleCase:
    mode = str(item.get("mode", "max_yield"))
    if mode not in {"max_yield", "max_quality"}:
        raise ValueError(f"Invalid mode for cycle #{i}: {mode}")

    if "profile_json" in item:
        p = Path(item["profile_json"])
        if not p.is_absolute():
            p = (dataset_dir / p).resolve()
        profile = load_profile(mode=mode, profile_json=str(p))
    elif "profile" in item and isinstance(item["profile"], dict):
        profile = _profile_from_export_dict(item["profile"])
    else:
        raise ValueError(f"Cycle #{i} must provide 'profile_json' or inline 'profile'.")

    observed_raw = item.get("observed")
    if not isinstance(observed_raw, dict) or not observed_raw:
        raise ValueError(f"Cycle #{i} requires non-empty 'observed' dict.")
    observed = {str(k): float(v) for k, v in observed_raw.items() if k in METRIC_WEIGHTS}
    if not observed:
        raise ValueError(f"Cycle #{i}: no supported observed metrics found.")

    raw_profile_id = str(profile.metadata.get("genetic_profile_id", ""))
    raw_family = item.get("cultivar_family", profile.metadata.get("cultivar_family", default_cultivar_family()))
    raw_name = item.get("cultivar_name", profile.metadata.get("cultivar_name", ""))
    norm_profile_id, norm_family, prior = validate_profile_cultivar_args(
        profile_id=raw_profile_id if raw_profile_id else None,
        cultivar_family=str(raw_family) if raw_family is not None else None,
        cultivar_name=str(raw_name) if raw_name is not None else None,
    )
    cultivar_name = prior.name if prior is not None else str(raw_name or "").strip()

    context: Dict[str, str | float | bool] = {}
    for key in (
        "system_type",
        "hydro_subsystem",
        "area_m2",
        "plant_density_pl_m2",
        "recirculation_l_h",
        "source_water_ec_ms_cm",
        "source_water_ph",
        "sensor_qc_score",
        "measurement_protocol",
        "notes",
    ):
        if key in item:
            val = item[key]
            if isinstance(val, bool):
                context[key] = bool(val)
            elif isinstance(val, (int, float)):
                context[key] = float(val)
            else:
                context[key] = str(val)

    profile.metadata["genetic_profile_id"] = norm_profile_id
    profile.metadata["cultivar_family"] = norm_family
    if cultivar_name:
        profile.metadata["cultivar_name"] = cultivar_name

    return CycleCase(
        case_id=str(item.get("id", f"cycle_{i:03d}")),
        mode=mode,
        profile=profile,
        observed=observed,
        seed=int(item.get("seed", default_seed + 137 * i)),
        sanitation_level=float(item.get("sanitation_level", 0.94)),
        cultivar_family=norm_family,
        cultivar_name=cultivar_name or "unspecified",
        context=context,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate CEA digital twin on real/historical cycle outcomes. "
            "Input JSON must contain a 'cycles' list."
        )
    )
    parser.add_argument("--dataset-json", required=True, help="Path to calibration dataset JSON.")
    parser.add_argument("--out-json", default="runtime/profiles/twin_calibration.json", help="Output calibration JSON.")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--restarts", type=int, default=6, help="Number of optimization restarts.")
    parser.add_argument("--maxiter", type=int, default=260, help="Max L-BFGS-B iterations per restart.")
    parser.add_argument("--val-ratio", type=float, default=0.2, help="Validation split ratio in [0, 0.8].")
    parser.add_argument(
        "--bootstrap-resamples",
        type=int,
        default=200,
        help="Bootstrap resamples for confidence intervals on mean loss (0 disables).",
    )
    parser.add_argument(
        "--calibrate-family-coeffs",
        action="store_true",
        help="Also calibrate cultivar-family multipliers on top of twin calibration scalers.",
    )
    parser.add_argument(
        "--family-regularization",
        type=float,
        default=0.03,
        help="L2 regularization strength for family multipliers around 1.0.",
    )
    parser.add_argument(
        "--validation-min-cases",
        type=int,
        default=3,
        help="Minimum validation cases required to consider holdout validation statistically informative.",
    )
    parser.add_argument("--name", default="twin_calibration_v1", help="Calibration label stored in metadata.")
    parser.add_argument("--store-db", default="runtime/db/cea_timeseries.db", help="SQLite path where calibration is logged.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset_json).resolve()
    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    rows = raw.get("cycles")
    if not isinstance(rows, list) or not rows:
        raise ValueError("dataset-json must contain non-empty 'cycles' list.")

    cases = [_load_case(item=row, i=i + 1, dataset_dir=dataset_path.parent, default_seed=args.seed) for i, row in enumerate(rows)]
    train_cases, val_cases = _split_cases(cases=cases, val_ratio=float(args.val_ratio), seed=int(args.seed))
    n_twin_params = len(PARAM_NAMES)
    fam_names = _family_param_names() if args.calibrate_family_coeffs else []
    fam_bounds = _family_param_bounds() if args.calibrate_family_coeffs else []
    all_param_names = list(PARAM_NAMES) + list(fam_names)
    all_bounds = list(PARAM_BOUNDS) + list(fam_bounds)

    def split_vector(x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        x = np.asarray(x, dtype=float)
        twin_x = x[:n_twin_params]
        fam_x = x[n_twin_params:]
        return twin_x, fam_x

    def objective(x: np.ndarray) -> float:
        twin_x, fam_x = split_vector(x)
        calibration = _calibration_from_x(twin_x)
        fam_scaling = _family_scaling_from_x(fam_x) if args.calibrate_family_coeffs else None
        loss, _ = _evaluate_cases(
            calibration=calibration,
            cases=train_cases,
            family_scaling=fam_scaling,
        )
        if args.calibrate_family_coeffs and fam_x.size > 0:
            reg = float(args.family_regularization) * float(np.mean((fam_x - 1.0) ** 2))
            loss += reg
        return float(loss)

    rng = np.random.default_rng(int(args.seed))
    twin_default = _x_from_calibration(TwinCalibration())
    if args.calibrate_family_coeffs:
        fam_default = np.ones(len(fam_names), dtype=float)
        x_default = np.concatenate([twin_default, fam_default], axis=0)
    else:
        x_default = twin_default
    best_res = None

    for r in range(max(int(args.restarts), 1)):
        if r == 0:
            x0 = x_default
        else:
            x0 = np.asarray([rng.uniform(lo, hi) for lo, hi in all_bounds], dtype=float)

        res = minimize(
            objective,
            x0=x0,
            method="L-BFGS-B",
            bounds=all_bounds,
            options={"maxiter": int(args.maxiter)},
        )
        if (best_res is None) or (float(res.fun) < float(best_res.fun)):
            best_res = res

    assert best_res is not None
    best_vec = np.asarray(best_res.x, dtype=float)
    best_twin_x, best_fam_x = split_vector(best_vec)
    best_cal = _calibration_from_x(best_twin_x)
    best_fam_scaling = _family_scaling_from_x(best_fam_x) if args.calibrate_family_coeffs else None
    train_loss, train_details = _evaluate_cases(
        calibration=best_cal,
        cases=train_cases,
        family_scaling=best_fam_scaling,
    )
    val_loss, val_details = _evaluate_cases(
        calibration=best_cal,
        cases=val_cases,
        family_scaling=best_fam_scaling,
    )

    train_metric_stats = _metric_stats_from_details(train_details)
    val_metric_stats = _metric_stats_from_details(val_details)
    train_loss_values = _split_loss_values(train_details)
    val_loss_values = _split_loss_values(val_details)
    train_loss_ci = _bootstrap_ci_mean(
        values=train_loss_values,
        n_resamples=int(args.bootstrap_resamples),
        seed=int(args.seed) + 7001,
    )
    val_loss_ci = _bootstrap_ci_mean(
        values=val_loss_values,
        n_resamples=int(args.bootstrap_resamples),
        seed=int(args.seed) + 7009,
    )

    by_mode: Dict[str, int] = {}
    by_family: Dict[str, int] = {}
    for c in cases:
        by_mode[c.mode] = int(by_mode.get(c.mode, 0) + 1)
        by_family[c.cultivar_family] = int(by_family.get(c.cultivar_family, 0) + 1)

    validation_ok = (len(val_cases) >= int(args.validation_min_cases)) if val_cases else False
    governance = {
        "run_id": new_run_id("cal"),
        "git_commit": git_commit_short(),
        "dataset_signature": file_signature(dataset_path),
        "calibration_signature": dict_signature(twin_calibration_to_dict(best_cal)),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "name": args.name,
        "dataset_path": str(dataset_path),
        "n_cycles": len(cases),
        "train_size": len(train_cases),
        "val_size": len(val_cases),
        "optimization": {
            "method": "L-BFGS-B",
            "restarts": int(args.restarts),
            "maxiter": int(args.maxiter),
            "seed": int(args.seed),
            "n_parameters": int(len(all_param_names)),
            "best_train_objective": float(best_res.fun),
            "success": bool(best_res.success),
            "message": str(best_res.message),
        },
        "fit": {
            "train_loss": float(train_loss),
            "val_loss": float(val_loss) if val_cases else None,
            "train_loss_ci95": train_loss_ci,
            "val_loss_ci95": val_loss_ci,
            "train_metric_stats": train_metric_stats,
            "val_metric_stats": val_metric_stats,
            "validation_min_cases": int(args.validation_min_cases),
            "validation_statistically_informative": bool(validation_ok),
        },
        "dataset_summary": {
            "by_mode": by_mode,
            "by_cultivar_family": by_family,
        },
        "calibration": twin_calibration_to_dict(best_cal),
        "family_calibration": {
            "enabled": bool(args.calibrate_family_coeffs),
            "regularization": float(args.family_regularization),
            "multipliers": best_fam_scaling if args.calibrate_family_coeffs else {},
        },
        "governance": governance,
        "bounds": {all_param_names[i]: [float(all_bounds[i][0]), float(all_bounds[i][1])] for i in range(len(all_param_names))},
        "train_cases": train_details,
        "val_cases": val_details,
    }

    out_path = Path(args.out_json).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.store_db:
        init_storage(args.store_db)
        store_twin_calibration(
            db_path=args.store_db,
            ts=payload["generated_at"],
            payload=payload,
            name=args.name,
            train_loss=payload["fit"]["train_loss"],
            val_loss=payload["fit"]["val_loss"],
        )

    print(str(out_path))
    print(
        json.dumps(
            {
                "train_loss": payload["fit"]["train_loss"],
                "val_loss": payload["fit"]["val_loss"],
                "n_cycles": payload["n_cycles"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
