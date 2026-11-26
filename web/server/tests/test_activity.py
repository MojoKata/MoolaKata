"""Activity (requirements S10.8, S12.1.3): filtered by who did it, the +N new pill, and what
its entries name."""

from conftest import make_user, sign_in
from test_accounts import new_account

from moolakata import activity, clock


def test_activity_filtered_by_person_lists_only_what_they_did(server):
    jane = make_user(server, "jane")
    john = make_user(server, "john")
    c = sign_in(server, "jane")
    new_account(c, name="Hers")
    got = c.get("/ui/api/activity", params={"person": jane.id}).json()["items"]
    assert got and {x["actorId"] for x in got} == {jane.id}
    assert c.get("/ui/api/activity", params={"person": john.id}).json()["items"] == []


def test_the_new_count_after_an_entry_not_found_is_zero(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    new_account(c, name="First")
    before = c.get("/ui/api/activity").json()["items"]
    new_account(c, name="Second", mask="1111")
    after = c.get("/ui/api/activity").json()["items"]
    got = c.get("/ui/api/activity/newer", params={"since": before[0]["id"]}).json()["count"]
    assert got == len(after) - len(before) > 0
    gone = {"since": "Actvt_00000000000000000000000000"}
    assert c.get("/ui/api/activity/newer", params=gone).json() == {"count": 0}


def test_an_entry_names_a_person_until_they_are_deleted(server):
    """A person an entry is about is named while they stand, and not once deleted."""
    from moolakata import people
    from moolakata.store.entities.core import Activity
    from moolakata.ui.activity import _names

    jane = make_user(server, "jane")
    with server.db.tx(unscoped="test") as s:
        kept = people.make(s, "Kept", "female")
        gone = people.make(s, "Gone", "male")
        for p in (kept, gone):
            activity.record(s, "person.share-asked", actor=jane.id, subject_kind="person",
                            subject_id=p.id, owner=jane.id)  # fmt: skip
        gone.deletedAt = clock.now()
    with server.db.read(unscoped="test") as s:
        names = _names(s, list(s.query(Activity).filter(Activity.subjectKind == "person")))
    assert names[("person", kept.id)] == "Kept"
    assert ("person", gone.id) not in names
