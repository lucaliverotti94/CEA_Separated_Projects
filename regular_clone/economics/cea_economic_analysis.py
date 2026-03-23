from __future__ import annotations

from itertools import product
from types import SimpleNamespace
from typing import Dict, Iterable, List, Tuple

R_KG_M2_CYCLE = 2.0
T_CYCLE_BASE_DAYS = 112.0
E_M2_CYCLE_BASE = 700.0
E_M2_CYCLE_MAX = 700.0

FAMILY_MULTIPLIERS = {
    "hybrid": {"energy": 1.0, "cycle_days": 1.0},
    "indica_dominant": {"energy": 0.907, "cycle_days": 105.0 / 112.0},
    "sativa_dominant": {"energy": 1.235, "cycle_days": 120.0 / 112.0},
}

DEFAULT_QUALITY_FLOOR = 62.0
DEFAULT_INFRASTRUCTURE_PROFILE = "startup_low_capex"
DEFAULT_ENERGY_ARCHITECTURE = "grid_only_retrofit"
DEFAULT_MONITORING_TIER = "core_efficiency_extended"
DEFAULT_YIELD_SOURCE = "manual"

INFRASTRUCTURE_CATALOG: Dict[str, Dict[str, float]] = {
    "startup_low_capex": {
        "gross_area_factor": 1.25,
        "civil_eur_m2_gross": 340.0,
        "hvac_eur_m2_gross": 230.0,
        "led_eur_m2_active": 300.0,
        "hydro_eur_m2_active": 75.0,
        "ro_fixed_eur": 6500.0,
        "post_fixed_eur": 8500.0,
        "dwc_extra_eur_m2_active": 30.0,
        "electrical_eur_m2_gross": 70.0,
        "labor_base_eur_year": 36500.0,
        "labor_var_eur_m2_gross_year": 95.0,
        "maintenance_pct_capex_subtotal": 0.026,
        "maintenance_fixed_eur_year": 900.0,
        "ro_membrane_pct": 0.075,
        "contingency_pct": 0.10,
    },
    "industrial_full": {
        "gross_area_factor": 1.45,
        "civil_eur_m2_gross": 480.0,
        "hvac_eur_m2_gross": 310.0,
        "led_eur_m2_active": 430.0,
        "hydro_eur_m2_active": 95.0,
        "ro_fixed_eur": 9500.0,
        "post_fixed_eur": 14000.0,
        "dwc_extra_eur_m2_active": 35.0,
        "electrical_eur_m2_gross": 95.0,
        "labor_base_eur_year": 42000.0,
        "labor_var_eur_m2_gross_year": 120.0,
        "maintenance_pct_capex_subtotal": 0.030,
        "maintenance_fixed_eur_year": 1200.0,
        "ro_membrane_pct": 0.08,
        "contingency_pct": 0.12,
    },
}

MONITORING_CATALOG: Dict[str, Dict[str, float]] = {
    "core_efficiency_extended": {
        "sensor_eur_m2_active": 26.0,
        "control_core_fixed_eur": 3400.0,
        "actuation_interfaces_fixed_eur": 1800.0,
        "energy_metering_fixed_eur": 1400.0,
        "probes_replacement_eur_m2_active_year": 4.2,
    },
    "full": {
        "sensor_eur_m2_active": 44.0,
        "control_core_fixed_eur": 4750.0,
        "actuation_interfaces_fixed_eur": 2650.0,
        "energy_metering_fixed_eur": 2800.0,
        "probes_replacement_eur_m2_active_year": 6.8,
    },
}

ENERGY_ARCHITECTURE_CATALOG: Dict[str, Dict[str, float]] = {
    "grid_only_retrofit": {
        "pv_kwp": 0.0,
        "battery_kwh_nominal": 0.0,
        "inverter_kw": 0.0,
        "switchgear_eur": 2800.0,
        "retrofit_prep_eur": 4200.0,
        "install_pct": 0.08,
        "self_consumption_ratio": 0.0,
        "pv_yield_kwh_per_kwp_year": 1700.0,
        "pv_degradation_pct_year": 0.007,
        "grid_import_eur_kwh": 0.29,
        "grid_fixed_charges_eur_year": 1200.0,
        "cost_pv_eur_kwp": 1150.0,
        "cost_battery_eur_kwh": 360.0,
        "cost_inverter_eur_kw": 180.0,
        "battery_replacement_year": 10.0,
        "inverter_replacement_year": 12.0,
        "replacement_factor_pct": 0.70,
    },
    "hybrid_small": {
        "pv_kwp": 20.0,
        "battery_kwh_nominal": 40.0,
        "inverter_kw": 20.0,
        "switchgear_eur": 5000.0,
        "retrofit_prep_eur": 2000.0,
        "install_pct": 0.10,
        "self_consumption_ratio": 0.70,
        "pv_yield_kwh_per_kwp_year": 1700.0,
        "pv_degradation_pct_year": 0.007,
        "grid_import_eur_kwh": 0.29,
        "grid_fixed_charges_eur_year": 1200.0,
        "cost_pv_eur_kwp": 1150.0,
        "cost_battery_eur_kwh": 360.0,
        "cost_inverter_eur_kw": 180.0,
        "battery_replacement_year": 10.0,
        "inverter_replacement_year": 12.0,
        "replacement_factor_pct": 0.70,
    },
    "hybrid_full": {
        "pv_kwp": 60.0,
        "battery_kwh_nominal": 120.0,
        "inverter_kw": 60.0,
        "switchgear_eur": 8500.0,
        "retrofit_prep_eur": 0.0,
        "install_pct": 0.12,
        "self_consumption_ratio": 0.75,
        "pv_yield_kwh_per_kwp_year": 1700.0,
        "pv_degradation_pct_year": 0.007,
        "grid_import_eur_kwh": 0.29,
        "grid_fixed_charges_eur_year": 1200.0,
        "cost_pv_eur_kwp": 1150.0,
        "cost_battery_eur_kwh": 360.0,
        "cost_inverter_eur_kw": 180.0,
        "battery_replacement_year": 10.0,
        "inverter_replacement_year": 12.0,
        "replacement_factor_pct": 0.70,
    },
}

# Backward-compatible baseline used by legacy `case(...)` tests and scripts.
HYBRID_K: Dict[str, float] = {
    "pv_kwp": 60.0,
    "battery_kwh_nominal": 120.0,
    "battery_dod_usable": 0.85,
    "battery_roundtrip_eff": 0.92,
    "inverter_kw": 60.0,
    "pv_yield_kwh_per_kwp_year": 1700.0,
    "pv_degradation_pct_year": 0.007,
    "self_consumption_ratio": 0.75,
    "grid_import_eur_kwh": 0.29,
    "grid_fixed_charges_eur_year": 1200.0,
    "export_tariff_eur_kwh": 0.0,
    "cost_pv_eur_kwp": 1150.0,
    "cost_battery_eur_kwh": 360.0,
    "cost_inverter_eur_kw": 180.0,
    "cost_switchgear_eur": 8500.0,
    "cost_install_power_pct": 0.12,
    "battery_replacement_year": 10.0,
    "inverter_replacement_year": 12.0,
    "replacement_factor_pct": 0.70,
}


def _legacy_auto_capex(scale_reference_kg: float) -> Dict[str, float]:
    scale = float(scale_reference_kg) / 80.0
    c_auto_sensors = 6205.0 * scale
    c_control_core = 4750.0
    c_actuation_interfaces = 2650.0
    c_auto = c_auto_sensors + c_control_core + c_actuation_interfaces
    return {
        "c_auto_sensors": float(c_auto_sensors),
        "c_control_core": float(c_control_core),
        "c_actuation_interfaces": float(c_actuation_interfaces),
        "c_auto": float(c_auto),
    }


def _legacy_power_block_costs(hk: Dict[str, float]) -> Dict[str, float]:
    c_pv = hk["pv_kwp"] * hk["cost_pv_eur_kwp"]
    c_battery = hk["battery_kwh_nominal"] * hk["cost_battery_eur_kwh"]
    c_inverter = hk["inverter_kw"] * hk["cost_inverter_eur_kw"]
    c_switchgear = hk["cost_switchgear_eur"]
    c_install_power = hk["cost_install_power_pct"] * (c_pv + c_battery + c_inverter + c_switchgear)
    c_power_hybrid = c_pv + c_battery + c_inverter + c_switchgear + c_install_power
    return {
        "c_pv": float(c_pv),
        "c_battery": float(c_battery),
        "c_inverter": float(c_inverter),
        "c_switchgear": float(c_switchgear),
        "c_install_power": float(c_install_power),
        "c_power_hybrid": float(c_power_hybrid),
    }


def _validate_choice(name: str, value: str, catalog: Dict[str, Dict[str, float]]) -> str:
    choice = str(value).strip()
    if choice not in catalog:
        options = ", ".join(sorted(catalog.keys()))
        raise ValueError(f"{name} must be one of: {options}")
    return choice


def _financial_kpis(
    *,
    capex_total: float,
    opex_total_annual: float,
    annual_yield_kg: float,
    price_eur_g: float,
) -> Dict[str, float | None]:
    annual_revenue = float(annual_yield_kg) * 1000.0 * float(price_eur_g)
    ebitda_annual = annual_revenue - float(opex_total_annual)
    roi_annual_pct = (100.0 * ebitda_annual / float(capex_total)) if capex_total > 0.0 else None
    simple_payback_years = (float(capex_total) / ebitda_annual) if ebitda_annual > 0.0 else None
    break_even_yield_kg_year = float(opex_total_annual) / (1000.0 * float(price_eur_g))
    break_even_price_eur_g = float(opex_total_annual) / (1000.0 * max(float(annual_yield_kg), 1e-9))
    return {
        "annual_revenue_eur": float(annual_revenue),
        "ebitda_annual_eur": float(ebitda_annual),
        "roi_annual_pct": float(roi_annual_pct) if roi_annual_pct is not None else None,
        "simple_payback_years": float(simple_payback_years) if simple_payback_years is not None else None,
        "break_even_yield_kg_year": float(break_even_yield_kg_year),
        "break_even_price_eur_g": float(break_even_price_eur_g),
    }


def _resolve_economic_yield_basis_kg(
    *,
    target_annual_kg: float,
    planned_annual_kg: float,
    policy: str,
) -> float:
    if policy == "planned":
        return float(planned_annual_kg)
    if policy == "target":
        return float(target_annual_kg)
    raise ValueError("economic_yield_basis_policy must be one of: planned, target")


def _monitoring_capex(active_area_m2: float, monitoring_tier: str) -> Dict[str, float]:
    cfg = MONITORING_CATALOG[monitoring_tier]
    c_auto_sensors = float(cfg["sensor_eur_m2_active"]) * float(active_area_m2)
    c_control_core = float(cfg["control_core_fixed_eur"])
    c_actuation_interfaces = float(cfg["actuation_interfaces_fixed_eur"])
    c_energy_metering = float(cfg["energy_metering_fixed_eur"])
    c_auto = c_auto_sensors + c_control_core + c_actuation_interfaces + c_energy_metering
    return {
        "c_auto_sensors": float(c_auto_sensors),
        "c_control_core": float(c_control_core),
        "c_actuation_interfaces": float(c_actuation_interfaces),
        "c_energy_metering": float(c_energy_metering),
        "c_auto": float(c_auto),
    }


def _power_block_costs(energy_architecture: str) -> Dict[str, float]:
    cfg = ENERGY_ARCHITECTURE_CATALOG[energy_architecture]
    c_pv = float(cfg["pv_kwp"]) * float(cfg["cost_pv_eur_kwp"])
    c_battery = float(cfg["battery_kwh_nominal"]) * float(cfg["cost_battery_eur_kwh"])
    c_inverter = float(cfg["inverter_kw"]) * float(cfg["cost_inverter_eur_kw"])
    c_switchgear = float(cfg["switchgear_eur"])
    c_retrofit_prep = float(cfg["retrofit_prep_eur"])
    c_install_power = float(cfg["install_pct"]) * (c_pv + c_battery + c_inverter + c_switchgear + c_retrofit_prep)
    c_power_hybrid = c_pv + c_battery + c_inverter + c_switchgear + c_retrofit_prep + c_install_power
    return {
        "c_pv": float(c_pv),
        "c_battery": float(c_battery),
        "c_inverter": float(c_inverter),
        "c_switchgear": float(c_switchgear),
        "c_retrofit_prep": float(c_retrofit_prep),
        "c_install_power": float(c_install_power),
        "c_power_hybrid": float(c_power_hybrid),
    }


def _resolve_yield_quality_basis(
    *,
    yield_source: str,
    target_yield_kg_m2_cycle: float,
    target_annual_kg: float,
    energy_cap_kwh_m2_cycle: float,
    quality_floor: float,
    price_eur_g: float,
    mix_indica: float,
    mix_sativa: float,
    manual_quality_index: float,
    optimizer_mode: str,
    optimizer_n_init: int,
    optimizer_n_iter: int,
    optimizer_pool_size: int,
    optimizer_seed: int,
) -> Dict[str, float | str | Dict]:
    if yield_source == "manual":
        return {
            "yield_source": "manual",
            "yield_kg_m2_cycle": float(target_yield_kg_m2_cycle),
            "quality_index": float(manual_quality_index),
            "optimizer_result": {},
        }

    if yield_source != "optimizer":
        raise ValueError("yield_source must be one of: manual, optimizer")

    from optimizer_literature_best import run_mode

    mode = str(optimizer_mode).strip().lower()
    if mode not in {"max_yield", "max_yield_energy"}:
        raise ValueError("optimizer_mode must be one of: max_yield, max_yield_energy")

    args = SimpleNamespace(
        quality_y_min=1300.0,
        quality_floor=float(quality_floor),
        energy_cap_kwh_m2=float(energy_cap_kwh_m2_cycle),
        yield_target_annual_kg=float(target_annual_kg),
        farm_active_area_m2=max(
            float(target_annual_kg)
            / max(float(target_yield_kg_m2_cycle) * (365.0 / T_CYCLE_BASE_DAYS), 1e-9),
            10.0,
        ),
        n_init=int(optimizer_n_init),
        n_iter=int(optimizer_n_iter),
        pool_size=int(optimizer_pool_size),
        seed=int(optimizer_seed),
        yield_restarts=2,
        yield_robust_evals=4,
        quality_restarts=1,
        ensemble_evals=0,
        twin_calibration_json=None,
        genetic_profile="regular_photoperiodic",
        cultivar_family="hybrid",
        cultivar_name="",
    )
    res = run_mode(mode=mode, args=args)
    outcome = res.get("outcome", {})
    derived = outcome.get("derived_metrics", {})
    yield_kg_m2_cycle = float(derived.get("dry_yield_g_m2_cycle", 0.0)) / 1000.0
    quality_index = float(outcome.get("quality_index", 0.0))
    if yield_kg_m2_cycle <= 0.0:
        raise RuntimeError("optimizer did not return a valid cycle yield for economic analysis")
    return {
        "yield_source": "optimizer",
        "yield_kg_m2_cycle": float(yield_kg_m2_cycle),
        "quality_index": float(quality_index),
        "optimizer_result": {
            "mode": str(res.get("mode", mode)),
            "objective_value": float(res.get("objective_value", 0.0)),
            "dry_yield_g_m2": float(outcome.get("dry_yield_g_m2", 0.0)),
            "quality_index": float(quality_index),
            "energy_kwh_m2": float(outcome.get("energy_kwh_m2", 0.0)),
            "constraints": dict(res.get("constraints", {})),
            "price_eur_g_reference": float(price_eur_g),
            "mix_indica_reference": float(mix_indica),
            "mix_sativa_reference": float(mix_sativa),
        },
    }


def _candidate_case(
    *,
    target_annual_kg: float,
    price_eur_g: float,
    mix_indica: float,
    mix_sativa: float,
    target_yield_kg_m2_cycle: float,
    energy_cap_kwh_m2_cycle: float,
    economic_yield_basis_policy: str,
    quality_floor: float,
    quality_index_basis: float,
    infrastructure_profile: str,
    energy_architecture: str,
    monitoring_tier: str,
) -> Dict[str, object]:
    from core.production_planner import HARD_STAGE_DAYS, PlannerInput, build_clone_logistics_plan

    cfg = PlannerInput(
        target_annual_kg=float(target_annual_kg),
        target_yield_kg_m2_cycle=float(target_yield_kg_m2_cycle),
        mix_indica=float(mix_indica),
        mix_sativa=float(mix_sativa),
    )
    plan = build_clone_logistics_plan(cfg)
    annual_by_family = plan["annual_targets"]["by_family_kg"]

    family_rows: Dict[str, Dict[str, float]] = {}
    e_prod_annual = 0.0
    max_family_energy_kwh_m2_cycle = 0.0
    for fam in ("indica_dominant", "sativa_dominant"):
        cycle_days = float(sum(HARD_STAGE_DAYS[fam].values()))
        n_cycles = 365.0 / cycle_days
        annual_kg = float(annual_by_family[fam])
        y_kg_cycle = annual_kg / n_cycles
        area_m2_net = y_kg_cycle / float(target_yield_kg_m2_cycle)
        energy_mult = float(FAMILY_MULTIPLIERS.get(fam, FAMILY_MULTIPLIERS["hybrid"])["energy"])
        e_m2_cycle_nominal = E_M2_CYCLE_BASE * energy_mult
        e_m2_cycle = min(e_m2_cycle_nominal, float(energy_cap_kwh_m2_cycle))
        max_family_energy_kwh_m2_cycle = max(max_family_energy_kwh_m2_cycle, float(e_m2_cycle))
        e_family_annual = e_m2_cycle * area_m2_net * n_cycles
        e_prod_annual += e_family_annual
        family_rows[fam] = {
            "annual_target_kg": float(annual_kg),
            "cycle_days": float(cycle_days),
            "n_cycles": float(n_cycles),
            "yield_kg_cycle": float(y_kg_cycle),
            "production_area_m2_net": float(area_m2_net),
            "energy_kwh_m2_cycle_nominal": float(e_m2_cycle_nominal),
            "energy_kwh_m2_cycle": float(e_m2_cycle),
            "energy_annual_kwh": float(e_family_annual),
        }

    e_support_annual = 0.30 * e_prod_annual
    e_dwc_annual = 0.08 * e_prod_annual
    e_hvac_dwc_annual = 0.25 * e_dwc_annual
    e_total_annual = e_prod_annual + e_support_annual + e_dwc_annual + e_hvac_dwc_annual

    energy_cfg = ENERGY_ARCHITECTURE_CATALOG[energy_architecture]
    infra_cfg = INFRASTRUCTURE_CATALOG[infrastructure_profile]
    monitoring_cfg = MONITORING_CATALOG[monitoring_tier]

    e_pv_annual = (
        float(energy_cfg["pv_kwp"])
        * float(energy_cfg["pv_yield_kwh_per_kwp_year"])
        * (1.0 - float(energy_cfg["pv_degradation_pct_year"]))
    )
    e_pv_self_annual = min(float(e_total_annual), float(energy_cfg["self_consumption_ratio"]) * float(e_pv_annual))
    e_grid_import_annual = float(e_total_annual) - float(e_pv_self_annual)
    e_export_annual = 0.0
    e_curtail_annual = max(float(e_pv_annual) - float(e_pv_self_annual) - float(e_export_annual), 0.0)

    area_cap = plan["area_plan_m2"]["capacity_with_margin"]
    active_area_m2 = float(plan["area_plan_m2"]["total_active_cultivation_capacity_m2"])
    gross_area_m2 = float(active_area_m2) * float(infra_cfg["gross_area_factor"])

    c_civil = float(infra_cfg["civil_eur_m2_gross"]) * gross_area_m2
    c_hvac = float(infra_cfg["hvac_eur_m2_gross"]) * gross_area_m2
    c_led = float(infra_cfg["led_eur_m2_active"]) * active_area_m2
    c_hydro = float(infra_cfg["hydro_eur_m2_active"]) * active_area_m2
    c_ro = float(infra_cfg["ro_fixed_eur"])
    c_post = float(infra_cfg["post_fixed_eur"])
    c_dwc_extra = float(infra_cfg["dwc_extra_eur_m2_active"]) * active_area_m2
    c_electrical_farm = float(infra_cfg["electrical_eur_m2_gross"]) * gross_area_m2

    auto = _monitoring_capex(active_area_m2=active_area_m2, monitoring_tier=monitoring_tier)
    power = _power_block_costs(energy_architecture=energy_architecture)

    capex_subtotal = (
        c_civil
        + c_hvac
        + c_led
        + c_hydro
        + c_ro
        + auto["c_auto"]
        + c_post
        + c_dwc_extra
        + c_electrical_farm
        + power["c_power_hybrid"]
    )
    c_contingency = float(infra_cfg["contingency_pct"]) * capex_subtotal
    capex_total = capex_subtotal + c_contingency

    plan_projected_annual_yield_kg = float(plan["weekly_clone_plan"]["projected_annual_yield_kg_from_schedule"])
    target_vs_planned_kg = float(target_annual_kg) - plan_projected_annual_yield_kg
    economic_yield_basis_kg = _resolve_economic_yield_basis_kg(
        target_annual_kg=float(target_annual_kg),
        planned_annual_kg=plan_projected_annual_yield_kg,
        policy=economic_yield_basis_policy,
    )

    opex_energy = float(e_grid_import_annual) * float(energy_cfg["grid_import_eur_kwh"]) + float(
        energy_cfg["grid_fixed_charges_eur_year"]
    )
    opex_water = float(economic_yield_basis_kg) * 0.25 * 2.5
    opex_nutrients = float(economic_yield_basis_kg) * 3.2
    opex_labor = float(infra_cfg["labor_base_eur_year"]) + float(infra_cfg["labor_var_eur_m2_gross_year"]) * gross_area_m2
    opex_maintenance = float(infra_cfg["maintenance_pct_capex_subtotal"]) * capex_subtotal + float(
        infra_cfg["maintenance_fixed_eur_year"]
    )
    opex_ro_membranes = float(infra_cfg["ro_membrane_pct"]) * c_ro
    battery_replacement = (
        float(energy_cfg["replacement_factor_pct"])
        * float(power["c_battery"])
        / max(float(energy_cfg["battery_replacement_year"]), 1e-9)
    )
    inverter_replacement = (
        float(energy_cfg["replacement_factor_pct"])
        * float(power["c_inverter"])
        / max(float(energy_cfg["inverter_replacement_year"]), 1e-9)
    )
    probes_replacement = float(monitoring_cfg["probes_replacement_eur_m2_active_year"]) * active_area_m2
    opex_replacement_annual = battery_replacement + inverter_replacement + probes_replacement
    opex_total_annual = (
        opex_energy
        + opex_water
        + opex_nutrients
        + opex_labor
        + opex_maintenance
        + opex_ro_membranes
        + opex_replacement_annual
    )

    kpi = _financial_kpis(
        capex_total=capex_total,
        opex_total_annual=opex_total_annual,
        annual_yield_kg=economic_yield_basis_kg,
        price_eur_g=float(price_eur_g),
    )

    constraints_satisfied = {
        "annual_yield_equals_target": bool(plan["checks"]["annual_yield_equals_target"]),
        "energy_cap_respected": bool(float(max_family_energy_kwh_m2_cycle) <= float(energy_cap_kwh_m2_cycle) + 1e-9),
        "quality_floor_satisfied": bool(float(quality_index_basis) >= float(quality_floor)),
    }
    constraints_satisfied["all"] = all(constraints_satisfied.values())

    return {
        "target_annual_kg": float(target_annual_kg),
        "price_eur_g": float(price_eur_g),
        "target_yield_kg_m2_cycle": float(target_yield_kg_m2_cycle),
        "quality_index_basis": float(quality_index_basis),
        "quality_floor": float(quality_floor),
        "energy_cap_kwh_m2_cycle": float(energy_cap_kwh_m2_cycle),
        "mix_indica": float(mix_indica),
        "mix_sativa": float(mix_sativa),
        "infrastructure_profile": str(infrastructure_profile),
        "energy_architecture": str(energy_architecture),
        "monitoring_tier": str(monitoring_tier),
        "economic_yield_basis_policy": str(economic_yield_basis_policy),
        "economic_yield_basis_kg": float(economic_yield_basis_kg),
        "family_breakdown": family_rows,
        "plan_checks": dict(plan["checks"]),
        "plan_projected_annual_yield_kg": float(plan_projected_annual_yield_kg),
        "target_vs_planned_kg": float(target_vs_planned_kg),
        "area_m2": {
            "gross_area_m2": float(gross_area_m2),
            "active_area_m2": float(active_area_m2),
            "flower_area_capacity_m2": float(area_cap["flower"]),
            "propagation_area_capacity_m2": float(area_cap["propagation"]),
            "vegetative_area_capacity_m2": float(area_cap["vegetative"]),
            "transition_area_capacity_m2": float(area_cap["transition"]),
        },
        "constraints_satisfied": constraints_satisfied,
        "e_total_annual": float(e_total_annual),
        "e_pv_annual": float(e_pv_annual),
        "e_pv_self_annual": float(e_pv_self_annual),
        "e_grid_import_annual": float(e_grid_import_annual),
        "e_export_annual": float(e_export_annual),
        "e_curtail_annual": float(e_curtail_annual),
        "c_pv": float(power["c_pv"]),
        "c_battery": float(power["c_battery"]),
        "c_inverter": float(power["c_inverter"]),
        "c_switchgear": float(power["c_switchgear"]),
        "c_retrofit_prep": float(power["c_retrofit_prep"]),
        "c_install_power": float(power["c_install_power"]),
        "c_power_hybrid": float(power["c_power_hybrid"]),
        "c_auto": float(auto["c_auto"]),
        "c_auto_sensors": float(auto["c_auto_sensors"]),
        "c_control_core": float(auto["c_control_core"]),
        "c_actuation_interfaces": float(auto["c_actuation_interfaces"]),
        "c_energy_metering": float(auto["c_energy_metering"]),
        "capex_subtotal": float(capex_subtotal),
        "c_contingency": float(c_contingency),
        "capex_total": float(capex_total),
        "opex_energy": float(opex_energy),
        "opex_water": float(opex_water),
        "opex_nutrients": float(opex_nutrients),
        "opex_labor": float(opex_labor),
        "opex_maintenance": float(opex_maintenance),
        "opex_ro_membranes": float(opex_ro_membranes),
        "opex_replacement_annual": float(opex_replacement_annual),
        "opex_total_annual": float(opex_total_annual),
        "annual_revenue_eur": kpi["annual_revenue_eur"],
        "ebitda_annual_eur": kpi["ebitda_annual_eur"],
        "roi_annual_pct": kpi["roi_annual_pct"],
        "simple_payback_years": kpi["simple_payback_years"],
        "break_even_yield_kg_year": kpi["break_even_yield_kg_year"],
        "break_even_price_eur_g": kpi["break_even_price_eur_g"],
    }


def _candidate_space(
    infrastructure_profile: str,
    energy_architecture: str,
    monitoring_tier: str,
) -> Iterable[Tuple[str, str, str]]:
    infra_pref = _validate_choice("infrastructure_profile", infrastructure_profile, INFRASTRUCTURE_CATALOG)
    energy_pref = _validate_choice("energy_architecture", energy_architecture, ENERGY_ARCHITECTURE_CATALOG)
    monitor_pref = _validate_choice("monitoring_tier", monitoring_tier, MONITORING_CATALOG)
    ordered_infra = [infra_pref] + [k for k in INFRASTRUCTURE_CATALOG if k != infra_pref]
    ordered_energy = [energy_pref] + [k for k in ENERGY_ARCHITECTURE_CATALOG if k != energy_pref]
    ordered_monitor = [monitor_pref] + [k for k in MONITORING_CATALOG if k != monitor_pref]
    return product(ordered_infra, ordered_energy, ordered_monitor)


def project_case(
    target_annual_kg: float = 80.0,
    price_eur_g: float = 4.0,
    mix_indica: float = 0.5,
    mix_sativa: float = 0.5,
    target_yield_kg_m2_cycle: float = 0.35,
    energy_cap_kwh_m2_cycle: float = 700.0,
    economic_yield_basis_policy: str = "target",
    infrastructure_profile: str = DEFAULT_INFRASTRUCTURE_PROFILE,
    energy_architecture: str = DEFAULT_ENERGY_ARCHITECTURE,
    monitoring_tier: str = DEFAULT_MONITORING_TIER,
    quality_floor: float = DEFAULT_QUALITY_FLOOR,
    yield_source: str = DEFAULT_YIELD_SOURCE,
    manual_quality_index: float = 64.0,
    optimizer_mode: str = "max_yield_energy",
    optimizer_n_init: int = 8,
    optimizer_n_iter: int = 6,
    optimizer_pool_size: int = 240,
    optimizer_seed: int = 2026,
) -> Dict[str, object]:
    if target_annual_kg <= 0.0:
        raise ValueError("target_annual_kg must be > 0")
    if price_eur_g <= 0.0:
        raise ValueError("price_eur_g must be > 0")
    if target_yield_kg_m2_cycle <= 0.0:
        raise ValueError("target_yield_kg_m2_cycle must be > 0")
    if energy_cap_kwh_m2_cycle <= 0.0:
        raise ValueError("energy_cap_kwh_m2_cycle must be > 0")
    if quality_floor <= 0.0:
        raise ValueError("quality_floor must be > 0")
    if abs((float(mix_indica) + float(mix_sativa)) - 1.0) > 1e-9:
        raise ValueError("mix_indica + mix_sativa must be 1.0")
    if economic_yield_basis_policy not in {"planned", "target"}:
        raise ValueError("economic_yield_basis_policy must be one of: planned, target")

    yield_basis = _resolve_yield_quality_basis(
        yield_source=str(yield_source),
        target_yield_kg_m2_cycle=float(target_yield_kg_m2_cycle),
        target_annual_kg=float(target_annual_kg),
        energy_cap_kwh_m2_cycle=float(energy_cap_kwh_m2_cycle),
        quality_floor=float(quality_floor),
        price_eur_g=float(price_eur_g),
        mix_indica=float(mix_indica),
        mix_sativa=float(mix_sativa),
        manual_quality_index=float(manual_quality_index),
        optimizer_mode=str(optimizer_mode),
        optimizer_n_init=int(optimizer_n_init),
        optimizer_n_iter=int(optimizer_n_iter),
        optimizer_pool_size=int(optimizer_pool_size),
        optimizer_seed=int(optimizer_seed),
    )

    cycle_yield_kg_m2 = float(yield_basis["yield_kg_m2_cycle"])
    quality_index_basis = float(yield_basis["quality_index"])

    candidates: List[Dict[str, object]] = []
    for infra_id, energy_id, monitor_id in _candidate_space(
        infrastructure_profile=str(infrastructure_profile),
        energy_architecture=str(energy_architecture),
        monitoring_tier=str(monitoring_tier),
    ):
        c = _candidate_case(
            target_annual_kg=float(target_annual_kg),
            price_eur_g=float(price_eur_g),
            mix_indica=float(mix_indica),
            mix_sativa=float(mix_sativa),
            target_yield_kg_m2_cycle=float(cycle_yield_kg_m2),
            energy_cap_kwh_m2_cycle=float(energy_cap_kwh_m2_cycle),
            economic_yield_basis_policy=str(economic_yield_basis_policy),
            quality_floor=float(quality_floor),
            quality_index_basis=float(quality_index_basis),
            infrastructure_profile=infra_id,
            energy_architecture=energy_id,
            monitoring_tier=monitor_id,
        )
        candidates.append(c)

    ranked = sorted(candidates, key=lambda r: (float(r["capex_total"]), float(r["opex_total_annual"])))
    for idx, row in enumerate(ranked):
        row["rank"] = int(idx + 1)

    feasible = [r for r in ranked if bool((r.get("constraints_satisfied") or {}).get("all", False))]
    if not feasible:
        raise RuntimeError("No feasible economic configuration found for current constraints")
    selected = feasible[0]

    ranking_summary: List[Dict[str, object]] = []
    for row in ranked:
        ranking_summary.append(
            {
                "rank": int(row["rank"]),
                "infrastructure_profile": str(row["infrastructure_profile"]),
                "energy_architecture": str(row["energy_architecture"]),
                "monitoring_tier": str(row["monitoring_tier"]),
                "capex_total": float(row["capex_total"]),
                "opex_total_annual": float(row["opex_total_annual"]),
                "ebitda_annual_eur": float(row["ebitda_annual_eur"]),
                "constraints_satisfied": dict(row["constraints_satisfied"]),
            }
        )

    out = dict(selected)
    out["yield_source"] = str(yield_basis["yield_source"])
    out["yield_basis"] = {
        "yield_kg_m2_cycle": float(cycle_yield_kg_m2),
        "quality_index": float(quality_index_basis),
    }
    out["optimizer_result"] = dict(yield_basis.get("optimizer_result", {}))
    out["requested_configuration"] = {
        "infrastructure_profile": str(infrastructure_profile),
        "energy_architecture": str(energy_architecture),
        "monitoring_tier": str(monitoring_tier),
    }
    out["selected_configuration"] = {
        "infrastructure_profile": str(selected["infrastructure_profile"]),
        "energy_architecture": str(selected["energy_architecture"]),
        "monitoring_tier": str(selected["monitoring_tier"]),
        "selection_policy": "min_capex_feasible",
    }
    out["candidate_rankings"] = ranking_summary
    out["constraints_satisfied"] = dict(selected["constraints_satisfied"])
    return out


def case(
    y: float,
    p: float,
    family: str = "hybrid",
    layout_name: str = "base",
    hybrid_overrides: Dict[str, float] | None = None,
    yield_kg_m2_cycle: float = R_KG_M2_CYCLE,
    energy_cap_kwh_m2_cycle: float = E_M2_CYCLE_MAX,
) -> Dict[str, float | None]:
    if y <= 0.0:
        raise ValueError("y must be > 0")
    if p <= 0.0:
        raise ValueError("p must be > 0")
    if yield_kg_m2_cycle <= 0.0:
        raise ValueError("yield_kg_m2_cycle must be > 0")
    if energy_cap_kwh_m2_cycle <= 0.0:
        raise ValueError("energy_cap_kwh_m2_cycle must be > 0")

    fm = FAMILY_MULTIPLIERS.get(family, FAMILY_MULTIPLIERS["hybrid"])
    hk = dict(HYBRID_K)
    if hybrid_overrides:
        hk.update({k: float(v) for k, v in hybrid_overrides.items()})

    t_cycle_days = T_CYCLE_BASE_DAYS * float(fm["cycle_days"])
    n_cycles = 365.0 / t_cycle_days
    s_prod = float(y) / float(yield_kg_m2_cycle)

    e_m2_cycle_nominal = E_M2_CYCLE_BASE * float(fm["energy"])
    e_m2_cycle = min(e_m2_cycle_nominal, float(energy_cap_kwh_m2_cycle))
    e_prod_cycle = e_m2_cycle * s_prod
    e_support_cycle = 0.30 * e_prod_cycle
    e_dwc_cycle = 0.08 * e_prod_cycle
    e_hvac_dwc_cycle = 0.25 * e_dwc_cycle
    e_total_cycle = e_prod_cycle + e_support_cycle + e_dwc_cycle + e_hvac_dwc_cycle
    e_total_annual = e_total_cycle * n_cycles

    e_pv_annual = hk["pv_kwp"] * hk["pv_yield_kwh_per_kwp_year"] * (1.0 - hk["pv_degradation_pct_year"])
    e_pv_self_annual = min(e_total_annual, hk["self_consumption_ratio"] * e_pv_annual)
    e_grid_import_annual = e_total_annual - e_pv_self_annual
    e_export_annual = 0.0
    e_curtail_annual = max(e_pv_annual - e_pv_self_annual - e_export_annual, 0.0)

    scale_reference_kg = float(y)
    scale = scale_reference_kg / 80.0
    auto = _legacy_auto_capex(scale_reference_kg=scale_reference_kg)

    c_civil = 120000.0 * scale
    c_hvac = 65000.0 * scale
    c_led = 95000.0 * scale
    c_hydro = 18000.0 * scale
    c_ro = 9500.0 * scale
    c_post = 14000.0 * scale
    c_dwc_extra = 4800.0 * scale
    c_electrical_farm = 12000.0 * scale

    power = _legacy_power_block_costs(hk)
    capex_subtotal = (
        c_civil
        + c_hvac
        + c_led
        + c_hydro
        + c_ro
        + auto["c_auto"]
        + c_post
        + c_dwc_extra
        + c_electrical_farm
        + power["c_power_hybrid"]
    )
    c_contingency = 0.12 * capex_subtotal
    capex_total = capex_subtotal + c_contingency

    opex_energy = e_grid_import_annual * hk["grid_import_eur_kwh"] + hk["grid_fixed_charges_eur_year"]
    opex_water = (y * n_cycles) * 0.25 * 2.5
    opex_nutrients = (y * n_cycles) * 3.2
    opex_labor = 42000.0 + 160.0 * scale
    opex_maintenance = 0.03 * capex_subtotal + 1200.0
    opex_ro_membranes = 0.08 * c_ro
    battery_replacement = hk["replacement_factor_pct"] * power["c_battery"] / hk["battery_replacement_year"]
    inverter_replacement = hk["replacement_factor_pct"] * power["c_inverter"] / hk["inverter_replacement_year"]
    probes_replacement = 950.0 * scale
    opex_replacement_annual = battery_replacement + inverter_replacement + probes_replacement
    opex_total_annual = (
        opex_energy
        + opex_water
        + opex_nutrients
        + opex_labor
        + opex_maintenance
        + opex_ro_membranes
        + opex_replacement_annual
    )

    annual_yield_kg = float(y) * n_cycles
    kpi = _financial_kpis(
        capex_total=capex_total,
        opex_total_annual=opex_total_annual,
        annual_yield_kg=annual_yield_kg,
        price_eur_g=float(p),
    )

    return {
        "layout_name": str(layout_name),
        "family": str(family),
        "y_kg_cycle": float(y),
        "price_eur_g": float(p),
        "yield_kg_m2_cycle_assumed": float(yield_kg_m2_cycle),
        "energy_cap_kwh_m2_cycle": float(energy_cap_kwh_m2_cycle),
        "s_prod": float(s_prod),
        "t_cycle_days": float(t_cycle_days),
        "n_cycles": float(n_cycles),
        "annual_yield_kg": float(annual_yield_kg),
        "e_m2_cycle": float(e_m2_cycle),
        "e_total_cycle": float(e_total_cycle),
        "e_total_annual": float(e_total_annual),
        "e_pv_annual": float(e_pv_annual),
        "e_pv_self_annual": float(e_pv_self_annual),
        "e_grid_import_annual": float(e_grid_import_annual),
        "e_export_annual": float(e_export_annual),
        "e_curtail_annual": float(e_curtail_annual),
        "c_pv": float(power["c_pv"]),
        "c_battery": float(power["c_battery"]),
        "c_inverter": float(power["c_inverter"]),
        "c_switchgear": float(power["c_switchgear"]),
        "c_install_power": float(power["c_install_power"]),
        "c_power_hybrid": float(power["c_power_hybrid"]),
        "c_auto": float(auto["c_auto"]),
        "c_auto_sensors": float(auto["c_auto_sensors"]),
        "c_control_core": float(auto["c_control_core"]),
        "c_actuation_interfaces": float(auto["c_actuation_interfaces"]),
        "capex_subtotal": float(capex_subtotal),
        "c_contingency": float(c_contingency),
        "capex_total": float(capex_total),
        "opex_energy": float(opex_energy),
        "opex_water": float(opex_water),
        "opex_nutrients": float(opex_nutrients),
        "opex_labor": float(opex_labor),
        "opex_maintenance": float(opex_maintenance),
        "opex_ro_membranes": float(opex_ro_membranes),
        "opex_replacement_annual": float(opex_replacement_annual),
        "opex_total_annual": float(opex_total_annual),
        "annual_revenue_eur": kpi["annual_revenue_eur"],
        "ebitda_annual_eur": kpi["ebitda_annual_eur"],
        "roi_annual_pct": kpi["roi_annual_pct"],
        "simple_payback_years": kpi["simple_payback_years"],
        "break_even_yield_kg_year": kpi["break_even_yield_kg_year"],
        "break_even_price_eur_g": kpi["break_even_price_eur_g"],
    }
