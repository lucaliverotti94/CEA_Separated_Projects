import unittest

from core.model import StrategyBuilder, profile_literature_sources, reference_audit_summary


def _midpoint_params(builder: StrategyBuilder) -> dict[str, float]:
    return {k: (b.lo + b.hi) / 2.0 for k, b in builder.parameter_bounds().items()}


class ReferenceAuditSummaryTests(unittest.TestCase):
    def test_summary_is_computed_from_profile_sources(self) -> None:
        builder = StrategyBuilder(
            genetic_profile_id="regular_photoperiodic",
            cultivar_family="indica_dominant",
        )
        profile = builder.build(p=_midpoint_params(builder), mode="max_yield")
        rows = profile_literature_sources(profile)
        summary = reference_audit_summary(rows)

        self.assertIn("compatible", summary)
        self.assertIn("incompatible", summary)
        self.assertIn("ambiguous", summary)
        self.assertGreaterEqual(summary["compatible"], 1)


if __name__ == "__main__":
    unittest.main()

