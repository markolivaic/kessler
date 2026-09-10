"""Time the pieces separately, on whatever machine runs it.

The survey reports wall clock for its own phases, but those phases mix things.
"Screening" is SGP4 plus array slicing plus a tree build plus a vectorised filter, and
quoting that as an SGP4 rate would be wrong by a factor of two. This times each piece
on its own so the README can say which part costs what.

Nothing here is cached and nothing is estimated. Rerun it and the numbers change with
your CPU, which is the point.

Usage:
    python scripts/benchmark.py
    python scripts/benchmark.py --repeats 5 --out data/survey/benchmark.json
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from sgp4.api import SatrecArray

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from kessler import catalogue as cat_mod  # noqa: E402
from kessler import manoeuvre, screening

ROOT = Path(__file__).resolve().parent.parent

SIEVE_SAMPLES = ["ISS (ZARYA)", "STARLINK-30273", "FENGYUN 1C DEB", "EXPRESS-AMU1"]


def best_of(repeats: int, fn):
    """Fastest of N runs. The slow runs are the machine doing something else."""
    times = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        times.append(time.perf_counter() - started)
    return min(times)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--steps", type=int, default=200, help="steps per propagation timing")
    parser.add_argument(
        "--inversions",
        type=int,
        default=0,
        help="objects to invert SGP4 for, 0 meaning the whole catalogue",
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    catalogue = cat_mod.load()
    sats = catalogue.sats
    n = len(sats)
    print(f"snapshot {catalogue.date}, {n:,} objects")

    start = datetime.strptime(catalogue.date, "%Y-%m-%d").replace(tzinfo=UTC)
    window = screening.Window.build(start, args.steps * 10.0 / 3600.0, 10.0)
    offsets = window.offsets[: args.steps]
    arr = SatrecArray(sats)
    jd = np.full(len(offsets), window.jd)
    fr = window.fr + offsets / 86400.0

    # 1. SGP4 alone.
    seconds = best_of(args.repeats, lambda: arr.sgp4(jd, fr))
    vectors = n * len(offsets)
    rate = vectors / seconds
    print(f"sgp4           {vectors:,} state vectors in {seconds:.2f}s  =  {rate / 1e6:.2f}M/s")

    errors, positions, _ = arr.sgp4(jd[:1], fr[:1])
    frame = positions[np.all(errors == 0, axis=1), 0, :]
    gate = screening.gate_radius_km(sats, 25.0, 10.0)

    # 2. Neighbour search.
    build_seconds = best_of(
        args.repeats, lambda: cKDTree(frame, balanced_tree=False, compact_nodes=False)
    )
    tree = cKDTree(frame, balanced_tree=False, compact_nodes=False)
    query_seconds = best_of(args.repeats, lambda: tree.query_pairs(gate, output_type="ndarray"))
    pairs = tree.query_pairs(gate, output_type="ndarray")
    print(f"kdtree build   {len(frame):,} points in {build_seconds * 1000:.1f} ms")
    print(
        f"kdtree query   {len(pairs):,} pairs inside {gate:.0f} km in {query_seconds * 1000:.1f} ms"
    )

    # 3. The shell sieve, which is only useful for single-object questions.
    sieve = {}
    for name in SIEVE_SAMPLES:
        entry = next((e for e in catalogue.entries if e.name.startswith(name)), None)
        if entry is None:
            continue
        kept = screening.shell_sieve(sats, entry.index, 25.0)
        sieve[entry.name] = {
            "survivors": int(len(kept)),
            "of": n,
            "kept_percent": round(100 * len(kept) / n, 1),
        }
        print(
            f"shell sieve    {entry.name[:26]:26s} keeps {len(kept):6,} of {n:,} "
            f"({100 * len(kept) / n:4.1f}%)"
        )

    # 4. SGP4 inversion, which is what a manoeuvre costs.
    # The whole catalogue by default. A sample used to hide the fact that the least
    # squares fallback crashed: the objects that needed it raised, were skipped, and
    # the surviving 200 all happened to converge by fixed point.
    if args.inversions and args.inversions < n:
        sample = np.random.default_rng(11).choice(n, args.inversions, replace=False)
    else:
        sample = np.arange(n)
    residuals, took, refused, unconverged = [], [], 0, 0
    for index in sample:
        try:
            began = time.perf_counter()
            inversion = manoeuvre.apply_burn(
                sats[int(index)], manoeuvre.Burn(at_offset_s=3600.0), window.jd, window.fr
            )
            took.append(time.perf_counter() - began)
            residuals.append(inversion.residual_km)
            if not inversion.converged:
                unconverged += 1
        except ValueError:
            refused += 1
            continue
    residuals_m = np.array(residuals) * 1000.0
    print(
        f"sgp4 inversion {len(residuals):,} zero burns, median residual "
        f"{np.median(residuals_m):.2e} m, {np.median(took) * 1000:.2f} ms each, "
        f"{unconverged} did not converge, {refused} refused by SGP4"
    )

    steps_per_day = int(86400 / 10) + 1
    per_step = seconds / len(offsets) + build_seconds + query_seconds
    print(
        f"projected      one day at 10 s = {steps_per_day:,} steps "
        f"= {per_step * steps_per_day:.0f}s of screening"
    )

    payload = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "python": platform.python_version(),
            "numpy": np.__version__,
        },
        "snapshot": catalogue.date,
        "objects": n,
        "repeats": args.repeats,
        "sgp4": {
            "steps": len(offsets),
            "state_vectors": vectors,
            "seconds": round(seconds, 4),
            "state_vectors_per_second": round(rate),
        },
        "neighbour_search": {
            "points": int(len(frame)),
            "gate_km": round(gate, 2),
            "build_ms": round(build_seconds * 1000, 3),
            "query_ms": round(query_seconds * 1000, 3),
            "pairs_returned": int(len(pairs)),
        },
        "shell_sieve": sieve,
        "sgp4_inversion": {
            "objects": len(residuals),
            "burn": "zero delta-v, so the residual is the accuracy floor of the manoeuvre",
            "residual_m_median": float(np.median(residuals_m)),
            "residual_m_p99": float(np.percentile(residuals_m, 99)),
            "residual_m_max": float(residuals_m.max()),
            "under_1_micron_percent": round(100 * float((residuals_m < 1e-6).mean()), 4),
            "did_not_converge": unconverged,
            "refused_by_sgp4": refused,
            "ms_median": round(float(np.median(took)) * 1000, 3),
        },
        "projected_full_day_screening_seconds": round(per_step * steps_per_day, 1),
    }

    out = Path(args.out) if args.out else ROOT / "data" / "survey" / "benchmark.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
