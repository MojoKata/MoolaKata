"""People and relationships (requirements S10.10): every user is a person, people are the
household's unless private, one person is added once, who may change a person, relationships
and their rules, the family tree worked out as of a day, and the spouse on the day for wash
sales (S3.8) and joint tax books (S8.14.1)."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, make, remove, saved, share
from test_accounts import new_account
from test_positions import trade

from moolakata import alerts, clock, people
from moolakata.people import tree
from moolakata.store.entities.education import Person, Relationship

T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def two(server, frozen):
    make_user(server, "alice", admin=False)
    make_user(server, "bob", sex="male")
    return sign_in(server, "alice"), sign_in(server, "bob")


def me(c) -> str:
    return c.get("/ui/api/profile").json()["personId"]


def add(c, name, sex="female", **kw):
    r = make(c, "Persn", **{"name": name, "sex": sex, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def relate(c, a, b, relation, **kw):
    r = make(c, "Rltn", **{"person1Id": a, "person2Id": b, "relation": relation, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_every_user_is_a_person_with_their_sex_and_birthday(two):
    alice, _ = two
    p = alice.get("/ui/api/profile").json()
    assert p["personId"].startswith("Persn_") and p["sex"] == "female"
    r = change(alice, "User", p, displayName="Alice Griffin", birthMonth=4, birthDay=12,
               birthYear=1979)  # fmt: skip
    assert saved(r)["displayName"] == "Alice Griffin"
    row = next(x for x in alice.get("/ui/api/persons").json()["items"] if x["id"] == p["personId"])
    assert (row["name"], row["birthYear"], row["relation"]) == ("Alice Griffin", 1979, "you")


def test_one_person_once_and_asking_to_share_a_private_one(server, two):
    alice, bob = two
    priya = add(alice, "Priya Shah", private=True, birthYear=1985)
    assert "Priya Shah" not in {x["name"] for x in bob.get("/ui/api/persons").json()["items"]}
    r = make(bob, "Persn", name="priya shah", sex="female")
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "person-exists"
    # The dialog then reads who it would be (S10.10.3).
    clash = bob.get("/ui/api/persons/clash", params={"name": "priya shah"}).json()
    assert clash == {
        "id": priya["id"],
        "name": "Priya Shah",
        "visible": False,
        "private": True,
        "createdBy": "Alice",
    }
    # A different person is told apart by both birth years.
    r = make(bob, "Persn", name="Priya Shah", sex="female", differentPerson=True)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "birthYear"
    other = make(
        bob, "Persn", name="Priya Shah", sex="female", birthYear=1990, differentPerson=True
    )
    assert other.status_code == 200
    # Asking to share raises an alert for whoever added her, and for the admins.
    assert bob.post(f"/ui/api/persons/{priya['id']}/ask-to-share").json() == {"asked": True}
    opened = alerts.evaluate(server)
    assert sorted((a.kind, a.userId is None) for a in opened) == [
        ("share-asked", False),
        ("share-asked", True),
    ]
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    r = share(alice, "person", priya["id"], users={bob_id: "read"})
    assert r.status_code == 200, r.text
    assert "Priya Shah" in {x["name"] for x in bob.get("/ui/api/persons").json()["items"]}
    alerts.evaluate(server)
    with server.db.read() as s:
        from moolakata.store.entities.alerts import Alert

        assert all(a.resolvedAt for a in s.query(Alert).filter_by(kind="share-asked"))


def test_only_the_person_their_creator_or_an_admin_changes_them(server, two):
    alice, bob = two
    emma = add(alice, "Emma Griffin", birthYear=2018)
    r = change(bob, "Persn", emma, birthYear=2017)
    assert r.status_code == 403
    assert saved(change(alice, "Persn", emma, birthYear=2017))["birthYear"] == 2017
    # A user's own person is theirs; it can't be deleted while they are a user.
    mine = alice.get("/ui/api/profile").json()["personId"]
    r = remove(alice, "Persn", alice.get(f"/ui/api/persons/{mine}").json())
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "person-is-user"


def test_relationships_are_added_by_those_in_them_and_kept_sound(server, two):
    alice, bob = two
    a, b = me(alice), me(bob)
    emma = add(alice, "Emma Griffin")
    carol = add(alice, "Carol Griffin")
    sp = relate(alice, b, a, "spouse", fromDate="2009-06-14")
    assert sorted([sp["person1"]["id"], sp["person2"]["id"]]) == sorted([a, b])
    assert sp["person1"]["id"] < sp["person2"]["id"], "a two-way relation is kept ordered"
    relate(alice, a, emma["id"], "child")
    # Bob isn't in Emma and Carol's relationship, and isn't an admin.
    r = make(bob, "Rltn", person1Id=emma["id"], person2Id=carol["id"], relation="family")
    assert r.status_code == 403
    # At most one spouse at a time.
    r = make(alice, "Rltn", person1Id=a, person2Id=carol["id"], relation="spouse")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "one-spouse"
    # No one is their own ancestor.
    r = make(alice, "Rltn", person1Id=emma["id"], person2Id=a, relation="child")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "ancestor-loop"
    words = {x["name"]: x["word"] for x in alice.get("/ui/api/profile").json()["relations"]}
    assert words == {"Bob": "husband", "Emma Griffin": "daughter"}


def family(s):
    """Three generations, a divorce, a remarriage and a death, made straight in the store."""

    def p(name, sex, died=None):
        x = Person(id=f"Persn_{name.lower():0<26}"[:32], name=name, sex=sex, diedOn=died)
        s.add(x)
        return x

    gma, gpa = p("Gma", "female"), p("Gpa", "male", dt.date(2020, 5, 1))
    mum, dad, aunt = p("Mum", "female"), p("Dad", "male"), p("Aunt", "female")
    me_, sis, half = p("Me", "female"), p("Sis", "female"), p("Half", "male")
    step, stepkid, cousin = p("Step", "female"), p("Stepkid", "male"), p("Cousin", "male")
    wife, kid, inlaw = p("Wife", "female"), p("Kid", "male"), p("Inlaw", "female")
    s.flush()

    def r(a, b, relation, since=None, until=None):
        x, y = people.ordered(relation, a.id, b.id)
        s.add(
            Relationship(
                id=f"Rltn_{a.name.lower()}{b.name.lower()}{relation}".ljust(31, "0")[:31],
                person1Id=x,
                person2Id=y,
                relation=relation,
                fromDate=since,
                toDate=until,
            )
        )

    r(gma, gpa, "spouse", dt.date(1960, 1, 1))
    for kid_ in (mum, aunt):
        r(gma, kid_, "child")
        r(gpa, kid_, "child")
    r(mum, dad, "spouse", dt.date(1985, 1, 1), dt.date(2000, 1, 1))
    for kid_ in (me_, sis):
        r(mum, kid_, "child")
        r(dad, kid_, "child")
    r(dad, step, "spouse", dt.date(2005, 1, 1))
    r(dad, half, "child")
    r(step, half, "child")
    r(step, stepkid, "child")
    r(aunt, cousin, "child")
    r(me_, wife, "spouse", dt.date(2015, 1, 1))
    r(inlaw, wife, "child")
    r(me_, kid, "child")
    s.flush()
    return {x.name: x.id for x in s.query(Person)}


def test_the_family_tree_is_worked_out_as_of_a_day(db):
    with db.tx() as s:
        ids = family(s)
        now = {
            s.get(Person, r.personId).name: r.word
            for r in tree.relations(s, ids["Me"], dt.date(2026, 1, 1))
        }
        assert now == {
            "Wife": "wife",
            "Mum": "mother",
            "Dad": "father",
            "Kid": "son",
            "Sis": "sister",
            "Half": "half-brother",
            "Gma": "grandmother",
            "Gpa": "grandfather",
            "Aunt": "aunt",
            "Cousin": "cousin",
            "Step": "stepmother",
            "Stepkid": "stepbrother",
            "Inlaw": "mother-in-law",
        }
        # Before Dad's remarriage there was no stepmother, and Mum and Dad were married.
        then = {
            s.get(Person, r.personId).name: r.word
            for r in tree.relations(s, ids["Me"], dt.date(1999, 1, 1))
        }
        assert then.get("Step") != "stepmother" and then["Dad"] == "father"
        mum = {
            s.get(Person, r.personId).name: r.word
            for r in tree.relations(s, ids["Mum"], dt.date(1999, 1, 1))
        }
        assert mum["Dad"] == "husband"
        later = {
            s.get(Person, r.personId).name: r.word
            for r in tree.relations(s, ids["Mum"], dt.date(2026, 1, 1))
        }
        assert later["Dad"] == "ex-husband"
        gma = {
            s.get(Person, r.personId).name: r.word
            for r in tree.relations(s, ids["Gma"], dt.date(2026, 1, 1))
        }
        assert gma["Gpa"] == "husband" and gma["Kid"] == "great-grandson"
        gpa = {
            s.get(Person, r.personId).name: r.word
            for r in tree.relations(s, ids["Gpa"], dt.date(2026, 1, 1))
        }
        assert gpa["Gma"] == "widow"


def test_wash_sales_count_the_spouse_on_the_day_of_the_sale(server, two):
    alice, bob = two
    a, b = me(alice), me(bob)
    mine = new_account(alice, name="Alice's brokerage", type="brokerage")
    his = new_account(bob, name="Bob's brokerage", type="brokerage")
    trade(alice, mine["id"], "2025-03-01", "buy", "10", "200", "AAPL")
    trade(alice, mine["id"], "2026-06-01", "sell", "10", "150", "AAPL")  # a 500 loss
    trade(bob, his["id"], "2026-06-10", "buy", "10", "155", "AAPL")

    def realized():
        v = alice.get("/ui/api/positions").json()
        return next(r for r in v["closed"] if r["symbol"] == "AAPL")["realized"]

    assert realized() == "-500.00", "not married: Bob's buy is his own"
    made = relate(alice, a, b, "spouse", fromDate="2026-07-01")
    assert made["confirmed"] is False and [w["id"] for w in made["waitingFor"]] == [b]
    assert not made["canConfirm"]
    assert alice.post(f"/ui/api/relationships/{made['id']}/confirm").status_code == 403
    assert bob.post(f"/ui/api/relationships/{made['id']}/confirm").json()["confirmed"] is True
    assert realized() == "-500.00", "married after the sale"
    rel = alice.get("/ui/api/relationships").json()["items"][0]
    r = change(alice, "Rltn", rel, fromDate="2009-06-14")
    assert saved(r)["confirmed"] is False, "a changed marriage is confirmed again"
    assert realized() == "-500.00", "Alice alone can't make Bob's trades hers"
    waiting = bob.get("/ui/api/relationships").json()["items"][0]
    assert waiting["canConfirm"]
    assert bob.post(f"/ui/api/relationships/{rel['id']}/confirm").status_code == 200
    assert realized() == "0.00", "married on the day: the whole loss is disallowed"


def test_a_joint_book_needs_a_marriage_on_the_last_day_or_a_death_that_year(server, two):
    alice, bob = two
    a, b = me(alice), me(bob)
    a_id = alice.get("/ui/api/session").json()["user"]["id"]
    b_id = bob.get("/ui/api/session").json()["user"]["id"]
    made = relate(alice, a, b, "spouse", fromDate="2009-06-14", toDate="2025-06-01")

    def joint(year):
        return make(alice, "TaxBk", year=year, filers=[a_id, b_id])

    assert joint(2024).status_code == 422, "not yet confirmed by Bob"
    assert bob.post(f"/ui/api/relationships/{made['id']}/confirm").status_code == 200
    assert joint(2024).status_code == 200
    assert joint(2025).status_code == 422, "divorced before the year ended"
    with server.db.tx() as s:
        rel = s.query(Relationship).one()
        rel.toDate = None
        s.get(Person, b).diedOn = dt.date(2025, 6, 1)
    assert joint(2025).status_code == 200, "widowed in the year: still joint"
    assert joint(2026).status_code == 422


def test_a_gift_plans_person_keeps_their_death_and_only_its_creator_makes_them_private(two):
    alice, bob = two
    r = make(alice, "GfPln", name="Ruth Griffin", sex="female", birthYear=1940)
    assert r.status_code == 200, r.text
    ruth = r.json()
    assert ruth["canMakePrivate"] and not ruth["isUser"] and not ruth["private"]
    person = {"id": ruth["id"], "version": ruth["personVersion"]}
    r = change(alice, "Persn", person, diedOn="2030-01-01")
    assert r.json()["errors"][0]["code"] == "died-on-invalid"
    r = saved(change(alice, "Persn", person, diedOn="2026-03-02", private=True))
    assert (r["diedOn"], r["private"]) == ("2026-03-02", True)
    # Shared with Bob, who plans for her too but may not make her public again.
    pid = r["id"]
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    assert share(alice, "person", pid, users={bob_id: "read"}).status_code == 200
    r = make(bob, "GfPln", personId=pid)
    assert r.status_code == 200, r.text
    assert not r.json()["canMakePrivate"]
    plan = {"id": r.json()["planId"], "version": r.json()["version"]}
    saved(change(bob, "GfPln", plan, notes="likes tea"))
    r = change(bob, "Persn", r.json() | {"version": r.json()["personVersion"]}, private=False)
    assert r.status_code == 403, "Bob reads Ruth, so he may not change her"
    assert bob.get(f"/ui/api/people/{pid}").json()["private"]


def test_a_relationship_is_changed_and_removed_with_its_version(two):
    alice, bob = two
    a, b = me(alice), me(bob)
    r = relate(alice, a, b, "spouse", fromDate="2009-06-14")
    r2 = saved(change(alice, "Rltn", r, toDate="2015-03-02"))
    assert r2["endsOn"] == "2015-03-02"
    rows = alice.get("/ui/api/relationships").json()["items"]
    assert [x["toDate"] for x in rows] == ["2015-03-02"]
    assert remove(alice, "Rltn", r).status_code == 412, "the version it was read at"
    r3 = remove(alice, "Rltn", r2)
    assert r3.status_code == 200, r3.text
    assert alice.get("/ui/api/relationships").json()["items"] == []


def test_a_person_who_becomes_a_user_is_theirs_to_change(server, two):
    """S10.10.2 (P5): whoever made a person before they were invited no longer changes them."""
    from moolakata.auth import users as accounts
    from moolakata.store.entities.users import User

    alice, _ = two
    made = make(alice, "Persn", name="Dana Ortiz", sex="female")
    assert made.status_code == 200, made.text
    person = made.json()
    assert person["canChange"]
    from moolakata import settings

    with server.db.tx() as s:  # invited under the same name, she becomes that person
        settings.put(s, "publicUrl", "https://money.home.lan", None)
        admin = s.query(User).filter(User.username == "admin").one()
        dana = accounts.invite(
            s, server.services, admin, "Dana Ortiz", "dana", "dana@home.lan", [], "female"
        )
        assert dana.personId == person["id"]
    mine = next(p for p in alice.get("/ui/api/persons").json()["items"] if p["id"] == person["id"])
    assert not mine["canChange"]
    r = change(alice, "Persn", mine, birthYear=1990)
    assert r.status_code == 403
