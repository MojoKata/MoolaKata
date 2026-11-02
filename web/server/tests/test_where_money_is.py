"""Where the money is (requirements S7.10.4, S7.10.5): each transaction of an account reserves
are held in is classified once, and what is to move is the reserves' total less what the
account holds for them. Doing what it says leaves every account backed."""

import datetime as dt
import random
from decimal import Decimal

import pytest
from edits import budget_accounts, edit, saved
from test_accounts import add, new_account
from test_budgets import save_plan, setup_budget

from moolakata import clock
from moolakata.budgets import Members, Span, Tree
from moolakata.budgets.reserves import classify

T0 = dt.datetime(2026, 12, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def _ok(r):
    assert r.status_code == 200, r.text


def _where(c, b, m="2026-12"):
    r = c.get(f"/ui/api/budgets/{b['id']}/where", params={"month": m})
    assert r.status_code == 200, r.text
    return {h["accountName"]: h for h in r.json()["heldIn"]}


def _setup(server, *held):
    """A budget with reserves, Checking and a savings account for each name in `held`."""
    c, acct, cat, b = setup_budget(server)
    saved(edit(c, "Bdgt", f"/ui/api/budgets/{b['id']}", reserves=True))
    accounts = {"Checking": acct}
    for i, name in enumerate(held):
        accounts[name] = new_account(c, name=name, type="savings", mask=f"{2222 + i}")
    _ok(budget_accounts(c, b, [a["id"] for a in accounts.values()]))
    return c, accounts, cat, b


def _transfer(c, frm, to, amount, day):
    add(c, frm["id"], f"-{amount}", day, payee="Transfer out")
    add(c, to["id"], amount, day, payee="Transfer in", kind="deposit")


def test_spending_paid_from_the_held_in_account_is_the_reserves_own(server, frozen):
    """The claim (CR3-39): $1,000 moved in, then the roofer paid $700 from Ally: Ally holds
    $300, the reserve $300, so the account is backed, not $700 to move back."""
    c, a, cat, b = _setup(server, "Ally")
    roof = cat["Housing › Maintenance"]
    _ok(save_plan(c, b, "2026-11-01", [{"categoryId": roof, "amount": "500", "target": "5000",
                                        "heldInId": a["Ally"]["id"]}]))  # fmt: skip
    _transfer(c, a["Checking"], a["Ally"], "500.00", "2026-11-01")
    _transfer(c, a["Checking"], a["Ally"], "500.00", "2026-12-01")
    add(c, a["Ally"]["id"], "-700.00", "2026-12-05", payee="Roofer", categoryId=roof)
    h = _where(c, b)["Ally"]
    assert (h["total"], h["balance"], h["toMove"]) == ("300.00", "300.00", "0.00")


def test_a_refund_in_a_reserves_category_is_its_own_never_landed(server, frozen):
    """Found while walking: the roofer's $100 refund into Ally is the reserve's own, so it
    is never offered as landed money to give, which would count it twice."""
    c, a, cat, b = _setup(server, "Ally")
    roof = cat["Housing › Maintenance"]
    _ok(save_plan(c, b, "2026-12-01", [{"categoryId": roof, "amount": "500", "target": "5000",
                                        "heldInId": a["Ally"]["id"]}]))  # fmt: skip
    _transfer(c, a["Checking"], a["Ally"], "500.00", "2026-12-01")
    add(c, a["Ally"]["id"], "-300.00", "2026-12-05", payee="Roofer", categoryId=roof)
    add(c, a["Ally"]["id"], "100.00", "2026-12-09", payee="Roofer refund", categoryId=roof,
        kind="deposit")  # fmt: skip
    h = _where(c, b)["Ally"]
    assert h["unassigned"] == []
    assert (h["total"], h["balance"], h["toMove"]) == ("300.00", "300.00", "0.00")


def test_a_cross_payment_is_moved_straight_between_the_two_accounts(server, frozen):
    """1.1 of the walk: Ally pays $200 of a repair whose reserve Marcus holds: $200 to move
    from Marcus to Ally, and nothing with Checking. Once moved, both read backed."""
    c, a, cat, b = _setup(server, "Ally", "Marcus")
    roof, repair = cat["Housing › Maintenance"], cat["Transportation › Car maintenance"]
    _ok(save_plan(c, b, "2026-12-01", [
        {"categoryId": roof, "amount": "300", "target": "5000", "heldInId": a["Ally"]["id"]},
        {"categoryId": repair, "amount": "400", "target": "5000", "heldInId": a["Marcus"]["id"]},
    ]))  # fmt: skip
    _transfer(c, a["Checking"], a["Ally"], "300.00", "2026-12-01")
    _transfer(c, a["Checking"], a["Marcus"], "400.00", "2026-12-01")
    add(c, a["Ally"]["id"], "-200.00", "2026-12-05", payee="Midas", categoryId=repair)
    w = _where(c, b)
    ally, marcus = w["Ally"], w["Marcus"]
    assert (ally["toMove"], marcus["toMove"]) == ("0.00", "0.00")
    assert [(x["fromName"], x["toName"], x["amount"]) for x in ally["between"]] == [
        ("Marcus", "Ally", "200.00")
    ]
    _transfer(c, a["Marcus"], a["Ally"], "200.00", "2026-12-10")
    w = _where(c, b)
    for name in ("Ally", "Marcus"):
        assert (w[name]["toMove"], w[name]["between"]) == ("0.00", []), name


def _line(target=None, held=None):
    from types import SimpleNamespace

    return SimpleNamespace(target=target, heldInId=held, cadence="month")


def test_each_kind_of_transaction_has_one_class():
    """A table of the classes (S7.10.4): moved, reserve (here or elsewhere), landed, own."""
    from types import SimpleNamespace

    cat = lambda i, parent=None: SimpleNamespace(id=i, parentId=parent, kind="expense")  # noqa: E731
    tr = Tree({"roof": cat("roof"), "repair": cat("repair"), "food": cat("food"),
               "fee": cat("fee"), "interest": cat("interest")})  # fmt: skip
    plan = {"roof": _line("5000", "ally"), "repair": _line("5000", "marcus"), "food": _line()}
    mem = Members((Span("chk", None, None), Span("ally", None, None), Span("marcus", None, None)))
    day = dt.date(2026, 12, 5)

    def kinds(amount, category=None, other=None, parts=None):
        t = SimpleNamespace(id="t", date=day, amount=Decimal(amount), categoryId=category)
        return [(f.kind, f.amount, f.reserveIn) for f in
                classify(t, parts or [], other, "ally", mem, tr, lambda m: plan)]  # fmt: skip

    D = Decimal
    assert kinds("500", other="chk") == [("moved", D("500"), None)]
    assert kinds("-200", other="marcus") == [("moved", D("-200"), None)]
    assert kinds("-700", "roof") == [("reserve", D("-700"), "ally")]
    assert kinds("100", "roof") == [("reserve", D("100"), "ally")]
    assert kinds("-200", "repair") == [("reserve", D("-200"), "marcus")]
    assert kinds("4.20", "interest") == [("landed", D("4.20"), None)]
    assert kinds("300", other="outside") == [("landed", D("300"), None)]
    assert kinds("-3", "fee") == [("own", D("-3"), None)]
    assert kinds("-80", "food") == [("own", D("-80"), None)]
    assert kinds("-50", other="outside") == [("own", D("-50"), None)]
    split = [("roof", D("-60")), ("food", D("-40"))]
    assert kinds("-100", parts=split) == [("reserve", D("-60"), "ally"), ("own", D("-40"), None)]


@pytest.mark.parametrize("seed", range(6))
def test_doing_what_to_move_says_leaves_every_account_backed(server, frozen, seed):
    """Generated: reserves held in two accounts, spending and refunds in their categories paid
    from Checking or either account, interest landing; then each move *Where the money is*
    asks for is made, and every account reads backed."""
    rnd = random.Random(seed)
    c, a, cat, b = _setup(server, "Ally", "Marcus")
    roof, repair = cat["Housing › Maintenance"], cat["Transportation › Car maintenance"]
    _ok(save_plan(c, b, "2026-11-01", [
        {"categoryId": roof, "amount": "300", "target": "5000", "heldInId": a["Ally"]["id"]},
        {"categoryId": repair, "amount": "200", "target": "5000", "heldInId": a["Marcus"]["id"]},
    ]))  # fmt: skip
    _transfer(c, a["Checking"], a["Ally"], "300.00", "2026-11-02")
    _transfer(c, a["Checking"], a["Marcus"], "200.00", "2026-11-02")
    for i in range(6):
        day = f"2026-12-{3 + i:02d}"
        payer = rnd.choice(["Checking", "Ally", "Marcus"])
        category = rnd.choice([roof, repair])
        amount = rnd.randint(10, 150) + i / 100
        sign = "" if rnd.random() < 0.2 else "-"
        add(c, a[payer]["id"], f"{sign}{amount:.2f}", day, payee="Shop", categoryId=category)
    for name in ("Ally", "Marcus"):
        if rnd.random() < 0.5:
            add(c, a[name]["id"], "1.37", "2026-12-01", payee="Interest", kind="interest")
    w = _where(c, b)
    day = 20
    for name, h in w.items():
        for x in h["between"]:
            if x["toName"] == name:
                _transfer(c, a[x["fromName"]], a[name], x["amount"], f"2026-12-{day}")
                day += 1
        move = Decimal(h["toMove"])
        if move > 0:
            _transfer(c, a["Checking"], a[name], f"{move:.2f}", f"2026-12-{day}")
        elif move < 0:
            _transfer(c, a[name], a["Checking"], f"{-move:.2f}", f"2026-12-{day}")
        day += 1
    for name, h in _where(c, b).items():
        assert (h["toMove"], h["between"]) == ("0.00", []), (name, h)
