"""The month's review, the kept month figures and the cash before payday (requirements S7.14,
S7.3.10, S7.6.1)."""

import datetime as dt

import pytest
from sqlalchemy import update
from test_accounts import add
from test_budgets import month, plan, row, setup_budget

from moolakata import alerts, clock
from moolakata.store.entities.accounts import Transaction

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
    assert changed["reviewed"]["changes"] == ["Food: spent 340.00 then, 360.00 now"]
    # October's review lists September among the months before.
    oct_ = c.get(f"/ui/api/budgets/{b['id']}/review", params={"month": "2026-10"}).json()
    assert [(h["month"], bool(h["changes"])) for h in oct_["history"]] == [("2026-09-01", True)]


def test_month_figures_are_kept_and_refreshed(server, frozen):
    c, acct, cat, b = setup_budget(server)
    plan(c, b, "2026-10-01", [{"categoryId": cat["Food"], "amount": "300.00"}])
    t = add(
        c, acct["id"], "-50.00", "2026-10-03", payee="Kroger", categoryId=cat["Food › Groceries"]
    )
    assert row(month(c, b, "2026-10"), "Food")["actual"] == "50.00"
    # A change the kept figures don't see (written past the session's flush): Refresh does.
    with server.db.tx(unscoped="test") as s:
        s.execute(update(Transaction).where(Transaction.id == t["id"]).values(amount=-80))
    assert row(month(c, b, "2026-10"), "Food")["actual"] == "50.00"
    r = c.post(f"/ui/api/budgets/{b['id']}/refresh", params={"month": "2026-10"})
    assert r.status_code == 200, r.text
    assert row(r.json(), "Food")["actual"] == "80.00"


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
    assert "before money comes in on Oct 31" in a.about
