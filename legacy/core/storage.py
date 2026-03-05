from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional
import json
import sqlite3


def _connect(db_path: str) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r["name"]) for r in rows}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
    cols = _table_columns(conn, table)
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def init_storage(db_path: str) -> None:
    with _connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS control_ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                mode TEXT,
                cycle_day INTEGER,
                stage TEXT,
                actions_json TEXT,
                sensor_json TEXT,
                baseline_json TEXT,
                recommended_json TEXT,
                source TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "control_ticks", "heuristic_json", "TEXT")
        _ensure_column(conn, "control_ticks", "fault_json", "TEXT")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_control_ticks_ts ON control_ticks(ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_control_ticks_mode_stage ON control_ticks(mode, stage)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS optimizer_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                mode TEXT,
                objective_value REAL,
                feasibility_violation REAL,
                dry_yield_g_m2 REAL,
                quality_index REAL,
                energy_kwh_m2 REAL,
                penalty REAL,
                disease_pressure REAL,
                hlvd_pressure REAL,
                payload_json TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "optimizer_runs", "run_id", "TEXT")
        _ensure_column(conn, "optimizer_runs", "profile_signature", "TEXT")
        _ensure_column(conn, "optimizer_runs", "git_commit", "TEXT")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_optimizer_runs_ts ON optimizer_runs(ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_optimizer_runs_mode ON optimizer_runs(mode)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_optimizer_runs_run_id ON optimizer_runs(run_id)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS twin_calibrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                name TEXT,
                train_loss REAL,
                val_loss REAL,
                params_json TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "twin_calibrations", "run_id", "TEXT")
        _ensure_column(conn, "twin_calibrations", "dataset_signature", "TEXT")
        _ensure_column(conn, "twin_calibrations", "git_commit", "TEXT")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_twin_calibrations_ts ON twin_calibrations(ts)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                severity TEXT,
                code TEXT,
                message TEXT,
                source TEXT,
                mode TEXT,
                stage TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alert_events_ts ON alert_events(ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alert_events_code ON alert_events(code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alert_events_severity ON alert_events(severity)")
        conn.commit()


def store_control_tick(db_path: str, payload: Dict, source: Optional[str] = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO control_ticks (
                ts, mode, cycle_day, stage, actions_json, sensor_json, baseline_json, recommended_json,
                heuristic_json, fault_json, source, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("ts"),
                payload.get("mode"),
                payload.get("cycle_day"),
                payload.get("stage"),
                json.dumps(payload.get("actions", []), ensure_ascii=False),
                json.dumps(payload.get("sensor", {}), ensure_ascii=False),
                json.dumps(payload.get("baseline_setpoint", {}), ensure_ascii=False),
                json.dumps(payload.get("recommended_setpoint", {}), ensure_ascii=False),
                json.dumps(payload.get("heuristic_setpoint", {}), ensure_ascii=False),
                json.dumps(payload.get("fault", {}), ensure_ascii=False),
                source or payload.get("source"),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()


def store_optimizer_run(db_path: str, result: Dict, ts: str) -> None:
    out = result.get("outcome", {}) if isinstance(result, dict) else {}
    governance = result.get("governance", {}) if isinstance(result, dict) else {}
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO optimizer_runs (
                ts, mode, objective_value, feasibility_violation, dry_yield_g_m2, quality_index,
                energy_kwh_m2, penalty, disease_pressure, hlvd_pressure, run_id, profile_signature, git_commit, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                result.get("mode"),
                result.get("objective_value"),
                result.get("feasibility_violation"),
                out.get("dry_yield_g_m2"),
                out.get("quality_index"),
                out.get("energy_kwh_m2"),
                out.get("penalty"),
                out.get("disease_pressure"),
                out.get("hlvd_pressure"),
                governance.get("run_id"),
                governance.get("profile_signature"),
                governance.get("git_commit"),
                json.dumps(result, ensure_ascii=False),
            ),
        )
        conn.commit()


def store_twin_calibration(
    db_path: str,
    ts: str,
    payload: Dict,
    name: Optional[str] = None,
    train_loss: Optional[float] = None,
    val_loss: Optional[float] = None,
) -> None:
    params = payload.get("calibration") if isinstance(payload, dict) else None
    governance = payload.get("governance", {}) if isinstance(payload, dict) else {}
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO twin_calibrations (
                ts, name, train_loss, val_loss, params_json, run_id, dataset_signature, git_commit, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                name,
                train_loss,
                val_loss,
                json.dumps(params or {}, ensure_ascii=False),
                governance.get("run_id"),
                governance.get("dataset_signature"),
                governance.get("git_commit"),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()


def store_alert_event(
    db_path: str,
    alert: Dict,
    source: Optional[str] = None,
    mode: Optional[str] = None,
    stage: Optional[str] = None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO alert_events (ts, severity, code, message, source, mode, stage, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert.get("ts"),
                alert.get("severity"),
                alert.get("code"),
                alert.get("message"),
                source or alert.get("source"),
                mode or alert.get("mode"),
                stage or alert.get("stage"),
                json.dumps(alert, ensure_ascii=False),
            ),
        )
        conn.commit()


def fetch_control_ticks(db_path: str, limit: int = 5000) -> List[Dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ts, mode, cycle_day, stage, actions_json, sensor_json, baseline_json, recommended_json, heuristic_json, fault_json, source
            FROM control_ticks
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    out: List[Dict] = []
    for r in reversed(rows):
        out.append(
            {
                "ts": r["ts"],
                "mode": r["mode"],
                "cycle_day": r["cycle_day"],
                "stage": r["stage"],
                "actions": json.loads(r["actions_json"] or "[]"),
                "sensor": json.loads(r["sensor_json"] or "{}"),
                "baseline_setpoint": json.loads(r["baseline_json"] or "{}"),
                "heuristic_setpoint": json.loads(r["heuristic_json"] or "{}"),
                "recommended_setpoint": json.loads(r["recommended_json"] or "{}"),
                "fault": json.loads(r["fault_json"] or "{}"),
                "source": r["source"],
            }
        )
    return out


def fetch_optimizer_runs(db_path: str, limit: int = 300) -> List[Dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ts, mode, objective_value, feasibility_violation, dry_yield_g_m2, quality_index,
                   energy_kwh_m2, penalty, disease_pressure, hlvd_pressure, run_id, profile_signature, git_commit
            FROM optimizer_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def fetch_calibrations(db_path: str, limit: int = 30) -> List[Dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ts, name, train_loss, val_loss, params_json, run_id, dataset_signature, git_commit
            FROM twin_calibrations
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    out: List[Dict] = []
    for r in reversed(rows):
        row = dict(r)
        row["params"] = json.loads(row.pop("params_json") or "{}")
        out.append(row)
    return out


def fetch_alert_events(db_path: str, limit: int = 1000) -> List[Dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ts, severity, code, message, source, mode, stage, payload_json
            FROM alert_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    out: List[Dict] = []
    for r in reversed(rows):
        row = dict(r)
        row["payload"] = json.loads(row.pop("payload_json") or "{}")
        out.append(row)
    return out
