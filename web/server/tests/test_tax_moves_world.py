"""Generated worlds of money moved for taxes (`worlds.tax_moves`), made through the API and held
to the reference (requirements S2.2, S8.1, S8.5, S8.6; the values, taxes and options walk,
10.2): the 2026 book's Retirement panel (what counts against each limit, the conversions, the
rollovers, the distributions, an HSA's limit), its Income panel (foreign tax by payer, crypto
income by account) and Form 8949's rows of shares moved in and coins received.

A decoy stranger, Mallory, holds the same kinds of records; none of them may reach Alice's
book.
"""

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import make_user, sign_in
from corpus import import_file
from edits import change, edit, make, saved
from test_accounts import add, new_account
from worlds import tax_moves as tm

from moolakata import clock

T0 = dt.datetime(tm.TODAY.year, tm.TODAY.month, tm.TODAY.day, 15, 0, tzinfo=dt.UTC)


def test_the_worlds_meet_every_pair_of_data_shapes():
    worlds = [tm.world(seed) for seed in tm.SEEDS]
    assert not tm.AXES.missing(worlds), tm.AXES.missing(worlds)
    assert not tm.AXES.impossible_reached(worlds)


def _ok(r):
    assert r.status_code == 200, r.text
    return r


def _csv(name: str, text: str, mapping: dict):
    return SimpleNamespace(data=lambda: text.encode(), upload_name=lambda: name, mapping=mapping)


class Made:
    def __init__(self, server, w: tm.World):
        self.w, self.ids = w, {}
        clock.fix(T0)
        make_user(server, "alice", born=w.born)
        make_user(server, "mallory", born=1966)
        self.c = sign_in(server, "alice")
        me = self.c.get("/ui/api/session").json()["user"]["id"]
        for k, m in enumerate(w.moves):
            self._move(k, m)
        for k, h in enumerate(w.hsas):
            self._hsa(k, h)
        for k, i in enumerate(w.incomes):
            self._income(k, i)
        for k, m in enumerate(w.move_ins):
            self._move_in(k, m)
        self._decoy(sign_in(server, "mallory"))
        self.book = _ok(make(self.c, "TaxBk", year=tm.YEAR, filers=[me])).json()["id"]

    def account(self, name: str, kind: str, **kw) -> str:
        if name not in self.ids:
            self.ids[name] = new_account(self.c, name=name, type=kind, mask=None, **kw)["id"]
        return self.ids[name]

    def _move(self, k: int, m: tm.Move) -> None:
        frm, to = tm.accounts_of_move(m, k)
        kind, day, amount = m.axes["move"], m.day.isoformat(), tm._money(m.cents)
        if kind == "employee":
            add(self.c, self.account(to, tm.type_of(to)), f"{amount}", day, kind="deposit")
        elif kind == "employer":
            add(self.c, self.account(to, tm.type_of(to)), f"{amount}", day, kind="deposit",
                contributionSource="employer")  # fmt: skip
        elif kind == "distribution":
            a = self.account(to, tm.type_of(to))
            add(
                self.c, a, f"{amount * 2}", "2026-01-05", kind="deposit", contributionYear=2025
            )  # last year's money, so it can come out
            add(self.c, a, f"-{amount}", day, kind="withdrawal")
        elif m.axes["route"] == "pair":
            src = self.account(frm, tm.type_of(frm))
            add(self.c, src, f"{amount}", "2026-01-05", kind="deposit", contributionYear=2025)
            out = add(self.c, src, f"-{amount}", day, kind="transfer", payee="Moved")
            back = add(self.c, self.account(to, tm.type_of(to)), f"{amount}", day,
                       kind="transfer", payee="Moved")  # fmt: skip
            assert back["transferId"] == out["id"], (k, m.axes)
        else:  # typed: the money arrives from an account MoolaKata doesn't hold
            source = "conversion" if kind == "conversion" else "rollover"
            add(self.c, self.account(to, tm.type_of(to)), f"{amount}", day, kind="deposit",
                contributionSource=source)  # fmt: skip

    def _hsa(self, k: int, h: tm.Hsa) -> None:
        a = self.account(f"HSA {k}", "hsa")
        if h.axes["coverage"] != "unset":
            _ok(edit(self.c, "Acct", f"/ui/api/accounts/{a}", hsaCoverage=h.axes["coverage"]))
        add(self.c, a, f"{tm._money(h.owner_cents)}", "2026-03-01", kind="deposit")
        if h.employer_cents:
            add(self.c, a, f"{tm._money(h.employer_cents)}", "2026-04-01", kind="deposit",
                contributionSource="employer")  # fmt: skip

    def _income(self, k: int, i: tm.IncomeR) -> None:
        day = i.day.isoformat()
        if i.axes["income"] == "foreign-tax":
            a = self.account(f"Broker {k}", "brokerage", institution=f"Broker {k}")
            if i.axes["how"] == "typed":
                add(self.c, a, f"-{tm._money(i.cents)}", day, kind="foreign-tax", symbol=f"FT{k}")
            else:
                d = i.day.strftime("%m/%d/%Y")
                text = ("Run Date,Action,Symbol,Description,Type,Quantity,Price ($),"
                        "Commission ($),Fees ($),Accrued Interest ($),Amount ($),"
                        f"Settlement Date\n{d},FOREIGN TAX PAID FUND (FT{k}) (Cash), FT{k},"
                        f"FUND,Cash,0.000,,,,,-{tm._money(i.cents)},\n")  # fmt: skip
                import_file(self.c, a, _csv("history.csv", text, {"amount": "Amount ($)"}))
            return
        a = self.account(f"Exchange {k}", "crypto-exchange", institution="Coinbase")
        add(self.c, a, "1000.00", "2026-01-02", kind="deposit")
        if i.axes["how"] == "typed":
            add(self.c, a, "0.00", day, kind="reward", symbol=f"RW{k}", quantity=str(i.quantity),
                price=str(i.price))  # fmt: skip
        else:
            text = ("Timestamp,Transaction Type,Asset,Quantity Transacted,Spot Price Currency,"
                    "Spot Price at Transaction,Subtotal,Total (inclusive of fees and/or spread),"
                    f"Fees and/or Spread,Notes\n{day}T04:00:00Z,Staking Income,RW{k},"
                    f"{i.quantity},USD,{i.price},0,0,0,Staking\n")  # fmt: skip
            import_file(self.c, a, _csv("coinbase.csv", text, {"payee": "Notes"}))
        if i.axes["sold"] == "sold":
            add(self.c, a, "10.00", tm.TODAY.isoformat(), kind="sell", symbol=f"RW{k}",
                quantity=str(i.quantity), price="1")  # fmt: skip

    def _move_in(self, k: int, m: tm.MoveIn) -> None:
        how, qty = m.axes["how"], "10"
        basis = f"{tm._money(m.basis_cents)}"
        new = self.account(f"New broker {k}", "brokerage")
        if how == "paired":
            old = self.account(f"Old broker {k}", "brokerage")
            add(self.c, old, basis, m.bought.isoformat(), kind="deposit")
            add(self.c, old, f"-{basis}", m.bought.isoformat(), kind="buy", symbol=m.symbol,
                quantity=qty, price=f"{tm._money(m.basis_cents) / 10}")  # fmt: skip
            add(self.c, old, "0.00", "2026-01-09", kind="transfer-out", symbol=m.symbol,
                quantity=qty)  # fmt: skip
            add(self.c, new, "0.00", "2026-01-10", kind="transfer-in", symbol=m.symbol,
                quantity=qty)  # fmt: skip
            pairs = [p for p in self.c.get("/ui/api/transfers/bitcoin").json()["items"]
                     if p["symbol"] == m.symbol]  # fmt: skip
            assert len(pairs) == 1, pairs
            r = self.c.post(f"/ui/api/transfers/bitcoin/{pairs[0]['id']}",
                            json={"confirm": True},
                            headers={"If-Match": f'"{pairs[0]["version"]}"'})  # fmt: skip
            assert r.status_code == 200, r.text
        else:
            lots = [{"acquiredOn": m.bought.isoformat(), "quantity": qty, "costBasis": basis}]
            r = make(self.c, "Txn", accountId=new, date="2026-01-10", kind="transfer-in",
                     symbol=m.symbol, quantity=qty, amount="0.00",
                     **({"transferLots": lots} if how == "typed-lots" else {}))  # fmt: skip
            assert r.status_code == 200, r.text
            if how == "filled-later":
                t = self.c.get(f"/ui/api/transactions/{r.json()['id']}").json()
                saved(change(self.c, "Txn", t, transferLots=lots))
        add(self.c, new, f"{tm._money(m.proceeds_cents)}", m.sold.isoformat(), kind="sell",
            symbol=m.symbol, quantity=qty, price=f"{tm._money(m.proceeds_cents) / 10}")  # fmt: skip

    def _decoy(self, m) -> None:
        """Mallory's own money moved, foreign tax and rewards: none may reach Alice's book."""
        ira = new_account(m, name="IRA 0", type="ira", mask=None)["id"]
        roth = new_account(m, name="Roth IRA 0", type="roth-ira", mask=None)["id"]
        add(m, ira, "90000.00", "2026-01-05", kind="deposit")
        out = add(m, ira, "-50000.00", "2026-03-02", kind="transfer")
        back = add(m, roth, "50000.00", "2026-03-02", kind="transfer")
        assert back["transferId"] == out["id"]
        b = new_account(m, name="Broker 0", type="brokerage", institution="Broker 0",
                        mask=None)["id"]  # fmt: skip
        add(m, b, "-999.00", "2026-05-01", kind="foreign-tax", symbol="FT0")


@pytest.fixture(params=list(tm.SEEDS), ids=lambda s: f"world{s}")
def made(request, server):
    try:
        yield Made(server, tm.world(request.param))
    finally:
        clock.fix(None)


def test_a_world(made):
    check(made)


def check_world(server, seed: int) -> None:
    try:
        check(Made(server, tm.world(seed)))
    finally:
        clock.fix(None)


def _d(x):
    return Decimal(str(x))


def check(made) -> None:
    w = made.w
    p = made.c.get(f"/ui/api/tax-books/{made.book}/panels").json()
    r = p["retirement"]
    got = {c["account"]: _d(c["contributed"]) for c in r["contributions"]}
    want = tm.contributions(w)
    wrong = [f"{a}: contributed {got.get(a)}, want {v}" for a, v in want.items()
             if got.get(a) != v]  # fmt: skip
    wrong += [f"{a}: contributed {v}, want none" for a, v in got.items()
              if a not in want and v]  # fmt: skip
    for k, h in enumerate(w.hsas):
        c = next(x for x in r["contributions"] if x["account"] == f"HSA {k}")
        if _d(c["limit"]) != tm.hsa_limit(w, h):
            wrong.append(f"HSA {k} {h.axes}: limit {c['limit']}, want {tm.hsa_limit(w, h)}")
    for kind, key in (("conversion", "conversions"), ("rollover", "rollovers")):
        listed = sorted((x["fromAccount"], x["toAccount"], _d(x["amount"])) for x in r[key])
        if listed != tm.movements(w, kind):
            wrong.append(f"{key}: {listed}, want {tm.movements(w, kind)}")
    dist = sorted((x["label"], _d(x["amount"])) for x in r["distributions"])
    if dist != tm.distributions(w):
        wrong.append(f"distributions: {dist}, want {tm.distributions(w)}")
    inc = p["income"]
    for key, want_ in (("foreignTax", tm.foreign_tax(w)), ("cryptoIncome", tm.crypto_income(w))):
        got_ = sorted((x["label"], _d(x["amount"])) for x in inc[key])
        if got_ != want_:
            wrong.append(f"{key}: {got_}, want {want_}")
    rows = sorted(
        (x["description"].split()[-1], x["acquired"], _d(x["basis"]), x["longTerm"])
        for x in p["rows"]
    )
    if rows != tm.rows_8949(w):
        wrong.append(f"8949: {rows}, want {tm.rows_8949(w)}")
    assert not wrong, "\n".join(wrong)
