from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import argparse
import json
import sys

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[1]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from core.genetics import available_cultivars, get_cultivar_prior
from optimizer_literature_best import run_mode


def main() -> None:
    parser = argparse.ArgumentParser(description="Recalculate Top10 regular cultivar profiles with hard cycle constraints.")
    parser.add_argument("--mode", choices=["max_yield", "max_quality", "both"], default="both")
    parser.add_argument("--n-init", type=int, default=6)
    parser.add_argument("--n-iter", type=int, default=4)
    parser.add_argument("--pool-size", type=int, default=300)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--quality-y-min", type=float, default=900.0)
    parser.add_argument("--out-json", default="")
    args = parser.parse_args()

    modes = [args.mode] if args.mode != "both" else ["max_yield", "max_quality"]
    cultivars = list(available_cultivars())
    rows = []
    for cultivar_name in cultivars:
        prior = get_cultivar_prior(cultivar_name)
        family = prior.family if prior is not None else "indica_dominant"
        item = {
            "cultivar_name": cultivar_name,
            "cultivar_family": family,
            "results": {},
        }
        for mode in modes:
            run_args = SimpleNamespace(
                seed=args.seed,
                quality_y_min=args.quality_y_min,
                n_init=args.n_init,
                n_iter=args.n_iter,
                pool_size=args.pool_size,
                yield_restarts=1,
                yield_robust_evals=2,
                quality_restarts=1,
                ensemble_evals=2,
                twin_calibration_json=None,
                genetic_profile="regular_photoperiodic",
                cultivar_family=family,
                cultivar_name=cultivar_name,
                energy_cap_kwh_m2=700.0,
            )
            item["results"][mode] = run_mode(mode=mode, args=run_args)
        rows.append(item)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "genetic_profile": "regular_photoperiodic",
        "hard_cycle_constraints": {
            "indica_dominant_total_days": 105,
            "sativa_dominant_total_days": 120,
            "indica_density_pl_m2": 4.0,
            "sativa_density_pl_m2": 2.0,
        },
        "cultivars": rows,
    }

    out_path = args.out_json or f"top10_regular_profiles_{datetime.now().strftime('%Y%m%d')}.json"
    Path(out_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Saved recalculated profiles: {out_path}")


if __name__ == "__main__":
    main()

