"""Write element sets back out as two-line element text.

The snapshot is OMM CSV, which is the modern encoding. The browser propagates with
satellite.js, and satellite.js ingests exactly one thing: TLE text. So the element
sets have to go over the wire in the old fixed-width format.

That format is not a serialisation of the numbers, it is a serialisation from 1969
designed for punched cards, and it drops precision in specific places. Eccentricity
gets seven digits with the decimal point assumed. Mean motion gets eight. B* gets a
five digit mantissa and a one digit exponent. Anything past that is gone.

So the honest thing is not to claim this is lossless, it is to measure what it costs.
`tests/unit/test_tle.py` round-trips every object in the snapshot through this writer
and back through SGP4, and reports the worst position disagreement it produces.
"""

from __future__ import annotations

import numpy as np

DEGREES = 180.0 / np.pi


def checksum(line: str) -> int:
    """Modulo ten of the digits, with every minus sign counting as one."""
    total = 0
    for character in line[:68]:
        if character.isdigit():
            total += int(character)
        elif character == "-":
            total += 1
    return total % 10


def _decimal_point_assumed(value: float, digits: int) -> str:
    """0.0123 with 7 digits becomes '0123000'. The leading '0.' is implied."""
    text = f"{abs(value):.{digits}f}"
    return text[2 : 2 + digits].ljust(digits, "0")


def _exponential(value: float) -> str:
    """B* and the second derivative use a five digit mantissa and a signed exponent.

    0.00012345 becomes ' 12345-3', meaning 0.12345e-3.

    The exponent field is one character wide, so anything below 1e-9 cannot be written
    at all and is emitted as zero. In this snapshot that applies to 104 of the 105
    non-zero second derivatives, whose magnitudes run down to 7e-16. Nothing is lost by
    it: standard SGP4 does not read the second derivative, and a value that small is
    below the resolution of the element set it came from.
    """
    if value == 0:
        return " 00000-0"
    sign = "-" if value < 0 else " "
    magnitude = abs(value)
    exponent = int(np.floor(np.log10(magnitude))) + 1
    mantissa = magnitude / (10.0**exponent)
    mantissa_digits = f"{mantissa:.5f}"[2:7]
    # Rounding 0.99999x up to 1.00000 pushes a digit past the field.
    if mantissa_digits == "00000" and mantissa >= 0.999995:
        exponent += 1
        mantissa_digits = "10000"
    if abs(exponent) > 9:
        return " 00000-0"
    exponent_sign = "-" if exponent < 0 else "+"
    return f"{sign}{mantissa_digits}{exponent_sign}{abs(exponent)}"


# Catalogue numbers ran past 99999 in 2026 and the five column field cannot hold six
# digits. The agreed workaround is Alpha-5: the leading digit becomes a letter worth
# ten more per step, with I and O left out so they cannot be read as one and zero.
ALPHA5 = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def format_satnum(norad: int) -> str:
    """Five columns, whatever the catalogue number is.

    In the 2026-08-17 snapshot 265 objects are past 99999, the highest being 100332.
    Writing those with %05d produces a six character field, which shifts every column
    after it and silently turns 100000 into 10000.
    """
    if norad < 100000:
        return f"{norad:05d}"
    leading = norad // 10000
    index = leading - 10
    if not 0 <= index < len(ALPHA5):
        raise ValueError(f"catalogue number {norad} is past what Alpha-5 can encode")
    return f"{ALPHA5[index]}{norad % 10000:04d}"


def parse_satnum(field_text: str) -> int:
    """The inverse, so a test can check the encoding round trips."""
    head = field_text[0]
    if head.isdigit():
        return int(field_text)
    return (ALPHA5.index(head) + 10) * 10000 + int(field_text[1:])


def epoch_to_yyddd(epoch_iso: str) -> str:
    """ISO epoch to the TLE's two digit year plus fractional day of year."""
    from datetime import datetime

    moment = datetime.fromisoformat(epoch_iso)
    start_of_year = moment.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    day_of_year = (moment - start_of_year).total_seconds() / 86400.0 + 1.0
    return f"{moment.year % 100:02d}{day_of_year:012.8f}"


def format_designator(object_id: str) -> str:
    """1999-025A becomes '99025A  ', which is the eight column field."""
    if not object_id or "-" not in object_id:
        return " " * 8
    year, rest = object_id.split("-", 1)
    return f"{year[2:]:>2}{rest:<6}"[:8]


def to_tle(satrec, name: str, object_id: str, epoch_iso: str) -> tuple[str, str, str]:
    """One initialised Satrec back into three lines of TLE text."""
    number = format_satnum(int(satrec.satnum))
    line1 = (
        f"1 {number}U {format_designator(object_id)} {epoch_to_yyddd(epoch_iso)} "
        f"{' ' if satrec.ndot >= 0 else '-'}.{_decimal_point_assumed(satrec.ndot, 8)} "
        f"{_exponential(satrec.nddot)} {_exponential(satrec.bstar)} 0  999"
    )
    line2 = (
        f"2 {number} "
        f"{satrec.inclo * DEGREES:8.4f} "
        f"{satrec.nodeo * DEGREES:8.4f} "
        f"{_decimal_point_assumed(satrec.ecco, 7)} "
        f"{satrec.argpo * DEGREES:8.4f} "
        f"{satrec.mo * DEGREES:8.4f} "
        f"{satrec.no_kozai * 1440.0 / (2 * np.pi):11.8f}"
        f"{0:5d}"
    )
    line1 = f"{line1}{checksum(line1)}"
    line2 = f"{line2}{checksum(line2)}"
    return name, line1, line2


def catalogue_to_tle(catalogue) -> list[dict]:
    """Every object in a snapshot as TLE text, ready to hand to a browser."""
    out = []
    for entry in catalogue.entries:
        satrec = catalogue.sats[entry.index]
        name, line1, line2 = to_tle(satrec, entry.name, entry.object_id, entry.epoch)
        out.append({"name": name, "line1": line1, "line2": line2})
    return out
