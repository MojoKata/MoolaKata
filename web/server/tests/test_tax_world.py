"""Generated tax worlds (`tax_world`), made through the API and held to the reference model
(`tax_reference`) and to the tax panels' own sums (requirements S2.3, S3.1, S3.8, S8.1, S8.2,
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
import tax_reference as ref
import tax_world as tw
from conftest import make_user, sign_in
from edits import make

from moolakata import clock

T0 = dt.datetime(tw.TODAY.year, tw.TODAY.month, tw.TODAY.day, 15, 0, tzinfo=dt.UTC)


def test_the_worlds_meet_every_pair_of_data_shapes():
    for kind in tw.AXES:
        got = set()
        for seed in tw.SEEDS:
            got |= tw.pairs(tw.world(seed))[kind]
        missing = tw.all_pairs(kind) - got
        assert not missing, (kind, sorted(sorted(p) for p in missing)[:10])


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
        self.books = {}
        for year, filers in w.books():
            self.books[(year, filers)] = self._book(year, filers)

    def client(self, account: str):
        return self.c[tw.ACCOUNTS[account][0]]

    def _trade(self, i: int, t: tw.Trade) -> None:
        c = self.client(t.account)
        fields = {"accountId": self.accounts[t.account], "date": t.date.isoformat(),
                  "amount": t.amount, "kind": t.kind, "symbol": t.symbol,
                  "quantity": str(t.quantity), "price": t.price}  # fmt: skip
        if t.picks:
            lots = self._lots(t.account, t.symbol)
            fields["picks"] = [
                {"lotId": lots[self.w.trades[b].date], "quantity": str(n)} for b, n in t.picks
            ]
        r = make(c, "Txn", **fields)
        assert r.status_code == 200, (i, t, r.text)

    def _lots(self, account: str, symbol: str) -> dict[dt.date, str]:
        h = _ok(self.client(account).get(f"/ui/api/accounts/{self.accounts[account]}/holdings"))
        out = {}
        for row in h.json()["holdings"]:
            if row["symbol"] == symbol:
                for lot in row["lots"]:
                    out[dt.date.fromisoformat(lot["acquiredOn"])] = lot["lotId"]
        return out

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


def reachable(w: tw.World) -> tw.World:
    """The world as the API can make it. A sale's lots can't be picked yet (S2.3's *chosen per
    sale* has no field in the save or the dialog): its picks are left out, here and in the
    reference alike, until `test_a_sales_lots_can_be_picked` passes."""
    for t in w.trades:
        t.picks = []
    return w


def test_a_sales_lots_can_be_picked(server):
    from moolakata.ui.transactions import TxnRecord

    if "picks" not in TxnRecord.model_fields:
        pytest.xfail("S2.3: no way to pick a sale's lots in the save")


# Worlds the app gets wrong today, by what the worlds found (the filed tax years walk's
# Applied): CR3-388, a replacement bought before the loss sale (its loss in its basis before
# the sale, and shares the sale sold counted as its replacement). Strict: a world that passes
# fails here until taken off.
KNOWN = {4, 6, 7, 9, 19, 22}


def _seeds():
    for seed in tw.SEEDS:
        marks = [pytest.mark.xfail(strict=True, reason="CR3-388")] if seed in KNOWN else []
        yield pytest.param(seed, marks=marks, id=f"world{seed}")


@pytest.fixture(params=list(_seeds()))
def made(request, server):
    w = reachable(tw.world(request.param))
    try:
        yield Made(server, w)
    finally:
        clock.fix(None)


# ---------- the checks ----------


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
    """Each book's Form 8949 is the reference model's; its Schedule D, wash sales and CSV
    export follow its rows."""
    _the_rows_are_the_reference_models(made)
    _schedule_d_washes_and_the_export_follow_the_rows(made)


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
