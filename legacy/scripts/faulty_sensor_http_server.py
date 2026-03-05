from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict
import argparse
import json
import random
import time


def _clamp(v: float, lo: float, hi: float) -> float:
    return float(min(max(v, lo), hi))


class SensorGenerator:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.state = {
            "t_air_c": 25.0,
            "rh_pct": 62.0,
            "co2_ppm": 760.0,
            "ppfd": 850.0,
            "t_solution_c": 20.0,
            "do_mg_l": 8.0,
            "ec_ms_cm": 1.9,
            "ph": 5.9,
            "transpiration_l_m2_day": 2.4,
        }

    def next(self) -> Dict:
        s = self.state
        s["t_air_c"] = _clamp(s["t_air_c"] + self.rng.uniform(-0.35, 0.35), 20.0, 30.0)
        s["rh_pct"] = _clamp(s["rh_pct"] + self.rng.uniform(-1.8, 1.8), 45.0, 80.0)
        s["co2_ppm"] = _clamp(s["co2_ppm"] + self.rng.uniform(-40.0, 40.0), 420.0, 1200.0)
        s["ppfd"] = _clamp(s["ppfd"] + self.rng.uniform(-70.0, 70.0), 180.0, 1700.0)
        s["t_solution_c"] = _clamp(s["t_solution_c"] + self.rng.uniform(-0.2, 0.2), 17.0, 22.5)
        s["do_mg_l"] = _clamp(s["do_mg_l"] + self.rng.uniform(-0.15, 0.15), 6.8, 9.5)
        s["ec_ms_cm"] = _clamp(s["ec_ms_cm"] + self.rng.uniform(-0.08, 0.08), 1.0, 3.0)
        s["ph"] = _clamp(s["ph"] + self.rng.uniform(-0.05, 0.05), 5.5, 6.4)
        s["transpiration_l_m2_day"] = _clamp(s["transpiration_l_m2_day"] + self.rng.uniform(-0.2, 0.2), 1.2, 4.8)
        out = dict(s)
        out["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return out


class FaultyHandler(BaseHTTPRequestHandler):
    generator: SensorGenerator
    rng: random.Random
    drop_rate: float
    malformed_rate: float
    missing_field_rate: float
    slow_rate: float
    slow_seconds: float

    def _write(self, code: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/sensors/latest", "/health"}:
            self._write(404, b'{"error":"not_found"}')
            return

        if self.path == "/health":
            self._write(200, b'{"status":"ok"}')
            return

        x = self.rng.random()
        if x < self.drop_rate:
            self._write(503, b'{"error":"simulated_drop"}')
            return

        x -= self.drop_rate
        if x < self.slow_rate:
            time.sleep(self.slow_seconds)

        x -= self.slow_rate
        if x < self.malformed_rate:
            self._write(200, b'{"invalid_json":', content_type="application/json")
            return

        x -= self.malformed_rate
        payload = self.generator.next()
        if x < self.missing_field_rate:
            payload.pop("ph", None)

        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._write(200, raw)

    def log_message(self, _format: str, *args) -> None:  # noqa: A003
        # Keep server output concise for test runs.
        return


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fault-injection HTTP sensor emulator for HIL tests.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8091)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--drop-rate", type=float, default=0.08, help="Probability of HTTP 503 response.")
    p.add_argument("--malformed-rate", type=float, default=0.06, help="Probability of malformed JSON body.")
    p.add_argument("--missing-field-rate", type=float, default=0.06, help="Probability of payload missing a required field.")
    p.add_argument("--slow-rate", type=float, default=0.05, help="Probability of delayed response.")
    p.add_argument("--slow-seconds", type=float, default=3.0, help="Delay duration used by slow-rate.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    FaultyHandler.generator = SensorGenerator(seed=int(args.seed))
    FaultyHandler.rng = random.Random(int(args.seed) + 99)
    FaultyHandler.drop_rate = max(0.0, min(1.0, float(args.drop_rate)))
    FaultyHandler.malformed_rate = max(0.0, min(1.0, float(args.malformed_rate)))
    FaultyHandler.missing_field_rate = max(0.0, min(1.0, float(args.missing_field_rate)))
    FaultyHandler.slow_rate = max(0.0, min(1.0, float(args.slow_rate)))
    FaultyHandler.slow_seconds = max(0.0, float(args.slow_seconds))

    server = ThreadingHTTPServer((args.host, int(args.port)), FaultyHandler)
    print(f"http://{args.host}:{args.port}/sensors/latest")
    server.serve_forever()


if __name__ == "__main__":
    main()

