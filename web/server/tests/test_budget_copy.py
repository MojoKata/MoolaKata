"""Copy as scenario (requirements S7.12.4): the same accounts and plan from this month, in the
method chosen, with this month's moves when asked."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import budget_accounts, make, share
from test_accounts import add, new_account
from test_budgets import cats, setup_budget
from test_reserves import landed, put_plan, reserves_on

from moolakata import clock

T0 = dt.datetime(2026, 12, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def copy(c, b, method="tracking", with_moves=False) -> dict:
    r = c.post(f"/ui/api/budgets/{b['id']}/copy",
               json={"name": "Scenario", "method": method, "withMoves": with_moves})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


def plan_lines(c, b) -> dict[str, dict]:
    v = c.get(f"/ui/api/budgets/{b['id']}/plan", params={"month": "2026-12"}).json()
    return {x["categoryId"]: x for x in v["lines"]}


def test_a_reserve_held_in_an_account_the_copy_does_not_count_is_held_nowhere(server, frozen):
    """A reserve is held in one of the budget's accounts (S7.10.4): a copier who can't see that
    account gets the reserve, target kept, held nowhere (*in the budget's accounts*)."""
    c, acct, cat, b = setup_budget(server)
    ally = new_account(c, name="Ally", type="savings", mask="2222")
    assert budget_accounts(c, b, [acct["id"], ally["id"]]).status_code == 200
    reserves_on(c, b)
    repair = cat["Transportation › Car maintenance"]
    line = {"categoryId": repair, "amount": "100", "target": "500", "heldInId": ally["id"]}
    assert put_plan(c, b, "2026-12-01", [line]).status_code == 200
    # Its owner's copy counts Ally: the reserve stays held there.
    assert plan_lines(c, copy(c, b))[repair]["heldInId"] == ally["id"]
    make_user(server, "john")
    john = sign_in(server, "john")
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    share(c, "budget", b["id"], users={john_id: "read"})
    share(c, "account", acct["id"], users={john_id: "read"})
    theirs = copy(john, b)
    got = plan_lines(john, theirs)[repair]
    assert (str(got["target"]), got["heldInId"]) == ("500.00", None)


def moves_of(c, b) -> list[tuple[str, str, str]]:
    v = c.get(f"/ui/api/budgets/{b['id']}/month", params={"month": "2026-12"}).json()
    return sorted((m["fromLabel"], m["toLabel"], str(m["amount"])) for m in v["moves"])


def test_this_months_moves_come_along_as_the_copy_can_hold_them(server, frozen):
    """A move into a card's payment line comes along into an envelope copy that counts the card;
    landed money given or kept comes along into either method while the copy counts its account;
    To Budget's moves only into an envelope copy (S7.12.4, S7.13.2, S7.10.5). None is rewritten
    as another."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)
    visa = new_account(c, name="Visa", type="credit-card", mask="1111")
    ally = new_account(c, name="Ally", type="savings", mask="2222")
    cat = cats(c)
    ids_ = [chk["id"], visa["id"], ally["id"]]
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=ids_).json()
    reserves_on(c, b)
    food, fun = cat["Food"], cat["Entertainment"]
    repair = cat["Transportation › Car maintenance"]
    lines = [
        {"categoryId": food, "amount": "300"},
        {"categoryId": fun, "amount": "100"},
        {"categoryId": repair, "amount": "100", "target": "500", "heldInId": ally["id"]},
    ]
    assert put_plan(c, b, "2026-12-01", lines).status_code == 200
    add(c, chk["id"], "3000.00", "2026-12-01", payee="Payroll", categoryId=cat["Income › Salary"])
    interest = add(c, ally["id"], "40.00", "2026-12-03", payee="Interest", kind="interest")
    for body in ({"cardId": visa["id"], "amount": "60"},
                 {"fromCategoryId": food, "cardId": visa["id"], "amount": "20"},
                 {"toCategoryId": food, "amount": "10"},
                 {"fromCategoryId": food, "toCategoryId": fun, "amount": "5"}):  # fmt: skip
        r = make(c, "BdgMv", **{"budgetId": b["id"], "month": "2026-12-01", **body})
        assert r.status_code == 200, r.text
    assert landed(c, b, interest, {repair: "30.00", None: "10.00"}).status_code == 200
    every = moves_of(c, b)
    assert len(every) == 6
    assert moves_of(c, copy(c, b, "envelope", with_moves=True)) == every
    assert moves_of(c, copy(c, b, "tracking", with_moves=True)) == [
        ("Food", "Entertainment", "5.00"),
        ("money landed", "Transportation › Car maintenance", "30.00"),
        ("money landed", "the account's own", "10.00"),
    ]
    # A copier who sees only the checking account: no card, no Ally.
    make_user(server, "john")
    john = sign_in(server, "john")
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    share(c, "budget", b["id"], users={john_id: "read"})
    share(c, "account", chk["id"], users={john_id: "read"})
    assert moves_of(john, copy(john, b, "envelope", with_moves=True)) == [
        ("Food", "Entertainment", "5.00"),
        ("To Budget", "Food", "10.00"),
    ]
