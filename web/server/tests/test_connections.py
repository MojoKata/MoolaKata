"""Profile › Connections and an account's sync (requirements S18.6, S18.7): a user's own
sign-ins kept by the connector, credentials sealed in the browser that MoolaKata can't open,
the account's Sync using MoolaKata Connector switch for its owner alone, and Remove."""

import pytest
from conftest import make_user, sign_in
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from edits import change, make, remove, saved, share
from test_connector import FakeConnector, pair_code

from moolakata import ids
from moolakata.connector import sealed
from moolakata.links import keys
from moolakata.store.entities.accounts import Account


@pytest.fixture
def paired(server, admin, client):
    fake = FakeConnector(server, client)
    fake.sealing_private = X25519PrivateKey.generate()
    from moolakata.connector.manage import SEALING_LABEL

    raw = fake.sealing_private.public_key().public_bytes_raw()
    r = fake.call(
        "/connector/v1/pair",
        {
            "code": pair_code(admin),
            "sealingKey": keys.b64(raw),
            "sealingSignature": keys.b64(fake.key.sign(SEALING_LABEL + raw)),
            "version": "0.1.0-test",
        },
    )
    assert r.status_code == 200, r.text
    # The admin compared the fingerprints (S18.4.3).
    assert admin.post("/ui/api/settings/connector/confirm").status_code == 200
    return fake


@pytest.fixture
def admin(server, admin_client):
    from conftest import ORIGIN

    from moolakata import settings

    with server.db.tx() as s:
        settings.put(s, "publicUrl", ORIGIN, None)
    return admin_client


def account(server, owner_id: str, name="Everyday Checking") -> str:
    with server.db.tx() as s:
        a = Account(id=ids.new_id("Acct"), ownerId=owner_id, name=name, type="checking")
        s.add(a)
        return a.id


def test_a_sealed_box_opens_only_with_the_sealing_key_and_the_connection():
    key = X25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    box = sealed.seal(b'{"username": "alice", "password": "pw"}', public, "Conn_1")
    assert sealed.looks_sealed(box)
    assert sealed.open_box(box, key, "Conn_1") == b'{"username": "alice", "password": "pw"}'
    with pytest.raises(Exception):  # noqa: B017 - any failure to open
        sealed.open_box(box, key, "Conn_2")
    with pytest.raises(Exception):  # noqa: B017
        sealed.open_box(box, X25519PrivateKey.generate(), "Conn_1")
    assert not sealed.looks_sealed("abc")


def test_anyone_can_see_whether_a_connector_is_paired(server, client, paired):
    alice = make_user(server, "alice")
    c = sign_in(server, "alice")
    info = c.get("/ui/api/connector").json()
    assert info["paired"] is True and info["sealingKey"] and info["fingerprint"]
    assert alice


def test_a_user_makes_a_connection_seals_credentials_and_the_connector_collects_them(
    server, paired
):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    r = make(c, "Conn", driver="schwab", label="My Schwab login", settings={"appKey": "k1"})
    assert r.status_code == 200, r.text
    made = r.json()
    cid = made["id"]
    assert made["state"] == "new" and made["driver"] == "schwab"
    # The same name twice, an unknown driver and missing settings are refused at their field.
    r = make(c, "Conn", driver="schwab", label="My Schwab login", settings={"appKey": "k1"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "label"
    r = make(c, "Conn", driver="plaid", label="x")
    assert r.json()["errors"][0]["field"] == "driver"
    r = make(c, "Conn", driver="ofx-direct", label="CU")
    assert r.json()["errors"][0]["field"] == "settings.url"
    # The credential, sealed to the connector's key, is kept as it is and handed over.
    public = keys.unb64(c.get("/ui/api/connector").json()["sealingKey"])
    box = sealed.seal(b'{"code": "oauth-code"}', public, cid)
    r = c.post(f"/ui/api/profile/connections/{cid}/credential", json={"sealed": box})
    assert r.status_code == 200 and r.json()["credentialWaiting"] is True
    r = c.post(f"/ui/api/profile/connections/{cid}/credential", json={"sealed": "nope"})
    assert r.status_code == 422
    # A locked connector can't open a box (its sealing key is in the vault), so it is not
    # handed one; an unlocked one is (protocol §4.2).
    out = paired.call("/connector/v1/report", {"locked": True, "connections": []}).json()
    assert out["connections"][0]["sealed"] is None
    out = paired.call("/connector/v1/report", {"locked": False, "connections": []}).json()
    (conn,) = out["connections"]
    assert conn["id"] == cid and conn["settings"] == {"appKey": "k1"}
    assert sealed.open_box(conn["sealed"]["ciphertext"], paired.sealing_private, cid) == (
        b'{"code": "oauth-code"}'
    )
    # MoolaKata never shows it back, and it never reaches Activity.
    mine = c.get("/ui/api/profile/connections").json()["items"]
    assert "sealed" not in str(mine) and mine[0]["credentialWaiting"] is True
    acts = c.get("/ui/api/activity").json()
    assert "oauth-code" not in str(acts) and box not in str(acts)
    # Taken, naming the box: it is gone.
    taken = {"sealedAt": conn["sealed"]["sealedAt"]}
    r = paired.call(f"/connector/v1/connections/{cid}/credential/taken", taken)
    assert r.status_code == 200
    assert c.get("/ui/api/profile/connections").json()["items"][0]["credentialWaiting"] is False
    # Change the label and settings; versions apply.
    was = c.get("/ui/api/profile/connections").json()["items"][0]
    now = saved(change(c, "Conn", was, label="Schwab", settings={"appKey": "k2"}))
    assert now["label"] == "Schwab"
    assert change(c, "Conn", was, label="x").status_code == 412
    r = change(c, "Conn", now, driver="ofx-direct")
    assert r.json()["errors"][0]["code"] == "driver-fixed"


def test_only_the_owner_turns_an_accounts_sync_on_naming_their_own_connection(server, paired):
    make_user(server, "alice")
    make_user(server, "bob")
    alice, bob = sign_in(server, "alice"), sign_in(server, "bob")
    cid = make(
        alice,
        "Conn",
        driver="ofx-direct",
        label="Credit union",
        settings={
            "url": "https://ofx.cu.example/ofx",
            "org": "CU",
            "fid": "1",
            "accountType": "CHECKING",
            "accountId": "4417",
        },
    ).json()["id"]
    bobs = make(
        bob,
        "Conn",
        driver="ofx-direct",
        label="Credit union",
        settings={
            "url": "https://ofx.cu.example/ofx",
            "org": "CU",
            "fid": "1",
            "accountType": "CHECKING",
            "accountId": "4417",
        },
    ).json()["id"]
    aid = account(server, alice.get("/ui/api/session").json()["user"]["id"])
    a = alice.get(f"/ui/api/accounts/{aid}").json()
    assert a["connectionId"] is None
    # Bob's connection can't be named, nor one without the institution account.
    r = change(alice, "Acct", a, connectionId=bobs, syncAccount="x")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "connectionId"
    r = change(alice, "Acct", a, connectionId=cid)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "syncAccount"
    out = saved(change(alice, "Acct", a, connectionId=cid, syncAccount="Checking ••4417"))
    assert out["connectionId"] == cid and out["syncAccount"] == "Checking ••4417"
    # The connector's report answer names the account.
    out = paired.call("/connector/v1/report", {"locked": False, "connections": []}).json()
    mine = next(x for x in out["connections"] if x["id"] == cid)
    assert mine["accounts"][0]["id"] == aid
    # A write share doesn't see or change it (S18.6.2).
    bob_id = bob.get("/ui/api/session").json()["user"]["id"]
    r = share(alice, "account", aid, users={bob_id: "write"})
    assert r.status_code == 200, r.text
    shown = bob.get(f"/ui/api/accounts/{aid}").json()
    assert shown["connectionId"] is None and shown["syncAccount"] is None
    r = change(bob, "Acct", shown, connectionId=None, syncAccount="y")
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "owner-only"
    # Remove turns the sync off and the connector is told.
    r = remove(alice, "Conn", alice.get("/ui/api/profile/connections").json()["items"][0])
    assert r.status_code == 200, r.text
    assert alice.get(f"/ui/api/accounts/{aid}").json()["connectionId"] is None
    assert alice.get("/ui/api/profile/connections").json()["items"] == []
    out = paired.call("/connector/v1/report", {"locked": False, "connections": []}).json()
    assert cid in out["removed"] and all(x["id"] != cid for x in out["connections"])


def test_a_watched_folder_is_no_driver(server, paired):
    """S18.9: what nothing can fetch is downloaded and uploaded by its owner, never watched in
    a folder on the server."""
    make_user(server, "alice")
    c = sign_in(server, "alice")
    r = make(c, "Conn", driver="folder", label="Downloads", settings={"path": "in"})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "driver-invalid"


def test_a_connection_needs_a_paired_connector(server, admin_client):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    assert c.get("/ui/api/connector").json()["paired"] is False
    r = make(
        c,
        "Conn",
        driver="ofx-direct",
        label="Credit union",
        settings={
            "url": "https://ofx.cu.example/ofx",
            "org": "CU",
            "fid": "1",
            "accountType": "CHECKING",
            "accountId": "4417",
        },
    )
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "no-connector"


def test_an_ofx_connection_may_name_how_many_days_back_each_run_asks_for(server, paired):
    """CR3-140: `days` is one of OFX Direct Connect's settings (protocol §6, S18.9.1)."""
    make_user(server, "alice")
    c = sign_in(server, "alice")
    base = {
        "url": "https://ofx.cu.example/ofx",
        "org": "CU",
        "fid": "1",
        "accountType": "CHECKING",
        "accountId": "4417",
    }
    for days in (0, 91, "many", True):
        r = make(c, "Conn", driver="ofx-direct", label="CU", settings={**base, "days": days})
        assert r.json()["errors"][0]["field"] == "settings.days", days
    made = make(c, "Conn", driver="ofx-direct", label="CU", settings={**base, "days": 30}).json()
    out = paired.call("/connector/v1/report", {"locked": False, "connections": []}).json()
    (conn,) = [x for x in out["connections"] if x["id"] == made["id"]]
    assert conn["settings"]["days"] == 30
    other = make(c, "Conn", driver="ofx-direct", label="CU 2", settings=base).json()
    out = paired.call("/connector/v1/report", {"locked": False, "connections": []}).json()
    (conn,) = [x for x in out["connections"] if x["id"] == other["id"]]
    assert "days" not in conn["settings"]
