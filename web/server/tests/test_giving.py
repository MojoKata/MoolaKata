"""Charitable giving (requirements S7.9, S8.9): the plan and target, donations of each type,
what is deductible and needs an acknowledgement, shares from a lot, and the donor-advised fund
counted once."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, giving_plan, make, remove, saved, share
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
    assert v["pledged"] == "600.00", "October's, not yet given, November's and December's"
    assert v["projected"] == "2600.00"
    assert v["byCause"] == [{"label": "Faith", "amount": "2000.00"}]
    bad = giving_plan(jane, 2026, incomeBasis="gross", income=None)
    assert bad.json()["errors"][0]["field"] == "income"


def test_this_months_pledge_is_expected_less_what_was_given_to_it(jane):
    """S7.9.6, S7.9.5: the projected year end expects this month's monthly pledge less what
    was given to its organisation this month, never below nothing, and the year's yearly one
    less what was given to it this year."""
    saved(giving_plan(jane, 2026, targetKind="amount", amount="5000"))
    food = org(jane, "Food Bank", pledge="100", pledgeEvery="month")
    library = org(jane, "Library", pledge="300", pledgeEvery="year")
    donate(jane, date="2026-09-30", kind="cash", organisationId=food["id"], amount="100")
    donate(jane, date="2026-02-01", kind="cash", organisationId=library["id"], amount="120")
    v = jane.get("/ui/api/giving").json()
    assert v["pledged"] == "480.00", "100 for October, 200 after it, and the library's 180"
    donate(jane, date="2026-10-02", kind="cash", organisationId=food["id"], amount="40")
    assert jane.get("/ui/api/giving").json()["pledged"] == "440.00"
    donate(jane, date="2026-10-05", kind="cash", organisationId=food["id"], amount="90")
    v = jane.get("/ui/api/giving").json()
    assert v["pledged"] == "380.00", "October met (over by 30, not carried)"
    assert v["projected"] == "730.00"


def _on(y, m, d):
    clock.fix(dt.datetime(y, m, d, 12, tzinfo=dt.UTC))


def _due(server) -> list[tuple[str, str]]:
    """The open *pledge due* alerts, after the alerts task has run."""
    from moolakata import alerts
    from moolakata.store.entities.alerts import Alert

    alerts.evaluate(server)
    with server.db.read(unscoped="test") as s:
        rows = s.query(Alert).filter(Alert.kind == "pledge-due", Alert.resolvedAt.is_(None))
        return [(a.title, a.about) for a in rows]


def test_a_missed_month_stays_due_until_made_up_a_late_gift_paying_the_oldest(server, frozen):
    """S7.9.5: September's pledge, unpaid, is still due in October; October's $100 pays
    September's first, so October's stays due until a second $100. One alert throughout."""
    from moolakata.store.entities.alerts import Alert

    make_user(server, "jane")
    _on(2026, 9, 2)
    food = org(sign_in(server, "jane"), "Food Bank", pledge="100", pledgeEvery="month")
    _on(2026, 9, 24)
    assert _due(server) == []
    due = ("Your pledge to Food Bank is due", "for September")
    _on(2026, 9, 25)
    assert _due(server) == [due]
    _on(2026, 10, 2)
    assert _due(server) == [due], "the month's end forgives nothing"
    _on(2026, 10, 26)
    c = sign_in(server, "jane")
    assert _due(server) == [("Your pledge to Food Bank is due", "for September to October")]
    donate(c, date="2026-10-26", kind="cash", organisationId=food["id"], amount="100")
    assert _due(server) == [("Your pledge to Food Bank is due", "for October")]
    donate(c, date="2026-10-26", kind="cash", organisationId=food["id"], amount="100")
    assert _due(server) == []
    with server.db.read(unscoped="test") as s:
        assert s.query(Alert).filter(Alert.kind == "pledge-due").count() == 1


def test_a_pledge_changed_counts_from_its_period_and_cleared_ends_its_alert(server, frozen):
    """S7.9.5: only the user's own change forgives a missed period: a new amount counts from
    the month it is set in, a note changed counts nothing again, and a pledge cleared ends."""
    make_user(server, "jane")
    _on(2026, 9, 2)
    food = org(sign_in(server, "jane"), "Food Bank", pledge="100", pledgeEvery="month")
    _on(2026, 10, 2)
    c = sign_in(server, "jane")
    food = saved(change(c, "Orgzn", food, notes="the parish pantry"))
    assert _due(server) == [("Your pledge to Food Bank is due", "for September")]
    food = saved(change(c, "Orgzn", food, pledge="50"))
    assert _due(server) == [], "counted from October, not due before the 25th"
    _on(2026, 10, 25)
    c = sign_in(server, "jane")
    assert _due(server) == [("Your pledge to Food Bank is due", "for October")]
    saved(change(c, "Orgzn", food, pledge=None, pledgeEvery=None))
    assert _due(server) == []


def test_a_yearly_pledge_is_met_by_a_giving_transaction_to_its_name_the_next_year(server, frozen):
    """S7.9.5, S7.9.3: 2025's pledge, due from December 1, stays due into 2026, and is met by a
    card payment filed under Giving to the organisation's name, as the Giving screen counts it."""
    make_user(server, "jane")
    _on(2025, 6, 2)
    org(sign_in(server, "jane"), "Library", pledge="300", pledgeEvery="year")
    _on(2025, 11, 30)
    assert _due(server) == []
    _on(2025, 12, 1)
    assert _due(server) == [("Your pledge to Library is due", "for 2025")]
    _on(2026, 1, 5)
    c = sign_in(server, "jane")
    assert _due(server) == [("Your pledge to Library is due", "for 2025")]
    card = new_account(c, name="Card", type="credit-card")
    add(c, card["id"], "-300.00", "2026-01-04", payee="Library", categoryId=_cat(c, "Giving"))
    assert _due(server) == []


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
    assert john.get("/ui/api/giving", params={"plan": plan["id"]}).json()["income"] == "9000.00"


def _john(server):
    make_user(server, "john")
    john = sign_in(server, "john")
    return john, john.get("/ui/api/session").json()["user"]["id"]


def test_ones_own_plan_comes_first_with_the_plans_shared_that_year_to_choose(server, jane):
    """S7.9.1: a plan shared with John doesn't stop him keeping his own that year; his Giving
    screen shows his own, and hers when he chooses it."""
    john, john_id = _john(server)
    hers = saved(giving_plan(jane, 2026, targetKind="amount", amount="5000"))
    share(jane, "giving-plan", hers["id"], users={john_id: "read"})
    v = john.get("/ui/api/giving").json()
    assert v["plan"] is None
    assert [(p["id"], p["ownerName"]) for p in v["shared"]] == [(hers["id"], "Jane")]
    assert john.get("/ui/api/giving", params={"plan": hers["id"]}).json()["target"] == "5000.00"
    his = saved(giving_plan(john, 2026, targetKind="amount", amount="800"))
    v = john.get("/ui/api/giving").json()
    assert v["plan"]["id"] == his["id"] and v["target"] == "800.00"
    assert [p["id"] for p in v["shared"]] == [hers["id"]]
    assert john.get("/ui/api/giving", params={"plan": hers["id"]}).json()["target"] == "5000.00"
    # Another year's plan, or one he doesn't read, isn't his to choose.
    assert john.get("/ui/api/giving", params={"year": 2025, "plan": hers["id"]}).status_code == 404
    assert jane.get("/ui/api/giving", params={"plan": his["id"]}).status_code == 404
    assert jane.get("/ui/api/giving").json()["shared"] == []


def test_a_plan_sent_across_a_link_is_the_plan_itself(server, jane):
    """S11.4, S7.9.1: what a link sends for a shared giving plan is that plan, though its
    viewer keeps one of their own that year."""
    from moolakata.links import serve
    from moolakata.store.entities.users import User
    from moolakata.ui.deps import Caller

    john, john_id = _john(server)
    hers = saved(giving_plan(jane, 2026, targetKind="amount", amount="5000"))
    share(jane, "giving-plan", hers["id"], users={john_id: "read"})
    saved(giving_plan(john, 2026, targetKind="amount", amount="800"))
    it = serve.Item(hers["id"], "giving-plan", "2026", "Jane", "2026-10-13")
    with server.db.read(unscoped="test: the viewer") as s:
        viewer = Caller(s.get(User, john_id), None, False)
        s.expunge(viewer.user)
    docs = {path: serve._document(fn(viewer)) for path, fn in serve._paths(server, it)}
    assert docs["/giving?year=2026"]["plan"]["id"] == hers["id"]
    assert docs["/giving/donations?year=2026"]["items"] == []


def test_a_reader_gives_from_his_own_and_adds_nothing_to_the_plan_he_reads(server, jane):
    """S7.9.1, S10.3.1: John reads Jane's plan; what he records is his own giving, and the
    plan he reads takes nothing from him."""
    john, john_id = _john(server)
    hers = saved(giving_plan(jane, 2026, percent="10"))
    share(jane, "giving-plan", hers["id"], users={john_id: "read"})
    shelter = org(john, "Night Shelter")
    assert shelter["access"]["writable"]
    d = donate(john, date="2026-03-01", kind="cash", organisationId=shelter["id"], amount="250")
    assert d["organisationId"] == shelter["id"] and d["access"]["writable"]
    assert [x["id"] for x in john.get("/ui/api/giving/donations").json()["items"]] == [d["id"]]
    assert john.get("/ui/api/giving").json()["given"] == "250.00"
    assert jane.get("/ui/api/giving/donations").json()["items"] == []
    into_hers = make(john, "Orgzn", name="Food Bank", planId=hers["id"])
    assert into_hers.status_code == 403, into_hers.text
    into_hers = make(
        john,
        "Dnatn",
        date="2026-03-02",
        kind="cash",
        organisationId=shelter["id"],
        amount="10",
        planId=hers["id"],
    )
    assert into_hers.status_code == 403, into_hers.text


def test_a_writer_adds_to_the_plan_shown_as_its_owners(server, jane):
    """S7.9.1, S10.3.2: what John adds to Jane's plan, shared with him to write, is the plan's:
    hers, counted and listed there."""
    john, john_id = _john(server)
    hers = saved(giving_plan(jane, 2026, percent="10"))
    share(jane, "giving-plan", hers["id"], users={john_id: "write"})
    food = org(john, "Food Bank", planId=hers["id"])
    assert [o["id"] for o in jane.get("/ui/api/giving/organisations").json()["items"]] == [
        food["id"]
    ]
    assert john.get("/ui/api/giving/organisations").json()["items"] == []
    listed = john.get("/ui/api/giving/organisations", params={"plan": hers["id"]}).json()
    assert [o["id"] for o in listed["items"]] == [food["id"]]
    d = donate(
        john,
        date="2026-04-01",
        kind="cash",
        organisationId=food["id"],
        amount="300",
        planId=hers["id"],
    )
    assert d["name"] == "Food Bank" and d["counted"]
    assert [x["id"] for x in jane.get("/ui/api/giving/donations").json()["items"]] == [d["id"]]
    assert jane.get("/ui/api/giving").json()["given"] == "300.00"
    assert john.get("/ui/api/giving").json()["given"] == "0.00", "his own giving"
    # Her plan is for 2026: a donation of 2025 isn't one of its entries.
    other_year = make(
        john,
        "Dnatn",
        date="2025-12-01",
        kind="cash",
        organisationId=food["id"],
        amount="5",
        planId=hers["id"],
    )
    assert other_year.json()["errors"][0]["field"] == "date"
    # He changes her plan, and keeps one of his own.
    assert saved(change(john, "GvPln", hers, percent="12"))["percent"] == "12.00"
    assert saved(giving_plan(john, 2026, percent="5"))["percent"] == "5.00"


def test_a_writer_pays_into_the_plan_shown_from_its_owners_accounts_or_none(server, jane):
    """S7.9.1: a donation John adds to Jane's plan comes from one of her accounts he may
    write, or from none; his own account, or hers he only reads, is refused at the field."""
    john, john_id = _john(server)
    hers = saved(giving_plan(jane, 2026, percent="10"))
    share(jane, "giving-plan", hers["id"], users={john_id: "write"})
    food = org(jane, "Food Bank")
    her_bank = new_account(jane, name="Jane's checking", type="checking")
    her_savings = new_account(jane, name="Jane's savings", type="savings")
    share(jane, "account", her_bank["id"], users={john_id: "write"})
    share(jane, "account", her_savings["id"], users={john_id: "read"})
    his_bank = new_account(john, name="John's checking", type="checking")
    his_brk = new_account(john, name="John's brokerage", type="brokerage")
    add(john, his_brk["id"], "-1000.00", "2024-01-05", kind="buy", symbol="VTI", quantity="10",
        price="100")  # fmt: skip
    lot = john.get(f"/ui/api/accounts/{his_brk['id']}/holdings").json()["holdings"][0]["lots"][0]
    cash = {"date": "2026-04-01", "kind": "cash", "organisationId": food["id"], "amount": "300"}
    for refused in (
        {**cash, "fromAccountId": his_bank["id"]},
        {**cash, "fromAccountId": her_savings["id"]},
        {**cash, "kind": "securities", "fromAccountId": his_brk["id"], "lotId": lot["lotId"],
         "quantity": "1"},
    ):  # fmt: skip
        r = make(john, "Dnatn", planId=hers["id"], **refused)
        assert r.status_code == 422, r.text
        (e,) = r.json()["errors"]
        assert e["field"] == "fromAccountId" and "Jane" not in e["message"]
    held = john.get(f"/ui/api/accounts/{his_brk['id']}/holdings").json()["holdings"][0]
    assert held["lots"][0]["quantity"] == lot["quantity"], "no shares left his account"
    paid = donate(john, planId=hers["id"], fromAccountId=her_bank["id"], **cash)
    t = jane.get(f"/ui/api/transactions/{paid['transactionId']}").json()
    assert t["accountId"] == her_bank["id"] and t["amount"] == "-300.00"
    unpaid = donate(john, planId=hers["id"], **cash)
    assert unpaid["transactionId"] is None
    assert jane.get("/ui/api/giving").json()["given"] == "600.00"


def test_a_writer_records_the_owners_transactions_and_funds_only(server, jane):
    """S7.9.1: into Jane's plan, John records a transaction in one of her accounts he may
    write, and names one of her funds he may write; his own, or hers he only reads, are
    refused at their field, and a recorded donation keeps them."""
    john, john_id = _john(server)
    hers = saved(giving_plan(jane, 2026, percent="10"))
    share(jane, "giving-plan", hers["id"], users={john_id: "write"})
    food = org(jane, "Food Bank")
    giving_cat = _cat(jane, "Giving")
    her_bank = new_account(jane, name="Jane's checking", type="checking")
    her_savings = new_account(jane, name="Jane's savings", type="savings")
    her_fund = new_account(jane, name="Jane's fund", type="daf")
    her_old_fund = new_account(jane, name="Jane's old fund", type="daf")
    for a, how in ((her_bank, "write"), (her_savings, "read"), (her_fund, "write"),
                   (her_old_fund, "read")):  # fmt: skip
        share(jane, "account", a["id"], users={john_id: how})
    his_bank = new_account(john, name="John's checking", type="checking")
    his_fund = new_account(john, name="John's fund", type="daf")
    hers_paid = add(jane, her_bank["id"], "-40.00", "2026-04-02", categoryId=giving_cat)
    hers_read = add(jane, her_savings["id"], "-50.00", "2026-04-03", categoryId=giving_cat)
    his_paid = add(john, his_bank["id"], "-60.00", "2026-04-04", categoryId=_cat(john, "Giving"))
    cash = {"date": "2026-04-05", "kind": "cash", "organisationId": food["id"]}
    grant = {**cash, "kind": "daf-grant", "amount": "70"}
    for refused, field in (
        ({**cash, "transactionId": his_paid["id"]}, "transactionId"),
        ({**cash, "transactionId": hers_read["id"]}, "transactionId"),
        ({**grant, "dafAccountId": his_fund["id"]}, "dafAccountId"),
        ({**grant, "dafAccountId": her_old_fund["id"]}, "dafAccountId"),
    ):
        r = make(john, "Dnatn", planId=hers["id"], **refused)
        assert r.status_code == 422, r.text
        (e,) = r.json()["errors"]
        assert (e["field"], e["code"]) == (field, "account-not-plans"), e
        assert "plan owner's" in e["message"] and "Jane" not in e["message"]
    paid = donate(john, planId=hers["id"], transactionId=hers_paid["id"], **cash)
    assert paid["transactionId"] == hers_paid["id"] and paid["amount"] == "40.00"
    granted = donate(john, planId=hers["id"], dafAccountId=her_fund["id"], **grant)
    t = jane.get(f"/ui/api/transactions/{granted['transactionId']}").json()
    assert t["accountId"] == her_fund["id"] and t["amount"] == "-70.00"
    for field, to in (("transactionId", his_paid["id"]), ("dafAccountId", his_fund["id"])):
        r = change(john, "Dnatn", granted, **{field: to})
        assert r.json()["errors"][0]["field"] == field, r.text
    v = jane.get("/ui/api/giving").json()
    assert v["given"] == "90.00", "her two Giving transactions; the grant counts at its fund"


def test_a_writer_changes_and_deletes_the_plans_entries_a_reader_cant(server, jane):
    """S10.3.2: a giving plan shared to write lets John change its donations and
    organisations, Jane's or those he added; at read he can't."""
    john, john_id = _john(server)
    hers = saved(giving_plan(jane, 2026, percent="10"))
    share(jane, "giving-plan", hers["id"], users={john_id: "write"})
    church = org(jane, "Parish")
    food = org(jane, "Food Bank")
    d = donate(jane, date="2026-03-01", kind="cash", organisationId=church["id"], amount="500")
    seen = john.get("/ui/api/giving/donations", params={"plan": hers["id"]}).json()["items"]
    assert seen[0]["access"]["writable"]
    d = saved(change(john, "Dnatn", d, acknowledged=True, organisationId=food["id"]))
    assert d["acknowledged"] and d["name"] == "Food Bank"
    food = saved(change(john, "Orgzn", food, pledge="50", pledgeEvery="month"))
    assert food["pledge"] == "50.00" and food["access"]["writable"]
    assert remove(john, "Dnatn", d).status_code == 200
    assert remove(john, "Orgzn", food).status_code == 200
    assert jane.get("/ui/api/giving/donations").json()["items"] == []
    assert [o["name"] for o in jane.get("/ui/api/giving/organisations").json()["items"]] == [
        "Parish"
    ]
    share(jane, "giving-plan", hers["id"], users={john_id: "read"})
    d = donate(jane, date="2026-03-02", kind="cash", organisationId=church["id"], amount="20")
    seen = john.get("/ui/api/giving/donations", params={"plan": hers["id"]}).json()["items"]
    assert not seen[0]["access"]["writable"]
    assert change(john, "Dnatn", d, acknowledged=True).status_code in (403, 404)
    assert change(john, "Orgzn", church, notes="x").status_code in (403, 404)
    assert remove(john, "Dnatn", d).status_code in (403, 404)


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


def _category(c, name, **kw):
    r = make(c, "Cat", name=name, kind="expense", **kw)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_a_donation_is_any_charitable_part_wherever_its_category_sits(jane):
    """S7.9.3, S7.3.1: a transaction or split part in a category tagged charitable is a
    donation, under Giving or not, each part a gift of its own."""
    saved(giving_plan(jane, 2026, targetKind="amount", amount="5000"))
    bank = new_account(jane, name="Checking")
    giving_id = _cat(jane, "Giving")
    church = _category(jane, "Church", parentId=giving_id, taxTag="charitable")
    alumni = _category(jane, "Alumni fund", taxTag="charitable")
    raffle = _category(jane, "Raffle tickets", parentId=giving_id)  # no tag: not a gift
    add(jane, bank["id"], "-300.00", "2026-02-01", payee="St. Mark's", categoryId=church)
    add(jane, bank["id"], "-50.00", "2026-03-01", payee="State U", categoryId=alumni)
    add(jane, bank["id"], "-20.00", "2026-03-02", payee="PTA", categoryId=raffle)
    auction = add(
        jane,
        bank["id"],
        "-120.00",
        "2026-04-01",
        payee="Food Bank gala",
        splits=[
            {"categoryId": giving_id, "amount": "-80.00"},
            {"categoryId": _cat(jane, "Dining out"), "amount": "-40.00"},
        ],
    )
    rows = jane.get("/ui/api/giving/donations").json()["items"]
    assert [(d["name"], d["amount"], d["transactionId"]) for d in rows] == [
        ("Food Bank gala", "80.00", auction["id"]),
        ("State U", "50.00", rows[1]["transactionId"]),
        ("St. Mark's", "300.00", rows[2]["transactionId"]),
    ]
    assert jane.get("/ui/api/giving").json()["given"] == "430.00"
    # Recorded, the split part is the donation, and the transaction keeps its parts.
    food = org(jane, "Food Bank")
    d = donate(
        jane,
        date="2026-04-01",
        kind="cash",
        organisationId=food["id"],
        transactionId=auction["id"],
        amount="80",
    )
    assert d["amount"] == "80.00"
    t = jane.get(f"/ui/api/transactions/{auction['id']}").json()
    assert t["categoryId"] is None and len(t["splits"]) == 2
    rows = jane.get("/ui/api/giving/donations").json()["items"]
    assert [x["id"] for x in rows if x["transactionId"] == auction["id"]] == [d["id"]]
    assert jane.get("/ui/api/giving").json()["given"] == "430.00"


def test_a_pledge_without_the_period_it_was_set_in_is_refused_by_the_database(server):
    """S7.9.5: what is due is counted from the period a pledge was set in, so the database
    refuses a pledge without it, and the alerts never meet one."""
    from sqlalchemy.exc import IntegrityError

    from moolakata import ids
    from moolakata.store.entities.giving import Organisation

    owner = make_user(server, "joan").id
    with pytest.raises(IntegrityError), server.db.tx(unscoped="test") as s:
        s.add(
            Organisation(
                id=ids.new_id("Orgzn"), ownerId=owner, name="Food Bank", pledge=25,
                pledgeEvery="month",
            )
        )  # fmt: skip
