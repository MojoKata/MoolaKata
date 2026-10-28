"""A gift plan, its person and its occasions saved as the plan's dialog saves them
(requirements S7.7, S10.10, S12.15, S13.8.11)."""

import pytest
from conftest import make_user, sign_in
from edits import asked, change, remove, saved
from test_gifts import T0, gift, person
from test_save import made_at

from moolakata import clock


@pytest.fixture
def alice(server):
    clock.fix(T0)
    make_user(server, "alice")
    yield sign_in(server, "alice")
    clock.fix(None)


def new(prefix: str) -> str:
    return made_at(prefix, clock.now())


def save(c, ops, confirm=()):
    return c.post("/ui/api/save", json={"ops": ops, "confirm": list(confirm)})


def test_a_new_person_their_plan_and_its_occasions_in_one_save(alice):
    p, gp, o = new("Persn"), new("GfPln"), new("Occsn")
    r = save(alice, [
        {"op": "create", "entity": "Persn", "id": p,
         "fields": {"name": "Leo Griffin", "sex": "male", "birthMonth": 3, "birthDay": 4}},
        {"op": "create", "entity": "GfPln", "id": gp,
         "fields": {"personId": p, "giftBudget": "300", "leadDays": 14}},
        {"op": "create", "entity": "Occsn", "id": o,
         "fields": {"giftPlanId": gp, "kind": "holiday", "holiday": "christmas"}},
    ])  # fmt: skip
    assert r.status_code == 200, r.text
    plan = alice.get(f"/ui/api/people/{p}").json()
    assert (plan["planId"], plan["giftBudget"]) == (gp, "300.00")
    assert [x["id"] for x in plan["occasions"]] == [o]


def test_a_person_already_here_is_named_for_the_dialog(alice):
    person(alice)
    r = save(alice, [{"op": "create", "entity": "Persn", "id": new("Persn"),
                      "fields": {"name": "Emma Griffin", "sex": "female"}}])  # fmt: skip
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "person-exists"
    found = alice.get("/ui/api/persons/clash", params={"name": "Emma Griffin"}).json()
    assert found["name"] == "Emma Griffin" and found["visible"]
    assert alice.get("/ui/api/persons/clash", params={"name": "Nobody"}).json() is None


def test_an_occasion_changed_keeps_its_gifts(alice):
    """CR3-43: the plan's notes, or an occasion's budget, changed: the gifts planned for its
    anniversaries and other occasions keep them."""
    p = person(alice, occasions=[{"kind": "custom", "name": "Graduation", "month": 11, "day": 1}])
    (grad,) = p["occasions"]
    gift(alice, people=[p["id"]], occasion=f"occasion:{grad['id']}", occasionYear=2026,
         status="planned", cost="200")  # fmt: skip
    saved(change(alice, "GfPln", {"id": p["planId"], "version": p["version"]}, notes="likes art"))
    saved(change(alice, "Occsn", grad, budget="250"))
    (g,) = alice.get("/ui/api/gifts").json()["items"]
    assert g["occasion"] == f"occasion:{grad['id']}" and g["occasionLabel"] == "Graduation"
    up = alice.get("/ui/api/gifts/upcoming").json()["items"]
    assert [x["label"] for x in up if x["gifts"]] == ["Graduation"]


def test_an_occasion_taken_away_with_gifts_asks_and_they_become_ideas(alice):
    p = person(alice, occasions=[{"kind": "custom", "name": "Graduation", "month": 11, "day": 1}])
    (grad,) = p["occasions"]
    gift(alice, people=[p["id"]], occasion=f"occasion:{grad['id']}", occasionYear=2026)
    r = remove(alice, "Occsn", grad)
    assert asked(r) == ["occasion-gifts"]
    assert "becomes an idea" in r.json()["asks"][0]["message"]
    assert remove(alice, "Occsn", grad, confirm=True).status_code == 200
    (g,) = alice.get("/ui/api/gifts").json()["items"]
    assert g["occasion"] is None
    assert alice.get(f"/ui/api/people/{p['id']}").json()["occasions"] == []


def test_a_plan_deleted_leaves_its_person(alice):
    p = person(alice)
    r = remove(alice, "GfPln", {"id": p["planId"], "version": p["version"]})
    assert r.status_code == 200, r.text
    assert alice.get(f"/ui/api/people/{p['id']}").status_code == 404
    assert alice.get(f"/ui/api/persons/{p['id']}").status_code == 200
