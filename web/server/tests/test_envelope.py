"""Envelope budgets (requirements S7.13): To Budget, card payment lines, owed not backed, and
what an overspent envelope does at the month's end."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import budget_accounts, make
from test_accounts import add, new_account
from test_budgets import cats, month, plan, row
from test_reserves import landed, put_plan, reserves_on

from moolakata import clock

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def test_to_budget_card_lines_and_owed_not_backed(server, frozen):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    cat = cats(c)
    r = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"], card["id"]])
    b = r.json()
    food, fun = cat["Food"], cat["Entertainment"]
    add(c, chk["id"], "3000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    plan(
        c,
        b,
        "2026-10-01",
        [
            {"categoryId": food, "amount": "500.00"},
            {"categoryId": fun, "amount": "200.00", "overspend": "next"},
        ],
    )

    def view():
        return month(c, b, "2026-10")

    v = view()
    assert (v["toBudget"], v["assigned"]) == ("2300.00", "700.00")
    # Cash spent comes out of the envelope and the cash alike: To Budget doesn't move.
    add(c, chk["id"], "-100.00", "2026-10-03", payee="Kroger", categoryId=cat["Food › Groceries"])
    assert view()["toBudget"] == "2300.00"
    # A charge to the card moves the money from the envelope to the card's payment line.
    add(
        c,
        card["id"],
        "-150.00",
        "2026-10-04",
        payee="Whole Foods",
        categoryId=cat["Food › Groceries"],
    )
    v = view()
    assert v["toBudget"] == "2300.00" and row(v, "Food")["remaining"] == "250.00"
    (line,) = v["cards"]
    assert (line["setAside"], line["owed"], line["notBacked"]) == ("150.00", "150.00", "0.00")
    # Beyond what the envelope held: the envelope stops at nothing, the rest is owed, not backed.
    add(c, card["id"], "-260.00", "2026-10-05", payee="Concert", categoryId=cat["Entertainment"])
    v = view()
    assert row(v, "Entertainment")["remaining"] == "0.00" and v["toBudget"] == "2300.00"
    (line,) = v["cards"]
    assert (line["setAside"], line["owed"], line["notBacked"]) == ("350.00", "410.00", "60.00")
    # The Spent card counts it as spent and names it (S7.3.12): every dollar of the month's
    # spending, $100 + $150 + $260, against $700 available.
    assert row(v, "Entertainment")["unbacked"] == "60.00"
    assert (v["available"], v["left"], v["unbacked"]) == ("700.00", "190.00", "60.00")
    card_ = c.get("/ui/api/dashboard").json()["budget"]
    assert (card_["spent"], card_["left"], card_["unbacked"]) == ("510.00", "190.00", "60.00")
    # A payment to the card takes from its line, cash and line alike.
    add(c, chk["id"], "-300.00", "2026-10-10", payee="Visa payment")
    add(c, card["id"], "300.00", "2026-10-10", payee="Thank you", kind="deposit")
    v = view()
    (line,) = v["cards"]
    assert (v["toBudget"], line["setAside"], line["notBacked"]) == ("2300.00", "50.00", "60.00")
    # A move from To Budget covers the debt, and another adds to an envelope.
    for body in ({"cardId": card["id"]}, {"toCategoryId": food}):
        r = make(
            c, "BdgMv", **{"budgetId": b["id"], **{"month": "2026-10-01", "amount": "60.00"} | body}
        )
        assert r.status_code == 200, r.text
    v = view()
    (line,) = v["cards"]
    assert (v["toBudget"], v["assignedByMoves"], line["notBacked"]) == ("2180.00", "120.00", "0.00")
    assert row(v, "Food")["remaining"] == "310.00"
    assert {m["toLabel"] for m in v["moves"]} == {"Food", "Visa's payment"}


def test_an_overspent_envelope_carried_or_taken_from_next_month(server, frozen):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)
    cat = cats(c)
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"]]).json()
    food, fun = cat["Food"], cat["Entertainment"]
    add(c, chk["id"], "2000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    plan(
        c,
        b,
        "2026-10-01",
        [
            {"categoryId": food, "amount": "300.00"},
            {"categoryId": fun, "amount": "100.00", "overspend": "next"},
        ],
    )
    add(c, chk["id"], "-340.00", "2026-10-03", payee="Kroger", categoryId=cat["Food › Groceries"])
    add(c, chk["id"], "-130.00", "2026-10-04", payee="Concert", categoryId=fun)
    oct_ = month(c, b, "2026-10")
    assert (
        row(oct_, "Food")["state"] == "over" and row(oct_, "Entertainment")["remaining"] == "-30.00"
    )
    nov = month(c, b, "2026-11")
    # Carried negative: November starts 40 short. Taken from next month: it starts at nothing.
    assert row(nov, "Food")["carried"] == "-40.00"
    assert row(nov, "Entertainment")["carried"] == "0.00"
    # So November's To Budget is what is left after the shortfall: 1530 cash, less 260 and 100.
    assert nov["toBudget"] == "1170.00"
    bad = make(c, "BdgMv", budgetId=b["id"], month="2026-10-01", amount="5", cardId=chk["id"])
    assert bad.status_code == 422


def test_landed_money_given_to_a_reserve_comes_out_of_to_budget(server, frozen):
    """Money given to a reserve is a move into it (S7.10.5): its envelope gains it and To
    Budget, whose cash it already raised, loses it; what is kept as the account's own moves
    nothing (S7.13.1)."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)
    ally = new_account(c, name="Ally", type="savings", mask="2222")
    cat = cats(c)
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"]]).json()
    assert budget_accounts(c, b, [chk["id"], ally["id"]]).status_code == 200
    reserves_on(c, b)
    repair = cat["Transportation › Car maintenance"]
    line = {"categoryId": repair, "amount": "100", "target": "1000", "heldInId": ally["id"]}
    assert put_plan(c, b, "2026-10-01", [line]).status_code == 200
    add(c, chk["id"], "3000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    interest = add(c, ally["id"], "40.00", "2026-10-03", payee="Interest", kind="interest")
    v = month(c, b, "2026-10")
    label = "Transportation › Car maintenance"
    assert (v["toBudget"], row(v, label)["balance"]) == ("2940.00", "100.00")
    assert landed(c, b, interest, {repair: "30.00", None: "10.00"}).status_code == 200
    v = month(c, b, "2026-10")
    r = row(v, label)
    assert (v["toBudget"], v["assignedByMoves"]) == ("2910.00", "30.00")
    assert (r["moved"], r["balance"]) == ("30.00", "130.00")


def test_a_reserves_envelope_keeps_its_money_when_the_target_comes_off(server, frozen):
    """In an envelope budget the balance is money set aside: taking a reserve's target off
    asks, saying the money stays in the envelope, now an ordinary line (S7.10.3, S7.13.3)."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)
    cat = cats(c)
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"]]).json()
    reserves_on(c, b)
    add(c, chk["id"], "3000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    repair = cat["Transportation › Car maintenance"]
    line = {"categoryId": repair, "amount": "100", "target": "1000"}
    assert put_plan(c, b, "2026-10-01", [line]).status_code == 200
    plain = {"categoryId": repair, "amount": "100"}
    r = put_plan(c, b, "2026-11-01", [plain])
    assert r.status_code == 409
    assert r.json()["asks"][0]["message"] == (
        "Transportation › Car maintenance holds 100.00: it stays in the envelope."
    )
    assert put_plan(c, b, "2026-11-01", [plain], confirm=True).status_code == 200
    r = row(month(c, b, "2026-11"), "Transportation › Car maintenance")
    assert (r["carried"], r["remaining"], r["target"]) == ("100.00", "200.00", None)


def test_turning_reserves_off_leaves_the_money_in_the_envelopes(server, frozen):
    """Turning reserves off takes every target off from this month; in an envelope budget the
    balances stay in the envelopes (S7.1.4, S7.10.3)."""
    from edits import edit

    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)
    cat = cats(c)
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"]]).json()
    reserves_on(c, b)
    add(c, chk["id"], "3000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    repair = cat["Transportation › Car maintenance"]
    line = {"categoryId": repair, "amount": "100", "target": "1000"}
    assert put_plan(c, b, "2026-10-01", [line]).status_code == 200
    clock.fix(T0 + dt.timedelta(days=12))  # November 1st
    c = sign_in(server, "jane")
    path = f"/ui/api/budgets/{b['id']}"
    r = edit(c, "Bdgt", path, reserves=False)
    assert r.status_code == 409 and r.json()["asks"][0]["message"] == (
        "Every target comes off from November 2026: Transportation › Car maintenance holds 100.00;"
        " the balances stay in their envelopes."
    )
    assert edit(c, "Bdgt", path, True, reserves=False).status_code == 200
    r = row(month(c, b, "2026-11"), "Transportation › Car maintenance")
    assert (r["carried"], r["target"]) == ("100.00", None)


def test_gifts_and_giving_are_assigned_as_yearly_lines(server, frozen):
    """S7.3.6, S7.13.1: the gift and giving plans' yearly amounts are envelopes assigned a
    twelfth a month, so To Budget sets their money aside and their spending comes out of them."""
    from edits import giving_plan

    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)
    cat = cats(c)
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"]]).json()
    assert make(c, "GfPln", name="Emma Doe", sex="female", giftBudget="1200").status_code == 200
    assert giving_plan(c, 2026, targetKind="amount", amount="600").status_code == 200
    add(c, chk["id"], "3000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    plan(c, b, "2026-10-01", [{"categoryId": cat["Food"], "amount": "500.00"}])
    v = month(c, b, "2026-10")
    gifts = row(v, "Gifts")
    assert v["toBudget"] == "2350.00"
    assert (gifts["planned"], gifts["putIn"], gifts["fromPlan"]) == ("100.00", "100.00", "gifts")
    assert row(v, "Giving")["planned"] == "50.00"
    add(c, chk["id"], "-100.00", "2026-10-05", payee="Toy store", categoryId=cat["Gifts"])
    v = month(c, b, "2026-10")
    assert (v["toBudget"], row(v, "Gifts")["remaining"]) == ("2350.00", "0.00")
    # November's twelfth comes on top of what October's envelope kept.
    assert row(month(c, b, "2026-11"), "Giving")["planned"] == "100.00"


NOT_SHARED = "an account not shared"


def _household(server):
    """Jane's envelope budget counts her Checking, her Chase Sapphire card and her Ally Savings,
    where the roof's reserve is held and $40 of interest has landed, and chooses Ally as where
    Checking's money moves from; Bob follows it at write and reads only Checking (S7.1.1)."""
    from edits import change, saved, share

    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)
    card = new_account(c, name="Chase Sapphire", type="credit-card", mask="1111")
    ally = new_account(c, name="Ally Savings", type="savings", mask="2222")
    cat = cats(c)
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"]]).json()
    roles = {chk["id"]: {"movedFromId": ally["id"]}}
    assert budget_accounts(c, b, [chk["id"], card["id"], ally["id"]], roles=roles).is_success
    reserves_on(c, b)
    roof = cat["Housing › Maintenance"]
    lines = [
        {"categoryId": cat["Food"], "amount": "500.00"},
        {"categoryId": roof, "amount": "150.00", "target": "5000", "heldInId": ally["id"]},
    ]
    assert put_plan(c, b, "2026-10-01", lines).status_code == 200
    add(c, chk["id"], "3000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    add(c, card["id"], "-150.00", "2026-10-04", payee="Whole Foods", categoryId=cat["Food"])
    add(c, ally["id"], "40.00", "2026-10-03", payee="Interest", kind="interest")
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    share(c, "budget", b["id"], users={bob_id: "write"})
    share(c, "account", chk["id"], users={bob_id: "read"})
    saved(change(bob, "User", bob.get("/ui/api/profile").json(), activeBudgetId=b["id"]))
    return c, bob, b, cat, card, ally


def _unnamed(text: str, *hidden: dict) -> None:
    for a in hidden:
        assert a["id"] not in text and a["name"] not in text


def test_a_receiver_sees_the_owners_figures_but_no_account_not_shared_with_them(server, frozen):
    """S7.1.1, S11.3.1: Bob's month counts Jane's card and her Ally Savings as hers does, spent,
    To Budget and the reserve alike, but names neither, nor gives either's id: not as the
    card's payment line, nor in a move into it, nor where the reserve is held; and his change
    to the reserve's line keeps where it is held."""
    from edits import new_id

    c, bob, b, cat, card, ally = _household(server)
    roof = cat["Housing › Maintenance"]
    fields = {"budgetId": b["id"], "month": "2026-10-01", "cardId": card["id"], "amount": "10.00"}
    op = {"op": "create", "entity": "BdgMv", "id": new_id("BdgMv"), "fields": fields}
    r = c.post("/ui/api/save", json={"ops": [op]})
    assert r.status_code == 200, r.text
    mine, theirs = month(c, b, "2026-10"), month(bob, b, "2026-10")
    totals = ("spent", "income", "toBudget", "assigned", "assignedByMoves", "available", "left")
    assert mine["spent"] == "150.00"
    assert [theirs[k] for k in totals] == [mine[k] for k in totals]
    assert [{**x, "heldInId": None} for x in mine["rows"]] == theirs["rows"]
    assert row(mine, "Housing › Maintenance")["heldInId"] == ally["id"]
    assert [(x["accountId"], x["name"]) for x in mine["cards"]] == [(card["id"], card["name"])]
    assert [(x["accountId"], x["name"]) for x in theirs["cards"]] == [(None, NOT_SHARED)]
    figures = ("setAside", "owed", "paid", "notBacked")
    assert [[x[k] for k in figures] for x in theirs["cards"]] == [
        [x[k] for k in figures] for x in mine["cards"]
    ]
    assert [x["toLabel"] for x in mine["moves"]] == ["Chase Sapphire's payment"]
    assert [x["toLabel"] for x in theirs["moves"]] == [f"the payment of {NOT_SHARED}"]
    plan_path = f"/ui/api/budgets/{b['id']}/plan"
    lines = bob.get(plan_path, params={"month": "2026-10"}).json()["lines"]
    assert [x["heldInId"] for x in lines] == [None, None]
    _unnamed(str(theirs) + str(lines), card, ally)
    # Bob's draft sends only what he changed: the reserve stays held in Ally.
    (line,) = [x for x in lines if x["categoryId"] == roof]
    op = {"op": "update", "entity": "BdgLn", "id": line["id"], "version": line["version"],
          "fields": {"amount": "175.00"}}  # fmt: skip
    r = bob.post("/ui/api/save", json={"ops": [op]})
    assert r.status_code == 200, r.text
    lines = c.get(plan_path, params={"month": "2026-10"}).json()["lines"]
    assert [(x["amount"], x["heldInId"]) for x in lines if x["categoryId"] == roof] == [
        ("175.00", ally["id"])
    ]


def test_where_the_money_is_names_no_account_not_shared_with_the_receiver(server, frozen):
    """S7.1.1, S7.10.4: Bob's Where the money is holds the reserve in Ally Savings, with the
    interest landed there, and the card's payments, as Jane's does, each account not shared
    with him unnamed and without its id."""
    c, bob, b, _, card, ally = _household(server)
    path = f"/ui/api/budgets/{b['id']}/where"
    mine = c.get(path, params={"month": "2026-10"}).json()
    theirs = bob.get(path, params={"month": "2026-10"}).json()
    assert [(h["accountId"], h["accountName"]) for h in mine["heldIn"]] == [
        (ally["id"], ally["name"])
    ]
    assert [(h["accountId"], h["accountName"]) for h in theirs["heldIn"]] == [(None, NOT_SHARED)]
    kept = ("reserves", "total", "movedIn", "given", "balance", "toMove")
    assert [[h[k] for k in kept] for h in theirs["heldIn"]] == [
        [h[k] for k in kept] for h in mine["heldIn"]
    ]
    assert [x["free"] for x in theirs["heldIn"][0]["unassigned"]] == ["40.00"]
    assert [(x["accountId"], x["accountName"]) for x in theirs["cards"]] == [(None, NOT_SHARED)]
    assert [x["owed"] for x in theirs["cards"]] == [x["owed"] for x in mine["cards"]] == ["150.00"]
    _unnamed(str(theirs), card, ally)
    # Nor do the budget and its accounts name Ally as where Checking's money moves from.
    base = f"/ui/api/budgets/{b['id']}"
    mine, theirs = c.get(base).json(), bob.get(base).json()
    assert ally["id"] in [r["movedFromId"] for r in mine["roles"]]
    _unnamed(str(theirs) + bob.get(f"{base}/accounts").text, card, ally)


def test_a_receiver_sees_the_amounts_of_an_account_not_shared_but_not_its_transactions(
    server, frozen
):
    """S7.1.1: money landed in Ally, moved in from Checking, and sent between Ally and Jane's
    brokerage with no category reaches Bob's month and Where the money is as amounts only,
    each list's rows from Ally added into one row (left and entered apart, kept and moved in
    apart) with no payee, date or transaction id; his own Checking's rows keep theirs, and
    the totals are Jane's."""
    c, bob, b, _, card, ally = _household(server)
    chk = b["accountIds"][0]
    brokerage = new_account(c, name="Fidelity", type="brokerage", mask="3333")
    hidden = [add(c, ally["id"], "5.00", "2026-10-08", payee="Cash-back", kind="interest")]
    for day, amount in (("2026-10-02", "100.00"), ("2026-10-09", "50.00")):
        out = add(c, chk, f"-{amount}", day, payee="To Ally")
        hidden.append(add(c, ally["id"], amount, day, payee="From checking", kind="deposit"))
        assert hidden[-1]["transferId"] == out["id"]
    for day, amount, back in (
        ("2026-10-10", "-200.00", "200.00"),
        ("2026-10-12", "-100.00", "100.00"),
        ("2026-10-14", "60.00", "-60.00"),
    ):
        hidden.append(add(c, ally["id"], amount, day, payee="Fidelity sweep"))
        kind = "deposit" if back[0] != "-" else "withdrawal"
        pair = add(c, brokerage["id"], back, day, payee="Sweep", kind=kind)
        assert pair["transferId"] == hidden[-1]["id"]
    out = add(c, chk, "-25.00", "2026-10-11", payee="To Fidelity")
    add(c, brokerage["id"], "25.00", "2026-10-11", payee="From checking", kind="deposit")
    mine, theirs = month(c, b, "2026-10"), month(bob, b, "2026-10")
    assert [x["amount"] for x in mine["moved"]] == ["-200.00", "-25.00", "-100.00", "60.00"]
    # Each added row stands where its first one did.
    assert theirs["moved"] == [
        {"transactionId": None, "date": None, "accountName": NOT_SHARED,
         "otherAccountName": None, "amount": "-300.00", "payee": None},
        {"transactionId": out["id"], "date": "2026-10-11", "accountName": "Checking",
         "otherAccountName": NOT_SHARED, "amount": "-25.00", "payee": "To Fidelity"},
        {"transactionId": None, "date": None, "accountName": NOT_SHARED,
         "otherAccountName": None, "amount": "60.00", "payee": None},
    ]  # fmt: skip
    totals = ("spent", "income", "saved", "toBudget", "available")
    assert [theirs[k] for k in totals] == [mine[k] for k in totals]
    path = f"/ui/api/budgets/{b['id']}/where"
    (h,) = c.get(path, params={"month": "2026-10"}).json()["heldIn"]
    (theirs_h,) = bob.get(path, params={"month": "2026-10"}).json()["heldIn"]
    # What entered from the brokerage landed in Ally too.
    assert [x["free"] for x in h["unassigned"]] == ["40.00", "5.00", "60.00"]
    assert theirs_h["unassigned"] == [
        {"transactionId": None, "date": None, "payee": None, "amount": "105.00", "free": "105.00"}
    ]
    assert [x["amount"] for x in h["transfers"]] == ["100.00", "50.00"]
    assert theirs_h["transfers"] == [
        {"transactionId": None, "date": None, "payee": None, "amount": "150.00", "kept": False}
    ]
    kept = ("total", "movedIn", "given", "balance", "toMove")
    assert [theirs_h[k] for k in kept] == [h[k] for k in kept]
    text = str(theirs) + str(theirs_h)
    for t in hidden:
        assert t["id"] not in text and t["payee"] not in text
    assert "Interest" not in text
    _unnamed(text, card, ally)


def test_a_receivers_other_views_count_the_owners_accounts_not_shared_with_them(server, frozen):
    """S7.1.1: Bob's review, its loose ends and what changed since Jane reviewed it, his
    dashboard's budget card, cash flow, trends, a comparison and an estimate count Jane's card
    and Ally Savings as hers do, and name neither."""
    c, bob, b, cat, card, ally = _household(server)
    base = f"/ui/api/budgets/{b['id']}"
    assert c.post(f"{base}/review", json={"month": "2026-10-01"}).is_success
    add(c, card["id"], "-20.00", "2026-10-06", payee="Bistro", categoryId=cat["Food"])

    def review(who):
        return who.get(f"{base}/review", params={"month": "2026-10"}).json()

    mine, theirs = review(c), review(bob)
    assert mine["reviewed"]["changes"][0] == "Food: spent 150.00 then, 170.00 now"
    assert theirs["reviewed"]["changes"] == mine["reviewed"]["changes"]
    assert [x["over"] for x in theirs["overspent"]] == [x["over"] for x in mine["overspent"]]
    assert theirs["toBudget"] == mine["toBudget"]
    assert [x["toMove"] for x in theirs["toMove"]] == [x["toMove"] for x in mine["toMove"]]
    assert {x["accountName"] for x in mine["toMove"]} == {ally["name"]}
    assert {x["accountName"] for x in theirs["toMove"]} == {NOT_SHARED}
    _unnamed(str(theirs), card, ally)
    card_ = c.get("/ui/api/dashboard").json()["budget"]
    assert bob.get("/ui/api/dashboard").json()["budget"] == card_
    assert card_["spent"] == "170.00"
    for path, params in (
        ("cash-flow", {"month": "2026-10"}),
        ("trends", {"month": "2026-10"}),
        ("compare", {"other": b["id"], "month": "2026-10"}),
        ("estimate", {}),
    ):
        got = [who.get(f"{base}/{path}", params=params) for who in (c, bob)]
        assert all(r.status_code == 200 for r in got), [r.text for r in got]
        assert got[1].json() == got[0].json(), path


def test_a_transfer_between_the_budgets_accounts_comes_out_of_no_envelope(server, frozen):
    """S7.3.2, S7.1.2: $80 from the Visa to Checking, both counted, moves no money in or out,
    whatever its category: no envelope spends it and the card's line sets nothing aside."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    cat = cats(c)
    b = make(c, "Bdgt", name="Envelopes", method="envelope", accountIds=[chk["id"], card["id"]])
    b = b.json()
    add(c, chk["id"], "3000.00", "2026-10-01", payee="Payroll", categoryId=cat["Income › Salary"])
    plan(c, b, "2026-10-01", [{"categoryId": cat["Food"], "amount": "500.00"}])
    out = add(c, card["id"], "-80.00", "2026-10-05", payee="Cash advance", categoryId=cat["Food"])
    back = add(c, chk["id"], "80.00", "2026-10-05", payee="From Visa", kind="deposit")
    assert back["transferId"] == out["id"]
    v = month(c, b, "2026-10")
    assert (v["spent"], row(v, "Food")["actual"]) == ("0.00", "0.00")
    assert [x["setAside"] for x in v["cards"]] == ["0.00"]
