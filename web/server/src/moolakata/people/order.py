"""The order people are named in (requirements S10.10.7): a couple, as in a joint tax book's
name, by (sex, name), men first; a person's children oldest first."""

from typing import Protocol


class Born(Protocol):
    name: str
    birthYear: int | None
    birthMonth: int | None
    birthDay: int | None


def couple_key(sex: str, name: str) -> tuple[int, str]:
    """The (sex, name) a couple is named by, men first."""
    return (0 if sex == "male" else 1, name.casefold())


def oldest_first_key(p: Born) -> tuple:
    """The oldest first, by birthday: one whose birth year isn't known after those whose is, a
    month or a day not known after those known in the same year, twins by name."""
    return (
        p.birthYear is None,
        p.birthYear or 0,
        p.birthMonth or 13,
        p.birthDay or 32,
        p.name.casefold(),
    )
