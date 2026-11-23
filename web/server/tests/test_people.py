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
    make_user(server, "jane", admin=False)
    make_user(server, "john", sex="male")
    return sign_in(server, "jane"), sign_in(server, "john")


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
    jane, _ = two
    p = jane.get("/ui/api/profile").json()
    assert p["personId"].startswith("Persn_") and p["sex"] == "female"
    r = change(jane, "User", p, displayName="Jane Doe", birthMonth=4, birthDay=12,
               birthYear=1979)  # fmt: skip
    assert saved(r)["displayName"] == "Jane Doe"
    row = next(x for x in jane.get("/ui/api/persons").json()["items"] if x["id"] == p["personId"])
    assert (row["name"], row["birthYear"], row["relation"]) == ("Jane Doe", 1979, "you")


def test_profile_lists_the_children_oldest_first(server, two):
    # S10.10.7: whenever they were added, a person's children are listed oldest first, one
    # whose birth year isn't known last.
    jane, _ = two
    a = me(jane)
    for name, year in (("Young", 2019), ("Unknown", None), ("Old", 2010), ("Mid", 2015)):
        kid = add(jane, name, birthYear=year) if year else add(jane, name)
        relate(jane, a, kid["id"], "child")
    words = [(x["name"], x["word"]) for x in jane.get("/ui/api/profile").json()["relations"]]
    assert words == [
        ("Old", "daughter"),
        ("Mid", "daughter"),
        ("Young", "daughter"),
        ("Unknown", "daughter"),
    ]


def test_one_person_once_and_asking_to_share_a_private_one(server, two):
    jane, john = two
    jsmith = add(jane, "John Smith", private=True, birthYear=1985)
    assert "John Smith" not in {x["name"] for x in john.get("/ui/api/persons").json()["items"]}
    r = make(john, "Persn", name="john smith", sex="male")
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "person-exists"
    # The dialog then reads who it would be (S10.10.3).
    clash = john.get("/ui/api/persons/clash", params={"name": "john smith"}).json()
    assert clash == {
        "id": jsmith["id"],
        "name": "John Smith",
        "visible": False,
        "private": True,
        "createdBy": "Jane",
    }
    # A different person is told apart by both birth years.
    r = make(john, "Persn", name="John Smith", sex="male", differentPerson=True)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "birthYear"
    other = make(john, "Persn", name="John Smith", sex="male", birthYear=1990, differentPerson=True)
    assert other.status_code == 200
    # Asking to share raises an alert for whoever added her, and for the admins.
    assert john.post(f"/ui/api/persons/{jsmith['id']}/ask-to-share").json() == {"asked": True}
    opened = alerts.evaluate(server)
    assert sorted((a.kind, a.userId is None) for a in opened) == [
        ("share-asked", False),
        ("share-asked", True),
    ]
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    r = share(jane, "person", jsmith["id"], users={john_id: "read"})
    assert r.status_code == 200, r.text
    assert "John Smith" in {x["name"] for x in john.get("/ui/api/persons").json()["items"]}
    alerts.evaluate(server)
    with server.db.read(unscoped="test") as s:
        from moolakata.store.entities.alerts import Alert

        assert all(a.resolvedAt for a in s.query(Alert).filter_by(kind="share-asked"))


def test_only_the_person_their_creator_or_an_admin_changes_them(server, two):
    jane, john = two
    lisa = add(jane, "Lisa Doe", birthYear=2018)
    r = change(john, "Persn", lisa, birthYear=2017)
    assert r.status_code == 403
    assert saved(change(jane, "Persn", lisa, birthYear=2017))["birthYear"] == 2017
    # A user's own person is theirs; it can't be deleted while they are a user.
    mine = jane.get("/ui/api/profile").json()["personId"]
    r = remove(jane, "Persn", jane.get(f"/ui/api/persons/{mine}").json())
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "person-is-user"


def test_relationships_are_added_by_those_in_them_and_kept_sound(server, two):
    jane, john = two
    a, b = me(jane), me(john)
    lisa = add(jane, "Lisa Doe")
    bart = add(jane, "Bart Doe", "male")
    sp = relate(jane, b, a, "spouse", fromDate="2009-06-14")
    assert sorted([sp["person1"]["id"], sp["person2"]["id"]]) == sorted([a, b])
    assert sp["person1"]["id"] < sp["person2"]["id"], "a two-way relation is kept ordered"
    relate(jane, a, lisa["id"], "child")
    # John isn't in Lisa and Bart's relationship, and isn't an admin.
    r = make(john, "Rltn", person1Id=lisa["id"], person2Id=bart["id"], relation="family")
    assert r.status_code == 403
    # At most one spouse at a time.
    r = make(jane, "Rltn", person1Id=a, person2Id=bart["id"], relation="spouse")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "one-spouse"
    # No one is their own ancestor.
    r = make(jane, "Rltn", person1Id=lisa["id"], person2Id=a, relation="child")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "ancestor-loop"
    words = {x["name"]: x["word"] for x in jane.get("/ui/api/profile").json()["relations"]}
    assert words == {"John": "husband", "Lisa Doe": "daughter"}


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
    with db.tx(unscoped="test") as s:
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


def test_a_death_keeps_the_in_laws_and_step_family_a_divorce_ends(db):
    """S10.10.5: a marriage ended by death keeps the in-laws and step-family through it, and
    the dead spouse's family stays joined; a divorce ends them. A survivor who remarries has
    both families' in-laws."""
    with db.tx(unscoped="test") as s:

        def p(name, sex, died=None):
            x = Person(id=f"Persn_{name.lower():0<26}"[:32], name=name, sex=sex, diedOn=died)
            s.add(x)
            return x

        ann, bob = p("Ann", "female"), p("Bob", "male", dt.date(2020, 6, 1))
        mae, kid, sib = p("Mae", "female"), p("Kid", "male"), p("Sib", "female")
        cal, rue = p("Cal", "male"), p("Rue", "female")
        dee, ed = p("Dee", "female"), p("Ed", "male", dt.date(2021, 3, 1))
        xan, xma = p("Xan", "male"), p("Xma", "female")
        s.flush()

        def r(a, b, relation, since=None, until=None):
            x, y = people.ordered(relation, a.id, b.id)
            s.add(Relationship(id=f"Rltn_{a.name}{b.name}{relation}".ljust(31, "0")[:31],
                               person1Id=x, person2Id=y, relation=relation, fromDate=since,
                               toDate=until))  # fmt: skip

        r(ann, xan, "spouse", dt.date(1990, 1, 1), dt.date(1999, 1, 1))
        r(xma, xan, "child")
        r(ann, bob, "spouse", dt.date(2000, 1, 1))
        for x in (bob, sib):
            r(mae, x, "child")
        r(bob, kid, "child")
        r(ann, cal, "spouse", dt.date(2022, 1, 1))
        r(rue, cal, "child")
        r(ann, dee, "child")
        r(dee, ed, "spouse", dt.date(2010, 1, 1))
        s.flush()

        def words(who, day):
            return {
                s.get(Person, x.personId).name: x.word
                for x in tree.relations(s, who.id, dt.date(*day))
            }

        before = words(ann, (2019, 1, 1))
        after = words(ann, (2021, 1, 1))
        assert before == {"Bob": "husband", "Kid": "stepson", "Mae": "mother-in-law",
                          "Sib": "sister-in-law", "Dee": "daughter", "Ed": "son-in-law",
                          "Xan": "ex-husband"}  # fmt: skip
        assert after == before
        assert words(kid, (2021, 1, 1))["Ann"] == "stepmother"
        assert words(mae, (2021, 1, 1))["Ann"] == "daughter-in-law"
        remarried = words(ann, (2023, 1, 1))
        assert (remarried["Cal"], remarried["Rue"], remarried["Mae"], remarried["Ed"]) == (
            "husband",
            "mother-in-law",
            "mother-in-law",
            "son-in-law",
        )
        assert "Xma" not in remarried, "a divorce ends the in-laws through it"


def test_wash_sales_count_the_spouse_on_the_day_of_the_sale(server, two):
    jane, john = two
    a, b = me(jane), me(john)
    mine = new_account(jane, name="Jane's brokerage", type="brokerage")
    his = new_account(john, name="John's brokerage", type="brokerage")
    trade(jane, mine["id"], "2025-03-01", "buy", "10", "200", "AAPL")
    trade(jane, mine["id"], "2026-06-01", "sell", "10", "150", "AAPL")  # a 500 loss
    trade(john, his["id"], "2026-06-10", "buy", "10", "155", "AAPL")

    def realized():
        v = jane.get("/ui/api/positions").json()
        return next(r for r in v["closed"] if r["symbol"] == "AAPL")["realized"]

    assert realized() == "-500.00", "not married: John's buy is his own"
    made = relate(jane, a, b, "spouse", fromDate="2026-07-01")
    assert made["confirmed"] is False and [w["id"] for w in made["waitingFor"]] == [b]
    assert not made["canConfirm"]
    assert jane.post(f"/ui/api/relationships/{made['id']}/confirm").status_code == 403
    assert john.post(f"/ui/api/relationships/{made['id']}/confirm").json()["confirmed"] is True
    assert realized() == "-500.00", "married after the sale"
    rel = jane.get("/ui/api/relationships").json()["items"][0]
    r = change(jane, "Rltn", rel, fromDate="2009-06-14")
    assert saved(r)["confirmed"] is False, "a changed marriage is confirmed again"
    assert realized() == "-500.00", "Jane alone can't make John's trades hers"
    waiting = john.get("/ui/api/relationships").json()["items"][0]
    assert waiting["canConfirm"]
    assert john.post(f"/ui/api/relationships/{rel['id']}/confirm").status_code == 200
    assert realized() == "0.00", "married on the day: the whole loss is disallowed"


def test_a_joint_book_needs_a_marriage_on_the_last_day_or_a_death_that_year(server, two):
    jane, john = two
    a, b = me(jane), me(john)
    a_id = jane.get("/ui/api/session").json()["user"]["id"]
    b_id = john.get("/ui/api/session").json()["user"]["id"]
    made = relate(jane, a, b, "spouse", fromDate="2009-06-14", toDate="2025-06-01")

    def joint(year):
        return make(jane, "TaxBk", year=year, filers=[a_id, b_id])

    assert joint(2024).status_code == 422, "not yet confirmed by John"
    assert john.post(f"/ui/api/relationships/{made['id']}/confirm").status_code == 200
    assert joint(2024).status_code == 200
    assert joint(2025).status_code == 422, "divorced before the year ended"
    with server.db.tx(unscoped="test") as s:
        rel = s.query(Relationship).one()
        rel.toDate = None
        s.get(Person, b).diedOn = dt.date(2025, 6, 1)
    assert joint(2025).status_code == 200, "widowed in the year: still joint"
    assert joint(2026).status_code == 422


def test_a_gift_plans_person_keeps_their_death_and_only_its_creator_makes_them_private(two):
    jane, john = two
    r = make(jane, "GfPln", name="Ruth Doe", sex="female", birthYear=1940)
    assert r.status_code == 200, r.text
    ruth = jane.get(f"/ui/api/persons/{r.json()['personId']}").json()
    assert ruth["canMakePrivate"] and ruth["userId"] is None and not ruth["private"]
    person = ruth
    r = change(jane, "Persn", person, diedOn="2030-01-01")
    assert r.json()["errors"][0]["code"] == "died-on-invalid"
    r = saved(change(jane, "Persn", person, diedOn="2026-03-02", private=True))
    assert (r["diedOn"], r["private"]) == ("2026-03-02", True)
    # Shared with John, who plans for her too but may not make her public again.
    pid = r["id"]
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    assert share(jane, "person", pid, users={john_id: "read"}).status_code == 200
    r = make(john, "GfPln", personId=pid)
    assert r.status_code == 200, r.text
    plan = r.json()
    hers = john.get(f"/ui/api/persons/{pid}").json()
    assert not hers["canMakePrivate"] and not hers["access"]["writable"]
    saved(change(john, "GfPln", plan, notes="likes tea"))
    r = change(john, "Persn", hers, private=False)
    assert r.status_code == 403, "John reads Ruth, so he may not change her"
    assert john.get(f"/ui/api/persons/{pid}").json()["private"]


def test_a_person_who_is_a_user_is_never_made_private(server, two, admin_client):
    """S10.10.1, S10.10.2: every user is a person the household sees; neither whoever added
    them before they became a user, nor an admin, nor the user, makes them private."""
    from moolakata import ids
    from moolakata.store.entities.users import User

    jane, john = two
    bob = add(admin_client, "Bob Ray", sex="male")
    with server.db.tx(unscoped="test: Bob Ray signs in, as the person the admin added") as s:
        s.add(User(id=ids.new_id("User"), personId=bob["id"], username="bob",
                   displayName="Bob Ray", email="bob@home.lan", passwordHash="x"))  # fmt: skip
    seen = admin_client.get(f"/ui/api/persons/{bob['id']}").json()
    assert seen["userId"] and not seen["canMakePrivate"]
    for c, pid in ((admin_client, bob["id"]), (john, me(john))):
        r = change(c, "Persn", c.get(f"/ui/api/persons/{pid}").json(), private=True)
        assert r.status_code == 422, r.text
        assert [(e["field"], e["code"]) for e in r.json()["errors"]] == [
            ("private", "person-is-user")
        ]
    assert not jane.get(f"/ui/api/persons/{bob['id']}").json()["private"]


def test_a_relationship_is_changed_and_removed_with_its_version(two):
    jane, john = two
    a, b = me(jane), me(john)
    r = relate(jane, a, b, "spouse", fromDate="2009-06-14")
    r2 = saved(change(jane, "Rltn", r, toDate="2015-03-02"))
    assert r2["endsOn"] == "2015-03-02"
    rows = jane.get("/ui/api/relationships").json()["items"]
    assert [x["toDate"] for x in rows] == ["2015-03-02"]
    assert remove(jane, "Rltn", r).status_code == 412, "the version it was read at"
    r3 = remove(jane, "Rltn", r2)
    assert r3.status_code == 200, r3.text
    assert jane.get("/ui/api/relationships").json()["items"] == []


def test_a_person_who_becomes_a_user_is_theirs_to_change(server, two):
    """S10.10.2: whoever made a person before they were invited no longer changes them."""
    from moolakata.auth import users as accounts
    from moolakata.store.entities.users import User

    jane, _ = two
    made = make(jane, "Persn", name="Dana Ortiz", sex="female")
    assert made.status_code == 200, made.text
    person = made.json()
    assert person["access"]["writable"]
    from moolakata import settings

    with server.db.tx(unscoped="test") as s:  # invited under the same name, she becomes that person
        settings.put(s, "publicUrl", "https://money.home.lan", None)
        admin = s.query(User).filter(User.username == "admin").one()
        dana = accounts.invite(
            s, server.services, admin, "Dana Ortiz", "dana", "dana@home.lan", [], "female"
        )
        assert dana.personId == person["id"]
    mine = next(p for p in jane.get("/ui/api/persons").json()["items"] if p["id"] == person["id"])
    assert not mine["access"]["writable"]
    r = change(jane, "Persn", mine, birthYear=1990)
    assert r.status_code == 403
