"""Generated worlds of money moved for taxes (requirements S2.2, S8.1, S8.5, S8.6; the values,
taxes and options walk, 10.2): retirement money moved in and out by every route, an HSA's
coverage and its owner's age, foreign tax and coins received as income, and shares moved in by
every route across the one-year line, drawn from a seed. A world is a plain description; the
reference functions below work out from it alone, as plainly as possible, what the 2026 tax
book's Retirement and Income panels and Form 8949 must say; `test_tax_moves_world` makes each
world through the API and holds the panels to them.

Records, each in accounts of its own:

- a **move** of retirement money: an owner's contribution, an employer's, a rollover from an
  IRA or a 401(k), a conversion to Roth, a distribution; matched as a transfer between two of
  the owner's accounts, or typed into one with its source set;
- an **hsa**: its coverage (self-only, family, unset) and whether the employer put in too;
- an **income**: foreign tax a fund paid, or coins received as income, typed or imported, a
  reward sold later or not;
- a **move in** of shares: paired with a transfer out of another account, typed with its lots,
  or arriving without them and given them after; sold before or after a year from the day
  bought.

Per world, the owner's age: under 50, or 55 and over (the catch-ups).
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field
from decimal import Decimal

from worlds import Axes, Plant, decks

D = Decimal
YEAR = 2026
TODAY = dt.date(2026, 12, 20)
AGES = ("under-50", "55-plus")
BORN = {"under-50": 1990, "55-plus": 1966}

MOVES = ("employee", "employer", "rollover-ira", "rollover-401k", "conversion", "distribution")
ROUTES = ("pair", "typed")
COVERAGES = ("self", "family", "unset")
EMPLOYER = ("none", "some")
INCOMES = ("foreign-tax", "reward")
HOW = ("typed", "imported")
SOLD = ("kept", "sold")
MOVE_INS = ("paired", "typed-lots", "filled-later")
CROSSING = ("before-a-year", "after-a-year")

_AXES = {
    "move": {"age": AGES, "move": MOVES, "route": ROUTES},
    "hsa": {"age": AGES, "coverage": COVERAGES, "employer": EMPLOYER},
    "income": {"age": AGES, "income": INCOMES, "how": HOW, "sold": SOLD},
    "move-in": {"age": AGES, "how": MOVE_INS, "crossing": CROSSING},
}


def _impossible(kind: str, a: tuple[str, str], b: tuple[str, str]) -> bool:
    k = {a[0]: a[1], b[0]: b[1]}
    get = k.get
    # A contribution or a distribution has no other half to match: typed is its only route.
    if kind == "move" and get("move") in ("employee", "employer", "distribution"):
        return get("route") == "pair"
    # Foreign tax is never sold; it is cash.
    if kind == "income" and get("income") == "foreign-tax":
        return get("sold") == "sold"
    return False


AXES = Axes(_AXES, _impossible)
SEEDS = range(4)


@dataclass
class Move:
    axes: dict
    cents: int
    day: dt.date


@dataclass
class Hsa:
    axes: dict
    owner_cents: int
    employer_cents: int


@dataclass
class IncomeR:
    axes: dict
    quantity: D  # a reward's coins
    price: D  # their day's price
    cents: int  # foreign tax
    day: dt.date


@dataclass
class MoveIn:
    axes: dict
    symbol: str
    bought: dt.date
    sold: dt.date
    basis_cents: int
    proceeds_cents: int


@dataclass
class World:
    seed: int
    age: str
    moves: list[Move] = field(default_factory=list)
    hsas: list[Hsa] = field(default_factory=list)
    incomes: list[IncomeR] = field(default_factory=list)
    move_ins: list[MoveIn] = field(default_factory=list)

    @property
    def born(self) -> int:
        return BORN[self.age]

    def records(self) -> dict[str, list[dict]]:
        base = {"age": self.age}
        return {
            "move": [{**base, **m.axes} for m in self.moves],
            "hsa": [{**base, **h.axes} for h in self.hsas],
            "income": [{**base, **i.axes} for i in self.incomes],
            "move-in": [{**base, **m.axes} for m in self.move_ins],
        }


def world(seed: int) -> World:
    rnd = random.Random(seed)
    w = World(seed, AGES[seed % 2])
    for axes in decks(rnd, {"move": MOVES, "route": ROUTES}, 8):
        if axes["move"] in ("employee", "employer", "distribution"):
            axes["route"] = "typed"
        w.moves.append(Move(axes, rnd.randint(50, 300) * 1000,
                            dt.date(YEAR, rnd.randint(2, 11), rnd.randint(1, 25))))  # fmt: skip
    for axes in decks(rnd, {"coverage": COVERAGES, "employer": EMPLOYER}, 6):
        employer = rnd.randint(10, 30) * 100 if axes["employer"] == "some" else 0
        w.hsas.append(Hsa(axes, rnd.randint(10, 40) * 100, employer))
    for axes in decks(rnd, {"income": INCOMES, "how": HOW, "sold": SOLD}, 4):
        if axes["income"] == "foreign-tax":
            axes["sold"] = "kept"
        w.incomes.append(IncomeR(axes, D(rnd.randint(1, 50)) / 1000, D(rnd.randint(1500, 3500)),
                                 rnd.randint(500, 9000),
                                 dt.date(YEAR, rnd.randint(1, 9), rnd.randint(1, 25))))  # fmt: skip
    for k, axes in enumerate(decks(rnd, {"how": MOVE_INS, "crossing": CROSSING}, 4)):
        sold = dt.date(YEAR, 6, 15)
        bought = (
            sold.replace(year=YEAR - 2)
            if axes["crossing"] == "after-a-year"
            else dt.date(YEAR - 1, 9, 1)
        )
        basis, proceeds = rnd.randint(50, 200) * 100, rnd.randint(50, 300) * 100
        w.move_ins.append(MoveIn(axes, f"MV{seed}{chr(65 + k)}", bought, sold, basis, proceeds))
    return w


# ---------- what the panels must say: the reference ----------


def _money(cents: int) -> D:
    return (D(cents) / 100).quantize(D("0.01"))


def accounts_of_move(m: Move, k: int) -> tuple[str | None, str]:
    """The accounts a move runs between: (from, into), from None for a contribution typed in,
    into the IRA a distribution leaves."""
    kind = m.axes["move"]
    if kind == "employee":
        return None, f"IRA {k}"
    if kind == "employer":
        return None, f"401(k) {k}"
    if kind == "rollover-ira":
        return f"Old IRA {k}", f"IRA {k}"
    if kind == "rollover-401k":
        return f"401(k) {k}", f"IRA {k}"
    if kind == "conversion":
        return f"IRA {k}", f"Roth IRA {k}"
    return f"IRA {k}", f"IRA {k}"  # distribution: out of the IRA


TYPES = {"IRA": "ira", "Old IRA": "ira", "Roth IRA": "roth-ira", "401(k)": "401k"}


def type_of(name: str) -> str:
    return TYPES[name.rsplit(" ", 1)[0]]


def contributions(w: World) -> dict[str, D]:
    """What each account counts against its limit: an owner's own money, and an HSA's
    employer's too; never a rollover or a conversion (S8.6)."""
    out: dict[str, D] = {}
    for k, m in enumerate(w.moves):
        if m.axes["move"] == "employee":
            out[f"IRA {k}"] = out.get(f"IRA {k}", D(0)) + _money(m.cents)
    for k, h in enumerate(w.hsas):
        out[f"HSA {k}"] = _money(h.owner_cents + h.employer_cents)
    return out


def hsa_limit(w: World, h: Hsa) -> D:
    base = D(4400) if h.axes["coverage"] == "self" else D(8750)
    return base + (D(1000) if YEAR - w.born >= 55 else D(0))


def movements(w: World, kind: str) -> list[tuple[str, str, D]]:
    """The conversions or rollovers listed, (from, to, amount); one typed in names its source
    as another account."""
    out = []
    for k, m in enumerate(w.moves):
        what = m.axes["move"]
        listed = "conversion" if what == "conversion" else (
            "rollover" if what.startswith("rollover") else None)  # fmt: skip
        if listed != kind:
            continue
        frm, to = accounts_of_move(m, k)
        out.append(("another account" if m.axes["route"] == "typed" else frm, to,
                    _money(m.cents)))  # fmt: skip
    return sorted(out)


def distributions(w: World) -> list[tuple[str, D]]:
    out: dict[str, D] = {}
    for k, m in enumerate(w.moves):
        if m.axes["move"] == "distribution":
            out[f"IRA {k}"] = out.get(f"IRA {k}", D(0)) + _money(m.cents)
    return sorted(out.items())


def foreign_tax(w: World) -> list[tuple[str, D]]:
    """By payer: each income record's fund at its own broker."""
    return sorted((f"Broker {k}", _money(i.cents)) for k, i in enumerate(w.incomes)
                  if i.axes["income"] == "foreign-tax")  # fmt: skip


def crypto_income(w: World) -> list[tuple[str, D]]:
    return sorted((f"Exchange {k}", (i.quantity * i.price).quantize(D("0.01")))
                  for k, i in enumerate(w.incomes) if i.axes["income"] == "reward")  # fmt: skip


def long_term(acquired: dt.date, sold: dt.date) -> bool:
    try:
        anniversary = acquired.replace(year=acquired.year + 1)
    except ValueError:
        anniversary = acquired.replace(year=acquired.year + 1, day=28)
    return sold > anniversary


def rows_8949(w: World) -> list[tuple[str, str, D, bool]]:
    """Each sale of shares moved in: its day bought, basis and term (S2.2): the day bought
    went with the shares, whatever route they came by. A reward sold: its basis is its value
    when received (S8.5)."""
    out = []
    for m in w.move_ins:
        out.append((m.symbol, m.bought.isoformat(), _money(m.basis_cents),
                    long_term(m.bought, m.sold)))  # fmt: skip
    for k, i in enumerate(w.incomes):
        if i.axes["income"] == "reward" and i.axes["sold"] == "sold":
            out.append((f"RW{k}", i.day.isoformat(), (i.quantity * i.price).quantize(D("0.01")),
                        long_term(i.day, TODAY)))  # fmt: skip
    return sorted(out)


# ---------- bugs a world must catch (`test_worlds`) ----------


def _every_deposit_a_contribution(s, t, account):
    """CR3-37 put back: money into a retirement account is a contribution, however it came."""
    if t.instrumentId or not t.amount:
        return None
    return "employee" if t.amount > 0 else "distribution"


def _bitcoin_pairs_alone(s, owner_id):
    """CR3-73 put back: only bitcoin moved between accounts is offered as a pair; shares
    arrive as bought the day they did, missing their basis."""
    return 0


PLANTS = [
    (
        Plant(
            "every deposit a contribution",
            "moolakata.taxes.retirement:classify",
            _every_deposit_a_contribution,
            "CR3-37",
        ),
        (0,),
    ),
    (
        Plant(
            "shares never paired",
            "moolakata.bitcoin.transfers:propose",
            _bitcoin_pairs_alone,
            "CR3-73",
        ),
        (0,),
    ),
]
