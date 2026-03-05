import unittest

from core.genetics import available_cultivars, available_genetic_profiles, get_cultivar_prior, get_genetic_profile
from core.literature import available_literature_sources, get_literature_source
from optimizer_literature_best import CannabisYieldLiteratureBuilder


class LiteratureBoundsAndSourcesTests(unittest.TestCase):
    def test_uvb_late_frac_upper_bound_is_conservative(self) -> None:
        builder = CannabisYieldLiteratureBuilder(
            genetic_profile_id="regular_photoperiodic",
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

    def test_audit_fields_are_present_for_all_sources(self) -> None:
        for sid in available_literature_sources():
            src = get_literature_source(sid)
            self.assertTrue(str(src.variety_studied).strip())
            self.assertTrue(str(src.photoperiod_class).strip())
            self.assertTrue(str(src.compatibility_regular).strip())


if __name__ == "__main__":
    unittest.main()
