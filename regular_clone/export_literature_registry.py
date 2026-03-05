from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import json

from core.genetics import (
    available_genetic_profiles,
    default_genetic_profile_id,
    profile_evidence_source_ids,
)
from core.literature import literature_sources_to_dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export curated literature sources used by the genetic profile configuration."
    )
    parser.add_argument(
        "--genetic-profile",
        choices=available_genetic_profiles(),
        default=default_genetic_profile_id(),
    )
    parser.add_argument("--out-json", default="runtime/logs/literature_registry.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_ids = profile_evidence_source_ids(args.genetic_profile)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "genetic_profile": args.genetic_profile,
        "source_ids": list(source_ids),
        "sources": literature_sources_to_dict(source_ids),
    }
    out_path = Path(args.out_json).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
