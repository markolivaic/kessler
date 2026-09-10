"""The OMM to TLE writer, and what the old format costs.

The snapshot is OMM CSV. The browser propagates with satellite.js, which reads TLE text
and nothing else. So element sets are re-encoded into a fixed-width format from 1969
that holds eight digits of mean motion and seven of eccentricity, and past that the
precision is gone.

This does not claim the round trip is lossless. It measures what it loses.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from kessler import catalogue as cat_mod
from kessler import screening, tle
from sgp4.api import Satrec, SatrecArray


@pytest.fixture(scope="module")
def catalogue():
    return cat_mod.load()


@pytest.fixture(scope="module")
def window():
    return screening.Window.build(datetime(2026, 8, 17, tzinfo=UTC), 24.0, 10.0)


@pytest.fixture(scope="module")
def round_trip(catalogue, window):
    """Every object, written out and parsed back, compared over a full day."""
    rebuilt = []
    for entry in catalogue.entries:
        _, line1, line2 = tle.to_tle(
            catalogue.sats[entry.index], entry.name, entry.object_id, entry.epoch
        )
        rebuilt.append(Satrec.twoline2rv(line1, line2))

    times = np.array([0.0, 3600.0, 43200.0, 86400.0])
    jd = np.full(len(times), window.jd)
    fr = window.fr + times / 86400.0
    original_errors, original, _ = SatrecArray(catalogue.sats).sgp4(jd, fr)
    rebuilt_errors, again, _ = SatrecArray(rebuilt).sgp4(jd, fr)
    clean = np.all(original_errors == 0, axis=1) & np.all(rebuilt_errors == 0, axis=1)
    distance = np.linalg.norm(original - again, axis=2)
    finite = clean & np.all(np.isfinite(distance), axis=1)
    return distance[finite] * 1000.0


def test_every_object_parses_back(catalogue):
    for entry in catalogue.entries:
        _, line1, line2 = tle.to_tle(
            catalogue.sats[entry.index], entry.name, entry.object_id, entry.epoch
        )
        satrec = Satrec.twoline2rv(line1, line2)
        assert satrec.satnum == entry.norad


def test_the_lines_are_the_right_shape(catalogue):
    entry = catalogue.entries[catalogue.index_of(25544)]
    name, line1, line2 = tle.to_tle(
        catalogue.sats[entry.index], entry.name, entry.object_id, entry.epoch
    )
    assert name == "ISS (ZARYA)"
    assert len(line1) == 69, f"line 1 is {len(line1)} characters, the format says 69"
    assert len(line2) == 69, f"line 2 is {len(line2)} characters, the format says 69"
    assert line1.startswith("1 25544")
    assert line2.startswith("2 25544")


def test_the_checksums_are_right(catalogue):
    """A wrong checksum is accepted by some parsers and rejected by others."""
    for entry in catalogue.entries[:400]:
        _, line1, line2 = tle.to_tle(
            catalogue.sats[entry.index], entry.name, entry.object_id, entry.epoch
        )
        assert int(line1[68]) == tle.checksum(line1)
        assert int(line2[68]) == tle.checksum(line2)


def test_the_round_trip_cost_is_small_and_known(round_trip):
    median = float(np.median(round_trip))
    p99 = float(np.percentile(round_trip, 99))
    worst = float(round_trip.max())
    assert median < 1.0, f"median round trip error {median:.3f} m"
    assert p99 < 20.0, f"p99 round trip error {p99:.3f} m"
    # The number the README quotes. Generous headroom so a snapshot change does not
    # break the build, tight enough that a real regression would.
    assert worst < 250.0, f"worst round trip error {worst:.3f} m"


def test_the_round_trip_is_never_wildly_wrong(round_trip):
    """A formatting slip shows up as kilometres, not metres."""
    assert (round_trip > 1000.0).sum() == 0


def test_exponential_field_encodes_bstar_the_way_the_format_expects():
    assert tle._exponential(0.0) == " 00000-0"
    assert tle._exponential(0.00012345) == " 12345-3"
    assert tle._exponential(-0.00012345) == "-12345-3"
    for text in (tle._exponential(1.2e-9), tle._exponential(-3.4e-2)):
        assert len(text) == 8


def test_decimal_point_assumed_fields_drop_the_leading_zero():
    assert tle._decimal_point_assumed(0.0027786, 7) == "0027786"
    assert tle._decimal_point_assumed(0.0, 7) == "0000000"
    assert len(tle._decimal_point_assumed(0.1234567891, 7)) == 7


def test_checksum_counts_a_minus_sign_as_one():
    plain = "1" + "0" * 67
    assert tle.checksum(plain) == 1
    assert tle.checksum("-" + "0" * 67) == 1
    # Two minus signs are worth exactly two more than two plus signs.
    with_minus = "1 00000U 00000A   00000.00000000  .00000000  00000-0  00000-0 0  000"
    with_plus = "1 00000U 00000A   00000.00000000  .00000000  00000+0  00000+0 0  000"
    assert tle.checksum(with_minus) == (tle.checksum(with_plus) + 2) % 10


def test_checksum_ignores_the_check_digit_itself():
    """Column 69 is the checksum, so it must not be counted into its own sum."""
    body = "1" + "0" * 67
    assert tle.checksum(body + "7") == tle.checksum(body + "3")


def test_designator_field_is_eight_columns():
    assert tle.format_designator("1998-067A") == "98067A  "
    assert tle.format_designator("1999-025X") == "99025X  "
    assert len(tle.format_designator("")) == 8
    assert len(tle.format_designator("2025-313AB")) == 8


def test_the_catalogue_serialises_to_three_lines_per_object(catalogue):
    rows = tle.catalogue_to_tle(catalogue)
    assert len(rows) == len(catalogue.entries)
    assert rows[0]["line1"].startswith("1 ")
    assert rows[0]["line2"].startswith("2 ")


def test_alpha5_encodes_catalogue_numbers_past_99999():
    """The catalogue crossed 99999 in 2026 and the field is five columns wide."""
    assert tle.format_satnum(25544) == "25544"
    assert tle.format_satnum(99999) == "99999"
    assert tle.format_satnum(100000) == "A0000"
    assert tle.format_satnum(100332) == "A0332"
    assert tle.format_satnum(148493) == "E8493"
    for number in (900, 25544, 99999, 100000, 100332, 148493, 339999):
        assert len(tle.format_satnum(number)) == 5
        assert tle.parse_satnum(tle.format_satnum(number)) == number


def test_alpha5_leaves_out_the_letters_that_read_as_digits():
    """I and O are excluded so a catalogue number cannot be read as 1 or 0."""
    assert "I" not in tle.ALPHA5
    assert "O" not in tle.ALPHA5


def test_high_catalogue_numbers_survive_the_round_trip(catalogue):
    high = [e for e in catalogue.entries if e.norad >= 100000]
    assert high, "this snapshot has no Alpha-5 objects, the test is not exercising"
    for entry in high[:40]:
        _, line1, line2 = tle.to_tle(
            catalogue.sats[entry.index], entry.name, entry.object_id, entry.epoch
        )
        assert len(line1) == 69
        assert len(line2) == 69
        satrec = Satrec.twoline2rv(line1, line2)
        assert satrec.satnum == entry.norad, f"{entry.name} came back as {satrec.satnum}"


def test_a_second_derivative_too_small_for_the_field_becomes_zero():
    """One exponent column cannot hold 1e-15, and SGP4 does not read this anyway."""
    assert tle._exponential(-2.8481e-12) == " 00000-0"
    assert tle._exponential(6.7e-16) == " 00000-0"
    # Anything the field can hold is still written.
    assert tle._exponential(3.7e-6) != " 00000-0"
    assert len(tle._exponential(-2.8481e-12)) == 8
