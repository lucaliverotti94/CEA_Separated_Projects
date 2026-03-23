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
    )

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_only:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print("Analisi economica completata")
    print(f"- target_annual_kg: {out['target_annual_kg']:.2f} kg/anno")
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
