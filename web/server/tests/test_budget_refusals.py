"""What a budget's routes and records refuse, each at its field with its code and words, and
what they find no record of (requirements S7.1, S7.10.5, S7.11, S13.8.11.4)."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, make, new_id, remove, saved, share
from test_accounts import add, new_account
from test_budgets import plan, setup_budget
from test_moves import move, moves_on
from test_reserves import landed, put_plan, reserves_on

from moolakata import clock

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def refused(r, field, code, words, status=422):
    assert r.status_code == status, r.text
    e = r.json()["errors"][0]
    assert (e["field"], e["code"], e["message"]) == (field, code, words)


def problem(r, status, code, words):
    assert r.status_code == status, r.text
    assert (r.json()["code"], r.json()["detail"]) == (code, words)


def save(c, *ops):
    return c.post("/ui/api/save", json={"ops": list(ops)})


def update(entity, record, **fields):
    return {"op": "update", "entity": entity, "id": record["id"], "version": record["version"],
            "fields": {**{k: v for k, v in record.items() if k not in ("id", "version",
                                                                       "access")},
                       **fields}}  # fmt: skip


# ---------- a month asked for ----------


def test_a_month_that_isnt_one_is_refused(server, frozen):
    c, _, _, b = setup_budget(server)
    for bad in ("2026-13", "October"):
        r = c.get(f"/ui/api/budgets/{b['id']}/month", params={"month": bad})
        problem(r, 422, "month-invalid", "A month such as 2026-10.")


# ---------- a budget: its name and method (S7.1.3, S7.12.4) ----------


def test_a_budget_is_renamed_but_keeps_its_method(server, frozen):
    c, _, _, b = setup_budget(server)
    assert saved(change(c, "Bdgt", b, name=" Home "))["name"] == "Home"
    b = c.get(f"/ui/api/budgets/{b['id']}").json()
    refused(
        change(c, "Bdgt", b, method="envelope"),
        "method",
        "method-fixed",
        "A budget keeps its method; copy it as a scenario.",
    )
    # A method other than the two is the record's own refusal, before any rule of the budget's.
    r = change(c, "Bdgt", b, method="zero")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "method"


@pytest.mark.parametrize(
    ("body", "field", "code", "words"),
    [
        ({"name": "Try", "method": "zero"}, "method", "method-invalid", "Tracking or envelope."),
        ({"name": "  ", "method": "envelope"}, "name", "name-invalid",
         "Enter a name of up to 80 characters."),
        ({"name": "x" * 81, "method": "envelope"}, "name", "name-invalid",
         "Enter a name of up to 80 characters."),
    ],
)  # fmt: skip
def test_a_copy_as_scenario_needs_a_method_and_a_name(server, frozen, body, field, code, words):
    c, _, _, b = setup_budget(server)
    refused(c.post(f"/ui/api/budgets/{b['id']}/copy", json=body), field, code, words)


# ---------- a plan line (S7.1.2, S7.2.1) ----------


def _line(b, category, **fields):
    return {"op": "create", "entity": "BdgLn", "id": new_id("BdgLn"),
            "fields": {"budgetId": b["id"], "categoryId": category, "fromMonth": "2026-10-01",
                       "amount": "100.00", **fields}}  # fmt: skip


def test_a_line_needs_a_category_it_can_count_and_a_projection_of_the_owners(server, frozen):
    c, _, cat, b = setup_budget(server)
    between = make(c, "Cat", name="Between mine", kind="transfer").json()
    refused(
        save(c, _line(b, between["id"])), "categoryId", "category-unknown", "Choose a category."
    )
    nowhere = new_id("Prjct")
    refused(
        save(c, _line(b, cat["Savings › Investing"], projectionId=nowhere)),
        "projectionId",
        "projection-unknown",
        "Choose a projection.",
    )
    # Monthly or yearly is the record's own refusal, before the line's rules.
    r = save(c, _line(b, cat["Food"], cadence="week"))
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "cadence"
    r = save(c, _line(b, cat["Food"], overspend="later"))
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "overspend"


def test_a_line_keeps_its_category_and_one_not_there_is_not_found(server, frozen):
    c, _, cat, b = setup_budget(server)
    plan(c, b, "2026-10-01", [{"categoryId": cat["Food"], "amount": "300.00"}])
    (ln,) = c.get(f"/ui/api/budgets/{b['id']}/plan", params={"month": "2026-10"}).json()["lines"]
    refused(
        save(c, update("BdgLn", ln, categoryId=cat["Travel"])),
        "categoryId",
        "line-fixed",
        "A line keeps its budget and category.",
    )
    gone = {**ln, "id": new_id("BdgLn")}
    refused(save(c, update("BdgLn", gone, amount="1.00")), None, "not-found", "Not found", 404)


# ---------- a move (S7.11) ----------


def test_a_move_is_of_more_than_nothing_between_categories_with_a_short_note(server, frozen):
    c, _, cat, b = setup_budget(server)
    moves_on(c, b)
    between = make(c, "Cat", name="Between mine", kind="transfer").json()
    base = {"month": "2026-10-01", "fromCategoryId": cat["Food"], "toCategoryId": cat["Travel"]}
    refused(
        move(c, b, **{**base, "fromCategoryId": between["id"]}, amount="5"),
        "fromCategoryId",
        "category-unknown",
        "Choose a category.",
    )
    for nothing in ("0", "-5.00"):
        refused(
            move(c, b, **base, amount=nothing), "amount", "amount-invalid", "More than nothing."
        )
    refused(
        move(c, b, **base, amount="5", note="x" * 201),
        "note",
        "note-too-long",
        "At most 200 characters.",
    )
    made = move(c, b, **base, amount="5", note="x" * 200).json()
    fields = {"budgetId": b["id"], **base, "amount": "6.00"}
    op = {"op": "update", "entity": "BdgMv", "id": made["id"], "version": made["version"],
          "fields": fields}  # fmt: skip
    refused(
        save(c, op),
        None,
        "move-fixed",
        "A move isn't changed: delete it, and move again.",
    )
    saved(remove(c, "BdgMv", made))
    refused(remove(c, "BdgMv", made), None, "not-found", "No such move.", 404)


# ---------- landed money given (S7.10.5) ----------


def test_landed_money_is_given_only_from_where_it_landed_to_a_reserve_held_there(server, frozen):
    c, acct, cat, b = setup_budget(server)
    savings = new_account(c, name="Ally", type="savings", mask="2222")
    reserves_on(c, b)
    from edits import budget_accounts

    assert budget_accounts(c, b, [acct["id"], savings["id"]]).status_code == 200
    roof = cat["Housing › Maintenance"]
    line = {"categoryId": roof, "amount": "100", "target": "900", "heldInId": savings["id"]}
    assert put_plan(c, b, "2026-10-01", [line]).status_code == 200
    interest = add(c, savings["id"], "4.00", "2026-10-02", payee="Interest", kind="interest")
    fee = add(c, savings["id"], "-2.00", "2026-10-03", payee="Fee")
    refused(
        landed(c, b, fee, {roof: "2.00"}), "transactionId", "not-found", "No such money landed."
    )
    gone = {**interest, "id": new_id("Txn")}
    refused(
        landed(c, b, gone, {roof: "1.00"}), "transactionId", "not-found", "No such money landed."
    )
    refused(
        landed(c, b, interest, {cat["Food"]: "4.00"}),
        "toCategoryId",
        "reserve-unknown",
        "One of the reserves held there.",
    )
    refused(
        landed(c, b, interest, {roof: "4.00"}, month_="2026-09-01"),
        "month",
        "month-invalid",
        "The month it landed, or one after.",
    )
    for amount in ("0", "4.01"):
        refused(
            landed(c, b, interest, {roof: amount}),
            "amount",
            "amount-invalid",
            "No more than is unassigned of it.",
        )
    fields = {"budgetId": b["id"], "month": "2026-10-01", "fromCategoryId": cat["Food"],
              "toCategoryId": roof, "amount": "1.00", "transactionId": interest["id"]}  # fmt: skip
    op = {"op": "create", "entity": "BdgMv", "id": new_id("BdgMv"), "fields": fields}
    refused(
        save(c, op), "fromCategoryId", "move-invalid", "Landed money comes from where it landed."
    )
    assert landed(c, b, interest, {roof: "4.00"}).status_code == 200


# ---------- a transaction's budgets (S7.3.5) ----------


def test_the_budgets_of_a_transaction_not_there_are_not_found(server, frozen):
    c, *_ = setup_budget(server)
    r = c.get(f"/ui/api/transactions/{new_id('Txn')}/budgets")
    problem(r, 404, "not-found", "No such transaction.")


# ---------- a budget's accounts over months (S7.1.7) ----------


def _ba(b, account, **fields):
    return {"op": "create", "entity": "BdgAc", "id": new_id("BdgAc"),
            "fields": {"budgetId": b["id"], "accountId": account, **fields}}  # fmt: skip


def test_a_budgets_accounts_are_the_owners_to_choose_in_whole_months(server, frozen):
    c, acct, _, b = setup_budget(server)
    savings = new_account(c, name="Ally", type="savings", mask="2222")
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    theirs = new_account(bob, name="Bob's checking", mask="9999")
    refused(
        save(c, _ba(b, theirs["id"])),
        "accountId",
        "account-unknown",
        "Choose accounts you own or that are shared with you.",
    )
    refused(
        save(c, _ba(b, savings["id"], fromMonth="2026-10-15")),
        "fromMonth",
        "month-invalid",
        "A month: its first day.",
    )
    refused(
        save(c, _ba(b, savings["id"], untilMonth="2026-10-02")),
        "untilMonth",
        "month-invalid",
        "A month: its first day.",
    )
    refused(
        save(c, _ba(b, savings["id"], fromMonth="2026-10-01", untilMonth="2026-09-01")),
        "untilMonth",
        "months-order",
        "The last month comes after the first.",
    )
    refused(
        save(c, _ba(b, card["id"], paidFromId=savings["id"])),
        "paidFromId",
        "account-unknown",
        "Choose one of the budget's accounts.",
    )
    (counted,) = c.get(f"/ui/api/budgets/{b['id']}/accounts").json()["items"]
    refused(
        save(c, update("BdgAc", counted, accountId=savings["id"])),
        "accountId",
        "account-fixed",
        "A budget's account keeps its account.",
    )
    gone = {**counted, "id": new_id("BdgAc")}
    refused(
        save(c, update("BdgAc", gone, untilMonth="2026-10-01")), None, "not-found", "Not found", 404
    )
    # One who writes the budget changes its plan, never its accounts (S7.1.1).
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    share(c, "budget", b["id"], users={bob_id: "write"})
    # Making one is refused as any record of the budget's is; changing one, by the rule itself.
    refused(
        save(bob, _ba(b, theirs["id"])),
        "budgetId",
        "owner-only",
        "Only the budget's owner can do this.",
        403,
    )
    refused(
        save(bob, update("BdgAc", counted, untilMonth="2026-10-01")),
        None,
        "owner-only",
        "Only the owner chooses the accounts.",
        403,
    )
    assert [
        x["accountId"] for x in c.get(f"/ui/api/budgets/{b['id']}/accounts").json()["items"]
    ] == [acct["id"]]
