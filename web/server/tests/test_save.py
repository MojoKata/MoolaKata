"""The save (requirements S13.8.11): a draft's ops applied in one transaction or not at all.
No kind of record is registered for the save yet, so these tests register two of their own on
the giving tables: an organisation, and a donation that refers to one."""

import datetime as dt
import json
import os
import uuid
from typing import Literal

import pytest

from moolakata import clock, ids
from moolakata.errors import Problem, refuse
from moolakata.store.entities.giving import Donation, Organisation
from moolakata.ui import save
from moolakata.ui.conventions import IdOf, Model, Money

AFTER: list[str] = []


class OrgIn(Model):
    name: str
    notes: str | None = None
    causes: list[str] = []  # noqa: RUF012


class DonIn(Model):
    date: dt.date
    kind: Literal["cash", "goods"]
    amount: Money
    organisationId: IdOf("Orgzn") | None = None  # type: ignore[valid-type]


def _mine(ctx, entity, record_id):
    r = ctx.s.get(entity, record_id)
    if r is None or r.deleted or r.ownerId != ctx.caller.id:
        raise Problem(404, "not-found", "Not found.")
    return r


def _org_values(ctx, body: OrgIn) -> dict:
    if not body.name.strip():
        raise refuse("name", "name-required", "Give it a name.")
    if body.name == "Ask":
        ctx.ask("test-ask", "Name it Ask?")
    return {"name": body.name, "notes": body.notes, "causes": json.dumps(body.causes)}


def _org_create(ctx, record_id, body):
    ctx.s.add(Organisation(id=record_id, ownerId=ctx.caller.id, **_org_values(ctx, body)))
    ctx.after("orgs", lambda: AFTER.append("orgs"))


def _org_update(ctx, r, body):
    for k, v in _org_values(ctx, body).items():
        setattr(r, k, v)
    ctx.after("orgs", lambda: AFTER.append("orgs"))


def _org_read(ctx, record_id):
    r = ctx.s.get(Organisation, record_id)
    return {
        "id": r.id,
        "version": r.version,
        "name": r.name,
        "notes": r.notes,
        "causes": json.loads(r.causes),
    }


def _don_create(ctx, record_id, body):
    ctx.s.add(Donation(id=record_id, ownerId=ctx.caller.id, **body.model_dump()))


def _don_update(ctx, r, body):
    for k, v in body.model_dump().items():
        setattr(r, k, v)


def _don_read(ctx, record_id):
    r = ctx.s.get(Donation, record_id)
    return {
        "id": r.id,
        "version": r.version,
        "amount": r.amount,
        "organisationId": r.organisationId,
    }


ORG = save.Kind(
    prefix="Orgzn",
    entity=Organisation,
    fields=OrgIn,
    create=_org_create,
    editable=lambda ctx, i: _mine(ctx, Organisation, i),
    current=lambda ctx, r: {"name": r.name, "notes": r.notes, "causes": json.loads(r.causes)},
    update=_org_update,
    delete=lambda ctx, r: r.mark_deleted(ctx.caller.id),
    read=_org_read,
)
DON = save.Kind(
    prefix="Dnatn",
    entity=Donation,
    fields=DonIn,
    create=_don_create,
    editable=lambda ctx, i: _mine(ctx, Donation, i),
    current=lambda ctx, r: {
        "date": r.date.isoformat(),
        "kind": r.kind,
        "amount": r.amount,
        "organisationId": r.organisationId,
    },
    update=_don_update,
    delete=lambda ctx, r: r.mark_deleted(ctx.caller.id),
    read=_don_read,
)


@pytest.fixture(autouse=True)
def kinds(monkeypatch):
    monkeypatch.setattr(save, "KINDS", {"Orgzn": ORG, "Dnatn": DON})
    AFTER.clear()


def made_at(prefix: str, when: dt.datetime) -> str:
    """An id as the browser makes one: a UUIDv7 from its clock (schema.md §2)."""
    ms = int(when.timestamp() * 1000)
    rand = int.from_bytes(os.urandom(10)) & ((1 << 74) - 1)
    value = (
        (ms << 80) | (0x7 << 76) | ((rand >> 62) << 64) | (0b10 << 62) | (rand & ((1 << 62) - 1))
    )
    return f"{prefix}_{ids.encode(uuid.UUID(int=value))}"


def new(prefix: str) -> str:
    return made_at(prefix, clock.now())


def create(entity, record_id, **fields):
    return {"op": "create", "entity": entity, "id": record_id, "fields": fields}


def post(c, ops, confirm=(), **kw):
    return c.post("/ui/api/save", json={"ops": ops, "confirm": list(confirm)}, **kw)


def count(server, entity) -> int:
    from sqlalchemy import func, select

    with server.db.read() as s:
        return s.scalar(select(func.count()).select_from(entity).where(entity.deleted.is_(False)))


CASH = {"date": "2026-10-01", "kind": "cash", "amount": "25.00"}


def test_a_donation_and_its_new_organisation_save_together(admin_client, server):
    org, don = new("Orgzn"), new("Dnatn")
    # The donation comes first: its reference is checked at the commit, not as it is made.
    r = post(
        admin_client,
        [
            create(
                "Dnatn", don, date="2026-10-01", kind="cash", amount="25.00", organisationId=org
            ),
            create("Orgzn", org, name="Food bank", causes=["hunger"]),
        ],
    )
    assert r.status_code == 200, r.text
    saved = {x["id"]: x for x in r.json()["saved"]}
    assert saved[org]["record"]["name"] == "Food bank" and saved[org]["version"] == 1
    assert saved[don]["record"]["organisationId"] == org
    assert str(saved[don]["record"]["amount"]) == "25.00"
    assert AFTER == ["orgs"]


def test_an_update_sends_only_what_changed(admin_client):
    org = new("Orgzn")
    assert post(
        admin_client, [create("Orgzn", org, name="Library", notes="x", causes=["a"])]
    ).is_success
    r = post(
        admin_client,
        [
            {
                "op": "update",
                "entity": "Orgzn",
                "id": org,
                "version": 1,
                "fields": {"notes": "read more", "causes": {"add": ["b"], "remove": ["a"]}},
            }
        ],
    )
    assert r.status_code == 200, r.text
    rec = r.json()["saved"][0]
    assert rec["version"] == 2
    assert rec["record"] == {
        "id": org,
        "version": 2,
        "name": "Library",
        "notes": "read more",
        "causes": ["b"],
    }


def test_one_refusal_saves_nothing_and_every_refusal_is_named(admin_client, server):
    good, bad1, bad2 = new("Orgzn"), new("Orgzn"), new("Dnatn")
    r = post(
        admin_client,
        [
            create("Orgzn", good, name="Fine"),
            create("Orgzn", bad1, name="  "),
            create("Dnatn", bad2, date="2026-10-01", kind="crypto", amount="1.00"),
        ],
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["code"] == "save-refused"
    got = {(e["id"], e["field"], e["code"]) for e in body["errors"]}
    assert (bad1, "name", "name-required") in got
    assert any(e[0] == bad2 and e[1] == "kind" for e in got)
    assert all(e[0] != good for e in got)
    assert count(server, Organisation) == 0


def test_a_stale_version_refuses_the_whole_save(admin_client, server):
    org, other = new("Orgzn"), new("Orgzn")
    assert post(admin_client, [create("Orgzn", org, name="One")]).is_success
    up = {"op": "update", "entity": "Orgzn", "id": org, "fields": {"notes": "n"}}
    assert post(admin_client, [{**up, "version": 1}]).is_success
    r = post(admin_client, [create("Orgzn", other, name="Two"), {**up, "version": 1}])
    assert r.status_code == 412, r.text
    (current,) = r.json()["current"]
    assert current["id"] == org and current["version"] == 2
    assert count(server, Organisation) == 1


def test_questions_are_asked_together_and_confirmed_by_name(admin_client):
    a, b = new("Orgzn"), new("Orgzn")
    ops = [create("Orgzn", a, name="Ask"), create("Orgzn", b, name="Ask")]
    r = post(admin_client, ops)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "confirm-needed"
    assert {(x["code"], x["id"]) for x in r.json()["asks"]} == {("test-ask", a), ("test-ask", b)}
    # Confirming one leaves the other asked again.
    r = post(admin_client, ops, confirm=[{"code": "test-ask", "id": a}])
    assert r.status_code == 409
    assert [x["id"] for x in r.json()["asks"]] == [b]
    r = post(admin_client, ops, confirm=[{"code": "test-ask", "id": x} for x in (a, b)])
    assert r.status_code == 200, r.text


def test_ids_made_in_the_browser_are_checked(admin_client):
    def code_of(r):
        return [(e["field"], e["code"]) for e in r.json()["errors"]]

    r = post(admin_client, [create("Orgzn", new("Dnatn"), name="Wrong table")])
    assert code_of(r) == [("id", "id-invalid")]
    r = post(admin_client, [create("Orgzn", "Orgzn_not-an-id", name="Bad form")])
    assert code_of(r) == [("id", "id-invalid")]
    off = made_at("Orgzn", clock.now() - dt.timedelta(days=2))
    r = post(admin_client, [create("Orgzn", off, name="Old clock")])
    assert code_of(r) == [("id", "id-clock")]
    org = new("Orgzn")
    assert post(admin_client, [create("Orgzn", org, name="First")]).is_success
    r = post(admin_client, [create("Orgzn", org, name="Again")])
    assert r.status_code == 409 and code_of(r) == [("id", "id-taken")]


def test_a_reference_is_checked_for_its_table_and_at_the_commit(admin_client, server):
    don = new("Dnatn")
    fields = {"date": "2026-10-01", "kind": "cash", "amount": "5.00"}
    r = post(admin_client, [create("Dnatn", don, **fields, organisationId=new("Dnatn"))])
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "organisationId"
    r = post(admin_client, [create("Dnatn", don, **fields, organisationId=new("Orgzn"))])
    assert r.status_code == 422 and r.json()["code"] == "reference-missing"
    assert count(server, Donation) == 0


def test_a_repeat_with_the_same_key_gets_the_first_answer(admin_client, server):
    org = new("Orgzn")
    ops = [create("Orgzn", org, name="Once")]
    first = post(admin_client, ops, headers={"Idempotency-Key": "k1"})
    again = post(admin_client, ops, headers={"Idempotency-Key": "k1"})
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert count(server, Organisation) == 1


def test_a_delete_answers_what_went(admin_client, server):
    org = new("Orgzn")
    assert post(admin_client, [create("Orgzn", org, name="Gone soon")]).is_success
    r = post(admin_client, [{"op": "delete", "entity": "Orgzn", "id": org, "version": 1}])
    assert r.status_code == 200, r.text
    assert r.json()["saved"][0]["deleted"]["id"] == org
    assert count(server, Organisation) == 0


def test_another_users_record_isnt_found(admin_client, server):
    from conftest import make_user, sign_in

    org = new("Orgzn")
    assert post(admin_client, [create("Orgzn", org, name="Mine")]).is_success
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    r = post(
        bob,
        [{"op": "update", "entity": "Orgzn", "id": org, "version": 1, "fields": {"name": "Bob's"}}],
    )
    assert r.status_code == 404
    assert r.json()["errors"][0]["id"] == org


def test_one_change_per_record_and_known_kinds_only(admin_client):
    org = new("Orgzn")
    r = post(admin_client, [create("Orgzn", org, name="A"), create("Orgzn", org, name="B")])
    assert ("id", "id-repeated") in {(e["field"], e["code"]) for e in r.json()["errors"]}
    r = post(admin_client, [create("Xyz", "Xyz_x", name="?")])
    assert r.json()["errors"][0]["code"] == "entity-unknown"


def test_the_time_of_an_id():
    when = dt.datetime(2026, 10, 28, 14, 5, tzinfo=dt.UTC)
    assert ids.time_of(made_at("Orgzn", when)) == when
