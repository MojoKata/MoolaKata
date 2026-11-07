"""Generated account worlds (`worlds.accounts`), made through the API and held to the
reference values and to each other (requirements S1.9, S1.10, S4, S5.1, S5.2, S6.1, S6.4.2.2).

For every world, as its viewer (the owner, or one who sees some of the accounts):

1. Each account's value is the reference's (the owner reads each one).
2. The portfolio's value is the sum over the accounts the viewer sees; its Holdings total is
   that value, its loan and item rows the reference's parts; its series ends on it.
3. A projection built on the portfolio starts from what it grows, and what it leaves out, by
   name and value, is the reference's; the two add up to the portfolio's value.
4. Every loan's payment is the schedule's next row.

A decoy household (Mallory, a stranger) holds the same symbols, with trades, statement values
and typed prices of her own on the same days: a figure that reads them differs from the
reference.
"""

import contextlib
import datetime as dt
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import create, make, option_trade, saved, share, terms
from test_accounts import add, new_account
from worlds import accounts as aw

from moolakata import clock, ids
from moolakata.store.entities.accounts import Holding, Instrument
from moolakata.store.entities.prices import Price

T0 = dt.datetime(aw.TODAY.year, aw.TODAY.month, aw.TODAY.day, 15, 0, tzinfo=dt.UTC)


def test_the_worlds_meet_every_pair_of_data_shapes():
    worlds = [aw.world(seed) for seed in aw.SEEDS]
    assert not aw.AXES.missing(worlds), aw.AXES.missing(worlds)
    assert not aw.AXES.impossible_reached(worlds)


# ---------- making a world ----------


def _ok(r):
    assert r.status_code == 200, r.text
    return r


class Made:
    def __init__(self, server, w: aw.World):
        self.server, self.w = server, w
        clock.fix(T0)
        for u in ("alice", "bob", "mallory"):
            make_user(server, u)
        self.c = {u: sign_in(server, u) for u in ("alice", "bob", "mallory")}
        self.uid = {u: c.get("/ui/api/session").json()["user"]["id"] for u, c in self.c.items()}
        alice = self.c["alice"]
        self.ids: dict[str, str] = {}
        for i, a in enumerate(w.accounts):
            acct = new_account(alice, name=a.name, type=a.type, institution="Example",
                               mask=f"{3000 + i}")  # fmt: skip
            self.ids[a.name] = acct["id"]
            if a.loan:
                saved(terms(alice, acct["id"], principal=str(a.loan.principal),
                            startDate=a.loan.start.isoformat(), termMonths=a.loan.months,
                            rate=str(a.loan.rate),
                            method="daily" if a.loan.method == "daily" else "amortized",
                            drawMonths=a.loan.draw_months or None,
                            resets=[{"date": d.isoformat(), "rate": str(r)}
                                    for d, r in a.loan.resets],
                            recasts=[{"date": d.isoformat(), "fee": str(f)}
                                     for d, f in a.loan.recasts]))  # fmt: skip
            for t in a.txns:
                self._txn(alice, acct["id"], t)
            for it in a.items:
                self._item(alice, acct["id"], it)
        self._closes()
        self._decoy()
        self.portfolio = _ok(make(alice, "Portf", name="World",
                                  accountIds=list(self.ids.values()))).json()["id"]  # fmt: skip
        if w.viewer == "viewer":
            bob = self.uid["bob"]
            _ok(share(alice, "portfolio", self.portfolio, users={bob: "read"}))
            for a in w.seen():
                _ok(share(alice, "account", self.ids[a.name], users={bob: "read"}))

    @property
    def viewer(self):
        return self.c["alice" if self.w.viewer == "owner" else "bob"]

    def _txn(self, c, account_id: str, t: aw.Txn) -> None:
        day = t.day.isoformat()
        if t.option:
            right, strike, expiry, _mult = t.option
            _ok(option_trade(c, account_id, day, t.kind, t.symbol, right, strike,
                             expiry.isoformat(), t.quantity, t.price))  # fmt: skip
            return
        kw = {"kind": t.kind}
        if t.symbol:
            kw |= {"symbol": t.symbol, "quantity": str(t.quantity), "price": str(t.price)}
        add(c, account_id, f"{t.amount:.2f}", day, **kw)

    def _item(self, c, account_id: str, it: aw.ItemD) -> None:
        body = {"accountId": account_id, "name": it.name, "acquiredOn": it.acquired.isoformat(),
                "costBasis": str(it.cost), "valuation": it.valuation}  # fmt: skip
        if it.metal:
            body |= {"metal": it.metal, "unitWeight": str(it.ounces), "weightUnit": "ozt",
                     "purity": str(aw.FINE)}  # fmt: skip
        if it.rate is not None:
            body["depreciationRate"] = str(it.rate)
        if it.sold:
            body |= {"soldOn": it.sold.isoformat(), "proceeds": str(it.cost)}
        made = _ok(make(c, "Item", **body)).json()
        for d, v in it.valuations:
            _ok(make(c, "Valtn", itemId=made["id"], date=d.isoformat(), value=str(v),
                     source="estimate"))  # fmt: skip

    def _closes(self) -> None:
        from moolakata import assets

        with self.server.db.tx(unscoped="test") as s:
            by_symbol = self._instruments(s)
            for sym, days in self.w.closes.items():
                inst = by_symbol.get(sym)
                assert inst is not None, f"{sym}: no instrument made"
                for d, close in days.items():
                    s.add(Price(id=ids.new_id("Price"), instrumentId=inst.id, date=d, close=close,
                                source="test", fetchedAt=clock.now()))  # fmt: skip
            for metal, spot in self.w.spot.items():
                inst = assets.metal_instrument(s, metal)
                s.add(Price(id=ids.new_id("Price"), instrumentId=inst.id,
                            date=aw.TODAY - dt.timedelta(days=1), close=spot, source="test",
                            fetchedAt=clock.now()))  # fmt: skip

    def _instruments(self, s) -> dict[str, Instrument]:
        """The instruments Alice's trades are in, by symbol."""
        from moolakata.store.entities.accounts import Transaction

        rows = s.query(Instrument).join(Transaction, Transaction.instrumentId == Instrument.id)
        return {i.symbol: i for i in rows.filter(Transaction.accountId.in_(self.ids.values()))}

    def _decoy(self) -> None:
        """Mallory, a stranger: the world's symbols held at other prices on the same days, a
        statement value for each and a typed price, none of which may value Alice's."""
        m = self.c["mallory"]
        held = sorted({t.symbol for a in self.w.accounts for t in a.txns
                       if t.symbol and not t.option})  # fmt: skip
        days = sorted({t.day for a in self.w.accounts for t in a.txns} | {aw.TODAY})
        mine = {}
        for kind in ("brokerage", "crypto-exchange"):
            acct = new_account(m, name=f"Decoy {kind}", type=kind, institution="Elsewhere",
                               mask="9999")  # fmt: skip
            add(m, acct["id"], "900000.00", "2021-01-04", kind="deposit")
            mine[kind] = acct["id"]
        for k, sym in enumerate(held):
            where = mine["crypto-exchange" if sym in aw.COINS else "brokerage"]
            for d in days[-3:]:
                price = Decimal(7 + k)  # nothing like any world's price
                add(m, where, f"-{price:.2f}", d.isoformat(), kind="buy", symbol=sym,
                    quantity="1", price=str(price))  # fmt: skip
        with self.server.db.tx(unscoped="test") as s:
            insts = self._instruments(s)
            for sym in held:
                where = mine["crypto-exchange" if sym in aw.COINS else "brokerage"]
                s.add(Holding(id=ids.new_id("Hold"), accountId=where,
                              instrumentId=insts[sym].id, asOf=aw.TODAY, quantity=Decimal(1),
                              marketValue=Decimal("3.33")))  # fmt: skip
        with self.server.db.read(unscoped="test") as s:
            insts = {sym: i.id for sym, i in self._instruments(s).items()}
        for sym in held:
            create(m, "TyPrc", instrumentId=insts[sym], date=aw.TODAY.isoformat(), close="1.11")


@pytest.fixture(params=list(aw.SEEDS), ids=lambda s: f"world{s}")
def made(request, server):
    w = aw.world(request.param)
    with _closes_installed():
        try:
            yield Made(server, w)
        finally:
            clock.fix(None)


@contextlib.contextmanager
def _closes_installed():
    """Stored closes value holdings while a world runs, as on the running server; put back
    as they were after."""
    from moolakata import valuation
    from moolakata.prices import refresh as pricing

    was = (list(valuation._closes), list(valuation._history))
    pricing.install()
    try:
        yield
    finally:
        valuation._closes[:], valuation._history[:] = was


# ---------- the checks ----------


def _d(x) -> Decimal:
    return Decimal(str(x)) if x is not None else Decimal(0)


def test_a_world(made):
    check(made)


def check_world(server, seed: int) -> None:
    """Make the world of `seed` and check it; run under each of `PLANTS` by `test_worlds`."""
    with _closes_installed():
        try:
            check(Made(server, aw.world(seed)))
        finally:
            clock.fix(None)


def check(made) -> None:
    _each_account_is_the_references(made)
    _the_portfolio_adds_up(made)
    _contributions_are_the_money_moved(made)
    _a_projection_leaves_out_what_it_doesnt_grow(made)
    _a_loans_payment_is_its_schedules_next_row(made)


def _each_account_is_the_references(made):
    alice, w = made.c["alice"], made.w
    wrong = []
    for a in w.accounts:
        got = _d(alice.get(f"/ui/api/accounts/{made.ids[a.name]}").json()["balance"])
        want = aw.value(w, a)
        if got != want:
            wrong.append(f"{a.name} {a.axes}: got {got}, want {want}")
            if a.kind in aw.INVESTING:
                h = alice.get(f"/ui/api/accounts/{made.ids[a.name]}/holdings").json()
                app = [(x["symbol"], x["quantity"], x["price"], x["priceSource"], x["value"])
                       for x in h["holdings"]]  # fmt: skip
                wrong.append(f"  app: cash {h['cash']} {app}")
                wrong.append(f"  ref: {[(p.kind, p.name, p.value) for p in aw.parts(w, a)]}")
    assert not wrong, "\n".join(wrong)


def _the_portfolio_adds_up(made):
    c, w = made.viewer, made.w
    seen = w.seen()
    want = sum((aw.value(w, a) for a in seen), Decimal(0))
    row = c.get(f"/ui/api/portfolios/{made.portfolio}").json()
    h = c.get(f"/ui/api/portfolios/{made.portfolio}/holdings").json()
    series = c.get(f"/ui/api/portfolios/{made.portfolio}/series", params={"range": "1M"}).json()
    got = {"value": _d(row["value"]), "holdings": _d(h["total"]), "series": _d(series["end"])}
    assert got == dict.fromkeys(got, want), (got, want)
    others = sorted((o["kind"], o["name"], _d(o["value"])) for o in h["others"])
    ref = sorted((p.kind, p.name, p.value) for a in seen for p in aw.parts(w, a)
                 if p.kind in ("loan", "item"))  # fmt: skip
    assert others == ref


def _contributions_are_the_money_moved(made):
    """What the portfolio's chart counts contributed over its last month is the money that
    came in or left from outside, valued as the reference values it (CR3-28)."""
    c, w = made.viewer, made.w
    series = c.get(f"/ui/api/portfolios/{made.portfolio}/series", params={"range": "1M"}).json()
    first = aw.TODAY - dt.timedelta(days=31)
    want = sum((aw.flows(w, a, first, aw.TODAY) for a in w.seen()), Decimal(0))
    assert _d(series["contributed"]) == want, (series["contributed"], want)


def _a_projection_leaves_out_what_it_doesnt_grow(made):
    alice, w = made.c["alice"], made.w
    r = _ok(make(alice, "Prjct", name="Grow", goal="savings",
                 builtOn={"kind": "portfolio", "id": made.portfolio},
                 inputs={"target": 50000, "targetDate": "2030-01-01"}))  # fmt: skip
    res = alice.get(f"/ui/api/projections/{r.json()['id']}").json()["result"]
    got = sorted((x["name"], _d(x["value"])) for x in res["leftOut"])
    assert got == aw.left_out(w, w.accounts)
    total = sum((aw.value(w, a) for a in w.accounts), Decimal(0))
    assert _d(res["start"]) + sum((v for _, v in got), Decimal(0)) == total


def _a_loans_payment_is_its_schedules_next_row(made):
    alice = made.c["alice"]
    for a in made.w.accounts:
        if a.loan is None:
            continue
        v = alice.get(f"/ui/api/accounts/{made.ids[a.name]}/loan").json()
        nxt = next((r for r in v["rows"] if not r["past"]), None)
        if nxt is None:
            assert _d(v["payment"]) == 0 == _d(v["total"]), (a.name, v["payment"])
            continue
        assert (_d(v["payment"]), _d(v["total"])) == (
            _d(nxt["principal"]) + _d(nxt["interest"]),
            _d(nxt["payment"]),
        ), a.name
