"""Charitable giving (requirements S7.9, S8.9): the plan and target, donations of each type,
what is deductible and needs an acknowledgement, shares from a lot, and the donor-advised fund
counted once."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, giving_plan, make, saved, share
from test_accounts import add, new_account

from moolakata import clock

T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def jane(server, frozen):
    make_user(server, "jane")
    return sign_in(server, "jane")


def org(c, name, **kw):
    r = make(c, "Orgzn", **{"name": name, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def donate(c, **kw):
    r = make(c, "Dnatn", **kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_target_pace_and_pledges(jane):
    saved(giving_plan(jane, 2026, percent="10", incomeBasis="gross", income="185000"))
    church = org(
        jane,
        "St. Mark's Parish",
        ein="36-2167053",
        causes=["Faith"],
        pledge="200",
        pledgeEvery="month",
    )
    donate(jane, date="2026-02-01", kind="cash", organisationId=church["id"], amount="2000")
    v = jane.get("/ui/api/giving").json()
    assert v["target"] == "18500.00" and v["given"] == "2000.00"
    assert v["pace"] == str(round(18500 * 286 / 365)) + ".00"
    assert v["pledged"] == "400.00", "November and December"
    assert v["projected"] == "2400.00"
    assert v["byCause"] == [{"label": "Faith", "amount": "2000.00"}]
    bad = giving_plan(jane, 2026, incomeBasis="gross", income=None)
    assert bad.json()["errors"][0]["field"] == "income"


def test_giving_transactions_count_and_acknowledgements_are_flagged(jane):
    saved(giving_plan(jane, 2026, percent="10"))
    org(jane, "Red Cross")
    bank = new_account(jane, name="Checking")
    add(jane, bank["id"], "9000.00", "2026-01-02", categoryId=_cat(jane, "Salary"))
    add(
        jane,
        bank["id"],
        "-300.00",
        "2026-03-01",
        payee="Red Cross",
        categoryId=_cat(jane, "Giving"),
    )
    rows = jane.get("/ui/api/giving/donations").json()["items"]
    assert [(d["name"], d["amount"], d["needsAck"], d["id"]) for d in rows] == [
        ("Red Cross", "300.00", True, None)
    ]
    v = jane.get("/ui/api/giving").json()
    assert v["income"] == "9000.00" and v["target"] == "900.00" and v["missingAcks"] == 1
    # Recorded, then acknowledged.
    red = jane.get("/ui/api/giving/organisations").json()["items"][0]
    d = donate(
        jane,
        date="2026-03-01",
        kind="cash",
        organisationId=red["id"],
        transactionId=rows[0]["transactionId"],
    )
    assert d["amount"] == "300.00"
    up = jane.post(
        "/ui/api/receipts", files={"file": ("ack.pdf", b"%PDF-1.4 thank you", "application/pdf")}
    )
    r = change(jane, "Dnatn", d, receiptIds={"add": [up.json()["id"]], "remove": []})
    assert saved(r)["acknowledged"]
    assert jane.get("/ui/api/giving").json()["missingAcks"] == 0
    assert len(jane.get("/ui/api/giving/donations").json()["items"]) == 1, "counted once"


def _cat(c, name):
    return next(x["id"] for x in c.get("/ui/api/categories").json()["items"] if x["name"] == name)


def test_shares_from_a_lot_without_a_gain(jane):
    brk = new_account(jane, name="Brokerage", type="brokerage")
    add(
        jane,
        brk["id"],
        "-1000.00",
        "2024-01-05",
        kind="buy",
        symbol="VTI",
        quantity="10",
        price="100",
    )
    add(
        jane,
        brk["id"],
        "-3000.00",
        "2026-06-05",
        kind="buy",
        symbol="VTI",
        quantity="10",
        price="300",
    )
    lots = jane.get(f"/ui/api/accounts/{brk['id']}/holdings").json()["holdings"][0]["lots"]
    old, new = lots
    food = org(jane, "Food Depository")
    d = donate(
        jane,
        date="2026-10-01",
        kind="securities",
        organisationId=food["id"],
        fromAccountId=brk["id"],
        lotId=old["lotId"],
        quantity="4",
        amount="1320",
    )
    assert d["longTerm"] and d["basis"] == "400.00" and d["amount"] == "1320.00"
    # Held under a year: the deduction is the basis.
    d2 = donate(
        jane,
        date="2026-10-01",
        kind="securities",
        organisationId=food["id"],
        fromAccountId=brk["id"],
        lotId=new["lotId"],
        quantity="2",
        amount="660",
    )
    assert not d2["longTerm"] and d2["amount"] == "600.00"
    h = jane.get(f"/ui/api/accounts/{brk['id']}/holdings").json()["holdings"][0]
    assert h["quantity"] == "14.0"
    assert [x["quantity"] for x in h["lots"]] == ["6.0", "8.0"]
    too_many = make(
        jane,
        "Dnatn",
        date="2026-10-02",
        kind="securities",
        organisationId=food["id"],
        fromAccountId=brk["id"],
        lotId=old["lotId"],
        quantity="60",
        amount="1",
    )
    assert too_many.json()["errors"][0]["field"] == "quantity"


def test_a_donor_advised_fund_counts_once(jane):
    saved(giving_plan(jane, 2026, targetKind="amount", amount="5000"))
    fund = new_account(jane, name="Giving fund", type="daf", institution="Fidelity Charitable")
    assert jane.get(f"/ui/api/accounts/{fund['id']}").json()["countInNetWorth"] is False
    bank = new_account(jane, name="Checking")
    add(jane, bank["id"], "20000.00", "2026-01-02")
    library = org(jane, "Library Foundation")
    donate(
        jane,
        date="2026-03-01",
        kind="daf-contribution",
        dafAccountId=fund["id"],
        fromAccountId=bank["id"],
        amount="4000",
    )
    g = donate(
        jane,
        date="2026-06-01",
        kind="daf-grant",
        dafAccountId=fund["id"],
        organisationId=library["id"],
        amount="1000",
        granted=True,
    )
    assert not g["deductible"] and not g["counted"]
    v = jane.get("/ui/api/giving").json()
    assert v["given"] == "4000.00"
    assert v["funds"][0]["balance"] == "3000.00" and v["funds"][0]["granted"] == "1000.00"
    saved(giving_plan(jane, 2026, targetKind="amount", amount="5000", dafCounted="granted"))
    assert jane.get("/ui/api/giving").json()["given"] == "1000.00"


def test_qcds_goods_and_what_they_need(jane):
    church = org(jane, "Parish")
    shop = org(jane, "Goodwill")
    campaign = org(jane, "Friends of a candidate", deductible=False)
    q = donate(jane, date="2026-04-01", kind="qcd", organisationId=church["id"], amount="3000")
    assert not q["deductible"] and q["counted"]
    donate(
        jane,
        date="2026-05-01",
        kind="goods",
        organisationId=shop["id"],
        amount="6000",
        description="A piano",
    )
    p = donate(jane, date="2026-05-02", kind="cash", organisationId=campaign["id"], amount="500")
    assert not p["deductible"] and not p["needsAck"]
    notes = jane.get("/ui/api/giving").json()["notes"]
    assert any("Form 8283" in n for n in notes) and any("appraisal" in n for n in notes)


def test_a_shared_plan_counts_its_owners_accounts_only(server, jane):
    """S7.9.1: sharing her plan with John shows it to him, and never reads his money."""
    make_user(server, "john")
    john = sign_in(server, "john")
    b_id = john.get("/ui/api/session").json()["user"]["id"]
    plan = saved(giving_plan(jane, 2026, percent="10"))
    share(jane, "giving-plan", plan["id"], users={b_id: "read"})
    mine = new_account(jane, name="Jane's checking")
    his = new_account(john, name="John's checking")
    add(jane, mine["id"], "9000.00", "2026-01-02", categoryId=_cat(jane, "Salary"))
    add(john, his["id"], "7000.00", "2026-01-02", categoryId=_cat(john, "Salary"))
    add(
        john, his["id"], "-500.00", "2026-03-01", payee="Food Bank", categoryId=_cat(john, "Giving")
    )
    v = jane.get("/ui/api/giving").json()
    assert v["income"] == "9000.00" and v["given"] == "0.00"
    assert jane.get("/ui/api/giving/donations").json()["items"] == []
    assert john.get("/ui/api/giving").json()["income"] == "9000.00", "he sees her plan"


def test_a_donated_replacement_is_held_from_the_sold_shares_purchase(jane):
    # S3.8.3: a wash sale's replacement carries the sold shares' days, so given away
    # within a year of its own purchase it can still be long term.
    brk = new_account(jane, name="Brokerage", type="brokerage")
    add(jane, brk["id"], "10000.00", "2025-01-02", kind="deposit")
    for date, kind, amount, qty, price in (
        ("2025-03-01", "buy", "-2000.00", "10", "200"),
        ("2026-06-01", "sell", "1500.00", "10", "150"),  # a 500 loss
        ("2026-06-20", "buy", "-620.00", "4", "155"),  # replaces 4 of the 10
    ):
        add(jane, brk["id"], amount, date, kind=kind, symbol="AAPL", quantity=qty, price=price)
    (lot,) = jane.get(f"/ui/api/accounts/{brk['id']}/holdings").json()["holdings"][0]["lots"]
    d = donate(
        jane,
        date="2026-10-01",
        kind="securities",
        organisationId=org(jane, "Food Depository")["id"],
        fromAccountId=brk["id"],
        lotId=lot["lotId"],
        quantity="4",
        amount="700",
    )
    assert d["longTerm"], "held since 2025-03-20, over a year"


def test_a_split_paycheck_counts_through_its_income_parts(jane):
    """S7.9.2, S7.3.1: a paycheck split across Income categories is income, part by part; a
    part in another category isn't."""
    saved(giving_plan(jane, 2026, percent="10"))
    bank = new_account(jane, name="Checking")
    add(
        jane,
        bank["id"],
        "4500.00",
        "2026-01-15",
        payee="Acme payroll",
        splits=[
            {"categoryId": _cat(jane, "Salary"), "amount": "4000.00"},
            {"categoryId": _cat(jane, "Other income"), "amount": "1000.00"},
            {"categoryId": _cat(jane, "Taxes"), "amount": "-500.00"},
        ],
    )
    add(jane, bank["id"], "1000.00", "2026-02-15", categoryId=_cat(jane, "Salary"))
    v = jane.get("/ui/api/giving").json()
    assert v["income"] == "6000.00" and v["target"] == "600.00"
    assert v["history"][-1] == {"year": 2026, "percent": 0.0}
