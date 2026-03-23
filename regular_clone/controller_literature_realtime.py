from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional
import argparse
import json
import sys
import time

from core.genetics import (
    available_cultivar_families,
    available_genetic_profiles,
    default_genetic_profile_id,
    validate_profile_cultivar_args,
)
from core.alerting import AlertThresholds, OperationalAlertMonitor
from core.governance import dict_signature, git_commit_short, new_run_id
from core.model import AdaptiveController, CEADigitalTwin, SensorState, profile_to_dict
from core.mpc_supervisor import MPCConfig, MPCSupervisor, enforce_setpoint_limits
from core.sensor_quality import evaluate_sensor_quality
from core.storage import init_storage, store_alert_event, store_control_tick, store_optimizer_run
from core.realtime_io import (
    DEFAULT_ENERGY_CAP_KWH_M2,
    DEFAULT_FARM_ACTIVE_AREA_M2,
    DEFAULT_YIELD_TARGET_ANNUAL_KG,
    SerialActuatorSink,
    _iso_now,
    _parse_iso_date,
    _profile_from_export_dict,
    build_source,
    day_idx_from_start,
    emit_safe_fallback_tick,
    emit_output,
    is_source_event_payload,
    load_profile,
    projected_annual_yield_from_profile,
    resolve_profile_energy_kwh_m2_cycle,
    resolve_runtime_energy_cap,
    resolve_runtime_yield_target,
    resolve_stage_for_day,
    sensor_payload_to_state,
    source_event_kind,
)
from optimizer_literature_best import DEFAULT_QUALITY_FLOOR, run_mode

RUNTIME_MODE_BASE = {
    "max_yield": "max_yield",
    "max_quality": "max_quality",
    "max_yield_energy": "max_yield",
    "max_quality_energy": "max_quality",
}
POWER_OBSERVABILITY_FIELDS = ("power_total_kw", "power_led_kw", "power_hvac_kw", "power_pumps_kw")


def _runtime_base_mode(mode: str) -> str:
    if mode not in RUNTIME_MODE_BASE:
        raise ValueError(
            "mode must be one of: max_yield, max_quality, max_yield_energy, max_quality_energy"
        )
    return RUNTIME_MODE_BASE[mode]


def _build_profile_from_literature(mode: str, args: argparse.Namespace) -> Dict:
    opt_args = SimpleNamespace(
        quality_y_min=args.quality_y_min,
        quality_floor=args.quality_floor,
        energy_cap_kwh_m2=args.energy_cap_kwh_m2,
        yield_target_annual_kg=args.yield_target_annual_kg,
        farm_active_area_m2=args.farm_active_area_m2,
        n_init=args.opt_n_init,
        n_iter=args.opt_n_iter,
        pool_size=args.opt_pool_size,
        seed=args.opt_seed,
        yield_restarts=args.yield_restarts,
        yield_robust_evals=args.yield_robust_evals,
        quality_restarts=args.quality_restarts,
        ensemble_evals=args.opt_ensemble_evals,
        twin_calibration_json=args.twin_calibration_json,
        genetic_profile=args.genetic_profile,
        cultivar_family=args.cultivar_family,
        cultivar_name=args.cultivar_name,
    )
    return run_mode(mode=mode, args=opt_args)


def _extract_power_observability(payload: Dict) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for key in POWER_OBSERVABILITY_FIELDS:
        if key not in payload:
            continue
        try:
            out[key] = float(payload[key])
        except Exception:
            continue
    return out


def _validate_profile_quality_floor(profile, control_mode: str, quality_floor: float) -> float | None:
    if control_mode != "max_yield":
        return None
    floor = float(quality_floor)
    if floor <= 0.0:
        raise ValueError("quality_floor must be > 0")
    twin_q = CEADigitalTwin(random_seed=2026, sanitation_level=0.94)
    quality_out = twin_q.simulate_cycle(profile=profile, mode=control_mode)
    projected_cycle_quality_index = float(quality_out.quality_index)
    if projected_cycle_quality_index < floor - 1e-9:
        raise ValueError(
            "Profile violates quality floor for max_yield runtime: "
            f"{projected_cycle_quality_index:.3f} < {floor:.3f}. "
            "Lower --quality-floor or regenerate/provide a higher-quality profile."
        )
    return projected_cycle_quality_index


def _write_generated_profile(path: Path, result: Dict) -> None:
    payload = {
        "generated_at": _iso_now(),
        "generator": "controller_literature_realtime",
        "results": [result],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Realtime closed-loop controller based on optimizer_literature_best profile. "
            "If --profile-json is omitted, the profile is auto-optimized first."
        )
    )

    parser.add_argument(
        "--mode",
        choices=["max_yield", "max_quality", "max_yield_energy", "max_quality_energy"],
        default="max_yield",
    )

    parser.add_argument(
        "--source",
        choices=["jsonl_file", "stdin_json", "http_poll", "serial_json", "mock_stream"],
        default="serial_json",
        help="Sensor source type.",
    )
    parser.add_argument("--input-path", default="runtime/jsonl/sensor_stream.jsonl", help="Input JSONL path for --source jsonl_file.")
    parser.add_argument("--http-url", default=None, help="HTTP endpoint for --source http_poll.")
    parser.add_argument("--serial-port", default=None, help="Serial port for --source serial_json, e.g. COM4")
    parser.add_argument("--serial-baud", type=int, default=115200, help="Serial baudrate for --source serial_json.")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--mock-seed", type=int, default=1337, help="Seed used when --source mock_stream.")
    parser.add_argument("--mock-noise-scale", type=float, default=1.0, help="Noise scaling for --source mock_stream.")

    parser.add_argument(
        "--profile-json",
        default=None,
        help="Optional existing profile JSON. If omitted, profile is generated by literature optimizer.",
    )
    parser.add_argument(
        "--genetic-profile",
        choices=available_genetic_profiles(),
        default=default_genetic_profile_id(),
        help="Genetic profile used for auto-optimization and default profiles.",
    )
    parser.add_argument(
        "--cultivar-family",
        choices=available_cultivar_families(),
        default=None,
        help="Optional cultivar family prior (hybrid/sativa_dominant/indica_dominant).",
    )
    parser.add_argument("--cultivar-name", default="", help="Optional cultivar tag stored in profile metadata.")
    parser.add_argument(
        "--save-generated-profile",
        default="runtime/profiles/literature_best_profile_runtime.json",
        help="Path where generated profile payload is saved when auto-optimizing.",
    )

    parser.add_argument("--quality-y-min", type=float, default=1300.0, help="Yield floor for max_quality optimization.")
    parser.add_argument(
        "--quality-floor",
        type=float,
        default=DEFAULT_QUALITY_FLOOR,
        help="Minimum quality index for max_yield/max_yield_energy modes.",
    )
    parser.add_argument(
        "--energy-cap-kwh-m2",
        type=float,
        default=DEFAULT_ENERGY_CAP_KWH_M2,
        help="Hard energy cap (kWh/m2 per cycle) for *_energy modes.",
    )
    parser.add_argument(
        "--yield-target-annual-kg",
        "--yield-cap-annual-kg",
        dest="yield_target_annual_kg",
        type=float,
        default=DEFAULT_YIELD_TARGET_ANNUAL_KG,
        help="Exact annual farm yield target (kg/year).",
    )
    parser.add_argument(
        "--farm-active-area-m2",
        type=float,
        default=DEFAULT_FARM_ACTIVE_AREA_M2,
        help="Available active productive area (m2) used to verify exact annual target feasibility.",
    )
    parser.add_argument("--opt-n-init", type=int, default=20)
    parser.add_argument("--opt-n-iter", type=int, default=24)
    parser.add_argument("--opt-pool-size", type=int, default=1800)
    parser.add_argument("--opt-seed", type=int, default=2026)
    parser.add_argument("--yield-restarts", type=int, default=4)
    parser.add_argument("--yield-robust-evals", type=int, default=8)
    parser.add_argument("--quality-restarts", type=int, default=4)
    parser.add_argument("--opt-ensemble-evals", type=int, default=8, help="Uncertainty evals during auto profile generation.")
    parser.add_argument("--twin-calibration-json", default=None, help="Optional twin calibration JSON used by optimizer.")
    parser.add_argument(
        "--use-mpc-supervisor",
        action="store_true",
        help="Enable receding-horizon MPC supervisor on top of heuristic adjustments.",
    )
    parser.add_argument("--mpc-horizon", type=int, default=6, help="MPC prediction horizon in control ticks.")
    parser.add_argument("--mpc-candidates", type=int, default=96, help="Number of candidate setpoints sampled per tick.")
    parser.add_argument("--mpc-seed", type=int, default=2026, help="Random seed for MPC candidate sampling.")

    parser.add_argument(
        "--start-date",
        default=datetime.now().date().isoformat(),
        help="Cycle start date in YYYY-MM-DD. Used to determine active stage.",
    )

    parser.add_argument("--out-jsonl", default="runtime/jsonl/control_output_literature_realtime.jsonl")
    parser.add_argument("--store-db", default="runtime/db/cea_timeseries.db", help="SQLite file for telemetry and optimizer runs.")
    parser.add_argument("--actuator-post-url", default=None, help="Optional HTTP endpoint for actuator commands (POST JSON).")
    parser.add_argument("--actuator-serial-port", default=None, help="Optional serial port for actuator commands.")
    parser.add_argument("--actuator-serial-baud", type=int, default=115200)
    parser.add_argument(
        "--watchdog-timeout-s",
        type=float,
        default=0.0,
        help="If > 0, emit safe fallback when no valid sensor payload arrives within this timeout.",
    )
    parser.add_argument(
        "--no-safe-fallback",
        action="store_true",
        help="Disable safe fallback setpoint emission on sensor/communication faults.",
    )
    parser.add_argument("--alert-window-ticks", type=int, default=60, help="Rolling window used for operational alerting.")
    parser.add_argument(
        "--alert-fallback-rate-threshold",
        type=float,
        default=0.15,
        help="Emit alert when fallback_rate in rolling window exceeds this threshold.",
    )
    parser.add_argument(
        "--alert-timeout-count-threshold",
        type=int,
        default=3,
        help="Emit alert when timeout-derived fallback count in rolling window exceeds this threshold.",
    )
    parser.add_argument(
        "--alert-payload-error-count-threshold",
        type=int,
        default=3,
        help="Emit alert when payload/source error count in rolling window exceeds this threshold.",
    )
    parser.add_argument(
        "--alert-quality-fault-count-threshold",
        type=int,
        default=3,
        help="Emit alert when hard sensor-quality fault count in rolling window exceeds this threshold.",
    )
    parser.add_argument("--alert-cooldown-ticks", type=int, default=30, help="Cooldown ticks between repeated alerts of same code.")
    parser.add_argument("--max-samples", type=int, default=0, help="Stop after N samples (0 = run forever).")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    control_mode = _runtime_base_mode(args.mode)
    if not args.profile_json:
        try:
            norm_profile, norm_family, prior = validate_profile_cultivar_args(
                profile_id=args.genetic_profile,
                cultivar_family=args.cultivar_family,
                cultivar_name=args.cultivar_name,
            )
        except ValueError as exc:
            raise SystemExit(str(exc))
        args.genetic_profile = norm_profile
        args.cultivar_family = norm_family
        if prior is not None and not str(args.cultivar_name).strip():
            args.cultivar_name = prior.name

    start_date = _parse_iso_date(args.start_date)
    try:
        yield_target_annual_kg, farm_active_area_m2, yield_target_kg_m2_year = resolve_runtime_yield_target(
            yield_target_annual_kg=float(args.yield_target_annual_kg),
            farm_active_area_m2=float(args.farm_active_area_m2),
        )
        energy_constraint_active, energy_cap_kwh_m2 = resolve_runtime_energy_cap(
            mode=args.mode,
            energy_cap_kwh_m2=float(args.energy_cap_kwh_m2),
        )
    except ValueError as exc:
        raise SystemExit(str(exc))

    profile_source: str
    generation_meta: Optional[Dict] = None
    if args.store_db:
        init_storage(args.store_db)
    if args.profile_json:
        profile = load_profile(
            mode=args.mode,
            profile_json=args.profile_json,
            genetic_profile=args.genetic_profile,
            cultivar_family=args.cultivar_family,
            cultivar_name=args.cultivar_name,
        )
        profile_source = args.profile_json
    else:
        generation_meta = _build_profile_from_literature(mode=args.mode, args=args)
        profile = _profile_from_export_dict(generation_meta["profile"])
        save_path = Path(args.save_generated_profile)
        _write_generated_profile(save_path, generation_meta)
        profile_source = str(save_path)
        if args.store_db:
            store_optimizer_run(db_path=args.store_db, result=generation_meta, ts=_iso_now())

    controller = AdaptiveController(mode=control_mode)
    runtime_run_id = new_run_id("rt")
    profile_signature = dict_signature(profile_to_dict(profile))
    _, projected_metrics = projected_annual_yield_from_profile(
        profile=profile,
        mode_base=control_mode,
        farm_active_area_m2=farm_active_area_m2,
    )
    if isinstance(generation_meta, dict):
        derived_meta = (((generation_meta.get("outcome") or {}).get("derived_metrics")) or {})
        try:
            profile_yield_kg_m2_year = float(derived_meta.get("dry_yield_kg_m2_year"))
            projected_metrics = dict(derived_meta)
        except Exception:
            profile_yield_kg_m2_year = float(projected_metrics.get("dry_yield_kg_m2_year", 0.0))
    else:
        profile_yield_kg_m2_year = float(projected_metrics.get("dry_yield_kg_m2_year", 0.0))
    required_active_area_m2_for_target = float(yield_target_annual_kg) / max(profile_yield_kg_m2_year, 1e-9)
    if required_active_area_m2_for_target > float(farm_active_area_m2) + 1e-9:
        raise SystemExit(
            "Profile cannot satisfy exact annual yield target with available active area: "
            f"required_area={required_active_area_m2_for_target:.3f} m2 > available_area={farm_active_area_m2:.3f} m2. "
            "Increase --farm-active-area-m2 or reduce --yield-target-annual-kg."
        )
    projected_annual_yield_kg = float(yield_target_annual_kg)
    try:
        profile_energy_kwh_m2 = resolve_profile_energy_kwh_m2_cycle(projected_metrics)
    except ValueError as exc:
        raise SystemExit(str(exc))
    if energy_constraint_active and profile_energy_kwh_m2 > energy_cap_kwh_m2 + 1e-9:
        raise SystemExit(
            "Profile violates hard cycle energy cap: "
            f"{profile_energy_kwh_m2:.3f} kWh/m2 > {energy_cap_kwh_m2:.3f} kWh/m2. "
            "Raise --energy-cap-kwh-m2 or regenerate/provide a lower-energy profile."
        )
    try:
        projected_cycle_quality_index = _validate_profile_quality_floor(
            profile=profile,
            control_mode=control_mode,
            quality_floor=float(args.quality_floor),
        )
    except ValueError as exc:
        raise SystemExit(str(exc))
    mpc_supervisor: Optional[MPCSupervisor] = None
    if args.use_mpc_supervisor:
        mpc_supervisor = MPCSupervisor(
            mode=control_mode,
            config=MPCConfig(
                horizon_steps=max(1, int(args.mpc_horizon)),
                candidate_samples=max(1, int(args.mpc_candidates)),
                random_seed=int(args.mpc_seed),
            ),
        )
    emit_source_events = args.watchdog_timeout_s > 0.0 or not args.no_safe_fallback
    source_iter = build_source(args, emit_source_events=emit_source_events)

    actuator_serial_sink: Optional[SerialActuatorSink] = None
    if args.actuator_serial_port:
        actuator_serial_sink = SerialActuatorSink(
            port=args.actuator_serial_port,
            baud=args.actuator_serial_baud,
        )

    prev_disease = 0.0
    prev_hlvd = 0.0
    prev_sensor_quality_ref: Optional[SensorState] = None
    last_valid_payload_ts = time.monotonic()
    watchdog_tripped = False
    alert_monitor = OperationalAlertMonitor(
        thresholds=AlertThresholds(
            window_ticks=max(1, int(args.alert_window_ticks)),
            fallback_rate_threshold=float(args.alert_fallback_rate_threshold),
            timeout_count_threshold=max(1, int(args.alert_timeout_count_threshold)),
            payload_error_count_threshold=max(1, int(args.alert_payload_error_count_threshold)),
            quality_fault_count_threshold=max(1, int(args.alert_quality_fault_count_threshold)),
            cooldown_ticks=max(1, int(args.alert_cooldown_ticks)),
        )
    )

    def _emit_alert(alert: Dict) -> None:
        print(json.dumps(alert, ensure_ascii=False), file=sys.stderr)
        if args.store_db:
            store_alert_event(
                db_path=args.store_db,
                alert=alert,
                source=args.source,
                mode=args.mode,
                stage=str(alert.get("stage", "")),
            )

    def _emit_rolling_alerts(actions: list[str], stage: str, fault_kind: str = "") -> None:
        alerts = alert_monitor.observe(
            mode=args.mode,
            stage=stage,
            source=args.source,
            actions=actions,
            fault_kind=fault_kind,
        )
        for alert in alerts:
            _emit_alert(alert)

    start_event = {
        "event": "controller_started",
        "ts": _iso_now(),
        "mode": args.mode,
        "mode_base": control_mode,
        "source": args.source,
        "start_date": start_date.isoformat(),
        "profile_source": profile_source,
        "genetic_profile": args.genetic_profile,
        "cultivar_family": str(profile.metadata.get("cultivar_family", args.cultivar_family or "")),
        "cultivar_name": str(profile.metadata.get("cultivar_name", args.cultivar_name or "")),
        "run_id": runtime_run_id,
        "git_commit": git_commit_short(),
        "profile_signature": profile_signature,
        "stages": profile.stage_days,
        "yield_target_annual_kg": float(yield_target_annual_kg),
        "farm_active_area_m2": float(farm_active_area_m2),
        "yield_target_kg_m2_year": float(yield_target_kg_m2_year),
        "yield_cap_annual_kg": float(yield_target_annual_kg),
        "yield_cap_kg_m2_year": float(yield_target_kg_m2_year),
        "projected_annual_yield_kg": float(projected_annual_yield_kg),
        "projected_annual_yield_kg_m2": float(projected_metrics.get("dry_yield_kg_m2_year", 0.0)),
        "planned_active_area_m2_for_target": float(required_active_area_m2_for_target),
        "planned_active_area_utilization_frac": float(required_active_area_m2_for_target / max(float(farm_active_area_m2), 1e-9)),
        "projected_cycle_energy_kwh_m2": float(profile_energy_kwh_m2),
        "projected_cycle_quality_index": float(projected_cycle_quality_index) if projected_cycle_quality_index is not None else None,
        "energy_constraint_active": bool(energy_constraint_active),
        "energy_cap_kwh_m2": float(energy_cap_kwh_m2) if energy_constraint_active else None,
        "quality_floor": float(args.quality_floor) if control_mode == "max_yield" else None,
    }
    if generation_meta is not None:
        start_event["generation_meta"] = {
            "objective_value": generation_meta.get("objective_value"),
            "feasibility_violation": generation_meta.get("feasibility_violation"),
            "search_meta": generation_meta.get("search_meta"),
        }
    print(json.dumps(start_event, ensure_ascii=False))

    processed = 0
    for payload in source_iter:
        now_dt = datetime.now()
        day_idx = day_idx_from_start(start_date=start_date, now_dt=now_dt)
        stage = resolve_stage_for_day(profile=profile, day_idx=day_idx)

        baseline = profile.stage_setpoints[stage]
        if is_source_event_payload(payload):
            kind = source_event_kind(payload)
            elapsed = time.monotonic() - last_valid_payload_ts
            fallback_out: Optional[Dict] = None
            if args.watchdog_timeout_s > 0.0 and elapsed >= args.watchdog_timeout_s and not watchdog_tripped:
                fallback_out = emit_safe_fallback_tick(
                    mode=args.mode,
                    day_idx=day_idx,
                    stage=stage,
                    baseline=baseline,
                    reason="safe_fallback_watchdog_timeout",
                    fault={
                        "kind": kind,
                        "source": payload.get("_source", ""),
                        "elapsed_s": round(float(elapsed), 2),
                        "watchdog_timeout_s": float(args.watchdog_timeout_s),
                    },
                    out_jsonl=args.out_jsonl,
                    actuator_post_url=args.actuator_post_url,
                    actuator_serial_sink=actuator_serial_sink,
                )
                watchdog_tripped = True
            elif kind == "error" and not args.no_safe_fallback:
                fallback_out = emit_safe_fallback_tick(
                    mode=args.mode,
                    day_idx=day_idx,
                    stage=stage,
                    baseline=baseline,
                    reason="safe_fallback_source_error",
                    fault={
                        "kind": kind,
                        "source": payload.get("_source", ""),
                        "message": payload.get("message", ""),
                    },
                    out_jsonl=args.out_jsonl,
                    actuator_post_url=args.actuator_post_url,
                    actuator_serial_sink=actuator_serial_sink,
                )
            if fallback_out is not None:
                _emit_rolling_alerts(
                    actions=list(fallback_out.get("actions", [])),
                    stage=stage,
                    fault_kind=str((fallback_out.get("fault") or {}).get("kind", "")),
                )
                if args.store_db:
                    store_control_tick(db_path=args.store_db, payload=fallback_out, source=args.source)
            processed += 1
            if args.max_samples > 0 and processed >= args.max_samples:
                break
            continue

        try:
            sensor_state = sensor_payload_to_state(
                payload=payload,
                stage_photoperiod_h=baseline.photoperiod_h,
                prev_disease_pressure=prev_disease,
                prev_hlvd_pressure=prev_hlvd,
            )
        except ValueError as exc:
            print(
                json.dumps({"event": "sensor_payload_error", "error": str(exc), "payload": payload}, ensure_ascii=False),
                file=sys.stderr,
            )
            _emit_alert(
                {
                    "event": "operational_alert",
                    "ts": _iso_now(),
                    "code": "sensor_payload_error",
                    "severity": "warning",
                    "message": f"Invalid sensor payload: {exc}",
                    "mode": args.mode,
                    "stage": stage,
                    "source": args.source,
                }
            )
            if not args.no_safe_fallback:
                fallback_out = emit_safe_fallback_tick(
                    mode=args.mode,
                    day_idx=day_idx,
                    stage=stage,
                    baseline=baseline,
                    reason="safe_fallback_sensor_payload_error",
                    fault={"kind": "sensor_payload_error", "error": str(exc)},
                    out_jsonl=args.out_jsonl,
                    actuator_post_url=args.actuator_post_url,
                    actuator_serial_sink=actuator_serial_sink,
                )
                _emit_rolling_alerts(
                    actions=list(fallback_out.get("actions", [])),
                    stage=stage,
                    fault_kind=str((fallback_out.get("fault") or {}).get("kind", "")),
                )
                if args.store_db:
                    store_control_tick(db_path=args.store_db, payload=fallback_out, source=args.source)
            processed += 1
            if args.max_samples > 0 and processed >= args.max_samples:
                break
            continue

        quality = evaluate_sensor_quality(sensor=sensor_state, prev_sensor=prev_sensor_quality_ref)
        if quality.is_hard_fault:
            _emit_alert(
                {
                    "event": "operational_alert",
                    "ts": _iso_now(),
                    "code": "sensor_quality_hard_fault",
                    "severity": "critical",
                    "message": "Hard sensor quality fault detected; control tick rejected.",
                    "mode": args.mode,
                    "stage": stage,
                    "source": args.source,
                    "hard_faults": list(quality.hard_faults),
                }
            )
            if not args.no_safe_fallback:
                fallback_out = emit_safe_fallback_tick(
                    mode=args.mode,
                    day_idx=day_idx,
                    stage=stage,
                    baseline=baseline,
                    reason="safe_fallback_sensor_quality_fault",
                    fault={"kind": "sensor_quality", "hard_faults": list(quality.hard_faults)},
                    out_jsonl=args.out_jsonl,
                    actuator_post_url=args.actuator_post_url,
                    actuator_serial_sink=actuator_serial_sink,
                )
                _emit_rolling_alerts(
                    actions=list(fallback_out.get("actions", [])),
                    stage=stage,
                    fault_kind="sensor_quality",
                )
                if args.store_db:
                    store_control_tick(db_path=args.store_db, payload=fallback_out, source=args.source)
            processed += 1
            if args.max_samples > 0 and processed >= args.max_samples:
                break
            continue

        heuristic_recommended, actions = controller.adjust(stage=stage, baseline=baseline, sensor=sensor_state)
        if quality.warnings:
            actions = list(actions) + ["sensor_quality_warning"]
        recommended = enforce_setpoint_limits(candidate=heuristic_recommended, sensor=sensor_state)
        if asdict(recommended) != asdict(heuristic_recommended):
            actions = list(actions) + ["enforce_limits"]
        mpc_meta: Optional[Dict] = None
        if mpc_supervisor is not None:
            recommended, mpc_meta = mpc_supervisor.optimize(
                stage=stage,
                baseline=baseline,
                heuristic=heuristic_recommended,
                sensor=sensor_state,
            )
            actions = list(actions) + ["mpc_supervisor"]

        out = {
            "event": "control_tick",
            "ts": _iso_now(),
            "mode": args.mode,
            "cycle_day": day_idx,
            "stage": stage,
            "actions": actions,
            "sensor": asdict(sensor_state),
            "baseline_setpoint": asdict(baseline),
            "heuristic_setpoint": asdict(heuristic_recommended),
            "recommended_setpoint": asdict(recommended),
            "sensor_quality": {
                "score": quality.score,
                "warnings": list(quality.warnings),
                "hard_faults": list(quality.hard_faults),
            },
            "governance": {
                "run_id": runtime_run_id,
                "profile_signature": profile_signature,
            },
        }
        power_obs = _extract_power_observability(payload)
        if power_obs:
            out["energy_observability_kw"] = power_obs
        if mpc_meta is not None:
            out["mpc"] = mpc_meta
        emit_output(
            out,
            out_jsonl=args.out_jsonl,
            actuator_post_url=args.actuator_post_url,
            actuator_serial_sink=actuator_serial_sink,
        )
        if args.store_db:
            store_control_tick(db_path=args.store_db, payload=out, source=args.source)
        _emit_rolling_alerts(actions=list(out.get("actions", [])), stage=stage)

        prev_disease = sensor_state.disease_pressure
        prev_hlvd = sensor_state.hlvd_pressure
        prev_sensor_quality_ref = sensor_state
        last_valid_payload_ts = time.monotonic()
        watchdog_tripped = False

        processed += 1
        if args.max_samples > 0 and processed >= args.max_samples:
            break

    if actuator_serial_sink:
        actuator_serial_sink.close()


if __name__ == "__main__":
    main()
