"""Loading a dated snapshot, joining it to SATCAT, and saying what it covers.

Nothing in here touches the network. A snapshot is a directory of files that were
fetched once, by hand, with `scripts/fetch_snapshot.py`, and committed. The rest of
kessler reads what is on disk and nothing else.
"""

from __future__ import annotations

import contextlib
import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sgp4 import omm
from sgp4.api import Satrec

EARTH_RADIUS_KM = 6378.137
MU_KM3_S2 = 398600.4418

# "FENGYUN 1C DEB", "CZ-6A DEB (TANK)" both reduce to the parent object's name.
DEBRIS_SUFFIX = re.compile(r"\s+DEB\b.*$")


@dataclass(frozen=True)
class Entry:
    """One catalogued object, as kessler knows it."""

    index: int
    norad: int
    name: str
    object_id: str
    epoch: str
    group: str
    object_type: str = "UNK"
    owner: str = ""
    rcs_m2: float | None = None
    launch_date: str = ""

    @property
    def is_debris(self) -> bool:
        return self.object_type == "DEB"


@dataclass
class Catalogue:
    """A snapshot, parsed. Index positions are stable and are what everything else uses."""

    snapshot: Path
    sats: list = field(repr=False)
    entries: list[Entry] = field(repr=False)
    satcat: dict = field(repr=False, default_factory=dict)

    def __len__(self) -> int:
        return len(self.sats)

    @property
    def date(self) -> str:
        return self.snapshot.name

    def by_norad(self, norad: int) -> Entry | None:
        for entry in self.entries:
            if entry.norad == norad:
                return entry
        return None

    def index_of(self, norad: int) -> int | None:
        entry = self.by_norad(norad)
        return entry.index if entry else None

    def manifest(self) -> dict:
        path = self.snapshot / "MANIFEST.json"
        return json.loads(path.read_text()) if path.exists() else {}


def snapshot_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "snapshots"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("Could not find data/snapshots above " + str(here))


def latest_snapshot(root: Path | None = None) -> Path:
    root = root or snapshot_root()
    candidates = sorted(p for p in root.iterdir() if p.is_dir() and any(p.glob("gp-*.csv")))
    if not candidates:
        raise FileNotFoundError(f"No snapshot with gp-*.csv under {root}")
    return candidates[-1]


def load_satcat(snapshot: Path) -> dict:
    path = snapshot / "satcat.csv"
    if not path.exists():
        return {}
    rows = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                rows[int(row["NORAD_CAT_ID"])] = row
            except (KeyError, ValueError, TypeError):
                continue
    return rows


def _float_or_none(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load(snapshot: Path | None = None) -> Catalogue:
    """Parse every gp-*.csv in a snapshot, join SATCAT, return one Catalogue.

    Files are read in sorted order, which puts gp-active first. An object listed in
    both the active catalogue and a debris group therefore keeps its active entry and
    is not counted twice.
    """
    snapshot = snapshot or latest_snapshot()
    satcat = load_satcat(snapshot)

    sats: list = []
    entries: list[Entry] = []
    seen: set[int] = set()

    for path in sorted(snapshot.glob("gp-*.csv")):
        group = path.stem.removeprefix("gp-")
        with path.open() as handle:
            for fields in omm.parse_csv(handle):
                norad = int(fields["NORAD_CAT_ID"])
                if norad in seen:
                    continue
                seen.add(norad)
                satrec = Satrec()
                omm.initialize(satrec, fields)
                row = satcat.get(norad, {})
                entries.append(
                    Entry(
                        index=len(sats),
                        norad=norad,
                        name=fields["OBJECT_NAME"],
                        object_id=fields["OBJECT_ID"],
                        epoch=fields["EPOCH"],
                        group=group,
                        object_type=row.get("OBJECT_TYPE") or "UNK",
                        owner=row.get("OWNER", ""),
                        rcs_m2=_float_or_none(row.get("RCS", "")),
                        launch_date=row.get("LAUNCH_DATE", ""),
                    )
                )
                sats.append(satrec)

    if not sats:
        raise FileNotFoundError(f"No gp-*.csv in {snapshot}")
    return Catalogue(snapshot=snapshot, sats=sats, entries=entries, satcat=satcat)


def orbit_geometry(sats):
    """Semi-major axis, perigee and apogee radius from mean motion, all in km."""
    n_rad_per_s = np.array([s.no_kozai for s in sats]) / 60.0
    ecc = np.array([s.ecco for s in sats])
    sma = MU_KM3_S2 ** (1 / 3) / n_rad_per_s ** (2 / 3)
    return sma, sma * (1 - ecc), sma * (1 + ecc)


def max_orbital_speed(sats) -> float:
    """Vis-viva speed at perigee, maximised over the catalogue.

    Twice this bounds the relative speed of any pair, which is what sets the screening
    gate. Taking it from the catalogue rather than assuming a round number means the
    gate is correct for whatever is actually in the file.
    """
    sma, r_peri, _ = orbit_geometry(sats)
    return float(np.sqrt(MU_KM3_S2 * (2.0 / r_peri - 1.0 / sma)).max())


def coverage(catalogue: Catalogue) -> dict:
    """What fraction of the catalogued on-orbit population this snapshot screens.

    The denominator is every SATCAT row with a blank DECAY_DATE. A screening result
    without its denominator is not a result, and "partial" is not a number.
    """
    on_orbit = [r for r in catalogue.satcat.values() if not (r.get("DECAY_DATE") or "").strip()]
    included = {entry.norad for entry in catalogue.entries}

    by_type: dict = {}
    for row in on_orbit:
        kind = row.get("OBJECT_TYPE") or "UNK"
        bucket = by_type.setdefault(kind, {"on_orbit": 0, "screened": 0})
        bucket["on_orbit"] += 1
        if int(row["NORAD_CAT_ID"]) in included:
            bucket["screened"] += 1
    for bucket in by_type.values():
        bucket["percent"] = round(100 * bucket["screened"] / bucket["on_orbit"], 1)

    screened = sum(b["screened"] for b in by_type.values())
    debris = by_type.get("DEB", {"on_orbit": 0, "screened": 0})

    return {
        "denominator": "CelesTrak SATCAT rows with a blank DECAY_DATE, i.e. still on orbit",
        "on_orbit_catalogued": len(on_orbit),
        "screened": screened,
        "screened_percent": round(100 * screened / max(len(on_orbit), 1), 1),
        "debris_on_orbit": debris["on_orbit"],
        "debris_screened": debris["screened"],
        "debris_percent": round(100 * debris["screened"] / max(debris["on_orbit"], 1), 1),
        "by_object_type": by_type,
        "objects_without_a_satcat_row": len(included) - screened,
    }


def debris_families(catalogue: Catalogue) -> list[dict]:
    """Rank on-orbit debris by family, splitting single breakups from vehicle types.

    Fragments from one breakup all inherit the parent's international designator, so a
    family spanning one launch id is one event. A family spanning many is a vehicle
    type that has shed debris on separate flights, which is not an event and has no
    parent object a catalogue group could be named after.
    """
    launch_id = re.compile(r"^(\d{4}-\d{3})")
    families: dict = {}
    for row in catalogue.satcat.values():
        if (row.get("DECAY_DATE") or "").strip() or row.get("OBJECT_TYPE") != "DEB":
            continue
        parent = DEBRIS_SUFFIX.sub("", row["OBJECT_NAME"]).strip()
        entry = families.setdefault(parent, {"count": 0, "launches": set(), "perigee": []})
        entry["count"] += 1
        match = launch_id.match(row.get("OBJECT_ID") or "")
        if match:
            entry["launches"].add(match.group(1))
        with contextlib.suppress(KeyError, ValueError, TypeError):
            entry["perigee"].append(int(row["PERIGEE"]))

    ranked = [
        {
            "family": name,
            "on_orbit_fragments": item["count"],
            "distinct_launches": len(item["launches"]),
            "kind": "single-event" if len(item["launches"]) <= 1 else "vehicle-type",
            "median_perigee_km": (float(np.median(item["perigee"])) if item["perigee"] else None),
        }
        for name, item in families.items()
    ]
    ranked.sort(key=lambda item: -item["on_orbit_fragments"])
    return ranked
