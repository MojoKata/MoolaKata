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


def test_a_birthday_and_a_wedding_anniversary_carry_budgets_of_their_own(jane):
    """S7.7.1, S7.7.3: a plan budgeted per occasion gives the birthday and the wedding
    anniversary, which come from the person, budgets of their own, shown with each date."""
    from test_people import me, relate

    bob = person(
        jane,
        name="Bob Lee",
        sex="male",
        birthMonth=10,
        birthDay=20,
        birthYear=1980,
        birthdayBudget="60",
        weddingBudget="90",
        occasions=[{"kind": "holiday", "holiday": "christmas", "budget": "40"}],
    )
    relate(jane, me(jane), bob["id"], "spouse", fromDate="2009-11-02")
    plan = jane.get(f"/ui/api/gift-plans/{bob['plan']['id']}").json()
    assert (plan["giftBudget"], plan["birthdayBudget"], plan["weddingBudget"]) == (
        None,
        "60.00",
        "90.00",
    )
    up = jane.get("/ui/api/gifts/upcoming").json()["items"]
    assert [(u["label"], u["budget"]) for u in up] == [
        ("Birthday", "60.00"),
        ("Wedding anniversary", "90.00"),
    ]
    bad = make(jane, "GfPln", name="Cy Lee", sex="male", birthdayBudget="-1")
    assert [(e["field"], e["code"]) for e in bad.json()["errors"]] == [
        ("birthdayBudget", "amount-invalid")
    ]


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


def test_a_gift_plan_is_never_shown_to_its_own_person(server, jane, admin_client):
    """S7.8.5: a plan for a user is left out of what anyone but its owner sees when that user
    is the viewer, shared to them or to a group they are in; the other plans of the share
    are still seen, and its owner sees it."""
    john_user, bart_user = make_user(server, "john", sex="male"), make_user(server, "bart")
    john, bart = sign_in(server, "john"), sign_in(server, "bart")
    john_person = john.get("/ui/api/profile").json()["personId"]
    lisa = person(jane)
    him = make(jane, "GfPln", personId=john_person, giftBudget="800", notes="wants the Seiko")
    assert him.status_code == 200, him.text
    him = him.json()
    for plan in (lisa["plan"]["id"], him["id"]):
        r = share(jane, "gift-plan", plan, users={john_user.id: "write"})
        assert r.status_code == 200, r.text

    def plans(c):
        return [p["personId"] for p in c.get("/ui/api/gift-plans").json()["items"]]

    assert plans(john) == [lisa["id"]]
    assert john.get(f"/ui/api/gift-plans/{him['id']}").status_code == 404
    r = make(john, "Occsn", giftPlanId=him["id"], kind="holiday", holiday="christmas")
    assert r.status_code == 404, "nor changed through the share"
    # Through a group he is in, the same; another member sees both.
    for plan in (lisa["plan"]["id"], him["id"]):
        share(jane, "gift-plan", plan, users={john_user.id: "none"})
    g = make(admin_client, "Group", name="Household", memberIds=[john_user.id, bart_user.id])
    for plan in (lisa["plan"]["id"], him["id"]):
        r = share(jane, "gift-plan", plan, groups={g.json()["id"]: "read"})
        assert r.status_code == 200, r.text
    assert plans(john) == [lisa["id"]]
    assert sorted(plans(bart)) == sorted([lisa["id"], john_person])
    assert sorted(plans(jane)) == sorted([lisa["id"], john_person])


def test_a_plan_for_someone_its_reader_cant_see_names_them_and_nothing_else(server, jane):
    """R3.14, S7.7: John makes Ann, whom Jane plans for, private: Jane's plan stays hers,
    naming Ann, with its occasions, gifts and spending; Ann's birthday, which is Ann's and
    not the plan's, is left out, as is Ann herself; Jane still plans Ann's gifts."""
    john_id = make_user(server, "john", sex="male").id
    john = sign_in(server, "john")
    ann = person(john, name="Ann Roe", birthMonth=10, birthDay=20, birthYear=1990)
    thanksgiving = {"kind": "holiday", "holiday": "thanksgiving", "budget": "30"}
    mine = make(jane, "GfPln", personId=ann["id"], birthdayBudget="50", occasions=[thanksgiving])
    assert mine.status_code == 200, mine.text
    mine = mine.json()
    gift(jane, people=[ann["id"]], description="Scarf", status="bought", cost="20",
         occasion="holiday:thanksgiving", occasionYear=2026)  # fmt: skip
    hers = john.get(f"/ui/api/persons/{ann['id']}").json()
    assert saved(change(john, "Persn", hers, private=True))["private"]
    # Alerts, read as the server, remind John of her birthday, never Jane.
    opened = [(a.userId, a.title) for a in alerts.evaluate(server) if a.kind == "occasion"]
    assert opened == [(john_id, "Ann Roe's birthday in 9 days")]
    [row] = jane.get("/ui/api/gift-plans").json()["items"]
    assert (row["id"], row["personId"], row["personName"]) == (mine["id"], ann["id"], "Ann Roe")
    assert row["next"]["key"] == "holiday:thanksgiving"
    assert [o["label"] for o in row["occasions"]] == ["Thanksgiving"]
    assert jane.get(f"/ui/api/gift-plans/{mine['id']}").json()["personName"] == "Ann Roe"
    assert jane.get(f"/ui/api/persons/{ann['id']}").status_code == 404
    assert ann["id"] not in {p["id"] for p in jane.get("/ui/api/persons").json()["items"]}
    [g] = jane.get("/ui/api/gifts").json()["items"]
    assert g["people"] == [{"id": ann["id"], "name": "Ann Roe", "deleted": False}]
    up = jane.get("/ui/api/gifts/upcoming").json()["items"]
    assert [(u["person"]["name"], u["label"], u["budget"]) for u in up] == [
        ("Ann Roe", "Thanksgiving", "30.00")
    ]
    sp = jane.get("/ui/api/gifts/spending?year=2026").json()
    assert [(x["person"]["name"], x["spent"], x["budget"]) for x in sp["byPerson"]] == [
        ("Ann Roe", "20.00", "30.00")
    ]
    # Her plan is hers to change, and Ann's gifts hers to plan.
    assert saved(change(jane, "GfPln", row, giftBudget="200"))["giftBudget"] == "200.00"
    more = gift(jane, people=[ann["id"]], description="Gloves", occasion="holiday:thanksgiving",
                occasionYear=2026)  # fmt: skip
    assert saved(change(jane, "Gift", more, status="given", cost="15"))["status"] == "given"


def test_a_gift_is_changed_keeping_people_its_owner_no_longer_sees(server, jane):
    """R3.14, S7.8.1: Jane's gift for Lisa and Max, whom John added, made private after; Jane
    plans for Lisa alone. The gift still names Max and is hers to change, keeping him or
    leaving him out; naming him again, once left out, is a new choice, and refused."""
    make_user(server, "john", sex="male")
    john = sign_in(server, "john")
    lisa = person(jane)
    r = make(john, "Persn", name="Max Smith", sex="male")
    assert r.status_code == 200, r.text
    max_ = r.json()
    g = gift(jane, people=[lisa["id"], max_["id"]], description="Board game")
    assert saved(change(john, "Persn", max_, private=True))["private"]
    [seen] = jane.get("/ui/api/gifts").json()["items"]
    assert {p["name"] for p in seen["people"]} == {"Lisa Doe", "Max Smith"}
    kept = saved(change(jane, "Gift", g, description="Chess set"))
    assert (kept["description"], {p["name"] for p in kept["people"]}) == (
        "Chess set",
        {"Lisa Doe", "Max Smith"},
    )
    alone = saved(change(jane, "Gift", kept, people=[lisa["id"]]))
    assert [p["id"] for p in alone["people"]] == [lisa["id"]]
    r = change(jane, "Gift", alone, people=[lisa["id"], max_["id"]])
    assert r.status_code == 404, r.text


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


def test_spending_by_person_keeps_a_deleted_person_and_a_plan_budgeted_per_occasion(jane):
    """S7.8.4, S7.8.6, S7.7.1: by person adds up with by year: a deleted person keeps a row,
    named as deleted, as does one whose plan is gone; a plan budgeted per occasion is
    compared with its occasions' budgets together. Money given above the exclusion to a
    deleted person is still flagged."""
    christmas = {"kind": "holiday", "holiday": "christmas", "budget": "100"}
    lisa = person(jane, birthMonth=10, birthDay=20, birthdayBudget="50", occasions=[christmas])
    sam = person(jane, name="Sam Lee", sex="male")
    leo = person(jane, name="Leo Doe", sex="male")
    for who, cost in ((lisa, "30"), (sam, "20"), (leo, "15")):
        gift(jane, people=[who["id"]], description="Book", status="given", cost=cost,
             occasion="birthday", occasionYear=2026)  # fmt: skip
    gift(jane, people=[sam["id"]], description="Cash", status="given", cash=True, cost="20000",
         occasion="birthday", occasionYear=2026)  # fmt: skip
    r = remove(jane, "Persn", jane.get(f"/ui/api/persons/{sam['id']}").json())
    assert r.status_code == 200, r.text
    r = remove(jane, "GfPln", jane.get(f"/ui/api/gift-plans/{leo['plan']['id']}").json())
    assert r.status_code == 200, r.text
    sp = jane.get("/ui/api/gifts/spending?year=2026").json()
    assert [(x["person"]["name"], x["person"]["deleted"], x["spent"], x["budget"])
            for x in sp["byPerson"]] == [
        ("Leo Doe", False, "15.00", None),
        ("Lisa Doe", False, "30.00", "150.00"),
        ("Sam Lee", True, "20020.00", None),
    ]  # fmt: skip
    assert sp["byYear"] == [{"label": "2026", "amount": "20065.00"}]
    assert [(f["person"]["name"], f["person"]["deleted"]) for f in sp["flagged"]] == [
        ("Sam Lee", True)
    ]


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
    # The beneficiary has no gift plan; the owner's five-year election of 100,000 in 2024
    # spreads five times that year's 18,000 exclusion, 18,000 in each of 2024-2028, and the
    # 10,000 above it is a 2024 gift (S1.8.2): 2024 is flagged, 2026 isn't.
    leo = person(jane, name="Leo Doe", sex="male")
    acct = new_account(jane, name="Leo's 529", type="529")
    saved(plan529(jane, acct["id"], beneficiaryId=leo["id"]))
    r = make(jane, "Cntrb", accountId=acct["id"], date="2024-03-01", amount="100000", fiveYear=True)
    assert r.status_code == 200, r.text
    sp = jane.get("/ui/api/gifts/spending?year=2024").json()
    assert [(f["person"]["id"], f["given"]) for f in sp["flagged"]] == [(leo["id"], "28000.00")]
    assert jane.get("/ui/api/gifts/spending?year=2026").json()["flagged"] == []


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
    # Not in the Inbox while kept with the gift; detached, it is again.
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


def test_deleting_a_person_deletes_every_gift_plan_for_them(server, jane):
    """S7.8.6: the person's gift plans go with them, whoever's they are: Jane's, and John's,
    which she can't see."""
    from moolakata.store.entities.education import GiftPlan

    make_user(server, "john", sex="male")
    john = sign_in(server, "john")
    sam = person(jane, name="Sam Lee", sex="male")
    his = make(john, "GfPln", personId=sam["id"])
    assert his.status_code == 200, his.text
    his = his.json()
    r = remove(jane, "Persn", jane.get(f"/ui/api/persons/{sam['id']}").json())
    assert r.status_code == 200, r.text
    assert jane.get("/ui/api/gift-plans").json()["items"] == []
    assert john.get("/ui/api/gift-plans").json()["items"] == []
    with server.db.read(unscoped="test: the plans' rows") as s:
        for plan_id in (sam["plan"]["id"], his["id"]):
            gp = s.get(GiftPlan, plan_id)
            assert gp.deleted and gp.version == 2, plan_id
