"""The kit generated worlds are built with (requirements S17.5): a world is a plain description
drawn from a seed, its records each a point on named axes, made through the API by its test
and held to a reference model or to invariants.

What every world shares lives here:

1. `Axes`: the axes of each kind of record, the pairs of values no record can hold, every pair
   that can, and the pairs a set of worlds reaches, so pairwise coverage is checked without a
   server.
2. `deal`: an axis's values dealt from a shuffled deck, so each world holds every value about
   equally and the pairs fall differently in each.
3. `Plant` and `planted`: a bug put back on purpose. Each world names the bugs it must catch;
   `test_worlds_catch_their_plants` runs a world under each one and fails when the world still
   passes, so a world that has stopped seeing a kind of bug says so.
4. `Decoy`: a second household, a stranger to the world's, holding the same symbols, amounts
   and dates (its own trades, statement values, files and transfers). Every world is made with
   one; its figures are held to a reference that knows nothing of the decoy, so any figure that
   reads another household's data shows (S10.3, S4.10).
5. Per-world timing: `conftest.pytest_terminal_summary` adds up each world's tests.
"""

from __future__ import annotations

import contextlib
import itertools
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from unittest import mock

Pair = frozenset
Impossible = Callable[[str, tuple[str, str], tuple[str, str]], bool]


class Axes:
    """The axes of each kind of record ({kind: {axis: values}}) and the pairs no record can
    hold (`impossible(kind, (axis, value), (axis, value))`)."""

    def __init__(self, axes: dict[str, dict[str, tuple]], impossible: Impossible | None = None):
        self.axes = axes
        self.impossible = impossible or (lambda kind, a, b: False)

    def __getitem__(self, kind: str) -> dict[str, tuple]:
        return self.axes[kind]

    def __iter__(self):
        return iter(self.axes)

    def items(self):
        return self.axes.items()

    def all_pairs(self, kind: str) -> set[Pair]:
        """Every pair of values of two axes of one kind of record that can exist."""
        out = set()
        axes = self.axes[kind]
        for x, y in itertools.combinations(axes, 2):
            for vx in axes[x]:
                for vy in axes[y]:
                    if not self.impossible(kind, (x, vx), (y, vy)):
                        out.add(Pair({(x, vx), (y, vy)}))
        return out

    def pairs(self, records: dict[str, list[dict]]) -> dict[str, set[Pair]]:
        """The pairs a world's records reach, by kind."""
        out: dict[str, set[Pair]] = {}
        for kind, rows in records.items():
            got = set()
            for r in rows:
                for x, y in itertools.combinations(self.axes[kind], 2):
                    got.add(Pair({(x, r[x]), (y, r[y])}))
            out[kind] = got
        return out

    def missing(self, worlds: Iterable) -> dict[str, list]:
        """The pairs that can exist and no world reaches, by kind; empty when coverage is
        pairwise. Each world has `records()`."""
        got: dict[str, set[Pair]] = {k: set() for k in self.axes}
        for w in worlds:
            for kind, ps in self.pairs(w.records()).items():
                got[kind] |= ps
        out = {}
        for kind in self.axes:
            left = self.all_pairs(kind) - got[kind]
            if left:
                out[kind] = sorted(sorted(p) for p in left)
        return out

    def impossible_reached(self, worlds: Iterable) -> dict[str, list]:
        """Pairs a world holds that `impossible` says can't exist: the description and the
        rules disagree."""
        out: dict[str, list] = {}
        for w in worlds:
            for kind, ps in self.pairs(w.records()).items():
                for p in ps:
                    a, b = sorted(p)
                    if a[0] != b[0] and self.impossible(kind, a, b):
                        out.setdefault(kind, []).append((w, sorted(p)))
        return out


def deal(rnd: random.Random, values: tuple, n: int) -> list:
    """n values dealt from a shuffled deck of `values` repeated: each about equally often."""
    deck = [values[k % len(values)] for k in range(n)]
    rnd.shuffle(deck)
    return deck


def decks(rnd: random.Random, axes: dict[str, tuple], n: int, skip: tuple = ()) -> list[dict]:
    """n records, each axis's values dealt from its own deck."""
    dealt = {name: deal(rnd, values, n) for name, values in axes.items() if name not in skip}
    return [{name: d[i] for name, d in dealt.items()} for i in range(n)]


@dataclass
class Plant:
    """A bug put back: `target` ("module.path:attribute") replaced by `replacement` while a
    world runs. `why` names the claim or rule it stands for."""

    name: str
    target: str
    replacement: object
    why: str = ""

    def patch(self):
        module, attr = self.target.split(":")
        return mock.patch(f"{module}.{attr}", self.replacement)


@contextlib.contextmanager
def planted(plant: Plant):
    with plant.patch():
        yield


def catches(run: Callable[[], None], plant: Plant) -> bool:
    """Whether `run` (a world's checks) fails with the bug planted."""
    with planted(plant):
        try:
            run()
        except AssertionError:
            return True
    return False


@dataclass
class Decoy:
    """A second household's data, meant to look like the world's: the same symbols, amounts
    and dates. `made` is filled by the world's maker with what it created (by kind), so a test
    can say what the decoy holds."""

    username: str = "mallory"
    symbols: list[str] = field(default_factory=list)
    days: list = field(default_factory=list)
    made: dict[str, list[str]] = field(default_factory=dict)
