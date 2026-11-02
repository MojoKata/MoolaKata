"""Generated budget worlds (`budget_world`), made through the API and held to every budget
invariant (requirements S7): pairwise coverage of the data shapes, asserted, and each world's
figures checked month by month for its viewer.

The invariants, each from the budgets walk (`docs/reviews/code-review-0003-2026-10-24/
budgets-walk.md`):

1. One reading of a line's month (S7.3.11): every row, every month (`test_budgets.month`).
2. Each transaction counts against one line at most (S7.1.2): the rows' spending and the
   unplanned add up to the month's spending.
3. A balance carries on (S7.10.3, S7.1.2): a line that rolls over begins each month with what
   the month before left, through any amount.
4. Compare over a range (S7.12.3): a carrying line's range leaves what its last month leaves;
   another's range has its months' own available.
5. History reads as it was (R3.10): an account taken out, one closed and one outside deleted
   after March leave January to March as they were.
6. Where the money is (S7.10.4): a repair paid from the account a reserve is held in, or a
   refund into it, leaves what it is short as it was, and one paid from Checking leaves it
   that much ahead; and doing what *to move* says leaves every account backed.

And throughout, every kept month is worked out again and compared (S7.3.10, `cache.CHECK`).
"""

import datetime as dt
from decimal import Decimal

import budget_world as bw
import pytest
from conftest import make_user, sign_in
from edits import change, drop, edit, make, new_id, saved, share
from test_accounts import add, new_account
from test_budgets import cats, month, save_plan

from moolakata import clock

T0 = dt.datetime(*bw.TODAY, 15, 0, tzinfo=dt.UTC)


def test_the_worlds_meet_every_pair_of_data_shapes():
    """Every pair of values of two axes of one record that can exist meets in some world."""
    for kind in bw.AXES:
        got = set()
        for seed in bw.SEEDS:
            got |= bw.pairs(bw.world(seed))[kind]
        missing = bw.all_pairs(kind) - got
        assert not missing, (kind, sorted(sorted(p) for p in missing)[:10])


# ---------- making a world ----------


def _ok(r):
    assert r.status_code == 200, r.text
    return r


class Made:
    def __init__(self, server, w: bw.World):
        self.w = w
        make_user(server, "alice")
        self.c = sign_in(server, "alice")
        self.cat = cats(self.c)
        self.accounts: dict[str, dict] = {}
        for i, (name, kind) in enumerate({**bw.IN_BUDGET, **bw.OUTSIDE}.items()):
            mask = None if kind in ("cash", "brokerage") else f"{1000 + i}"
            kind = {"card": "credit-card"}.get(kind, kind)
            self.accounts[name] = new_account(self.c, name=name, type=kind, mask=mask,
                                              openingBalance="2000.00",
                                              openingDate="2025-12-31")  # fmt: skip
        # Made in January, so an envelope budget's envelopes run all four months (S7.13.1).
        clock.fix(dt.datetime(2026, 1, 5, 15, 0, tzinfo=dt.UTC))
        r = make(self.c, "Bdgt", name="World", method=w.method, reserves=True, moves=True)
        clock.fix(T0)
        self.b = _ok(r).json()
        self._accounts()
        self._plan()
        self._txns()
        self._moves()
        self._ends()
        self.viewer = self.c if w.viewer == "owner" else self._receiver(server)

    def id(self, name: str) -> str:
        return self.accounts[name]["id"]

    def _accounts(self):
        """Each account's records over months, as its span says (S7.1.7)."""
        spans = {"always": [(None, None)], "from": [("2026-02-01", None)],
                 "until": [(None, "2026-02-01")],
                 "gap": [(None, "2026-01-01"), ("2026-04-01", None)],
                 "closed": [(None, None)]}  # fmt: skip
        ops = []
        for name in bw.IN_BUDGET:
            for first, last in spans[self.w.spans.get(name, "always")]:
                fields = {"budgetId": self.b["id"], "accountId": self.id(name),
                          "fromMonth": first, "untilMonth": last}  # fmt: skip
                ops.append({"op": "create", "entity": "BdgAc", "id": new_id("BdgAc"),
                            "fields": fields})  # fmt: skip
        _ok(self.c.post("/ui/api/save", json={"ops": ops}))

    def _plan(self):
        for m in bw.MONTHS:
            lines = []
            for category, ln in self.w.plan_at(m).items():
                line = {"categoryId": self.cat[category], "amount": ln["amount"],
                        "cadence": ln["cadence"], "rollover": ln["rollover"]}  # fmt: skip
                if ln.get("target"):
                    line |= {"target": ln["target"], "heldInId": self.id(ln["heldIn"])}
                lines.append(line)
            _ok(save_plan(self.c, self.b, m + "-01", lines, confirm=True))

    def _other(self, t: bw.Txn) -> str | None:
        if t.other == "inside":
            return next(n for n in ("Checking", "Spare", "Visa", "Ally")
                        if n != t.account and self.w.counts(n, t.month))  # fmt: skip
        if t.other == "held-in":
            return next(n for n in bw.HELD if n != t.account)
        return {"outside": "Brokerage", "cash": "Pocket", "deleted": "Old",
                "unseen": "Hidden"}.get(t.other)  # fmt: skip

    def _txns(self):
        for i, t in enumerate(self.w.txns):
            day = f"{t.month}-{t.day:02d}"
            kw: dict = {"payee": f"{t.shape} {i}"}
            if t.category:
                kw["categoryId"] = self.cat[t.category]
            if t.parts:
                kw["splits"] = [{"categoryId": self.cat[k], "amount": a} for k, a in t.parts]
            if t.reimbursable:
                kw["reimbursable"] = t.reimbursable
            if not t.amount.startswith("-"):
                kw["kind"] = "deposit"
            made = add(self.c, self.id(t.account), t.amount, day, **kw)
            other = self._other(t)
            if other is not None:
                back = t.amount[1:] if t.amount.startswith("-") else "-" + t.amount
                kind = "deposit" if not back.startswith("-") else "withdrawal"
                half = add(self.c, self.id(other), back, day, payee=f"half {i}", kind=kind)
                assert half["transferId"] == made["id"], (t, half)
            if t.shape == "left-out":
                now = self.c.get(f"/ui/api/transactions/{made['id']}").json()
                saved(change(self.c, "Txn", now,
                             leftOutOf={"add": [self.b["id"]], "remove": []}))  # fmt: skip

    def _moves(self):
        for mv in self.w.moves:
            body: dict = {"budgetId": self.b["id"], "month": mv.month + "-01",
                          "amount": mv.amount}  # fmt: skip
            if mv.kind in ("landed-given", "landed-kept"):
                landed = add(self.c, self.id(mv.account), mv.amount, mv.month + "-01",
                             payee="Interest", kind="interest")  # fmt: skip
                body |= {"transactionId": landed["id"], "month": landed["date"],
                         "toCategoryId": self.cat[mv.to] if mv.to else None}  # fmt: skip
            elif mv.kind == "card":
                body |= {"cardId": self.id("Visa"), "fromCategoryId": self.cat[mv.frm]}
            else:
                body |= {"fromCategoryId": self.cat[mv.frm] if mv.frm else None,
                         "toCategoryId": self.cat[mv.to]}  # fmt: skip
            _ok(make(self.c, "BdgMv", **body))

    def _ends(self):
        """What ends: a closed span's account, and the outside account deleted since."""
        for name, span in self.w.spans.items():
            if span == "closed":
                _ok(edit(self.c, "Acct", f"/ui/api/accounts/{self.id(name)}",
                         closedOn="2026-03-10"))  # fmt: skip
        _ok(drop(self.c, "Acct", f"/ui/api/accounts/{self.id('Old')}", confirm=True))

    def _receiver(self, server):
        make_user(server, "bob")
        bob = sign_in(server, "bob")
        bob_id = bob.get("/ui/api/session").json()["user"]["id"]
        _ok(share(self.c, "budget", self.b["id"], users={bob_id: "read"}))
        seen = bw.IN_BUDGET if self.w.viewer == "receiver-all" else ("Checking", "Ally")
        for name in seen:
            _ok(share(self.c, "account", self.id(name), users={bob_id: "read"}))
        return bob


# ---------- the invariants ----------


def _months(made: Made) -> dict[str, dict]:
    return {m: month(made.viewer, made.b, m) for m in bw.MONTHS}


def _rows_and_unplanned_are_the_spending(views):
    for m, v in views.items():
        # A yearly row's spending is its year's so far; its month's is apart (S7.3.12).
        # An envelope's card spending beyond what it held is owed, not backed (S7.13.2).
        rows = sum(
            Decimal(r["actual"]) + Decimal(r["unbacked"])
            for r in v["rows"]
            if r["kind"] == "expense" and r["cadence"] == "month"
        )
        unplanned = sum(Decimal(x["spent"]) for x in v["unplanned"])
        assert rows + Decimal(v["yearlySpent"]) + unplanned == Decimal(v["spent"]), m


def _balances_carry_on(made: Made, views):
    for before, after in zip(bw.MONTHS, bw.MONTHS[1:], strict=False):
        was = {r["categoryId"]: r for r in views[before]["rows"]}
        for r in views[after]["rows"]:
            p = was.get(r["categoryId"])
            if p is None or not (p["rollover"] and r["rollover"]):
                continue
            if (p["target"] is None) != (r["target"] is None) or p["cadence"] != r["cadence"]:
                continue  # a reserve begun or ended starts afresh
            want = Decimal(p["remaining"])
            if made.w.method == "envelope" and p["overspend"] == "next" and want < 0:
                want = Decimal(0)
            assert Decimal(r["carried"]) == want, (after, r["label"])


def _a_range_reads_its_months(made: Made, views):
    other = _ok(make(made.c, "Bdgt", name="Other")).json()
    query = {"other": other["id"], "month": bw.MONTHS[-1], "span": "year"}
    r = _ok(made.c.get(f"/ui/api/budgets/{made.b['id']}/compare", params=query))
    got = {x["categoryId"]: x for x in r.json()["rows"] if x["available"] is not None}
    owner = {m: month(made.c, made.b, m) for m in bw.MONTHS}
    rows = {m: {x["categoryId"]: x for x in v["rows"]} for m, v in owner.items()}
    for cat_id, x in got.items():
        each = [rows[m].get(cat_id) for m in bw.MONTHS]
        if any(e is None for e in each) or each[-1]["cadence"] != "month":
            continue
        if len({(e["target"] is None, e["rollover"]) for e in each}) != 1:
            continue
        if each[-1]["rollover"]:
            left = Decimal(x["available"]) - Decimal(x["spent"])
            assert left == Decimal(each[-1]["remaining"]), each[-1]["label"]
        else:
            assert Decimal(x["available"]) == sum(Decimal(e["planned"]) for e in each)
    del views


def _figures(v):
    """A month's figures, without the names an account's deletion may change."""
    moved = [{k: x[k] for k in x if k not in ("otherAccountName",)} for x in v["moved"]]
    return {**v, "moved": moved, "daysLeft": None}


def _history_holds(made: Made):
    before = {m: _figures(month(made.viewer, made.b, m)) for m in bw.MONTHS[:3]}
    rows = made.c.get(f"/ui/api/budgets/{made.b['id']}/accounts").json()["items"]
    spare = [x for x in rows if x["accountId"] == made.id("Spare") and x["untilMonth"] is None
             and (x["fromMonth"] or "") < "2026-04-01"]  # fmt: skip
    for x in spare:
        _ok(change(made.c, "BdgAc", x, untilMonth="2026-03-01"))
    if made.w.spans.get("Visa") != "closed":
        _ok(edit(made.c, "Acct", f"/ui/api/accounts/{made.id('Visa')}", closedOn="2026-04-15"))
    _ok(drop(made.c, "Acct", f"/ui/api/accounts/{made.id('Brokerage')}", confirm=True))
    after = {m: _figures(month(made.viewer, made.b, m)) for m in bw.MONTHS[:3]}
    assert after == before


def _where(made: Made) -> dict[str, dict]:
    r = made.c.get(f"/ui/api/budgets/{made.b['id']}/where", params={"month": bw.MONTHS[-1]})
    return {h["accountName"]: h for h in _ok(r).json()["heldIn"]}


def _short(h: dict) -> Decimal:
    """What the account is short of its reserves, + short, − ahead: to move with its moved-from
    account and with other held-in accounts together."""
    mine = sum(Decimal(x["amount"]) for x in h["between"] if x["toName"] == h["accountName"])
    theirs = sum(Decimal(x["amount"]) for x in h["between"] if x["fromName"] == h["accountName"])
    return Decimal(h["toMove"]) + mine - theirs


def _reserve_flows_read_right(made: Made):
    """What *to move* answers, not how (S7.10.4): a repair paid from the account a reserve is
    held in, or a refund into it, leaves what the account is short as it was; the same repair
    paid from Checking leaves it that much ahead (it goes back)."""
    plan = made.w.plan_at(bw.MONTHS[-1])
    held = [(c, ln["heldIn"]) for c, ln in plan.items() if ln.get("heldIn")]
    if not held:
        return
    category, account = held[0]
    cat_id, day = made.cat[category], "2026-04-19"
    before = _short(_where(made)[account])
    add(made.c, made.id(account), "-37.15", day, payee="Repair here", categoryId=cat_id)
    assert _short(_where(made)[account]) == before, "a repair paid from where it is held"
    add(made.c, made.id(account), "11.20", day, payee="Refund here", categoryId=cat_id,
        kind="deposit")  # fmt: skip
    assert _short(_where(made)[account]) == before, "a refund into where it is held"
    assert all(x["payee"] != "Refund here" for x in _where(made)[account]["unassigned"])
    add(made.c, made.id("Checking"), "-23.40", day, payee="Repair there", categoryId=cat_id)
    assert _short(_where(made)[account]) == before - Decimal("23.40"), "a repair paid elsewhere"


def _moves_leave_it_backed(made: Made):
    for name, h in _where(made).items():
        for x in h["between"]:
            if x["toName"] == name:
                _pair(made, x["fromName"], name, Decimal(x["amount"]))
        move = Decimal(h["toMove"])
        if move > 0:
            _pair(made, "Checking", name, move)
        elif move < 0:
            _pair(made, name, "Checking", -move)
    for name, h in _where(made).items():
        assert (h["toMove"], h["between"]) == ("0.00", []), (name, h)


def _pair(made: Made, frm: str, to: str, amount: Decimal):
    day = "2026-04-20"
    out = add(made.c, made.id(frm), f"-{amount:.2f}", day, payee=f"to {to}")
    back = add(made.c, made.id(to), f"{amount:.2f}", day, payee=f"from {frm}", kind="deposit")
    assert back["transferId"] == out["id"]


@pytest.mark.parametrize("seed", bw.SEEDS)
def test_a_worlds_figures_keep_every_rule(server, seed):
    clock.fix(T0)
    try:
        made = Made(server, bw.world(seed))
        views = _months(made)  # the reading of every row, every month (invariant 1)
        _rows_and_unplanned_are_the_spending(views)
        _balances_carry_on(made, views)
        _a_range_reads_its_months(made, views)
        _history_holds(made)
        _reserve_flows_read_right(made)
        _moves_leave_it_backed(made)
    finally:
        clock.fix(None)
