"""Gift plans, occasions and gifts at their edges (requirements S7.7, S7.8): each refusal at
its field with its code and words, what no longer is or can't be changed, a gift's people
changed, how a gift is labelled and paid, and which year its spending counts in."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, make, new_id, remove, saved, share
from test_accounts import add, new_account
from test_gifts import T0, gift, person

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
    make_user(server, "john", sex="male")
    john = sign_in(server, "john")
    return john, john.get("/ui/api/session").json()["user"]["id"]


def _cat(c, name):
    return next(x["id"] for x in c.get("/ui/api/categories").json()["items"] if x["name"] == name)


# ---- A gift (S7.8.1) ----


@pytest.mark.parametrize(
    ("fields", "field", "code", "words"),
    [
        ({"description": "  "}, "description", "description-missing", "What it is."),
        ({"status": "lost"}, "status", "status-invalid", "Idea, planned, bought, given, received."),
        ({"people": []}, "people", "people-missing", "Who it is for."),
        ({"cost": "-0.01"}, "cost", "amount-invalid", "Zero or more."),
        ({"occasion": "birthday"}, "occasionYear", "year-missing", "The year of the occasion."),
    ],
)
def test_a_gifts_description_status_people_cost_and_year_are_refused_at_their_field(
    jane, fields, field, code, words
):
    lisa = person(jane)
    refused(make(jane, "Gift", **{"people": [lisa["id"]], "description": "Kite", **fields}),
            field, code, words)  # fmt: skip


def test_a_gift_links_a_purchase_that_is_there_and_keeps_its_category(jane):
    """S7.8.4: a purchase already categorised keeps its category when a gift links it."""
    lisa = person(jane)
    bank = new_account(jane, name="Checking")
    gone = add(jane, bank["id"], "-20.00", "2026-10-01")
    assert remove(jane, "Txn", gone).status_code == 200
    for missing in (gone["id"], new_id("Txn")):
        refused(make(jane, "Gift", people=[lisa["id"]], description="Kite",
                     transactionId=missing), "transactionId", "not-found",
                "No such transaction.")  # fmt: skip
    food = _cat(jane, "Groceries")
    t = add(jane, bank["id"], "-30.00", "2026-10-02", categoryId=food)
    g = gift(jane, people=[lisa["id"]], status="bought", cost="30", transactionId=t["id"])
    assert g["paid"]["transactionId"] == t["id"]
    assert jane.get(f"/ui/api/transactions/{t['id']}").json()["categoryId"] == food


def test_a_gifts_people_are_changed_as_a_set(jane):
    lisa, sam = person(jane), person(jane, name="Sam Lee", sex="male")
    g = gift(jane, people=[lisa["id"], sam["id"]])
    g = saved(change(jane, "Gift", g, people=[lisa["id"]]))
    assert [p["name"] for p in g["people"]] == ["Lisa Doe"]
    g = saved(change(jane, "Gift", g, people=[lisa["id"], sam["id"]]))
    assert sorted(p["name"] for p in g["people"]) == ["Lisa Doe", "Sam Lee"]


def test_gifts_are_listed_by_status_and_by_person(jane):
    lisa, sam = person(jane), person(jane, name="Sam Lee", sex="male")
    gift(jane, people=[lisa["id"]], description="Kite")
    gift(jane, people=[sam["id"]], description="Robot", status="planned")

    def listed(**params):
        items = jane.get("/ui/api/gifts", params=params).json()["items"]
        return [g["description"] for g in items]

    assert listed(status="planned") == ["Robot"]
    assert listed(person=lisa["id"]) == ["Kite"]
    assert listed(status="planned", person=lisa["id"]) == []


def test_a_gift_for_a_holiday_or_the_wedding_anniversary_is_labelled_by_it(jane):
    lisa = person(jane)
    labels = {
        gift(jane, people=[lisa["id"]], occasion=key, occasionYear=2026)["occasionLabel"]
        for key in ("holiday:christmas", "wedding", "occasion:gone")
    }
    assert labels == {"Christmas", "Wedding anniversary", "An occasion"}


def test_a_gift_no_longer_there_or_shared_to_read_is_not_changed(server, jane):
    john, john_id = _john(server)
    lisa = person(jane)
    g = gift(jane, people=[lisa["id"]])
    share(jane, "gift-plan", lisa["plan"]["id"], users={john_id: "read"})
    refused(change(john, "Gift", g, description="Mine"), None, "read-only",
            "This gift is shared with you to read.", 403)  # fmt: skip
    share(jane, "gift-plan", lisa["plan"]["id"], users={john_id: "none"})
    r = change(john, "Gift", g, description="Mine")
    assert (r.status_code, r.json()["errors"][0]["code"]) == (404, "not-found"), r.text
    assert remove(jane, "Gift", g).status_code == 200
    refused(change(jane, "Gift", g, description="Back"), None, "not-found", "Not found", 404)


def test_a_gift_for_the_writer_himself_is_not_found_by_him(server, jane):
    """S7.8.5: a gift for John in a plan he writes stays a surprise: changing it, he finds
    nothing there."""
    john, john_id = _john(server)
    john_person = john.get("/ui/api/profile").json()["personId"]
    lisa = person(jane)
    g = gift(jane, people=[lisa["id"], john_person], description="A board game")
    share(jane, "gift-plan", lisa["plan"]["id"], users={john_id: "write"})
    refused(change(john, "Gift", g, description="Seen"), None, "not-found", "Not found", 404)
    assert jane.get("/ui/api/gifts").json()["items"][0]["description"] == "A board game"


def test_a_gift_paid_from_an_account_not_shared_names_no_account(server, jane):
    """S11.5.2: John, who plans Lisa's gifts with Jane, sees what a gift cost and when, but
    not her account or its transaction."""
    john, john_id = _john(server)
    lisa = person(jane)
    bank = new_account(jane, name="Jane's checking")
    t = add(jane, bank["id"], "-45.00", "2026-10-01", payee="Toy shop")
    gift(jane, people=[lisa["id"]], status="bought", cost="45", transactionId=t["id"])
    share(jane, "gift-plan", lisa["plan"]["id"], users={john_id: "write"})
    (seen,) = john.get("/ui/api/gifts").json()["items"]
    assert seen["paid"] == {
        "transactionId": None,
        "date": "2026-10-01",
        "amount": "-45.00",
        "payee": None,
        "accountName": "an account not shared",
    }


def test_spending_counts_a_gift_in_its_occasions_year_else_its_purchases(jane):
    """S7.8.4: a gift's spending counts in its occasion's year, else its purchase's; one with
    neither counts in no year."""
    lisa = person(jane)
    bank = new_account(jane, name="Checking")
    t = add(jane, bank["id"], "-25.00", "2025-12-20")
    gift(jane, people=[lisa["id"]], status="bought", cost="25", transactionId=t["id"])
    gift(jane, people=[lisa["id"]], status="given", cost="10", description="Loose change")
    gift(jane, people=[lisa["id"]], status="given", cost="40", occasion="birthday",
         occasionYear=2026)  # fmt: skip
    sp = jane.get("/ui/api/gifts/spending", params={"year": 2026}).json()
    assert sp["byYear"] == [
        {"label": "2025", "amount": "25.00"},
        {"label": "2026", "amount": "40.00"},
    ]
    assert [(p["person"]["name"], p["spent"]) for p in sp["byPerson"]] == [("Lisa Doe", "40.00")]


def test_a_529_for_oneself_is_no_gift(jane):
    """S7.8.7: what the user puts in a 529 for their own person is no gift to anyone."""
    from edits import plan529

    me = jane.get("/ui/api/profile").json()["personId"]
    acct = new_account(jane, name="My 529", type="529", institution="my529")
    saved(plan529(jane, acct["id"], beneficiaryId=me))
    made(make(jane, "Cntrb", accountId=acct["id"], date="2026-02-01", amount="30000"))
    assert jane.get("/ui/api/gifts/spending").json()["flagged"] == []


# ---- A gift plan and its occasions (S7.7) ----


def test_a_gift_plan_refuses_its_lead_time_a_second_plan_and_a_new_person(jane):
    lisa, sam = person(jane), person(jane, name="Sam Lee", sex="male")
    plan = lisa["plan"]
    for days in (-1, 121):
        refused(change(jane, "GfPln", plan, leadDays=days), "leadDays", "lead-invalid",
                "0 to 120 days.")  # fmt: skip
    assert saved(change(jane, "GfPln", plan, leadDays=120))["leadDays"] == 120
    refused(make(jane, "GfPln", personId=lisa["id"]), "personId", "plan-exists",
            "You have a gift plan for Lisa Doe.", 409)  # fmt: skip
    plan = jane.get(f"/ui/api/gift-plans/{plan['id']}").json()
    refused(change(jane, "GfPln", plan, personId=sam["id"]), "personId", "plan-fixed",
            "A gift plan stays with its person.")  # fmt: skip


def test_a_gift_plan_shared_to_read_is_not_changed(server, jane):
    john, john_id = _john(server)
    lisa = person(jane)
    share(jane, "gift-plan", lisa["plan"]["id"], users={john_id: "read"})
    plan = john.get(f"/ui/api/gift-plans/{lisa['plan']['id']}").json()
    refused(change(john, "GfPln", plan, leadDays=3), None, "read-only",
            "This gift plan is shared with you to read.", 403)  # fmt: skip


def test_ones_own_plan_for_a_person_is_the_one_shown(server, jane):
    """S7.7: one plan per person is shown, one's own first; the plan shared for the same
    person is not found by its id."""
    john, john_id = _john(server)
    lisa = person(jane)
    share(jane, "gift-plan", lisa["plan"]["id"], users={john_id: "write"})
    his = made(make(john, "GfPln", personId=lisa["id"], leadDays=7))
    assert [p["id"] for p in john.get("/ui/api/gift-plans").json()["items"]] == [his["id"]]
    r = john.get(f"/ui/api/gift-plans/{lisa['plan']['id']}")
    assert (r.status_code, r.json()["code"]) == (404, "not-found")
    shared = [p for p in jane.get("/ui/api/gift-plans").json()["items"]]
    assert [p["id"] for p in shared] == [lisa["plan"]["id"]]


@pytest.mark.parametrize(
    ("fields", "field", "code", "words"),
    [
        ({"kind": "custom", "name": "Name day"}, "month", "date-invalid", "A month and a day."),
        (
            {"kind": "anniversary", "month": 13, "day": 1},
            "month",
            "date-invalid",
            "A month and a day.",
        ),
        (
            {"kind": "anniversary", "month": 2, "day": 32},
            "month",
            "date-invalid",
            "A month and a day.",
        ),
        (
            {"kind": "custom", "month": 5, "day": 1, "name": " "},
            "name",
            "name-missing",
            "What the occasion is.",
        ),
        (
            {"kind": "holiday", "holiday": "christmas", "budget": "-1"},
            "budget",
            "amount-invalid",
            "Zero or more.",
        ),
    ],
)
def test_an_occasions_date_name_and_budget_are_refused_at_their_field(
    jane, fields, field, code, words
):
    lisa = person(jane)
    refused(make(jane, "Occsn", giftPlanId=lisa["plan"]["id"], **fields), field, code, words)


def test_an_occasion_stays_with_its_plan_and_once_gone_is_not_found(jane):
    lisa, sam = person(jane), person(jane, name="Sam Lee", sex="male")
    o = made(make(jane, "Occsn", giftPlanId=lisa["plan"]["id"], kind="custom", name="Name day",
                  month=5, day=1))  # fmt: skip
    refused(change(jane, "Occsn", o, giftPlanId=sam["plan"]["id"]), "giftPlanId",
            "occasion-fixed", "An occasion stays with its plan.")  # fmt: skip
    assert remove(jane, "Occsn", o).status_code == 200
    refused(change(jane, "Occsn", o, name="Saint's day"), None, "not-found", "Not found", 404)


def test_a_birthday_on_29_february_comes_on_the_28th_in_other_years(server, jane):
    """S7.7.1: in a year without the 29th, a leap-day birthday is on 28 February."""
    clock.fix(dt.datetime(2027, 2, 1, 12, tzinfo=dt.UTC))
    jane = sign_in(server, "jane")
    person(jane, name="Leap Lee", birthMonth=2, birthDay=29, birthYear=2004)
    up = jane.get("/ui/api/gifts/upcoming").json()["items"]
    assert [(u["person"]["name"], u["date"], u["turns"]) for u in up] == [
        ("Leap Lee", "2027-02-28", 23)
    ]


def test_ones_own_dates_are_not_upcoming_to_oneself(jane):
    """S7.7.3: a plan for one's own person shows no reminders to oneself."""
    me = jane.get("/ui/api/profile").json()
    made(make(jane, "GfPln", personId=me["personId"]))
    saved(change(jane, "Persn", jane.get(f"/ui/api/persons/{me['personId']}").json(),
                 birthMonth=10, birthDay=20))  # fmt: skip
    assert jane.get("/ui/api/gifts/upcoming").json()["items"] == []
