"""The screen: propagate everything, find the pairs that come close, pin down when.

Three passes, and the reason for each is in its own docstring. The property the whole
thing rests on is the gate: at the sample nearest a close approach, the two objects
are separated by at most the threshold plus the furthest they can close in half a
step. Screen at that radius and nothing below the threshold can hide between samples.
tests/unit/test_screening.py checks that against a dense reference that uses no
optimiser at all.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.spatial import cKDTree
from sgp4.api import SatrecArray, jday

from .catalogue import EARTH_RADIUS_KM, max_orbital_speed, orbit_geometry

# Steps propagated at once. 19k objects x 180 steps x 2 vectors x 3 floats is about
# 160 MB, which is the reason for chunking rather than propagating the whole window.
BLOCK_STEPS = 180

# Slack for the linear closest-approach test. Over half a step an orbiting body
# departs from its own tangent by roughly a*(h/2)^2/2, which is 110 m per object at
# 10 s in low orbit. One km covers both objects with room to spare.
LINEAR_SLACK_KM = 1.0


@dataclass
class Encounter:
    """One close approach: a pair, a time, and how close they got."""

    index_a: int
    index_b: int
    tca_offset_s: float
    miss_km: float
    rel_speed_kms: float
    altitude_km: float
    steps_in_run: int
    first_step: int
    last_step: int
    classification: str = "passage"
    reason: str = ""

    def tca(self, window_start: datetime) -> datetime:
        return window_start + timedelta(seconds=self.tca_offset_s)


@dataclass
class Window:
    """The interval being screened, and the SGP4 time base for it."""

    start: datetime
    hours: float
    step_s: float
    offsets: np.ndarray = field(repr=False)
    jd: float = 0.0
    fr: float = 0.0

    @classmethod
    def build(cls, start: datetime, hours: float, step_s: float) -> Window:
        count = int(round(hours * 3600.0 / step_s)) + 1
        offsets = np.arange(count) * step_s
        jd, fr = jday(start.year, start.month, start.day, start.hour, start.minute, start.second)
        return cls(start=start, hours=hours, step_s=step_s, offsets=offsets, jd=jd, fr=fr)

    def __len__(self) -> int:
        return len(self.offsets)


def gate_radius_km(sats, threshold_km: float, step_s: float) -> float:
    """The screening radius that makes the search exhaustive.

    Derived, not chosen. If a pair reaches `threshold_km` at some instant, then at the
    sample nearest that instant, at most half a step away, they are separated by at
    most the threshold plus their closing speed times half a step. Relative speed is
    bounded by twice the fastest perigee speed in the catalogue.
    """
    return threshold_km + max_orbital_speed(sats) * step_s


def shell_sieve(sats, target_index: int, threshold_km: float) -> np.ndarray:
    """Objects whose radial shell can reach the target's, within the threshold.

    The classic first filter in pair screening, from Hoots. Two orbits cannot come
    within D if one's perigee is more than D above the other's apogee. It is exact,
    it costs one vectorised comparison, and it needs no propagation at all.

    It is worth being clear about where this does and does not help. The all-pairs
    screen in this module does not use it, because a per-step spatial index never
    enumerates pairs in the first place and so has nothing to prefilter. Its use is
    the single-object question: given one satellite, which of the other 19,000 could
    ever matter. scripts/benchmark.py measures how much it removes.
    """
    _, perigee, apogee = orbit_geometry(sats)
    lo, hi = perigee[target_index] - threshold_km, apogee[target_index] + threshold_km
    return np.flatnonzero((apogee >= lo) & (perigee <= hi))


def preflight(sats, window: Window) -> np.ndarray:
    """Boolean mask of objects SGP4 will integrate everywhere in the window."""
    arr = SatrecArray(sats)
    stride = max(len(window) // 144, 1)
    probe = window.offsets[::stride]
    errors, _, _ = arr.sgp4(np.full(len(probe), window.jd), window.fr + probe / 86400.0)
    return np.all(errors == 0, axis=1)


def separation_km(sat_a, sat_b, jd: float, fr: float, seconds: float) -> float:
    """SGP4 separation of two objects, seconds after the window start.

    Module level rather than a closure inside the refine loop, so it binds its
    satellites once and so it can be called on its own to draw a separation curve.
    """
    at = fr + seconds / 86400.0
    err_a, r_a, _ = sat_a.sgp4(jd, at)
    err_b, r_b, _ = sat_b.sgp4(jd, at)
    if err_a or err_b:
        return 1e9
    dx, dy, dz = r_a[0] - r_b[0], r_a[1] - r_b[1], r_a[2] - r_b[2]
    return float(np.sqrt(dx * dx + dy * dy + dz * dz))


def screen(sats, usable, window: Window, gate_km: float, threshold_km: float, quiet=True):
    """Coarse pass. Returns per-step survivors as (step, i, j, linear_miss_km).

    At each step every object goes into a KD tree and every pair inside the gate comes
    out. Those pairs then get a closest-approach test using the velocities SGP4 has
    already returned, clamped to the half step this sample is responsible for and
    clamped again to the window, so an approach outside the interval asked for is not
    reported inside it.
    """
    arr = SatrecArray(sats)
    n_steps = len(window)
    hits_step, hits_i, hits_j, hits_d = [], [], [], []
    half_step = window.step_s / 2.0
    first_offset, last_offset = float(window.offsets[0]), float(window.offsets[-1])
    tree_seconds = 0.0
    started = last_report = time.perf_counter()

    for start in range(0, n_steps, BLOCK_STEPS):
        stop = min(start + BLOCK_STEPS, n_steps)
        block = window.offsets[start:stop]
        errors, positions, velocities = arr.sgp4(
            np.full(len(block), window.jd), window.fr + block / 86400.0
        )
        # An object that fails at one step is pushed out of reach rather than dropped,
        # so indices stay aligned with the catalogue for the whole run.
        positions[errors != 0] = 1e9
        block_positions = positions[usable]
        block_velocities = velocities[usable]

        for local in range(stop - start):
            here = block_positions[:, local, :]
            tree_started = time.perf_counter()
            tree = cKDTree(here, balanced_tree=False, compact_nodes=False)
            pairs = tree.query_pairs(gate_km, output_type="ndarray")
            tree_seconds += time.perf_counter() - tree_started
            if len(pairs) == 0:
                continue

            left, right = pairs[:, 0], pairs[:, 1]
            speed_here = block_velocities[:, local, :]
            d_rel = here[left] - here[right]
            v_rel = speed_here[left] - speed_here[right]

            now = float(window.offsets[start + local])
            lower = max(-half_step, first_offset - now)
            upper = min(half_step, last_offset - now)

            v_squared = np.einsum("ij,ij->i", v_rel, v_rel)
            v_squared[v_squared == 0.0] = 1e-12
            t_star = -np.einsum("ij,ij->i", d_rel, v_rel) / v_squared
            np.clip(t_star, lower, upper, out=t_star)
            closest = d_rel + v_rel * t_star[:, None]
            miss = np.sqrt(np.einsum("ij,ij->i", closest, closest))

            keep = miss <= threshold_km + LINEAR_SLACK_KM
            if not keep.any():
                continue
            survivors = np.flatnonzero(keep)
            hits_step.append(np.full(len(survivors), start + local, dtype=np.int32))
            hits_i.append(left[survivors].astype(np.int32))
            hits_j.append(right[survivors].astype(np.int32))
            hits_d.append(miss[survivors])

        elapsed = time.perf_counter() - started
        if not quiet and (elapsed - (last_report - started) >= 1.0 or stop >= n_steps):
            last_report = time.perf_counter()
            found = sum(len(h) for h in hits_step)
            sys.stderr.write(
                f"\r  screening {stop / n_steps * 100:5.1f}%  "
                f"{elapsed:6.1f}s  {found:,} detections   "
            )
            sys.stderr.flush()

    if not quiet:
        sys.stderr.write("\n")

    if not hits_step:
        empty = np.empty(0, dtype=np.int32)
        return empty, empty, empty, np.empty(0), tree_seconds
    return (
        np.concatenate(hits_step),
        np.concatenate(hits_i),
        np.concatenate(hits_j),
        np.concatenate(hits_d),
        tree_seconds,
    )


def group_runs(steps, left, right, miss):
    """Collapse per-step detections into encounters: one contiguous run, one event.

    Two satellites flying six km apart in the same orbital plane are inside the
    threshold at every step of the day. That is one proximity, not 8,641 conjunctions,
    and counting it per step would be the same error as counting the space station
    against its own Progress.
    """
    if len(steps) == 0:
        return []
    pair_key = left.astype(np.int64) * (2**31) + right.astype(np.int64)
    order = np.lexsort((steps, pair_key))
    pair_key, steps, left, right, miss = (
        pair_key[order],
        steps[order],
        left[order],
        right[order],
        miss[order],
    )

    new_run = np.empty(len(steps), dtype=bool)
    new_run[0] = True
    new_run[1:] = (pair_key[1:] != pair_key[:-1]) | (steps[1:] != steps[:-1] + 1)
    run_id = np.cumsum(new_run) - 1
    n_runs = int(run_id[-1]) + 1

    best_miss = np.full(n_runs, np.inf)
    np.minimum.at(best_miss, run_id, miss)
    # np.minimum.at leaves ties in place; keep the first index attaining the minimum.
    attains = np.flatnonzero(miss <= best_miss[run_id])
    best_index = np.empty(n_runs, dtype=np.int64)
    best_index[run_id[attains][::-1]] = attains[::-1]

    run_start = np.flatnonzero(new_run)
    run_stop = np.append(run_start[1:], len(steps)) - 1

    runs = []
    for run in range(n_runs):
        index = int(best_index[run])
        runs.append(
            {
                "i": int(left[index]),
                "j": int(right[index]),
                "step": int(steps[index]),
                "linear_miss_km": float(miss[index]),
                "first_step": int(steps[run_start[run]]),
                "last_step": int(steps[run_stop[run]]),
                "steps_in_run": int(run_stop[run] - run_start[run] + 1),
            }
        )
    return runs


def refine_run(run, sats, usable_index, window: Window) -> Encounter:
    """Minimise the true SGP4 separation inside one run's bracket."""
    sat_a = sats[usable_index[run["i"]]]
    sat_b = sats[usable_index[run["j"]]]
    centre = float(window.offsets[run["step"]])

    result = minimize_scalar(
        partial(separation_km, sat_a, sat_b, window.jd, window.fr),
        bounds=(
            max(centre - window.step_s, float(window.offsets[0])),
            min(centre + window.step_s, float(window.offsets[-1])),
        ),
        method="bounded",
        options={"xatol": 1e-4},
    )
    tca = float(result.x)
    at = window.fr + tca / 86400.0
    _, r_a, v_a = sat_a.sgp4(window.jd, at)
    _, r_b, v_b = sat_b.sgp4(window.jd, at)
    r_a, v_a, r_b, v_b = (np.asarray(x) for x in (r_a, v_a, r_b, v_b))

    return Encounter(
        index_a=int(usable_index[run["i"]]),
        index_b=int(usable_index[run["j"]]),
        tca_offset_s=tca,
        miss_km=float(np.linalg.norm(r_a - r_b)),
        rel_speed_kms=float(np.linalg.norm(v_a - v_b)),
        altitude_km=float((np.linalg.norm(r_a) + np.linalg.norm(r_b)) / 2 - EARTH_RADIUS_KM),
        steps_in_run=run["steps_in_run"],
        first_step=run["first_step"],
        last_step=run["last_step"],
    )


def refine(runs, sats, usable_index, window: Window, quiet=True) -> list[Encounter]:
    started = last_report = time.perf_counter()
    out: list[Encounter] = []
    for number, run in enumerate(runs):
        out.append(refine_run(run, sats, usable_index, window))
        elapsed = time.perf_counter() - started
        if not quiet and (elapsed - (last_report - started) >= 1.0 or number == len(runs) - 1):
            last_report = time.perf_counter()
            sys.stderr.write(f"\r  refining {number + 1:,}/{len(runs):,}  {elapsed:6.1f}s   ")
            sys.stderr.flush()
    if not quiet and runs:
        sys.stderr.write("\n")
    return out


def separation_curve(sat_a, sat_b, window: Window, centre_s: float, span_s: float, samples: int):
    """Separation through a time of closest approach, for drawing.

    Returns offsets in seconds and distances in km. This is what the miss-distance
    curve in the interface is, and it is the same SGP4 call the screen used, not a
    smoothed or interpolated version of it.
    """
    times = np.linspace(centre_s - span_s, centre_s + span_s, samples)
    arr = SatrecArray([sat_a, sat_b])
    errors, positions, _ = arr.sgp4(np.full(len(times), window.jd), window.fr + times / 86400.0)
    delta = positions[0] - positions[1]
    distance = np.sqrt(np.einsum("ij,ij->i", delta, delta))
    distance[np.any(errors != 0, axis=0)] = np.nan
    return times, distance
