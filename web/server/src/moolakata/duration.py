"""Durations as people type them (requirements S12.13): one or more parts, each a whole number
and a unit, `w` (weeks), `d` (days), `h` (hours) or `m` (minutes), largest first, each unit at
most once, with or without spaces: `1d`, `90m`, `2w 3d 4h`, `2w3d`, and at most 52 weeks. The
browser has the same helper in web/ui/kit/duration.js."""

import datetime as dt
import re

UNITS = {
    "w": dt.timedelta(weeks=1),
    "d": dt.timedelta(days=1),
    "h": dt.timedelta(hours=1),
    "m": dt.timedelta(minutes=1),
}
ORDER = "wdhm"
PART = re.compile(r"\s*(\d+)\s*([a-zA-Z]+)\s*")
# The longest a duration is (S12.13): a pause, the one asked for, ends on its own within a
# year (S11.7.2).
LONGEST = dt.timedelta(weeks=52)
TOO_LONG = "A duration is at most 52w."


class DurationError(ValueError):
    """A duration that doesn't follow the grammar, with why, worded for the field."""


def parse(text: str) -> dt.timedelta:
    s = (text or "").strip()
    if not s:
        raise DurationError("Type a duration, such as 1d or 2w 3d 4h.")
    total, pos, last = dt.timedelta(0), 0, -1
    while pos < len(s):
        m = PART.match(s, pos)
        if not m:
            raise DurationError(f"“{s[pos:].strip()}” isn't a number and a unit (w, d, h or m).")
        unit = m.group(2).lower()
        if unit not in UNITS:
            raise DurationError(f"“{m.group(2)}” isn't a unit: use w, d, h or m.")
        at = ORDER.index(unit)
        if at == last:
            raise DurationError(f"“{unit}” is given twice.")
        if at < last:
            raise DurationError("Give the units largest first: w, then d, then h, then m.")
        last = at
        try:
            total += int(m.group(1)) * UNITS[unit]
        except OverflowError, ValueError:  # past what a timedelta, or an int, holds
            raise DurationError(TOO_LONG) from None
        pos = m.end()
    if total <= dt.timedelta(0):
        raise DurationError("A duration is at least a minute.")
    if total > LONGEST:
        raise DurationError(TOO_LONG)
    return total


def format(td: dt.timedelta) -> str:
    """A duration as it would be typed, largest units first: 2w 3d 4h."""
    minutes = int(td.total_seconds() // 60)
    parts = []
    for unit, size in (("w", 7 * 24 * 60), ("d", 24 * 60), ("h", 60), ("m", 1)):
        if minutes >= size:
            parts.append(f"{minutes // size}{unit}")
            minutes %= size
    return " ".join(parts) or "0m"
