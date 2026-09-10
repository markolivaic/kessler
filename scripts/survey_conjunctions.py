"""Screen one catalogue snapshot for close approaches and report the distribution.

This is the measurement the rest of kessler is built on. It answers one question:
propagate the whole snapshot for 24 hours, active satellites and the debris clouds
together, throw away the pairs that only look close, and see how many genuine close
approaches are left. If the answer is three a week there is nothing to show. If it is
hundreds a day there is.

It also reports what fraction of the catalogued on-orbit population it covers, because
a screening result without its denominator is not a result.

The screening itself lives in `backend/kessler/`. This script is the runner: it picks
the window, drives the three passes, applies the artefact predicates and writes the
two artefacts the README quotes from.

Usage:
    python scripts/survey_conjunctions.py
    python scripts/survey_conjunctions.py --hours 24 --step 10 --threshold 25
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from kessler import artefacts, screening  # noqa: E402
from kessler import catalogue as cat_mod

ROOT = Path(__file__).resolve().parent.parent
SURVEY_DIR = ROOT / "data" / "survey"

REPORT_THRESHOLDS_KM = [1.0, 5.0, 10.0, 25.0]
SENSITIVITY_FLOORS_KMS = [0.0, 0.01, 0.05, 0.1, 0.2]
HISTOGRAM_BINS_KM = range(0, 25)


def show(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=None)
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--step", type=float, default=10.0, help="screening cadence, seconds")
    parser.add_argument("--threshold", type=float, default=25.0, help="widest miss distance, km")
    parser.add_argument(
        "--co-orbit-floor",
        type=float,
        default=artefacts.CO_ORBIT_FLOOR_KMS,
        help="relative speed below which a pair is co-orbiting, not passing, km/s",
    )
    parser.add_argument(
        "--csv-threshold",
        type=float,
        default=5.0,
        help="only passages closer than this reach the CSV, to keep the artefact committable",
    )
    parser.add_argument("--out", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    snapshot = Path(args.snapshot) if args.snapshot else cat_mod.latest_snapshot()
    out_dir = Path(args.out) if args.out else SURVEY_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    catalogue = cat_mod.load(snapshot)
    entries = catalogue.entries
    print(f"snapshot   {catalogue.date}")
    print(f"catalogue  {len(catalogue):,} objects parsed")
    group_counts: dict = {}
    for entry in entries:
        group_counts[entry.group] = group_counts.get(entry.group, 0) + 1
    for name, count in sorted(group_counts.items(), key=lambda kv: -kv[1]):
        print(f"           {count:6,}  {name}")

    reach = cat_mod.coverage(catalogue)
    print(
        f"coverage   {reach['screened']:,} of {reach['on_orbit_catalogued']:,} on-orbit "
        f"catalogued objects ({reach['screened_percent']}%), debris "
        f"{reach['debris_screened']:,}/{reach['debris_on_orbit']:,} ({reach['debris_percent']}%)"
    )

    # The window starts at the snapshot date, midnight UTC, so rerunning the same
    # snapshot reproduces the same numbers.
    start = datetime.strptime(catalogue.date, "%Y-%m-%d").replace(tzinfo=UTC)
    window = screening.Window.build(start, args.hours, args.step)

    clean = screening.preflight(catalogue.sats, window)
    dropped = [entries[i].name for i in np.flatnonzero(~clean)]
    usable_index = np.flatnonzero(clean)
    print(f"preflight  {len(usable_index):,} usable, {len(dropped)} refused by SGP4")
    for name in dropped[:10]:
        print(f"           dropped {name}")

    gate = screening.gate_radius_km(catalogue.sats, args.threshold, args.step)
    speed_max = cat_mod.max_orbital_speed(catalogue.sats)
    print(
        f"gate       {gate:.1f} km  (threshold {args.threshold:g} km plus "
        f"{2 * speed_max:.2f} km/s closing over half a {args.step:g} s step)"
    )
    print(f"window     {args.hours:g} h at {args.step:g} s, {len(window):,} steps")

    screen_started = time.perf_counter()
    steps, left, right, linear_miss, tree_seconds = screening.screen(
        catalogue.sats, usable_index, window, gate, args.threshold, quiet=args.quiet
    )
    screen_seconds = time.perf_counter() - screen_started
    print(
        f"screen     {len(steps):,} detections in {screen_seconds:.1f}s "
        f"({tree_seconds:.1f}s in the tree)"
    )

    runs = screening.group_runs(steps, left, right, linear_miss)
    print(f"group      {len(runs):,} encounters (contiguous runs of one pair)")

    refine_started = time.perf_counter()
    encounters = screening.refine(runs, catalogue.sats, usable_index, window, quiet=args.quiet)
    refine_seconds = time.perf_counter() - refine_started
    print(f"refine     {refine_seconds:.1f}s")

    element_groups = artefacts.element_set_groups(catalogue.sats)
    for event in encounters:
        verdict = artefacts.classify(
            event.index_a, event.index_b, event.rel_speed_kms, element_groups, args.co_orbit_floor
        )
        event.classification = verdict.classification.value
        event.reason = verdict.reason

    in_range = [e for e in encounters if e.miss_km <= args.threshold]
    duplicated = [e for e in in_range if e.classification == "shared-element-set"]
    co_orbiting = [e for e in in_range if e.classification == "co-orbiting"]
    within = sorted([e for e in in_range if e.classification == "passage"], key=lambda e: e.miss_km)
    print(f"artefacts  {len(duplicated):,} shared element set, {len(co_orbiting):,} co-orbiting")
    print(f"genuine    {len(within):,} passages within {args.threshold:g} km over {args.hours:g} h")

    def row(event) -> dict:
        a, b = entries[event.index_a], entries[event.index_b]
        return {
            "norad_a": a.norad,
            "name_a": a.name,
            "type_a": a.object_type,
            "group_a": a.group,
            "norad_b": b.norad,
            "name_b": b.name,
            "type_b": b.object_type,
            "group_b": b.group,
            "tca_utc": event.tca(start).isoformat(timespec="milliseconds"),
            "miss_km": round(event.miss_km, 6),
            "rel_speed_kms": round(event.rel_speed_kms, 6),
            "altitude_km": round(event.altitude_km, 3),
            "steps_in_run": event.steps_in_run,
            "classification": event.classification,
        }

    csv_path = out_dir / "conjunctions.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row(in_range[0]).keys()))
        writer.writeheader()
        # Passages below the CSV cut, plus every artefact at any distance: the
        # artefacts are the part of this a reader is most likely to disbelieve.
        for event in [e for e in within if e.miss_km <= args.csv_threshold]:
            writer.writerow(row(event))
        for event in sorted(duplicated + co_orbiting, key=lambda e: e.miss_km):
            writer.writerow(row(event))

    miss = np.array([e.miss_km for e in within]) if within else np.empty(0)
    speed = np.array([e.rel_speed_kms for e in within]) if within else np.empty(0)
    distinct = [e for e in in_range if e.classification != "shared-element-set"]
    distinct_miss = np.array([e.miss_km for e in distinct]) if distinct else np.empty(0)
    distinct_speed = np.array([e.rel_speed_kms for e in distinct]) if distinct else np.empty(0)
    days = args.hours / 24.0

    def per_object_load(events: list) -> dict:
        counts: dict = {}
        for event in events:
            for index in (event.index_a, event.index_b):
                counts[index] = counts.get(index, 0) + 1
        values = np.array(sorted(counts.values())) if counts else np.empty(0)
        if not len(values):
            return {"objects_involved": 0}
        return {
            "objects_involved": int(len(values)),
            "objects_with_none": int(len(usable_index) - len(values)),
            "fleet_mean_per_day": round(2 * len(events) / len(usable_index) / days, 3),
            "involved_mean_per_day": round(float(values.mean()) / days, 2),
            "involved_median_per_day": round(float(np.median(values)) / days, 2),
            "involved_p95_per_day": round(float(np.percentile(values, 95)) / days, 2),
            "involved_max_per_day": round(float(values.max()) / days, 2),
        }

    def by_object_type(events: list) -> dict:
        counts: dict = {}
        for event in events:
            kinds = sorted([entries[event.index_a].object_type, entries[event.index_b].object_type])
            key = f"{kinds[0]}-{kinds[1]}"
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    summary = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "snapshot": catalogue.date,
        "command": (
            "python scripts/survey_conjunctions.py "
            f"--hours {args.hours:g} --step {args.step:g} --threshold {args.threshold:g}"
        ),
        "window": {
            "start_utc": start.isoformat(),
            "hours": args.hours,
            "step_seconds": args.step,
            "steps": len(window),
        },
        "catalogue": {
            "objects_parsed": len(catalogue),
            "objects_usable": int(len(usable_index)),
            "objects_refused_by_sgp4": dropped,
            "objects_by_group": dict(sorted(group_counts.items(), key=lambda kv: -kv[1])),
        },
        "coverage": reach,
        "screening": {
            "threshold_km": args.threshold,
            "gate_km": round(gate, 3),
            "max_orbital_speed_kms": round(speed_max, 4),
            "detections": int(len(steps)),
            "encounters_before_filter": len(encounters),
            "state_vectors": int(len(usable_index) * len(window)),
        },
        "artefact_filter": {
            "encounters_in_range_before_filter": len(in_range),
            "shared_element_set": {
                "rule": artefacts.classify(0, 0, 9.9, {0: 1}).reason,
                "removed": len(duplicated),
                "example_pairs": [
                    f"{entries[e.index_a].name} / {entries[e.index_b].name}"
                    for e in sorted(duplicated, key=lambda e: e.miss_km)[:8]
                ],
            },
            "co_orbiting": {
                "rule": (
                    f"relative speed at closest approach below {args.co_orbit_floor:g} km/s. "
                    "These pairs fly together on purpose and never separate, so there is no "
                    "time of closest approach and no manoeuvre decision"
                ),
                "removed": len(co_orbiting),
                "example_pairs": [
                    f"{entries[e.index_a].name} / {entries[e.index_b].name} "
                    f"({e.miss_km:.2f} km, {e.rel_speed_kms * 1000:.1f} m/s)"
                    for e in sorted(co_orbiting, key=lambda e: e.miss_km)[:8]
                ],
            },
            "sensitivity_to_the_speed_floor": {
                f"{floor:g} km/s": {
                    f"<={t:g}km": int(((distinct_miss <= t) & (distinct_speed >= floor)).sum())
                    for t in REPORT_THRESHOLDS_KM
                }
                for floor in SENSITIVITY_FLOORS_KMS
            },
        },
        "result": {
            "passages_within_threshold": len(within),
            "per_day": round(len(within) / days, 1),
            "cumulative_counts_km": {
                f"<={t:g}": int((miss <= t).sum()) for t in REPORT_THRESHOLDS_KM
            },
            "per_day_by_threshold_km": {
                f"<={t:g}": round(float((miss <= t).sum()) / days, 1) for t in REPORT_THRESHOLDS_KM
            },
            "histogram_1km_bins": {
                f"{lo}-{lo + 1}": int(((miss >= lo) & (miss < lo + 1)).sum())
                for lo in HISTOGRAM_BINS_KM
            },
            "miss_distance_km": {
                "min": round(float(miss.min()), 4) if len(miss) else None,
                "p05": round(float(np.percentile(miss, 5)), 3) if len(miss) else None,
                "median": round(float(np.median(miss)), 3) if len(miss) else None,
                "p95": round(float(np.percentile(miss, 95)), 3) if len(miss) else None,
                "max": round(float(miss.max()), 3) if len(miss) else None,
            },
            "relative_speed_kms": {
                "min": round(float(speed.min()), 4) if len(speed) else None,
                "median": round(float(np.median(speed)), 3) if len(speed) else None,
                "max": round(float(speed.max()), 3) if len(speed) else None,
            },
            "per_object_load_by_threshold_km": {
                f"<={t:g}": per_object_load([e for e in within if e.miss_km <= t])
                for t in REPORT_THRESHOLDS_KM
            },
            "object_type_pairs_by_threshold_km": {
                f"<={t:g}": by_object_type([e for e in within if e.miss_km <= t])
                for t in REPORT_THRESHOLDS_KM
            },
            "closest_ten": [
                {
                    "a": entries[e.index_a].name,
                    "b": entries[e.index_b].name,
                    "miss_km": round(e.miss_km, 4),
                    "rel_speed_kms": round(e.rel_speed_kms, 3),
                    "tca_utc": e.tca(start).isoformat(timespec="milliseconds"),
                }
                for e in within[:10]
            ],
        },
        "timing_seconds": {
            "screen_total": round(screen_seconds, 2),
            "screen_kdtree": round(tree_seconds, 2),
            "screen_propagate_and_filter": round(screen_seconds - tree_seconds, 2),
            "refine": round(refine_seconds, 2),
            "note": (
                "screen_propagate_and_filter is SGP4 plus the vectorised linear test plus "
                "array slicing, not SGP4 alone. scripts/benchmark.py times SGP4 on its own."
            ),
        },
    }

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"wrote      {show(csv_path)}")
    print(f"wrote      {show(summary_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
