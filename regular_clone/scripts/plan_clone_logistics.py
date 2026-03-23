from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[1]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from core.production_planner import PlannerInput, build_clone_logistics_plan


def _render_markdown(plan: dict) -> str:
    area = plan["area_plan_m2"]
    weekly = plan["weekly_clone_plan"]
    lines = [
        "# Piano logistico talee regular",
        "",
        "## Target",
        f"- Produzione annua: {plan['annual_targets']['total_kg']:.1f} kg infiorescenza secca market-ready",
        f"- Mix indica/sativa: {plan['inputs']['mix_indica']:.2f}/{plan['inputs']['mix_sativa']:.2f}",
        "",
        "## Area capacity (m2)",
        f"- Propagazione: {area['capacity_with_margin']['propagation']:.2f}",
        f"- Vegetativa: {area['capacity_with_margin']['vegetative']:.2f}",
        f"- Transition: {area['capacity_with_margin']['transition']:.2f}",
        f"- Fioritura: {area['capacity_with_margin']['flower']:.2f}",
        f"- Totale coltivazione attiva: {area['total_active_cultivation_capacity_m2']:.2f}",
        "",
        "## Piano settimanale talee",
        f"- Finestre/settimana: {weekly['cadence_windows_per_week']}",
        f"- Talee staccate indica: {weekly['detached_cuttings_per_week']['indica_dominant']}",
        f"- Talee staccate sativa: {weekly['detached_cuttings_per_week']['sativa_dominant']}",
        f"- Totale talee staccate: {weekly['detached_cuttings_per_week']['total']}",
        f"- Totale attese radicate: {weekly['expected_rooted_per_week']['total']:.2f}",
        f"- Produzione annua stimata dal piano: {weekly['projected_annual_yield_kg_from_schedule']:.2f} kg/anno",
        f"- Rebalance cap resa applicato: {weekly['yield_cap_rebalance_applied']}",
        "",
        "## Saturazione",
        f"- Soglia blocco: {100.0 * area['saturation_threshold']:.1f}%",
        f"- Propagazione: {100.0 * area['saturation_ratio']['propagation']:.1f}%",
        f"- Vegetativa: {100.0 * area['saturation_ratio']['vegetative']:.1f}%",
        f"- Transition: {100.0 * area['saturation_ratio']['transition']:.1f}%",
        f"- Fioritura: {100.0 * area['saturation_ratio']['flower']:.1f}%",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone-cycle logistics planner for regular photoperiodic CEA.")
    parser.add_argument("--target-annual-kg", type=float, default=80.0)
    parser.add_argument("--target-yield-kg-m2-cycle", type=float, default=0.35)
    parser.add_argument("--mix-indica", type=float, default=0.50)
    parser.add_argument("--mix-sativa", type=float, default=0.50)
    parser.add_argument("--rooting-rate", type=float, default=0.85)
    parser.add_argument("--cuttings-per-plant", type=float, default=5.0)
    parser.add_argument("--windows-per-week", type=int, default=2)
    parser.add_argument("--safety-margin", type=float, default=0.20)
    parser.add_argument("--saturation-threshold", type=float, default=0.85)
    parser.add_argument("--out-json", default="", help="Optional path to save full JSON plan.")
    parser.add_argument("--out-md", default="", help="Optional path to save markdown summary.")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    cfg = PlannerInput(
        target_annual_kg=args.target_annual_kg,
        target_yield_kg_m2_cycle=args.target_yield_kg_m2_cycle,
        mix_indica=args.mix_indica,
        mix_sativa=args.mix_sativa,
        rooting_rate=args.rooting_rate,
        cuttings_per_vegetative_plant=args.cuttings_per_plant,
        cuttings_windows_per_week=args.windows_per_week,
        safety_margin=args.safety_margin,
        saturation_threshold=args.saturation_threshold,
    )
    plan = build_clone_logistics_plan(cfg)

    if args.out_json:
        Path(args.out_json).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    md = _render_markdown(plan)
    if args.out_md:
        Path(args.out_md).write_text(md, encoding="utf-8")

    if args.json_only:
        print(json.dumps(plan, indent=2))
        return

    print(md)
    print("Full JSON:")
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
