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
    srv.guard.allow(hosts, hosts)


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
    make_user(a, "alice")
    make_user(b, "carol")
    inv = ca.post("/ui/api/settings/links/invitations")
    assert inv.status_code == 201, inv.text
    code = inv.json()["code"]
    assert code.startswith("mkl1.") and inv.json()["link"]["state"] == "invited"
    joined = cb.post("/ui/api/settings/links/join", json={"code": code})
    assert joined.status_code == 201, joined.text
    assert joined.json()["state"] == "pending"
    assert joined.json()["fingerprint"] == links_of(ca)["fingerprint"]
    req = links_of(ca)["links"][0]
    assert req["state"] == "requested" and req["fingerprint"] == links_of(cb)["fingerprint"]
    # Nothing of either household crosses before the approval (S10.10.1, P5).
    assert req["users"] == [] and links_of(cb)["links"][0]["users"] == []
    with a.db.read(unscoped="test") as s:
        assert s.query(Person).filter(Person.name == "Carol").count() == 0
    again = cb.post("/ui/api/settings/links/join", json={"code": code})
    assert again.status_code == 422 and again.json()["code"] in ("code-used", "already-linked")
    r = ca.post(f"/ui/api/settings/links/{req['id']}/approve")
    assert r.status_code == 200 and r.json()["state"] == "active"
    b_side = links_of(cb)["links"][0]
    assert b_side["state"] == "active", "told at once by the approval's exchange"
    assert {u["username"] for u in b_side["users"]} == {"admin", "alice"}
    assert {u["username"] for u in links_of(ca)["links"][0]["users"]} == {"admin", "carol"}
    assert b_side["householdName"]
    # Remote users never sign in, and stay out of Users and Groups.
    assert all(u["username"] != "carol" for u in ca.get("/ui/api/users").json()["items"])


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


def test_pausing_stops_exchanges_and_ending_reaches_the_other_side(admins):
    _a, _b, ca, cb, wire = admins
    a_id, b_id = linked(ca, cb)
    assert ca.post(f"/ui/api/settings/links/{a_id}/pause").json()["state"] == "paused"
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
    make_user(b, "carol")
    a_id, _ = linked(ca, cb)
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    acct = make(alice, "Acct", name="Brokerage", type="brokerage").json()
    v = alice.get(f"/ui/api/shares/account/{acct['id']}").json()
    peers = v["links"]
    assert len(peers) == 1 and peers[0]["linkId"] == a_id
    carol = next(u for u in peers[0]["users"] if u["displayName"] != "Admin B")
    assert all(u["id"] != carol["id"] for u in v["users"]), "remote people only under their server"
    r = share(alice, "account", acct["id"], users={carol["id"]: "write"})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "read-only"
    r = share(alice, "account", acct["id"], users={carol["id"]: "read"}, receipts={a_id: True})
    assert r.status_code == 200, r.text
    after = alice.get(f"/ui/api/shares/account/{acct['id']}").json()["links"][0]
    assert after["includeReceipts"] is True
    assert next(u for u in after["users"] if u["id"] == carol["id"])["level"] == "read"
    # Ending the link removes the share.
    ca.post(f"/ui/api/settings/links/{a_id}/end")
    v = alice.get(f"/ui/api/shares/account/{acct['id']}").json()
    assert v["links"] == []
    from moolakata.store.entities.sharing import Share

    with a.db.read(unscoped="test") as s:
        assert s.query(Share).filter(Share.deleted.is_(False)).count() == 0


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
    make_user(b, "carol")
    make_user(b, "dave")
    a_id, b_id = linked(ca, cb)
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    acct = make(alice, "Acct", name="Mom's checking", type="checking").json()
    add(alice, acct["id"], amount="1200.00", payee="Pension")
    carol_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    share(alice, "account", acct["id"], users={carol_here["id"]: "read"})
    # Before B has an access key, it learns only who the item names, not what it is.
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    carol = sign_in(b, "carol")
    dave = sign_in(b, "dave")
    homes = carol.get("/ui/api/linked").json()["items"]
    assert len(homes) == 1 and homes[0]["items"] == 1 and homes[0]["name"]
    assert dave.get("/ui/api/linked").json()["items"] == [], "dave is named by nothing"
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    cb.post(f"/ui/api/settings/links/{b_id}/pull")  # the new copy asks for everything
    st = carol.get(f"/ui/api/linked/{b_id}").json()
    assert st["waiting"] == 1 and st["household"]["locked"]
    r = carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 200, r.text
    items, docs = docs_in(b, b_id)
    carol_id = carol.get("/ui/api/session").json()["user"]["id"]
    assert items[acct["id"]].name == "Mom's checking"
    assert json.loads(items[acct["id"]].viewers) == [carol_id]
    detail = docs[(acct["id"], f"/accounts/{acct['id']}", carol_id)]
    assert detail["balance"] == "1200.00"
    txns = docs[(acct["id"], f"/transactions?account={acct['id']}", carol_id)]
    assert [t["payee"] for t in txns["items"]] == ["Pension"]
    assert (acct["id"], "", carol_id) in docs, "its row in the accounts list"
    # The window reads them through the API, only for the people they name.
    rows = carol.get(f"/ui/api/linked/{b_id}/items").json()["items"]
    assert [(r["kind"], r["name"]) for r in rows] == [("account", "Mom's checking")]
    assert rows[0]["row"]["balance"] == "1200.00"
    got = carol.get(f"/ui/api/linked/{b_id}/doc", params={"path": f"/accounts/{acct['id']}"})
    assert got.status_code == 200 and got.json()["balance"] == "1200.00"
    assert carol.get(f"/ui/api/linked/{b_id}/doc", params={"path": "/accounts"}).status_code == 404
    assert dave.get(f"/ui/api/linked/{b_id}/items").status_code == 404
    homes = carol.get("/ui/api/linked").json()["items"]
    assert homes[0]["colour"] == "teal" and not homes[0]["locked"]
    r = create(carol, "LkCol", linkId=b_id, colour="amber")
    assert saved(r)["household"]["colour"] == "amber"
    carol.post(f"/ui/api/linked/{b_id}/lock")
    assert carol.get(f"/ui/api/linked/{b_id}/items").status_code == 423
    carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    # Only what changed travels.
    add(alice, acct["id"], amount="-40.00", payee="Pharmacy")
    ca.post(f"/ui/api/settings/links/{a_id}/pull")  # either side can make the exchange
    items, docs = docs_in(b, b_id)
    assert docs[(acct["id"], f"/accounts/{acct['id']}", carol_id)]["balance"] == "1160.00"
    nothing = a  # the next exchange with nothing new sends no change
    from moolakata.store.entities.links import Link

    with nothing.db.read(unscoped="test") as s:
        seq = s.get(Link, a_id).sentSeq
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    with a.db.read(unscoped="test") as s:
        assert s.get(Link, a_id).sentSeq == seq
    # A share removed: the item goes.
    share(alice, "account", acct["id"], users={carol_here["id"]: "none"})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    items, docs = docs_in(b, b_id)
    assert items == {} and docs == {}
    assert carol.get("/ui/api/linked").json()["items"] == []
    # The link ended: the copy goes.
    ca.post(f"/ui/api/settings/links/{a_id}/end")
    assert not lcopy.folder(b.config.data_dir, b_id).exists()


def test_a_reset_copy_is_pulled_again_in_full(admins):
    a, b, ca, cb, _ = admins
    make_user(b, "carol")
    _a_id, b_id = linked(ca, cb)
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    acct = make(alice, "Acct", name="IRA", type="ira").json()
    carol_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    share(alice, "account", acct["id"], users={carol_here["id"]: "read"})
    cb.post(f"/ui/api/settings/links/{b_id}/copy-key")
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    wait_job(cb, cb.post(f"/ui/api/settings/links/{b_id}/reset-copy").json())
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    carol = sign_in(b, "carol")
    assert (
        carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)}).status_code
        == 200
    )
    items, _ = docs_in(b, b_id)
    assert set(items) == {acct["id"]}


def test_receipts_cross_only_when_included_and_open_through_decryption(admins):
    from test_receipts import png

    a, b, ca, cb, _ = admins
    make_user(b, "carol")
    a_id, b_id = linked(ca, cb)
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    acct = make(alice, "Acct", name="Checking", type="checking").json()
    t = add(alice, acct["id"], amount="-12.50", payee="Blue Bottle")
    image = png()
    rid = alice.post(
        "/ui/api/receipts", files={"file": ("r.png", image, "application/octet-stream")}
    ).json()["id"]
    saved(attach(alice, rid, t["id"]))
    carol_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    share(alice, "account", acct["id"], users={carol_here["id"]: "read"})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    carol = sign_in(b, "carol")
    carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    assert carol.get(f"/ui/api/linked/{b_id}/files").json()["items"] == [], "not included: not sent"
    share(alice, "account", acct["id"], users={carol_here["id"]: "read"}, receipts={a_id: True})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    files = carol.get(f"/ui/api/linked/{b_id}/files").json()["items"]
    assert len(files) == 1 and files[0]["meta"]["transactionId"] == t["id"]
    sealed_dir = lcopy.folder(b.config.data_dir, b_id) / "receipts"
    on_disk = list(sealed_dir.glob("*.mkr"))
    assert len(on_disk) == 1 and image[:64] not in on_disk[0].read_bytes()
    got = carol.get(f"/ui/api/linked/{b_id}/files/{files[0]['id']}")
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
    got = carol.get(f"/ui/api/linked/{b_id}/files/{files[0]['id']}")
    assert got.status_code == 415 and got.json()["code"] == "receipt-type"
    # Not included any more: the receipt and its sealed file go.
    share(alice, "account", acct["id"], users={carol_here["id"]: "read"}, receipts={a_id: False})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    assert carol.get(f"/ui/api/linked/{b_id}/files").json()["items"] == []
    assert list(sealed_dir.glob("*.mkr")) == []


def test_sharing_with_a_linked_server_needs_the_password_again(admins):
    """S13.7.2: a share that sends more across a link, and Include receipts turned on."""
    from conftest import stale

    a, b, ca, cb, _ = admins
    make_user(b, "carol")
    a_id, _b_id = linked(ca, cb)
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    acct = make(alice, "Acct", name="IRA", type="ira").json()
    carol_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    stale(a)
    to_carol = {carol_here["id"]: "read"}
    r = share(alice, "account", acct["id"], users=to_carol)
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "reauth-required"
    pw = "a long user passphrase"
    assert alice.post("/ui/api/session/reauth", json={"password": pw}).status_code == 204
    assert share(alice, "account", acct["id"], users=to_carol).status_code == 200
    stale(a)
    # The same share saved again asks nothing; its receipts turned on do.
    assert share(alice, "account", acct["id"], users=to_carol).status_code == 200
    r = share(alice, "account", acct["id"], users=to_carol, receipts={a_id: True})
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
    make_user(b, "carol")
    _a_id, b_id = linked(ca, cb)
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    acct = make(alice, "Acct", name="Checking", type="checking").json()
    carol_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    share(alice, "account", acct["id"], users={carol_here["id"]: "read"})
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
    r = ca.post(f"/ui/api/settings/links/{a_id}/pause", json={"for": "a week"})
    assert r.json()["code"] == "duration-invalid"
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
    make_user(b, "carol")
    _a_id, b_id = linked(ca, cb)
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    carol_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    ids_ = []
    for year in (2020, 2023, 2026):
        acct = make(alice, "Acct", name=f"Account {year}", type="checking").json()
        add(alice, acct["id"], amount="10.00", day=f"{year}-03-02", payee="Opening")
        if year == 2026:  # a long history: its transactions travel in pieces by date
            for month in range(4, 10):
                add(alice, acct["id"], amount="-1.00", day=f"2026-{month:02}-01", payee="Shop")
        share(alice, "account", acct["id"], users={carol_here["id"]: "read"})
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
    carol = sign_in(b, "carol")
    carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
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
    """S10.10.1 (P5): a linked server's user never takes over a person here by its name; one
    who may change that person joins them, and its privacy stays as it was."""
    from moolakata.store.entities.education import Person
    from moolakata.store.entities.users import User

    a, b, ca, cb, _ = admins
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    plan = make(alice, "GfPln", name="Carol", sex="female", private=True).json()
    make_user(b, "carol")
    linked(ca, cb)
    with a.db.read(unscoped="test") as s:
        carol = s.query(User).filter(User.username == "carol", User.linkId.is_not(None)).one()
        assert carol.personId != plan["id"], "not joined by name"
        assert s.get(Person, plan["id"]).private
    row = next(p for p in alice.get("/ui/api/people").json()["items"] if p["id"] == plan["id"])
    assert [r["id"] for r in row["sameAs"]] == [carol.id]
    r = alice.post(f"/ui/api/persons/{plan['id']}/join", json={"userId": carol.id})
    assert r.status_code == 200, r.text
    with a.db.read(unscoped="test") as s:
        assert s.get(User, carol.id).personId == plan["id"]
        assert s.get(Person, plan["id"]).private, "joining never changes whether it is private"
    # Exchanges keep the joined person's name as it is here.
    ca.post(f"/ui/api/settings/links/{links_of(ca)['links'][0]['id']}/pull")
    with a.db.read(unscoped="test") as s:
        assert s.get(Person, plan["id"]).name == "Carol"


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
    make_user(b, "carol")
    _a_id, b_id = linked(ca, cb)
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    acct = make(alice, "Acct", name="Secret Brokerage", type="brokerage")
    acct = acct.json()
    add(alice, acct["id"], amount="-1234.56", payee="A very private payee")
    carol_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    share(alice, "account", acct["id"], users={carol_here["id"]: "read"})
    seen: list[bytes] = []
    wire.watch = lambda request, body: seen.extend([request.content, body])
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    wire.watch = None
    wire_bytes = b"".join(seen)
    assert b"Secret Brokerage" not in wire_bytes and b"A very private payee" not in wire_bytes
    assert b'"sealed"' in wire_bytes, "the change crossed, sealed"
    carol = sign_in(b, "carol")
    carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    items, _ = docs_in(b, b_id)
    assert [i.name for i in items.values()] == ["Secret Brokerage"], "the copy opens it"


def test_a_malformed_change_is_set_aside_and_everything_asked_for(admins, monkeypatch):
    """S11.9.5.3: a signed change that isn't in a change's shape stops nothing: it is set
    aside, recorded on the link, and the next pull asks for everything."""
    from moolakata.links import changes
    from moolakata.store.entities.links import Link

    a, b, ca, cb, _wire = admins
    make_user(b, "carol")
    _a_id, b_id = linked(ca, cb)
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    acct = make(alice, "Acct", name="Brokerage", type="brokerage").json()
    carol_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    share(alice, "account", acct["id"], users={carol_here["id"]: "read"})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    assert changes.waiting(b.config.data_dir, b_id)
    texts = [e["text"] for e in cb.get("/ui/api/activity").json()["items"]]
    assert any(t.endswith("asked a linked server for its changes now") for t in texts)
    assert any("changed items: Alice" in t and "account for Carol" in t for t in texts), texts[:4]
    real = changes.open_part
    monkeypatch.setattr(changes, "open_part", lambda *x: {**real(*x), "items": [{"id": 5}]})
    carol = sign_in(b, "carol")
    r = carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
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
    # N9: 60 a minute, counted before a body is read (S13.7.5.4).
    from conftest import new_client

    with new_client(server) as c:
        codes = [c.get("/link/v1/hello").status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429


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


def test_a_person_crosses_a_link_with_their_relationships_and_a_pull_names_its_link(admins):
    # S10.3: a person is one of the eight shareable kinds, and goes, read only, to named
    # people on a linked server; S11.8: a pull's Activity names the household it came from.
    a, b, ca, cb, _ = admins
    make_user(b, "carol")
    _, b_id = linked(ca, cb)
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    rose = make(
        alice, "Persn", name="Grandma Rose", sex="female", birthMonth=5, birthDay=3, private=True
    ).json()
    carol_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    r = share(alice, "person", rose["id"], users={carol_here["id"]: "read"})
    assert r.status_code == 200, r.text
    # S11.7: what flows each way, this side's by kind, owner and the people there it names.
    (out,) = links_of(ca)["links"][0]["outgoing"]
    assert (out["kind"], out["names"]) == ("person", [carol_here["displayName"]])
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    assert [x["kind"] for x in links_of(cb)["links"][0]["incoming"]] == ["person"]
    carol = sign_in(b, "carol")
    r = carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 200, r.text
    rows = carol.get(f"/ui/api/linked/{b_id}/items").json()["items"]
    assert [(r["kind"], r["name"]) for r in rows] == [("person", "Grandma Rose")]
    assert (rows[0]["row"]["birthMonth"], rows[0]["row"]["birthDay"]) == (5, 3)
    got = carol.get(
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
    make_user(b, "carol")
    _, b_id = linked(ca, cb)
    make_user(a, "alice")
    alice = sign_in(a, "alice")
    acct = make(alice, "Acct", name="Old", type="checking").json()
    carol_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    share(alice, "account", acct["id"], users={carol_here["id"]: "read"})
    words = " ".join(cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"])
    cb.post(f"/ui/api/settings/links/{b_id}/pull")  # waits in the inbox: the copy is locked
    inbox = lcopy.folder(b.config.data_dir, b_id) / "inbox"
    kept = b.config.data_dir / "kept"
    sh.copytree(inbox, kept)
    carol = sign_in(b, "carol")
    assert carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": words}).status_code == 200
    assert [r["name"] for r in carol.get(f"/ui/api/linked/{b_id}/items").json()["items"]]
    carol.post(f"/ui/api/linked/{b_id}/lock")
    for f in kept.iterdir():
        sh.copy(f, inbox / f.name)
    carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": words})
    with b.db.read(unscoped="test") as s:
        link = s.get(Link, b_id)
        assert link.needsFull and "doesn't follow the last one applied" in (link.lastError or "")


def test_a_released_copys_key_opens_nothing_more():
    # K25: the copy's database key is overwritten at the release, and no new connection opens.
    from moolakata.store.db import HeldKey, WrongKey

    k = HeldKey(bytes(range(32)))
    assert k.text().startswith("x'000102")
    k.release()
    with pytest.raises(WrongKey):
        k.text()


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


# ---------- one receipt never holds a change back (S11.4, CR3-4)


def _shared_receipt(a, ca, cb):
    """Alice on A shares an account with Carol on B, its receipts included; Carol's copy has
    its access key. Returns Alice, Carol, B's link id and the receipt's bytes."""
    from test_receipts import png

    make_user(a, "alice")
    alice = sign_in(a, "alice")
    a_id, b_id = linked(ca, cb)
    acct = make(alice, "Acct", name="Checking", type="checking").json()
    t = add(alice, acct["id"], amount="-12.50", payee="Blue Bottle")
    image = png()
    rid = alice.post(
        "/ui/api/receipts", files={"file": ("r.png", image, "application/octet-stream")}
    ).json()["id"]
    saved(attach(alice, rid, t["id"]))
    carol_here = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    words = cb.post(f"/ui/api/settings/links/{b_id}/copy-key").json()["words"]
    share(alice, "account", acct["id"], users={carol_here["id"]: "read"}, receipts={a_id: True})
    return alice, words, b_id, image


def test_a_receipt_that_cant_be_fetched_holds_nothing_back_and_comes_later(admins):
    import httpx

    from moolakata.store.entities.links import LinkFile

    a, b, ca, cb, wire = admins
    make_user(b, "carol")
    _alice, words, b_id, image = _shared_receipt(a, ca, cb)
    # Every receipt file the source sends is cut off, as one past a ceiling would be.
    wire.fail = lambda m, url, kw: httpx.ReadError("cut off") if url.endswith("/file") else None
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    carol = sign_in(b, "carol")
    assert carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)}).is_success
    # The change arrived without it: the account is there, the receipt marked not arrived.
    assert carol.get(f"/ui/api/linked/{b_id}/items").json()["items"]
    (f,) = carol.get(f"/ui/api/linked/{b_id}/files").json()["items"]
    assert f["arrived"] is False
    got = carol.get(f"/ui/api/linked/{b_id}/files/{f['id']}")
    assert got.status_code == 404 and got.json()["code"] == "not-arrived"
    link = next(x for x in links_of(cb)["links"] if x["id"] == b_id)
    assert link["lastError"] is None and link["failingSince"] is None, "the link is fine"
    with b.db.read(unscoped="test") as s:
        (row,) = s.query(LinkFile).all()
        assert row.fileName is None and row.tries == 1 and row.error
    # The next exchange asks for it again, and it reaches the open copy.
    wire.fail = None
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    (f,) = carol.get(f"/ui/api/linked/{b_id}/files").json()["items"]
    assert f["arrived"] is True
    got = carol.get(f"/ui/api/linked/{b_id}/files/{f['id']}")
    assert got.status_code == 200 and got.content == image
    with b.db.read(unscoped="test") as s:
        assert s.query(LinkFile).count() == 0


def test_a_receipt_fetched_while_the_copy_is_locked_reaches_it_at_the_unlock(admins):
    import httpx

    a, b, ca, cb, wire = admins
    make_user(b, "carol")
    _alice, words, b_id, image = _shared_receipt(a, ca, cb)
    wire.fail = lambda m, url, kw: httpx.ReadError("cut off") if url.endswith("/file") else None
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    wire.fail = None
    cb.post(f"/ui/api/settings/links/{b_id}/pull")  # fetched now, the copy still locked
    carol = sign_in(b, "carol")
    assert carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)}).is_success
    (f,) = carol.get(f"/ui/api/linked/{b_id}/files").json()["items"]
    assert f["arrived"] is True
    assert carol.get(f"/ui/api/linked/{b_id}/files/{f['id']}").content == image


def test_a_failure_after_the_exchange_call_is_recorded_on_the_link(admins):
    import httpx

    a, b, ca, cb, wire = admins
    make_user(a, "alice")
    _a_id, b_id = linked(ca, cb)
    make_user(b, "bob")
    bob = sign_in(b, "bob")
    acct = make(bob, "Acct", name="Savings", type="savings").json()
    alice_there = next(u for u in links_of(cb)["links"][0]["users"] if u["username"] == "alice")
    assert share(bob, "account", acct["id"], users={alice_there["id"]: "read"}).status_code == 200
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
    `deliver` body and a `file` answer are bounded by it sealed, and the uploads in flight hold
    one. (Statements against uploads in flight are CR3-121, not covered here yet.)"""
    from moolakata import middleware, net, settings
    from moolakata.links import sealed

    biggest = settings.RECEIPT_MAX_MB * 1024 * 1024
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
    assert mw.limit_for("/link/v1/deliver", "application/octet-stream") == sealed.max_receipt()
    assert mw.limit_for("/link/v1/deliver", "application/json") == middleware.LINK_LIMIT
    assert mw.limit_for("/ui/api/receipts", "multipart/form-data") == 1024 * 1024
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
    assert check(settings.RECEIPT_MAX_MB) == settings.RECEIPT_MAX_MB
    with pytest.raises(settings.Invalid):
        check(settings.RECEIPT_MAX_MB + 1)


def test_a_locked_copys_inbox_names_no_one(admins):
    """CR3-55, S11.9.1: what waits in a locked copy's inbox is sealed, the change's registry
    beside it too: no owner's name, item id or user id in the clear; the unlock still checks
    and applies it."""
    from moolakata.store.entities.users import User

    a, b, ca, cb, _ = admins
    make_user(b, "carol")
    alice, words, b_id, _image = _shared_receipt(a, ca, cb)
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    inbox = lcopy.folder(b.config.data_dir, b_id) / "inbox"
    files = list(inbox.iterdir())
    assert files and {f.suffix for f in files} == {".mks", ".mke"}
    acct = alice.get("/ui/api/accounts").json()["items"][0]["id"]
    with b.db.read(unscoped="test") as s:
        carol_id = s.query(User).filter(User.username == "carol").one().id
    for f in files:
        body = f.read_bytes()
        assert body.startswith(b"MKR1"), f.name
        for plain in (b"Alice", acct.encode(), carol_id.encode()):
            assert plain not in body, (f.name, plain)
    carol = sign_in(b, "carol")
    assert carol.post(f"/ui/api/linked/{b_id}/unlock", json={"words": " ".join(words)}).is_success
    assert carol.get(f"/ui/api/linked/{b_id}/items").json()["items"]
    assert not any(inbox.iterdir()), "applied"
