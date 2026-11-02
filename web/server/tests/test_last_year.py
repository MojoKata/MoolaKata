"""Last year's books (requirements S8.14, S8.17; the filed tax years walk, decision 2): every
pair of a couple's arrangements over two years, through the API.

Alice and Bob, married since 2009. In 2025 they filed one of the arrangements of `LAST`; each
2025 book's federal return carries figures of its own (AGI, total tax, capital-loss carryovers,
8606 basis) and has a document received from an issuer of its own. In 2026 they file one of
`THIS`, made with *Start from last year* on or off. For each 2026 book:

1. *From last year* lists the 2025 books each of its filers accepted, and only those: never one
   a filer only was named on, never a deleted one.
2. Joint after separate: the Summary's carryovers and last year's total tax are the sums.
   Separate after joint: a joint return's carryover is the filer's to split (S8.18): none is
   counted until their share is typed, and an issue asks for it.
3. The documents received last year are expected again only with *Start from last year*.
"""

import datetime as dt
import itertools
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import change, make

from moolakata import clock

T0 = dt.datetime(2026, 3, 2, 15, 0, tzinfo=dt.UTC)

# 2025: who filed which book. "pending": named, never accepted.
LAST = {
    "none": [],
    "alice-alone": [("alice", ())],
    "separate": [("alice", ()), ("bob", ())],
    "joint": [("alice", ("bob",))],
    "joint-pending": [("alice", ("bob:pending",))],
    "invited-filed-alone": [("bob", ("alice:pending",)), ("alice", ())],
    "deleted": [("alice", (), "deleted")],
}
THIS = {"alice-alone": [("alice", ())], "separate": [("alice", ()), ("bob", ())],
        "joint": [("alice", ("bob",))]}  # fmt: skip

CASES = [
    pytest.param(last, this, switch, id=f"{last}-then-{this}-{'from' if switch else 'fresh'}")
    for last, this, switch in itertools.product(LAST, THIS, (True, False))
]


def _ok(r):
    assert r.status_code == 200, r.text
    return r


class Couple:
    def __init__(self, server):
        make_user(server, "alice")
        make_user(server, "bob")
        self.c = {"alice": sign_in(server, "alice"), "bob": sign_in(server, "bob")}
        self.uid = {n: c.get("/ui/api/session").json()["user"]["id"] for n, c in self.c.items()}
        pa, pb = (self.c[n].get("/ui/api/profile").json()["personId"] for n in ("alice", "bob"))
        r = _ok(make(self.c["alice"], "Rltn", person1Id=pa, person2Id=pb, relation="spouse",
                     fromDate="2009-06-14"))  # fmt: skip
        _ok(self.c["bob"].post(f"/ui/api/relationships/{r.json()['id']}/confirm"))
        self.made: list[dict] = []  # each 2025 book: id, accepted filers, figures, issuer

    def book(self, year: int, owner: str, others: tuple, switch: bool = True) -> dict:
        names = [owner, *(o.split(":")[0] for o in others)]
        r = make(self.c[owner], "TaxBk", year=year, filers=[self.uid[n] for n in names],
                 fromLastYear=switch)  # fmt: skip
        b = _ok(r).json()
        accepted = {owner}
        for o in others:
            if not o.endswith(":pending"):
                _ok(self.c[o].post(f"/ui/api/tax-books/{b['id']}/accept"))
                accepted.add(o)
        return {"id": b["id"], "owner": owner, "accepted": accepted}

    def last_year(self, arrangement: str) -> None:
        for owner, others, *rest in LAST[arrangement]:
            b = self.book(2025, owner, others)
            k = len(self.made) + 1
            figures = {"agi": f"{k * 10000}.00", "totalTax": f"{k * 1000}.00",
                       "capitalLossShort": f"{k * 100}.00", "capitalLossLong": f"{k * 200}.00",
                       "basis8606": f"{k * 50}.00"}  # fmt: skip
            c = self.c[owner]
            _ok(make(c, "Filng", bookId=b["id"], jurisdiction="federal", form="1040",
                     progress="filed", filedOn="2026-04-10", carried=figures))  # fmt: skip
            issuer = f"Issuer {k}"
            _ok(make(c, "TxDoc", bookId=b["id"], form="1099-INT", issuer=issuer))
            # A child of the book's own, copied a year older when the next book starts from it.
            kid = _ok(make(c, "Persn", name=f"Child {k}", sex="female", birthYear=2015))
            _ok(make(c, "TxDep", bookId=b["id"], personId=kid.json()["id"],
                     claimedAs="qualifying child", months=12))  # fmt: skip
            b |= {"figures": figures, "issuer": issuer, "kid": f"Child {k}"}
            if rest and rest[0] == "deleted":
                got = c.get(f"/ui/api/tax-books/{b['id']}").json()
                from edits import remove

                _ok(remove(c, "TaxBk", got))
                b["deleted"] = True
            self.made.append(b)

    def expected_books(self, filers: set[str]) -> list[dict]:
        """For each filer, the 2025 book they accepted, deleted ones aside."""
        return [b for b in self.made if not b.get("deleted") and b["accepted"] & filers]


@pytest.fixture
def couple(server):
    clock.fix(T0)
    try:
        yield Couple(server)
    finally:
        clock.fix(None)


def _d(x) -> Decimal:
    return Decimal(str(x)) if x is not None else Decimal(0)


@pytest.mark.parametrize(("last", "this", "switch"), CASES)
def test_last_years_books_are_the_filers_accepted_ones(couple, last, this, switch):
    w = couple
    w.last_year(last)
    books = [w.book(2026, owner, others, switch) for owner, others in THIS[this]]
    for b in books:
        c = w.c[b["owner"]]
        want = w.expected_books(b["accepted"])
        d = _ok(c.get(f"/ui/api/tax-books/{b['id']}")).json()
        got = sorted(_d(x["figures"]["agi"]) for x in d["lastYear"])
        assert got == sorted(_d(x["figures"]["agi"]) for x in want), (b["accepted"], d["lastYear"])
        p = _ok(c.get(f"/ui/api/tax-books/{b['id']}/panels")).json()
        split = any(len(x["accepted"]) > len(b["accepted"]) for x in want)
        asks = [i for i in p["issues"] if i["kind"] == "carryover-share"]
        if split:
            # A joint return's carryover, the filer's own share not typed yet: none counted.
            assert _d(p["scheduleD"]["carryoverShort"]) == 0 and asks, p["issues"]
        else:
            assert not asks
            assert _d(p["scheduleD"]["carryoverShort"]) == sum(
                (_d(x["figures"]["capitalLossShort"]) for x in want), Decimal(0)
            )
            assert _d(p["scheduleD"]["carryoverLong"]) == sum(
                (_d(x["figures"]["capitalLossLong"]) for x in want), Decimal(0)
            )
        tax = sum((_d(x["figures"]["totalTax"]) for x in want), Decimal(0))
        assert _d(p["lastYearTax"]) == tax if want else p["lastYearTax"] is None
        issuers = {e["issuer"] for e in d["expected"] if e["why"].startswith("Received in")}
        assert issuers == ({x["issuer"] for x in want} if switch else set()), d["expected"]
        # The copy is from each filer's book, whoever accepted last (S8.14.4).
        kids = {x["name"] for x in d["dependents"]}
        assert kids == ({x["kid"] for x in want} if switch else set()), d["dependents"]


def test_a_joint_returns_carryover_counts_once_the_filer_types_their_share(couple):
    # S8.18: splitting a joint carryover is the filers' call; once typed, the Summary has it.
    w = couple
    w.last_year("joint")
    b = w.book(2026, "alice", ())
    c = w.c["alice"]
    got = c.get(f"/ui/api/tax-books/{b['id']}").json()
    _ok(change(c, "TaxBk", got, carryoverShareShort="40.00", carryoverShareLong="150.00"))
    p = _ok(c.get(f"/ui/api/tax-books/{b['id']}/panels")).json()
    assert (_d(p["scheduleD"]["carryoverShort"]), _d(p["scheduleD"]["carryoverLong"])) == (
        Decimal("40.00"),
        Decimal("150.00"),
    )
    assert not [i for i in p["issues"] if i["kind"] == "carryover-share"]


def test_one_book_a_year_for_each_filer_and_a_waiting_book_declined(couple):
    # S8.14.1: a filer is on one book a year; a pending invitation blocks nothing, and is
    # declined, its owner told.
    w = couple
    mine = w.book(2025, "alice", ())
    r = make(w.c["alice"], "TaxBk", year=2025, filers=[w.uid["alice"]])
    assert r.status_code == 422 and "a filer on 2025's tax book" in r.text, r.text
    invite = w.book(2025, "bob", ("alice:pending",))
    r = w.c["alice"].post(f"/ui/api/tax-books/{invite['id']}/accept")
    assert r.status_code == 422 and "a filer on 2025's tax book" in r.text, r.text
    assert w.c["alice"].post(f"/ui/api/tax-books/{invite['id']}/decline").status_code == 204
    assert w.c["alice"].get("/ui/api/tax-books").json()["waiting"] == []
    d = w.c["bob"].get(f"/ui/api/tax-books/{invite['id']}").json()
    assert [f["id"] for f in d["filers"]] == [w.uid["bob"]]
    told = w.c["bob"].get("/ui/api/activity").json()["items"]
    assert any(a["kind"] == "tax-book.declined" for a in told), told
    assert mine
