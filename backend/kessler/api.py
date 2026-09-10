"""The HTTP surface.

Three kinds of thing are served here, and they have very different costs.

The catalogue and the precomputed passages are cheap: they are read off disk once at
startup and handed out. Screening the whole catalogue takes about nine minutes, so it
is not something a request can trigger. It happened once, offline, and
`data/survey/conjunctions.csv` is the result.

The manoeuvre is the exception. Re-propagating one object after a burn costs about a
millisecond, so that one really is computed per request.

Nothing here calls CelesTrak. The snapshot on disk is the whole world as far as this
process is concerned, and its date is in every response that depends on it.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import artefacts, probability, screening, tle
from . import catalogue as cat_mod
from .manoeuvre import Burn, apply_burn

ROOT = Path(__file__).resolve().parent.parent.parent
SURVEY_DIR = ROOT / "data" / "survey"

# Everything in this service is a statement about one dated snapshot, propagated with
# a model whose inputs carry no uncertainty. That is not a disclaimer to put in a
# footer, it is a field on the responses that depend on it.
PROVENANCE = {
    "source": "CelesTrak GP element sets, one dated snapshot, committed to the repository",
    "propagator": "SGP4 (sgp4 2.27, MIT), unmodified",
    "model_output": True,
    "trained_model": False,
    "covariance": (
        "none. Two-line element sets carry no covariance, so no collision probability is "
        "computed unless you supply the uncertainty yourself"
    ),
    "not_a_warning_service": (
        "screens a slice of the public catalogue on one date. Not a substitute for a "
        "conjunction assessment from an operator who has the observations"
    ),
}


class Manoeuvre(BaseModel):
    norad: int = Field(description="the object that burns")
    partner_norad: int = Field(description="the object it is being screened against")
    tca_offset_s: float = Field(description="seconds from window start to the unperturbed TCA")
    burn_offset_s: float = Field(description="seconds from window start to the burn")
    radial_ms: float = 0.0
    in_track_ms: float = 0.0
    cross_track_ms: float = 0.0
    span_s: float = Field(
        default=600.0,
        ge=10.0,
        le=7200.0,
        description="half width of the separation curve around TCA, in seconds",
    )
    position_sigma_km: float | None = Field(
        default=None,
        description=(
            "one-sigma spherical position uncertainty for the probability. There is no "
            "default because the element sets publish none; omit it and no probability "
            "is returned"
        ),
    )


@lru_cache(maxsize=1)
def get_catalogue() -> cat_mod.Catalogue:
    return cat_mod.load()


@lru_cache(maxsize=1)
def get_window() -> screening.Window:
    start = datetime.strptime(get_catalogue().date, "%Y-%m-%d").replace(tzinfo=UTC)
    return screening.Window.build(start, 24.0, 10.0)


@lru_cache(maxsize=1)
def get_passages() -> list[dict]:
    """The precomputed screen. Read once, kept in memory, never recomputed on request."""
    path = SURVEY_DIR / "conjunctions.csv"
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in ("miss_km", "rel_speed_kms", "altitude_km"):
            row[key] = float(row[key])
        row["norad_a"] = int(row["norad_a"])
        row["norad_b"] = int(row["norad_b"])
    return rows


@lru_cache(maxsize=1)
def get_index() -> dict:
    """NORAD id to the passages it takes part in, closest first."""
    index: dict = {}
    for row in get_passages():
        for key in ("norad_a", "norad_b"):
            index.setdefault(row[key], []).append(row)
    for rows in index.values():
        rows.sort(key=lambda r: r["miss_km"])
    return index


app = FastAPI(
    title="kessler",
    version="0.1.0",
    description=(
        "Conjunction screening over a dated public catalogue snapshot. Physics, not "
        "machine learning: no model is trained here and none runs."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/provenance")
def provenance() -> dict:
    catalogue = get_catalogue()
    return {
        "snapshot_date": catalogue.date,
        "objects": len(catalogue),
        "coverage": cat_mod.coverage(catalogue),
        "manifest": catalogue.manifest(),
        **PROVENANCE,
    }


@app.get("/api/catalogue")
def catalogue_endpoint() -> dict:
    """Every object, with the element set the browser needs to propagate it itself.

    Sent as parallel arrays rather than a list of objects. For 19,000 entries that is
    the difference between a 2 MB response and a 6 MB one, and the browser wants typed
    arrays at the other end anyway.
    """
    catalogue = get_catalogue()
    sats = catalogue.sats
    _, perigee, apogee = cat_mod.orbit_geometry(sats)
    return {
        "snapshot_date": catalogue.date,
        "count": len(catalogue),
        "norad": [e.norad for e in catalogue.entries],
        "name": [e.name for e in catalogue.entries],
        "type": [e.object_type for e in catalogue.entries],
        "group": [e.group for e in catalogue.entries],
        "perigee_km": [round(float(p) - cat_mod.EARTH_RADIUS_KM, 1) for p in perigee],
        "apogee_km": [round(float(a) - cat_mod.EARTH_RADIUS_KM, 1) for a in apogee],
        "elements": [
            {
                "n": s.no_kozai,
                "e": s.ecco,
                "i": s.inclo,
                "raan": s.nodeo,
                "argp": s.argpo,
                "m": s.mo,
                "bstar": s.bstar,
                "epoch_jd": s.jdsatepoch,
                "epoch_fr": s.jdsatepochF,
            }
            for s in sats
        ],
    }


@lru_cache(maxsize=1)
def get_tle_text() -> str:
    """The catalogue as TLE text, because satellite.js ingests nothing else.

    Encoding into the 1969 fixed-width format costs precision: the round trip is worth
    a median of 0.27 m and at worst 83 m of position over 24 hours, measured over the
    whole snapshot in tests/unit/test_tle.py. That is the globe's accuracy, and it is
    why every number in the readout comes from the server rather than from the browser.
    """
    lines = []
    for row in tle.catalogue_to_tle(get_catalogue()):
        lines.extend([row["name"], row["line1"], row["line2"]])
    return "\n".join(lines) + "\n"


@app.get("/api/catalogue.tle", response_class=PlainTextResponse)
def catalogue_tle() -> str:
    return get_tle_text()


@app.get("/api/object/{norad}")
def object_endpoint(norad: int, limit: int = Query(default=50, le=500)) -> dict:
    catalogue = get_catalogue()
    entry = catalogue.by_norad(norad)
    if entry is None:
        raise HTTPException(404, f"{norad} is not in the {catalogue.date} snapshot")
    passages = [r for r in get_index().get(norad, []) if r["classification"] == "passage"]
    artefact_rows = [r for r in get_index().get(norad, []) if r["classification"] != "passage"]
    return {
        "norad": entry.norad,
        "name": entry.name,
        "object_id": entry.object_id,
        "object_type": entry.object_type,
        "owner": entry.owner,
        "group": entry.group,
        "epoch": entry.epoch,
        "rcs_m2": entry.rcs_m2,
        "passages": passages[:limit],
        "passages_total": len(passages),
        "artefacts": artefact_rows,
        "screened_to_km": 5.0,
        "note": (
            "passages are precomputed to 5 km over the 24 hours from the snapshot date. "
            "Anything wider was screened but is not shipped, because the full result is "
            "1.5 million rows"
        ),
    }


@app.get("/api/encounter")
def encounter_endpoint(
    a: int,
    b: int,
    tca_offset_s: float,
    span_s: float = Query(default=600.0, ge=10.0, le=7200.0),
    samples: int = Query(default=241, ge=21, le=2001),
) -> dict:
    """The separation curve through one time of closest approach.

    This is the same SGP4 the screen used, sampled densely around the encounter. It is
    not a smoothed or interpolated version of the screening result.
    """
    catalogue = get_catalogue()
    index_a, index_b = catalogue.index_of(a), catalogue.index_of(b)
    if index_a is None or index_b is None:
        raise HTTPException(404, "one of those objects is not in the snapshot")
    window = get_window()
    times, distance = screening.separation_curve(
        catalogue.sats[index_a], catalogue.sats[index_b], window, tca_offset_s, span_s, samples
    )
    finite = np.isfinite(distance)
    return {
        "a": a,
        "b": b,
        "offsets_s": [float(t) for t in times],
        "separation_km": [
            None if not ok else float(d) for ok, d in zip(finite, distance, strict=True)
        ],
        "min_km": float(np.nanmin(distance)) if finite.any() else None,
        "tca_offset_s": float(times[int(np.nanargmin(distance))]) if finite.any() else None,
    }


@app.post("/api/manoeuvre")
def manoeuvre_endpoint(request: Manoeuvre) -> dict:
    """Apply a burn and re-screen the one encounter it was meant to change.

    Both objects stay on SGP4. The manoeuvred one gets a fresh element set found by
    inverting SGP4 onto its post-burn state, so this is not a two-body approximation
    being compared against a perturbed one. `inversion.residual_m` is how well that
    inversion closed, and it is the accuracy floor of everything else in the response.
    """
    catalogue = get_catalogue()
    index = catalogue.index_of(request.norad)
    partner_index = catalogue.index_of(request.partner_norad)
    if index is None or partner_index is None:
        raise HTTPException(404, "one of those objects is not in the snapshot")

    window = get_window()
    burn = Burn(
        at_offset_s=request.burn_offset_s,
        radial_ms=request.radial_ms,
        in_track_ms=request.in_track_ms,
        cross_track_ms=request.cross_track_ms,
    )
    if burn.at_offset_s >= request.tca_offset_s:
        raise HTTPException(
            422, "the burn has to happen before the encounter it is supposed to change"
        )

    try:
        inversion = apply_burn(catalogue.sats[index], burn, window.jd, window.fr)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    if not inversion.converged:
        # Two geostationary objects in the snapshot do not converge. Refusing is the
        # only honest option: a manoeuvre answer built on a 1 km element-set error
        # would look exactly like one built on a good fit.
        raise HTTPException(
            422,
            f"SGP4 inversion did not converge for {catalogue.entries[index].name} "
            f"(residual {inversion.residual_km * 1000:.1f} m). No manoeuvre is reported "
            "rather than a wrong one.",
        )

    partner = catalogue.sats[partner_index]
    # Fixed, not derived from the lead time. Scaling the window with the burn's lead
    # made the lead slider silently rezoom the chart underneath the encounter, so
    # moving one control changed the axis of a different one.
    span = request.span_s

    before_t, before_d = screening.separation_curve(
        catalogue.sats[index], partner, window, request.tca_offset_s, span, 401
    )
    after_t, after_d = screening.separation_curve(
        inversion.satrec, partner, window, request.tca_offset_s, span, 401
    )

    before_min = float(np.nanmin(before_d))
    after_min = float(np.nanmin(after_d))

    response = {
        "burn": {
            "at_offset_s": burn.at_offset_s,
            "radial_ms": burn.radial_ms,
            "in_track_ms": burn.in_track_ms,
            "cross_track_ms": burn.cross_track_ms,
            "magnitude_ms": burn.magnitude_ms,
            "lead_time_s": request.tca_offset_s - burn.at_offset_s,
        },
        "before": {
            "min_km": before_min,
            "tca_offset_s": float(before_t[int(np.nanargmin(before_d))]),
            "offsets_s": [float(t) for t in before_t],
            "separation_km": [float(d) for d in before_d],
        },
        "after": {
            "min_km": after_min,
            "tca_offset_s": float(after_t[int(np.nanargmin(after_d))]),
            "offsets_s": [float(t) for t in after_t],
            "separation_km": [float(d) for d in after_d],
        },
        "change_km": after_min - before_min,
        "inversion": {
            "residual_m": inversion.residual_km * 1000.0,
            "iterations": inversion.iterations,
            "converged": inversion.converged,
            "note": (
                "the post-burn object is propagated by SGP4 on element sets fitted to its "
                "post-burn state, not by a different propagator. This residual is how well "
                "that fit closed and is the floor on the change reported above"
            ),
        },
    }

    if request.position_sigma_km is not None:
        entry_a = catalogue.entries[index]
        entry_b = catalogue.entries[partner_index]
        combined_radius = probability.radius_from_rcs(entry_a.rcs_m2) + probability.radius_from_rcs(
            entry_b.rcs_m2
        )
        response["probability"] = {
            "before": probability.collision_probability(
                before_min, request.position_sigma_km, combined_radius
            ).as_dict(),
            "after": probability.collision_probability(
                after_min, request.position_sigma_km, combined_radius
            ).as_dict(),
            "sweep_before": probability.sweep(before_min, combined_radius),
            "warning": (
                "these probabilities are conditional on the covariance you supplied. The "
                "element sets publish none. Change the assumption and the answer moves by "
                "orders of magnitude, which sweep_before shows"
            ),
        }

    return response


@app.get("/api/artefacts")
def artefacts_endpoint() -> dict:
    """What was filtered out, and why. Deliberately easy to find."""
    rows = [r for r in get_passages() if r["classification"] != "passage"]
    rows.sort(key=lambda r: r["miss_km"])
    return {
        "rules": {
            "shared-element-set": artefacts.classify(0, 0, 9.9, {0: 1}).reason,
            "co-orbiting": artefacts.classify(0, 1, 0.0, {0: 1, 1: 2}).reason,
        },
        "count": len(rows),
        "rows": rows,
        "note": (
            "unfiltered, the twenty closest approaches in this snapshot are the space "
            "station against its own docked vehicles, at zero kilometres"
        ),
    }


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "snapshot": get_catalogue().date, "passages": len(get_passages())}
