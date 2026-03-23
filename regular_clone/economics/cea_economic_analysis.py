from __future__ import annotations

from typing import Dict

R_KG_M2_CYCLE = 2.0
T_CYCLE_BASE_DAYS = 112.0
E_M2_CYCLE_BASE = 700.0
E_M2_CYCLE_MAX = 700.0

FAMILY_MULTIPLIERS = {
    # Coherent with hard cycle constraints and midpoint twin energy behavior.
    "hybrid": {"energy": 1.0, "cycle_days": 1.0},
    "indica_dominant": {"energy": 0.907, "cycle_days": 105.0 / 112.0},
    "sativa_dominant": {"energy": 1.235, "cycle_days": 120.0 / 112.0},
}

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


def _auto_capex(scale_reference_kg: float) -> Dict[str, float]:
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


def _power_block_costs(hk: Dict[str, float]) -> Dict[str, float]:
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


def case(
    y: float,
    p: float,
    family: str = "hybrid",
    layout_name: str = "base",
    hybrid_overrides: Dict[str, float] | None = None,
    yield_kg_m2_cycle: float = R_KG_M2_CYCLE,
    energy_cap_kwh_m2_cycle: float = E_M2_CYCLE_MAX,
) -> Dict[str, float | None]:
    """
    Legacy case model (cycle-centered), now extended with investor KPI fields.

    Parameters:
    - y: yield [kg/cycle]
    - p: selling price [EUR/g]
    """
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
    auto = _auto_capex(scale_reference_kg=scale_reference_kg)

    c_civil = 120000.0 * scale
    c_hvac = 65000.0 * scale
    c_led = 95000.0 * scale
    c_hydro = 18000.0 * scale
    c_ro = 9500.0 * scale
    c_post = 14000.0 * scale
    c_dwc_extra = 4800.0 * scale
    c_electrical_farm = 12000.0 * scale

    power = _power_block_costs(hk)
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


def project_case(
    target_annual_kg: float = 80.0,
    price_eur_g: float = 4.0,
    mix_indica: float = 0.5,
    mix_sativa: float = 0.5,
    target_yield_kg_m2_cycle: float = 0.35,
    energy_cap_kwh_m2_cycle: float = 700.0,
    hybrid_overrides: Dict[str, float] | None = None,
) -> Dict[str, float | bool | Dict]:
    """
    Project-aligned annual economics using regular_clone production-planner assumptions.
    """
    if target_annual_kg <= 0.0:
        raise ValueError("target_annual_kg must be > 0")
    if price_eur_g <= 0.0:
        raise ValueError("price_eur_g must be > 0")
    if target_yield_kg_m2_cycle <= 0.0:
        raise ValueError("target_yield_kg_m2_cycle must be > 0")
    if energy_cap_kwh_m2_cycle <= 0.0:
        raise ValueError("energy_cap_kwh_m2_cycle must be > 0")
    if abs((float(mix_indica) + float(mix_sativa)) - 1.0) > 1e-9:
        raise ValueError("mix_indica + mix_sativa must be 1.0")

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
    for fam in ("indica_dominant", "sativa_dominant"):
        cycle_days = float(sum(HARD_STAGE_DAYS[fam].values()))
        n_cycles = 365.0 / cycle_days
        annual_kg = float(annual_by_family[fam])
        y_kg_cycle = annual_kg / n_cycles
        area_m2_net = y_kg_cycle / float(target_yield_kg_m2_cycle)
        energy_mult = float(FAMILY_MULTIPLIERS.get(fam, FAMILY_MULTIPLIERS["hybrid"])["energy"])
        e_m2_cycle = min(E_M2_CYCLE_BASE * energy_mult, float(energy_cap_kwh_m2_cycle))
        e_family_annual = e_m2_cycle * area_m2_net * n_cycles
        e_prod_annual += e_family_annual
        family_rows[fam] = {
            "annual_target_kg": float(annual_kg),
            "cycle_days": float(cycle_days),
            "n_cycles": float(n_cycles),
            "yield_kg_cycle": float(y_kg_cycle),
            "production_area_m2_net": float(area_m2_net),
            "energy_kwh_m2_cycle": float(e_m2_cycle),
            "energy_annual_kwh": float(e_family_annual),
        }

    e_support_annual = 0.30 * e_prod_annual
    e_dwc_annual = 0.08 * e_prod_annual
    e_hvac_dwc_annual = 0.25 * e_dwc_annual
    e_total_annual = e_prod_annual + e_support_annual + e_dwc_annual + e_hvac_dwc_annual

    hk = dict(HYBRID_K)
    if hybrid_overrides:
        hk.update({k: float(v) for k, v in hybrid_overrides.items()})

    e_pv_annual = hk["pv_kwp"] * hk["pv_yield_kwh_per_kwp_year"] * (1.0 - hk["pv_degradation_pct_year"])
    e_pv_self_annual = min(e_total_annual, hk["self_consumption_ratio"] * e_pv_annual)
    e_grid_import_annual = e_total_annual - e_pv_self_annual
    e_export_annual = 0.0
    e_curtail_annual = max(e_pv_annual - e_pv_self_annual - e_export_annual, 0.0)

    scale_reference_kg = float(target_annual_kg)
    scale = scale_reference_kg / 80.0
    auto = _auto_capex(scale_reference_kg=scale_reference_kg)
    power = _power_block_costs(hk)

    c_civil = 120000.0 * scale
    c_hvac = 65000.0 * scale
    c_led = 95000.0 * scale
    c_hydro = 18000.0 * scale
    c_ro = 9500.0 * scale
    c_post = 14000.0 * scale
    c_dwc_extra = 4800.0 * scale
    c_electrical_farm = 12000.0 * scale

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
    opex_water = float(target_annual_kg) * 0.25 * 2.5
    opex_nutrients = float(target_annual_kg) * 3.2
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

    kpi = _financial_kpis(
        capex_total=capex_total,
        opex_total_annual=opex_total_annual,
        annual_yield_kg=float(target_annual_kg),
        price_eur_g=float(price_eur_g),
    )

    return {
        "target_annual_kg": float(target_annual_kg),
        "price_eur_g": float(price_eur_g),
        "target_yield_kg_m2_cycle": float(target_yield_kg_m2_cycle),
        "energy_cap_kwh_m2_cycle": float(energy_cap_kwh_m2_cycle),
        "mix_indica": float(mix_indica),
        "mix_sativa": float(mix_sativa),
        "family_breakdown": family_rows,
        "plan_checks": dict(plan["checks"]),
        "plan_projected_annual_yield_kg": float(plan["weekly_clone_plan"]["projected_annual_yield_kg_from_schedule"]),
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

