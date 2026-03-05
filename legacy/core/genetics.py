from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple
import json


BoundsOverride = Tuple[float, float]

# Fallback defaults; runtime defaults are loaded from configs/genetic_profiles.json.
DEFAULT_GENETIC_PROFILE_ID = "feminized_photoperiodic"
DEFAULT_CULTIVAR_FAMILY = "hybrid"

_GENETIC_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "genetic_profiles.json"
_CULTIVAR_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "cultivar_catalog.json"


@dataclass(frozen=True)
class GeneticProfile:
    profile_id: str
    label: str
    seed_category: str
    photoperiodic: bool
    notes: str
    default_cultivar_family: str
    bound_overrides: Dict[str, BoundsOverride]
    family_bound_overrides: Dict[str, Dict[str, BoundsOverride]]
    model_coefficients: Dict[str, float]
    family_model_coefficients: Dict[str, Dict[str, float]]
    metadata: Dict[str, str | float | bool]
    evidence_source_ids: Tuple[str, ...]


@dataclass(frozen=True)
class CultivarPrior:
    cultivar_id: str
    name: str
    aliases: Tuple[str, ...]
    family: str
    model_coefficients: Dict[str, float]
    bound_overrides: Dict[str, BoundsOverride]
    metadata: Dict[str, str | float | bool]
    evidence_source_ids: Tuple[str, ...]
    profile_ids: Tuple[str, ...]


def _normalize_key(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _scalar_metadata_map(raw: object) -> Dict[str, str | float | bool]:
    out: Dict[str, str | float | bool] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        key = str(k)
        if isinstance(v, bool):
            out[key] = bool(v)
        elif isinstance(v, (int, float)):
            out[key] = float(v)
        else:
            out[key] = str(v)
    return out


def _bounds_map(raw: object) -> Dict[str, BoundsOverride]:
    out: Dict[str, BoundsOverride] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise ValueError(f"Invalid bounds override for '{k}': expected [lo, hi]")
        lo = float(v[0])
        hi = float(v[1])
        if lo >= hi:
            raise ValueError(f"Invalid bounds override for '{k}': lo ({lo}) >= hi ({hi})")
        out[str(k)] = (lo, hi)
    return out


def _float_map(raw: object) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        out[str(k)] = float(v)
    return out


@lru_cache(maxsize=1)
def _profiles_store() -> Tuple[str, str, Dict[str, GeneticProfile]]:
    raw = json.loads(_GENETIC_CONFIG.read_text(encoding="utf-8"))
    rows = raw.get("profiles", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Invalid genetic profile config: {_GENETIC_CONFIG}")

    default_profile_id = str(raw.get("default_genetic_profile_id", DEFAULT_GENETIC_PROFILE_ID))
    default_family = str(raw.get("default_cultivar_family", DEFAULT_CULTIVAR_FAMILY))

    profiles: Dict[str, GeneticProfile] = {}
    for item in rows:
        pid = str(item["profile_id"])
        fam_bounds_raw = item.get("family_bound_overrides", {})
        fam_model_raw = item.get("family_model_coefficients", {})
        if not isinstance(fam_bounds_raw, dict) or not isinstance(fam_model_raw, dict):
            raise ValueError(f"Invalid family maps for profile '{pid}'")

        family_bound_overrides_map: Dict[str, Dict[str, BoundsOverride]] = {}
        for fam, bmap in fam_bounds_raw.items():
            family_bound_overrides_map[str(fam)] = _bounds_map(bmap)

        family_model_coefficients_map: Dict[str, Dict[str, float]] = {}
        for fam, mmap in fam_model_raw.items():
            family_model_coefficients_map[str(fam)] = _float_map(mmap)

        profiles[pid] = GeneticProfile(
            profile_id=pid,
            label=str(item.get("label", pid)),
            seed_category=str(item.get("seed_category", "unknown")),
            photoperiodic=bool(item.get("photoperiodic", True)),
            notes=str(item.get("notes", "")),
            default_cultivar_family=str(item.get("default_cultivar_family", default_family)),
            bound_overrides=_bounds_map(item.get("bound_overrides", {})),
            family_bound_overrides=family_bound_overrides_map,
            model_coefficients=_float_map(item.get("model_coefficients", {})),
            family_model_coefficients=family_model_coefficients_map,
            metadata=_scalar_metadata_map(item.get("metadata", {})),
            evidence_source_ids=tuple(str(x) for x in item.get("evidence_source_ids", [])),
        )

    if default_profile_id not in profiles:
        default_profile_id = next(iter(profiles.keys()))
    return default_profile_id, default_family, profiles


@lru_cache(maxsize=1)
def _cultivar_store() -> Tuple[Dict[str, CultivarPrior], Dict[str, CultivarPrior]]:
    raw = json.loads(_CULTIVAR_CONFIG.read_text(encoding="utf-8"))
    rows = raw.get("cultivars", [])
    if not isinstance(rows, list):
        raise ValueError(f"Invalid cultivar catalog config: {_CULTIVAR_CONFIG}")

    by_alias: Dict[str, CultivarPrior] = {}
    by_name: Dict[str, CultivarPrior] = {}

    for item in rows:
        name = str(item["name"]).strip()
        aliases = tuple(str(x).strip() for x in item.get("aliases", []) if str(x).strip())
        family = str(item.get("family", DEFAULT_CULTIVAR_FAMILY)).strip().lower()
        cultivar_id = str(item.get("cultivar_id", _normalize_key(name)))
        prior = CultivarPrior(
            cultivar_id=cultivar_id,
            name=name,
            aliases=aliases,
            family=family,
            model_coefficients=_float_map(item.get("model_coefficients", {})),
            bound_overrides=_bounds_map(item.get("bound_overrides", {})),
            metadata=_scalar_metadata_map(item.get("metadata", {})),
            evidence_source_ids=tuple(str(x) for x in item.get("evidence_source_ids", [])),
            profile_ids=tuple(str(x) for x in item.get("profile_ids", [])),
        )
        by_name[name] = prior

        alias_keys = set([_normalize_key(name)])
        for alias in aliases:
            alias_keys.add(_normalize_key(alias))
        for key in alias_keys:
            if key:
                by_alias[key] = prior

    return by_alias, by_name


def default_genetic_profile_id() -> str:
    return _profiles_store()[0]


def default_cultivar_family() -> str:
    return _profiles_store()[1]


def available_genetic_profiles() -> Tuple[str, ...]:
    return tuple(sorted(_profiles_store()[2].keys()))


def _profile_or_default(profile_id: str | None) -> GeneticProfile:
    default_profile, _, profiles = _profiles_store()
    key = profile_id or default_profile
    if key not in profiles:
        supported = ", ".join(available_genetic_profiles())
        raise ValueError(f"Unknown genetic profile '{key}'. Available: {supported}")
    return profiles[key]


def available_cultivar_families(profile_id: str | None = None) -> Tuple[str, ...]:
    profile = _profile_or_default(profile_id)
    return tuple(sorted(profile.family_model_coefficients.keys()))


def normalize_cultivar_family(profile: GeneticProfile, cultivar_family: str | None) -> str:
    fallback_family = profile.default_cultivar_family or default_cultivar_family() or DEFAULT_CULTIVAR_FAMILY
    family = (cultivar_family or fallback_family).strip().lower()
    if family not in profile.family_model_coefficients:
        supported = ", ".join(sorted(profile.family_model_coefficients.keys()))
        raise ValueError(
            f"Unknown cultivar family '{family}' for profile '{profile.profile_id}'. "
            f"Available: {supported}"
        )
    return family


def family_model_coefficients(profile: GeneticProfile, cultivar_family: str | None) -> Dict[str, float]:
    family = normalize_cultivar_family(profile, cultivar_family)
    return {k: float(v) for k, v in profile.family_model_coefficients[family].items()}


def family_bound_overrides(profile: GeneticProfile, cultivar_family: str | None) -> Dict[str, BoundsOverride]:
    family = normalize_cultivar_family(profile, cultivar_family)
    return dict(profile.family_bound_overrides.get(family, {}))


def profile_evidence_source_ids(profile_id: str | None) -> Tuple[str, ...]:
    profile = _profile_or_default(profile_id)
    return tuple(profile.evidence_source_ids)


def available_cultivars() -> Tuple[str, ...]:
    _, by_name = _cultivar_store()
    return tuple(sorted(by_name.keys()))


def get_cultivar_prior(cultivar_name: str | None) -> Optional[CultivarPrior]:
    if not cultivar_name:
        return None
    key = _normalize_key(str(cultivar_name))
    if not key:
        return None
    by_alias, _ = _cultivar_store()
    return by_alias.get(key)


def cultivar_model_coefficients(cultivar_prior: Optional[CultivarPrior]) -> Dict[str, float]:
    if cultivar_prior is None:
        return {}
    return {k: float(v) for k, v in cultivar_prior.model_coefficients.items()}


def cultivar_bound_overrides(cultivar_prior: Optional[CultivarPrior]) -> Dict[str, BoundsOverride]:
    if cultivar_prior is None:
        return {}
    return dict(cultivar_prior.bound_overrides)


def cultivar_evidence_source_ids(cultivar_prior: Optional[CultivarPrior]) -> Tuple[str, ...]:
    if cultivar_prior is None:
        return tuple()
    return tuple(cultivar_prior.evidence_source_ids)


def resolve_cultivar(
    profile: GeneticProfile,
    cultivar_name: str | None,
    cultivar_family: str | None,
) -> Tuple[str, Optional[CultivarPrior]]:
    prior = get_cultivar_prior(cultivar_name)
    explicit_family = normalize_cultivar_family(profile, cultivar_family) if cultivar_family else None

    if prior is None:
        final_family = explicit_family or normalize_cultivar_family(profile, None)
        return final_family, None

    if prior.profile_ids and profile.profile_id not in prior.profile_ids:
        allowed = ", ".join(prior.profile_ids)
        raise ValueError(
            f"Cultivar '{prior.name}' is not configured for profile '{profile.profile_id}'. "
            f"Allowed profiles: {allowed}"
        )

    inferred_family = normalize_cultivar_family(profile, prior.family)
    if explicit_family and explicit_family != inferred_family:
        raise ValueError(
            f"Cultivar '{prior.name}' expects family '{inferred_family}', "
            f"but '{explicit_family}' was provided."
        )
    return inferred_family, prior


def validate_profile_cultivar_args(
    profile_id: str | None,
    cultivar_family: str | None,
    cultivar_name: str | None,
) -> Tuple[str, str, Optional[CultivarPrior]]:
    profile = get_genetic_profile(profile_id)
    resolved_family, prior = resolve_cultivar(
        profile=profile,
        cultivar_name=cultivar_name,
        cultivar_family=cultivar_family,
    )
    return profile.profile_id, resolved_family, prior


def get_genetic_profile(profile_id: str | None) -> GeneticProfile:
    return _profile_or_default(profile_id)
