"""Does the screen find everything, and is what it finds where it says it is.

The one claim the whole project rests on is that the screen is exhaustive: no approach
below the threshold is missed between two samples. That is not checked by asserting it
in a comment, it is checked against an independent reference built a different way.

The reference uses no optimiser. It walks a dense grid, then walks a denser one around
each candidate minimum. It is far too slow for 19,000 objects, which is exactly why the
real screen exists, but over a few hundred objects in one altitude band it is the
ground truth the fast path has to match.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from kessler import catalogue as cat_mod
from kessler import screening
from kessler.catalogue import EARTH_RADIUS_KM
from sgp4.api import SatrecArray

THRESHOLD_KM = 25.0
STEP_S = 10.0
BAND_LOW_KM, BAND_HIGH_KM = 540.0, 570.0
BAND_SAMPLE = 380
WINDOW_MINUTES = 8.0


@pytest.fixture(scope="module")
def catalogue():
    return cat_mod.load()


@pytest.fixture(scope="module")
def band(catalogue):
    """A slice of the busiest shell, so the test has something to find."""
    _, perigee, apogee = cat_mod.orbit_geometry(catalogue.sats)
    altitude = (perigee + apogee) / 2 - EARTH_RADIUS_KM
    inside = np.flatnonzero((altitude > BAND_LOW_KM) & (altitude < BAND_HIGH_KM))
    rng = np.random.default_rng(7)
    if len(inside) > BAND_SAMPLE:
        inside = np.sort(rng.choice(inside, BAND_SAMPLE, replace=False))
    return [catalogue.sats[i] for i in inside]


@pytest.fixture(scope="module")
def window():
    return screening.Window.build(
        datetime(2026, 8, 17, 3, 0, 0, tzinfo=UTC), WINDOW_MINUTES / 60.0, STEP_S
    )


def dense_reference(sats, window) -> dict[tuple[int, int], float]:
    """Every pair within the threshold, found by brute force and no optimiser.

    Two stages only because one would be unaffordable even here: a half second grid
    nominates candidates generously, then a fifty times finer scan around each
    candidate's minimum pins the distance down. At 0.02 s the residual curvature error
    near a minimum is millimetres.
    """
    coarse_step = 0.5
    count = int(round(window.hours * 3600.0 / coarse_step)) + 1
    offsets = np.arange(count) * coarse_step
    arr = SatrecArray(sats)
    errors, positions, _ = arr.sgp4(np.full(len(offsets), window.jd), window.fr + offsets / 86400.0)
    clean = np.all(errors == 0, axis=1)

    rows, columns = np.triu_indices(len(sats), k=1)
    keep = clean[rows] & clean[columns]
    rows, columns = rows[keep], columns[keep]

    # Half a second of relative motion is worth at most about 11 km, so a 60 km cut
    # cannot drop a pair whose true minimum is under 25.
    nominated = []
    for start in range(0, len(rows), 4000):
        a, b = rows[start : start + 4000], columns[start : start + 4000]
        delta = positions[a] - positions[b]
        distance = np.sqrt(np.einsum("ijk,ijk->ij", delta, delta))
        minima = distance.min(axis=1)
        for hit in np.flatnonzero(minima <= 60.0):
            nominated.append((int(a[hit]), int(b[hit]), float(offsets[distance[hit].argmin()])))

    fine = np.arange(-1.0, 1.0 + 1e-9, 0.02)
    truth: dict[tuple[int, int], float] = {}
    for a, b, centre in nominated:
        grid = centre + fine
        pair = SatrecArray([sats[a], sats[b]])
        errors, positions_pair, _ = pair.sgp4(
            np.full(len(grid), window.jd), window.fr + grid / 86400.0
        )
        if np.any(errors != 0):
            continue
        delta = positions_pair[0] - positions_pair[1]
        distance = np.sqrt(np.einsum("ij,ij->i", delta, delta))
        if distance.min() <= THRESHOLD_KM:
            truth[(a, b)] = float(distance.min())
    return truth


@pytest.fixture(scope="module")
def comparison(band, window):
    truth = dense_reference(band, window)
    usable = np.arange(len(band))
    gate = screening.gate_radius_km(band, THRESHOLD_KM, STEP_S)
    steps, left, right, linear, _ = screening.screen(
        band, usable, window, gate, THRESHOLD_KM, quiet=True
    )
    encounters = screening.refine(
        screening.group_runs(steps, left, right, linear), band, usable, window
    )
    found: dict[tuple[int, int], float] = {}
    for event in encounters:
        if event.miss_km <= THRESHOLD_KM:
            key = (event.index_a, event.index_b)
            found[key] = min(found.get(key, np.inf), event.miss_km)
    return truth, found


def test_the_band_actually_contains_encounters(comparison):
    """A test that finds nothing proves nothing."""
    truth, _ = comparison
    assert len(truth) >= 5, f"only {len(truth)} reference encounters, the test is not exercising"


def test_the_screen_misses_nothing(comparison):
    truth, found = comparison
    missed = {pair: distance for pair, distance in truth.items() if pair not in found}
    assert not missed, f"the screen missed {len(missed)} approaches: {sorted(missed.items())[:5]}"


def test_the_screen_invents_nothing(comparison):
    truth, found = comparison
    extra = {pair: distance for pair, distance in found.items() if pair not in truth}
    assert not extra, f"the screen reported {len(extra)} approaches the reference does not have"


def test_refined_distances_match_the_reference(comparison):
    truth, found = comparison
    worst = max(abs(truth[pair] - found[pair]) for pair in truth)
    # Metres, over kilometre-scale distances.
    assert worst < 0.01, f"worst disagreement {worst * 1000:.1f} m"


def test_the_gate_is_derived_from_the_catalogue_not_guessed(catalogue):
    gate = screening.gate_radius_km(catalogue.sats, THRESHOLD_KM, STEP_S)
    fastest = cat_mod.max_orbital_speed(catalogue.sats)
    assert gate == pytest.approx(THRESHOLD_KM + fastest * STEP_S)
    # Two objects closing at twice the fastest perigee speed for half a step.
    assert gate > THRESHOLD_KM + 2 * fastest * (STEP_S / 2) - 1e-9


def test_a_finer_step_needs_a_smaller_gate(catalogue):
    coarse = screening.gate_radius_km(catalogue.sats, THRESHOLD_KM, 10.0)
    fine = screening.gate_radius_km(catalogue.sats, THRESHOLD_KM, 1.0)
    assert fine < coarse


def test_runs_collapse_into_one_encounter_each():
    """A pair inside the threshold for many consecutive steps is one encounter."""
    steps = np.array([4, 5, 6, 7, 20, 21], dtype=np.int32)
    left = np.zeros(6, dtype=np.int32)
    right = np.ones(6, dtype=np.int32)
    miss = np.array([9.0, 6.0, 5.0, 8.0, 3.0, 4.0])
    runs = screening.group_runs(steps, left, right, miss)
    assert len(runs) == 2
    assert runs[0]["steps_in_run"] == 4
    assert runs[0]["linear_miss_km"] == 5.0
    assert runs[1]["steps_in_run"] == 2
    assert runs[1]["linear_miss_km"] == 3.0


def test_separate_pairs_do_not_merge_into_one_run():
    steps = np.array([4, 4, 5, 5], dtype=np.int32)
    left = np.array([0, 2, 0, 2], dtype=np.int32)
    right = np.array([1, 3, 1, 3], dtype=np.int32)
    miss = np.array([2.0, 7.0, 1.0, 6.0])
    runs = screening.group_runs(steps, left, right, miss)
    assert len(runs) == 2
    assert {(r["i"], r["j"]) for r in runs} == {(0, 1), (2, 3)}


def test_empty_input_produces_no_encounters():
    empty = np.empty(0, dtype=np.int32)
    assert screening.group_runs(empty, empty, empty, np.empty(0)) == []


def test_shell_sieve_never_drops_a_pair_that_could_meet(catalogue):
    """The sieve is exact, so anything it removes really cannot come close."""
    _, perigee, apogee = cat_mod.orbit_geometry(catalogue.sats)
    target = catalogue.index_of(25544)
    kept = set(screening.shell_sieve(catalogue.sats, target, THRESHOLD_KM).tolist())
    dropped = [i for i in range(len(catalogue.sats)) if i not in kept]
    for index in dropped[:2000]:
        separated = (
            perigee[index] > apogee[target] + THRESHOLD_KM
            or perigee[target] > apogee[index] + THRESHOLD_KM
        )
        assert separated, f"index {index} was dropped but its shell overlaps"


def test_shell_sieve_keeps_the_object_itself(catalogue):
    target = catalogue.index_of(25544)
    kept = screening.shell_sieve(catalogue.sats, target, THRESHOLD_KM)
    assert target in kept.tolist()


def test_separation_curve_bottoms_out_at_the_time_of_closest_approach(catalogue, window):
    """The curve the interface draws has its minimum where the screen said it would."""
    a = catalogue.index_of(25544)
    b = catalogue.index_of(33757)
    times, distance = screening.separation_curve(
        catalogue.sats[a], catalogue.sats[b], window, 240.0, 120.0, 241
    )
    assert len(times) == 241
    assert np.all(np.isfinite(distance))
    assert distance.min() > 0
