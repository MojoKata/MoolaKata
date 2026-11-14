"""The order people are named in (requirements S10.10.7): a couple by (sex, name), men first;
a person's children oldest first."""

from dataclasses import dataclass

import pytest

from moolakata.people import order


@dataclass
class P:
    name: str
    birthYear: int | None = None
    birthMonth: int | None = None
    birthDay: int | None = None


def named(couple: list[tuple[str, str]]) -> list[str]:
    return [n for _, n in sorted(couple, key=lambda x: order.couple_key(*x))]


@pytest.mark.parametrize(
    ("couple", "want"),
    [
        ([("female", "Jane"), ("male", "John")], ["John", "Jane"]),  # however they were added
        ([("male", "John"), ("female", "Jane")], ["John", "Jane"]),
        ([("female", "Ann"), ("male", "Zed")], ["Zed", "Ann"]),  # the sex first, then the name
        ([("female", "Zoe"), ("female", "ann")], ["ann", "Zoe"]),  # the name, in any case
        ([("male", "Max"), ("male", "Ben")], ["Ben", "Max"]),
    ],
)
def test_a_couple_is_named_by_sex_then_name(couple, want):
    assert named(couple) == want


def test_children_are_listed_oldest_first():
    kids = [
        P("Lisa", 2018, 10, 20),
        P("No year"),
        P("Bart", 2012, 3, 3),
        P("May", 2012, 5),  # a month, no day
        P("Year only", 2012),
        P("Twin b", 2015, 6, 1),
        P("Twin A", 2015, 6, 1),
        P("March 4th", 2012, 3, 4),
    ]
    got = [k.name for k in sorted(kids, key=order.oldest_first_key)]
    assert got == [
        "Bart",  # 2012-03-03
        "March 4th",  # a day later
        "May",  # May, its day unknown: after the known days of 2012 before it
        "Year only",  # 2012, month unknown: after those known that year
        "Twin A",  # twins by name, in any case
        "Twin b",
        "Lisa",
        "No year",  # no birth year: last
    ]
