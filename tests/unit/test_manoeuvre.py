"""The burn, and the SGP4 inversion underneath it.

The load-bearing test here is the zero burn. Apply no delta-v at all, invert SGP4 onto
the unchanged state, and the element set that comes out has to reproduce the original
trajectory. Whatever that fails by is the floor on every manoeuvre answer the project
gives, so it is measured rather than asserted loosely.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from kessler import catalogue as cat_mod
from kessler import manoeuvre, screening
from kessler.catalogue import EARTH_RADIUS_KM
from sgp4.api import SatrecArray


@pytest.fixture(scope="module")
def catalogue():
    return cat_mod.load()


@pytest.fixture(scope="module")
def window():
    return screening.Window.build(datetime(2026, 8, 17, tzinfo=UTC), 24.0, 10.0)


@pytest.fixture(scope="module")
def orbit_classes(catalogue):
    """One object from each regime, because they fail differently."""
    _, perigee, apogee = cat_mod.orbit_geometry(catalogue.sats)
    altitude = (perigee + apogee) / 2 - EARTH_RADIUS_KM
    eccentricity = np.array([s.ecco for s in catalogue.sats])
    debris = np.array([e.is_debris for e in catalogue.entries])
    picks = {}
    for label, mask in {
        "low circular": (altitude > 400) & (altitude < 600) & (eccentricity < 0.01),
        "low high": (altitude > 800) & (altitude < 1200) & (eccentricity < 0.01),
        "eccentric": eccentricity > 0.3,
        "geostationary": altitude > 35000,
        "debris": debris,
    }.items():
        found = np.flatnonzero(mask)
        if len(found):
            picks[label] = int(found[len(found) // 2])
    return picks


def test_a_zero_burn_reproduces_the_original_orbit(catalogue, window, orbit_classes):
    for label, index in orbit_classes.items():
        inversion = manoeuvre.apply_burn(
            catalogue.sats[index], manoeuvre.Burn(at_offset_s=3600.0), window.jd, window.fr
        )
        assert inversion.converged, f"{label} did not converge"
        assert inversion.residual_km * 1000 < 1e-3, (
            f"{label} left {inversion.residual_km * 1000:.6f} m of error"
        )


def test_a_zero_burn_still_matches_a_day_later(catalogue, window, orbit_classes):
    """Closing at the epoch is not enough. The orbit has to stay closed."""
    index = orbit_classes["low circular"]
    original = catalogue.sats[index]
    inversion = manoeuvre.apply_burn(
        original, manoeuvre.Burn(at_offset_s=3600.0), window.jd, window.fr
    )
    times = np.arange(0.0, 86400.0, 600.0)
    jd = np.full(len(times), window.jd)
    fr = window.fr + times / 86400.0
    _, before, _ = SatrecArray([original]).sgp4(jd, fr)
    _, after, _ = SatrecArray([inversion.satrec]).sgp4(jd, fr)
    drift = np.linalg.norm(before[0] - after[0], axis=1)
    assert drift.max() * 1000 < 1.0, f"drifted {drift.max() * 1000:.3f} m over 24 h"


def test_the_inversion_converges_across_the_catalogue(catalogue, window):
    """A sample, because doing all 19,000 in a test would take half a minute."""
    rng = np.random.default_rng(11)
    sample = rng.choice(len(catalogue.sats), 300, replace=False)
    residuals = []
    for index in sample:
        try:
            inversion = manoeuvre.apply_burn(
                catalogue.sats[int(index)],
                manoeuvre.Burn(at_offset_s=3600.0),
                window.jd,
                window.fr,
            )
        except ValueError:
            continue
        residuals.append(inversion.residual_km * 1000)
    residuals = np.array(residuals)
    assert len(residuals) > 250
    assert np.median(residuals) < 1e-3
    # A small tail is real and known: deep space element sets are harder to fit.
    assert (residuals < 1e-3).mean() > 0.98


def test_an_in_track_burn_moves_the_object_along_its_own_track(catalogue, window):
    """In-track changes the period, so the displacement grows with every revolution."""
    index = catalogue.index_of(25544)
    burn = manoeuvre.Burn(at_offset_s=3600.0, in_track_ms=0.05)
    inversion = manoeuvre.apply_burn(catalogue.sats[index], burn, window.jd, window.fr)
    assert inversion.converged

    def separation_at(seconds: float) -> float:
        return screening.separation_km(
            catalogue.sats[index], inversion.satrec, window.jd, window.fr, seconds
        )

    at_burn = separation_at(3600.0)
    one_hour = separation_at(3600.0 + 3600.0)
    six_hours = separation_at(3600.0 + 6 * 3600.0)

    assert at_burn < 0.001, "the burn should change nothing at the instant it happens"
    assert one_hour > at_burn
    assert six_hours > one_hour, "an in-track burn's effect grows with time"


def test_a_bigger_burn_moves_it_further(catalogue, window):
    index = catalogue.index_of(25544)
    displacements = []
    for magnitude in (0.01, 0.05, 0.2):
        inversion = manoeuvre.apply_burn(
            catalogue.sats[index],
            manoeuvre.Burn(at_offset_s=3600.0, in_track_ms=magnitude),
            window.jd,
            window.fr,
        )
        displacements.append(
            screening.separation_km(
                catalogue.sats[index], inversion.satrec, window.jd, window.fr, 3600.0 + 6 * 3600.0
            )
        )
    assert displacements[0] < displacements[1] < displacements[2]


def test_the_burn_frame_is_orthonormal_and_right_handed():
    r = np.array([7000.0, 0.0, 0.0])
    v = np.array([0.0, 7.5, 0.0])
    radial = manoeuvre.Burn(0, radial_ms=1000.0).as_eci_kms(r, v)
    in_track = manoeuvre.Burn(0, in_track_ms=1000.0).as_eci_kms(r, v)
    cross = manoeuvre.Burn(0, cross_track_ms=1000.0).as_eci_kms(r, v)

    for axis in (radial, in_track, cross):
        assert np.linalg.norm(axis) == pytest.approx(1.0)
    assert np.dot(radial, in_track) == pytest.approx(0.0, abs=1e-12)
    assert np.dot(radial, cross) == pytest.approx(0.0, abs=1e-12)
    assert np.dot(in_track, cross) == pytest.approx(0.0, abs=1e-12)

    # Radial points out along r, in-track along v for a circular orbit.
    assert radial == pytest.approx(np.array([1.0, 0.0, 0.0]))
    assert in_track == pytest.approx(np.array([0.0, 1.0, 0.0]))


def test_burn_magnitude_combines_the_components():
    burn = manoeuvre.Burn(0, radial_ms=3.0, in_track_ms=4.0)
    assert burn.magnitude_ms == pytest.approx(5.0)


def test_equinoctial_round_trip_survives_a_circular_equatorial_orbit():
    """Both classical singularities at once, which is where the fixed point failed."""
    classical = np.array([0.0011, 1e-9, 1e-9, 0.0, 0.0, 1.2])
    back = manoeuvre.from_nonsingular(manoeuvre.to_nonsingular(classical))
    assert back[0] == pytest.approx(classical[0])
    assert back[1] == pytest.approx(classical[1], abs=1e-9)
    # Perigee and node are undefined here, but their combination with the anomaly is
    # not, and that combination is what has to survive.
    original_longitude = (classical[3] + classical[4] + classical[5]) % (2 * np.pi)
    recovered_longitude = (back[3] + back[4] + back[5]) % (2 * np.pi)
    assert recovered_longitude == pytest.approx(original_longitude, abs=1e-9)


def test_equinoctial_round_trip_survives_an_ordinary_orbit():
    classical = np.array([0.0011, 0.0072, 0.9012, 6.2, 0.99, 5.3])
    back = manoeuvre.from_nonsingular(manoeuvre.to_nonsingular(classical))
    assert back == pytest.approx(classical, abs=1e-9)


def test_a_burn_the_propagator_cannot_reach_is_refused(catalogue, window):
    """An object SGP4 will not integrate must raise, not return a plausible number."""
    broken = next(
        (
            catalogue.sats[i]
            for i in range(len(catalogue.sats))
            if catalogue.sats[i].sgp4(window.jd, window.fr + 3600.0 / 86400.0)[0] != 0
        ),
        None,
    )
    if broken is None:
        pytest.skip("every object in this snapshot propagates at the test epoch")
    with pytest.raises(ValueError):
        manoeuvre.apply_burn(broken, manoeuvre.Burn(at_offset_s=3600.0), window.jd, window.fr)
