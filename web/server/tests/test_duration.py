"""Durations as typed (requirements S12.13), on the server and in the browser."""

import datetime as dt

import pytest

from moolakata import duration


@pytest.mark.parametrize(
    "text, want",
    [
        ("1d", dt.timedelta(days=1)),
        ("90m", dt.timedelta(minutes=90)),
        ("2w 3d 4h", dt.timedelta(weeks=2, days=3, hours=4)),
        ("2w3d", dt.timedelta(weeks=2, days=3)),
        ("  1H 30M ", dt.timedelta(hours=1, minutes=30)),
        ("52w", dt.timedelta(weeks=52)),
        ("51w 7d", dt.timedelta(weeks=52)),
    ],
)
def test_durations_read_as_typed(text, want):
    assert duration.parse(text) == want


@pytest.mark.parametrize(
    "text, why",
    [
        ("", "Type a duration"),
        ("3", "isn't a number and a unit"),
        ("2x", "isn't a unit"),
        ("1d 2d", "given twice"),
        ("4h 2d", "largest first"),
        ("0d", "at least a minute"),
        ("1 day", "isn't a unit"),
        # At most 52 weeks (S12.13), however far past: never an overflow.
        ("52w 1m", "at most 52w"),
        ("1000000w", "at most 52w"),
        ("999999999w", "at most 52w"),
        ("99999999999999999999m", "at most 52w"),
        pytest.param("9" * 5000 + "m", "at most 52w", id="5000 digits"),
    ],
)
def test_other_text_is_refused_with_why(text, why):
    with pytest.raises(duration.DurationError, match=why):
        duration.parse(text)


def test_a_duration_shows_as_it_would_be_typed():
    assert duration.format(dt.timedelta(weeks=2, days=3, hours=4)) == "2w 3d 4h"
    assert duration.format(dt.timedelta(minutes=90)) == "1h 30m"
    assert duration.format(duration.parse("2w3d")) == "2w 3d"
