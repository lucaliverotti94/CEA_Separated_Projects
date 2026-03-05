import unittest

from core.genetics import available_cultivars, available_genetic_profiles, get_cultivar_prior, get_genetic_profile
from core.literature import available_literature_sources
from optimizer_literature_best import CannabisYieldLiteratureBuilder


class LiteratureBoundsAndSourcesTests(unittest.TestCase):
    def test_uvb_late_frac_upper_bound_is_conservative(self) -> None:
        builder = CannabisYieldLiteratureBuilder(
            genetic_profile_id="feminized_photoperiodic",
            cultivar_family="hybrid",
        )
        bounds = builder.parameter_bounds()
        self.assertIn("uvb_late_frac", bounds)
        self.assertAlmostEqual(float(bounds["uvb_late_frac"].hi), 0.10, places=9)

    def test_all_evidence_source_ids_exist_in_registry(self) -> None:
        valid_ids = set(available_literature_sources())
        missing: list[str] = []

        for profile_id in available_genetic_profiles():
            profile = get_genetic_profile(profile_id)
            for sid in profile.evidence_source_ids:
                if sid not in valid_ids:
                    missing.append(f"profile:{profile_id}:{sid}")

        for cultivar_name in available_cultivars():
            prior = get_cultivar_prior(cultivar_name)
            if prior is None:
                continue
            for sid in prior.evidence_source_ids:
                if sid not in valid_ids:
                    missing.append(f"cultivar:{prior.name}:{sid}")

        self.assertFalse(missing, f"Missing evidence source IDs in literature registry: {missing}")


if __name__ == "__main__":
    unittest.main()
