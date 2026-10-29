"""Gifts (requirements S7.7, S7.8): gift plans and occasions, holidays, gifts and their privacy,
upcoming occasions with their reminder, spending and the gift-tax flag, and what deleting a
person leaves (S7.8.6)."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, plan529, remove, saved, share
from test_accounts import add, new_account

from moolakata import alerts, clock
from moolakata.gifts import holidays

T0 = dt.datetime(2026, 10, 11, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def alice(server, frozen):
    make_user(server, "alice")
    return sign_in(server, "alice")


def person(c, **kw):
    r = c.post("/ui/api/people", json={"name": "Emma Griffin", "sex": "female", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def gift(c, **kw):
    r = c.post("/ui/api/gifts", json={"description": "Watercolour set", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_holiday_dates_by_rule_and_table():
    assert holidays.date_of("christmas", 2026) == dt.date(2026, 12, 25)
    assert holidays.date_of("mothers-day", 2026) == dt.date(2026, 5, 10)
    assert holidays.date_of("thanksgiving", 2026) == dt.date(2026, 11, 26)
    assert holidays.date_of("fathers-day", 2027) == dt.date(2027, 6, 20)
    assert holidays.date_of("diwali", 2026) == dt.date(2026, 11, 8)
    assert holidays.date_of("diwali", 2040) is None


def test_a_person_with_occasions_and_their_next_date(alice):
    p = person(
        alice,
        birthMonth=10,
        birthDay=20,
        birthYear=2018,
        giftBudget="600",
        occasions=[
            {"kind": "holiday", "holiday": "christmas", "budget": "150"},
            {"kind": "custom", "name": "First day of school", "month": 9, "day": 1},
        ],
    )
    assert p["next"] == {
        "key": "birthday",
        "label": "Birthday",
        "date": "2026-10-20",
        "days": 9,
        "turns": 8,
    }
    labels = {o["label"]: o["next"] for o in p["occasions"]}
    assert labels == {"Christmas": "2026-12-25", "First day of school": "2027-09-01"}
    bad = alice.post(
        "/ui/api/people",
        json={
            "name": "X",
            "sex": "male",
            "occasions": [{"kind": "holiday", "holiday": "festivus"}],
        },
    )
    assert bad.json()["errors"][0]["field"] == "occasions.0.holiday"


def test_upcoming_with_the_reminder_on_the_dashboard_and_as_an_alert(server, alice):
    emma = person(alice, birthMonth=10, birthDay=20, birthYear=2018)
    up = alice.get("/ui/api/gifts/upcoming").json()["items"]
    assert [(u["person"]["name"], u["label"], u["days"], u["inLead"]) for u in up] == [
        ("Emma Griffin", "Birthday", 9, True)
    ]
    assert up[0]["missing"] == "no gift yet"
    dash = alice.get("/ui/api/dashboard").json()["attention"]
    assert any(a["text"] == "Emma Griffin's birthday in 9 days, no gift yet" for a in dash)
    opened = alerts.evaluate(server)
    assert [a.kind for a in opened] == ["occasion"]
    # An idea isn't enough; something bought clears the reminder.
    g = gift(alice, people=[emma["id"]], occasion="birthday", occasionYear=2026)
    assert (
        alice.get("/ui/api/gifts/upcoming").json()["items"][0]["missing"]
        == "1 idea, nothing bought"
    )
    saved(change(alice, "Gift", g, occasion="birthday", occasionYear=2026, status="bought",
                 cost="35"))  # fmt: skip
    assert alice.get("/ui/api/gifts/upcoming").json()["items"][0]["planned"] == "35.00"
    alerts.evaluate(server)
    with server.db.read() as s:
        from moolakata.store.entities.alerts import Alert

        a = s.query(Alert).filter_by(kind="occasion").one()
        assert a.resolvedAt is not None


def test_a_gift_for_a_user_is_never_shown_to_them(server, alice):
    make_user(server, "bob", sex="male")
    bob = sign_in(server, "bob")
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    bob_person = bob.get("/ui/api/profile").json()["personId"]
    emma = person(alice)
    him = alice.post("/ui/api/people", json={"personId": bob_person, "giftBudget": "800"})
    assert him.status_code == 201, him.text
    him = him.json()
    assert him["userId"] == bob_id and not him["canChangePerson"]
    gift(alice, people=[emma["id"]], description="Paints")
    gift(alice, people=[him["id"]], description="A watch", status="planned")
    gift(alice, people=[emma["id"], him["id"]], description="A board game", status="bought")
    r = share(alice, "gift-plan", emma["planId"], users={bob_id: "write"})
    assert r.status_code == 200, r.text
    seen = {g["description"] for g in bob.get("/ui/api/gifts").json()["items"]}
    assert seen == {"Paints"}, "the surprise stays one"
    assert {g["description"] for g in alice.get("/ui/api/gifts").json()["items"]} == {
        "Paints",
        "A watch",
        "A board game",
    }
    # Bob plans Emma's gifts with Alice: what he adds goes in her plan, so she sees it.
    r = bob.post("/ui/api/gifts", json={"people": [emma["id"]], "description": "Horse book"})
    assert r.status_code == 201, r.text
    assert "Horse book" in {g["description"] for g in alice.get("/ui/api/gifts").json()["items"]}
    names = [p["name"] for p in bob.get("/ui/api/people").json()["items"]]
    assert names == ["Emma Griffin"]


def test_deleting_a_person_keeps_what_was_given_by_name(alice):
    emma, sam = person(alice), person(alice, name="Sam Lee", sex="male")
    gift(alice, people=[sam["id"]], description="Kite", status="idea")
    gift(alice, people=[sam["id"]], description="Robot", status="planned")
    gift(alice, people=[emma["id"], sam["id"]], description="Puzzle", status="idea")
    gift(
        alice,
        people=[sam["id"]],
        description="Book",
        status="given",
        cost="20",
        occasion="birthday",
        occasionYear=2026,
    )
    r = remove(alice, "Persn", alice.get(f"/ui/api/persons/{sam['id']}").json())
    assert r.status_code == 200, r.text
    left = {g["description"]: g for g in alice.get("/ui/api/gifts").json()["items"]}
    assert set(left) == {"Puzzle", "Book"}, "ideas and planned gifts for Sam alone go"
    assert [x["name"] for x in left["Puzzle"]["people"]] == ["Emma Griffin"]
    assert left["Book"]["people"] == [{"id": sam["id"], "name": "Sam Lee", "deleted": True}]
    assert alice.get("/ui/api/gifts/spending?year=2026").json()["byYear"] == [
        {"label": "2026", "amount": "20.00"}
    ]
    names = [x["name"] for x in alice.get("/ui/api/people").json()["items"]]
    assert names == ["Emma Griffin"]


def test_a_linked_purchase_is_categorised_and_spending_is_summed(alice):
    emma = person(alice, giftBudget="600")
    card = new_account(alice, name="Card", type="credit-card")
    t = add(alice, card["id"], "-35.00", "2026-10-09", payee="Michaels")
    g = gift(
        alice,
        people=[emma["id"]],
        occasion="birthday",
        occasionYear=2026,
        status="bought",
        cost="35",
        transactionId=t["id"],
    )
    assert g["paid"]["payee"] == "Michaels"
    items = alice.get("/ui/api/transactions", params={"account": card["id"]}).json()["items"]
    txn = next(x for x in items if x["id"] == t["id"])
    cats = {c["id"]: c["name"] for c in alice.get("/ui/api/categories").json()["items"]}
    assert cats[txn["categoryId"]] == "Gifts"
    sp = alice.get("/ui/api/gifts/spending?year=2026").json()
    assert sp["byPerson"][0]["spent"] == "35.00" and sp["byPerson"][0]["budget"] == "600.00"
    assert sp["byOccasion"] == [{"label": "Birthdays", "amount": "35.00"}]


def test_money_given_above_the_exclusion_is_flagged(alice):
    emma = person(alice)
    gift(
        alice,
        people=[emma["id"]],
        description="Cash",
        status="given",
        cash=True,
        cost="15000",
        occasion="birthday",
        occasionYear=2026,
    )
    acct = new_account(alice, name="Emma's 529", type="529")
    saved(plan529(alice, acct["id"], beneficiaryId=emma["id"]))
    alice.post(
        f"/ui/api/accounts/{acct['id']}/contributions",
        json={"date": "2026-03-01", "amount": "6000"},
    )
    sp = alice.get("/ui/api/gifts/spending?year=2026").json()
    assert sp["flagged"] == [
        {
            "person": {"id": emma["id"], "name": "Emma Griffin", "deleted": False},
            "given": "21000.00",
            "exclusion": "19000.00",
        }
    ]


def test_a_529_counts_with_no_gift_plan_and_an_election_over_its_five_years(alice):
    # B16: the beneficiary has no gift plan; the owner's five-year election of 100,000 in 2024
    # is 20,000 in each of 2024-2028, over the 2026 exclusion.
    leo = alice.post("/ui/api/people", json={"name": "Leo Griffin", "sex": "male"}).json()
    acct = new_account(alice, name="Leo's 529", type="529")
    saved(plan529(alice, acct["id"], beneficiaryId=leo["id"]))
    r = alice.post(
        f"/ui/api/accounts/{acct['id']}/contributions",
        json={"date": "2024-03-01", "amount": "100000", "fiveYear": True},
    )
    assert r.status_code == 201, r.text
    sp = alice.get("/ui/api/gifts/spending?year=2026").json()
    assert [(f["person"]["id"], f["given"]) for f in sp["flagged"]] == [(leo["id"], "20000.00")]
    assert alice.get("/ui/api/gifts/spending?year=2029").json()["flagged"] == []


def test_received_gifts_and_thank_yous(alice):
    gran = person(alice, name="Margaret Griffin")
    g = gift(alice, people=[gran["id"]], description="Scarf", status="received", thankYou=True)
    assert g["status"] == "received" and g["thankYou"]
    ideas = alice.get("/ui/api/gifts?status=received").json()["items"]
    assert [x["description"] for x in ideas] == ["Scarf"]


def test_a_gifts_receipt_is_kept_with_it_and_can_be_taken_back(alice):
    # N13: not in the Inbox while kept with the gift; detached, it is again.
    emma = person(alice)
    g = gift(alice, people=[emma["id"]], status="given", cost="40.00")
    up = alice.post(
        "/ui/api/receipts", files={"file": ("r.pdf", b"%PDF-1.4 r", "application/pdf")}
    ).json()
    saved(change(alice, "Gift", g, receiptIds={"add": [up["id"]], "remove": []}))
    assert alice.get("/ui/api/receipts", params={"show": "inbox"}).json()["items"] == []
    [link] = alice.get(f"/ui/api/receipts/{up['id']}").json()["links"]
    assert link["kind"] == "gift" and link["label"] == "The gift Watercolour set"
    assert link["canDetach"]
    r = alice.delete(f"/ui/api/receipts/{up['id']}/kept/gift/{g['id']}")
    assert r.status_code == 200, r.text
    inbox = alice.get("/ui/api/receipts", params={"show": "inbox"}).json()["items"]
    assert [x["id"] for x in inbox] == [up["id"]]
