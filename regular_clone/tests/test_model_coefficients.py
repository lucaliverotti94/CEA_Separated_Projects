import unittest

from core.model import CEADigitalTwin, StrategyBuilder


def _midpoint_params(builder: StrategyBuilder) -> dict[str, float]:
    return {k: (b.lo + b.hi) / 2.0 for k, b in builder.parameter_bounds().items()}


class ModelCoefficientCompositionTests(unittest.TestCase):
    def test_family_coefficient_is_composed_with_base(self) -> None:
        builder = StrategyBuilder(
            genetic_profile_id="regular_photoperiodic",
            cultivar_name="Amnesia Haze",
        )
        profile = builder.build(p=_midpoint_params(builder), mode="max_yield")
        twin = CEADigitalTwin(random_seed=7)
        coeffs = twin._profile_model_coefficients(profile)

        expected_yield_scale = (
            float(profile.metadata["genetics_yield_potential_scale"])
            * float(profile.metadata["genetics_family_yield_potential_scale"])
            * float(profile.metadata.get("genetics_cultivar_yield_potential_scale", 1.0))
        )
        self.assertAlmostEqual(coeffs["yield_potential_scale"], expected_yield_scale, places=9)

    def test_cultivar_coefficient_is_composed_with_base_and_family(self) -> None:
        builder = StrategyBuilder(
            genetic_profile_id="regular_photoperiodic",
            cultivar_name="Gorilla Glue #4",
        )
        profile = builder.build(p=_midpoint_params(builder), mode="max_yield")
        twin = CEADigitalTwin(random_seed=11)
        coeffs = twin._profile_model_coefficients(profile)

        expected_yield_scale = (
            float(profile.metadata["genetics_yield_potential_scale"])
            * float(profile.metadata["genetics_family_yield_potential_scale"])
            * float(profile.metadata["genetics_cultivar_yield_potential_scale"])
        )
        expected_nutrient_scale = (
            float(profile.metadata["genetics_nutrient_window_scale"])
            * float(profile.metadata["genetics_family_nutrient_window_scale"])
            * float(profile.metadata["genetics_cultivar_nutrient_window_scale"])
        )

        self.assertAlmostEqual(coeffs["yield_potential_scale"], expected_yield_scale, places=9)
        self.assertAlmostEqual(coeffs["nutrient_window_scale"], expected_nutrient_scale, places=9)


if __name__ == "__main__":
    unittest.main()
