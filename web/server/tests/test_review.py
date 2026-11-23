"""The month's review, the kept month figures and the cash before payday (requirements S7.14,
S7.3.10, S7.6.1)."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import budget_accounts, change, saved, share
from test_accounts import add, new_account
from test_budgets import plan, setup_budget

from moolakata import alerts, clock

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def test_a_reviewed_month_is_flagged_when_it_changes(server, frozen):
    c, acct, cat, b = setup_budget(server)
    plan(c, b, "2026-09-01", [{"categoryId": cat["Food"], "amount": "300.00"}])
    add(c, acct["id"], "-340.00", "2026-09-10", payee="Kroger", categoryId=cat["Food › Groceries"])
    add(c, acct["id"], "-12.00", "2026-09-11", payee="Mystery")
    r = c.get(f"/ui/api/budgets/{b['id']}/review")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["month"] == "2026-09-01" and v["reviewed"] is None
    assert [(x["label"], x["over"]) for x in v["overspent"]] == [("Food", "40.00")]
    assert v["uncategorised"] == 1
    r = c.post(f"/ui/api/budgets/{b['id']}/review", json={"month": "2026-09-01"})
    assert r.status_code == 200, r.text
    assert r.json()["reviewed"]["changes"] == []
    # A late transaction lands in September: the month is flagged, with what changed.
    add(c, acct["id"], "-20.00", "2026-09-28", payee="Kroger", categoryId=cat["Food › Groceries"])
    changed = c.get(f"/ui/api/budgets/{b['id']}/review", params={"month": "2026-09"}).json()
    assert changed["reviewed"]["changes"] == [
        "Food: spent 340.00 then, 360.00 now",
        "Spent: 340.00 then, 360.00 now",
    ]
    # October's review lists September among the months before.
    oct_ = c.get(f"/ui/api/budgets/{b['id']}/review", params={"month": "2026-10"}).json()
    assert [(h["month"], bool(h["changes"])) for h in oct_["history"]] == [("2026-09-01", True)]


def test_a_changed_review_names_every_total_that_changed(server, frozen):
    """S7.14: what changed lists each changed total, beside a changed row, not just the first."""
    c, acct, cat, b = setup_budget(server)
    plan(c, b, "2026-09-01", [{"categoryId": cat["Food"], "amount": "300.00"}])
    add(c, acct["id"], "-100.00", "2026-09-10", payee="Kroger", categoryId=cat["Food"])
    assert c.post(f"/ui/api/budgets/{b['id']}/review", json={"month": "2026-09-01"}).is_success

    def changes():
        v = c.get(f"/ui/api/budgets/{b['id']}/review", params={"month": "2026-09"}).json()
        return v["reviewed"]["changes"]

    add(c, acct["id"], "3000.00", "2026-09-28", payee="Acme Payroll", categoryId=cat["Income"])
    assert changes() == ["Income: 0.00 then, 3000.00 now"]
    add(c, acct["id"], "-20.00", "2026-09-29", payee="Kroger", categoryId=cat["Food"])
    assert changes() == [
        "Food: spent 100.00 then, 120.00 now",
        "Spent: 100.00 then, 120.00 now",
        "Income: 0.00 then, 3000.00 now",
    ]


def _user(server, name):
    make_user(server, name)
    c = sign_in(server, name)
    return c, c.get("/ui/api/session").json()["user"]["id"]


def test_a_review_compares_each_viewer_with_their_own_figures(server, frozen):
    """S7.14, S7.1.1: Carol's card is shared with Jane, not with John. Jane marks September
    reviewed: John's flag never reads the card's spending, and each one's clears on its own;
    one who reads the budget after the review sees who reviewed it, with nothing changed."""
    c, acct, cat, b = setup_budget(server)
    carol, _ = _user(server, "carol")
    jane_id = c.get("/ui/api/session").json()["user"]["id"]
    card = new_account(carol, name="Carol Visa", type="credit-card", mask="1111")
    share(carol, "account", card["id"], users={jane_id: "read"})
    assert budget_accounts(c, b, [acct["id"], card["id"]]).status_code == 200
    plan(c, b, "2026-09-01", [{"categoryId": cat["Food"], "amount": "300.00"}])
    add(c, acct["id"], "-100.00", "2026-09-10", payee="Kroger", categoryId=cat["Food"])
    add(carol, card["id"], "-457.30", "2026-09-12", payee="Bistro", categoryId=cat["Food"])
    john, john_id = _user(server, "john")
    share(c, "budget", b["id"], users={john_id: "write"})
    share(c, "account", acct["id"], users={john_id: "read"})

    def changes(who):
        v = who.get(f"/ui/api/budgets/{b['id']}/review", params={"month": "2026-09"}).json()
        return v["reviewed"]["changes"]

    assert c.post(f"/ui/api/budgets/{b['id']}/review", json={"month": "2026-09-01"}).is_success
    assert changes(c) == [] and changes(john) == []
    assert john.post(f"/ui/api/budgets/{b['id']}/review", json={"month": "2026-09-01"}).is_success
    assert changes(c) == [] and changes(john) == []
    # A late charge on the card changes Jane's September, not John's.
    add(carol, card["id"], "-20.00", "2026-09-28", payee="Bistro", categoryId=cat["Food"])
    assert changes(c)[0] == "Food: spent 557.30 then, 577.30 now"
    assert changes(john) == []
    # One at Checking changes both, each read in their own figures.
    add(c, acct["id"], "-5.00", "2026-09-29", payee="Kroger", categoryId=cat["Food"])
    assert changes(c)[0] == "Food: spent 557.30 then, 582.30 now"
    assert changes(john)[0] == "Food: spent 100.00 then, 105.00 now"
    # Someone the budget is shared with afterwards sees who reviewed it, and no change list.
    amy, amy_id = _user(server, "amy")
    share(c, "budget", b["id"], users={john_id: "write", amy_id: "read"})
    v = amy.get(f"/ui/api/budgets/{b['id']}/review", params={"month": "2026-09"}).json()
    assert v["reviewed"]["byName"] and v["reviewed"]["changes"] == []


def test_cash_before_payday(server, frozen):
    c, acct, _, _ = setup_budget(server)
    for m in (7, 8, 9, 10):
        add(c, acct["id"], "2000.00", f"2026-{m:02d}-01", payee="Acme Payroll")
    for m in (7, 8, 9):
        add(c, acct["id"], "-1000.00", f"2026-{m:02d}-25", payee="Oak Street Apts")
    add(c, acct["id"], "-5900.00", "2026-10-05", payee="Car repair")
    opened = alerts.evaluate(server)
    (a,) = [x for x in opened if x.kind == "cash-short"]
    assert a.title == "Checking dips below $0 on the 25th"
    assert "before money comes in on Nov 1" in a.about


def test_cash_before_payday_goes_to_each_who_follows_the_budget(server, frozen):
    """S7.6: a household budget active for Jane and for John raises the alert to each."""
    c, acct, _, b = setup_budget(server)
    john, john_id = _user(server, "john")
    share(c, "budget", b["id"], users={john_id: "write"})
    share(c, "account", acct["id"], users={john_id: "read"})
    assert saved(change(john, "User", john.get("/ui/api/profile").json(), activeBudgetId=b["id"]))
    for m in (7, 8, 9, 10):
        add(c, acct["id"], "2000.00", f"2026-{m:02d}-01", payee="Acme Payroll")
    for m in (7, 8, 9):
        add(c, acct["id"], "-1000.00", f"2026-{m:02d}-25", payee="Oak Street Apts")
    add(c, acct["id"], "-5900.00", "2026-10-05", payee="Car repair")
    alerts.evaluate(server)
    for who in (c, john):
        (a,) = [x for x in who.get("/ui/api/alerts").json()["open"] if x["kind"] == "cash-short"]
        assert a["title"] == "Checking dips below $0 on the 25th"
