import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.model import CEADigitalTwin, StrategyBuilder, profile_to_dict


class CalibrationE2ETests(unittest.TestCase):
    def test_calibrate_twin_cli_minimal_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            dataset_path = td_path / "dataset.json"
            out_path = td_path / "calibration.json"
            db_path = td_path / "calibration.db"

            builder = StrategyBuilder(genetic_profile_id="regular_photoperiodic", cultivar_family="hybrid")
            p = {k: (b.lo + b.hi) / 2.0 for k, b in builder.parameter_bounds().items()}
            profile = builder.build(p=p, mode="max_yield")
            twin = CEADigitalTwin(random_seed=1234, sanitation_level=0.94)
            outcome = twin.simulate_cycle(profile=profile, mode="max_yield")

            dataset = {
                "cycles": [
                    {
                        "id": "synthetic_001",
                        "mode": "max_yield",
                        "profile": profile_to_dict(profile),
                        "observed": {
                            "dry_yield_g_m2": float(outcome.dry_yield_g_m2),
                            "quality_index": float(outcome.quality_index),
                            "penalty": float(outcome.penalty),
                            "disease_pressure": float(outcome.disease_pressure),
                            "hlvd_pressure": float(outcome.hlvd_pressure),
                            "energy_kwh_m2": float(outcome.energy_kwh_m2),
                        },
                        "seed": 1234,
                        "sanitation_level": 0.94,
                    }
                ]
            }
            dataset_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

            cmd = [
                sys.executable,
                "calibrate_twin.py",
                "--dataset-json",
                str(dataset_path),
                "--out-json",
                str(out_path),
                "--restarts",
                "1",
                "--maxiter",
                "8",
                "--val-ratio",
                "0.0",
                "--bootstrap-resamples",
                "0",
                "--store-db",
                str(db_path),
            ]
            subprocess.run(cmd, check=True, cwd=str(Path(__file__).resolve().parents[1]))

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertIn("calibration", payload)
            self.assertIn("fit", payload)
            self.assertIn("governance", payload)
            self.assertIn("dataset_summary", payload)
            self.assertGreaterEqual(float(payload["fit"]["train_loss"]), 0.0)


if __name__ == "__main__":
    unittest.main()
