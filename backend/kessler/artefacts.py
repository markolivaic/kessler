"""The two ways a pair looks like a conjunction without being one.

Both were found by looking at real output rather than by reasoning about it, and both
sit at the top of a naive result list where they do the most damage. Unfiltered, the
twenty closest approaches in a 24 hour screen of the 2026-08-17 snapshot are the
International Space Station against its own docked vehicles, at exactly zero
kilometres.

Each rule is a predicate with its evidence attached, so a caller can ask not only
whether a pair was filtered but why, and the answer is a sentence rather than a
boolean.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

# Two entries whose mean elements match to this relative tolerance are one object
# published twice. Float equality would also work on the snapshot tested, since the
# duplicates are byte-identical element sets, but a tolerance survives a future
# publisher that rounds differently.
ELEMENT_MATCH_RTOL = 1e-9

# Below this relative speed at closest approach, a pair is flying together rather
# than passing. Measured on the 2026-08-17 snapshot: deliberate formations top out
# near 30 m/s, real passages start near 200 m/s, so the cut sits in a gap rather than
# through a population. scripts/survey_conjunctions.py reports the sensitivity.
CO_ORBIT_FLOOR_KMS = 0.05


class Classification(StrEnum):
    PASSAGE = "passage"
    SHARED_ELEMENT_SET = "shared-element-set"
    CO_ORBITING = "co-orbiting"

    @property
    def is_artefact(self) -> bool:
        return self is not Classification.PASSAGE


@dataclass(frozen=True)
class Verdict:
    classification: Classification
    reason: str

    @property
    def is_artefact(self) -> bool:
        return self.classification.is_artefact


def element_set_groups(sats, rtol: float = ELEMENT_MATCH_RTOL) -> dict[int, int]:
    """Map catalogue index to a group id, where one group shares one element set.

    A station and everything docked to it are published on a single element set, so
    SGP4 gives them one identical trajectory. Their computed miss distance is exactly
    zero and it describes the publishing convention, not the sky.
    """
    key = np.stack(
        [
            np.array([s.no_kozai for s in sats]),
            np.array([s.ecco for s in sats]),
            np.array([s.inclo for s in sats]),
            np.array([s.nodeo for s in sats]),
            np.array([s.argpo for s in sats]),
            np.array([s.mo for s in sats]),
        ],
        axis=1,
    )
    order = np.lexsort(key.T[::-1])
    ordered = key[order]
    scale = np.maximum(np.abs(ordered), 1e-12)
    tolerance = rtol * np.minimum(scale[:-1], scale[1:])
    same_as_previous = np.all(np.abs(np.diff(ordered, axis=0)) <= tolerance, axis=1)

    groups: dict[int, int] = {int(order[0]): 0}
    group_id = 0
    for position, shared in enumerate(same_as_previous, start=1):
        if not shared:
            group_id += 1
        groups[int(order[position])] = group_id
    return groups


def classify(
    index_a: int,
    index_b: int,
    rel_speed_kms: float,
    groups: dict[int, int],
    floor_kms: float = CO_ORBIT_FLOOR_KMS,
) -> Verdict:
    """Decide what a screened pair actually is."""
    if groups.get(index_a) == groups.get(index_b):
        return Verdict(
            Classification.SHARED_ELEMENT_SET,
            "both entries carry the same element set, so this is one tracked object "
            "published twice, usually a station and a vehicle docked to it",
        )
    if rel_speed_kms < floor_kms:
        return Verdict(
            Classification.CO_ORBITING,
            f"relative speed {rel_speed_kms * 1000:.1f} m/s at closest approach is below "
            f"the {floor_kms * 1000:.0f} m/s floor, so these two fly together rather than "
            "pass. There is no time of closest approach to find and no manoeuvre to decide",
        )
    return Verdict(Classification.PASSAGE, "two distinct objects passing each other")
