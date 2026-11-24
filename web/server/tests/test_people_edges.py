"""People, relationships and the family tree at their edges (requirements S10.10): each
refusal at its field with its code and words, what no longer is or isn't the caller's, and
what is worked out for no one."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, make, new_id, remove, saved
from test_people import T0, add, me, relate

from moolakata import clock, people
from moolakata.errors import Problem
from moolakata.people import tree
from moolakata.store.entities.education import Person, Relationship


@pytest.fixture
def two(server):
    clock.fix(T0)
    make_user(server, "jane", admin=False)
    make_user(server, "john", sex="male")
    yield sign_in(server, "jane"), sign_in(server, "john")
    clock.fix(None)


def refused(r, field, code, words, status=422):
    assert r.status_code == status, r.text
    e = r.json()["errors"][0]
    assert (e["field"], e["code"], e["message"]) == (field, code, words)


def problem(r, status, code, words):
    assert r.status_code == status, r.text
    assert (r.json()["code"], r.json()["detail"]) == (code, words)


# ---- A person's fields (S10.10.1) ----


@pytest.mark.parametrize(
    ("fields", "field", "code", "words"),
    [
        ({"name": " "}, "name", "name-invalid", "A name, up to 80 characters."),
        ({"name": "A" * 81}, "name", "name-invalid", "A name, up to 80 characters."),
        ({"sex": "other"}, "sex", "sex-invalid", "Female or male."),
        ({"birthMonth": 13, "birthDay": 1}, "birthMonth", "month-invalid", "A month, 1 to 12."),
        ({"birthMonth": 5, "birthDay": 32}, "birthDay", "day-invalid", "A day, 1 to 31."),
        ({"birthMonth": 5}, "birthDay", "birthday-incomplete", "A month and a day."),
        ({"birthDay": 5}, "birthDay", "birthday-incomplete", "A month and a day."),
        ({"birthYear": 1905}, "birthYear", "year-invalid", "A year of birth."),
        ({"birthYear": 2027}, "birthYear", "year-invalid", "A year of birth."),
        ({"diedOn": "2026-10-14"}, "diedOn", "died-on-invalid",
         "A day since their birth, not ahead."),
        ({"birthYear": 1950, "diedOn": "1949-12-31"}, "diedOn", "died-on-invalid",
         "A day since their birth, not ahead."),
    ],
)  # fmt: skip
def test_a_persons_fields_are_refused_at_their_field(two, fields, field, code, words):
    jane, _ = two
    body = {"name": "Ruth Doe", "sex": "female", **fields}
    refused(make(jane, "Persn", **body), field, code, words)


def test_a_persons_fields_take_their_edges(two):
    jane, _ = two
    ruth = add(jane, "A" * 80, birthYear=1906, birthMonth=12, birthDay=31, diedOn="2026-10-13")
    assert (ruth["birthYear"], ruth["diedOn"]) == (1906, "2026-10-13")


def test_only_whoever_added_a_person_makes_them_private(two, admin_client):
    """S10.10.2: an admin changes anyone's person, but making them private is their creator's."""
    jane, _ = two
    ruth = add(jane, "Ruth Doe")
    seen = admin_client.get(f"/ui/api/persons/{ruth['id']}").json()
    refused(change(admin_client, "Persn", seen, private=True), "private", "not-creator",
            "Only whoever added them makes them private.")  # fmt: skip
    assert saved(change(admin_client, "Persn", seen, birthYear=1950))["birthYear"] == 1950


def test_a_new_persons_sex_is_one_of_the_two(db):
    """S10.10.1: the store's own maker refuses any other, at the field."""
    with db.tx(unscoped="test") as s, pytest.raises(Problem) as e:
        people.make(s, "Ruth", "other")
    assert (e.value.status, [(x.field, x.code) for x in e.value.errors]) == (
        422,
        [("sex", "sex-invalid")],
    )


# ---- Joining and asking to share (S10.10.1, S10.10.3) ----


def test_only_a_remote_user_is_joined_to_a_person(server, two):
    jane, john = two
    ruth = add(jane, "Ruth Doe")
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    for user_id in (john_id, "Usr_nobody"):
        r = jane.post(f"/ui/api/persons/{ruth['id']}/join", json={"userId": user_id})
        problem(r, 404, "not-found", "Not found")


def test_a_user_not_offered_is_never_joined(db):
    """S10.10.1: only one of the users `may_join` offers is joined; any other is refused."""
    with db.tx(unscoped="test") as s:
        p = people.make(s, "Ruth", "female")
        with pytest.raises(Problem) as e:
            people.join(s, "Usr_nobody", p, object())
    assert (e.value.status, e.value.code) == (409, "cannot-join")


def test_asking_to_share_a_person_already_seen_or_not_there(two):
    jane, john = two
    mine = add(jane, "Ruth Doe", private=True)
    assert jane.post(f"/ui/api/persons/{mine['id']}/ask-to-share").json() == {"asked": False}
    for pid in (new_id("Persn"), add(jane, "Sam Doe", "male")["id"]):
        problem(john.post(f"/ui/api/persons/{pid}/ask-to-share"), 404, "not-found", "Not found")


# ---- Relationships (S10.10.4) ----


def test_a_relationship_is_refused_at_its_field(two):
    jane, _ = two
    a = me(jane)
    lisa = add(jane, "Lisa Doe")
    rel = {"person1Id": a, "person2Id": lisa["id"]}
    refused(make(jane, "Rltn", **rel, relation="cousin"), "relation", "relation-invalid",
            "One of the relations.")  # fmt: skip
    refused(make(jane, "Rltn", person1Id=a, person2Id=a, relation="family"), "person2Id",
            "same-person", "Two different people.")  # fmt: skip
    refused(make(jane, "Rltn", **rel, relation="family", fromDate="2020-01-02",
                 toDate="2020-01-01"), "toDate", "dates-invalid",
            "It ends after it begins.")  # fmt: skip
    relate(jane, a, lisa["id"], "friend", fromDate="2020-01-01")
    refused(make(jane, "Rltn", **rel, relation="friend", fromDate="2020-01-01"), "relation",
            "relationship-exists", "That relationship is already here.", 409)  # fmt: skip


def test_a_relationship_is_changed_by_those_in_it_and_once_gone_is_not_found(two, admin_client):
    jane, john = two
    lisa, bart = add(jane, "Lisa Doe"), add(jane, "Bart Doe", "male")
    r = relate(jane, me(jane), lisa["id"], "child")
    theirs = relate(admin_client, lisa["id"], bart["id"], "family", label="Cousins")
    refused(change(john, "Rltn", theirs, label="Pals"), None, "not-in-it",
            "You change relationships you are in; an admin any.", 403)  # fmt: skip
    assert remove(jane, "Rltn", r).status_code == 200
    refused(change(jane, "Rltn", r, fromDate="2018-01-01"), None, "not-found", "Not found", 404)


def test_only_a_marriage_is_confirmed_and_by_its_other_spouse(two):
    """S10.10.4: confirming a relationship that isn't a marriage, one already confirmed on
    the caller's side, or one no longer there is refused."""
    jane, john = two
    lisa = add(jane, "Lisa Doe")
    child = relate(jane, me(jane), lisa["id"], "child")
    problem(jane.post(f"/ui/api/relationships/{child['id']}/confirm"), 409, "not-a-marriage",
            "Only a marriage is confirmed.")  # fmt: skip
    wed = relate(jane, me(jane), me(john), "spouse", fromDate="2009-11-02")
    problem(jane.post(f"/ui/api/relationships/{wed['id']}/confirm"), 403,
            "not-yours-to-confirm", "Only the other spouse confirms this.")  # fmt: skip
    problem(jane.post(f"/ui/api/relationships/{new_id('Rltn')}/confirm"), 404, "not-found",
            "Not found")  # fmt: skip


# ---- What is worked out for no one (S10.10.4, S8.14.1) ----


def test_a_user_with_no_person_has_no_spouse_and_files_alone(db):
    with db.tx(unscoped="test") as s:
        day = dt.date(2026, 6, 1)
        assert people.spouse_user_on(s, "Usr_nobody", day) is None
        assert people.spouse_users_ever(s, "Usr_nobody") == set()
        assert people.joint_filers(s, "Usr_nobody", "Usr_noone", 2026) is False


# ---- The family tree (S10.10.5) ----


def _tree(s, ego: str, day=dt.date(2026, 1, 1)) -> dict[str, str]:
    return {s.get(Person, r.personId).name: r.word for r in tree.relations(s, ego, day)}


def _people(s, *names_sexes) -> dict[str, str]:
    out = {}
    for name, sex in names_sexes:
        p = Person(id=new_id("Persn"), name=name, sex=sex)
        s.add(p)
        out[name] = p.id
    s.flush()
    return out


def _rel(s, a: str, b: str, relation: str, **kw) -> Relationship:
    x, y = people.ordered(relation, a, b)
    r = Relationship(id=new_id("Rltn"), person1Id=x, person2Id=y, relation=relation, **kw)
    s.add(r)
    s.flush()
    return r


def test_a_couple_and_a_siblings_spouse_in_the_tree(db):
    """S10.10.5: a couple is each other's couple, and the partner's family relatives, not
    in-laws; a sibling's spouse is a sibling-in-law."""
    with db.tx(unscoped="test") as s:
        ids = _people(s, ("Ann", "female"), ("Bo", "male"), ("Bo's mum", "female"),
                      ("Mum", "female"), ("Sis", "female"), ("Sis's man", "male"))  # fmt: skip
        _rel(s, ids["Ann"], ids["Bo"], "couple")
        _rel(s, ids["Bo's mum"], ids["Bo"], "child")
        for kid in ("Ann", "Sis"):
            _rel(s, ids["Mum"], ids[kid], "child")
        _rel(s, ids["Sis"], ids["Sis's man"], "spouse", fromDate=dt.date(2010, 1, 1))
        assert _tree(s, ids["Ann"]) == {
            "Bo": "couple",
            "Bo's mum": "relative",
            "Mum": "mother",
            "Sis": "sister",
            "Sis's man": "brother-in-law",
        }


def test_the_tree_never_names_a_deleted_person_or_ego_themself(db):
    """S10.10.5: a relationship with a deleted person names no one; a stored relationship
    with someone the tree already names keeps the tree's word; a marriage between siblings,
    as entered, never makes a person their own relation; a stored one with anyone else names
    them by it, and one between others names no one."""
    with db.tx(unscoped="test") as s:
        ids = _people(s, ("Ann", "female"), ("Bo", "male"), ("Mum", "female"),
                      ("Gone", "male"), ("Pal", "female"))  # fmt: skip
        for kid in ("Ann", "Bo"):
            _rel(s, ids["Mum"], ids[kid], "child")
        _rel(s, ids["Ann"], ids["Bo"], "spouse", fromDate=dt.date(2010, 1, 1))
        _rel(s, ids["Ann"], ids["Mum"], "family", label="Mum")
        _rel(s, ids["Ann"], ids["Gone"], "friend")
        _rel(s, ids["Ann"], ids["Pal"], "family", label="Godmother")
        _rel(s, ids["Bo"], ids["Pal"], "colleague")
        s.get(Person, ids["Gone"]).mark_deleted(None)
        s.flush()
        named = tree.relations(s, ids["Ann"], dt.date(2026, 1, 1))
        assert {s.get(Person, r.personId).name: (r.word, r.stored) for r in named} == {
            "Bo": ("husband", True),
            "Mum": ("mother", True),
            "Pal": ("Godmother", True),
        }
