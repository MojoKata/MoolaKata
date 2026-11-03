"""Generated option worlds (`worlds.options`), made through the API and priced through the
real refresh (requirements S3.5.5, S3.5.6, S3.6, S4.4, S4.10).

For every option, each in an account of its own:

1. Grouped or not, its capital at risk is its shape's row: the account's, or its strategy's.
2. Its underlying is among what the refresh prices from the day it was opened, held or not.
3. The day after expiry, it is applied as expired only on a stored close out of the money or at
   the strike; with no close that day, with only the owner's typed price or only another user's
   trade, it waits for the user.
"""

import datetime as dt
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import create, option_trade, saved
from test_accounts import new_account
from worlds import options as ow

from moolakata import clock, ids
from moolakata.prices import TickerSource, register
from moolakata.prices import refresh as pricing
from moolakata.store.entities.accounts import Instrument
from moolakata.store.entities.prices import PriceSource

# What the world's price source answers: symbol -> {day: close}.
ANSWERS: dict[str, dict[dt.date, Decimal]] = {}


@register
class WorldCloses(TickerSource):
    name = "world-test"
    label = "The option world's"
    classes = frozenset({"equity"})

    def history(self, ref, start, end):
        return sorted((d, v) for d, v in ANSWERS.get(ref.symbol, {}).items() if start <= d <= end)


def _at(day: dt.date):
    clock.fix(dt.datetime(day.year, day.month, day.day, 23, 0, tzinfo=dt.UTC))


def test_the_worlds_meet_every_pair_of_data_shapes():
    worlds = [ow.world(seed) for seed in ow.SEEDS]
    assert not ow.AXES.missing(worlds), ow.AXES.missing(worlds)
    assert not ow.AXES.impossible_reached(worlds)


class Made:
    def __init__(self, server, w: ow.World):
        self.server, self.w = server, w
        _at(ow.BEFORE)
        for u in ("alice", "bob"):
            make_user(server, u)
        self.c = {u: sign_in(server, u) for u in ("alice", "bob")}
        alice = self.c["alice"]
        with server.db.tx(unscoped="test") as s:
            s.add(PriceSource(id=ids.new_id("Src"), name="world-test", enabled=True,
                              preference='{"equity": 1}'))  # fmt: skip
        ANSWERS.clear()
        self.accounts, self.instruments = {}, {}
        self.bob_account = new_account(self.c["bob"], name="Bob's", type="brokerage",
                                       mask="8800")  # fmt: skip
        for k, o in enumerate(w.options):
            a = new_account(alice, name=f"Options {k}", type="brokerage", mask=f"{8000 + k}")
            self.accounts[o.symbol] = a["id"]
            if o.shares == "held":
                q = 100 * o.contracts
                r = create(alice, "Txn", accountId=a["id"], date="2026-09-01", kind="buy",
                           symbol=o.symbol, quantity=str(q), price="100",
                           amount=f"-{q * 100}.00")  # fmt: skip
                assert r.status_code == 200, r.text
            action = "buy-to-open" if o.side == "long" else "sell-to-open"
            r = option_trade(alice, a["id"], ow.OPENED.isoformat(), action, o.symbol, o.right,
                             ow.STRIKE, ow.EXPIRY.isoformat(), o.contracts, o.premium,
                             "0")  # fmt: skip
            assert r.status_code == 200, r.text
            with server.db.read(unscoped="test") as s:
                self.instruments[o.symbol] = {
                    i.instrumentClass: i.id
                    for i in s.query(Instrument).filter(Instrument.symbol.like(f"{o.symbol}%"))
                }
            if o.grouped == "grouped":
                legs = [{"instrumentId": self.instruments[o.symbol]["option"]}]
                if o.shares == "held" and o.right == "call" and o.side == "short":
                    legs.append({"instrumentId": self.instruments[o.symbol]["equity"],
                                 "quantity": str(100 * o.contracts)})  # fmt: skip
                self.strategy = saved(create(alice, "Strat", accountId=a["id"], legs=legs))
                o.axes = {**o.axes, "strategy": self.strategy["id"]}
            if o.adjusted != "no":
                r = alice.post("/ui/api/options/adjust", json={
                    "date": ow.ADJUSTED_ON.isoformat(),
                    "contracts": [{"instrumentId": self.instruments[o.symbol]["option"],
                                   "root": o.root, "strike": str(ow.STRIKE),
                                   "deliverable": [{"symbol": o.symbol, "shares": o.adjusted}]}],
                })  # fmt: skip
                assert r.status_code == 200, r.text
            # How the expiry day's price is known.
            if o.source == "answers":
                ANSWERS[o.symbol] = {ow.OPENED: Decimal(100)}
                if o.expiry_close is not None:
                    ANSWERS[o.symbol][ow.EXPIRY] = o.expiry_close
                else:  # no close that day: the day before's only
                    ANSWERS[o.symbol][ow.EXPIRY - dt.timedelta(days=1)] = o.other_price

    def on_the_day(self) -> None:
        """What the expiry day brings without a source: Alice's typed price, or Bob's trade. Days
        later, each signs in again."""
        self.c = {u: sign_in(self.server, u) for u in ("alice", "bob")}
        alice = self.c["alice"]
        for o in self.w.options:
            if o.case == "typed-only":
                r = create(alice, "TyPrc", instrumentId=self._underlying(o),
                           date=ow.EXPIRY.isoformat(), close=str(o.other_price))  # fmt: skip
                assert r.status_code == 200, r.text
            elif o.case == "other-trade":
                p = o.other_price
                r = create(self.c["bob"], "Txn", accountId=self.bob_account["id"],
                           date=ow.EXPIRY.isoformat(), kind="buy", symbol=o.symbol, quantity="1",
                           price=str(p), amount=f"-{p}")  # fmt: skip
                assert r.status_code == 200, r.text

    def _underlying(self, o) -> str:
        with self.server.db.read(unscoped="test") as s:
            return s.query(Instrument).filter_by(symbol=o.symbol, instrumentClass="equity").one().id


@pytest.fixture(params=list(ow.SEEDS), ids=lambda s: f"world{s}")
def made(request, server):
    was = _install()
    try:
        yield Made(server, ow.world(request.param))
    finally:
        _restore(was)
        clock.fix(None)


def _install():
    from moolakata import valuation

    was = (list(valuation._closes), list(valuation._history))
    pricing.install()
    return was


def _restore(was):
    from moolakata import valuation

    valuation._closes[:], valuation._history[:] = was


def test_a_world(made):
    check(made)


def check_world(server, seed: int) -> None:
    was = _install()
    try:
        check(Made(server, ow.world(seed)))
    finally:
        _restore(was)
        clock.fix(None)


def check(made) -> None:
    _a_leg_risks_what_its_shape_does(made)
    _the_underlying_is_priced(made)
    _an_expiry_waits_for_a_close(made)


def _d(x):
    return None if x is None else Decimal(str(x))


def _a_leg_risks_what_its_shape_does(made):
    alice, wrong = made.c["alice"], []
    for o in made.w.options:
        acct = alice.get(f"/ui/api/accounts/{made.accounts[o.symbol]}").json()
        got = None if acct["capitalAtRiskUnlimited"] else _d(acct["capitalAtRisk"])
        if got != o.risk():
            wrong.append(f"{o.symbol} {o.axes}: account {got}, want {o.risk()}")
        if o.grouped == "grouped":
            [st] = [x for x in alice.get("/ui/api/positions/strategies").json()["strategies"]
                    if x["id"] == o.axes["strategy"]]  # fmt: skip
            if _d(st["capitalAtRiskNow"]) != o.risk():
                wrong.append(f"{o.symbol} {o.axes}: grouped {st['capitalAtRiskNow']}")
    assert not wrong, "\n".join(wrong)


def _the_underlying_is_priced(made):
    with made.server.db.read(unscoped="test") as s:
        got = {i.symbol: day for i, day in pricing.priced(s, benchmarks=False)}
    missing = [o.symbol for o in made.w.options if got.get(o.symbol) != ow.OPENED.replace(day=1)
               and got.get(o.symbol) is None]  # fmt: skip
    assert not missing, f"not priced: {missing}"


def _an_expiry_waits_for_a_close(made):
    from moolakata import options

    _at(ow.AFTER)
    made.on_the_day()
    pricing.refresh(made.server)
    with made.server.db.tx(unscoped="test") as s:
        options.expire_due(s, ow.AFTER)
    alice, wrong = made.c["alice"], []
    closed = {r["symbol"]: r for r in alice.get("/ui/api/positions").json()["closed"]}
    for o in made.w.options:
        sym = next(k for k in closed if k.startswith(o.root + " ")) if any(
            k.startswith(o.root + " ") for k in closed) else None  # fmt: skip
        expired = sym is not None and closed[sym]["how"] == "expired"
        if expired != o.expires:
            wrong.append(f"{o.symbol} {o.axes}: expired {expired}, want {o.expires}")
    assert not wrong, "\n".join(wrong)
