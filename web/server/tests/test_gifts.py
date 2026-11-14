"""Gifts (requirements S7.7, S7.8): gift plans and occasions, holidays, gifts and their privacy,
upcoming occasions with their reminder, spending and the gift-tax flag, and what deleting a
person leaves (S7.8.6)."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, detach, make, plan529, remove, saved, share
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
def jane(server, frozen):
    make_user(server, "jane")
    return sign_in(server, "jane")


def person(c, **kw):
    """A new person and a gift plan for them, in one save: the person as `/persons` reads
    them, with their plan as `/gift-plans` does (`plan`)."""
    r = make(c, "GfPln", **{"name": "Lisa Doe", "sex": "female", **kw})
    assert r.status_code == 200, r.text
    return planned(c, r.json())


def planned(c, plan: dict) -> dict:
    """A gift plan's person, with the plan (`plan`)."""
    return {**c.get(f"/ui/api/persons/{plan['personId']}").json(), "plan": plan}


def gift(c, **kw):
    r = make(c, "Gift", **{"description": "Watercolour set", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_holiday_dates_by_rule_and_table():
    assert holidays.date_of("christmas", 2026) == dt.date(2026, 12, 25)
    assert holidays.date_of("mothers-day", 2026) == dt.date(2026, 5, 10)
    assert holidays.date_of("thanksgiving", 2026) == dt.date(2026, 11, 26)
    assert holidays.date_of("fathers-day", 2027) == dt.date(2027, 6, 20)
    assert holidays.date_of("diwali", 2026) == dt.date(2026, 11, 8)
    assert holidays.date_of("diwali", 2040) is None


def test_a_person_with_occasions_and_their_next_date(jane):
    p = person(
        jane,
        birthMonth=10,
        birthDay=20,
        birthYear=2018,
        giftBudget="600",
        occasions=[
            {"kind": "holiday", "holiday": "christmas", "budget": "150"},
            {"kind": "custom", "name": "First day of school", "month": 9, "day": 1},
        ],
    )
    assert p["plan"]["next"] == {
        "key": "birthday",
        "label": "Birthday",
        "date": "2026-10-20",
        "days": 9,
        "turns": 8,
    }
    labels = {o["label"]: o["next"] for o in p["plan"]["occasions"]}
    assert labels == {"Christmas": "2026-12-25", "First day of school": "2027-09-01"}
    bad = make(
        jane, "GfPln", name="X", sex="male", occasions=[{"kind": "holiday", "holiday": "festivus"}]
    )
    assert bad.json()["errors"][0]["field"] == "holiday"


def test_upcoming_with_the_reminder_on_the_dashboard_and_as_an_alert(server, jane):
    lisa = person(jane, birthMonth=10, birthDay=20, birthYear=2018)
    up = jane.get("/ui/api/gifts/upcoming").json()["items"]
    assert [(u["person"]["name"], u["label"], u["days"], u["inLead"]) for u in up] == [
        ("Lisa Doe", "Birthday", 9, True)
    ]
    assert up[0]["missing"] == "no gift yet"
    dash = jane.get("/ui/api/dashboard").json()["attention"]
    assert any(a["text"] == "Lisa Doe's birthday in 9 days, no gift yet" for a in dash)
    opened = alerts.evaluate(server)
    assert [a.kind for a in opened] == ["occasion"]
    # An idea isn't enough; something bought clears the reminder.
    g = gift(jane, people=[lisa["id"]], occasion="birthday", occasionYear=2026)
    assert (
        jane.get("/ui/api/gifts/upcoming").json()["items"][0]["missing"] == "1 idea, nothing bought"
    )
    saved(change(jane, "Gift", g, occasion="birthday", occasionYear=2026, status="bought",
                 cost="35"))  # fmt: skip
    assert jane.get("/ui/api/gifts/upcoming").json()["items"][0]["planned"] == "35.00"
    alerts.evaluate(server)
    with server.db.read(unscoped="test") as s:
        from moolakata.store.entities.alerts import Alert

        a = s.query(Alert).filter_by(kind="occasion").one()
        assert a.resolvedAt is not None


def test_a_gift_for_a_user_is_never_shown_to_them(server, jane):
    make_user(server, "john", sex="male")
    john = sign_in(server, "john")
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    john_person = john.get("/ui/api/profile").json()["personId"]
    lisa = person(jane)
    him = make(jane, "GfPln", personId=john_person, giftBudget="800")
    assert him.status_code == 200, him.text
    him = planned(jane, him.json())
    assert him["userId"] == john_id and not him["access"]["writable"]
    gift(jane, people=[lisa["id"]], description="Paints")
    gift(jane, people=[him["id"]], description="A watch", status="planned")
    gift(jane, people=[lisa["id"], him["id"]], description="A board game", status="bought")
    r = share(jane, "gift-plan", lisa["plan"]["id"], users={john_id: "write"})
    assert r.status_code == 200, r.text
    seen = {g["description"] for g in john.get("/ui/api/gifts").json()["items"]}
    assert seen == {"Paints"}, "the surprise stays one"
    assert {g["description"] for g in jane.get("/ui/api/gifts").json()["items"]} == {
        "Paints",
        "A watch",
        "A board game",
    }
    # John plans Lisa's gifts with Jane: what he adds goes in her plan, so she sees it.
    r = make(john, "Gift", people=[lisa["id"]], description="Horse book")
    assert r.status_code == 200, r.text
    assert "Horse book" in {g["description"] for g in jane.get("/ui/api/gifts").json()["items"]}
    plans = john.get("/ui/api/gift-plans").json()["items"]
    assert [p["personId"] for p in plans] == [lisa["id"]]


def test_deleting_a_person_keeps_what_was_given_by_name(jane):
    lisa, sam = person(jane), person(jane, name="Sam Lee", sex="male")
    gift(jane, people=[sam["id"]], description="Kite", status="idea")
    gift(jane, people=[sam["id"]], description="Robot", status="planned")
    gift(jane, people=[lisa["id"], sam["id"]], description="Puzzle", status="idea")
    gift(
        jane,
        people=[sam["id"]],
        description="Book",
        status="given",
        cost="20",
        occasion="birthday",
        occasionYear=2026,
    )
    r = remove(jane, "Persn", jane.get(f"/ui/api/persons/{sam['id']}").json())
    assert r.status_code == 200, r.text
    left = {g["description"]: g for g in jane.get("/ui/api/gifts").json()["items"]}
    assert set(left) == {"Puzzle", "Book"}, "ideas and planned gifts for Sam alone go"
    assert [x["name"] for x in left["Puzzle"]["people"]] == ["Lisa Doe"]
    assert left["Book"]["people"] == [{"id": sam["id"], "name": "Sam Lee", "deleted": True}]
    assert jane.get("/ui/api/gifts/spending?year=2026").json()["byYear"] == [
        {"label": "2026", "amount": "20.00"}
    ]
    plans = jane.get("/ui/api/gift-plans").json()["items"]
    assert [x["personId"] for x in plans] == [lisa["id"]]


def test_a_linked_purchase_is_categorised_and_spending_is_summed(jane):
    lisa = person(jane, giftBudget="600")
    card = new_account(jane, name="Card", type="credit-card")
    t = add(jane, card["id"], "-35.00", "2026-10-09", payee="Michaels")
    g = gift(
        jane,
        people=[lisa["id"]],
        occasion="birthday",
        occasionYear=2026,
        status="bought",
        cost="35",
        transactionId=t["id"],
    )
    assert g["paid"]["payee"] == "Michaels"
    items = jane.get("/ui/api/transactions", params={"account": card["id"]}).json()["items"]
    txn = next(x for x in items if x["id"] == t["id"])
    cats = {c["id"]: c["name"] for c in jane.get("/ui/api/categories").json()["items"]}
    assert cats[txn["categoryId"]] == "Gifts"
    sp = jane.get("/ui/api/gifts/spending?year=2026").json()
    assert sp["byPerson"][0]["spent"] == "35.00" and sp["byPerson"][0]["budget"] == "600.00"
    assert sp["byOccasion"] == [{"label": "Birthdays", "amount": "35.00"}]


def test_money_given_above_the_exclusion_is_flagged(jane):
    lisa = person(jane)
    gift(
        jane,
        people=[lisa["id"]],
        description="Cash",
        status="given",
        cash=True,
        cost="15000",
        occasion="birthday",
        occasionYear=2026,
    )
    acct = new_account(jane, name="Lisa's 529", type="529")
    saved(plan529(jane, acct["id"], beneficiaryId=lisa["id"]))
    make(jane, "Cntrb", accountId=acct["id"], date="2026-03-01", amount="6000")
    sp = jane.get("/ui/api/gifts/spending?year=2026").json()
    assert sp["flagged"] == [
        {
            "person": {"id": lisa["id"], "name": "Lisa Doe", "deleted": False},
            "given": "21000.00",
            "exclusion": "19000.00",
        }
    ]


def test_a_529_counts_with_no_gift_plan_and_an_election_over_its_five_years(jane):
    # B16: the beneficiary has no gift plan; the owner's five-year election of 100,000 in 2024
    # is 20,000 in each of 2024-2028, over the 2026 exclusion.
    leo = person(jane, name="Leo Doe", sex="male")
    acct = new_account(jane, name="Leo's 529", type="529")
    saved(plan529(jane, acct["id"], beneficiaryId=leo["id"]))
    r = make(jane, "Cntrb", accountId=acct["id"], date="2024-03-01", amount="100000", fiveYear=True)
    assert r.status_code == 200, r.text
    sp = jane.get("/ui/api/gifts/spending?year=2026").json()
    assert [(f["person"]["id"], f["given"]) for f in sp["flagged"]] == [(leo["id"], "20000.00")]
    assert jane.get("/ui/api/gifts/spending?year=2029").json()["flagged"] == []


LONG = "https://shop.example.com/" + "a" * (2000 - 25)


@pytest.mark.parametrize(
    ("link", "kept", "refused"),
    [
        (None, None, None),
        ("", None, None),  # blank: no link
        ("   ", None, None),
        (" https://shop.example.com/item?id=1 ", "https://shop.example.com/item?id=1", None),
        ("http://shop.lan/x", "http://shop.lan/x", None),
        (LONG, LONG, None),  # 2,000 characters
        (LONG + "a", None, "At most 2,000 characters."),
        ("shop.example.com/item", None, "A web address starting with https:// or http://."),
        ("javascript:alert(1)", None, "A web address starting with https:// or http://."),
        ("ftp://shop.example.com", None, "A web address starting with https:// or http://."),
        ("https://", None, "A web address starting with https:// or http://."),
        ("https://shop.example.com/a b", None, "A web address starting with https:// or http://."),
        ("https://[::1", None, "A web address starting with https:// or http://."),
    ],
)
def test_a_gifts_link_is_a_web_address(jane, link, kept, refused):
    """S7.8.1: http or https and a host, up to 2,000 characters; blank is no link."""
    gran = person(jane, name="Candace Doe")
    r = make(jane, "Gift", description="Scarf", people=[gran["id"]], link=link)
    if refused:
        assert r.status_code == 422, r.text
        [e] = r.json()["errors"]
        assert (e["field"], e["code"], e["message"]) == ("link", "link-invalid", refused)
        return
    assert r.status_code == 200, r.text
    assert r.json()["link"] == kept


def test_received_gifts_and_thank_yous(jane):
    gran = person(jane, name="Candace Doe")
    g = gift(jane, people=[gran["id"]], description="Scarf", status="received", thankYou=True)
    assert g["status"] == "received" and g["thankYou"]
    ideas = jane.get("/ui/api/gifts?status=received").json()["items"]
    assert [x["description"] for x in ideas] == ["Scarf"]


def test_a_gifts_receipt_is_kept_with_it_and_can_be_taken_back(jane):
    # N13: not in the Inbox while kept with the gift; detached, it is again.
    lisa = person(jane)
    g = gift(jane, people=[lisa["id"]], status="given", cost="40.00")
    up = jane.post(
        "/ui/api/receipts", files={"file": ("r.pdf", b"%PDF-1.4 r", "application/pdf")}
    ).json()
    saved(change(jane, "Gift", g, receiptIds={"add": [up["id"]], "remove": []}))
    assert jane.get("/ui/api/receipts", params={"show": "inbox"}).json()["items"] == []
    [link] = jane.get(f"/ui/api/receipts/{up['id']}").json()["links"]
    assert link["kind"] == "gift" and link["label"] == "The gift Watercolour set"
    assert link["access"]["deletable"]
    r = detach(jane, up["id"], g["id"])
    assert r.status_code == 200, r.text
    inbox = jane.get("/ui/api/receipts", params={"show": "inbox"}).json()["items"]
    assert [x["id"] for x in inbox] == [up["id"]]
