"""Rank the on-orbit debris population by family, so inclusion follows a rule.

kessler screens some debris and not all of it. Which debris is a decision, and a
decision needs a stated rule rather than a list of clouds someone happened to think
of. This produces the evidence for that rule from the committed SATCAT snapshot. No
network.

The interesting split is not by name but by *international designator*. Every object
carries one, `YYYY-NNNPPP`, where `YYYY-NNN` identifies the launch. Debris from a
single breakup all inherits the parent's launch id, so a family spanning one
designator is one event. A family spanning ninety designators is not an event at
all, it is a vehicle type that sheds debris on many separate flights. Only the first
kind can have a CelesTrak GROUP endpoint, because only the first kind is a thing.

Usage:
    python scripts/debris_families.py
    python scripts/debris_families.py --top 20 --out data/survey/debris_families.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "data" / "snapshots"

# "FENGYUN 1C DEB", "COSMOS 2251 DEB", "CZ-6A DEB (TANK)" all reduce to the parent.
DEBRIS_SUFFIX = re.compile(r"\s+DEB\b.*$")
LAUNCH_ID = re.compile(r"^(\d{4}-\d{3})")


def latest_snapshot() -> Path:
    candidates = sorted(p for p in SNAPSHOTS.iterdir() if (p / "satcat.csv").exists())
    if not candidates:
        raise SystemExit("No snapshot with a satcat.csv. Run scripts/fetch_snapshot.py first.")
    return candidates[-1]


def to_int(value: str):
    value = (value or "").strip()
    try:
        return int(value)
    except ValueError:
        return None


def median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    snapshot = latest_snapshot()
    with (snapshot / "satcat.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    on_orbit = [r for r in rows if not (r.get("DECAY_DATE") or "").strip()]
    debris = [r for r in on_orbit if r.get("OBJECT_TYPE") == "DEB"]

    families: dict = {}
    for row in debris:
        parent = DEBRIS_SUFFIX.sub("", row["OBJECT_NAME"]).strip()
        entry = families.setdefault(
            parent, {"count": 0, "launches": set(), "perigee": [], "apogee": []}
        )
        entry["count"] += 1
        match = LAUNCH_ID.match(row.get("OBJECT_ID") or "")
        if match:
            entry["launches"].add(match.group(1))
        for field, key in (("PERIGEE", "perigee"), ("APOGEE", "apogee")):
            value = to_int(row.get(field, ""))
            if value is not None:
                entry[key].append(value)

    ranked = []
    for name, entry in families.items():
        ranked.append(
            {
                "family": name,
                "on_orbit_fragments": entry["count"],
                "distinct_launches": len(entry["launches"]),
                # One launch id means one breakup. Many means a vehicle type that has
                # shed debris on separate flights, which is not a single event and has
                # no single parent to name a group after.
                "kind": "single-event" if len(entry["launches"]) <= 1 else "vehicle-type",
                "launch_id": sorted(entry["launches"])[0] if len(entry["launches"]) == 1 else None,
                "median_perigee_km": median(entry["perigee"]),
                "median_apogee_km": median(entry["apogee"]),
            }
        )
    ranked.sort(key=lambda item: -item["on_orbit_fragments"])

    single = [item for item in ranked if item["kind"] == "single-event"]

    print(f"snapshot {snapshot.name}")
    print(f"on-orbit catalogued debris: {len(debris):,} in {len(families):,} families\n")
    header = (
        f"{'rank':>4}  {'fragments':>9}  {'launches':>8}  "
        f"{'kind':<12}  {'perigee':>7}  {'apogee':>6}  family"
    )
    print(header)
    print("-" * len(header))
    for index, item in enumerate(ranked[: args.top], start=1):
        print(
            f"{index:>4}  {item['on_orbit_fragments']:>9,}  {item['distinct_launches']:>8}  "
            f"{item['kind']:<12}  {str(item['median_perigee_km'] or '-'):>7}  "
            f"{str(item['median_apogee_km'] or '-'):>6}  {item['family']}"
        )

    print(f"\nsingle-event breakups only, top {args.top}:")
    print(header)
    print("-" * len(header))
    cumulative = 0
    for index, item in enumerate(single[: args.top], start=1):
        cumulative += item["on_orbit_fragments"]
        print(
            f"{index:>4}  {item['on_orbit_fragments']:>9,}  {item['distinct_launches']:>8}  "
            f"{item['kind']:<12}  {str(item['median_perigee_km'] or '-'):>7}  "
            f"{str(item['median_apogee_km'] or '-'):>6}  {item['family']}  "
            f"(cumulative {cumulative:,}, {100 * cumulative / len(debris):.1f}% of on-orbit debris)"
        )

    payload = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "snapshot": snapshot.name,
        "source": "SATCAT rows with OBJECT_TYPE=DEB and a blank DECAY_DATE",
        "on_orbit_debris": len(debris),
        "families": len(families),
        "family_definition": (
            "object name with the DEB suffix removed. kind is single-event when every "
            "fragment shares one international launch designator, vehicle-type when they "
            "span several, meaning separate flights of the same hardware rather than one "
            "breakup"
        ),
        "top_all": ranked[: args.top],
        "top_single_event": single[: args.top],
    }
    out = Path(args.out) if args.out else ROOT / "data" / "survey" / "debris_families.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
