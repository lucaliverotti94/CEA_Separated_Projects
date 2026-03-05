import unittest

from core.alerting import AlertThresholds, OperationalAlertMonitor


class AlertingMonitorTests(unittest.TestCase):
    def test_fallback_rate_high_alert(self) -> None:
        mon = OperationalAlertMonitor(
            thresholds=AlertThresholds(
                window_ticks=10,
                fallback_rate_threshold=0.30,
                timeout_count_threshold=99,
                payload_error_count_threshold=99,
                quality_fault_count_threshold=99,
                cooldown_ticks=1,
            )
        )
        alerts = []
        for _ in range(4):
            alerts.extend(
                mon.observe(
                    mode="max_yield",
                    stage="vegetative",
                    source="mock_stream",
                    actions=["safe_fallback_recipe"],
                    fault_kind="",
                )
            )
        self.assertTrue(any(a.get("code") == "fallback_rate_high" for a in alerts))

    def test_timeout_burst_alert(self) -> None:
        mon = OperationalAlertMonitor(
            thresholds=AlertThresholds(
                window_ticks=8,
                fallback_rate_threshold=1.0,
                timeout_count_threshold=2,
                payload_error_count_threshold=99,
                quality_fault_count_threshold=99,
                cooldown_ticks=1,
            )
        )
        alerts = []
        alerts.extend(
            mon.observe(
                mode="max_yield",
                stage="flower_early",
                source="http_poll",
                actions=["safe_fallback_watchdog_timeout", "safe_fallback_recipe"],
                fault_kind="idle",
            )
        )
        alerts.extend(
            mon.observe(
                mode="max_yield",
                stage="flower_early",
                source="http_poll",
                actions=["safe_fallback_watchdog_timeout", "safe_fallback_recipe"],
                fault_kind="idle",
            )
        )
        self.assertTrue(any(a.get("code") == "timeout_burst" for a in alerts))


if __name__ == "__main__":
    unittest.main()

