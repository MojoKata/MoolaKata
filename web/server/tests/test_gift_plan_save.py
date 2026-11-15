"""A gift plan, its person and its occasions saved as the plan's dialog saves them
(requirements S7.7, S10.10, S12.15, S13.8.11)."""

import pytest
from conftest import make_user, sign_in
from edits import asked, change, remove, saved
from test_gifts import T0, gift, person
from test_save import made_at

from moolakata import clock


@pytest.fixture
def jane(server):
    clock.fix(T0)
    make_user(server, "jane")
    yield sign_in(server, "jane")
    clock.fix(None)


def new(prefix: str) -> str:
    return made_at(prefix, clock.now())


def save(c, ops, confirm=()):
    return c.post("/ui/api/save", json={"ops": ops, "confirm": list(confirm)})


def test_a_new_person_their_plan_and_its_occasions_in_one_save(jane):
    p, gp, o = new("Persn"), new("GfPln"), new("Occsn")
    r = save(jane, [
        {"op": "create", "entity": "Persn", "id": p,
         "fields": {"name": "Leo Doe", "sex": "male", "birthMonth": 3, "birthDay": 4}},
        {"op": "create", "entity": "GfPln", "id": gp,
         "fields": {"personId": p, "giftBudget": "300", "leadDays": 14}},
        {"op": "create", "entity": "Occsn", "id": o,
         "fields": {"giftPlanId": gp, "kind": "holiday", "holiday": "christmas"}},
    ])  # fmt: skip
    assert r.status_code == 200, r.text
    plan = jane.get(f"/ui/api/gift-plans/{gp}").json()
    assert (plan["personId"], plan["giftBudget"]) == (p, "300.00")
    assert [x["id"] for x in plan["occasions"]] == [o]


def test_a_person_already_here_is_named_for_the_dialog(jane):
    person(jane)
    r = save(jane, [{"op": "create", "entity": "Persn", "id": new("Persn"),
                      "fields": {"name": "Lisa Doe", "sex": "female"}}])  # fmt: skip
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "person-exists"
    found = jane.get("/ui/api/persons/clash", params={"name": "Lisa Doe"}).json()
    assert found["name"] == "Lisa Doe" and found["visible"]
    assert jane.get("/ui/api/persons/clash", params={"name": "Nobody"}).json() is None


def test_an_occasion_changed_keeps_its_gifts(jane):
    """The plan's notes, or an occasion's budget, changed: the gifts planned for its
    anniversaries and other occasions keep them."""
    p = person(jane, occasions=[{"kind": "custom", "name": "Graduation", "month": 11, "day": 1}])
    (grad,) = p["plan"]["occasions"]
    gift(jane, people=[p["id"]], occasion=f"occasion:{grad['id']}", occasionYear=2026,
         status="planned", cost="200")  # fmt: skip
    saved(change(jane, "GfPln", p["plan"], notes="likes art"))
    saved(change(jane, "Occsn", grad, budget="250"))
    (g,) = jane.get("/ui/api/gifts").json()["items"]
    assert g["occasion"] == f"occasion:{grad['id']}" and g["occasionLabel"] == "Graduation"
    up = jane.get("/ui/api/gifts/upcoming").json()["items"]
    assert [x["label"] for x in up if x["gifts"]] == ["Graduation"]


def test_an_occasion_taken_away_with_gifts_asks_and_they_become_ideas(jane):
    p = person(jane, occasions=[{"kind": "custom", "name": "Graduation", "month": 11, "day": 1}])
    (grad,) = p["plan"]["occasions"]
    gift(jane, people=[p["id"]], occasion=f"occasion:{grad['id']}", occasionYear=2026)
    r = remove(jane, "Occsn", grad)
    assert asked(r) == ["occasion-gifts"]
    assert "becomes an idea" in r.json()["asks"][0]["message"]
    assert remove(jane, "Occsn", grad, confirm=True).status_code == 200
    (g,) = jane.get("/ui/api/gifts").json()["items"]
    assert g["occasion"] is None
    assert jane.get(f"/ui/api/gift-plans/{p['plan']['id']}").json()["occasions"] == []


def test_a_plan_deleted_leaves_its_person(jane):
    p = person(jane)
    r = remove(jane, "GfPln", p["plan"])
    assert r.status_code == 200, r.text
    assert jane.get(f"/ui/api/gift-plans/{p['plan']['id']}").status_code == 404
    assert jane.get(f"/ui/api/persons/{p['id']}").status_code == 200
