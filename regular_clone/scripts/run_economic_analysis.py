from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[1]
    _ECON = _ROOT / "economics"
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    if str(_ECON) not in sys.path:
        sys.path.insert(0, str(_ECON))

import cea_economic_analysis as econ


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run project-aligned economic analysis for regular_clone.")
    parser.add_argument("--target-annual-kg", type=float, default=80.0)
    parser.add_argument("--price-eur-g", type=float, default=4.0)
    parser.add_argument("--mix-indica", type=float, default=0.5)
    parser.add_argument("--mix-sativa", type=float, default=0.5)
    parser.add_argument("--target-yield-kg-m2-cycle", type=float, default=0.35)
    parser.add_argument("--energy-cap-kwh-m2-cycle", type=float, default=700.0)
    parser.add_argument("--economic-yield-basis-policy", choices=["planned", "target"], default="target")
    parser.add_argument(
        "--infrastructure-profile",
        choices=["startup_low_capex", "industrial_full"],
        default="startup_low_capex",
    )
    parser.add_argument(
        "--energy-architecture",
        choices=["grid_only_retrofit", "hybrid_small", "hybrid_full"],
        default="grid_only_retrofit",
    )
    parser.add_argument(
        "--monitoring-tier",
        choices=["core_efficiency_extended", "full"],
        default="core_efficiency_extended",
    )
    parser.add_argument("--quality-floor", type=float, default=62.0)
    parser.add_argument("--yield-source", choices=["optimizer", "manual"], default="optimizer")
    parser.add_argument("--manual-quality-index", type=float, default=64.0)
    parser.add_argument("--optimizer-mode", choices=["max_yield", "max_yield_energy"], default="max_yield_energy")
    parser.add_argument("--optimizer-n-init", type=int, default=8)
    parser.add_argument("--optimizer-n-iter", type=int, default=6)
    parser.add_argument("--optimizer-pool-size", type=int, default=240)
    parser.add_argument("--optimizer-seed", type=int, default=2026)
    parser.add_argument("--out-json", default="runtime/logs/economic_analysis_project.json")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = econ.project_case(
        target_annual_kg=float(args.target_annual_kg),
        price_eur_g=float(args.price_eur_g),
        mix_indica=float(args.mix_indica),
        mix_sativa=float(args.mix_sativa),
        target_yield_kg_m2_cycle=float(args.target_yield_kg_m2_cycle),
        energy_cap_kwh_m2_cycle=float(args.energy_cap_kwh_m2_cycle),
        economic_yield_basis_policy=str(args.economic_yield_basis_policy),
        infrastructure_profile=str(args.infrastructure_profile),
        energy_architecture=str(args.energy_architecture),
        monitoring_tier=str(args.monitoring_tier),
        quality_floor=float(args.quality_floor),
        yield_source=str(args.yield_source),
        manual_quality_index=float(args.manual_quality_index),
        optimizer_mode=str(args.optimizer_mode),
        optimizer_n_init=int(args.optimizer_n_init),
        optimizer_n_iter=int(args.optimizer_n_iter),
        optimizer_pool_size=int(args.optimizer_pool_size),
        optimizer_seed=int(args.optimizer_seed),
    )

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_only:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print("Analisi economica completata")
    sel = out.get("selected_configuration", {})
    print(
        "- selected_configuration: "
        f"{sel.get('infrastructure_profile')}/{sel.get('energy_architecture')}/{sel.get('monitoring_tier')}"
    )
    print(f"- constraints_satisfied: {out.get('constraints_satisfied', {})}")
    print(f"- target_annual_kg: {out['target_annual_kg']:.2f} kg/anno")
    print(f"- plan_projected_annual_yield_kg: {out['plan_projected_annual_yield_kg']:.2f} kg/anno")
    print(f"- target_vs_planned_kg: {out['target_vs_planned_kg']:.2f} kg/anno")
    print(f"- economic_yield_basis_policy: {out['economic_yield_basis_policy']}")
    print(f"- economic_yield_basis_kg: {out['economic_yield_basis_kg']:.2f} kg/anno")
    print(f"- annual_revenue_eur: {out['annual_revenue_eur']:.2f} EUR/anno")
    print(f"- opex_total_annual: {out['opex_total_annual']:.2f} EUR/anno")
    print(f"- ebitda_annual_eur: {out['ebitda_annual_eur']:.2f} EUR/anno")
    print(f"- roi_annual_pct: {out['roi_annual_pct']:.2f}%")
    if out["simple_payback_years"] is None:
        print("- simple_payback_years: n/a (EBITDA <= 0)")
    else:
        print(f"- simple_payback_years: {out['simple_payback_years']:.2f} anni")
    print(f"- out_json: {out_path}")


if __name__ == "__main__":
    main()
