from __future__ import annotations

from typing import Dict

R_KG_M2_CYCLE = 2.0
T_CYCLE_BASE_DAYS = 113.0
E_M2_CYCLE_BASE = 700.0
E_M2_CYCLE_MAX = 700.0

FAMILY_MULTIPLIERS = {
    "hybrid": {"energy": 1.0, "cycle_days": 1.0},
    "indica_dominant": {"energy": 0.819, "cycle_days": 0.894},
    "sativa_dominant": {"energy": 1.237, "cycle_days": 1.142},
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


def _auto_capex(y_kg_cycle: float) -> Dict[str, float]:
    scale = float(y_kg_cycle) / 80.0
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


def case(
    y: float,
    p: float,
    family: str = "hybrid",
    layout_name: str = "base",
    hybrid_overrides: Dict[str, float] | None = None,
) -> Dict[str, float]:
    if y <= 0.0:
        raise ValueError("y must be > 0")
    if p <= 0.0:
        raise ValueError("p must be > 0")

    fm = FAMILY_MULTIPLIERS.get(family, FAMILY_MULTIPLIERS["hybrid"])
    hk = dict(HYBRID_K)
    if hybrid_overrides:
        hk.update({k: float(v) for k, v in hybrid_overrides.items()})

    t_cycle_days = T_CYCLE_BASE_DAYS * float(fm["cycle_days"])
    n_cycles = 365.0 / t_cycle_days
    s_prod = float(y) / R_KG_M2_CYCLE

    e_m2_cycle_nominal = E_M2_CYCLE_BASE * float(fm["energy"])
    e_m2_cycle = min(e_m2_cycle_nominal, E_M2_CYCLE_MAX)
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

    scale = float(y) / 80.0
    auto = _auto_capex(y_kg_cycle=float(y))

    c_civil = 120000.0 * scale
    c_hvac = 65000.0 * scale
    c_led = 95000.0 * scale
    c_hydro = 18000.0 * scale
    c_ro = 9500.0 * scale
    c_post = 14000.0 * scale
    c_dwc_extra = 4800.0 * scale
    c_electrical_farm = 12000.0 * scale

    c_pv = hk["pv_kwp"] * hk["cost_pv_eur_kwp"]
    c_battery = hk["battery_kwh_nominal"] * hk["cost_battery_eur_kwh"]
    c_inverter = hk["inverter_kw"] * hk["cost_inverter_eur_kw"]
    c_switchgear = hk["cost_switchgear_eur"]
    c_install_power = hk["cost_install_power_pct"] * (c_pv + c_battery + c_inverter + c_switchgear)
    c_power_hybrid = c_pv + c_battery + c_inverter + c_switchgear + c_install_power

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
        + c_power_hybrid
    )
    c_contingency = 0.12 * capex_subtotal
    capex_total = capex_subtotal + c_contingency

    opex_energy = e_grid_import_annual * hk["grid_import_eur_kwh"] + hk["grid_fixed_charges_eur_year"]
    opex_water = (y * n_cycles) * 0.25 * 2.5
    opex_nutrients = (y * n_cycles) * 3.2
    opex_labor = 42000.0 + 160.0 * scale
    opex_maintenance = 0.03 * capex_subtotal + 1200.0
    opex_ro_membranes = 0.08 * c_ro
    battery_replacement = hk["replacement_factor_pct"] * c_battery / hk["battery_replacement_year"]
    inverter_replacement = hk["replacement_factor_pct"] * c_inverter / hk["inverter_replacement_year"]
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

    return {
        "layout_name": str(layout_name),
        "family": str(family),
        "y_kg_cycle": float(y),
        "price_eur_g": float(p),
        "s_prod": float(s_prod),
        "t_cycle_days": float(t_cycle_days),
        "n_cycles": float(n_cycles),
        "e_m2_cycle": float(e_m2_cycle),
        "e_total_cycle": float(e_total_cycle),
        "e_total_annual": float(e_total_annual),
        "e_pv_annual": float(e_pv_annual),
        "e_pv_self_annual": float(e_pv_self_annual),
        "e_grid_import_annual": float(e_grid_import_annual),
        "e_export_annual": float(e_export_annual),
        "e_curtail_annual": float(e_curtail_annual),
        "c_pv": float(c_pv),
        "c_battery": float(c_battery),
        "c_inverter": float(c_inverter),
        "c_switchgear": float(c_switchgear),
        "c_install_power": float(c_install_power),
        "c_power_hybrid": float(c_power_hybrid),
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
    }
