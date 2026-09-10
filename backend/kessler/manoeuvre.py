"""What a small burn does to an encounter.

The awkward part of this is not the burn, it is SGP4. A burn produces a state vector,
and SGP4 does not take state vectors. It takes *mean* elements in the Brouwer-Lyddane
Kozai formulation, which are not the osculating elements of the post-burn state and
cannot be obtained from them in closed form.

The usual dodge is to propagate the manoeuvred object with a two-body or J2 model
while the other object stays on SGP4. That quietly compares two different physics and
puts the difference into the answer.

So instead this inverts SGP4. Given a target state, find the mean elements whose SGP4
output *is* that state, by fixed point:

    mean(0)   = osculating elements of the target
    mean(k+1) = mean(k) + osc(target) - osc(SGP4(mean(k)))

It converges because SGP4's mean-to-osculating map is the identity plus small
periodic terms. Both objects then propagate on SGP4 and the comparison is honest.

The convergence is measured rather than asserted: apply a zero burn and the inverted
element set must reproduce the original trajectory. tests/unit/test_manoeuvre.py
checks exactly that and the README quotes the residual.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sgp4.api import WGS72, Satrec

MU_KM3_S2 = 398600.4418
# sgp4init counts epoch in days since 1949 December 31 00:00 UT.
SGP4_EPOCH_JD = 2433281.5

MAX_ITERATIONS = 30
CONVERGED_KM = 1e-9


@dataclass(frozen=True)
class Burn:
    """A manoeuvre, in the frame an operator actually thinks in.

    Radial is up, in-track is along the velocity, cross-track completes the set. For
    changing where you are along the orbit, which is what avoids a conjunction, the
    in-track component is the one that does the work: it changes the period, and the
    along-track displacement then grows with every revolution.
    """

    at_offset_s: float
    radial_ms: float = 0.0
    in_track_ms: float = 0.0
    cross_track_ms: float = 0.0

    @property
    def magnitude_ms(self) -> float:
        return float(np.sqrt(self.radial_ms**2 + self.in_track_ms**2 + self.cross_track_ms**2))

    def as_eci_kms(self, r_km: np.ndarray, v_kms: np.ndarray) -> np.ndarray:
        """Rotate the burn out of the RIC frame into the frame SGP4 works in."""
        radial = r_km / np.linalg.norm(r_km)
        cross = np.cross(r_km, v_kms)
        cross = cross / np.linalg.norm(cross)
        in_track = np.cross(cross, radial)
        metres_per_second_to_kms = 1e-3
        return metres_per_second_to_kms * (
            self.radial_ms * radial + self.in_track_ms * in_track + self.cross_track_ms * cross
        )


def state_to_elements(r_km: np.ndarray, v_kms: np.ndarray) -> np.ndarray:
    """Osculating classical elements from a state vector.

    Returns (n_rad_per_min, ecc, inc, raan, argp, mean_anomaly), matching the order and
    units sgp4init wants, so the fixed point can add and subtract these directly.
    """
    r_mag = float(np.linalg.norm(r_km))
    v_mag = float(np.linalg.norm(v_kms))
    h_vec = np.cross(r_km, v_kms)
    h_mag = float(np.linalg.norm(h_vec))
    node_vec = np.array([-h_vec[1], h_vec[0], 0.0])
    node_mag = float(np.linalg.norm(node_vec))

    ecc_vec = (v_mag**2 - MU_KM3_S2 / r_mag) * r_km - float(np.dot(r_km, v_kms)) * v_kms
    ecc_vec = ecc_vec / MU_KM3_S2
    ecc = float(np.linalg.norm(ecc_vec))

    energy = v_mag**2 / 2.0 - MU_KM3_S2 / r_mag
    sma = -MU_KM3_S2 / (2.0 * energy)
    n_rad_per_s = np.sqrt(MU_KM3_S2 / abs(sma) ** 3)

    inc = float(np.arccos(np.clip(h_vec[2] / h_mag, -1.0, 1.0)))

    if node_mag > 1e-10:
        raan = float(np.arccos(np.clip(node_vec[0] / node_mag, -1.0, 1.0)))
        if node_vec[1] < 0:
            raan = 2 * np.pi - raan
    else:
        # Equatorial: the node is undefined, so put the reference at the x axis.
        raan = 0.0

    if node_mag > 1e-10 and ecc > 1e-10:
        argp = float(np.arccos(np.clip(np.dot(node_vec, ecc_vec) / (node_mag * ecc), -1.0, 1.0)))
        if ecc_vec[2] < 0:
            argp = 2 * np.pi - argp
    elif ecc > 1e-10:
        argp = float(np.arctan2(ecc_vec[1], ecc_vec[0]))
    else:
        argp = 0.0

    if ecc > 1e-10:
        true_anomaly = float(np.arccos(np.clip(np.dot(ecc_vec, r_km) / (ecc * r_mag), -1.0, 1.0)))
        if np.dot(r_km, v_kms) < 0:
            true_anomaly = 2 * np.pi - true_anomaly
        eccentric = 2.0 * np.arctan2(
            np.sqrt(max(1 - ecc, 0.0)) * np.sin(true_anomaly / 2),
            np.sqrt(max(1 + ecc, 0.0)) * np.cos(true_anomaly / 2),
        )
        mean_anomaly = eccentric - ecc * np.sin(eccentric)
    else:
        # Circular: true anomaly measured from the node, and M equals it.
        argument_of_latitude = float(np.arctan2(r_km[1], r_km[0])) - raan
        mean_anomaly = argument_of_latitude

    return np.array(
        [
            n_rad_per_s * 60.0,
            ecc,
            inc,
            raan % (2 * np.pi),
            argp % (2 * np.pi),
            mean_anomaly % (2 * np.pi),
        ]
    )


def elements_to_satrec(elements: np.ndarray, epoch_jd: float, bstar: float, satnum: int) -> Satrec:
    """Build a propagator from mean elements with its epoch at the burn."""
    n, ecc, inc, raan, argp, mean_anomaly = elements
    satrec = Satrec()
    satrec.sgp4init(
        WGS72,
        "i",
        satnum,
        epoch_jd - SGP4_EPOCH_JD,
        bstar,
        0.0,
        0.0,
        float(np.clip(ecc, 1e-9, 0.999)),
        float(argp % (2 * np.pi)),
        float(inc),
        float(mean_anomaly % (2 * np.pi)),
        float(n),
        float(raan % (2 * np.pi)),
    )
    return satrec


def to_nonsingular(classical: np.ndarray) -> np.ndarray:
    """(n, e, i, raan, argp, M) into equinoctial elements.

    Classical elements have two singularities and the catalogue sits on both of them.
    At zero eccentricity the perigee is undefined, so argp and M are individually
    meaningless and only their sum is real. At zero inclination the ascending node is
    undefined, so raan goes with it. Correcting those angles separately makes the fixed
    point oscillate instead of converge, and it did: 38 m of residual on near-circular
    low orbits, 16 km on a geostationary one, against sub-micrometre everywhere else.

    Equinoctial elements have neither singularity. Eccentricity becomes a vector in the
    orbit plane, inclination and node become a vector too, and the three angles collapse
    into one mean longitude.

    Returns (n, h, k, p, q, mean_longitude).
    """
    n, ecc, inc, raan, argp, mean_anomaly = classical
    longitude_of_perigee = argp + raan
    tan_half_inc = np.tan(inc / 2.0)
    return np.array(
        [
            n,
            ecc * np.sin(longitude_of_perigee),
            ecc * np.cos(longitude_of_perigee),
            tan_half_inc * np.sin(raan),
            tan_half_inc * np.cos(raan),
            (mean_anomaly + longitude_of_perigee) % (2 * np.pi),
        ]
    )


def from_nonsingular(equinoctial: np.ndarray) -> np.ndarray:
    n, h, k, p, q, mean_longitude = equinoctial
    ecc = float(np.hypot(h, k))
    inc = float(2.0 * np.arctan(np.hypot(p, q)))
    raan = float(np.arctan2(p, q)) if (p or q) else 0.0
    longitude_of_perigee = float(np.arctan2(h, k)) if (h or k) else 0.0
    argp = (longitude_of_perigee - raan) % (2 * np.pi)
    mean_anomaly = (mean_longitude - longitude_of_perigee) % (2 * np.pi)
    return np.array([n, ecc, inc, raan % (2 * np.pi), argp, mean_anomaly])


def _least_squares_inversion(target, start, r_km, v_kms, epoch_jd, epoch_fr, bstar, satnum):
    """Six residuals, six unknowns, numerical Jacobian. The slow reliable path.

    Velocity error is multiplied by a characteristic time so both halves of the
    residual are in kilometres and neither dominates the fit for arbitrary reasons.
    """
    from scipy.optimize import least_squares

    n_rad_per_min = max(float(target[0]), 1e-9)
    characteristic_time_s = 60.0 / n_rad_per_min

    def residual(state):
        satrec = elements_to_satrec(from_nonsingular(state), epoch_jd + epoch_fr, bstar, satnum)
        error, r_out, v_out = satrec.sgp4(epoch_jd, epoch_fr)
        if error != 0:
            return np.full(6, 1e6)
        return np.concatenate(
            [
                np.asarray(r_out) - r_km,
                (np.asarray(v_out) - v_kms) * characteristic_time_s,
            ]
        )

    try:
        solution = least_squares(
            residual, start, method="lm", xtol=1e-14, ftol=1e-14, max_nfev=4000
        )
    except Exception:
        return None

    satrec = elements_to_satrec(from_nonsingular(solution.x), epoch_jd + epoch_fr, bstar, satnum)
    error, r_out, _ = satrec.sgp4(epoch_jd, epoch_fr)
    if error != 0:
        return None
    return solution.x, float(np.linalg.norm(np.asarray(r_out) - r_km)), int(solution.nfev)


@dataclass
class Inversion:
    """The element set that reproduces a state, and how well it does it."""

    satrec: Satrec
    residual_km: float
    residual_kms: float
    iterations: int
    converged: bool


def invert_sgp4(
    r_km: np.ndarray,
    v_kms: np.ndarray,
    epoch_jd: float,
    epoch_fr: float,
    bstar: float = 0.0,
    satnum: int = 99999,
    tolerance_km: float = CONVERGED_KM,
) -> Inversion:
    """Find mean elements whose SGP4 output at the epoch is the given state."""
    target = to_nonsingular(state_to_elements(r_km, v_kms))
    mean = target.copy()
    best = mean.copy()
    residual_km = best_residual_km = float("inf")
    residual_kms = 0.0
    iterations = 0

    for attempt in range(1, MAX_ITERATIONS + 1):
        iterations = attempt
        satrec = elements_to_satrec(from_nonsingular(mean), epoch_jd + epoch_fr, bstar, satnum)
        error, r_out, v_out = satrec.sgp4(epoch_jd, epoch_fr)
        if error != 0:
            break
        r_out = np.asarray(r_out)
        v_out = np.asarray(v_out)
        residual_km = float(np.linalg.norm(r_out - r_km))
        if residual_km < best_residual_km:
            best_residual_km, best = residual_km, mean.copy()
        if residual_km < tolerance_km:
            break
        achieved = to_nonsingular(state_to_elements(r_out, v_out))
        correction = target - achieved
        # Mean longitude is the only angle left. n, h, k, p and q are not angles and
        # wrapping them would be nonsense.
        correction[5] = (correction[5] + np.pi) % (2 * np.pi) - np.pi
        mean = mean + correction

    # The fixed point assumes the mean-to-osculating map is the identity plus something
    # small. Above about 225 minutes of period SGP4 switches to its deep space branch,
    # which adds lunar and solar terms and orbital resonance, and that assumption stops
    # holding: every object it failed on was geostationary. For those, solve properly
    # with a numerical Jacobian instead of guessing that the Jacobian is the identity.
    if best_residual_km >= tolerance_km:
        solved = _least_squares_inversion(
            target, best, r_km, v_kms, epoch_jd, epoch_fr, bstar, satnum
        )
        if solved is not None and solved[1] < best_residual_km:
            # Three values, not two. Unpacking this into a pair raised a ValueError
            # that apply_burn passed straight up to the API, so the fallback never
            # ran once and the two objects it exists for came back as a 422 reading
            # "too many values to unpack (expected 2)". The whole-catalogue check
            # caught ValueError and counted them as skips, which hid it.
            best, best_residual_km, extra_evaluations = solved
            iterations += extra_evaluations

    # Keep the best iterate rather than the last. The map is a contraction in practice
    # but nothing here guarantees the final step was the closest one.
    satrec = elements_to_satrec(from_nonsingular(best), epoch_jd + epoch_fr, bstar, satnum)
    error, r_out, v_out = satrec.sgp4(epoch_jd, epoch_fr)
    if error == 0:
        residual_km = float(np.linalg.norm(np.asarray(r_out) - r_km))
        residual_kms = float(np.linalg.norm(np.asarray(v_out) - v_kms))

    return Inversion(
        satrec=satrec,
        residual_km=residual_km,
        residual_kms=residual_kms,
        iterations=iterations,
        converged=residual_km < tolerance_km,
    )


def apply_burn(satrec: Satrec, burn: Burn, jd: float, fr: float) -> Inversion:
    """Propagate to the burn, add the delta-v, and return a propagator for what follows.

    A zero burn is not a special case and is not short-circuited. It runs the whole
    inversion, which is what makes it a usable control: the residual on a zero burn is
    the accuracy floor of everything this module reports.
    """
    at = fr + burn.at_offset_s / 86400.0
    error, r_km, v_kms = satrec.sgp4(jd, at)
    if error != 0:
        raise ValueError(f"SGP4 error {error} at the burn time; cannot manoeuvre from there")
    r_km = np.asarray(r_km)
    v_kms = np.asarray(v_kms)
    v_after = v_kms + burn.as_eci_kms(r_km, v_kms)
    return invert_sgp4(
        r_km, v_after, jd, at, bstar=satrec.bstar, satnum=getattr(satrec, "satnum", 99999)
    )
