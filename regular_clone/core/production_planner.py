from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil
from typing import Dict, List


FAMILIES = ("indica_dominant", "sativa_dominant")

# MODIFICATO: stage days hardcoded da ciclo talea regular (cutting -> harvest)
# fonte: Team Progetto CEA (2026) BUISNESS PLAN (1)
HARD_STAGE_DAYS = {
    "indica_dominant": {
        "propagation": 12,
        "vegetative": 24,
        "transition": 7,
        "flower_early": 32,
        "flower_late": 30,
    },
    "sativa_dominant": {
        "propagation": 12,
        "vegetative": 27,
        "transition": 7,
        "flower_early": 37,
        "flower_late": 37,
    },
}

# MODIFICATO: densita hardcoded richieste per famiglie produttive
# fonte: Team Progetto CEA (2026) BUISNESS PLAN (1)
HARD_DENSITY_PL_M2 = {
    "indica_dominant": 4.0,
    "sativa_dominant": 2.0,
}


@dataclass(frozen=True)
class PlannerInput:
    target_annual_kg: float = 80.0
    target_yield_kg_m2_cycle: float = 0.35
    mix_indica: float = 0.50
    mix_sativa: float = 0.50
    rooting_rate: float = 0.85
    cuttings_per_vegetative_plant: float = 5.0
    cuttings_windows_per_week: int = 2
    safety_margin: float = 0.20
    saturation_threshold: float = 0.85


def _validate_input(cfg: PlannerInput) -> None:
    if cfg.target_annual_kg <= 0:
        raise ValueError("target_annual_kg must be > 0")
    if cfg.target_yield_kg_m2_cycle <= 0:
        raise ValueError("target_yield_kg_m2_cycle must be > 0")
    if not 0.0 < cfg.rooting_rate <= 1.0:
        raise ValueError("rooting_rate must be in (0, 1]")
    if cfg.cuttings_per_vegetative_plant <= 0:
        raise ValueError("cuttings_per_vegetative_plant must be > 0")
    if cfg.cuttings_windows_per_week < 1:
        raise ValueError("cuttings_windows_per_week must be >= 1")
    if cfg.safety_margin < 0.0:
        raise ValueError("safety_margin must be >= 0")
    if not 0.0 < cfg.saturation_threshold <= 1.0:
        raise ValueError("saturation_threshold must be in (0, 1]")
    if abs((cfg.mix_indica + cfg.mix_sativa) - 1.0) > 1e-9:
        raise ValueError("mix_indica + mix_sativa must be 1.0")


def _cycle_days(family: str) -> int:
    return int(sum(HARD_STAGE_DAYS[family].values()))


def _flower_days(family: str) -> int:
    stage = HARD_STAGE_DAYS[family]
    return int(stage["flower_early"] + stage["flower_late"])


def _area_capacity(net_area_m2: float, margin: float) -> float:
    return float(net_area_m2 * (1.0 + margin))


def _split_windows(total_weekly: int, windows: int) -> List[int]:
    base = total_weekly // windows
    rem = total_weekly % windows
    out = []
    for idx in range(windows):
        out.append(base + (1 if idx < rem else 0))
    return out


def _weekly_cuttings_capacity(
    area_cap_veg_indica: float,
    area_cap_veg_sativa: float,
    cuttings_per_plant: float,
) -> float:
    indicap = area_cap_veg_indica * HARD_DENSITY_PL_M2["indica_dominant"]
    sativap = area_cap_veg_sativa * HARD_DENSITY_PL_M2["sativa_dominant"]
    indica_rate = indicap * cuttings_per_plant / HARD_STAGE_DAYS["indica_dominant"]["vegetative"] * 7.0
    sativa_rate = sativap * cuttings_per_plant / HARD_STAGE_DAYS["sativa_dominant"]["vegetative"] * 7.0
    return float(indica_rate + sativa_rate)


def _projected_annual_yield_from_schedule(
    detached_week: Dict[str, int],
    rooting_rate: float,
    yield_per_plant_kg: Dict[str, float],
) -> float:
    total = 0.0
    for family in FAMILIES:
        rooted_week = float(detached_week[family]) * float(rooting_rate)
        total += rooted_week * 52.0 * float(yield_per_plant_kg[family])
    return float(total)


def _rebalance_weekly_detached_for_yield_cap(
    detached_week: Dict[str, int],
    target_annual_kg: float,
    rooting_rate: float,
    yield_per_plant_kg: Dict[str, float],
) -> tuple[Dict[str, int], float, bool]:
    current = {
        "indica_dominant": int(detached_week["indica_dominant"]),
        "sativa_dominant": int(detached_week["sativa_dominant"]),
    }
    projected = _projected_annual_yield_from_schedule(current, rooting_rate, yield_per_plant_kg)
    if projected <= target_annual_kg + 1e-9:
        return current, projected, False

    best_under: Dict[str, int] | None = None
    best_under_proj = -1.0
    best_any: Dict[str, int] = dict(current)
    best_any_proj = projected

    for detached_i in range(1, current["indica_dominant"] + 1):
        for detached_s in range(1, current["sativa_dominant"] + 1):
            cand = {
                "indica_dominant": int(detached_i),
                "sativa_dominant": int(detached_s),
            }
            cand_proj = _projected_annual_yield_from_schedule(cand, rooting_rate, yield_per_plant_kg)
            if cand_proj < best_any_proj:
                best_any_proj = cand_proj
                best_any = cand
            if cand_proj <= target_annual_kg + 1e-9 and cand_proj > best_under_proj:
                best_under_proj = cand_proj
                best_under = cand

    if best_under is not None:
        return best_under, best_under_proj, True
    return best_any, best_any_proj, True


def build_clone_logistics_plan(cfg: PlannerInput) -> Dict[str, object]:
    _validate_input(cfg)

    mix = {
        "indica_dominant": float(cfg.mix_indica),
        "sativa_dominant": float(cfg.mix_sativa),
    }

    annual_target_by_family = {
        f: cfg.target_annual_kg * mix[f] for f in FAMILIES
    }
    yield_per_plant_kg = {
        f: cfg.target_yield_kg_m2_cycle / HARD_DENSITY_PL_M2[f] for f in FAMILIES
    }
    annual_plants_needed = {
        f: annual_target_by_family[f] / max(yield_per_plant_kg[f], 1e-9) for f in FAMILIES
    }

    annual_productivity_kg_m2 = {
        f: cfg.target_yield_kg_m2_cycle * (365.0 / _cycle_days(f)) for f in FAMILIES
    }
    flower_area_net_by_family = {
        f: annual_target_by_family[f] / max(annual_productivity_kg_m2[f], 1e-9) for f in FAMILIES
    }
    flower_area_capacity_by_family = {
        f: _area_capacity(flower_area_net_by_family[f], cfg.safety_margin) for f in FAMILIES
    }

    stage_net = {s: 0.0 for s in ("propagation", "vegetative", "transition", "flower")}
    stage_cap = {s: 0.0 for s in ("propagation", "vegetative", "transition", "flower")}
    stage_cap_family = {
        "indica_dominant": {s: 0.0 for s in ("propagation", "vegetative", "transition", "flower")},
        "sativa_dominant": {s: 0.0 for s in ("propagation", "vegetative", "transition", "flower")},
    }

    for family in FAMILIES:
        flower_net = flower_area_net_by_family[family]
        flower_cap = flower_area_capacity_by_family[family]
        stage_net["flower"] += flower_net
        stage_cap["flower"] += flower_cap
        stage_cap_family[family]["flower"] = flower_cap
        fdays = float(_flower_days(family))
        for stage in ("propagation", "vegetative", "transition"):
            ratio = HARD_STAGE_DAYS[family][stage] / max(fdays, 1e-9)
            net = flower_net * ratio
            cap = _area_capacity(net, cfg.safety_margin)
            stage_net[stage] += net
            stage_cap[stage] += cap
            stage_cap_family[family][stage] = cap

    saturation = {
        stage: (stage_net[stage] / max(stage_cap[stage], 1e-9)) for stage in stage_cap
    }
    max_sat = max(saturation.values())
    blocked = bool(max_sat >= cfg.saturation_threshold)

    detached_week = {
        f: int(ceil((annual_plants_needed[f] / 52.0) / cfg.rooting_rate)) for f in FAMILIES
    }
    rebalance_applied = False
    if blocked:
        # MODIFICATO: auto-ribilanciamento lotti quando la saturazione supera la soglia
        # fonte: requisito operativo piano logistico multi-ciclo
        scale = max((cfg.saturation_threshold / max(max_sat, 1e-9)) * 0.98, 0.20)
        for f in FAMILIES:
            detached_week[f] = max(1, int(ceil(detached_week[f] * scale)))
        rebalance_applied = True
    detached_week, projected_annual_yield_kg, yield_cap_rebalance_applied = _rebalance_weekly_detached_for_yield_cap(
        detached_week=detached_week,
        target_annual_kg=cfg.target_annual_kg,
        rooting_rate=cfg.rooting_rate,
        yield_per_plant_kg=yield_per_plant_kg,
    )

    rooted_week = {
        f: float(detached_week[f] * cfg.rooting_rate) for f in FAMILIES
    }
    harvest_kg_week = {
        f: float(rooted_week[f] * yield_per_plant_kg[f]) for f in FAMILIES
    }

    windows = []
    indica_split = _split_windows(detached_week["indica_dominant"], cfg.cuttings_windows_per_week)
    sativa_split = _split_windows(detached_week["sativa_dominant"], cfg.cuttings_windows_per_week)
    for idx in range(cfg.cuttings_windows_per_week):
        det_i = indica_split[idx]
        det_s = sativa_split[idx]
        windows.append(
            {
                "window_index": idx + 1,
                "detached_cuttings": {
                    "indica_dominant": det_i,
                    "sativa_dominant": det_s,
                    "total": det_i + det_s,
                },
                "expected_rooted_cuttings": {
                    "indica_dominant": round(det_i * cfg.rooting_rate, 2),
                    "sativa_dominant": round(det_s * cfg.rooting_rate, 2),
                    "total": round((det_i + det_s) * cfg.rooting_rate, 2),
                },
            }
        )

    weekly_cuttings_cap = _weekly_cuttings_capacity(
        area_cap_veg_indica=stage_cap_family["indica_dominant"]["vegetative"],
        area_cap_veg_sativa=stage_cap_family["sativa_dominant"]["vegetative"],
        cuttings_per_plant=cfg.cuttings_per_vegetative_plant,
    )

    checks = {
        "no_dedicated_mother_phase": True,
        "max_cuttings_per_plant_enforced": bool(cfg.cuttings_per_vegetative_plant <= 5.0),
        "weekly_cuttings_within_capacity": bool(
            (detached_week["indica_dominant"] + detached_week["sativa_dominant"]) <= weekly_cuttings_cap
        ),
        "saturation_below_threshold": bool(max_sat < cfg.saturation_threshold),
        "annual_yield_within_cap": bool(projected_annual_yield_kg <= (cfg.target_annual_kg + 1e-9)),
    }

    return {
        "inputs": asdict(cfg),
        "hard_constraints": {
            "plant_type": "regular_photoperiodic",
            "cutting_cycle_start": "detached_cutting",
            "hard_density_pl_m2": HARD_DENSITY_PL_M2,
            "hard_stage_days": HARD_STAGE_DAYS,
            "cuttings_per_vegetative_plant_max": 5,
            "dedicated_mother_plants": False,
        },
        "yield_assumptions": {
            "target_yield_kg_m2_cycle": cfg.target_yield_kg_m2_cycle,
            "yield_per_plant_kg": yield_per_plant_kg,
            "annual_productivity_kg_m2": annual_productivity_kg_m2,
        },
        "annual_targets": {
            "total_kg": cfg.target_annual_kg,
            "by_family_kg": annual_target_by_family,
            "annual_plants_needed": annual_plants_needed,
        },
        "area_plan_m2": {
            "required_net": stage_net,
            "capacity_with_margin": stage_cap,
            "flower_split_capacity_by_family": flower_area_capacity_by_family,
            "total_active_cultivation_capacity_m2": float(sum(stage_cap.values())),
            "saturation_ratio": saturation,
            "saturation_threshold": cfg.saturation_threshold,
            "blocked_for_over_saturation": blocked,
        },
        "weekly_clone_plan": {
            "cadence_windows_per_week": cfg.cuttings_windows_per_week,
            "detached_cuttings_per_week": {
                "indica_dominant": detached_week["indica_dominant"],
                "sativa_dominant": detached_week["sativa_dominant"],
                "total": detached_week["indica_dominant"] + detached_week["sativa_dominant"],
            },
            "expected_rooted_per_week": {
                "indica_dominant": rooted_week["indica_dominant"],
                "sativa_dominant": rooted_week["sativa_dominant"],
                "total": rooted_week["indica_dominant"] + rooted_week["sativa_dominant"],
            },
            "expected_harvest_kg_per_week": {
                "indica_dominant": harvest_kg_week["indica_dominant"],
                "sativa_dominant": harvest_kg_week["sativa_dominant"],
                "total": harvest_kg_week["indica_dominant"] + harvest_kg_week["sativa_dominant"],
            },
            "projected_annual_yield_kg_from_schedule": projected_annual_yield_kg,
            "windows": windows,
            "weekly_cuttings_capacity_limit": weekly_cuttings_cap,
            "rebalance_applied": rebalance_applied,
            "yield_cap_rebalance_applied": yield_cap_rebalance_applied,
        },
        "scheduler_rules": [
            "max 5 cuttings per vegetative plant",
            "no dedicated mother-plant phase",
            "auto-block when any zone saturation >= threshold",
            "auto-rebalance by reducing detached cuttings in next window when blocked",
        ],
        "checks": checks,
    }
