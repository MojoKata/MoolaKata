"""Generated tax worlds (`worlds.tax`), made through the API and held to the reference model
(`worlds.tax_reference`) and to the tax panels' own sums (requirements S2.3, S3.1, S3.8, S8.1, S8.2,
S8.3, S8.14).

For every tax book of every world:

1. Form 8949's rows are the reference model's, row for row: each lot's share of each sale, its
   dates, proceeds, basis, wash-sale adjustment, term and box.
2. Schedule D's boxes and terms are the sums of the rows.
3. The wash sales listed disallow what the rows' W adjustments add back.
4. The 8949 CSV export carries the panel's rows.
"""

import csv
import datetime as dt
import io
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import create, make, option_trade
from worlds import tax as tw
from worlds import tax_reference as ref

from moolakata import clock

T0 = dt.datetime(tw.TODAY.year, tw.TODAY.month, tw.TODAY.day, 15, 0, tzinfo=dt.UTC)


def test_the_worlds_meet_every_pair_of_data_shapes():
    """Every pair of values of two axes of one record that can exist meets in some world, and
    no world holds a pair the rules say can't."""
    worlds = [tw.world(seed) for seed in tw.SEEDS]
    assert not tw.AXES.missing(worlds), {k: v[:10] for k, v in tw.AXES.missing(worlds).items()}
    assert not tw.AXES.impossible_reached(worlds)


def test_the_reference_settles_every_world():
    """The reference model's wash sales settle in every world, and its rows reach every box
    a world can reach."""
    boxes = set()
    for seed in tw.SEEDS:
        w = tw.world(seed)
        h = ref.household(w)
        for year, filers in w.books():
            boxes |= {r.box for r in ref.rows(h, year, filers)}
    # B: short term without a reported basis needs a lot bought before 2011 and sold within a
    # year; J: a coin bought from 2026 held over a year, by 2026's end. Neither can happen.
    assert boxes == set("ADEGHIKL"), sorted(boxes)


# ---------- making a world ----------


def _ok(r):
    assert r.status_code == 200, r.text
    return r


class Made:
    def __init__(self, server, w: tw.World):
        self.w = w
        clock.fix(T0)
        make_user(server, "alice")
        make_user(server, "bob")
        self.c = {"alice": sign_in(server, "alice"), "bob": sign_in(server, "bob")}
        self.uid = {u: c.get("/ui/api/session").json()["user"]["id"] for u, c in self.c.items()}
        if w.married:
            pa = self.c["alice"].get("/ui/api/profile").json()["personId"]
            pb = self.c["bob"].get("/ui/api/profile").json()["personId"]
            r = _ok(make(self.c["alice"], "Rltn", person1Id=pa, person2Id=pb, relation="spouse",
                         fromDate="2009-06-14"))  # fmt: skip
            _ok(self.c["bob"].post(f"/ui/api/relationships/{r.json()['id']}/confirm"))
        self.accounts: dict[str, str] = {}
        for i, (name, (owner, kind)) in enumerate(tw.ACCOUNTS.items()):
            r = make(self.c[owner], "Acct", name=name, type=kind, institution="Example",
                     mask=f"{2000 + i}", lotMethod=w.methods[name])  # fmt: skip
            self.accounts[name] = _ok(r).json()["id"]
        for i, t in enumerate(w.trades):
            self._trade(i, t)
        for inc in w.incomes:
            self._income(inc)
        self.books = {}
        for year, filers in w.books():
            self.books[(year, filers)] = self._book(year, filers)
        if w.left_out:
            alice = next(f for y, f in w.books() if y == 2026 and "alice" in f)
            _ok(create(self.c["alice"], "TxBkA", bookId=self.books[(2026, alice)],
                       accountId=self.accounts["Second"], counted=False))  # fmt: skip

    def _income(self, inc: tw.Income) -> None:
        fields = {"accountId": self.accounts[inc.account], "date": inc.date.isoformat(),
                  "kind": inc.kind, "amount": inc.amount}  # fmt: skip
        if inc.symbol:
            fields["symbol"] = inc.symbol
        if inc.dividend_type:
            fields["dividendType"] = inc.dividend_type
        if inc.kind == "reinvest":
            fields |= {"quantity": "1", "price": inc.amount.lstrip("-")}
        r = make(self.client(inc.account), "Txn", **fields)
        assert r.status_code == 200, (inc, r.text)

    def client(self, account: str):
        return self.c[tw.ACCOUNTS[account][0]]

    def _trade(self, i: int, t: tw.Trade) -> None:
        c = self.client(t.account)
        acct = self.accounts[t.account]
        if t.leg_of is not None:
            return  # made by the assignment or exercise it belongs to
        if t.kind in ("buy-to-open", "sell-to-open", "buy-to-close", "sell-to-close"):
            r = option_trade(c, acct, t.date.isoformat(), t.kind, t.symbol, t.right, t.strike,
                             t.expiry.isoformat(), t.quantity, t.price, t.fees)  # fmt: skip
            assert r.status_code == 200, (i, t, r.text)
            return
        if t.kind in ("expire", "assign", "exercise"):
            held = _ok(c.get(f"/ui/api/accounts/{acct}/holdings")).json()["holdings"]
            inst = next(h["instrumentId"] for h in held if h["symbol"] == t.option)
            how = "expired" if t.kind == "expire" else t.kind
            day = t.expiry if t.kind == "expire" else t.date
            body = {"how": how, "date": day.isoformat(), "contracts": str(t.quantity)}
            r = c.post(f"/ui/api/accounts/{acct}/options/{inst}/settle", json=body)
            assert r.status_code == 201, (i, t, r.text)
            return
        if t.kind in ("split", "merger"):
            # A corporate action, recorded as Positions records it (S2.4).
            held = _ok(c.get(f"/ui/api/accounts/{acct}/holdings")).json()["holdings"]
            inst = next(h["instrumentId"] for h in held if h["symbol"] == t.symbol)
            more = {} if t.kind == "split" else {
                "newSymbol": t.new_symbol, "cashPerShare": _dollars(t.cash_cents),
                "newPrice": t.new_price}  # fmt: skip
            r = create(c, "CorpA", accountId=acct, instrumentId=inst, kind=t.kind,
                       date=t.date.isoformat(), ratio=str(t.ratio), **more)  # fmt: skip
            assert r.status_code == 200, (i, t, r.text)
            return
        fields = {"accountId": self.accounts[t.account], "date": t.date.isoformat(),
                  "amount": t.amount, "kind": t.kind, "symbol": t.symbol,
                  "quantity": str(t.quantity), "price": t.price}  # fmt: skip
        if t.picks:
            lots = self._lots(t.account, t.date)
            fields["picks"] = [
                {"lotId": lots[(t.symbol, self.w.trades[b].date)], "quantity": str(n)}
                for b, n in t.picks
            ]
        r = make(c, "Txn", **fields)
        assert r.status_code == 200, (i, t, r.text)

    def _lots(self, account: str, day: dt.date) -> dict[tuple[str, dt.date], str]:
        """The lots a sale that day may pick, by symbol and day bought."""
        c = self.client(account)
        r = _ok(c.get(f"/ui/api/accounts/{self.accounts[account]}/lots?date={day.isoformat()}"))
        return {(x["symbol"], dt.date.fromisoformat(x["acquiredOn"])): x["lotId"]
                for x in r.json()["items"]}  # fmt: skip

    def _book(self, year: int, filers: tuple[str, ...]) -> str:
        first = self.c[filers[0]]
        r = _ok(make(first, "TaxBk", year=year, filers=[self.uid[f] for f in filers]))
        book = r.json()["id"]
        for other in filers[1:]:
            _ok(self.c[other].post(f"/ui/api/tax-books/{book}/accept"))
        return book

    def panels(self, year: int, filers: tuple[str, ...]) -> dict:
        book = self.books[(year, filers)]
        return _ok(self.c[filers[0]].get(f"/ui/api/tax-books/{book}/panels")).json()

    def csv(self, year: int, filers: tuple[str, ...]) -> list[dict]:
        book = self.books[(year, filers)]
        r = self.c[filers[0]].get(f"/ui/api/tax-books/{book}/exports/8949.csv")
        assert r.status_code == 200, r.text
        lines = r.text.splitlines()[1:]  # past the heading's comment
        return list(csv.DictReader(io.StringIO("\n".join(lines))))


@pytest.fixture(params=list(tw.SEEDS), ids=lambda s: f"world{s}")
def made(request, server):
    w = tw.world(request.param)
    try:
        yield Made(server, w)
    finally:
        clock.fix(None)


# ---------- the checks ----------


def _dollars(c: int) -> str:
    return f"{c // 100}.{c % 100:02d}"


def _d(x) -> Decimal:
    return Decimal(str(x)) if x is not None else Decimal(0)


def _app_key(r: dict) -> tuple:
    return (r["account"], r["description"],
            dt.date.fromisoformat(r["acquired"]) if r["acquired"] else None,
            dt.date.fromisoformat(r["sold"]), _d(r["proceeds"]), _d(r["basis"]),
            _d(r["adjustment"]), r["longTerm"], r["box"])  # fmt: skip


def _diff(app: list[tuple], want: list[tuple]) -> str:
    extra = list(app)
    missing = []
    for k in want:
        if k in extra:
            extra.remove(k)
        else:
            missing.append(k)
    out = [f"{len(missing)} rows missing, {len(extra)} not expected"]
    out += ["  want " + repr(k) for k in sorted(missing, key=repr)[:12]]
    out += ["  got  " + repr(k) for k in sorted(extra, key=repr)[:12]]
    return "\n".join(out)


def test_a_world(made):
    """Each book's Form 8949 and income are the reference model's; its Schedule D, wash sales
    and CSV export follow its rows."""
    check(made)


def check_world(server, seed: int) -> None:
    """Make the world of `seed` and check it; run under each of `PLANTS` by `test_worlds`."""
    try:
        check(Made(server, tw.world(seed)))
    finally:
        clock.fix(None)


def check(made) -> None:
    _the_rows_are_the_reference_models(made)
    _schedule_d_washes_and_the_export_follow_the_rows(made)
    _income_is_the_reference_models(made)


def _income_is_the_reference_models(made):
    wrong = []
    for year, filers in made.w.books():
        want = ref.income(made.w, year, filers)
        got = made.panels(year, filers)["income"]
        pairs = {
            "interest": (_d(got["interestTotal"]), want.interest),
            "ordinary": (_d(got["ordinary"]), want.ordinary),
            "qualified": (_d(got["qualified"]), want.qualified),
            "gain distributions": (_d(got["capitalGainDistributions"]), want.gain_distributions),
        }
        wrong += [f"{year} {'+'.join(filers)} {k}: got {g}, want {w}"
                  for k, (g, w) in pairs.items() if g != w]  # fmt: skip
    assert not wrong, "\n".join(wrong)


def _the_rows_are_the_reference_models(made):
    h = ref.household(made.w)
    wrong = []
    for year, filers in made.w.books():
        app = sorted((_app_key(r) for r in made.panels(year, filers)["rows"]), key=repr)
        want = sorted((r.key() for r in ref.rows(h, year, filers)), key=repr)
        if app != want:
            wrong.append(f"{year} {'+'.join(filers)}: {_diff(app, want)}")
    assert not wrong, "\n".join(wrong)


def _schedule_d_washes_and_the_export_follow_the_rows(made):
    for year, filers in made.w.books():
        p = made.panels(year, filers)
        rows = p["rows"]
        boxes = {}
        for r in rows:
            t = boxes.setdefault(r["box"], [Decimal(0)] * 4)
            for k, f in enumerate(("proceeds", "basis", "adjustment", "gain")):
                t[k] += _d(r[f])
        got = {b["box"]: [_d(b[f]) for f in ("proceeds", "basis", "adjustment", "gain")]
               for b in p["scheduleD"]["boxes"]}  # fmt: skip
        assert got == boxes, (year, filers)
        d = p["scheduleD"]
        assert _d(d["shortTerm"]) == sum((_d(r["gain"]) for r in rows if not r["longTerm"]),
                                         Decimal(0))  # fmt: skip
        assert _d(d["longTerm"]) == sum((_d(r["gain"]) for r in rows if r["longTerm"]),
                                        Decimal(0))  # fmt: skip
        for r in rows:
            assert _d(r["gain"]) == _d(r["proceeds"]) - _d(r["basis"]) + _d(r["adjustment"])
            assert (r["code"] == "W") == (_d(r["adjustment"]) != 0), r
        disallowed = sum((_d(x["disallowed"]) for x in p["washes"] if not x["review"]),
                         Decimal(0))  # fmt: skip
        assert disallowed == sum((_d(r["adjustment"]) for r in rows), Decimal(0)), (year, filers)
        exported = made.csv(year, filers)
        assert len(exported) == len(rows), (year, filers)
        keyed = sorted(
            (e["Box"], e["Description"], e["Date sold"], _d(e["Proceeds"]), _d(e["Cost basis"]),
             _d(e["Adjustment"] or 0), e["Account"])
            for e in exported
        )  # fmt: skip
        want = sorted(
            (r["box"], r["description"], r["sold"], _d(r["proceeds"]), _d(r["basis"]),
             _d(r["adjustment"]), r["account"])
            for r in rows
        )  # fmt: skip
        assert keyed == want, (year, filers)
