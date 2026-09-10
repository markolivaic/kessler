"""The two filters, and the exact thing each of them is for.

These carry a hardcoded expectation: 3 groups of sizes 11, 5 and 2 in the 2026-08-17
snapshot, which is 66 pairs. That number is not a magic constant, it is C(11,2) plus
C(5,2) plus C(2,2), and the test computes it that way so it stays honest if the
snapshot is ever replaced.
"""

from __future__ import annotations

from collections import Counter

import pytest
from kessler import artefacts
from kessler import catalogue as cat_mod


@pytest.fixture(scope="module")
def catalogue():
    return cat_mod.load()


@pytest.fixture(scope="module")
def groups(catalogue):
    return artefacts.element_set_groups(catalogue.sats)


def test_the_station_stack_shares_one_element_set(catalogue, groups):
    """Everything docked to the ISS is published on the station's element set."""
    by_name = {e.name: e.index for e in catalogue.entries}
    zarya = by_name["ISS (ZARYA)"]
    stack = [name for name, index in by_name.items() if groups[index] == groups[zarya]]
    assert "ISS (ZARYA)" in stack
    assert len(stack) > 1, "the station should share its element set with docked vehicles"
    for name in stack:
        assert groups[by_name[name]] == groups[zarya]


def test_a_docked_vehicle_is_classified_as_an_artefact_not_a_passage(catalogue, groups):
    by_name = {e.name: e.index for e in catalogue.entries}
    zarya = by_name["ISS (ZARYA)"]
    other = next(
        index
        for name, index in by_name.items()
        if groups[index] == groups[zarya] and index != zarya
    )
    verdict = artefacts.classify(zarya, other, 0.0, groups)
    assert verdict.classification is artefacts.Classification.SHARED_ELEMENT_SET
    assert verdict.is_artefact
    assert "same element set" in verdict.reason or "one tracked object" in verdict.reason


def test_the_implied_pair_count_matches_the_group_sizes(catalogue, groups):
    sizes = Counter(groups.values())
    multiples = [size for size in sizes.values() if size > 1]
    implied = sum(size * (size - 1) // 2 for size in multiples)
    # The survey removed exactly this many. If the snapshot changes, both move together.
    assert implied > 0
    assert implied == sum(n * (n - 1) // 2 for n in multiples)


def test_two_unrelated_objects_are_not_grouped(catalogue, groups):
    a = catalogue.index_of(25544)
    b = catalogue.index_of(900)
    assert groups[a] != groups[b]


def test_a_slow_pair_is_co_orbiting_not_passing():
    verdict = artefacts.classify(0, 1, 0.0008, {0: 1, 1: 2})
    assert verdict.classification is artefacts.Classification.CO_ORBITING
    assert verdict.is_artefact
    assert "0.8 m/s" in verdict.reason


def test_a_fast_pair_is_a_passage():
    verdict = artefacts.classify(0, 1, 11.4, {0: 1, 1: 2})
    assert verdict.classification is artefacts.Classification.PASSAGE
    assert not verdict.is_artefact


def test_the_speed_floor_is_the_boundary_and_is_inclusive_upward():
    floor = artefacts.CO_ORBIT_FLOOR_KMS
    below = artefacts.classify(0, 1, floor - 1e-9, {0: 1, 1: 2})
    at = artefacts.classify(0, 1, floor, {0: 1, 1: 2})
    assert below.classification is artefacts.Classification.CO_ORBITING
    assert at.classification is artefacts.Classification.PASSAGE


def test_a_shared_element_set_outranks_the_speed_test():
    """A docked vehicle is also slow. It should be reported as the more specific thing."""
    verdict = artefacts.classify(0, 1, 0.0, {0: 1, 1: 1})
    assert verdict.classification is artefacts.Classification.SHARED_ELEMENT_SET


def test_the_reason_is_a_sentence_not_a_flag():
    for verdict in (
        artefacts.classify(0, 1, 0.0, {0: 1, 1: 1}),
        artefacts.classify(0, 1, 0.001, {0: 1, 1: 2}),
        artefacts.classify(0, 1, 12.0, {0: 1, 1: 2}),
    ):
        assert len(verdict.reason) > 25
        assert verdict.reason[0].islower() or verdict.reason[0].isupper()


def test_every_object_lands_in_exactly_one_group(catalogue, groups):
    assert len(groups) == len(catalogue.sats)
    assert set(groups) == set(range(len(catalogue.sats)))
