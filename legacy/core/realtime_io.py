from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Generator, Iterable, Optional
import argparse
import json
import random
import sys
import time
from urllib import request, error

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[1]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from core.alerting import AlertThresholds, OperationalAlertMonitor
from core.genetics import (
    DEFAULT_GENETIC_PROFILE_ID,
    available_cultivar_families,
    available_genetic_profiles,
    default_genetic_profile_id,
    validate_profile_cultivar_args,
)
from core.governance import dict_signature, git_commit_short, new_run_id
from core.mpc_supervisor import enforce_setpoint_limits
from core.model import (
    STAGE_ORDER,
    AdaptiveController,
    SensorState,
    StageSetpoint,
    StrategyBuilder,
    StrategyProfile,
    _dli_mol,
    profile_to_dict,
    _vpd_kpa,
)
from core.sensor_quality import evaluate_sensor_quality
from core.storage import init_storage, store_alert_event, store_control_tick


REQUIRED_SENSOR_FIELDS = (
    "t_air_c",
    "rh_pct",
    "co2_ppm",
    "ppfd",
    "t_solution_c",
    "do_mg_l",
    "ec_ms_cm",
    "ph",
)

SOURCE_EVENT_KEY = "_source_event"


def _source_event(kind: str, source: str, message: str = "") -> Dict[str, str]:
    evt = {SOURCE_EVENT_KEY: kind, "_source": source, "_event_ts": _iso_now()}
    if message:
        evt["message"] = message
    return evt


def is_source_event_payload(payload: Dict) -> bool:
    return SOURCE_EVENT_KEY in payload


def source_event_kind(payload: Dict) -> str:
    return str(payload.get(SOURCE_EVENT_KEY, "")).strip().lower()


def safe_fallback_setpoint(baseline: StageSetpoint) -> StageSetpoint:
    # Conservative recipe used when sensor stream is unavailable or invalid.
    return StageSetpoint(
        ppfd=min(max(baseline.ppfd, 220.0), 600.0),
        photoperiod_h=baseline.photoperiod_h,
        t_air_c=min(max(baseline.t_air_c, 22.0), 26.0),
        rh_pct=min(max(baseline.rh_pct, 55.0), 68.0),
        co2_ppm=min(max(baseline.co2_ppm, 420.0), 700.0),
        t_solution_c=min(max(baseline.t_solution_c, 18.0), 21.0),
        do_mg_l=max(baseline.do_mg_l, 7.5),
        ec_ms_cm=min(max(baseline.ec_ms_cm, 1.2), 2.0),
        ph=min(max(baseline.ph, 5.7), 6.1),
        n_mg_l=baseline.n_mg_l,
        p_mg_l=baseline.p_mg_l,
        k_mg_l=baseline.k_mg_l,
        blue_frac=baseline.blue_frac,
        red_frac=baseline.red_frac,
        far_red_frac=baseline.far_red_frac,
        uvb_frac=baseline.uvb_frac,
        airflow_m_s=max(baseline.airflow_m_s, 0.45),
    )


def _clamp(value: float, lo: float, hi: float) -> float:
    return float(min(max(value, lo), hi))


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _to_float(v: object, key: str) -> float:
    try:
        return float(v)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Field '{key}' is not numeric: {v!r}") from exc


def _parse_iso_date(s: str) -> date:
    try:
        return datetime.fromisoformat(s).date()
    except ValueError as exc:
        raise ValueError(f"Invalid date '{s}'. Use YYYY-MM-DD.") from exc


def _load_json(path: Path) -> Dict:
    # Use utf-8-sig so BOM-prefixed JSON files from Windows tools are accepted.
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _extract_profile_dict(raw: Dict, mode: str) -> Dict:
    # Case A: direct profile dict with stage keys.
    if all(stage in raw for stage in STAGE_ORDER):
        return raw

    # Case B: payload containing profile.
    if "profile" in raw and isinstance(raw["profile"], dict):
        p = raw["profile"]
        if all(stage in p for stage in STAGE_ORDER):
            return p

    # Case C: optimizer full payload with results list.
    if "results" in raw and isinstance(raw["results"], list):
        for item in raw["results"]:
            if isinstance(item, dict) and item.get("mode") == mode:
                p = item.get("profile")
                if isinstance(p, dict) and all(stage in p for stage in STAGE_ORDER):
                    return p

    raise ValueError(
        "Could not find a valid profile in JSON. Expected one of: "
        "{stage->setpoint}, {'profile': ...}, or {'results':[{'mode':..., 'profile':...}]}."
    )


def _profile_from_export_dict(profile_dict: Dict) -> StrategyProfile:
    stage_days: Dict[str, int] = {}
    stage_setpoints: Dict[str, StageSetpoint] = {}

    for stage in STAGE_ORDER:
        row = profile_dict.get(stage)
        if not isinstance(row, dict):
            raise ValueError(f"Missing stage '{stage}' in profile.")

        try:
            stage_days[stage] = int(row["days"])
            stage_setpoints[stage] = StageSetpoint(
                ppfd=float(row["ppfd"]),
                photoperiod_h=float(row["photoperiod_h"]),
                t_air_c=float(row["t_air_c"]),
                rh_pct=float(row["rh_pct"]),
                co2_ppm=float(row["co2_ppm"]),
                t_solution_c=float(row["t_solution_c"]),
                do_mg_l=float(row["do_mg_l"]),
                ec_ms_cm=float(row["ec_ms_cm"]),
                ph=float(row["ph"]),
                n_mg_l=float(row["n_mg_l"]),
                p_mg_l=float(row["p_mg_l"]),
                k_mg_l=float(row["k_mg_l"]),
                blue_frac=float(row["blue_frac"]),
                red_frac=float(row["red_frac"]),
                far_red_frac=float(row["far_red_frac"]),
                uvb_frac=float(row["uvb_frac"]),
                airflow_m_s=float(row["airflow_m_s"]),
            )
        except KeyError as exc:
            raise ValueError(f"Stage '{stage}' is missing field: {exc}") from exc

    metadata: Dict[str, float | str | bool] = {"source": "external_profile_json"}
    maybe_meta = profile_dict.get("_metadata")
    if isinstance(maybe_meta, dict):
        for k, v in maybe_meta.items():
            if isinstance(v, (str, bool, int, float)):
                metadata[str(k)] = v

    return StrategyProfile(
        stage_days=stage_days,
        stage_setpoints=stage_setpoints,
        metadata=metadata,
    )


def _default_profile(
    mode: str,
    genetic_profile: str = DEFAULT_GENETIC_PROFILE_ID,
    cultivar_family: str | None = None,
    cultivar_name: str = "",
) -> StrategyProfile:
    builder = StrategyBuilder(
        genetic_profile_id=genetic_profile,
        cultivar_family=cultivar_family,
        cultivar_name=cultivar_name,
    )
    params = {
        k: (b.lo + b.hi) / 2.0 for k, b in builder.parameter_bounds().items()
    }
    # Conservative defaults for first deployment.
    params["flower_ppfd"] = min(params["flower_ppfd"], 1200.0)
    params["co2_flower_ppm"] = 700.0
    params["flower_photoperiod_h"] = 12.2
    params["veg_days"] = 25.0
    params["flower_total_days"] = 60.0
    params["flower_early_days"] = 30.0
    return builder.build(p=params, mode=mode)


def load_profile(
    mode: str,
    profile_json: Optional[str],
    genetic_profile: str = DEFAULT_GENETIC_PROFILE_ID,
    cultivar_family: str | None = None,
    cultivar_name: str = "",
) -> StrategyProfile:
    if not profile_json:
        return _default_profile(
            mode=mode,
            genetic_profile=genetic_profile,
            cultivar_family=cultivar_family,
            cultivar_name=cultivar_name,
        )

    raw = _load_json(Path(profile_json))
    p = _extract_profile_dict(raw, mode=mode)
    return _profile_from_export_dict(p)


def resolve_stage_for_day(profile: StrategyProfile, day_idx: int) -> str:
    cumsum = 0
    for stage in STAGE_ORDER:
        cumsum += int(profile.stage_days[stage])
        if day_idx <= cumsum:
            return stage
    return STAGE_ORDER[-1]


def day_idx_from_start(start_date: date, now_dt: datetime) -> int:
    return max((now_dt.date() - start_date).days + 1, 1)

def sensor_payload_to_state(
    payload: Dict,
    stage_photoperiod_h: float,
    prev_disease_pressure: float,
    prev_hlvd_pressure: float,
) -> SensorState:
    for k in REQUIRED_SENSOR_FIELDS:
        if k not in payload:
            raise ValueError(f"Missing sensor field '{k}'")

    t_air_c = _to_float(payload["t_air_c"], "t_air_c")
    rh_pct = _to_float(payload["rh_pct"], "rh_pct")
    co2_ppm = _to_float(payload["co2_ppm"], "co2_ppm")
    ppfd = _to_float(payload["ppfd"], "ppfd")
    t_solution_c = _to_float(payload["t_solution_c"], "t_solution_c")
    do_mg_l = _to_float(payload["do_mg_l"], "do_mg_l")
    ec_ms_cm = _to_float(payload["ec_ms_cm"], "ec_ms_cm")
    ph = _to_float(payload["ph"], "ph")

    transp = _to_float(payload.get("transpiration_l_m2_day", 2.4), "transpiration_l_m2_day")
    dli_prev = _to_float(payload.get("dli_prev", _dli_mol(ppfd, stage_photoperiod_h)), "dli_prev")
    vpd_kpa = _to_float(payload.get("vpd_kpa", _vpd_kpa(t_air_c, rh_pct)), "vpd_kpa")

    disease_pressure = _to_float(payload.get("disease_pressure", prev_disease_pressure), "disease_pressure")
    hlvd_pressure = _to_float(payload.get("hlvd_pressure", prev_hlvd_pressure), "hlvd_pressure")

    return SensorState(
        t_air_c=t_air_c,
        rh_pct=rh_pct,
        co2_ppm=co2_ppm,
        ppfd=ppfd,
        t_solution_c=t_solution_c,
        do_mg_l=do_mg_l,
        ec_ms_cm=ec_ms_cm,
        ph=ph,
        dli_prev=dli_prev,
        transpiration_l_m2_day=transp,
        vpd_kpa=vpd_kpa,
        disease_pressure=disease_pressure,
        hlvd_pressure=hlvd_pressure,
    )


def iter_jsonl_file(path: Path, poll_s: float, emit_source_events: bool = False) -> Generator[Dict, None, None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()

    with path.open("r", encoding="utf-8") as f:
        while True:
            line = f.readline()
            if not line:
                time.sleep(poll_s)
                if emit_source_events:
                    yield _source_event(kind="idle", source="jsonl_file")
                continue
            s = line.strip().lstrip("\ufeff")
            if not s:
                continue
            try:
                yield json.loads(s)
            except json.JSONDecodeError as exc:
                print(f"[WARN] invalid JSON line skipped: {exc}", file=sys.stderr)
                if emit_source_events:
                    yield _source_event(kind="error", source="jsonl_file", message=f"invalid_json:{exc}")


def iter_stdin_json() -> Generator[Dict, None, None]:
    for line in sys.stdin:
        s = line.strip().lstrip("\ufeff")
        if not s:
            continue
        try:
            yield json.loads(s)
        except json.JSONDecodeError as exc:
            print(f"[WARN] invalid JSON from STDIN skipped: {exc}", file=sys.stderr)


def iter_http_poll(
    url: str,
    poll_s: float,
    timeout_s: float = 5.0,
    emit_source_events: bool = False,
) -> Generator[Dict, None, None]:
    while True:
        try:
            req = request.Request(url=url, method="GET")
            with request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8")
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("HTTP payload must be a JSON object")
                yield payload
        except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            print(f"[WARN] HTTP source error: {exc}", file=sys.stderr)
            if emit_source_events:
                yield _source_event(kind="error", source="http_poll", message=str(exc))
        time.sleep(poll_s)


def iter_serial_json(port: str, baud: int, emit_source_events: bool = False) -> Generator[Dict, None, None]:
    try:
        import serial  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Serial source requires pyserial. Install with: "
            "python -m pip install pyserial"
        ) from exc

    with serial.Serial(port=port, baudrate=baud, timeout=1.0) as ser:
        while True:
            raw = ser.readline()
            if not raw:
                if emit_source_events:
                    yield _source_event(kind="idle", source="serial_json")
                continue
            s = raw.decode("utf-8", errors="ignore").strip().lstrip("\ufeff")
            if not s:
                continue
            try:
                payload = json.loads(s)
            except json.JSONDecodeError as exc:
                print(f"[WARN] invalid JSON from serial skipped: {exc}", file=sys.stderr)
                if emit_source_events:
                    yield _source_event(kind="error", source="serial_json", message=f"invalid_json:{exc}")
                continue
            if not isinstance(payload, dict):
                print("[WARN] serial payload must be JSON object", file=sys.stderr)
                if emit_source_events:
                    yield _source_event(kind="error", source="serial_json", message="payload_not_object")
                continue
            yield payload


def iter_mock_stream(poll_s: float, seed: int, noise_scale: float) -> Generator[Dict, None, None]:
    rng = random.Random(seed)
    t_air = 25.0
    rh = 64.0
    co2 = 740.0
    ppfd = 820.0
    t_solution = 20.0
    do = 8.1
    ec = 2.0
    ph = 5.9
    transp = 2.4

    while True:
        t_air = _clamp(t_air + rng.uniform(-0.25, 0.25) * noise_scale, 20.0, 30.0)
        rh = _clamp(rh + rng.uniform(-1.4, 1.4) * noise_scale, 45.0, 82.0)
        co2 = _clamp(co2 + rng.uniform(-35.0, 35.0) * noise_scale, 420.0, 1200.0)
        ppfd = _clamp(ppfd + rng.uniform(-55.0, 55.0) * noise_scale, 220.0, 1700.0)
        t_solution = _clamp(t_solution + rng.uniform(-0.18, 0.18) * noise_scale, 17.0, 22.5)
        do = _clamp(do + rng.uniform(-0.15, 0.15) * noise_scale, 6.8, 9.5)
        ec = _clamp(ec + rng.uniform(-0.08, 0.08) * noise_scale, 1.1, 3.2)
        ph = _clamp(ph + rng.uniform(-0.04, 0.04) * noise_scale, 5.5, 6.4)
        transp = _clamp(transp + rng.uniform(-0.20, 0.20) * noise_scale, 1.2, 4.8)

        yield {
            "t_air_c": t_air,
            "rh_pct": rh,
            "co2_ppm": co2,
            "ppfd": ppfd,
            "t_solution_c": t_solution,
            "do_mg_l": do,
            "ec_ms_cm": ec,
            "ph": ph,
            "transpiration_l_m2_day": transp,
            "sensor_origin": "mock_stream",
        }
        time.sleep(poll_s)


def build_source(args: argparse.Namespace, emit_source_events: bool = False) -> Iterable[Dict]:
    if args.source == "jsonl_file":
        if not args.input_path:
            raise ValueError("--input-path is required when --source jsonl_file")
        return iter_jsonl_file(
            Path(args.input_path),
            poll_s=args.poll_seconds,
            emit_source_events=emit_source_events,
        )

    if args.source == "stdin_json":
        return iter_stdin_json()

    if args.source == "http_poll":
        if not args.http_url:
            raise ValueError("--http-url is required when --source http_poll")
        return iter_http_poll(
            args.http_url,
            poll_s=args.poll_seconds,
            emit_source_events=emit_source_events,
        )

    if args.source == "serial_json":
        if not args.serial_port:
            raise ValueError("--serial-port is required when --source serial_json")
        return iter_serial_json(
            port=args.serial_port,
            baud=args.serial_baud,
            emit_source_events=emit_source_events,
        )

    if args.source == "mock_stream":
        return iter_mock_stream(
            poll_s=args.poll_seconds,
            seed=args.mock_seed,
            noise_scale=args.mock_noise_scale,
        )

    raise ValueError(f"Unsupported source: {args.source}")


def send_to_http_sink(url: str, payload: Dict, timeout_s: float = 5.0) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=timeout_s):  # noqa: S310
        pass


class SerialActuatorSink:
    def __init__(self, port: str, baud: int):
        try:
            import serial  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Serial actuator sink requires pyserial. Install with: "
                "python -m pip install pyserial"
            ) from exc

        self._serial_mod = serial
        self._ser = serial.Serial(port=port, baudrate=baud, timeout=1.0, write_timeout=1.0)

    def send(self, payload: Dict) -> None:
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self._ser.write(line.encode("utf-8"))
        self._ser.flush()

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()


def emit_output(
    payload: Dict,
    out_jsonl: Optional[str],
    actuator_post_url: Optional[str],
    actuator_serial_sink: Optional[SerialActuatorSink],
) -> None:
    print(json.dumps(payload, ensure_ascii=False))

    if out_jsonl:
        out_path = Path(out_jsonl)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    if actuator_post_url:
        try:
            send_to_http_sink(actuator_post_url, payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] actuator POST failed: {exc}", file=sys.stderr)

    if actuator_serial_sink:
        try:
            actuator_serial_sink.send(payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] actuator serial send failed: {exc}", file=sys.stderr)


def emit_safe_fallback_tick(
    mode: str,
    day_idx: int,
    stage: str,
    baseline: StageSetpoint,
    reason: str,
    fault: Dict,
    out_jsonl: Optional[str],
    actuator_post_url: Optional[str],
    actuator_serial_sink: Optional[SerialActuatorSink],
) -> Dict:
    fallback = safe_fallback_setpoint(baseline)
    payload = {
        "event": "control_tick",
        "ts": _iso_now(),
        "mode": mode,
        "cycle_day": day_idx,
        "stage": stage,
        "actions": [reason, "safe_fallback_recipe"],
        "sensor": {},
        "baseline_setpoint": asdict(baseline),
        "heuristic_setpoint": asdict(fallback),
        "recommended_setpoint": asdict(fallback),
        "fault": fault,
    }
    emit_output(
        payload=payload,
        out_jsonl=out_jsonl,
        actuator_post_url=actuator_post_url,
        actuator_serial_sink=actuator_serial_sink,
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Realtime adaptive controller: uses real sensor payloads instead of digital twin simulation."
    )
    parser.add_argument("--mode", choices=["max_yield", "max_quality"], default="max_yield")

    parser.add_argument(
        "--source",
        choices=["jsonl_file", "stdin_json", "http_poll", "serial_json", "mock_stream"],
        default="jsonl_file",
        help="Sensor source type.",
    )
    parser.add_argument("--input-path", default="sensor_stream.jsonl", help="Input JSONL path for --source jsonl_file.")
    parser.add_argument("--http-url", default=None, help="HTTP endpoint for --source http_poll.")
    parser.add_argument("--serial-port", default=None, help="Serial port for --source serial_json, e.g. COM4")
    parser.add_argument("--serial-baud", type=int, default=115200, help="Serial baudrate for --source serial_json.")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--mock-seed", type=int, default=1337, help="Seed used when --source mock_stream.")
    parser.add_argument("--mock-noise-scale", type=float, default=1.0, help="Noise scaling for --source mock_stream.")

    parser.add_argument(
        "--profile-json",
        default=None,
        help="Optional JSON file containing profile exported from optimizer output.",
    )
    parser.add_argument(
        "--genetic-profile",
        choices=available_genetic_profiles(),
        default=default_genetic_profile_id(),
        help="Genetic profile used when --profile-json is not provided.",
    )
    parser.add_argument(
        "--cultivar-family",
        choices=available_cultivar_families(),
        default=None,
        help="Optional cultivar family prior used when --profile-json is not provided.",
    )
    parser.add_argument("--cultivar-name", default="", help="Optional cultivar tag stored in profile metadata.")
    parser.add_argument(
        "--start-date",
        default=date.today().isoformat(),
        help="Cycle start date in YYYY-MM-DD. Used to determine active stage.",
    )

    parser.add_argument("--out-jsonl", default="control_output.jsonl", help="Append controller output to this file.")
    parser.add_argument("--store-db", default=None, help="Optional SQLite file for telemetry and alerts.")
    parser.add_argument("--actuator-post-url", default=None, help="Optional HTTP endpoint for actuator commands (POST JSON).")
    parser.add_argument("--actuator-serial-port", default=None, help="Optional serial port for actuator commands, e.g. COM6.")
    parser.add_argument("--actuator-serial-baud", type=int, default=115200, help="Serial baudrate for actuator output.")
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
    if args.store_db:
        init_storage(args.store_db)

    profile = load_profile(
        mode=args.mode,
        profile_json=args.profile_json,
        genetic_profile=args.genetic_profile,
        cultivar_family=args.cultivar_family,
        cultivar_name=args.cultivar_name,
    )
    controller = AdaptiveController(mode=args.mode)
    runtime_run_id = new_run_id("rt_core")
    profile_signature = dict_signature(profile_to_dict(profile))
    actuator_serial_sink: Optional[SerialActuatorSink] = None
    if args.actuator_serial_port:
        actuator_serial_sink = SerialActuatorSink(
            port=args.actuator_serial_port,
            baud=args.actuator_serial_baud,
        )

    emit_source_events = args.watchdog_timeout_s > 0.0 or not args.no_safe_fallback
    source_iter = build_source(args, emit_source_events=emit_source_events)

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

    print(
        json.dumps(
            {
                "event": "controller_started",
                "ts": _iso_now(),
                "mode": args.mode,
                "source": args.source,
                "start_date": start_date.isoformat(),
                "profile_source": args.profile_json or "default_profile",
                "genetic_profile": args.genetic_profile,
                "cultivar_family": str(profile.metadata.get("cultivar_family", args.cultivar_family or "")),
                "cultivar_name": str(profile.metadata.get("cultivar_name", args.cultivar_name or "")),
                "run_id": runtime_run_id,
                "git_commit": git_commit_short(),
                "profile_signature": profile_signature,
                "stages": profile.stage_days,
            },
            ensure_ascii=False,
        )
    )

    processed = 0
    for payload in source_iter:
        now_dt = datetime.now()
        day_idx = day_idx_from_start(start_date=start_date, now_dt=now_dt)
        stage = resolve_stage_for_day(profile=profile, day_idx=day_idx)

        baseline = profile.stage_setpoints[stage]
        if is_source_event_payload(payload):
            kind = source_event_kind(payload)
            elapsed = time.monotonic() - last_valid_payload_ts
            emitted_fallback = False
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
                emitted_fallback = True
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
                emitted_fallback = True
            if emitted_fallback and fallback_out is not None:
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
            print(json.dumps({"event": "sensor_payload_error", "error": str(exc), "payload": payload}, ensure_ascii=False), file=sys.stderr)
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

        recommended_raw, actions = controller.adjust(stage=stage, baseline=baseline, sensor=sensor_state)
        if quality.warnings:
            actions = list(actions) + ["sensor_quality_warning"]
        recommended = enforce_setpoint_limits(candidate=recommended_raw, sensor=sensor_state)
        if asdict(recommended) != asdict(recommended_raw):
            actions = list(actions) + ["enforce_limits"]

        out = {
            "event": "control_tick",
            "ts": _iso_now(),
            "mode": args.mode,
            "cycle_day": day_idx,
            "stage": stage,
            "actions": actions,
            "sensor": asdict(sensor_state),
            "baseline_setpoint": asdict(baseline),
            "heuristic_setpoint": asdict(recommended_raw),
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

