"""Linked servers' calls (requirements S11.1.3): every call signed with the sender's link key
over its method, path, body, time and nonce, and the answer signed back."""

import time

import pytest
from linkpair import Wire, make_server

from moolakata import ids
from moolakata.links import client, keys, signing
from moolakata.store.entities.links import Link


def reach(srv, *hosts):
    """Let a server call these hosts, as a link to them would."""
    srv.guard.allow(hosts, {"link": hosts})


@pytest.fixture
def pair(tmp_path, monkeypatch):
    a, b = make_server(tmp_path, "a"), make_server(tmp_path, "b")
    wire = Wire()
    urls = wire.add("a", a), wire.add("b", b)
    wire.install(monkeypatch)
    yield a, b, urls, wire
    wire.close()
    a.db.dispose()
    b.db.dispose()


def public(srv) -> bytes:
    with srv.db.tx(unscoped="test") as s:
        return keys.public_of(s, srv.keys.secrets)


def link(srv, peer_url, peer_key, state="active", role="inviter") -> str:
    with srv.db.tx(unscoped="test") as s:
        row = Link(
            id=ids.new_id("Link"),
            state=state,
            role=role,
            address=peer_url,
            peerKey=keys.b64(peer_key),
        )
        s.add(row)
        return row.id


def test_a_linked_server_answers_a_signed_call_and_signs_its_answer(pair):
    a, b, (url_a, url_b), _ = pair
    reach(a, "b.test")
    ka, kb = public(a), public(b)
    assert ka != kb and len(ka) == 32
    assert public(a) == ka, "made once, then kept"
    link(a, url_b, kb)
    link(b, url_a, ka, role="joiner")
    hi = client.hello(a, url_b)
    assert hi["fingerprint"] == keys.fingerprint(kb) and hi["protocol"] == 1
    # Unsigned, so it names no release (S13.6): the version rides on signed answers.
    assert set(hi) == {"protocol", "fingerprint", "key"}
    out = client.call(a, url_b, kb, "/link/v1/ping")
    assert out["state"] == "active"
    with b.db.read(unscoped="test") as s:
        row = s.query(Link).one()
        assert row.lastOkAt is not None and row.peerVersion == a.version


def test_a_call_from_an_unknown_key_or_the_wrong_link_state_is_refused(pair):
    a, b, (url_a, url_b), _ = pair
    reach(a, "b.test")
    kb = public(b)
    with pytest.raises(client.LinkError) as e:
        client.call(a, url_b, kb, "/link/v1/ping")
    assert e.value.code == "not-linked"
    link(b, url_a, public(a), state="ended")
    with pytest.raises(client.LinkError) as e:
        client.call(a, url_b, kb, "/link/v1/ping")
    assert e.value.code == "link-ended"


def test_an_answer_not_signed_by_the_peer_is_refused(pair):
    a, b, (url_a, url_b), _ = pair
    reach(a, "b.test")
    link(b, url_a, public(a))
    stranger = keys.raw_public(signing.Ed25519PrivateKey.generate().public_key())
    with pytest.raises(client.LinkError) as e:
        client.call(a, url_b, stranger, "/link/v1/ping")
    assert e.value.code in ("bad-signature", "not-linked")


def test_signatures_times_and_nonces_are_checked():
    k = signing.Ed25519PrivateKey.generate()
    fp = "f" * 64
    nonces = signing.Nonces()
    s = signing.sign_request(k, "POST", "/link/v1/ping", b"{}", fp)
    h = {key.lower(): v for key, v in s.headers.items()}
    caller = signing.verify_request(h, "POST", "/link/v1/ping", b"{}", fp, nonces)
    assert caller.public == keys.raw_public(k.public_key())
    with pytest.raises(signing.Refused, match="already"):
        signing.verify_request(h, "POST", "/link/v1/ping", b"{}", fp, nonces)
    for body, path, other_fp in (
        (b"{1}", "/link/v1/ping", fp),
        (b"{}", "/link/v1/x", fp),
        (b"{}", "/link/v1/ping", "0" * 64),
    ):
        s = signing.sign_request(k, "POST", "/link/v1/ping", b"{}", fp)
        h = {key.lower(): v for key, v in s.headers.items()}
        with pytest.raises(signing.Refused) as e:
            signing.verify_request(h, "POST", path, body, other_fp, nonces)
        assert e.value.code == "bad-signature"
    old = signing.sign_request(k, "POST", "/p", b"", fp, now=time.time() - 61)
    h = {key.lower(): v for key, v in old.headers.items()}
    with pytest.raises(signing.Refused) as e:
        signing.verify_request(h, "POST", "/p", b"", fp, nonces)
    assert e.value.code == "clock-skew"
    with pytest.raises(signing.Refused) as e:
        signing.verify_request({}, "POST", "/p", b"", fp, nonces)
    assert e.value.code == "unsigned"


def test_a_peer_speaking_another_protocol_is_told_which_this_one_speaks(pair, monkeypatch):
    a, b, (url_a, url_b), _ = pair
    reach(a, "b.test")
    link(b, url_a, public(a))
    monkeypatch.setattr(client, "PROTOCOL", 2)
    with pytest.raises(client.LinkError) as e:
        client.call(a, url_b, public(b), "/link/v1/ping")
    assert e.value.code == "protocol-unsupported" and "speaks link protocol 1" in e.value.message


def test_an_unreachable_peer_says_so(pair):
    a, b, (_, url_b), wire = pair
    reach(a, "b.test")
    wire.down.add("b.test")
    with pytest.raises(client.LinkError) as e:
        client.call(a, url_b, public(b), "/link/v1/ping")
    assert e.value.code == "unreachable"


def test_a_links_answer_is_read_through_the_clients_ceiling(pair, monkeypatch):
    """S13.5: the `Wire` stands where the sockets are, so a link's answer meets `net.Client`'s
    ceiling as on the network: one past it is refused, the peer taken as unreachable."""
    from moolakata import net

    a, b, (url_a, url_b), _ = pair
    reach(a, "b.test")
    link(b, url_a, public(a))
    assert client.call(a, url_b, public(b), "/link/v1/ping")["state"] == "active"
    monkeypatch.setattr(
        client,
        "_client",
        lambda srv, pins, max_bytes=0: net.Client(srv.guard, max_bytes=16, pins=pins, use="link"),
    )
    with pytest.raises(client.LinkError) as e:
        client.call(a, url_b, public(b), "/link/v1/ping")
    assert e.value.code == "unreachable" and "ResponseTooLarge" in e.value.message


# ---------- invitations, approval and the directory (S11.1, S11.3, S11.6)

from conftest import make_user  # noqa: E402
from edits import attach, create, make, saved, share  # noqa: E402
from linkpair import admin_of, linked  # noqa: E402


@pytest.fixture
def admins(pair):
    a, b, (url_a, url_b), wire = pair
    ca, cb = admin_of(a, url_a), admin_of(b, url_b)
    yield a, b, ca, cb, wire
    ca.close()
    cb.close()


def links_of(c):
    return c.get("/ui/api/settings/links").json()


def test_an_invitation_is_joined_approved_and_each_side_sees_the_others_users(admins):
    from moolakata.store.entities.education import Person

    a, b, ca, cb, _ = admins
    make_user(a, "jane")
    make_user(b, "bart")
    inv = ca.post("/ui/api/settings/links/invitations")
    assert inv.status_code == 201, inv.text
    code = inv.json()["code"]
    assert code.startswith("mkl1.") and inv.json()["link"]["state"] == "invited"
    joined = cb.post("/ui/api/settings/links/join", json={"code": code})
    assert joined.status_code == 201, joined.text
    assert joined.json()["state"] == "pending"
    assert joined.json()["fingerprint"] == links_of(ca)["fingerprint"]
    with b.db.read(unscoped="test") as s:
        assert s.query(Link).one().peerVersion == a.version, "from the signed join answer"
    req = links_of(ca)["links"][0]
    assert req["state"] == "requested" and req["fingerprint"] == links_of(cb)["fingerprint"]
    # Nothing of either household crosses before the approval (S10.10.1).
    assert req["users"] == [] and links_of(cb)["links"][0]["users"] == []
    with a.db.read(unscoped="test") as s:
        assert s.query(Person).filter(Person.name == "Bart").count() == 0
    again = cb.post("/ui/api/settings/links/join", json={"code": code})
    assert again.status_code == 422 and again.json()["code"] in ("code-used", "already-linked")
    r = ca.post(f"/ui/api/settings/links/{req['id']}/approve")
    assert r.status_code == 200 and r.json()["state"] == "active"
    b_side = links_of(cb)["links"][0]
    assert b_side["state"] == "active", "told at once by the approval's exchange"
    assert {u["username"] for u in b_side["users"]} == {"admin", "jane"}
    assert {u["username"] for u in links_of(ca)["links"][0]["users"]} == {"admin", "bart"}
    assert b_side["householdName"]
    # Remote users never sign in, and stay out of Users and Groups.
    assert all(u["username"] != "bart" for u in ca.get("/ui/api/users").json()["items"])


def test_the_directory_follows_the_peers_users(admins):
    _a, b, ca, cb, _ = admins
    a_id, b_id = linked(ca, cb)
    make_user(b, "dave")
    assert ca.post(f"/ui/api/settings/links/{a_id}/pull").status_code == 200
    names = {u["username"] for u in links_of(ca)["links"][0]["users"]}
    assert "dave" in names
    from moolakata.store.entities.users import User

    with b.db.tx(unscoped="test") as s:
        s.query(User).filter(User.username == "dave").one().active = False
    ca.post(f"/ui/api/settings/links/{a_id}/pull")
    assert "dave" not in {u["username"] for u in links_of(ca)["links"][0]["users"]}
    with b.db.tx(unscoped="test") as s:
        s.query(User).filter(User.username == "dave").one().active = True
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    assert "dave" in {u["username"] for u in links_of(ca)["links"][0]["users"]}, (
        "an exchange from either side updates both"
    )


def test_a_directory_that_doesnt_fit_is_refused_whole_and_said_on_the_link(admins):
    from moolakata import settings
    from moolakata.store.entities.core import Setting

    _a, b, ca, cb, _ = admins
    a_id, _b_id = linked(ca, cb)
    before = links_of(ca)["links"][0]
    assert before["householdAvatar"]["kind"] == "initials"
    # A peer's avatar that isn't an object, written past b's own check.
    with b.db.tx(unscoped="test") as s:
        s.add(Setting(id=ids.new_id("Setng"), key="householdAvatar", value='["x"]'))
        settings.put(s, "householdName", "Not kept", None)
    make_user(b, "dave")
    out = ca.post(f"/ui/api/settings/links/{a_id}/pull").json()
    assert out["lastError"].startswith("Its household and users were refused")
    assert "avatar" in out["lastError"]
    after = links_of(ca)["links"][0]  # answered, not a 500
    assert after["householdAvatar"] == before["householdAvatar"]
    assert after["householdName"] == before["householdName"], "none of it is kept"
    assert "dave" not in {u["username"] for u in after["users"]}
    assert after["state"] == "active" and after["failingSince"] is None, "it was reached"


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ({"household": ["x"]}, "its household isn't an object"),
        ({"household": {"avatar": ["x"]}}, "its household's avatar isn't initials or an image"),
        (
            {"household": {"avatar": {"kind": "image", "image": "data:image/gif;base64,R0"}}},
            "its household's avatar isn't a PNG, JPEG or WebP image",
        ),
        ({"household": {"serverName": 7}}, "its server name isn't text"),
        ({"household": {"name": "x" * 61}}, "its household's name is longer than 60 characters"),
        ({"users": {"id": "u"}}, "its users aren't a list of objects"),
        ({"users": ["u"]}, "its users aren't a list of objects"),
        ({"users": [{"username": "jo"}]}, "a user has no id"),
        ({"users": [{"id": 5}]}, "a user's id isn't text"),
        ({"users": [{"id": "u" * 65}]}, "a user's id is longer than 64 characters"),
        ({"users": [{"id": "u", "email": ["a@b.c"]}]}, "an email isn't text"),
        ({"users": [{"id": "u", "email": "a" * 255}]}, "an email is longer than 254 characters"),
        ({"users": [{"id": "u", "displayName": {"x": 1}}]}, "a display name isn't text"),
        ({"users": [{"id": "u", "username": 1}]}, "a username isn't text"),
    ],
)
def test_each_field_of_a_peers_directory_is_checked_before_any_is_kept(payload, why):
    from moolakata.links import manage

    with pytest.raises(manage.BadDirectory) as e:
        manage._checked(payload)
    assert str(e.value) == why


def test_a_peers_directory_is_kept_within_its_bounds():
    from moolakata.links import manage

    h, users = manage._checked(
        {
            "household": {"serverName": "doe-parents", "name": "x" * 60},
            "users": [
                {"id": "u" * 64, "username": "n" * 70, "displayName": "d" * 130, "sex": "other"},
                {"id": "v", "email": "e" * 254, "sex": "female"},
            ],
        }
    )
    assert h == {"serverName": "doe-parents", "name": "x" * 60, "avatar": None}
    assert users == [
        {
            "id": "u" * 64,
            "username": "n" * 64,
            "displayName": "d" * 120,
            "email": None,
            "sex": "male",
        },
        {"id": "v", "username": None, "displayName": None, "email": "e" * 254, "sex": "female"},
    ]
    assert manage._checked({}) == (None, None), "no directory: nothing to keep"


def test_a_code_for_another_key_or_a_damaged_code_is_refused(admins):
    _a, _b, ca, cb, _ = admins
    code = ca.post("/ui/api/settings/links/invitations").json()["code"]
    from moolakata.links import manage

    c = manage.decode_code(code)
    forged = manage.encode_code(c["a"], "0" * 64, c["c"])
    r = cb.post("/ui/api/settings/links/join", json={"code": forged})
    assert r.status_code == 422 and r.json()["code"] == "fingerprint-mismatch"
    r = cb.post("/ui/api/settings/links/join", json={"code": "hello"})
    assert r.json()["code"] == "code-invalid"


def test_any_failure_of_one_links_exchange_is_recorded_on_it_and_the_next_goes_on(
    server, monkeypatch
):
    """link-protocol.md §4.3, S11.9.5.3: a peer's answer the exchange can't read (a `more`
    that isn't a number, an item without an id) fails that link alone, recorded on it as a
    failed call is; the hourly run goes on to every link after it."""
    from moolakata.links import manage

    ids_ = [link(server, f"https://{n}.test", bytes([n]) * 32) for n in (1, 2)]
    called = []

    def broken(srv, link_id):
        called.append(link_id)
        raise ValueError("invalid literal for int() with base 10: 'x'")

    monkeypatch.setattr(manage, "exchange", broken)
    manage.exchange_all(server)
    assert sorted(called) == sorted(ids_), "each link's exchange is made"
    with server.db.read(unscoped="test") as s:
        for link_id in ids_:
            row = s.get(Link, link_id)
            assert row.lastError == (
                "The exchange failed: ValueError: invalid literal for int() with base 10: 'x'"
            )
            assert row.failingSince is not None, "alerted as a failing link is"


def test_pausing_stops_exchanges_and_ending_reaches_the_other_side(admins):
    _a, _b, ca, cb, wire = admins
    a_id, b_id = linked(ca, cb)
    # The duration is asked for: missing, blank or empty is refused, never read as 1d (R3.11).
    for body in (None, {}, {"for": None}, {"for": ""}, {"for": "  "}):
        r = ca.post(f"/ui/api/settings/links/{a_id}/pause", json=body)
        assert (r.status_code, r.json()["code"]) == (422, "duration-missing"), body
        assert r.json()["errors"][0]["field"] == "for"
    paused = ca.post(f"/ui/api/settings/links/{a_id}/pause", json={"for": "1d"})
    assert paused.json()["state"] == "paused"
    out = cb.post(f"/ui/api/settings/links/{b_id}/pull").json()
    assert out["lastError"] and "paused" in out["lastError"]
    assert ca.post(f"/ui/api/settings/links/{a_id}/resume").json()["state"] == "active"
    assert cb.post(f"/ui/api/settings/links/{b_id}/pull").json()["lastError"] is None
    wire.down.add("b.test")
    ended = ca.post(f"/ui/api/settings/links/{a_id}/end").json()
    assert ended["state"] == "ended" and ended["users"] == []
    wire.down.clear()
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    b_side = links_of(cb)["links"][0]
    assert b_side["state"] == "ended" and b_side["users"] == [], "learnt at its next call"


def test_an_unreachable_peer_is_recorded_on_the_link(admins):
    _a, _b, ca, cb, wire = admins
    a_id, _ = linked(ca, cb)
    wire.down.add("b.test")
    out = ca.post(f"/ui/api/settings/links/{a_id}/pull").json()
    assert out["state"] == "active" and "didn't answer" in out["lastError"]
    assert out["failingSince"]


# ---------- sharing with linked people (S10.3.3, S10.4)

from conftest import sign_in  # noqa: E402


def test_an_item_is_shared_read_only_with_a_linked_servers_people(admins):
    a, b, ca, cb, _ = admins
    make_user(b, "bart")
    a_id, _ = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    acct = make(jane, "Acct", name="Brokerage", type="brokerage").json()
    v = jane.get(f"/ui/api/shares/account/{acct['id']}").json()
    peers = v["links"]
    assert len(peers) == 1 and peers[0]["linkId"] == a_id
    bart = next(u for u in peers[0]["users"] if u["displayName"] != "Admin B")
    assert all(u["id"] != bart["id"] for u in v["users"]), "remote people only under their server"
    r = share(jane, "account", acct["id"], users={bart["id"]: "write"})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "read-only"
    r = share(jane, "account", acct["id"], users={bart["id"]: "read"}, receipts={a_id: True})
    assert r.status_code == 200, r.text
    after = jane.get(f"/ui/api/shares/account/{acct['id']}").json()["links"][0]
    assert after["includeReceipts"] is True
    assert next(u for u in after["users"] if u["id"] == bart["id"])["allow"] == "read"
    # Ending the link removes the share.
    ca.post(f"/ui/api/settings/links/{a_id}/end")
    v = jane.get(f"/ui/api/shares/account/{acct['id']}").json()
    assert v["links"] == []
    from moolakata import sharing

    with a.db.read(unscoped="test") as s:
        assert list(sharing.every_share(s)) == []


# ---------- pulls (S11.3.1, S11.4, S11.9.5)

from test_accounts import add, wait_job  # noqa: E402

from moolakata.links import copy as lcopy  # noqa: E402
from moolakata.links import copydb  # noqa: E402


def docs_in(srv, link_id):
    o = srv.copies.get(link_id)
    with o.engine.connect() as conn:
        items = {r.id: r for r in conn.execute(copydb.Item.select())}
        docs = {
            (r.itemId, r.path, r.viewer): json.loads(r.body, parse_float=str)
            for r in conn.execute(copydb.Doc.select())
        }
    return items, docs


import json  # noqa: E402


def test_a_shared_account_reaches_the_people_it_names_as_its_screens_show_it(admins):
    a, b, ca, cb, _ = admins
    make_user(b, "bart")
    make_user(b, "dave")
    a_id, b_id = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    acct = make(jane, "Acct", name="Mom's checking", type="checking").json()
    add(jane, acct["id"], amount="1200.00", payee="Pension")
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    share(jane, "account", acct["id"], users={bart_here["id"]: "read"})
    # Before B has an access key, it learns only who the item names, not what it is.
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    bart = sign_in(b, "bart")
    dave = sign_in(b, "dave")
    homes = bart.get("/ui/api/linked").json()["items"]
    assert len(homes) == 1 and homes[0]["items"] == 1 and homes[0]["name"]
    assert dave.get("/ui/api/linked").json()["items"] == [], "dave is named by nothing"
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    cb.post(f"/ui/api/settings/links/{b_id}/pull")  # the new copy asks for everything
    st = bart.get(f"/ui/api/linked/{b_id}").json()
    assert st["waiting"] == 1 and st["household"]["locked"]
    r = bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 200, r.text
    items, docs = docs_in(b, b_id)
    bart_id = bart.get("/ui/api/session").json()["user"]["id"]
    assert items[acct["id"]].name == "Mom's checking"
    assert json.loads(items[acct["id"]].viewers) == [bart_id]
    detail = docs[(acct["id"], f"/accounts/{acct['id']}", bart_id)]
    assert detail["balance"] == "1200.00"
    txns = docs[(acct["id"], f"/transactions?account={acct['id']}", bart_id)]
    assert [t["payee"] for t in txns["items"]] == ["Pension"]
    assert (acct["id"], "", bart_id) in docs, "its row in the accounts list"
    # The window reads them through the API, only for the people they name.
    rows = bart.get(f"/ui/api/linked/{b_id}/items").json()["items"]
    assert [(r["kind"], r["name"]) for r in rows] == [("account", "Mom's checking")]
    assert rows[0]["row"]["balance"] == "1200.00"
    got = bart.get(f"/ui/api/linked/{b_id}/doc", params={"path": f"/accounts/{acct['id']}"})
    assert got.status_code == 200 and got.json()["balance"] == "1200.00"
    assert bart.get(f"/ui/api/linked/{b_id}/doc", params={"path": "/accounts"}).status_code == 404
    assert dave.get(f"/ui/api/linked/{b_id}/items").status_code == 404
    homes = bart.get("/ui/api/linked").json()["items"]
    assert homes[0]["colour"] == "teal" and not homes[0]["locked"]
    r = create(bart, "LkCol", linkId=b_id, colour="amber")
    assert saved(r)["household"]["colour"] == "amber"
    bart.post(f"/ui/api/linked/{b_id}/lock")
    assert bart.get(f"/ui/api/linked/{b_id}/items").status_code == 423
    bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    # Only what changed travels.
    add(jane, acct["id"], amount="-40.00", payee="Pharmacy")
    ca.post(f"/ui/api/settings/links/{a_id}/pull")  # either side can make the exchange
    items, docs = docs_in(b, b_id)
    assert docs[(acct["id"], f"/accounts/{acct['id']}", bart_id)]["balance"] == "1160.00"
    nothing = a  # the next exchange with nothing new sends no change
    from moolakata.store.entities.links import Link

    with nothing.db.read(unscoped="test") as s:
        seq = s.get(Link, a_id).sentSeq
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    with a.db.read(unscoped="test") as s:
        assert s.get(Link, a_id).sentSeq == seq
    # A share removed: the item goes.
    share(jane, "account", acct["id"], users={bart_here["id"]: "none"})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    items, docs = docs_in(b, b_id)
    assert items == {} and docs == {}
    assert bart.get("/ui/api/linked").json()["items"] == []
    # The link ended: the copy goes.
    ca.post(f"/ui/api/settings/links/{a_id}/end")
    assert not lcopy.folder(b.config.data_dir, b_id).exists()


def test_a_reset_copy_is_pulled_again_in_full(admins):
    a, b, ca, cb, _ = admins
    make_user(b, "bart")
    _a_id, b_id = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    acct = make(jane, "Acct", name="IRA", type="ira").json()
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    share(jane, "account", acct["id"], users={bart_here["id"]: "read"})
    cb.post(f"/ui/api/settings/links/{b_id}/copy-key")
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    wait_job(cb, cb.post(f"/ui/api/settings/links/{b_id}/reset-copy").json())
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    bart = sign_in(b, "bart")
    assert (
        bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)}).status_code
        == 200
    )
    items, _ = docs_in(b, b_id)
    assert set(items) == {acct["id"]}


def test_receipts_cross_only_when_included_and_open_through_decryption(admins):
    from test_receipts import png

    a, b, ca, cb, _ = admins
    make_user(b, "bart")
    a_id, b_id = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    acct = make(jane, "Acct", name="Checking", type="checking").json()
    t = add(jane, acct["id"], amount="-12.50", payee="Blue Bottle")
    image = png()
    rid = jane.post(
        "/ui/api/receipts", files={"file": ("r.png", image, "application/octet-stream")}
    ).json()["id"]
    saved(attach(jane, rid, t["id"]))
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    share(jane, "account", acct["id"], users={bart_here["id"]: "read"})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    bart = sign_in(b, "bart")
    bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    assert bart.get(f"/ui/api/linked/{b_id}/files").json()["items"] == [], "not included: not sent"
    share(jane, "account", acct["id"], users={bart_here["id"]: "read"}, receipts={a_id: True})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    files = bart.get(f"/ui/api/linked/{b_id}/files").json()["items"]
    assert len(files) == 1 and files[0]["meta"]["transactionId"] == t["id"]
    sealed_dir = lcopy.folder(b.config.data_dir, b_id) / "receipts"
    on_disk = list(sealed_dir.glob("*.mkr"))
    assert len(on_disk) == 1 and image[:64] not in on_disk[0].read_bytes()
    got = bart.get(f"/ui/api/linked/{b_id}/files/{files[0]['id']}")
    assert got.status_code == 200 and got.content == image
    # Served as a local receipt is (S11.9.6.5, S13.7.7): its type from its bytes, in a sandbox.
    assert got.headers["content-type"] == "image/png"
    assert got.headers["content-security-policy"] == "sandbox"
    assert got.headers["content-disposition"].startswith("inline")
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in got.headers["cache-control"]
    # A type the bytes don't bear out is never served, whatever the copy's row says.
    with b.copies.get(b_id).engine.begin() as conn:
        conn.execute(copydb.File.update().values(contentType="text/html"))
    got = bart.get(f"/ui/api/linked/{b_id}/files/{files[0]['id']}")
    assert got.status_code == 415 and got.json()["code"] == "receipt-type"
    # Not included any more: the receipt and its sealed file go.
    share(jane, "account", acct["id"], users={bart_here["id"]: "read"}, receipts={a_id: False})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    assert bart.get(f"/ui/api/linked/{b_id}/files").json()["items"] == []
    assert list(sealed_dir.glob("*.mkr")) == []


def test_sharing_with_a_linked_server_needs_the_password_again(admins):
    """S13.7.2: a share that sends more across a link, and Include receipts turned on."""
    from conftest import stale

    a, b, ca, cb, _ = admins
    make_user(b, "bart")
    a_id, _b_id = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    acct = make(jane, "Acct", name="IRA", type="ira").json()
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    stale(a)
    to_bart = {bart_here["id"]: "read"}
    r = share(jane, "account", acct["id"], users=to_bart)
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "reauth-required"
    pw = "a long user passphrase"
    assert jane.post("/ui/api/session/reauth", json={"password": pw}).status_code == 204
    assert share(jane, "account", acct["id"], users=to_bart).status_code == 200
    stale(a)
    # The same share saved again asks nothing; its receipts turned on do.
    assert share(jane, "account", acct["id"], users=to_bart).status_code == 200
    r = share(jane, "account", acct["id"], users=to_bart, receipts={a_id: True})
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "reauth-required"


def test_a_linked_receipts_type_comes_from_its_bytes(tmp_path):
    """What a source calls a file never decides how it is shown (S11.9.6.5): a page with a
    script is unknown, a PNG a PNG, once the copy opens what its source sealed; and a thumbnail
    is kept only as an image."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from test_receipts import png

    from moolakata.links import changes, sealed

    copy = X25519PrivateKey.generate()
    public = copy.public_key().public_bytes_raw()
    for fid, data, kind in (
        ("Rcpt_a", b"<html><script src=/ui/api/linked/x/files/y></script></html>", None),
        ("Rcpt_b", png(), "image/png"),
    ):
        path = tmp_path / f"{fid}.mkr"
        sealed.write(path, sealed.seal(public, sealed.RECEIPT, "s>r", fid, [data]))
        assert changes._type_of(copy, "s>r", fid, path) == (kind or "application/octet-stream")
        assert changes._type_of(copy, "r>s", fid, path) == "application/octet-stream", (
            "sealed for one direction, it opens for no other"
        )
    assert changes._thumbnail("data:image/webp;base64,AAAA") == "data:image/webp;base64,AAAA"
    for bad in ("javascript:alert(1)", "data:text/html;base64,AAAA", None, 7):
        assert changes._thumbnail(bad) is None


def test_a_share_waiting_for_its_access_key_alerts_the_admins(admins):
    from moolakata import alerts

    a, b, ca, cb, _ = admins
    make_user(b, "bart")
    _a_id, b_id = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    acct = make(jane, "Acct", name="Checking", type="checking").json()
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    share(jane, "account", acct["id"], users={bart_here["id"]: "read"})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    kinds = {x.kind for x in alerts.evaluate(b)}
    assert "link-key-waiting" in kinds
    cb.post(f"/ui/api/settings/links/{b_id}/copy-key")
    assert "link-key-waiting" not in {x.kind for x in alerts.evaluate(b) if not x.resolvedAt}


# ---------- links, the rest (S11.4, S11.7, S12.13)


def test_a_pause_lasts_its_duration_and_the_peer_isnt_alerted(admins):
    import datetime as dt

    from moolakata import clock
    from moolakata.links import manage

    a, _b, ca, cb, _ = admins
    a_id, b_id = linked(ca, cb)
    for text in ("a week", "52w 1m", "1000000w"):  # a pause is at most 52 weeks (S11.7.2)
        r = ca.post(f"/ui/api/settings/links/{a_id}/pause", json={"for": text})
        assert (r.status_code, r.json()["code"]) == (422, "duration-invalid"), text
    out = ca.post(f"/ui/api/settings/links/{a_id}/pause", json={"for": "2d"}).json()
    assert out["state"] == "paused" and out["pausedUntil"]
    pulled = cb.post(f"/ui/api/settings/links/{b_id}/pull").json()
    assert "paused" in pulled["lastError"] and pulled["failingSince"] is None, "not alerted"
    assert manage.resume_due(a) == 0
    clock.fix(clock.now() + dt.timedelta(days=2, minutes=1))
    try:
        assert manage.resume_due(a) == 1, "it resumes on its own"
    finally:
        clock.fix(None)
    assert links_of(ca)["links"][0]["state"] == "active"
    # Resume now ends a pause early.
    ca.post(f"/ui/api/settings/links/{a_id}/pause", json={"for": "1d"})
    assert ca.post(f"/ui/api/settings/links/{a_id}/resume").json()["pausedUntil"] is None


def test_a_large_change_arrives_in_parts_oldest_first(admins, monkeypatch):
    from moolakata.links import serve

    a, b, ca, cb, _ = admins
    make_user(b, "bart")
    _a_id, b_id = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    ids_ = []
    for year in (2020, 2023, 2026):
        acct = make(jane, "Acct", name=f"Account {year}", type="checking").json()
        add(jane, acct["id"], amount="10.00", day=f"{year}-03-02", payee="Opening")
        if year == 2026:  # a long history: its transactions travel in pieces by date
            for month in range(4, 10):
                add(jane, acct["id"], amount="-1.00", day=f"2026-{month:02}-01", payee="Shop")
        share(jane, "account", acct["id"], users={bart_here["id"]: "read"})
        ids_.append(acct["id"])
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    seen: list[dict] = []
    real = serve.split

    def small(change):
        parts = real(change)
        seen.extend(parts)
        return parts

    monkeypatch.setattr(serve, "PART_BYTES", 2000)
    monkeypatch.setattr(serve, "split", small)
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    assert len(seen) > 2, "a large change travels in parts"
    throughs = [p["progress"]["through"] for p in seen]
    assert throughs == sorted(throughs), "oldest to newest"
    assert seen[-1]["progress"]["bytes"] == seen[-1]["progress"]["total"]
    side = links_of(cb)["links"][0]
    assert side["syncTotal"] is None, "all of it arrived"
    bart = sign_in(b, "bart")
    bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    items, docs = docs_in(b, b_id)
    assert set(ids_) <= set(items), "every part applied, in order"
    pieces = [
        d
        for p in seen
        for d in p.get("docs") or []
        if d["path"] == f"/transactions?account={ids_[2]}"
    ]
    assert len(pieces) > 1 and pieces[0].get("append") is None and pieces[-1]["append"]
    long = next(v for k, v in docs.items() if k[1] == f"/transactions?account={ids_[2]}")
    days = [t["date"] for t in long["items"]]
    assert days == sorted(days, reverse=True) and len(days) == 7, "whole, newest first"


def test_a_remote_user_is_a_person_of_their_own_until_someone_joins_them(admins):
    """S10.10.1: a linked server's user never takes over a person here by its name; one
    who may change that person joins them, and its privacy stays as it was."""
    from moolakata.store.entities.education import Person
    from moolakata.store.entities.users import User

    a, b, ca, cb, _ = admins
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    plan = {"id": make(jane, "GfPln", name="Bart", sex="male", private=True).json()["personId"]}
    make_user(b, "bart")
    linked(ca, cb)
    with a.db.read(unscoped="test") as s:
        bart = s.query(User).filter(User.username == "bart", User.linkId.is_not(None)).one()
        assert bart.personId != plan["id"], "not joined by name"
        assert s.get(Person, plan["id"]).private
    row = jane.get(f"/ui/api/persons/{plan['id']}").json()
    assert [r["id"] for r in row["sameAs"]] == [bart.id]
    r = jane.post(f"/ui/api/persons/{plan['id']}/join", json={"userId": bart.id})
    assert r.status_code == 200, r.text
    with a.db.read(unscoped="test") as s:
        assert s.get(User, bart.id).personId == plan["id"]
        assert s.get(Person, plan["id"]).private, "joining never changes whether it is private"
    # Exchanges keep the joined person's name as it is here.
    ca.post(f"/ui/api/settings/links/{links_of(ca)['links'][0]['id']}/pull")
    with a.db.read(unscoped="test") as s:
        assert s.get(Person, plan["id"]).name == "Bart"


def test_an_answer_names_its_caller_and_its_call():
    """link-protocol.md §3.3: a signed answer handed on to another caller, or to another
    request, is refused."""
    k = signing.Ed25519PrivateKey.generate()
    pub = keys.raw_public(k.public_key())
    asked = signing.Asked("n0nce-n0nce", "a" * 64, signing.body_hash(b"{}"))
    headers = signing.sign_answer(k, 200, b'{"ok":true}', asked)
    signing.verify_answer(pub, 200, b'{"ok":true}', asked, headers)
    for other in (
        signing.Asked("n0nce-n0nce", "b" * 64, asked.body_hash),
        signing.Asked("n0nce-n0nce", asked.caller_fp, signing.body_hash(b'{"x":1}')),
        signing.Asked("another-nonce", asked.caller_fp, asked.body_hash),
    ):
        with pytest.raises(signing.Refused) as e:
            signing.verify_answer(pub, 200, b'{"ok":true}', other, headers)
        assert e.value.code == "bad-signature"


def test_only_link_ended_ends_a_link_and_not_linked_marks_it_broken(admins):
    """S11.6: a peer restored from an older backup answers `not-linked`; the link is marked
    broken and alerts admins, and nothing is deleted."""
    from moolakata import alerts
    from moolakata.links import manage

    a, b, ca, cb, _ = admins
    a_id, _b_id = linked(ca, cb)
    other = keys.b64(keys.raw_public(signing.Ed25519PrivateKey.generate().public_key()))
    with b.db.tx(unscoped="test") as s:  # b has no link with a's key, as an older backup wouldn't
        s.query(Link).update({Link.peerKey: other})
    out = ca.post(f"/ui/api/settings/links/{a_id}/pull").json()
    assert out["state"] == "active" and "no link with this one" in out["lastError"]
    with a.db.read(unscoped="test") as s:
        assert s.get(Link, a_id).brokenAt is not None
    alerts.evaluate(a)
    assert any(x["kind"] == "link-broken" for x in ca.get("/ui/api/alerts").json()["open"])
    assert manage.pins  # the module is there for what follows


def test_what_crosses_a_link_is_sealed_to_the_receiving_copy(admins):
    """S11.9.6, link-protocol.md §4.4: in transit, a change shows its registry only; its items'
    names and figures, and its receipts, open only with the receiving copy's key."""
    from test_accounts import add

    a, b, ca, cb, wire = admins
    make_user(b, "bart")
    _a_id, b_id = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    acct = make(jane, "Acct", name="Secret Brokerage", type="brokerage")
    acct = acct.json()
    add(jane, acct["id"], amount="-1234.56", payee="A very private payee")
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    share(jane, "account", acct["id"], users={bart_here["id"]: "read"})
    seen: list[bytes] = []
    wire.watch = lambda request, body: seen.extend([request.content, body])
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    wire.watch = None
    wire_bytes = b"".join(seen)
    assert b"Secret Brokerage" not in wire_bytes and b"A very private payee" not in wire_bytes
    assert b'"sealed"' in wire_bytes, "the change crossed, sealed"
    bart = sign_in(b, "bart")
    bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    items, _ = docs_in(b, b_id)
    assert [i.name for i in items.values()] == ["Secret Brokerage"], "the copy opens it"


def test_a_malformed_change_is_set_aside_and_everything_asked_for(admins, monkeypatch):
    """S11.9.5.3: a signed change that isn't in a change's shape stops nothing: it is set
    aside, recorded on the link, and the next pull asks for everything."""
    from moolakata.links import changes
    from moolakata.store.entities.links import Link

    a, b, ca, cb, _wire = admins
    make_user(b, "bart")
    _a_id, b_id = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    acct = make(jane, "Acct", name="Brokerage", type="brokerage").json()
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    share(jane, "account", acct["id"], users={bart_here["id"]: "read"})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    assert changes.waiting(b.config.data_dir, b_id)
    texts = [e["text"] for e in cb.get("/ui/api/activity").json()["items"]]
    assert "Admin B asked moolakata for its changes now" in texts, texts[:4]
    assert any("changed items: Jane" in t and "account for Bart" in t for t in texts), texts[:4]
    real = changes.open_part
    monkeypatch.setattr(changes, "open_part", lambda *x: {**real(*x), "items": [{"id": 5}]})
    bart = sign_in(b, "bart")
    r = bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 200, r.text
    assert changes.waiting(b.config.data_dir, b_id) == []
    with b.db.read(unscoped="test") as s:
        link = s.get(Link, b_id)
        assert link.needsFull and "asked for" in link.lastError


def test_a_peers_own_certificate_is_pinned_announced_and_accepted(admins):
    """link-protocol.md §4.5: an announced key is accepted beside the pinned one and becomes
    the pinned one once in use; one presented unannounced waits for an admin to accept it,
    after the password again."""
    from moolakata.links import client as link_client
    from moolakata.links import manage

    a, _b, ca, cb, wire = admins
    a_id, _ = linked(ca, cb)
    old, new, rogue = "aa" * 32, "bb" * 32, "cc" * 32
    wire.certs["b.test"] = old
    with a.db.tx(unscoped="test") as s:
        s.get(Link, a_id).peerCert = old
    with a.db.read(unscoped="test") as s:
        assert manage.pins(s.get(Link, a_id)) == {old}
    with a.db.read(unscoped="test") as s:
        manage.answer_certificate(a, s.get(Link, a_id), {"fingerprint": new})
    with a.db.read(unscoped="test") as s:
        assert manage.pins(s.get(Link, a_id)) == {old, new}
    wire.certs["b.test"] = new  # B moves to the key it announced
    manage.call(a, a_id, "/link/v1/ping")
    with a.db.read(unscoped="test") as s:
        row = s.get(Link, a_id)
        assert (row.peerCert, row.peerCertNext) == (new, None), "in use: now the pinned one"
    wire.certs["b.test"] = rogue  # one it never announced
    with pytest.raises(link_client.LinkError):
        manage.call(a, a_id, "/link/v1/ping")
    shown = next(x for x in links_of(ca)["links"] if x["id"] == a_id)
    assert shown["certificateOffered"] == rogue and shown["certificate"] == keys.short(new)
    r = ca.post(f"/ui/api/settings/links/{a_id}/accept-certificate")
    assert r.status_code == 200 and r.json()["certificate"] == keys.short(rogue)
    assert r.json()["certificateOffered"] is None


def test_calls_no_known_key_signs_are_limited_by_address(server):
    # 60 a minute, counted before a body is read (S13.7.5.4).
    from conftest import new_client

    with new_client(server) as c:
        answers = [c.get("/link/v1/hello") for _ in range(61)]
    assert [r.status_code for r in answers[:60]] == [200] * 60
    # link-protocol.md §7: `limit`, unsigned for an address.
    assert answers[60].status_code == 429 and answers[60].json()["code"] == "limit"


def test_a_peers_refusal_is_told_in_this_servers_own_words():
    # S13.7.9: a linked server's message stays in the log; alerts and emails say it this
    # server's way, by its code.
    assert client.refusal("clock-skew", 403) == (
        "The other server says this server's time is more than a minute off."
    )
    assert client.refusal("link-paused", 403) == "The link is paused on the other server."
    assert client.refusal("whatever", 403) == (
        "The other server refused the call (whatever, HTTP 403)."
    )


def test_a_peers_code_outside_the_protocols_table_is_refused_here(pair, monkeypatch):
    # S13.8.3: a peer never decides this server's codes. One in link-protocol.md §7's table is
    # kept (told in this server's words); any other is `refused`, the peer's code in the log.
    from moolakata.links import manage

    a, b, (_, url_b), _ = pair
    reach(a, "b.test")
    for sent, kept in (
        ("made-up", "refused"),
        ("link-bogus", "refused"),
        ("code-used", "code-used"),
    ):
        monkeypatch.setattr(manage, "answer_join", lambda *_, sent=sent: {"error": (sent, "no")})
        with pytest.raises(client.LinkError) as e:
            client.call(a, url_b, public(b), "/link/v1/join", {})
        assert e.value.code == kept
        assert e.value.code in client.LinkError.CODES
    assert client.peer_code("link-paused") == "link-paused"
    assert client.peer_code(["code-used"]) == "refused"


def test_a_person_crosses_a_link_with_their_relationships_and_a_pull_names_its_link(admins):
    # S10.3: a person is one of the eight shareable kinds, and goes, read only, to named
    # people on a linked server; S11.8: a pull's Activity names the household it came from.
    a, b, ca, cb, _ = admins
    make_user(b, "bart")
    _, b_id = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    rose = make(
        jane, "Persn", name="Grandma Rose", sex="female", birthMonth=5, birthDay=3, private=True
    ).json()
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    r = share(jane, "person", rose["id"], users={bart_here["id"]: "read"})
    assert r.status_code == 200, r.text
    # S11.7: what flows each way, this side's by kind, owner and the people there it names.
    (out,) = links_of(ca)["links"][0]["outgoing"]
    assert (out["kind"], out["names"]) == ("person", [bart_here["displayName"]])
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    assert [x["kind"] for x in links_of(cb)["links"][0]["incoming"]] == ["person"]
    bart = sign_in(b, "bart")
    r = bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 200, r.text
    rows = bart.get(f"/ui/api/linked/{b_id}/items").json()["items"]
    assert [(r["kind"], r["name"]) for r in rows] == [("person", "Grandma Rose")]
    assert (rows[0]["row"]["birthMonth"], rows[0]["row"]["birthDay"]) == (5, 3)
    got = bart.get(
        f"/ui/api/linked/{b_id}/doc", params={"path": f"/persons/{rose['id']}/relations"}
    )
    assert got.status_code == 200 and got.json()["items"] == []
    from moolakata.store.entities.core import Activity

    with b.db.read(unscoped="test") as s:
        pulled = [x for x in s.query(Activity) if x.kind == "link.pulled"]
    assert pulled and all((x.subjectKind, x.subjectId) == ("link", b_id) for x in pulled)


def test_a_change_put_back_in_the_inbox_is_refused_and_everything_asked_for(admins):
    # S11.9.5.3: a change must follow the last one applied, so an older one put back while
    # the copy is locked can't bring back what was since removed.
    import shutil as sh

    a, b, ca, cb, _ = admins
    make_user(b, "bart")
    _, b_id = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    acct = make(jane, "Acct", name="Old", type="checking").json()
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    share(jane, "account", acct["id"], users={bart_here["id"]: "read"})
    words = " ".join(cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"])
    cb.post(f"/ui/api/settings/links/{b_id}/pull")  # waits in the inbox: the copy is locked
    inbox = lcopy.folder(b.config.data_dir, b_id) / "inbox"
    kept = b.config.data_dir / "kept"
    sh.copytree(inbox, kept)
    bart = sign_in(b, "bart")
    assert bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": words}).status_code == 200
    assert [r["name"] for r in bart.get(f"/ui/api/linked/{b_id}/items").json()["items"]]
    bart.post(f"/ui/api/linked/{b_id}/lock")
    for f in kept.iterdir():
        sh.copy(f, inbox / f.name)
    bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": words})
    with b.db.read(unscoped="test") as s:
        link = s.get(Link, b_id)
        assert link.needsFull and "doesn't follow the last one applied" in (link.lastError or "")


def test_a_released_copys_key_opens_nothing_more():
    # The copy's database key is overwritten at the release, and no new connection opens.
    from moolakata.store.db import HeldKey, WrongKey

    k = HeldKey(bytes(range(32)))
    assert k.text().startswith("x'000102")
    k.release()
    with pytest.raises(WrongKey):
        k.text()


def test_an_own_certificate_that_cant_be_read_is_not_announced_as_public(pair, monkeypatch):
    """link-protocol.md §4.5, S13.5: when this server's own link address can't be read for its
    certificate (the guard refuses it, or it doesn't answer), nothing is announced and the key
    last told stays; it isn't taken for a public certificate."""
    from moolakata import certs, settings
    from moolakata.links import manage

    a, b, _, _ = pair
    a_id = link(a, "https://b.test", public(b))
    told = "aa" * 32
    with a.db.tx(unscoped="test") as s:
        s.get(Link, a_id).ownCertTold = told
        settings.put(s, "linkAddress", "https://127.0.0.1:8443", None)
    monkeypatch.setattr(certs, "_cached", {})
    assert certs.own_key(a) is None
    assert manage.announce_certificate(a) == 0
    with a.db.read(unscoped="test") as s:
        assert s.get(Link, a_id).ownCertTold == told


def test_a_new_certificate_is_told_again_until_each_peer_has_it(admins, monkeypatch):
    """link-protocol.md §4.5: a peer that missed the announcement (down at that run) is told
    at the next run; one told isn't told again; a public certificate is never announced, and
    the key last told stays for a later one of this server's own."""
    from moolakata import certs
    from moolakata.links import manage

    a, b, ca, cb, wire = admins
    a_id, b_id = linked(ca, cb)
    own = {"key": "dd" * 32}
    monkeypatch.setattr(certs, "own_key_read", lambda srv, use="link": own["key"])
    wire.down.add("a.test")
    assert manage.announce_certificate(b) == 0
    with a.db.read(unscoped="test") as s:
        assert s.get(Link, a_id).peerCertNext is None
    with b.db.read(unscoped="test") as s:
        assert s.get(Link, b_id).ownCertTold is None, "not reached, so not told"
    wire.down.clear()
    assert manage.announce_certificate(b) == 1, "told at the next run"
    with a.db.read(unscoped="test") as s:
        assert s.get(Link, a_id).peerCertNext == own["key"]
    with b.db.read(unscoped="test") as s:
        assert s.get(Link, b_id).ownCertTold == own["key"]
    assert manage.announce_certificate(b) == 0, "told once it has it"
    own["key"] = None
    assert manage.announce_certificate(b) == 0
    with b.db.read(unscoped="test") as s:
        assert s.get(Link, b_id).ownCertTold == "dd" * 32


UNREAD = (
    "This server can't read its own certificate at its link address: check the link address in "
    "Settings › Linked Servers."
)


def test_no_invitation_while_this_servers_own_certificate_cant_be_read(admins, monkeypatch):
    """S11.1.3: an invitation carries this server's certificate key when the certificate is its
    own, so none is made while that certificate can't be read: the dialog says why, and no
    link waits for a code that would leave the peer pinning nothing."""
    from moolakata import certs, settings

    a, _, ca, _, _ = admins

    def unread(guard, address):
        raise certs.Unread

    monkeypatch.setattr(certs, "_probe", unread)
    monkeypatch.setattr(certs, "_cached", {})
    with a.db.tx(unscoped="test") as s:
        settings.put(s, "linkAddress", "https://a.test", None)
    assert a.config.mode == "proxy", "behind a proxy, whose certificate is read nowhere else"
    r = ca.post("/ui/api/settings/links/invitations")
    assert r.status_code == 422 and r.json()["code"] == "certificate-unread"
    assert r.json()["detail"] == UNREAD
    with a.db.read(unscoped="test") as s:
        assert s.query(Link).count() == 0


def _serving_tls_itself(srv) -> str:
    """This server in tls mode with its self-signed certificate made: its key's fingerprint."""
    import dataclasses

    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    from moolakata import net
    from moolakata.listener import self_signed

    srv.config = dataclasses.replace(srv.config, mode="tls")
    cert, _ = self_signed(srv.config.tls_dir, ["a.test"])
    der = x509.load_pem_x509_certificate(cert.read_bytes()).public_bytes(Encoding.DER)
    return net.key_fingerprint(der)


def _invited_pin(ca) -> str | None:
    r = ca.post("/ui/api/settings/links/invitations")
    assert r.status_code == 201, r.text
    from moolakata.links import manage

    return manage.decode_code(r.json()["code"]).get("t")


def test_an_invitation_pins_the_certificate_read_at_its_link_address(admins, monkeypatch):
    """S11.1.1: the certificate an invitation carries is the one read at the address it
    carries, which the other server connects to, even when this server serves TLS itself: the
    address may lead through a proxy of its own."""
    from moolakata import certs, settings

    a, _, ca, _, _ = admins
    at_address = "cc" * 32
    read = []

    def probe(guard, address):
        read.append(address)
        return at_address

    monkeypatch.setattr(certs, "_probe", probe)
    _serving_tls_itself(a)
    with a.db.tx(unscoped="test") as s:
        settings.put(s, "linkAddress", "https://a.test", None)
    assert _invited_pin(ca) == at_address
    assert read == ["https://a.test"]


def test_an_invitation_pins_the_listeners_own_certificate_when_its_address_cant_be_reached(
    admins, monkeypatch
):
    """S11.1.1: a server that can't reach its own public address (a router with no NAT
    hairpinning) and serves TLS itself pins the certificate its listener serves, from the
    files it loads."""
    from moolakata import certs, settings

    a, _, ca, _, _ = admins

    def unread(guard, address):
        raise certs.Unread

    monkeypatch.setattr(certs, "_probe", unread)
    own = _serving_tls_itself(a)
    with a.db.tx(unscoped="test") as s:
        settings.put(s, "linkAddress", "https://a.test", None)
    assert _invited_pin(ca) == own


def test_a_link_at_the_smtp_servers_loopback_address_is_still_refused(pair):
    """S11.2, S13.5: a link's address is never loopback, whoever names that host: an SMTP
    server an admin set at 127.0.0.1 is exempt for the mail client alone."""
    from moolakata import settings
    from moolakata.ui.prices import apply_egress

    a, b, _, _ = pair
    with a.db.tx(unscoped="test") as s:
        settings.put(s, "smtpHost", "127.0.0.1", None)
    link(a, "https://127.0.0.1:2019", public(b))
    apply_egress(a)
    with pytest.raises(client.LinkError, match=r"didn't answer \(EgressRefused\)"):
        client.hello(a, "https://127.0.0.1:2019")


def test_an_unsigned_limit_or_locked_answer_is_taken_as_it_says(pair, monkeypatch):
    # link-protocol.md §7: refused before the answering server could sign to the call.
    import httpx

    from moolakata import net

    a, b, (_, url_b), _ = pair
    reach(a, "b.test")
    for status, code in ((429, "limit"), (503, "locked"), (413, "too-large")):
        answer = httpx.Response(status, json={"code": "rate-limited"})
        monkeypatch.setattr(
            net, "network", lambda g, p, answer=answer: httpx.MockTransport(lambda r: answer)
        )
        with pytest.raises(client.LinkError) as e:
            client.call(a, url_b, public(b), "/link/v1/ping")
        assert e.value.code == code


# ---------- one receipt never holds a change back (S11.4)


def _shared_receipt(a, ca, cb):
    """Jane on A shares an account with Bart on B, its receipts included; Bart's copy has
    its access key. Returns Jane, Bart, B's link id and the receipt's bytes."""
    from test_receipts import png

    make_user(a, "jane")
    jane = sign_in(a, "jane")
    a_id, b_id = linked(ca, cb)
    acct = make(jane, "Acct", name="Checking", type="checking").json()
    t = add(jane, acct["id"], amount="-12.50", payee="Blue Bottle")
    image = png()
    rid = jane.post(
        "/ui/api/receipts", files={"file": ("r.png", image, "application/octet-stream")}
    ).json()["id"]
    saved(attach(jane, rid, t["id"]))
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    share(jane, "account", acct["id"], users={bart_here["id"]: "read"}, receipts={a_id: True})
    return jane, words, b_id, image


def test_a_receipt_that_cant_be_fetched_holds_nothing_back_and_comes_later(admins):
    import httpx

    from moolakata.store.entities.links import LinkFile

    a, b, ca, cb, wire = admins
    make_user(b, "bart")
    _jane, words, b_id, image = _shared_receipt(a, ca, cb)
    # Every receipt file the source sends is cut off, as one past a ceiling would be.
    wire.fail = lambda m, url, kw: httpx.ReadError("cut off") if url.endswith("/file") else None
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    bart = sign_in(b, "bart")
    assert bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)}).is_success
    # The change arrived without it: the account is there, the receipt marked not arrived.
    assert bart.get(f"/ui/api/linked/{b_id}/items").json()["items"]
    (f,) = bart.get(f"/ui/api/linked/{b_id}/files").json()["items"]
    assert f["arrived"] is False
    got = bart.get(f"/ui/api/linked/{b_id}/files/{f['id']}")
    assert got.status_code == 404 and got.json()["code"] == "not-arrived"
    link = next(x for x in links_of(cb)["links"] if x["id"] == b_id)
    assert link["lastError"] is None and link["failingSince"] is None, "the link is fine"
    with b.db.read(unscoped="test") as s:
        (row,) = s.query(LinkFile).all()
        assert row.fileName is None and row.tries == 1 and row.error
    # The next exchange asks for it again, and it reaches the open copy.
    wire.fail = None
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    (f,) = bart.get(f"/ui/api/linked/{b_id}/files").json()["items"]
    assert f["arrived"] is True
    got = bart.get(f"/ui/api/linked/{b_id}/files/{f['id']}")
    assert got.status_code == 200 and got.content == image
    with b.db.read(unscoped="test") as s:
        assert s.query(LinkFile).count() == 0


def test_a_receipt_fetched_while_the_copy_is_locked_reaches_it_at_the_unlock(admins):
    import httpx

    a, b, ca, cb, wire = admins
    make_user(b, "bart")
    _jane, words, b_id, image = _shared_receipt(a, ca, cb)
    wire.fail = lambda m, url, kw: httpx.ReadError("cut off") if url.endswith("/file") else None
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    wire.fail = None
    cb.post(f"/ui/api/settings/links/{b_id}/pull")  # fetched now, the copy still locked
    bart = sign_in(b, "bart")
    assert bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)}).is_success
    (f,) = bart.get(f"/ui/api/linked/{b_id}/files").json()["items"]
    assert f["arrived"] is True
    assert bart.get(f"/ui/api/linked/{b_id}/files/{f['id']}").content == image


def test_a_failure_after_the_exchange_call_is_recorded_on_the_link(admins):
    import httpx

    a, b, ca, cb, wire = admins
    make_user(a, "jane")
    _a_id, b_id = linked(ca, cb)
    make_user(b, "john")
    john = sign_in(b, "john")
    acct = make(john, "Acct", name="Savings", type="savings").json()
    jane_there = next(u for u in links_of(cb)["links"][0]["users"] if u["username"] == "jane")
    assert share(john, "account", acct["id"], users={jane_there["id"]: "read"}).status_code == 200
    # This side's change can't be delivered after the exchange call went through.
    wire.fail = lambda m, url, kw: (
        httpx.ConnectError("dropped") if url.endswith("/link/v1/deliver") else None
    )
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    link = next(x for x in links_of(cb)["links"] if x["id"] == b_id)
    assert link["lastError"] and link["failingSince"], "recorded, so the alert follows"
    wire.fail = None
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    link = next(x for x in links_of(cb)["links"] if x["id"] == b_id)
    assert link["lastError"] is None and link["failingSince"] is None


def test_the_limits_fit_the_paths_a_receipt_travels(pair, monkeypatch):
    """S17.5: the largest receipt Settings allows fits every path it takes across a link: a
    `deliver` body and a `file` answer are bounded by it sealed, and the uploads in flight hold one.
    Statements against the uploads in flight are not covered here yet (See GH #237)."""
    from moolakata import middleware, net, settings
    from moolakata.links import sealed

    biggest = settings.FILE_MAX_MB * 1024 * 1024
    assert sealed.max_receipt() == sealed.sealed_size(biggest) > biggest > net.MAX_RESPONSE
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = X25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    for n in (0, 1, sealed.CHUNK - 1, sealed.CHUNK, sealed.CHUNK + 1, 3 * sealed.CHUNK + 7):
        out = b"".join(sealed.seal(key, sealed.RECEIPT, "l", "f", [b"x" * n]))
        assert len(out) == sealed.sealed_size(n), n
    assert sealed.max_receipt() <= middleware.IN_FLIGHT
    # A linked server's receipt body may be the largest, whatever this server's own setting.
    mw = middleware.BodyLimit(None, lambda: 1024 * 1024)
    assert mw.limit_for("/link/v1/deliver", "application/octet-stream") == (
        sealed.max_receipt(),
        True,
    )
    assert mw.limit_for("/link/v1/deliver", "application/json") == (middleware.LINK_LIMIT, False)
    assert mw.limit_for("/ui/api/receipts", "multipart/form-data") == (1024 * 1024, True)
    # A receipt's file answer is read up to it; every other answer up to 20 MB.
    seen = []

    def fake_client(srv, pins, max_bytes=net.MAX_RESPONSE):
        seen.append(max_bytes)
        raise net.httpx.ConnectError("not here")

    monkeypatch.setattr(client, "_client", fake_client)
    with pytest.raises(client.LinkError):
        list(client.iter_file(pair[0], "https://b.test", bytes(32), "Rcpt_x", []))
    assert seen == [sealed.max_receipt()]
    check = settings.DEFINITIONS["receiptMaxMb"].check
    assert check(settings.FILE_MAX_MB) == settings.FILE_MAX_MB
    with pytest.raises(settings.Invalid):
        check(settings.FILE_MAX_MB + 1)


def test_a_locked_copys_inbox_names_no_one(admins):
    """S11.9.1: what waits in a locked copy's inbox is sealed, the change's registry beside it too:
    no owner's name, item id or user id in the clear; the unlock still checks and applies it."""
    from moolakata.store.entities.users import User

    a, b, ca, cb, _ = admins
    make_user(b, "bart")
    jane, words, b_id, _image = _shared_receipt(a, ca, cb)
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    inbox = lcopy.folder(b.config.data_dir, b_id) / "inbox"
    files = list(inbox.iterdir())
    assert files and {f.suffix for f in files} == {".mks", ".mke"}
    acct = jane.get("/ui/api/accounts").json()["items"][0]["id"]
    with b.db.read(unscoped="test") as s:
        bart_id = s.query(User).filter(User.username == "bart").one().id
    for f in files:
        body = f.read_bytes()
        assert body.startswith(b"MKR1"), f.name
        for plain in (b"Jane", acct.encode(), bart_id.encode()):
            assert plain not in body, (f.name, plain)
    bart = sign_in(b, "bart")
    assert bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)}).is_success
    assert bart.get(f"/ui/api/linked/{b_id}/items").json()["items"]
    assert not any(inbox.iterdir()), "applied"


def test_a_tax_books_document_files_cross_when_included(admins):
    """A tax book shared with Include receipts sends its documents' files, each named by its form
    and issuer; without the tick they stay home (S11.5.1)."""
    from test_receipts import png

    a, b, ca, cb, _ = admins
    make_user(b, "bart")
    a_id, b_id = linked(ca, cb)
    make_user(a, "jane")
    jane = sign_in(a, "jane")
    me = jane.get("/ui/api/session").json()["user"]["id"]
    book = make(jane, "TaxBk", year=2026, filers=[me]).json()
    image = png()
    rid = jane.post(
        "/ui/api/receipts", files={"file": ("w2.png", image, "application/octet-stream")}
    ).json()["id"]
    r = make(jane, "TxDoc", bookId=book["id"], form="W-2", issuer="Acme Corp", receiptId=rid)
    assert r.status_code == 200, r.text
    bart_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "bart")
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    share(jane, "tax-book", book["id"], users={bart_here["id"]: "read"})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    bart = sign_in(b, "bart")
    bart.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    assert bart.get(f"/ui/api/linked/{b_id}/files").json()["items"] == [], "not included"
    share(jane, "tax-book", book["id"], users={bart_here["id"]: "read"}, receipts={a_id: True})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    files = bart.get(f"/ui/api/linked/{b_id}/files").json()["items"]
    assert [f["meta"]["payee"] for f in files] == ["W-2 · Acme Corp"]
    got = bart.get(f"/ui/api/linked/{b_id}/files/{files[0]['id']}")
    assert got.status_code == 200 and got.content == image
