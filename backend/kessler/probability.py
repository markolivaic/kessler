"""Collision probability, and the assumption it rests on.

A two-line element set carries no covariance. None. There is no uncertainty published
alongside it, and there is no way to derive one from the element set itself. Every
collision probability computed from public element sets, including every one this
module returns, rests on a covariance somebody chose.

So this module refuses to choose one. `position_sigma_km` has no default. The caller
must state the assumption, the interface puts that assumption on screen next to the
answer, and `sweep` exists to show what the answer does when the assumption moves,
which is: it moves by orders of magnitude.

Method is the standard two-dimensional one. In the encounter plane, perpendicular to
the relative velocity, a hypervelocity pass is a straight line through a stationary
Gaussian, so the probability is the mass of that Gaussian inside a disc of the
combined object radius. With an isotropic position uncertainty that integral is the
Rice distribution, which is a non-central chi-squared with two degrees of freedom, so
it is exact rather than quadrature.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import ncx2

# Radar cross section is not a diameter, but it is the only size in the catalogue.
# Treating it as the projected area of a sphere gives a radius that is the right
# order of magnitude and is stated as an assumption wherever it is used.
DEFAULT_RADIUS_M = 2.0


@dataclass(frozen=True)
class ProbabilityResult:
    probability: float
    miss_km: float
    combined_radius_m: float
    position_sigma_km: float
    method: str = "2D encounter plane, isotropic covariance, Rice/non-central chi-squared"
    assumption: str = ""

    def as_dict(self) -> dict:
        return {
            "probability": self.probability,
            "one_in": (round(1 / self.probability) if self.probability > 0 else None),
            "miss_km": self.miss_km,
            "combined_radius_m": self.combined_radius_m,
            "position_sigma_km": self.position_sigma_km,
            "method": self.method,
            "assumption": self.assumption,
        }


def radius_from_rcs(rcs_m2: float | None) -> float:
    """A radius in metres from a radar cross section in square metres.

    RCS is not a physical diameter and the catalogue publishes nothing better. Treating
    it as the projected area of a sphere is the usual approximation and it is wrong in
    a knowable direction for anything plate-like or with solar arrays.
    """
    if not rcs_m2 or rcs_m2 <= 0:
        return DEFAULT_RADIUS_M
    return float(np.sqrt(rcs_m2 / np.pi))


def collision_probability(
    miss_km: float,
    position_sigma_km: float,
    combined_radius_m: float = 2 * DEFAULT_RADIUS_M,
) -> ProbabilityResult:
    """Probability of collision, conditional on the covariance you supplied.

    position_sigma_km is the one-sigma spherical position uncertainty of the two
    objects combined. It is required and has no default, because the number that comes
    out is a statement about it as much as about the sky.
    """
    if position_sigma_km <= 0:
        raise ValueError("position_sigma_km must be positive; there is no zero-uncertainty case")

    sigma = float(position_sigma_km)
    radius_km = combined_radius_m / 1000.0
    # Rice CDF: mass of an isotropic 2D Gaussian offset by `miss` inside radius `R`.
    probability = float(ncx2.cdf((radius_km / sigma) ** 2, 2, (miss_km / sigma) ** 2))

    return ProbabilityResult(
        probability=probability,
        miss_km=float(miss_km),
        combined_radius_m=float(combined_radius_m),
        position_sigma_km=sigma,
        assumption=(
            f"assumes a {sigma:g} km one-sigma spherical position uncertainty, which is not "
            "published with the element sets and was supplied by whoever asked for this number"
        ),
    )


def sweep(
    miss_km: float,
    combined_radius_m: float = 2 * DEFAULT_RADIUS_M,
    sigmas_km=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
) -> list[dict]:
    """The same encounter under a range of assumed covariances.

    This exists so the interface can show that the probability is a function of the
    assumption. Across a plausible range of uncertainties the answer for one fixed
    geometry moves by several orders of magnitude, which is the honest headline.
    """
    return [
        collision_probability(miss_km, sigma, combined_radius_m).as_dict() for sigma in sigmas_km
    ]
