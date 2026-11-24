"""Charitable giving at its edges (requirements S7.9): each refusal of a plan, an
organisation and a donation at its field with its code and words, shares valued at the day's
price, shares into a fund, and the pace of a year past or to come."""

import pytest
from conftest import make_user, sign_in
from edits import _save, change, create, giving_plan, make, new_id, remove, saved, share
from test_accounts import add, new_account
from test_giving import T0, _cat, org

from moolakata import clock


@pytest.fixture
def jane(server):
    clock.fix(T0)
    make_user(server, "jane")
    yield sign_in(server, "jane")
    clock.fix(None)


def refused(r, field, code, words, status=422):
    assert r.status_code == status, r.text
    e = r.json()["errors"][0]
    assert (e["field"], e["code"], e["message"]) == (field, code, words)


def made(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def _john(server):
    make_user(server, "john")
    john = sign_in(server, "john")
    return john, john.get("/ui/api/session").json()["user"]["id"]


def _new_plan(c, **fields):
    op = {"op": "create", "entity": "GvPln", "id": new_id("GvPln"), "fields": fields}
    return _save(c, op, False)


# ---- The plan (S7.9.1, S7.9.2) ----


@pytest.mark.parametrize(
    ("fields", "field", "code", "words"),
    [
        ({"targetKind": "share"}, "targetKind", "target-invalid", "A percentage or an amount."),
        ({"percent": "0"}, "percent", "percent-invalid", "Between 0% and 100%."),
        ({"percent": "100.01"}, "percent", "percent-invalid", "Between 0% and 100%."),
        ({"percent": None}, "percent", "percent-invalid", "Between 0% and 100%."),
        ({"targetKind": "amount"}, "amount", "amount-invalid", "More than zero."),
        ({"targetKind": "amount", "amount": "0"}, "amount", "amount-invalid", "More than zero."),
        ({"incomeBasis": "net"}, "incomeBasis", "basis-invalid", "Take-home, gross or AGI."),
        ({"incomeBasis": "agi"}, "income", "income-missing", "The income, typed."),
        (
            {"incomeBasis": "gross", "income": "0"},
            "income",
            "income-missing",
            "The income, typed.",
        ),
        ({"dafCounted": "never"}, "dafCounted", "daf-invalid", "When funded, or when it grants."),
    ],
)
def test_a_giving_plans_target_and_income_are_refused_at_their_field(
    jane, fields, field, code, words
):
    refused(_new_plan(jane, year=2026, **fields), field, code, words)


def test_a_plan_refuses_every_field_wrong_at_once_and_takes_its_edges(jane):
    r = _new_plan(jane, year=2026, targetKind="amount", incomeBasis="gross", dafCounted="x")
    assert [e["field"] for e in r.json()["errors"]] == ["amount", "income", "dafCounted"]
    p = saved(_new_plan(jane, year=2026, percent="100"))
    assert p["percent"] == "100.00"


def test_a_year_has_one_plan_which_keeps_its_year(jane):
    p = saved(giving_plan(jane, 2026, percent="10"))
    refused(_new_plan(jane, year=2026), "year", "plan-exists",
            "This year has its plan; change it.", 409)  # fmt: skip
    refused(change(jane, "GvPln", p, year=2027), "year", "plan-fixed", "A plan keeps its year.")
    ghost = {**p, "id": new_id("GvPln")}
    refused(change(jane, "GvPln", ghost, percent="5"), None, "not-found", "Not found", 404)


def test_a_plan_shared_to_read_is_not_changed(server, jane):
    john, john_id = _john(server)
    p = saved(giving_plan(jane, 2026, percent="10"))
    share(jane, "giving-plan", p["id"], users={john_id: "read"})
    refused(change(john, "GvPln", p, percent="1"), None, "read-only",
            "This plan is shared with you to read.", 403)  # fmt: skip
    assert jane.get("/ui/api/giving").json()["plan"]["percent"] == "10.00"


def test_the_pace_of_a_year_past_is_its_target_and_of_one_to_come_nothing(jane):
    """S7.9.6: the even pace runs through the year; a past year's is the whole target, a
    future year's nothing yet."""
    for year in (2025, 2027):
        saved(giving_plan(jane, year, targetKind="amount", amount="1200"))
    assert jane.get("/ui/api/giving", params={"year": 2025}).json()["pace"] == "1200.00"
    assert jane.get("/ui/api/giving", params={"year": 2027}).json()["pace"] == "0.00"


def test_a_plan_chosen_that_isnt_there_is_not_found(jane):
    r = jane.get("/ui/api/giving", params={"plan": new_id("GvPln")})
    assert (r.status_code, r.json()["code"]) == (404, "not-found")


# ---- Organisations (S7.9.5) ----


@pytest.mark.parametrize(
    ("fields", "field", "code", "words"),
    [
        ({"name": "  "}, "name", "name-missing", "The organisation's name."),
        ({"ein": "36-21670"}, "ein", "ein-invalid", "Nine digits, such as 36-2167053."),
        ({"ein": "36-216705X"}, "ein", "ein-invalid", "Nine digits, such as 36-2167053."),
        ({"pledge": "-1"}, "pledge", "amount-invalid", "Zero or more."),
        ({"pledge": "25"}, "pledgeEvery", "every-invalid", "A month or a year."),
        (
            {"pledge": "25", "pledgeEvery": "week"},
            "pledgeEvery",
            "every-invalid",
            "A month or a year.",
        ),
    ],
)
def test_an_organisations_name_ein_and_pledge_are_refused_at_their_field(
    jane, fields, field, code, words
):
    refused(make(jane, "Orgzn", **{"name": "Food Bank", **fields}), field, code, words)


def test_an_organisation_keeps_its_ein_causes_and_pledge_tidy(jane):
    o = org(jane, " Food Bank ", ein="362167053", causes=["Hunger", " ", "Hunger "],
            pledge="0", pledgeEvery="month")  # fmt: skip
    assert (o["name"], o["ein"], o["causes"], o["pledge"], o["pledgeEvery"]) == (
        "Food Bank",
        "362167053",
        ["Hunger"],
        None,
        None,
    )
    refused(change(jane, "Orgzn", o, name=""), "name", "name-missing",
            "The organisation's name.")  # fmt: skip


# ---- Donations (S7.9.3) ----


@pytest.mark.parametrize(
    ("fields", "field", "code", "words"),
    [
        ({"kind": "barter"}, "kind", "kind-invalid", "One of the kinds of donation."),
        (
            {"organisationId": None},
            "organisationId",
            "organisation-missing",
            "Who it was given to.",
        ),
        ({"kind": "daf-grant"}, "dafAccountId", "fund-missing", "The donor-advised fund."),
        ({"amount": "0"}, "amount", "amount-invalid", "More than zero."),
        ({"amount": None}, "amount", "amount-invalid", "More than zero."),
        (
            {"kind": "goods", "description": " "},
            "description",
            "description-missing",
            "What was given.",
        ),
    ],
)
def test_a_donations_kind_organisation_fund_amount_and_goods_are_refused(
    jane, fields, field, code, words
):
    food = org(jane, "Food Bank")
    body = {"date": "2026-04-01", "kind": "cash", "organisationId": food["id"], "amount": "50"}
    refused(make(jane, "Dnatn", **{**body, **fields}), field, code, words)


def test_a_donation_names_a_fund_an_organisation_and_a_transaction_that_are_there(server, jane):
    john, _ = _john(server)
    food = org(jane, "Food Bank")
    his = org(john, "His shelter")
    bank = new_account(jane, name="Checking")
    cash = {"date": "2026-04-01", "kind": "cash", "organisationId": food["id"], "amount": "50"}
    refused(make(jane, "Dnatn", **{**cash, "kind": "daf-grant", "dafAccountId": bank["id"]}),
            "dafAccountId", "not-a-fund", "Choose a donor-advised fund.")  # fmt: skip
    refused(make(jane, "Dnatn", **{**cash, "organisationId": his["id"]}), "organisationId",
            "organisation-unknown", "Choose an organisation.")  # fmt: skip
    gone = add(jane, bank["id"], "-50.00", "2026-04-01")
    assert remove(jane, "Txn", gone).status_code == 200
    for missing in (gone["id"], new_id("Txn")):
        refused(make(jane, "Dnatn", **cash, transactionId=missing), "transactionId",
                "not-found", "No such transaction.")  # fmt: skip
    refused(make(jane, "Dnatn", **cash, planId=new_id("GvPln")), "planId", "not-found",
            "Not found", 404)  # fmt: skip


def test_an_uncategorised_transaction_recorded_as_cash_is_filed_under_giving(jane):
    """S7.9.3, S7.3.1: what the donation records counts once, in Giving."""
    food = org(jane, "Food Bank")
    bank = new_account(jane, name="Checking")
    t = add(jane, bank["id"], "-75.00", "2026-04-01", payee="Food Bank")
    d = made(make(jane, "Dnatn", date="2026-04-01", kind="cash", organisationId=food["id"],
                  transactionId=t["id"]))  # fmt: skip
    assert d["amount"] == "75.00" and d["transactionId"] == t["id"]
    assert jane.get(f"/ui/api/transactions/{t['id']}").json()["categoryId"] == _cat(jane, "Giving")
    assert jane.get("/ui/api/giving").json()["given"] == "75.00"


def _brokerage(c):
    brk = new_account(c, name="Brokerage", type="brokerage")
    bought = add(c, brk["id"], "-1000.00", "2024-01-05", kind="buy", symbol="VTI",
                 quantity="10", price="100")  # fmt: skip
    lot = c.get(f"/ui/api/accounts/{brk['id']}/holdings").json()["holdings"][0]["lots"][0]
    return brk, {**lot, "instrumentId": bought["instrumentId"]}


def test_shares_given_without_an_amount_are_valued_at_that_days_price(jane):
    """S7.9.3, S4.7: left out, the shares' market value is the owner's price for the day
    times the shares; on a day no price is known, the amount is asked for."""
    food = org(jane, "Food Bank")
    brk, lot = _brokerage(jane)
    saved(create(jane, "TyPrc", instrumentId=lot["instrumentId"], date="2026-09-30",
                 close="331.50"))  # fmt: skip
    shares = {"kind": "securities", "organisationId": food["id"], "fromAccountId": brk["id"],
              "lotId": lot["lotId"], "quantity": "2"}  # fmt: skip
    d = made(make(jane, "Dnatn", date="2026-10-01", **shares))
    assert d["amount"] == "663.00" and d["longTerm"] and d["basis"] == "200.00"
    refused(make(jane, "Dnatn", date="2024-01-04", **shares), "amount", "value-missing",
            "The shares' market value on the day.")  # fmt: skip


def test_shares_come_from_a_lot_in_the_account_named(jane):
    food = org(jane, "Food Bank")
    _brk, lot = _brokerage(jane)
    other = new_account(jane, name="Other brokerage", type="brokerage")
    refused(make(jane, "Dnatn", date="2026-10-01", kind="securities", organisationId=food["id"],
                 fromAccountId=other["id"], lotId=lot["lotId"], quantity="1", amount="300"),
            "lotId", "lot-unknown", "Choose a lot in that account.")  # fmt: skip


def test_shares_into_a_fund_leave_the_lot_and_arrive_with_its_basis(jane):
    """S7.9.3: a donor-advised fund funded with shares holds them from their purchase, at
    their basis; the contribution is counted once, at its market value."""
    saved(giving_plan(jane, 2026, targetKind="amount", amount="5000"))
    fund = new_account(jane, name="Giving fund", type="daf", institution="Fidelity Charitable")
    brk, lot = _brokerage(jane)
    d = made(make(jane, "Dnatn", date="2026-10-01", kind="daf-contribution",
                  dafAccountId=fund["id"], fromAccountId=brk["id"], lotId=lot["lotId"],
                  quantity="4", amount="1320"))  # fmt: skip
    assert d["amount"] == "1320.00" and d["basis"] == "400.00" and d["counted"]
    held = jane.get(f"/ui/api/accounts/{fund['id']}/holdings").json()["holdings"][0]
    assert (held["quantity"], [x["acquiredOn"] for x in held["lots"]]) == ("4.0", ["2024-01-05"])
    assert held["lots"][0]["basis"] == "400.00"
    left = jane.get(f"/ui/api/accounts/{brk['id']}/holdings").json()["holdings"][0]
    assert left["quantity"] == "6.0"
    assert jane.get("/ui/api/giving").json()["given"] == "1320.00"


def test_a_donation_made_with_its_acknowledgement_and_a_grant_paid_later(jane):
    """S7.9.2: the acknowledgement's file, kept as it is recorded, marks it received; a
    grant's paid tick is changed after the fact; a file taken away leaves it received."""
    food = org(jane, "Food Bank")
    fund = new_account(jane, name="Giving fund", type="daf")
    rid = jane.post(
        "/ui/api/receipts", files={"file": ("ack.pdf", b"%PDF-1.4 thanks", "application/pdf")}
    ).json()["id"]
    g = made(make(jane, "Dnatn", date="2026-04-01", kind="daf-grant", organisationId=food["id"],
                  dafAccountId=fund["id"], amount="300", granted=False,
                  receiptIds=[rid]))  # fmt: skip
    assert g["granted"] is False
    g = saved(change(jane, "Dnatn", g, granted=True))
    assert g["granted"] is True
    g = saved(change(jane, "Dnatn", g, receiptIds={"add": [], "remove": [rid]}, acknowledged=True))
    assert g["acknowledged"]


def test_only_an_item_over_5000_needs_an_appraisal(jane):
    """S8.9: goods over $500 in the year need Form 8283; each item over $5,000 an appraisal."""
    shop = org(jane, "Goodwill")
    for amount, what in (("6000", "A piano"), ("400", "Two bags of clothes")):
        made(make(jane, "Dnatn", date="2026-05-01", kind="goods", organisationId=shop["id"],
                  amount=amount, description=what))  # fmt: skip
    notes = jane.get("/ui/api/giving").json()["notes"]
    assert [n for n in notes if "appraisal" in n] == [
        "A piano to Goodwill is over $5,000: it needs a qualified appraisal."
    ]
    assert any("Form 8283" in n for n in notes)
