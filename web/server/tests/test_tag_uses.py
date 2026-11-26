"""A tag's uses (requirements S12.18.12): how many records the caller sees carry it, so a tag
box lists the most used first. Records deleted, and records the caller no longer sees, don't
count."""

import pytest
from conftest import make_user, sign_in
from edits import change, make, new_id, remove, share, tag
from test_accounts import add, new_account


def uses(c) -> dict[str, int]:
    return {t["name"]: t["uses"] for t in c.get("/ui/api/tags").json()["items"]}


def test_a_tag_counts_the_records_the_caller_sees_carrying_it(server):
    u = {n: make_user(server, n) for n in ("jane", "john")}
    jane, john = sign_in(server, "jane"), sign_in(server, "john")
    own = new_account(jane)
    make(jane, "Txn", accountId=own["id"], date="2026-09-01", amount="-4.00", tags=["work"])
    make(jane, "Txn", accountId=own["id"], date="2026-09-02", amount="-5.00",
         tags=["work", "coffee"])  # fmt: skip
    gone = make(jane, "Txn", accountId=own["id"], date="2026-09-03", amount="-6.00",
                tags=["work"])  # fmt: skip
    make(jane, "Rule", payeeMatch="blue bottle", tags=["coffee"])
    assert uses(jane) == {"coffee": 2, "work": 3}

    # A deleted transaction no longer counts.
    assert remove(jane, "Txn", gone.json()).status_code == 200
    assert uses(jane) == {"coffee": 2, "work": 2}

    # Jane's tag on John's shared account counts while she sees it, and not once she doesn't.
    theirs = new_account(john, name="Joint")
    assert share(john, "account", theirs["id"], users={u["jane"].id: "write"}).status_code == 200
    add(jane, theirs["id"], "-7.00", payee="Lunch")
    t = next(x for x in jane.get("/ui/api/transactions").json()["items"] if x["payee"] == "Lunch")
    r = change(jane, "Txn", t, tagIds={"add": [tag(jane, "work")], "remove": []})
    assert r.status_code == 200, r.text
    assert uses(jane)["work"] == 3
    assert share(john, "account", theirs["id"], users={u["jane"].id: "none"}).status_code == 200
    assert uses(jane)["work"] == 2
    # John's tags are his own: Jane's don't show for him at all.
    assert uses(john) == {}


def _tags(c) -> list[dict]:
    return c.get("/ui/api/tags").json()["items"]


def test_a_tag_deleted_comes_off_everything_that_carried_it(server):
    """S2.6: a tag deleted takes itself off its transactions and its rules; making one of the
    same name again starts with nothing carrying it."""
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    own = new_account(jane)
    t = make(jane, "Txn", accountId=own["id"], date="2026-09-01", amount="-4.00", tags=["work"])
    assert t.status_code == 200, t.text
    rule = make(jane, "Rule", payeeMatch="blue bottle", tags=["work"])
    assert rule.status_code == 200, rule.text
    assert uses(jane) == {"work": 2}
    [work] = _tags(jane)
    assert remove(jane, "Tag", work).status_code == 200
    assert uses(jane) == {}
    [txn] = jane.get("/ui/api/transactions").json()["items"]
    assert txn["tagIds"] == []
    assert [r["tagIds"] for r in jane.get("/ui/api/rules").json()["items"]] == [[]]
    tag(jane, "work")
    assert uses(jane) == {"work": 0}


@pytest.mark.parametrize("name", ["", "   ", "x" * 41, "work, play"])
def test_a_tag_blank_too_long_or_with_a_comma_is_refused_at_its_name(server, name):
    """S2.6, R3.11: a tag of up to 40 characters, without a comma; never blank."""
    from edits import new_id

    make_user(server, "jane")
    jane = sign_in(server, "jane")
    op = {"op": "create", "entity": "Tag", "id": new_id("Tag"), "fields": {"name": name}}
    r = jane.post("/ui/api/save", json={"ops": [op]})
    assert r.status_code == 422
    [error] = r.json()["errors"]
    assert (error["field"], error["code"], error["message"]) == (
        "name",
        "tag-invalid",
        "A tag of up to 40 characters, without a comma.",
    )


def test_a_tag_made_twice_is_the_same_and_only_the_owners_own_are_taken(unscoped):
    from moolakata import tags
    from moolakata.errors import Problem

    s, owner = unscoped
    work = tags.make(s, owner, " Work ")
    assert tags.make(s, owner, "work") is work and work.name == "work"
    assert tags.owned(s, owner, [work.id]) == [work]
    with pytest.raises(Problem) as e:
        tags.owned(s, owner, [work.id, "Tag_someone_elses"], field="tags")
    [error] = e.value.errors
    assert (error.field, error.code, error.message) == ("tags", "tag-unknown", "Tags of your own.")


def test_a_tag_taken_off_and_put_back_on_is_the_same_link_again(server):
    """A tag's link to its record is kept when taken off, and put back as it was: once, with
    nothing told twice."""
    from moolakata import tags
    from moolakata.store.entities.accounts import RuleTag

    make_user(server, "jane")
    jane = sign_in(server, "jane")
    assert make(jane, "Rule", payeeMatch="blue bottle", tags=["coffee"]).status_code == 200
    [rule] = jane.get("/ui/api/rules").json()["items"]
    [coffee] = rule["tagIds"]
    with server.db.tx(unscoped="test") as s:
        owner = s.get(tags.Tag, coffee).ownerId
        assert not tags.add_on(s, "rule", rule["id"], coffee), "already on"
        tags.set_on(s, "rule", rule["id"], owner, [], owner)
        s.flush()
        assert tags.ids_of(s, "rule", owner, rule["id"]) == []
        assert tags.add_on(s, "rule", rule["id"], coffee), "put back"
        s.flush()
        tags.set_on(s, "rule", rule["id"], owner, [], owner)
        s.flush()
        tags.set_on(s, "rule", rule["id"], owner, [coffee], owner)
        s.flush()
        assert tags.ids_of(s, "rule", owner, rule["id"]) == [coffee]
        links = s.query(RuleTag).filter_by(ruleId=rule["id"]).all()
        assert len(links) == 1 and not links[0].deleted


# ---- A tag's name, its owner's once (S2.6) ----


def _mine(c) -> dict[str, dict]:
    return {t["name"]: t for t in c.get("/ui/api/tags").json()["items"]}


def _refused(r) -> list[tuple[str | None, str, str]]:
    assert r.status_code == 409, r.text
    return [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]]


def test_a_tag_name_is_its_owners_once_and_only_its_owner_changes_it(server):
    make_user(server, "jane")
    make_user(server, "john")
    jane, john = sign_in(server, "jane"), sign_in(server, "john")
    tag(jane, "work")
    tag(jane, "coffee")
    op = {"op": "create", "entity": "Tag", "id": new_id("Tag"), "fields": {"name": " Work "}}
    taken = [("name", "tag-taken", "You have a tag work.")]
    assert _refused(jane.post("/ui/api/save", json={"ops": [op]})) == taken
    have = _mine(jane)
    assert _refused(change(jane, "Tag", have["coffee"], name="WORK")) == taken
    # The same name, as typed: nothing changes, and nothing is recorded.
    r = change(jane, "Tag", have["work"], name="Work")
    assert r.status_code == 200, r.text
    assert _mine(jane)["work"]["version"] == have["work"]["version"]
    # Another's tag is not found, to change or to delete.
    for r in (change(john, "Tag", have["work"], name="mine"), remove(john, "Tag", have["work"])):
        assert r.status_code == 404, r.text
        assert [(e["code"], e["message"]) for e in r.json()["errors"]] == [
            ("not-found", "Not found")
        ]
    assert set(_mine(jane)) == {"coffee", "work"}
    # Renamed, it is kept as typed in lower case, and the change recorded.
    r = change(jane, "Tag", have["coffee"], name="Espresso")
    assert r.status_code == 200, r.text
    assert set(_mine(jane)) == {"espresso", "work"}
    kinds = [x["kind"] for x in jane.get("/ui/api/activity").json()["items"]]
    assert kinds.count("tag.renamed") == 1
