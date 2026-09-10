"""Collision probability, and the fact that it is a statement about an assumption.

The point of these tests is not that the integral is right, though it is checked
against direct numerical integration. The point is that the module cannot be used
without declaring a covariance, and that the answer moves enormously when that
declaration changes. If either of those stopped being true the interface would start
implying a certainty the data does not have.
"""

from __future__ import annotations

import numpy as np
import pytest
from kessler import probability


def test_a_probability_cannot_be_asked_for_without_an_uncertainty():
    """There is no default sigma, because the element sets publish none."""
    with pytest.raises(TypeError):
        probability.collision_probability(1.0)  # type: ignore[call-arg]


def test_a_zero_or_negative_sigma_is_refused():
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            probability.collision_probability(1.0, bad)


def test_the_integral_matches_direct_numerical_integration():
    """The closed form is a Rice CDF. Check it against brute force quadrature."""
    for miss_km, sigma, radius_m in ((0.5, 0.3, 20.0), (2.0, 1.0, 10.0), (0.1, 0.05, 5.0)):
        result = probability.collision_probability(miss_km, sigma, radius_m)
        radius_km = radius_m / 1000.0

        # Mass of an isotropic 2D gaussian, offset by miss, inside a disc of radius R.
        samples = 4000
        rho = np.linspace(0, radius_km, samples)
        theta = np.linspace(0, 2 * np.pi, samples)
        grid_rho, grid_theta = np.meshgrid(rho, theta, indexing="ij")
        x = grid_rho * np.cos(grid_theta) - miss_km
        y = grid_rho * np.sin(grid_theta)
        density = np.exp(-(x**2 + y**2) / (2 * sigma**2)) / (2 * np.pi * sigma**2)
        integral = np.trapezoid(np.trapezoid(density * grid_rho, theta, axis=1), rho)

        assert result.probability == pytest.approx(integral, rel=0.02), (
            f"closed form {result.probability:.3e} against quadrature {integral:.3e}"
        )


def test_a_closer_pass_is_more_likely_to_hit():
    sigma = 0.5
    near = probability.collision_probability(0.1, sigma).probability
    far = probability.collision_probability(5.0, sigma).probability
    assert near > far


def test_a_bigger_object_is_more_likely_to_be_hit():
    small = probability.collision_probability(1.0, 0.5, 2.0).probability
    large = probability.collision_probability(1.0, 0.5, 40.0).probability
    assert large > small


def test_the_answer_swings_by_orders_of_magnitude_with_the_assumption():
    """This is the headline. One geometry, many defensible covariances."""
    rows = probability.sweep(0.5)
    values = [row["probability"] for row in rows if row["probability"] > 0]
    assert len(values) >= 4
    assert max(values) / min(values) > 100, (
        "if the assumption stopped mattering, showing it would stop being necessary"
    )


def test_every_result_carries_its_assumption_in_words():
    result = probability.collision_probability(1.0, 0.25)
    assert "0.25 km" in result.assumption
    assert "supplied by whoever asked" in result.assumption
    payload = result.as_dict()
    assert payload["position_sigma_km"] == 0.25
    assert "assumption" in payload
    assert payload["method"].startswith("2D encounter plane")


def test_the_one_in_form_is_consistent_with_the_probability():
    result = probability.collision_probability(0.2, 0.3, 20.0).as_dict()
    assert result["one_in"] == round(1 / result["probability"])


def test_radius_from_rcs_treats_it_as_a_projected_area():
    # A 4 square metre cross section is a disc of radius sqrt(4/pi).
    assert probability.radius_from_rcs(4.0) == pytest.approx(np.sqrt(4.0 / np.pi))


def test_radius_falls_back_when_the_catalogue_publishes_no_size():
    for missing in (None, 0.0, -1.0):
        assert probability.radius_from_rcs(missing) == probability.DEFAULT_RADIUS_M


def test_probability_stays_in_range_across_extremes():
    for miss in (0.0, 0.001, 1.0, 100.0):
        for sigma in (0.01, 1.0, 50.0):
            value = probability.collision_probability(miss, sigma).probability
            assert 0.0 <= value <= 1.0


def test_a_head_on_pass_at_zero_distance_is_not_certain():
    """Even a direct hit in the mean is not probability one, because sigma is not zero."""
    value = probability.collision_probability(0.0, 1.0, 10.0).probability
    assert 0.0 < value < 1.0
