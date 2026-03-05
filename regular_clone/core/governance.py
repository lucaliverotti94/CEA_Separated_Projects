from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import hashlib
import json
import subprocess
import uuid


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dict_signature(payload: Dict) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def file_signature(path: str | Path) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit_short() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        value = out.stdout.strip()
        return value or "unknown"
    except Exception:
        return "unknown"


def new_run_id(prefix: str) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    token = uuid.uuid4().hex[:8]
    return f"{prefix}_{ts}_{token}"

