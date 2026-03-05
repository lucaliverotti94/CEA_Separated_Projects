from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
import json


@dataclass(frozen=True)
class LiteratureSource:
    source_id: str
    citation: str
    year: int
    doi: str
    url: str
    topics: Tuple[str, ...]
    evidence_scope: str
    notes: str
    variety_studied: str = "NR"
    propagation_mode: str = "NR"
    photoperiod_class: str = "NR"
    compatibility_regular: str = "ambiguous"
    discrepancy_notes: str = ""
    replacement_of: Tuple[str, ...] = ()


_SOURCES_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "literature_sources.json"


@lru_cache(maxsize=1)
def _sources_map() -> Dict[str, LiteratureSource]:
    raw = json.loads(_SOURCES_CONFIG.read_text(encoding="utf-8"))
    rows = raw.get("sources", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Invalid literature sources config: {_SOURCES_CONFIG}")

    out: Dict[str, LiteratureSource] = {}
    for item in rows:
        sid = str(item["source_id"]).strip()
        out[sid] = LiteratureSource(
            source_id=sid,
            citation=str(item["citation"]),
            year=int(item["year"]),
            doi=str(item["doi"]),
            url=str(item["url"]),
            topics=tuple(str(x) for x in item.get("topics", [])),
            evidence_scope=str(item.get("evidence_scope", "")),
            notes=str(item.get("notes", "")),
            variety_studied=str(item.get("variety_studied", "NR")),
            propagation_mode=str(item.get("propagation_mode", "NR")),
            photoperiod_class=str(item.get("photoperiod_class", "NR")),
            compatibility_regular=str(item.get("compatibility_regular", "ambiguous")),
            discrepancy_notes=str(item.get("discrepancy_notes", "")),
            replacement_of=tuple(str(x) for x in item.get("replacement_of", [])),
        )
    return out


def available_literature_sources() -> Tuple[str, ...]:
    return tuple(sorted(_sources_map().keys()))


def get_literature_source(source_id: str) -> LiteratureSource:
    sources = _sources_map()
    if source_id not in sources:
        supported = ", ".join(available_literature_sources())
        raise ValueError(f"Unknown literature source '{source_id}'. Available: {supported}")
    return sources[source_id]


def literature_sources_for_ids(source_ids: Iterable[str]) -> List[LiteratureSource]:
    out: List[LiteratureSource] = []
    seen = set()
    for sid in source_ids:
        sid_norm = str(sid)
        if sid_norm in seen:
            continue
        seen.add(sid_norm)
        out.append(get_literature_source(sid_norm))
    return out


def literature_sources_to_dict(source_ids: Iterable[str]) -> List[Dict[str, object]]:
    rows = []
    for src in literature_sources_for_ids(source_ids):
        row = asdict(src)
        row["topics"] = list(src.topics)
        row["replacement_of"] = list(src.replacement_of)
        rows.append(row)
    return rows
