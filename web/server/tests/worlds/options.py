"""Generated option worlds (requirements S3.5.5, S3.5.6, S3.6, S4.4, S4.10): one option in an
account of its own, of every shape, grouped or not, and how its expiry day's price is known,
drawn from a seed. `test_option_world` makes each through the API, prices it through the real
refresh from a price source the test answers for, and holds it to three rules: grouped or
not, a leg risks what its shape does; an expiry is applied only on a stored close and only out
of the money; the underlying is priced while the option is open, held or not.

An **option** record's axes: call or put, long or short, whether the account holds the shares
(100 a contract), grouped as a strategy or not, and the expiry case: out of the money, in it,
at the strike, no close that day, only Alice's own typed price that day, or only another
user's trade that day; and whether a price source answers.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass
from decimal import Decimal

from worlds import Axes, Plant, decks

D = Decimal
OPENED = dt.date(2026, 9, 2)
EXPIRY = dt.date(2026, 10, 16)  # a Friday
BEFORE = dt.date(2026, 10, 13)
AFTER = dt.date(2026, 10, 19)
STRIKE = D(100)

RIGHTS = ("call", "put")
SIDES = ("long", "short")
SHARES = ("none", "held")
GROUPED = ("alone", "grouped")
CASES = ("otm", "itm", "at-strike", "no-close", "typed-only", "other-trade")
SOURCES = ("answers", "none")

_AXES = {"option": {"right": RIGHTS, "side": SIDES, "shares": SHARES, "grouped": GROUPED,
                    "case": CASES, "source": SOURCES}}  # fmt: skip
SEEDS = range(6)


def _impossible(kind: str, a: tuple[str, str], b: tuple[str, str]) -> bool:
    k = {a[0]: a[1], b[0]: b[1]}
    get = k.get
    # A close that day, or none, is a source's to answer; a typed price or another's trade
    # alone is the case without one.
    if get("case") in ("otm", "itm", "at-strike", "no-close") and get("source") == "none":
        return True
    return get("case") in ("typed-only", "other-trade") and get("source") == "answers"


AXES = Axes(_AXES, _impossible)


@dataclass
class Option:
    axes: dict
    symbol: str
    contracts: int
    premium: D

    def __getattr__(self, name):
        try:
            return self.__dict__["axes"][name]
        except KeyError:
            raise AttributeError(name) from None

    @property
    def expiry_close(self) -> D | None:
        """The underlying's close on the expiry day, as the source answers it."""
        if self.case not in ("otm", "itm", "at-strike"):
            return None
        itm = {"call": STRIKE + 7, "put": STRIKE - 7}[self.right]
        otm = {"call": STRIKE - 7, "put": STRIKE + 7}[self.right]
        return {"otm": otm, "itm": itm, "at-strike": STRIKE}[self.case]

    @property
    def other_price(self) -> D:
        """The out-of-the-money price a typed price or another user's trade shows that day."""
        return {"call": STRIKE - 9, "put": STRIKE + 9}[self.right]

    @property
    def expires(self) -> bool:
        """Applied automatically the day after: only on a stored close, out of the money or
        at the strike (S3.6)."""
        return self.case in ("otm", "at-strike")

    def risk(self) -> D | None:
        """Its capital at risk, by its shape's row (S3.5.5): None is unlimited."""
        n, credit = D(self.contracts), self.premium * 100 * self.contracts
        if self.side == "long":
            return credit
        if self.right == "put":
            return STRIKE * 100 * n - credit
        if self.shares == "held":
            return D(100) * 100 * n - credit  # the shares at their trade's $100, less it
        return None


@dataclass
class World:
    seed: int
    options: list[Option]

    def records(self) -> dict[str, list[dict]]:
        return {"option": [o.axes for o in self.options]}


def _fit(axes: dict) -> dict:
    axes = dict(axes)
    if axes["case"] in ("otm", "itm", "at-strike", "no-close"):
        axes["source"] = "answers"
    else:
        axes["source"] = "none"
    return axes


def world(seed: int) -> World:
    rnd = random.Random(seed)
    names = [k for k in _AXES["option"] if k != "source"]
    out = []
    for i, axes in enumerate(decks(rnd, {k: _AXES["option"][k] for k in names}, 8)):
        axes = _fit({**axes, "source": "none"})
        out.append(Option(axes, f"OW{seed}{chr(65 + i)}", rnd.randint(1, 3),
                          D(rnd.randint(150, 450)) / 100))  # fmt: skip
    return World(seed, out)


# ---------- bugs an option world must catch (`test_worlds`) ----------


def _any_price_decides(s, c, day):
    """CR3-24 put back: the expiry decided by any price on the day, anyone's."""
    from moolakata.options import per_share
    from moolakata.store.entities.accounts import Account, Transaction

    owner = (
        s.query(Account)
        .join(Transaction, Transaction.accountId == Account.id)
        .filter(Transaction.instrumentId == c.underlyingId)
        .first()
    )
    return per_share(s, c, day, owner.ownerId if owner else "")


def _single_leg_strike_risk(s, ledger, book=None):
    """CR3-6 put back: an option on its own risks the strike on its shares, whatever its
    shape (S3.9.2's figure)."""
    from moolakata.options import contract_of
    from moolakata.options import strategies as strat

    book = book or strat.Book(s, ledger)
    risk, value, held = D(0), D(0), False
    for iid, (qty, basis) in book.open.items():
        oc = contract_of(s, iid)
        if oc is None or not qty:
            continue
        held = True
        risk += basis if qty > 0 else (oc.strike * oc.multiplier * -qty)
    return value, risk, held


PLANTS = [
    (
        Plant(
            "an expiry decided by any price",
            "moolakata.options:market_close",
            _any_price_decides,
            "CR3-24",
        ),
        (0, 1),
    ),
    (
        Plant(
            "a single leg's risk its strike",
            "moolakata.options.strategies:risk_of_account",
            _single_leg_strike_risk,
            "CR3-6",
        ),
        (0,),
    ),
]
