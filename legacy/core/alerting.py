from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, Iterable, List


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True)
class AlertThresholds:
    window_ticks: int = 60
    fallback_rate_threshold: float = 0.15
    timeout_count_threshold: int = 3
    payload_error_count_threshold: int = 3
    quality_fault_count_threshold: int = 3
    cooldown_ticks: int = 30


class OperationalAlertMonitor:
    """Rolling monitor that emits high-level operational alerts from control events."""

    def __init__(self, thresholds: AlertThresholds | None = None):
        self.thresholds = thresholds or AlertThresholds()
        self._window: Deque[Dict[str, int]] = deque(maxlen=max(1, int(self.thresholds.window_ticks)))
        self._tick = 0
        self._last_alert_tick: Dict[str, int] = {}

    def _window_stats(self) -> Dict[str, float]:
        n = len(self._window)
        if n == 0:
            return {
                "window_ticks": 0.0,
                "fallback_count": 0.0,
                "timeout_count": 0.0,
                "payload_error_count": 0.0,
                "quality_fault_count": 0.0,
                "fallback_rate": 0.0,
            }
        fallback_count = float(sum(int(r["fallback"]) for r in self._window))
        timeout_count = float(sum(int(r["timeout"]) for r in self._window))
        payload_error_count = float(sum(int(r["payload_error"]) for r in self._window))
        quality_fault_count = float(sum(int(r["quality_fault"]) for r in self._window))
        return {
            "window_ticks": float(n),
            "fallback_count": fallback_count,
            "timeout_count": timeout_count,
            "payload_error_count": payload_error_count,
            "quality_fault_count": quality_fault_count,
            "fallback_rate": fallback_count / max(float(n), 1.0),
        }

    def _cooled_down(self, code: str) -> bool:
        last = self._last_alert_tick.get(code, -10**9)
        return (self._tick - last) >= int(self.thresholds.cooldown_ticks)

    def _build_alert(
        self,
        code: str,
        severity: str,
        message: str,
        mode: str,
        stage: str,
        source: str,
        stats: Dict[str, float],
        extra: Dict[str, float | str | bool] | None = None,
    ) -> Dict:
        payload: Dict[str, float | str | bool] = {
            "event": "operational_alert",
            "ts": _iso_now(),
            "code": code,
            "severity": severity,
            "message": message,
            "mode": mode,
            "stage": stage,
            "source": source,
            "window_ticks": int(stats.get("window_ticks", 0.0)),
            "fallback_count": int(stats.get("fallback_count", 0.0)),
            "timeout_count": int(stats.get("timeout_count", 0.0)),
            "payload_error_count": int(stats.get("payload_error_count", 0.0)),
            "quality_fault_count": int(stats.get("quality_fault_count", 0.0)),
            "fallback_rate": float(stats.get("fallback_rate", 0.0)),
        }
        if extra:
            payload.update(extra)
        return payload

    def observe(
        self,
        *,
        mode: str,
        stage: str,
        source: str,
        actions: Iterable[str],
        fault_kind: str = "",
    ) -> List[Dict]:
        actions_set = {str(a) for a in actions}
        fault = str(fault_kind or "").strip().lower()
        row = {
            "fallback": int("safe_fallback_recipe" in actions_set),
            "timeout": int("safe_fallback_watchdog_timeout" in actions_set or fault == "idle"),
            "payload_error": int(
                "safe_fallback_sensor_payload_error" in actions_set
                or "safe_fallback_source_error" in actions_set
                or fault in {"sensor_payload_error", "error"}
            ),
            "quality_fault": int("safe_fallback_sensor_quality_fault" in actions_set or fault == "sensor_quality"),
        }
        self._window.append(row)
        self._tick += 1

        stats = self._window_stats()
        alerts: List[Dict] = []

        if (
            stats["fallback_rate"] >= float(self.thresholds.fallback_rate_threshold)
            and self._cooled_down("fallback_rate_high")
        ):
            alerts.append(
                self._build_alert(
                    code="fallback_rate_high",
                    severity="warning",
                    message="Fallback rate above configured threshold in rolling window.",
                    mode=mode,
                    stage=stage,
                    source=source,
                    stats=stats,
                    extra={"threshold": float(self.thresholds.fallback_rate_threshold)},
                )
            )
            self._last_alert_tick["fallback_rate_high"] = self._tick

        if (
            stats["timeout_count"] >= float(self.thresholds.timeout_count_threshold)
            and self._cooled_down("timeout_burst")
        ):
            alerts.append(
                self._build_alert(
                    code="timeout_burst",
                    severity="critical",
                    message="Repeated sensor stream timeouts detected.",
                    mode=mode,
                    stage=stage,
                    source=source,
                    stats=stats,
                    extra={"threshold": int(self.thresholds.timeout_count_threshold)},
                )
            )
            self._last_alert_tick["timeout_burst"] = self._tick

        if (
            stats["payload_error_count"] >= float(self.thresholds.payload_error_count_threshold)
            and self._cooled_down("payload_error_burst")
        ):
            alerts.append(
                self._build_alert(
                    code="payload_error_burst",
                    severity="warning",
                    message="Repeated malformed/invalid payload events detected.",
                    mode=mode,
                    stage=stage,
                    source=source,
                    stats=stats,
                    extra={"threshold": int(self.thresholds.payload_error_count_threshold)},
                )
            )
            self._last_alert_tick["payload_error_burst"] = self._tick

        if (
            stats["quality_fault_count"] >= float(self.thresholds.quality_fault_count_threshold)
            and self._cooled_down("sensor_quality_fault_burst")
        ):
            alerts.append(
                self._build_alert(
                    code="sensor_quality_fault_burst",
                    severity="critical",
                    message="Repeated hard sensor quality faults detected.",
                    mode=mode,
                    stage=stage,
                    source=source,
                    stats=stats,
                    extra={"threshold": int(self.thresholds.quality_fault_count_threshold)},
                )
            )
            self._last_alert_tick["sensor_quality_fault_burst"] = self._tick

        return alerts

